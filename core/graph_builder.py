# core/graph_builder.py
from __future__ import annotations

import time
from typing import Dict, List, Tuple, Optional, Set

import streamlit as st

# ---- Safe import for different builds of streamlit-cytoscapejs ----
def _get_cytoscape_callable():
    """
    Try several import paths so we work with multiple package variants.
    """
    # 1) Most common export
    try:
        from streamlit_cytoscapejs import cytoscape  # type: ignore
        return cytoscape
    except Exception:
        pass

    # 2) Top-level attribute on module
    try:
        import streamlit_cytoscapejs as m  # type: ignore
        if hasattr(m, "cytoscape"):
            return getattr(m, "cytoscape")
    except Exception:
        pass

    raise ImportError(
        "Cannot locate 'cytoscape'. Install with: pip install --upgrade streamlit-cytoscapejs"
    )

CYTO = None
try:
    CYTO = _get_cytoscape_callable()
except Exception as e:
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


# -------------------- Helpers --------------------
def _canon(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return (
        s.strip().strip('"').strip("'").strip("`")
        .replace("\\", ".")
        .replace("/", ".")
        .replace(":", ".")
        .upper()
    )


def _build_index(schema: dict) -> Tuple[Dict[str, dict], Dict[str, str], Dict[str, Set[str]], List[dict]]:
    """
    Returnează:
      - by_id:     {table_name -> table_obj}
      - canon_map: {CANON_NAME -> original_name}
      - neighbors: {table_name -> set(vecini)}
      - edges:     listă de muchii, fiecare cu metadata (source, target, from_col, to_col, label, id)
    Se bazează pe cheile tale 'relations' din fiecare tabel:
      { "to": "<table>", "from_col": "<col>", "to_col": "<col>" }
    """
    by_id: Dict[str, dict] = {}
    canon_to_orig: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}
    edges: List[dict] = []

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
            edges.append(
                {
                    "data": {
                        "id": eid,
                        "source": src_o,
                        "target": dst_o,
                        "label": label,
                        "fk": f"{src_o}.{from_col} → {dst_o}.{to_col}",
                    }
                }
            )

    return by_id, canon_to_orig, neighbors, edges


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


def _build_cytoscape_elements_all(schema: dict) -> Tuple[List[dict], List[dict]]:
    nodes = []
    _, _, _, edges = _build_index(schema)
    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        if not tid:
            continue
        nodes.append({"data": {"id": tid, "label": tid}})
    return nodes, edges


def _build_cytoscape_elements_neighborhood(schema: dict, center: str) -> Tuple[List[dict], List[dict]]:
    """
    Construieste elementele (noduri + muchii) DOAR pentru:
      - nodul 'center'
      - vecinii direcți (relații IN/OUT)
    """
    by_id, _, neighbors, edges_all = _build_index(schema)
    nodes = []

    if center not in by_id:
        # fallback: nod izolat
        return [{"data": {"id": center, "label": center}}], []

    # Nucleu + vecini
    neigh = set(neighbors.get(center, set()))
    sub_nodes = {center} | neigh

    # Noduri cu culori: center = galben, vecini = verde
    for n in sub_nodes:
        color_cls = "level0" if n == center else "level1"
        nodes.append({"data": {"id": n, "label": n}, "classes": color_cls})

    # Muchii doar între nodurile selectate
    sub_edges = []
    for e in edges_all:
        src = e["data"]["source"]
        dst = e["data"]["target"]
        if src in sub_nodes and dst in sub_nodes:
            sub_edges.append(e)

    return nodes, sub_edges


def _stylesheet() -> List[dict]:
    return [
        {"selector": "node", "style": {
            "label": "data(label)",
            "background-color": "#4A90E2",
            "color": "#fff",
            "font-size": 10,
            "shape": "round-rectangle",
            "padding": 8,
        }},
        {"selector": ".level0", "style": {"background-color": "#FFC107", "color": "#111", "border-width": 2}},
        {"selector": ".level1", "style": {"background-color": "#06d6a0"}},
        {"selector": ".level2", "style": {"background-color": "#9E9E9E"}},
        {"selector": ".levelOther", "style": {"background-color": "#607D8B"}},
        {"selector": ".dimmed", "style": {"opacity": 0.35}},
        {"selector": "edge", "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "label": "data(label)",
            "font-size": 8,
        }},
        {"selector": ":selected", "style": {"border-width": 3, "border-color": "#6bb1ff"}},
    ]


