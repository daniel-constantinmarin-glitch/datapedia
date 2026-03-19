import os
import json
import requests
import google.auth
from google.auth.transport.requests import Request
import re


# -----------------------------
# Helpers
# -----------------------------
_SQL_KW = {
    'select','from','where','join','on','left','right','inner','outer','group','by','order','limit',
    'and','or','not','as','case','when','then','else','end','distinct','having','union','all','into',
    'is','null','asc','desc','over','partition','rows','range','with','exists','in','like','between'
}

def _clean_ident(s: str) -> str:
    """Remove quotes/backticks/brackets and return last part after dot (schema.table -> table)."""
    if not s:
        return ""
    s = s.strip()
    # strip quotes
    if (s.startswith("`") and s.endswith("`")) or (s.startswith('"') and s.endswith('"')) or (s.startswith("[") and s.endswith("]")):
        s = s[1:-1]
    # if qualified, keep last token
    parts = [p for p in re.split(r"\.", s) if p]
    return parts[-1] if parts else s


# -----------------------------
# Schema summarizer
# -----------------------------
def build_schema_summary(schema: dict) -> str:
    lines = []
    for table in schema.get("tables", []):
        table_name = table.get("id") or table.get("name")
        cols = table.get("columns", [])
        col_list = [c.get("name", "?") for c in cols]
        lines.append(f"{table_name}: {', '.join(col_list)}")
    return "\n".join(lines)


# -----------------------------
# SQL generation (Vertex AI)
# -----------------------------
def generate_sql(prompt: str, schema: dict) -> str:
    # 1. Token using VM service account
    try:
        creds, _ = google.auth.default()
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        return f"-- ERROR while obtaining access token: {e}"

    # 2. Required env vars
    project_id = os.getenv("VERTEX_PROJECT_ID", "datapedia-489407")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    model = os.getenv("VERTEX_MODEL", "gemini-2.5-pro")

    if not project_id or not location:
        return (
            "-- ERROR: Missing environment variables.\n"
            "Set VERTEX_PROJECT_ID, VERTEX_LOCATION."
        )

    # 3. REST endpoint
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/"
        f"publishers/google/models/{model}:generateContent"
    )

    schema_str = build_schema_summary(schema)

    system_rules = (
        "You are an expert SQL generator.\n"
        "Rules:\n"
        "1. Use ONLY tables/columns from schema.\n"
        "2. NEVER invent names.\n"
        "3. Output ONLY SQL.\n"
        "4. If impossible → output: NO_DATA.\n"
    )

    final_prompt = (
        f"{system_rules}\n\n"
        f"SCHEMA:\n{schema_str}\n\n"
        f"USER REQUEST:\n{prompt}\n"
    )

    body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": final_prompt}]
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(url, headers=headers, data=json.dumps(body), timeout=60)
        r.raise_for_status()
        response = r.json()
        text = response["candidates"][0]["content"]["parts"][0].get("text", "").strip()

        if not text:
            return "-- ERROR: Empty response from Vertex AI."
        if "NO_DATA" in text.upper():
            return "NO_DATA"
        return text

    except Exception as e:
        return f"-- ERROR calling Vertex AI: {e}\nRAW RESPONSE: {r.text if 'r' in locals() else ''}"


