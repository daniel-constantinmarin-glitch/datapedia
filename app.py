import streamlit as st
import os
import json
import requests

from core.graph_builder import render_table_neighborhood
from core.schema_loader import load_schema
from core.sql_generator import generate_sql, optimize_sql, extract_fields_from_query
from core.project_store import list_projects, load_project, save_project
from core.procedure_analyzer import explain_procedure

# RAG helpers
from core.rag_store import save_rag_files, list_rag_files, delete_rag_file, build_rag_context

st.set_page_config(page_title='Datapedia', layout='wide')


st.markdown("""
    <style>
    /* Stil pentru toate st.button */
    div.stButton > button {
        background-color: #ff6600;
        color: white;
        border-radius: 6px;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        border: none;
    }

    div.stButton > button:hover {
        background-color: #e65c00;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)


st.markdown("""
    <style>
    /* NAVBAR Streamlit */
    header[data-testid="stHeader"] {
        background-color: #ff6600 !important;
        height: 70px;
    }

    /* Eliminăm paddingurile interne ale header-ului */
    header[data-testid="stHeader"] > div:first-child {
        padding-top: 0px !important;
    }

    /* LOGO în navbar */
    .navbar-logo {
        position: absolute;
        top: 10px;          /* ajustează vertical */
        left: 20px;         /* ajustează orizontal */
        height: 50px;
        z-index: 9999;
    }

    </style>

    <!-- Inserăm imaginea în header prin poziționare absolută -->
    <img class="navbar-logo" src="static/datapedia_logo.png" height="50">
""", unsafe_allow_html=True)


# =============================================================================
# Data Firewall / LLM Proxy helpers (client HTTP inlined in this file)
# =============================================================================

DEFAULT_PROXY_TIMEOUT = (5, 30)  # connect, read

def _proxy_read_info(schema_path: str) -> dict:
    """
    Load Data Firewall settings (url, token) from proxy.json located
    in the same folder as the project's schema file.
    Falls back to env vars SAFE_PROXY_URL / SAFE_PROXY_TOKEN.
    """
    info = {"url": None, "token": None}
    if schema_path:
        folder = os.path.dirname(schema_path)
        proxy_path = os.path.join(folder, "proxy.json")
        if os.path.isfile(proxy_path):
            try:
                with open(proxy_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    info["url"] = data.get("url")
                    info["token"] = data.get("token")
            except Exception:
                pass

    if not info["url"]:
        info["url"] = os.getenv("SAFE_PROXY_URL")
    if not info["token"]:
        info["token"] = os.getenv("SAFE_PROXY_TOKEN")
    return info

def _proxy_save_info(schema_path: str, url: str, token: str|None) -> str:
    """
    Write proxy.json next to the schema file.
    """
    folder = os.path.dirname(schema_path)
    os.makedirs(folder, exist_ok=True)
    proxy_path = os.path.join(folder, "proxy.json")
    with open(proxy_path, "w", encoding="utf-8") as f:
        json.dump({"url": url, "token": (token or None)}, f, indent=2)
    return proxy_path

def _proxy_headers(token: str|None) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _proxy_endpoint(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path

def _proxy_post(schema_path: str, endpoint: str, payload: dict, timeout=DEFAULT_PROXY_TIMEOUT) -> dict:
    info = _proxy_read_info(schema_path)
    if not info["url"]:
        return {"ok": False, "error": "No Data Firewall URL configured for this project."}
    try:
        url = _proxy_endpoint(info["url"], endpoint)
        r = requests.post(url, headers=_proxy_headers(info["token"]), json=payload, timeout=timeout)
        if not r.ok:
            return {"ok": False, "error": r.text}
        data = r.json()
        data["ok"] = True
        return data
    except Exception as e:
        return {"ok": False, "error": str(e)}

def proxy_validate_sql(schema_path: str, sql: str) -> dict:
    return _proxy_post(schema_path, "/validate_sql", {"sql": sql})

def proxy_explain_sql(schema_path: str, sql: str) -> dict:
    return _proxy_post(schema_path, "/explain_sql", {"sql": sql})

def proxy_safe_query(schema_path: str, sql: str) -> dict:
    return _proxy_post(schema_path, "/safe_query", {"sql": sql})

# -----------------------------
# Session state
# -----------------------------
if "last_sql" not in st.session_state:
    st.session_state["last_sql"] = ""
if "last_optimized_sql" not in st.session_state:
    st.session_state["last_optimized_sql"] = ""


st.markdown("""
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@600;700&display=swap" rel="stylesheet">

    <style>
        .app-title {
            font-family: 'Poppins', sans-serif;
            font-size: 36px;
            font-weight: 700;
            color: #ff6600;
            padding: 15px 0 5px 0;
        }
    </style>

    <div class="app-title">Datapedia</div>
""", unsafe_allow_html=True)



# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Onboarding",
    "Project Browser",
    "SQL Generator",
    "Graph View",
    "Procedure Analyzer"
])

# ------------------------------------------------------
# 1. ONBOARDING TAB
# ------------------------------------------------------
with tab1:
    st.header("Project Onboarding")
    upload = st.file_uploader("Upload JSON schema (max 5MB)", type=["json"], key="onb_upload")
    name = st.text_input("Project name", key="onb_name")

    # NEW: Data Firewall settings (optional, recommended)
    st.subheader("Data Firewall (optional, recommended)")
    df_col1, df_col2 = st.columns(2)
    with df_col1:
        proxy_url = st.text_input("Proxy URL (internal)", placeholder="http://10.128.0.7:9000", key="onb_proxy_url")
    with df_col2:
        proxy_token = st.text_input("Proxy Token (optional)", type="password", key="onb_proxy_token")

    create_btn = st.button("Create project", key="onb_create_btn")
    if create_btn:
        if not upload or not name:
            st.error("Please provide both a JSON schema and a project name.")
        elif upload.size > 5 * 1024 * 1024:
            st.error("File is too large. Max size is 5MB.")
        else:
            base = "/home/daniel_constantin_marin_ing_com"  # keep your base path
            folder = os.path.join(base, name)
            try:
                os.makedirs(folder, exist_ok=True)
                path = os.path.join(folder, upload.name)
                with open(path, "wb") as f:
                    f.write(upload.getbuffer())
                save_project(name, path)

                # Save Data Firewall settings per project (proxy.json)
                if proxy_url.strip():
                    ppath = _proxy_save_info(path, proxy_url.strip(), proxy_token.strip() if proxy_token else None)
                    st.success(f"Project created and Data Firewall configured: {ppath}")
                else:
                    st.success("Project created successfully (no Data Firewall configured).")

            except Exception as e:
                st.error(f"Error saving project: {e}")

# ------------------------------------------------------
# 2. PROJECT BROWSER TAB
# ------------------------------------------------------
with tab2:
    st.header("Project Browser")
    projs = list_projects()
    if not projs:
        st.info("No projects found. Please create one in the Onboarding tab.")
    else:
        selected_proj = st.selectbox("Select project", [p.get("name", "") for p in projs], key="browse_proj")
        if selected_proj:
            proj = load_project(selected_proj)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}

            # list of tables (id/name)
            tables_raw = schema.get("tables", [])
            def _tbl_name(t):
                return t.get("id") or t.get("name") or "<unnamed>"
            tables = sorted({_tbl_name(t) for t in tables_raw})

            selected_table = st.selectbox("Select table", tables, key="browse_table")
            if selected_table:
                table = next((t for t in tables_raw if _tbl_name(t) == selected_table), None)
                if table:
                    st.subheader(f"Columns & Types — {selected_table}")
                    import pandas as pd
                    rows = []
                    for c in table.get("columns", []):
                        rows.append({
                            "column": c.get("name", "?"),
                            "type": c.get("type") or c.get("data_type") or "",
                            "nullable": c.get("nullable"),
                            "pk": c.get("pk") or c.get("primary_key"),
                            "unique": c.get("unique"),
                            "default": c.get("default"),
                        })
                    df = pd.DataFrame(rows, columns=["column", "type", "nullable", "pk", "unique", "default"])
                    if not df.empty:
                        df["pk"] = df["pk"].astype("boolean").fillna(False)
                        df["nullable"] = df["nullable"].astype("boolean").fillna(False)
                        pk_cols = int(df["pk"].sum())
                        nullable_cols = int(df["nullable"].sum())
                    else:
                        pk_cols = 0
                        nullable_cols = 0
                    st.dataframe(df, width="stretch", hide_index=True)
                    st.caption(f"Columns: **{len(df)}** · PK: **{pk_cols}** · Nullable: **{nullable_cols}**")

                    st.subheader("Table Neighborhood (FK links)")
                    render_table_neighborhood(schema, selected_table, height=760)
                else:
                    st.warning("Selected table not found in schema.")

            # -------- RAG knowledge per project --------
            st.subheader("RAG Knowledge (optional)")
            schema_path = proj.get("schema", "")

            rag_files = st.file_uploader(
                "Upload RAG files (.txt, .sql)",
                type=["txt", "sql"],
                accept_multiple_files=True,
                key="rag_upload"
            )
            if rag_files:
                saved = save_rag_files(schema_path, rag_files)
                if saved:
                    st.success(f"Saved {len(saved)} file(s) to the project's RAG folder.")

            existing = list_rag_files(schema_path)
            if not existing:
                st.info("No RAG files for this project. The AI will use only the JSON schema.")
            else:
                import pandas as pd
                st.write("Existing RAG files:")
                df_rag = pd.DataFrame(
                    [{"file": e["name"], "size_bytes": e["size"]} for e in existing],
                    columns=["file", "size_bytes"]
                )
                st.dataframe(df_rag, width="stretch", hide_index=True)

                # Delete controls
                for e in existing:
                    c1, c2 = st.columns([0.8, 0.2])
                    with c1:
                        st.caption(e["name"])
                    with c2:
                        if st.button("Delete", key=f"del_rag_{e['name']}"):
                            ok = delete_rag_file(schema_path, e["name"])
                            if ok:
                                st.success(f"Deleted: {e['name']}")
                                st.experimental_rerun()
                            else:
                                st.error("Delete failed.")

            # -------- Data Firewall settings per project --------
            st.subheader("Data Firewall (per project)")

            info = _proxy_read_info(schema_path)
            dfcol1, dfcol2 = st.columns(2)
            with dfcol1:
                edit_proxy_url = st.text_input("Proxy URL (internal)", value=(info["url"] or ""), placeholder="http://10.128.0.7:9000", key="edit_proxy_url")
            with dfcol2:
                edit_proxy_token = st.text_input("Proxy Token (optional)", value=(info["token"] or ""), type="password", key="edit_proxy_token")

            if st.button("Save Data Firewall settings", key="btn_save_proxy"):
                if not schema_path:
                    st.error("This project has no schema path.")
                elif not edit_proxy_url.strip():
                    st.error("Proxy URL cannot be empty.")
                else:
                    ppath = _proxy_save_info(schema_path, edit_proxy_url.strip(), edit_proxy_token.strip() if edit_proxy_token else None)
                    st.success(f"Saved: {ppath}")

# ------------------------------------------------------
# 3. SQL GENERATOR TAB
# ------------------------------------------------------
with tab3:
    st.header("SQL Generator")
    projs = list_projects()
    if not projs:
        st.info("No projects found. Please create one in the Onboarding tab.")
    else:
        selected_proj_sql = st.selectbox("Select project", [p.get("name", "") for p in projs], key="sql_proj")
        st.caption("Vertex AI uses environment variables VERTEX_PROJECT_ID / VERTEX_LOCATION / VERTEX_MODEL.")

        # Generate
        prompt = st.text_area("Describe your query in English", key="sql_prompt")
        gen_btn = st.button("Generate SQL", key="sql_btn")
        if gen_btn and selected_proj_sql:
            proj = load_project(selected_proj_sql)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            schema_path = proj.get("schema", "")
            rag_ctx = build_rag_context(schema_path, prompt or "", max_chars=8000, k=6)
            result_sql = generate_sql(prompt, schema, rag_context=rag_ctx)
            st.session_state["last_sql"] = result_sql

        if st.session_state.get("last_sql"):
            st.subheader("Last generated SQL")
            st.code(st.session_state["last_sql"], language="sql")

            # NEW: Data Firewall actions
            proj = load_project(selected_proj_sql)
            schema_path = proj.get("schema", "")

            c1, c2, c3 = st.columns(3)
            sql_current = st.session_state.get("last_sql", "").strip()

            with c1:
                if st.button("Validate (Firewall)", key="btn_val"):
                    resp = proxy_validate_sql(schema_path, sql_current)
                    if not resp.get("ok"):
                        st.error(resp.get("error", "Validation error"))
                    else:
                        st.success("SQL validated successfully under policy.")
                        st.json(resp)

            with c2:
                if st.button("Explain (Firewall)", key="btn_explain"):
                    resp = proxy_explain_sql(schema_path, sql_current)
                    if not resp.get("ok"):
                        st.error(resp.get("error", "Explain error"))
                    else:
                        st.json(resp)

            with c3:
                if st.button("Run via Data Firewall", key="btn_run"):
                    resp = proxy_safe_query(schema_path, sql_current)
                    if not resp.get("ok"):
                        st.error(resp.get("error", "Execution error"))
                    else:
                        st.success(f"Rows: {resp.get('row_count', 0)}")
                        import pandas as pd
                        rows = resp.get("rows", [])
                        if rows:
                            df = pd.DataFrame(rows)
                            st.dataframe(df, use_container_width=True)
                        st.caption("Executed SQL (with enforced limit):")
                        st.code(resp.get("executed_sql", ""), language="sql")

        # Show fields (generated)
        show_fields_btn = st.button("Show fields used in query", key="sql_fields_btn")
        if show_fields_btn and selected_proj_sql:
            sql_to_inspect = st.session_state.get("last_sql", "").strip()
            if not sql_to_inspect:
                st.warning("No SQL generated yet. Press 'Generate SQL' first.")
            else:
                proj = load_project(selected_proj_sql)
                schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
                fields = extract_fields_from_query(sql_to_inspect, schema)
                with st.expander("Debug (parser)"):
                    st.write("Detected tables:", fields.get("tables"))
                    st.write("Detected columns:", fields.get("columns"))

                import pandas as pd
                tables_map = {(t.get("id") or t.get("name")): t for t in schema.get("tables", [])}
                rows = []
                # If no columns but there are tables -> list all columns of those tables
                if (not fields.get("columns")) and fields.get("tables"):
                    for tbl in fields["tables"]:
                        tdef = tables_map.get(tbl, {})
                        for c in tdef.get("columns", []):
                            rows.append({
                                "table": tbl, "column": c.get("name", "?"),
                                "type": c.get("type") or c.get("data_type") or "",
                                "nullable": bool(c.get("nullable")),
                                "pk": bool(c.get("pk") or c.get("primary_key")),
                                "unique": bool(c.get("unique")),
                                "default": c.get("default") or ""
                            })
                else:
                    for tbl in sorted(set(fields.get("tables", []))):
                        tdef = tables_map.get(tbl, {})
                        coldefs = {c.get("name"): c for c in tdef.get("columns", [])}
                        for col in sorted(set(fields.get("columns", {}).get(tbl, []))):
                            cd = coldefs.get(col, {})
                            rows.append({
                                "table": tbl,
                                "column": col,
                                "type": cd.get("type") or cd.get("data_type") or "",
                                "nullable": bool(cd.get("nullable")),
                                "pk": bool(cd.get("pk") or cd.get("primary_key")),
                                "unique": bool(cd.get("unique")),
                                "default": cd.get("default") or ""
                            })
                df = pd.DataFrame(rows, columns=["table","column","type","nullable","pk","unique","default"])
                if df.empty:
                    st.info("No fields detected.")
                else:
                    st.dataframe(df, width="stretch", hide_index=True)

        # Optimize
        st.subheader("Optimize Existing SQL")
        sql_input = st.text_area("Paste an existing SQL query to optimize", key="sql_opt_input", height=200)
        opt_btn = st.button("Optimize SQL", key="sql_opt_btn")
        if opt_btn and selected_proj_sql:
            proj = load_project(selected_proj_sql)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            schema_path = proj.get("schema", "")
            rag_ctx = build_rag_context(schema_path, sql_input or "", max_chars=8000, k=6)
            optimized = optimize_sql(sql_input, schema, rag_context=rag_ctx)
            st.session_state["last_optimized_sql"] = optimized

        if st.session_state.get("last_optimized_sql"):
            st.subheader("Last optimized SQL")
            st.code(st.session_state["last_optimized_sql"], language="sql")

        # Show fields (optimized)
        show_opt_fields_btn = st.button("Show fields used in optimized query", key="sql_opt_fields_btn")
        if show_opt_fields_btn and selected_proj_sql:
            sql_to_inspect = st.session_state.get("last_optimized_sql", "").strip()
            if not sql_to_inspect:
                st.warning("No optimized SQL yet. Press 'Optimize SQL' first.")
            else:
                proj = load_project(selected_proj_sql)
                schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
                fields = extract_fields_from_query(sql_to_inspect, schema)
                with st.expander("Debug (parser)"):
                    st.write("Detected tables:", fields.get("tables"))
                    st.write("Detected columns:", fields.get("columns"))

                import pandas as pd
                tables_map = {(t.get("id") or t.get("name")): t for t in schema.get("tables", [])}
                rows = []
                if (not fields.get("columns")) and fields.get("tables"):
                    for tbl in fields["tables"]:
                        tdef = tables_map.get(tbl, {})
                        for c in tdef.get("columns", []):
                            rows.append({
                                "table": tbl, "column": c.get("name", "?"),
                                "type": c.get("type") or c.get("data_type") or "",
                                "nullable": bool(c.get("nullable")),
                                "pk": bool(c.get("pk") or c.get("primary_key")),
                                "unique": bool(c.get("unique")),
                                "default": c.get("default") or ""
                            })
                else:
                    for tbl in sorted(set(fields.get("tables", []))):
                        tdef = tables_map.get(tbl, {})
                        coldefs = {c.get("name"): c for c in tdef.get("columns", [])}
                        for col in sorted(set(fields.get("columns", {}).get(tbl, []))):
                            cd = coldefs.get(col, {})
                            rows.append({
                                "table": tbl,
                                "column": col,
                                "type": cd.get("type") or cd.get("data_type") or "",
                                "nullable": bool(cd.get("nullable")),
                                "pk": bool(cd.get("pk") or cd.get("primary_key")),
                                "unique": bool(cd.get("unique")),
                                "default": cd.get("default") or ""
                            })
                df = pd.DataFrame(rows, columns=["table","column","type","nullable","pk","unique","default"])
                if df.empty:
                    st.info("No fields detected.")
                else:
                    st.dataframe(df, width="stretch", hide_index=True)

# ------------------------------------------------------
# 4. GRAPH TAB
# ------------------------------------------------------
with tab4:
    st.header("Graph View")
    projs = list_projects()
    if not projs:
        st.info("No projects found. Please create one in the Onboarding tab.")
    else:
        selected_proj_graph = st.selectbox("Select project", [p.get("name", "") for p in projs], key="graph_proj")
        if selected_proj_graph:
            proj = load_project(selected_proj_graph)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            tables = sorted({(t.get("id") or t.get("name")) for t in schema.get("tables", []) if (t.get("id") or t.get("name"))})
            highlight = st.selectbox("Highlight table (optional)", [""] + list(tables), key="graph_highlight")
            render_table_neighborhood(schema, highlight, height=760)

# ------------------------------------------------------
# 5. PROCEDURE ANALYZER TAB
# ------------------------------------------------------
with tab5:
    st.header("SQL Procedure Analyzer")
    projs = list_projects()
    if not projs:
        st.info("No projects found. Please create one in the Onboarding tab.")
    else:
        selected_proj_proc = st.selectbox(
            "Select project",
            [p.get("name", "") for p in projs],
            key="proc_proj"
        )
        st.write("Upload a SQL stored procedure or paste its content below.")
        uploaded_proc = st.file_uploader("Upload .sql file", type=["sql"], key="proc_upload")
        proc_text = st.text_area("Or paste SQL procedure here", height=300, key="proc_text")
        analyze_btn = st.button("Analyze Procedure", key="analyze_proc_btn")

        if analyze_btn and selected_proj_proc:
            proj = load_project(selected_proj_proc)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            schema_path = proj.get("schema", "")

            if uploaded_proc:
                proc_code = uploaded_proc.read().decode("utf-8", errors="replace")
            else:
                proc_code = proc_text

            if not proc_code.strip():
                st.error("Please upload or paste a SQL procedure first.")
            else:
                rag_ctx = build_rag_context(schema_path, proc_code, max_chars=8000, k=8)
                analysis = explain_procedure(proc_code, schema, rag_context=rag_ctx)

                st.subheader("AI Explanation")
                st.markdown(analysis)
                st.download_button(
                    "Download analysis",
                    data=analysis.encode("utf-8"),
                    file_name="procedure_analysis.md",
                    mime="text/markdown"
                )