# -------------------- Public API --------------------
def render_graph(schema: dict) -> None:
    """
    Vizualizare globală (ca în varianta ta originală), cu:
      - slider BFS depth,
      - click pe nod: focus center,
      - dbl-click pe nod: modal cu coloane,
      - click pe muchie: info FK.
    """
    if _IMPORT_ERROR is not None:
        st.error(
            f"streamlit-cytoscapejs is not available: {_IMPORT_ERROR}. "
            "Run: pip install --upgrade streamlit-cytoscapejs"
        )
        return

    by_id, _, neighbors, _ = _build_index(schema)

    # persistent state
    st.session_state.setdefault("graph_center_table", None)
    st.session_state.setdefault("graph_last_click_id", None)
    st.session_state.setdefault("graph_last_click_ts", 0.0)
    st.session_state.setdefault("graph_modal_for", None)
    st.session_state.setdefault("graph_depth", 2)

    st.caption("Click a node to focus; double-click to open table columns; click an edge to see FK info.")

    st.session_state["graph_depth"] = st.slider(
        "BFS depth",
        1, 5,
        st.session_state["graph_depth"],
        key="graph_depth_slider"
    )

    nodes, edges = _build_cytoscape_elements_all(schema)
    levels = _compute_levels(neighbors, st.session_state["graph_center_table"], st.session_state["graph_depth"])

    # stilizare pe niveluri
    for n in nodes:
        nid = n["data"]["id"]
        lvl = levels.get(nid)
        if lvl is None:
            n["classes"] = "dimmed"
        elif lvl == 0:
            n["classes"] = "level0"
        elif lvl == 1:
            n["classes"] = "level1"
        elif lvl == 2:
            n["classes"] = "level2"
        else:
            n["classes"] = "levelOther"

    event = CYTO(
        elements=nodes + edges,
        layout={"name": "breadthfirst", "directed": True, "padding": 30},
        stylesheet=_stylesheet(),
        height="600px",
        width="100%",
        key="graph_cyto"
    )

    # Evenimente
    if event:
        ev = event.get("event") or event.get("type")
        etype = event.get("type")
        data = event.get("data", {})

        if etype == "edge" and ev in ("tap", "click", "select"):
            st.info(f"Foreign Key: {data.get('fk') or data.get('label')}")

        if etype == "node" and ev in ("tap", "click", "select", "dbltap", "doubleTap"):
            node_id = data.get("id")
            now = time.time()
            last_id = st.session_state["graph_last_click_id"]
            last_ts = st.session_state["graph_last_click_ts"]

            if node_id and ev in ("tap", "click", "select"):
                st.session_state["graph_center_table"] = node_id

            if node_id and last_id == node_id and (now - last_ts) <= 0.6:
                st.session_state["graph_modal_for"] = node_id

            st.session_state["graph_last_click_id"] = node_id
            st.session_state["graph_last_click_ts"] = now

    # Modal columne tabel
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
                    }
                    for c in cols
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)

                if st.button("Close", key="graph_modal_close_btn", use_container_width=True):
                    st.session_state["graph_modal_for"] = None
        else:
            st.session_state["graph_modal_for"] = None


def render_table_neighborhood(schema: dict, selected_table: str, height: int = 520) -> None:
    """
    Vizualizare centrată pe tabela selectată în tab-ul Project Browser:
      - nod central (galben),
      - vecini direcți (verde),
      - muchii IN/OUT cu etichete from_col → to_col,
      - click edge => FK info, dbl-click node => modal cu coloane (aceeași logică).
    """
    if _IMPORT_ERROR is not None:
        st.error(
            f"streamlit-cytoscapejs is not available: {_IMPORT_ERROR}. "
            "Run: pip install --upgrade streamlit-cytoscapejs"
        )
        return

    by_id, _, _, _ = _build_index(schema)

    # Construiește subgraful pentru selected_table
    nodes, edges = _build_cytoscape_elements_neighborhood(schema, selected_table)

    # State local pentru modal în acest view
    st.session_state.setdefault("nb_last_click_id", None)
    st.session_state.setdefault("nb_last_click_ts", 0.0)
    st.session_state.setdefault("nb_modal_for", None)

    event = CYTO(
        elements=nodes + edges,
        layout={"name": "breadthfirst", "directed": True, "padding": 25, "roots": f"[id = '{selected_table}']"},
        stylesheet=_stylesheet(),
        height=f"{height}px",
        width="100%",
        key=f"graph_cyto_nb_{selected_table}"
    )

    # Evenimente similare cu render_graph
    if event:
        ev = event.get("event") or event.get("type")
        etype = event.get("type")
        data = event.get("data", {})

        if etype == "edge" and ev in ("tap", "click", "select"):
            st.info(f"Foreign Key: {data.get('fk') or data.get('label')}")

        if etype == "node" and ev in ("tap", "click", "select", "dbltap", "doubleTap"):
            node_id = data.get("id")
            now = time.time()
            last_id = st.session_state["nb_last_click_id"]
            last_ts = st.session_state["nb_last_click_ts"]

            if node_id and last_id == node_id and (now - last_ts) <= 0.6:
                st.session_state["nb_modal_for"] = node_id

            st.session_state["nb_last_click_id"] = node_id
            st.session_state["nb_last_click_ts"] = now

    # Modal columne tabel (pentru neighborhood view)
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
                    }
                    for c in cols
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)

                if st.button("Close", key="nb_modal_close_btn", use_container_width=True):
                    st.session_state["nb_modal_for"] = None
        else:
            st.session_state["nb_modal_for"] = None