def optimize_sql(query: str, schema: dict) -> str:
    try:
        creds, _ = google.auth.default()
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        return f"-- ERROR while obtaining access token: {e}"

    project_id = os.getenv("VERTEX_PROJECT_ID", "datapedia-489407")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    model = os.getenv("VERTEX_MODEL", "gemini-2.5-pro")

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/"
        f"publishers/google/models/{model}:generateContent"
    )

    schema_str = build_schema_summary(schema)

    system_rules = (
        "You are an expert SQL optimizer.\n"
        "Optimize the SQL query WITHOUT changing the output.\n"
        "Rules:\n"
        "1. Do NOT change the meaning or returned rows.\n"
        "2. Use only tables/columns present in schema.\n"
        "3. Simplify joins, remove redundancies, push filters down, rewrite subqueries\n"
        "4. Output ONLY SQL.\n"
        "5. If optimization is impossible, return the original SQL.\n"
    )

    final_prompt = (
        f"{system_rules}\n\n"
        f"SCHEMA:\n{schema_str}\n\n"
        f"SQL TO OPTIMIZE:\n{query}\n"
    )

    body = {
        "contents": [{"role": "user", "parts": [{"text": final_prompt}]}]
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        r = requests.post(url, headers=headers, data=json.dumps(body), timeout=60)
        r.raise_for_status()
        response = r.json()
        text = response["candidates"][0]["content"]["parts"][0].get("text", "").strip()
        if not text:
            return query  # fallback
        return text
    except Exception as e:
        return f"-- ERROR calling Vertex AI: {e}"


# -----------------------------
# Field extractor (enhanced)
# -----------------------------
def extract_fields_from_query(query: str, schema: dict) -> dict:
    """
    Extract tables and columns used by the query.
    Supports: aliases (t.col, t.*), SELECT * (global & per-table), quoted/qualified identifiers,
              and unqualified columns mapped uniquely across detected tables.
    Returns:
        {
            "tables": [table1, table2, ...],
            "columns": { "table1": [colA, colB], ... }
        }
    """
    # Build schema maps
    tables_in_schema = {}
    col_index = {}  # col_name -> set(tables that have it)
    for t in schema.get("tables", []):
        tname = (t.get("id") or t.get("name"))
        if not tname:
            continue
        cols = [c.get("name") for c in t.get("columns", []) if c.get("name")]
        tables_in_schema[tname] = cols
        for c in cols:
            col_index.setdefault(c, set()).add(tname)

    # Normalize whitespace to ease regex
    q = " ".join(query.replace("\n", " ").split())

    # Detect FROM/JOIN tables + aliases
    alias_map = {}        # alias -> base_table
    detected_tables = []  # keep order of appearance
    tbl_pat = r"(?:FROM|JOIN)\s+((?:`[^`]+`|\"[^\"]+\"|\[[^\]]+\]|[a-zA-Z0-9_\.])+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_`\"\[\]]+))?"
    for base_tbl_raw, alias_raw in re.findall(tbl_pat, q, flags=re.IGNORECASE):
        base = _clean_ident(base_tbl_raw)
        alias = _clean_ident(alias_raw) if alias_raw else None
        if base in tables_in_schema and base not in detected_tables:
            detected_tables.append(base)
        if alias and alias.lower() != base.lower():
            alias_map[_clean_ident(alias)] = base

    # SELECT list (to detect global star or t.* quickly)
    sel_match = re.search(r"select\s+(.*?)\s+from\s", q, flags=re.IGNORECASE | re.S)
    select_clause = sel_match.group(1) if sel_match else ""

    has_global_star = bool(re.search(r"(^|\s)\*(\s|$|,)", select_clause))
    star_owners = set()  # tables that have t.* explicitly
    for owner in re.findall(r"([a-zA-Z0-9_`\"\[\]]+)\s*\.\s*\*", select_clause):
        owner_clean = _clean_ident(owner)
        owner_table = alias_map.get(owner_clean, owner_clean)
        if owner_table in tables_in_schema:
            star_owners.add(owner_table)

    # Qualified columns t.col
    detected_columns = {}
    for tbl_or_alias, col in re.findall(r"([a-zA-Z0-9_`\"\[\]]+)\s*\.\s*([a-zA-Z0-9_`\"\[\]]+)", q):
        col_clean = _clean_ident(col)
        if col_clean == "*":
            continue
        tbl_clean = _clean_ident(tbl_or_alias)
        actual_tbl = alias_map.get(tbl_clean, tbl_clean)
        if actual_tbl in tables_in_schema and col_clean in tables_in_schema[actual_tbl]:
            detected_columns.setdefault(actual_tbl, []).append(col_clean)

    # Unqualified columns: atribuie dacă numele este unic printre tabelele detectate
    # (sau, dacă avem o singură masă, le atribuim ei).
    unq_tokens = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", select_clause))
    unq_tokens = {t for t in unq_tokens if t.lower() not in _SQL_KW}
    if len(detected_tables) == 1:
        only_tbl = detected_tables[0]
        for tok in unq_tokens:
            if tok in tables_in_schema[only_tbl]:
                detected_columns.setdefault(only_tbl, []).append(tok)
    elif len(detected_tables) > 1:
        for tok in unq_tokens:
            owners = [t for t in detected_tables if tok in tables_in_schema.get(t, [])]
            if len(owners) == 1:
                detected_columns.setdefault(owners[0], []).append(tok)

    # Expand stars
    if has_global_star:
        for t in detected_tables:
            for c in tables_in_schema[t]:
                detected_columns.setdefault(t, []).append(c)
    if star_owners:
        for t in star_owners:
            for c in tables_in_schema[t]:
                detected_columns.setdefault(t, []).append(c)

    # Dedup + sort
    for t in list(detected_columns.keys()):
        detected_columns[t] = sorted(set(detected_columns[t]))

    return {
        "tables": detected_tables,
        "columns": detected_columns
    }
