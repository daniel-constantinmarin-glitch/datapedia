
import streamlit as st
import os

from core.project_manager import list_projects, save_project, load_project
from core.schema_loader import load_schema
from core.sql_generator import generate_sql
from core.graph_builder import render_graph  # assumed existing in your project

st.set_page_config(page_title='Datapedia', layout='wide')

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
            # Keep the base path as you had it
            base = "/home/daniel_constantin_marin_ing_com"
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
            [p["name"] for p in projs],
            key="browse_proj"
        )

        if selected_proj:
            proj = load_project(selected_proj)
            schema = load_schema(proj["schema"])

            # construim lista de tabele din cheile id/name
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
                # găsește obiectul tabel
                table = next((t for t in tables_raw if _tbl_name(t) == selected_table), None)

                if table:
                    # Layout: stânga = detalii/coloane, dreapta = graf vecini
                    left, right = st.columns([1, 2], gap="large")

                    with left:
                        st.subheader(f"Columns & Types — {selected_table}")

                        # Tabel structurat cu informații despre coloane
                        import pandas as pd

                        rows = []
                        for c in table.get("columns", []):
                            rows.append({
                                "column":  c.get("name", "?"),
                                "type":    c.get("type") or c.get("data_type") or "",
                                "nullable": c.get("nullable"),
                                "pk":      c.get("pk") or c.get("primary_key"),
                                "unique":  c.get("unique"),
                                "default": c.get("default")
                            })
                        df = pd.DataFrame(rows, columns=["column", "type", "nullable", "pk", "unique", "default"])
                        st.dataframe(df, use_container_width=True, hide_index=True)

                        # Mic sumar
                        total_cols = len(df)
                        pk_cols = int(df["pk"].fillna(False).sum()) if not df.empty else 0
                        nullable_cols = int(df["nullable"].fillna(False).sum()) if not df.empty else 0
                        st.caption(f"Columns: **{total_cols}** · PK: **{pk_cols}** · Nullable: **{nullable_cols}**")

                    with right:
                        st.subheader("Table Neighborhood (FK links)")
                        # Graful interactiv al vecinilor tabelei selectate
                        from core.graph_builder import render_table_neighborhood
                        render_table_neighborhood(schema, selected_table, height=520)

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
            [p["name"] for p in projs],
            key="sql_proj"
        )

        # Optional helper text to remind about env vars
        st.caption("Vertex AI uses environment variables VERTEX_PROJECT_ID / VERTEX_LOCATION / VERTEX_MODEL.")

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
            schema = load_schema(proj["schema"])

            result_sql = generate_sql(prompt, schema)
            st.code(result_sql, language="sql")


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
            [p["name"] for p in projs],
            key="graph_proj"
        )

        if selected_proj_graph:
            proj = load_project(selected_proj_graph)
            schema = load_schema(proj["schema"])

            render_graph(schema)
