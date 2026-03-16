
import streamlit as st
import os, json

from core.project_manager import list_projects, save_project, load_project
from core.schema_loader import load_schema
from core.sql_generator import generate_sql
from core.graph_builder import render_graph

st.set_page_config(page_title='Datapedia', layout='wide')

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

            tables = [t["id"] for t in schema["tables"]]

            selected_table = st.selectbox(
                "Select table",
                tables,
                key="browse_table"
            )

            if selected_table:
                table = next(t for t in schema["tables"] if t["id"] == selected_table)
                st.json(table)


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

