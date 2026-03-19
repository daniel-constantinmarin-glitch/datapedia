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
    Robust SQL table & column extractor.
    Handles:
      - FROM / JOIN on multiple lines
      - CTEs (WITH ... AS)
      - Subqueries
      - Aliases (with and without AS)
      - SELECT *
      - t.*
      - schema.table and db.schema.table
    """

    # -----------------------------------------------------
    # Build schema map
    # -----------------------------------------------------
    tables_in_schema = {}
    col_index = {}

    for t in schema.get("tables", []):
        tname = (t.get("id") or t.get("name"))
        if not tname:
            continue
        cols = [c.get("name") for c in t.get("columns", []) if c.get("name")]
        tables_in_schema[tname] = cols
        for c in cols:
            col_index.setdefault(c, set()).add(tname)

    # Normalize query
    q = query.replace("\n", " ").replace("\t", " ")
    q = " ".join(q.split())

    # -----------------------------------------------------
    # Detect tables (FROM + JOIN + WITH CTE)
    # -----------------------------------------------------
    detected_tables = []
    alias_map = {}

    # All patterns that may contain tables:
    table_patterns = [
        r"(?:FROM|JOIN)\s+([a-zA-Z0-9_\.\`\"\[\]]+)(?:\s+(?:AS\s+)?([a-zA-Z0-9_]+))?",
        r"WITH\s+([a-zA-Z0-9_]+)\s+AS\s*\(",
        r"FROM\s+\(\s*SELECT.*?FROM\s+([a-zA-Z0-9_\.\`\"\[\]]+)"
    ]

    import re

    for pat in table_patterns:
        for base_raw, alias_raw in re.findall(pat, q, flags=re.IGNORECASE):
            base = base_raw.strip("`[]\"").split(".")[-1]
            alias = alias_raw.strip("`[]\"") if alias_raw else None

            if base in tables_in_schema:
                if base not in detected_tables:
                    detected_tables.append(base)
            if alias and alias.lower() != base.lower():
                alias_map[alias] = base

    # -----------------------------------------------------
    # Detect SELECT clause
    # -----------------------------------------------------
    select_m = re.search(r"select\s+(.*?)\s+from\s", q, flags=re.IGNORECASE)
    select_clause = select_m.group(1) if select_m else ""

    has_global_star = "*" in select_clause

    star_owners = set()
    for owner in re.findall(r"([a-zA-Z0-9_]+)\s*\.\s*\*", select_clause):
        owner = owner.strip()
        tbl = alias_map.get(owner, owner)
        if tbl in tables_in_schema:
            star_owners.add(tbl)

    # -----------------------------------------------------
    # Detect qualified t.col
    # -----------------------------------------------------
    detected_columns = {}
    for tbl_or_alias, col in re.findall(r"([a-zA-Z0-9_]+)\s*\.\s*([a-zA-Z0-9_]+)", q):
        if col == "*":
            continue
        tbl = alias_map.get(tbl_or_alias, tbl_or_alias)
        if tbl in tables_in_schema and col in tables_in_schema[tbl]:
            detected_columns.setdefault(tbl, []).append(col)

    # -----------------------------------------------------
    # Unqualified columns (unique by schema)
    # -----------------------------------------------------
    tokens = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", select_clause))
    tokens = {t for t in tokens if t.lower() not in 
              {'select','from','where','join','on','as','and','or','case','when','then','else',
               'end','distinct','limit','group','order','by','left','right','inner','outer','asc','desc'}}

    if len(detected_tables) == 1:
        tbl = detected_tables[0]
        for t in tokens:
            if t in tables_in_schema[tbl]:
                detected_columns.setdefault(tbl, []).append(t)
    else:
        for t in tokens:
            owners = [tbl for tbl in detected_tables if t in tables_in_schema.get(tbl, [])]
            if len(owners) == 1:
                detected_columns.setdefault(owners[0], []).append(t)

    # -----------------------------------------------------
    # Expand SELECT *
    # -----------------------------------------------------
    if has_global_star:
        for tbl in detected_tables:
            for c in tables_in_schema[tbl]:
                detected_columns.setdefault(tbl, []).append(c)

    # t.*
    for tbl in star_owners:
        for c in tables_in_schema[tbl]:
            detected_columns.setdefault(tbl, []).append(c)

    # Deduplicate + sort
    for tbl in detected_columns:
        detected_columns[tbl] = sorted(set(detected_columns[tbl]))

    return {
        "tables": detected_tables,
        "columns": detected_columns
    }
