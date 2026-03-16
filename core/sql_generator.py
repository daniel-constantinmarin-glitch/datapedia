import os
import json
import requests
import google.auth
from google.auth.transport.requests import Request


def build_schema_summary(schema: dict) -> str:
    lines = []
    for table in schema.get("tables", []):
        table_name = table.get("id") or table.get("name")
        cols = table.get("columns", [])
        col_list = [c.get("name", "?") for c in cols]
        lines.append(f"{table_name}: {', '.join(col_list)}")
    return "\n".join(lines)


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
            {"parts": [{"text": final_prompt}]}
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
