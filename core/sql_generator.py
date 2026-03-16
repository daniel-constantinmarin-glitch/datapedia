import os
import json
import requests
import google.auth
from google.auth.transport.requests import Request


def build_schema_summary(schema: dict) -> str:
    """
    Converts the schema JSON into a readable list of tables + columns.
    """
    lines = []
    for table in schema.get("tables", []):
        table_name = table.get("id") or table.get("name") or "unknown"
        cols = table.get("columns", [])
        col_list = [c.get("name", "?") for c in cols]
        lines.append(f"{table_name}: {', '.join(col_list)}")
    return "\n".join(lines)


def generate_sql(prompt: str, schema: dict) -> str:
    """
    Generates SQL using Vertex AI Gemini 2.5 Pro (REST API).

    This implementation:

    - DOES NOT use the Python vertexai SDK (which breaks on Compute Engine + Streamlit)
    - DOES NOT call any pathway that touches `request.session`
    - ONLY uses REST calls with OAuth2 identity tokens
    - WORKS 100% on Compute Engine with service account authentication
    """

    # -----------------------------
    # 1. Load credentials (Compute Engine default)
    # -----------------------------
    try:
        creds, _ = google.auth.default()
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        return f"-- ERROR while obtaining access token: {e}"

    # -----------------------------
    # 2. Read required environment variables
    # -----------------------------
    project_id = os.getenv("VERTEX_PROJECT_ID")
    location = os.getenv("VERTEX_LOCATION")

    if not project_id or not location:
        return (
            "-- ERROR: Missing environment variables.\n"
            "Please set VERTEX_PROJECT_ID and VERTEX_LOCATION."
        )

    # -----------------------------
    # 3. Build Vertex API REST endpoint
    # -----------------------------
    model = "gemini-2.5-pro"

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/"
        f"projects/{project_id}/locations/{location}/"
        f"publishers/google/models/{model}:generateContent"
    )

    # -----------------------------
    # 4. Prepare schema summary for prompt
    # -----------------------------
    schema_str = build_schema_summary(schema)

    system_rules = (
        "You are an expert SQL generator.\n"
        "You ALWAYS follow these rules strictly:\n"
        "1. Use ONLY tables and columns that exist in the schema.\n"
        "2. NEVER invent table names or column names.\n"
        "3. Output ONLY SQL — no explanation.\n"
        "4. If the request cannot be answered, output exactly: NO_DATA.\n"
    )

    final_prompt = (
        f"{system_rules}\n\n"
        f"SCHEMA:\n{schema_str}\n\n"
        f"USER REQUEST:\n{prompt}\n"
    )

    body = {
        "contents": [
            {
                "parts": [
                    {"text": final_prompt}
                ]
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # -----------------------------
    # 5. Call REST API
    # -----------------------------
    try:
        r = requests.post(url, headers=headers, data=json.dumps(body))
        r.raise_for_status()

        response = r.json()

        text = (
            response["candidates"][0]["content"]["parts"][0].get("text")
        ).strip()

        if not text:
            return "-- ERROR: Empty response from Vertex AI."

        # Honor NO_DATA rule
        if "NO_DATA" in text.upper():
            return "NO_DATA"

        return text

    except Exception as e:
        return (
            f"-- ERROR calling Vertex AI REST API: {e}\n"
            f"-- RAW RESPONSE: {r.text if 'r' in locals() else ''}"
        )

