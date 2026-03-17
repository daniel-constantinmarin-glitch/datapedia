# core/graph_builder.py
from __future__ import annotations

import time
from typing import Dict, List, Tuple, Optional, Set, Callable

import streamlit as st

# -----------------------------------------------------------------------------
# Locate a callable Cytoscape renderer from installed packages
#   - Preferred: streamlit_cytoscapejs.st_cytoscapejs  (PyPI: streamlit-cytoscapejs)
#   - Fallback : streamlit_cytoscapejs.cytoscape       (în unele fork-uri)
#   - Fallback : st_cytoscape.cytoscape                (PyPI: st-cytoscape)
# -----------------------------------------------------------------------------
CYTO: Optional[Callable] = None
CYTO_NAME: str = ""

def _load_cyto() -> Tuple[Optional[Callable], str]:
    # A) streamlit-cytoscapejs (oficial) – funcția se numește st_cytoscapejs
    #    README/PyPI: from streamlit_cytoscapejs import st_cytoscapejs
    try:
        from streamlit_cytoscapejs import st_cytoscapejs  # type: ignore
        return st_cytoscapejs, "st_cytoscapejs"
    except Exception:
        pass

    # B) Unele fork-uri expun 'cytoscape' în același pachet
    try:
        from streamlit_cytoscapejs import cytoscape  # type: ignore
        return cytoscape, "cytoscape_in_streamlit_cytoscapejs"
    except Exception:
        pass

    # C) Pachet alternativ: st-cytoscape → from st_cytoscape import cytoscape
    try:
        from st_cytoscape import cytoscape  # type: ignore
        return cytoscape, "st_cytoscape.cytoscape"
    except Exception:
        pass

    return None, ""

CYTO, CYTO_NAME = _load_cyto()
_IMPORT_ERROR = None if CYTO else ImportError(
    "Cannot locate a Cytoscape renderer. Install one of:\n"
    "  pip install --upgrade streamlit-cytoscapejs\n"
    "  # (sau) pip install st-cytoscape"
)

# -------------------- Helpers --------------------
def _canon(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return (
        s.strip().strip('"').strip("'").strip("`")
        .replace("\\", ".").replace("/", ".").replace(":", ".")
        .upper()
    )

def _build_index(schema: dict) -> Tuple[Dict[str, dict], Dict[str, str], Dict[str, Set[str]], List[dict], Dict[str, str]]:
    """
    Returnează:
      - by_id:     {table_name -> table_obj}
      - canon_map: {CANON_NAME -> original_name}
      - neighbors: {table_name -> set(vecini)}
      - edges:     listă de elemente Cytoscape (edge) cu metadata în data{}
      - edge_fk:   map id_edge -> string FK (pentru lookup rapid din selecții)
    Se bazează pe cheile 'relations' din fiecare tabel:
      { "to": "<table>", "from_col": "<col>", "to_col": "<col>" }
    """
    by_id: Dict[str, dict] = {}
    canon_to_orig: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}
    edges: List[dict] = []
    edge_fk: Dict[str, str] = {}

    # Index tabele
    for t in (schema.get("tables") or []):
        tid = t.get("id") or t.get("name")
        if not tid:
            continue
        by_id[tid] = t

    for tid in list(by_id.keys()):
        c = _canon(tid)
        if c:
            canon_to_orig[c] = tid

    neighbors = {tid: set() for tid in by_id.keys()}

    # Muchii + vecini din 'relations'
    for t in by_id.values():
        src = t.get("id") or t.get("name")
        for r in t.get("relations", []) or []:
            dst = r.get("to")
            if not src or not dst:
                continue
            src_o = canon_to_orig.get(_canon(src))
            dst_o = canon_to_orig.get(_canon(dst))
            if not (src_o and dst_o):
                continue

            neighbors[src_o].add(dst_o)
            neighbors[dst_o].add(src_o)

            from_col = r.get("from_col") or "?"
            to_col   = r.get("to_col") or "?"
            eid = f"{src_o}__{from_col}__{dst_o}__{to_col}"
            label = f"{from_col} → {to_col}"
            fk_str = f"{src_o}.{from_col} → {dst_o}.{to_col}"
            edges.append({"data": {"id": eid, "source": src_o, "target": dst_o, "label": label, "fk": fk_str}})
            edge_fk[eid] = fk_str

    return by_id, canon_to_orig, neighbors, edges, edge_fk


