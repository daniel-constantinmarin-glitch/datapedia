import streamlit as st
import os

from core.graph_builder import render_table_neighborhood
from core.schema_loader import load_schema
from core.sql_generator import generate_sql, optimize_sql, extract_fields_from_query
from core.project_store import list_projects, load_project, save_project

st.set_page_config(page_title='Datapedia', layout='wide')

# -----------------------------
# Session state (pentru rerun)
# -----------------------------
if "last_sql" not in st.session_state:
    st.session_state["last_sql"] = ""
if "last_optimized_sql" not in st.session_state:
    st.session_state["last_optimized_sql"] = ""

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["Onboarding", "Project Browser", "SQL Generator", "Graph View"])

# ------------------------------------------------------
# 1. ONBOARDING TAB
# ------------------------------------------------------
with tab1:
    st.header("Project Onboarding")
    upload = st.file_uploader(
        "Upload JSON schema (max 5MB)",
        type=["json"],
        key="onb_upload"
    )
    name = st.text_input(
        "Project name",
        key="onb_name"
    )
    create_btn = st.button(
        "Create project",
        key="onb_create_btn"
    )

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
                st.success("Project created successfully!")
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
        selected_proj = st.selectbox(
            "Select project",
            [p.get("name", "") for p in projs],
            key="browse_proj"
        )
        if selected_proj:
            proj = load_project(selected_proj)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            # list of tables (id/name)
            tables_raw = schema.get("tables", [])
            def _tbl_name(t):
                return t.get("id") or t.get("name") or "<unnamed>"
            tables = sorted({_tbl_name(t) for t in tables_raw})

            selected_table = st.selectbox(
                "Select table",
                tables,
                key="browse_table"
            )
            if selected_table:
                # find table object
                table = next((t for t in tables_raw if _tbl_name(t) == selected_table), None)
                if table:
                    # --- Columns & Types (full-width) ---
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

                    # IMPORTANT: width=None (fără warning)
                     st.dataframe(df, width="stretch", hide_index=True)
                    st.caption(f"Columns: **{len(df)}** · PK: **{pk_cols}** · Nullable: **{nullable_cols}**")

                    # --- Full graph (no depth) ---
                    st.subheader("Table Neighborhood (FK links)")
                    render_table_neighborhood(schema, selected_table, height=760)
                else:
                    st.warning("Selected table not found in schema.")

# ------------------------------------------------------
# 3. SQL GENERATOR TAB
# ------------------------------------------------------
with tab3:
    st.header("SQL Generator")
    projs = list_projects()
    if not projs:
        st.info("No projects found. Please create one in the Onboarding tab.")
    else:
        selected_proj_sql = st.selectbox(
            "Select project",
            [p.get("name", "") for p in projs],
            key="sql_proj"
        )

        st.caption("Vertex AI uses environment variables VERTEX_PROJECT_ID / VERTEX_LOCATION / VERTEX_MODEL.")

        # -------- Generate SQL from prompt --------
        prompt = st.text_area(
            "Describe your query in English",
            key="sql_prompt"
        )
        gen_btn = st.button(
            "Generate SQL",
            key="sql_btn"
        )
        if gen_btn and selected_proj_sql:
            proj = load_project(selected_proj_sql)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            result_sql = generate_sql(prompt, schema)
            st.session_state["last_sql"] = result_sql  # store in session
            st.code(result_sql, language="sql")

        # -------- Show fields used in generated SQL --------
        show_fields_btn = st.button("Show fields used in query", key="sql_fields_btn")
        if show_fields_btn and selected_proj_sql:
            sql_to_inspect = st.session_state.get("last_sql", "").strip()
            if not sql_to_inspect:
                st.warning("No SQL generated yet. Press 'Generate SQL' first.")
            else:
                proj = load_project(selected_proj_sql)
                schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
                fields = extract_fields_from_query(sql_to_inspect, schema)

                # Build rich dataframe (table, column, type, nullable, pk, unique, default)
                import pandas as pd
                tables_map = {(t.get("id") or t.get("name")): t for t in schema.get("tables", [])}
                rows = []
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
                df = pd.DataFrame(rows, columns=["table", "column", "type", "nullable", "pk", "unique", "default"])
                if df.empty:
                    st.info("No fields detected.")
                else:
                     st.dataframe(df, width="stretch", hide_index=True)

        # -------- Optimizer --------
        st.subheader("Optimize Existing SQL")
        sql_input = st.text_area(
            "Paste an existing SQL query to optimize",
            key="sql_opt_input",
            height=200
        )
        opt_btn = st.button("Optimize SQL", key="sql_opt_btn")
        if opt_btn and selected_proj_sql:
            proj = load_project(selected_proj_sql)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            optimized = optimize_sql(sql_input, schema)
            st.session_state["last_optimized_sql"] = optimized  # store in session
            st.code(optimized, language="sql")

        # -------- Show fields used in optimized SQL --------
        show_opt_fields_btn = st.button("Show fields used in optimized query", key="sql_opt_fields_btn")
        if show_opt_fields_btn and selected_proj_sql:
            sql_to_inspect = st.session_state.get("last_optimized_sql", "").strip()
            if not sql_to_inspect:
                st.warning("No optimized SQL yet. Press 'Optimize SQL' first.")
            else:
                proj = load_project(selected_proj_sql)
                schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
                fields = extract_fields_from_query(sql_to_inspect, schema)

                import pandas as pd
                tables_map = {(t.get("id") or t.get("name")): t for t in schema.get("tables", [])}
                rows = []
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
                df = pd.DataFrame(rows, columns=["table", "column", "type", "nullable", "pk", "unique", "default"])
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
        selected_proj_graph = st.selectbox(
            "Select project",
            [p.get("name", "") for p in projs],
            key="graph_proj"
        )
        if selected_proj_graph:
            proj = load_project(selected_proj_graph)
            schema = load_schema(proj.get("schema", "")) if proj.get("schema") else {"tables": []}
            # optional: choose a table to highlight
            tables = sorted({(t.get("id") or t.get("name")) for t in schema.get("tables", []) if (t.get("id") or t.get("name"))})
            highlight = st.selectbox("Highlight table (optional)", [""] + tables, key="graph_highlight")
            render_table_neighborhood(schema, highlight, height=760)