def _compute_levels(neighbors: Dict[str, Set[str]], center: Optional[str], max_depth: int) -> Dict[str, int]:
    if not center:
        return {}
    levels: Dict[str, int] = {center: 0}
    frontier = {center}
    visited = set(frontier)
    for d in range(1, max_depth + 1):
        nxt = set()
        for u in frontier:
            for v in neighbors.get(u, set()):
                if v not in visited:
                    visited.add(v)
                    levels[v] = d
                    nxt.add(v)
        frontier = nxt
    return levels


def _build_nodes_all(schema: dict, levels: Dict[str, int]) -> List[dict]:
    nodes: List[dict] = []
    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        if not tid:
            continue
        cls = "dimmed"
        if tid in levels:
            if   levels[tid] == 0: cls = "level0"
            elif levels[tid] == 1: cls = "level1"
            elif levels[tid] == 2: cls = "level2"
            else:                  cls = "levelOther"
        nodes.append({"data": {"id": tid, "label": tid}, "classes": cls})
    return nodes


def _build_nodes_nb(schema: dict, center: str) -> List[dict]:
    by_id, _, neighbors, _, _ = _build_index(schema)
    if center not in by_id:
        return [{"data": {"id": center, "label": center}, "classes": "level0"}]

    neigh = set(neighbors.get(center, set()))
    nodes: List[dict] = [{"data": {"id": center, "label": center}, "classes": "level0"}]
    for n in sorted(neigh):
        nodes.append({"data": {"id": n, "label": n}, "classes": "level1"})
    return nodes


def _stylesheet() -> List[dict]:
    return [
        {"selector": "node", "style": {
            "label": "data(label)", "background-color": "#4A90E2",
            "color": "#fff", "font-size": 10, "shape": "round-rectangle", "padding": 8,
        }},
        {"selector": ".level0", "style": {"background-color": "#FFC107", "color": "#111", "border-width": 2}},
        {"selector": ".level1", "style": {"background-color": "#06d6a0"}},
        {"selector": ".level2", "style": {"background-color": "#9E9E9E"}},
        {"selector": ".levelOther", "style": {"background-color": "#607D8B"}},
        {"selector": ".dimmed", "style": {"opacity": 0.35}},
        {"selector": "edge", "style": {
            "curve-style": "bezier", "target-arrow-shape": "triangle",
            "label": "data(label)", "font-size": 8,
        }},
        {"selector": ":selected", "style": {"border-width": 3, "border-color": "#6bb1ff"}},
    ]


# -----------------------------------------------------------------------------
# NOTE despre evenimente:
#   st_cytoscapejs(...) returnează un dict cu "nodes" și "edges" SELECTATE
#   (nu "tap"/"dbltap"). Simulăm "dbl-click" comparând selecția curentă cu ultima.
# -----------------------------------------------------------------------------

def _call_cyto(elements: List[dict], stylesheet: List[dict], width: str, height: str, layout: dict, key: str):
    if CYTO_NAME == "st_cytoscapejs":
        # API-ul streamlit-cytoscapejs 0.0.2 acceptă doar (elements, stylesheet [, key])
        # Nu suportă width/height/layout ca arguments. Lăsăm Streamlit să gestioneze containerul.
        return CYTO(elements, stylesheet, key=key)  # type: ignore

    elif CYTO_NAME == "cytoscape_in_streamlit_cytoscapejs":
        # Unele fork-uri pot expune 'cytoscape' cu aceeași limitare; apelăm la fel ca mai sus
        return CYTO(elements, stylesheet, key=key)  # type: ignore

    elif CYTO_NAME == "st_cytoscape.cytoscape":
        # Pachetul alternativ st-cytoscape acceptă argumente extinse
        return CYTO(elements, stylesheet, width=width, height=height, layout=layout, key=key)  # type: ignore

    else:
        raise RuntimeError("No Cytoscape renderer available.")



# -------------------- Public API --------------------
def render_graph(schema: dict) -> None:
    if _IMPORT_ERROR is not None:
        st.error(str(_IMPORT_ERROR))
        return

    by_id, _, neighbors, edges, edge_fk = _build_index(schema)

    # state persistent
    st.session_state.setdefault("graph_center_table", None)
    st.session_state.setdefault("graph_last_node_sel", [])   # list of ids
    st.session_state.setdefault("graph_last_ts", 0.0)
    st.session_state.setdefault("graph_modal_for", None)
    st.session_state.setdefault("graph_depth", 2)

    st.caption("Click nodes/edges to select; double-click a node (rapid select twice) to open columns; click an edge to show FK.")

    st.session_state["graph_depth"] = st.slider(
        "BFS depth", 1, 5, st.session_state["graph_depth"], key="graph_depth_slider"
    )

    levels = _compute_levels(neighbors, st.session_state["graph_center_table"], st.session_state["graph_depth"])
    nodes = _build_nodes_all(schema, levels)

    result = _call_cyto(
        elements=nodes + edges,
        stylesheet=_stylesheet(),
        width="100%",
        height="600px",
        layout={"name": "breadthfirst", "directed": True, "padding": 30},
        key="graph_cyto"
    )

    # ----- Interpretare selecție (st_cytoscapejs) -----
    if isinstance(result, dict):
        sel_nodes = result.get("nodes") or []
        sel_edges = result.get("edges") or []

        # focus pe primul nod selectat
        if sel_nodes:
            st.session_state["graph_center_table"] = sel_nodes[0]

        # dbl-click: dacă același nod este selectat de 2 ori în < 0.6s
        now = time.time()
        last_nodes = st.session_state["graph_last_node_sel"]
        if sel_nodes and last_nodes == sel_nodes and (now - st.session_state["graph_last_ts"]) <= 0.6:
            st.session_state["graph_modal_for"] = sel_nodes[0]

        st.session_state["graph_last_node_sel"] = sel_nodes
        st.session_state["graph_last_ts"] = now

        # click pe muchie → afișează FK
        if sel_edges:
            eid = sel_edges[0]
            fk_info = edge_fk.get(eid)
            if fk_info:
                st.info(f"Foreign Key: {fk_info}")

    # Modal cu coloane pentru nodul selectat
    if st.session_state["graph_modal_for"]:
        tid = st.session_state["graph_modal_for"]
        t = by_id.get(tid)
        if t:
            with st.modal(f"Table details: {tid}"):
                cols = t.get("columns", []) or []
                rows = [
                    {
                        "Column": c.get("name") or "?",
                        "Type": c.get("type") or c.get("data_type") or "",
                        "Nullable": "YES" if c.get("nullable", True) else "NO",
                        "PK": "YES" if (c.get("pk") or c.get("primary_key")) else "NO"
                    } for c in cols
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)
                if st.button("Close", key="graph_modal_close_btn", use_container_width=True):
                    st.session_state["graph_modal_for"] = None
        else:
            st.session_state["graph_modal_for"] = None



def render_table_neighborhood(schema: dict, selected_table: str, height: int = 760) -> None:
    """
    Afișează TOT graful bazei de date:
      - fiecare tabel este un nod
      - fiecare FK este o muchie
      - fără BFS / fără depth / fără focus
      - graful ocupă toată lățimea ecranului
    """

    if _IMPORT_ERROR is not None:
        st.error(str(_IMPORT_ERROR))
        return

    # --------------------------------------
    # 1. Construim toate nodurile
    # --------------------------------------
    nodes = []
    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        if not tid:
            continue

        # toate nodurile uniform, dar tabela selectată iese în evidență
        cls = "level0" if tid == selected_table else "level1"
        nodes.append({
            "data": {"id": tid, "label": tid},
            "classes": cls
        })

    # --------------------------------------
    # 2. Construim toate muchiile (FK)
    # --------------------------------------
    by_id, canon_map, neighbors, edges_all, edge_fk = _build_index(schema)
    edges = edges_all  # deja sunt toate

    # --------------------------------------
    # 3. State pentru click/dbl-click
    # --------------------------------------
    st.session_state.setdefault("nb_last_node_sel", [])
    st.session_state.setdefault("nb_last_ts", 0.0)
    st.session_state.setdefault("nb_modal_for", None)

    # --------------------------------------
    # 4. Apelăm cytoscape
    #    streamlit-cytoscapejs *nu suportă* width/layout/height ca argumente,
    #    deci îl plasăm într-un container full-width Streamlit.
    # --------------------------------------
    st.markdown(
        "<div style='width:100%;'>",
        unsafe_allow_html=True
    )

    result = _call_cyto(
        elements=nodes + edges,
        stylesheet=_stylesheet(),
        width="100%",          # ignorat intern, dar ok pt compatibilitate
        height=f"{height}px",  # idem
        layout={},             # ignorat pentru streamlit-cytoscapejs
        key=f"graph_full_schema_{selected_table}"
    )

    st.markdown("</div>", unsafe_allow_html=True)

    # --------------------------------------
    # 5. Interpretare selecție
    # --------------------------------------
    if isinstance(result, dict):
        sel_nodes = result.get("nodes") or []
        sel_edges = result.get("edges") or []

        now = time.time()
        last_nodes = st.session_state["nb_last_node_sel"]

        # dublu-select rapid => modal coloană
        if sel_nodes and last_nodes == sel_nodes and (now - st.session_state["nb_last_ts"]) <= 0.6:
            st.session_state["nb_modal_for"] = sel_nodes[0]

        st.session_state["nb_last_node_sel"] = sel_nodes
        st.session_state["nb_last_ts"] = now

        # click pe muchie → afișează FK
        if sel_edges:
            fk_info = edge_fk.get(sel_edges[0])
            if fk_info:
                st.info(f"Foreign Key: {fk_info}")

    # --------------------------------------
    # 6. Modal cu coloane pentru nodul selectat
    # --------------------------------------
    tid = st.session_state["nb_modal_for"]
    if tid:
        t = by_id.get(tid)
        if t:
            with st.modal(f"Table details: {tid}"):
                cols = t.get("columns", []) or []
                rows = [
                    {
                        "Column": c.get("name") or "?",
                        "Type": c.get("type") or c.get("data_type") or "",
                        "Nullable": "YES" if c.get("nullable", True) else "NO",
                        "PK": "YES" if (c.get("pk") or c.get("primary_key")) else "NO",
                    }
                    for c in cols
                ]
                st.dataframe(rows, width="stretch", hide_index=True)
                if st.button("Close", key="nb_close_btn"):
                    st.session_state["nb_modal_for"] = None
        else:
            st.session_state["nb_modal_for"] = None

    by_id, _, neighbors, edges_all, edge_fk = _build_index(schema)

    # 1) BFS de la selected_table până la 'depth'
    def bfs_nodes(start: str, max_depth: int) -> Dict[str, int]:
        levels: Dict[str, int] = {}
        if start not in neighbors:
            return levels
        levels[start] = 0
        frontier = {start}
        visited = {start}
        for d in range(1, max_depth + 1):
            nxt = set()
            for u in frontier:
                for v in neighbors.get(u, set()):
                    if v not in visited:
                        visited.add(v)
                        levels[v] = d
                        nxt.add(v)
            frontier = nxt
            if not frontier:
                break
        return levels

    levels = bfs_nodes(selected_table, depth)


    by_id, _, neighbors, edges_all, edge_fk = _build_index(schema)

    # noduri: selected + vecinii direcți
    if selected_table not in by_id:
        nodes = [{"data": {"id": selected_table, "label": selected_table}, "classes": "level0"}]
        edges = []
    else:
        neigh = set(neighbors.get(selected_table, set()))
        nodes = [{"data": {"id": selected_table, "label": selected_table}, "classes": "level0"}]
        for n in sorted(neigh):
            nodes.append({"data": {"id": n, "label": n}, "classes": "level1"})
        # păstrează doar muchiile între nodurile din subgraf
        keep = {n["data"]["id"] for n in nodes}
        edges = [e for e in edges_all if e["data"]["source"] in keep and e["data"]["target"] in keep]

    # state local pentru neighborhood
    st.session_state.setdefault("nb_last_node_sel", [])
    st.session_state.setdefault("nb_last_ts", 0.0)
    st.session_state.setdefault("nb_modal_for", None)

    result = _call_cyto(
        elements=nodes + edges,
        stylesheet=_stylesheet(),
        width="100%",
        height=f"{height}px",
        layout={"name": "breadthfirst", "directed": True, "padding": 25, "roots": f"[id = '{selected_table}']"},
        key=f"graph_cyto_nb_{selected_table}"
    )

    if isinstance(result, dict):
        sel_nodes = result.get("nodes") or []
        sel_edges = result.get("edges") or []

        now = time.time()
        last_nodes = st.session_state["nb_last_node_sel"]
        if sel_nodes and last_nodes == sel_nodes and (now - st.session_state["nb_last_ts"]) <= 0.6:
            st.session_state["nb_modal_for"] = sel_nodes[0]
        st.session_state["nb_last_node_sel"] = sel_nodes
        st.session_state["nb_last_ts"] = now

        if sel_edges:
            fk_info = edge_fk.get(sel_edges[0])
            if fk_info:
                st.info(f"Foreign Key: {fk_info}")

    if st.session_state["nb_modal_for"]:
        tid = st.session_state["nb_modal_for"]
        t = by_id.get(tid)
        if t:
            with st.modal(f"Table details: {tid}"):
                cols = t.get("columns", []) or []
                rows = [
                    {
                        "Column": c.get("name") or "?",
                        "Type": c.get("type") or c.get("data_type") or "",
                        "Nullable": "YES" if c.get("nullable", True) else "NO",
                        "PK": "YES" if (c.get("pk") or c.get("primary_key")) else "NO"
                    } for c in cols
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)
                if st.button("Close", key="nb_modal_close_btn", use_container_width=True):
                    st.session_state["nb_modal_for"] = None
        else:
            st.session_state["nb_modal_for"] = None
