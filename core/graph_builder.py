
# =====================================================================
#  core/graph_builder.py — graf complet, fără depth, full-width
# =====================================================================
from __future__ import annotations
import time
from typing import Dict, List, Set, Callable, Optional, Tuple
import streamlit as st

# --------------------------------------------------------------
# Load Cytoscape (streamlit-cytoscapejs / st-cytoscape)
# --------------------------------------------------------------
CYTO: Optional[Callable] = None
CYTO_NAME: str = ""

def _load_cyto() -> Tuple[Optional[Callable], str]:
    # A) streamlit-cytoscapejs (API: st_cytoscapejs(elements, stylesheet, key=...))
    try:
        from streamlit_cytoscapejs import st_cytoscapejs  # type: ignore
        return st_cytoscapejs, "st_cytoscapejs"
    except Exception:
        pass
    # B) unele fork-uri: streamlit_cytoscapejs.cytoscape(...)
    try:
        from streamlit_cytoscapejs import cytoscape  # type: ignore
        return cytoscape, "cytoscape_in_streamlit_cytoscapejs"
    except Exception:
        pass
    # C) pachet alternativ: st-cytoscape (API: cytoscape(elements, stylesheet, width, height, layout, key))
    try:
        from st_cytoscape import cytoscape  # type: ignore
        return cytoscape, "st_cytoscape.cytoscape"
    except Exception:
        pass
    return None, ""

CYTO, CYTO_NAME = _load_cyto()
_IMPORT_ERROR = None if CYTO else ImportError(
    "Cannot locate a Cytoscape renderer. Install one of:
"
    "  pip install --upgrade streamlit-cytoscapejs
"
    "  or
"
    "  pip install st-cytoscape"
)

# =====================================================================
# Helpers
# =====================================================================

def _canon(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return (
        s.strip().strip('"').strip("'").strip("`")
        .replace("\", ".").replace("/", ".").replace(":", ".")
        .upper()
    )


def _build_index(schema: dict):
    """
    Return:
      - by_id       : {table_name -> table_obj}
      - canon_to_orig: {CANON -> original}
      - neighbors   : {table -> set(neighbors)}
      - edges       : list of Cytoscape edges (with labels)
      - edge_fk     : {edge_id -> FK string}
    """
    by_id: Dict[str, dict] = {}
    canon_to_orig: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}
    edges: List[dict] = []
    edge_fk: Dict[str, str] = {}

    # index tables
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

    # edges from relations
    for t in by_id.values():
        src = t.get("id") or t.get("name")
        for r in (t.get("relations") or []):
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
            to_col = r.get("to_col") or "?"
            eid = f"{src_o}__{from_col}__{dst_o}__{to_col}"
            label = f"{from_col} → {to_col}"
            fk_str = f"{src_o}.{from_col} → {dst_o}.{to_col}"
            edges.append({
                "data": {
                    "id": eid,
                    "source": src_o,
                    "target": dst_o,
                    "label": label,
                    "fk": fk_str,
                }
            })
            edge_fk[eid] = fk_str

    return by_id, canon_to_orig, neighbors, edges, edge_fk


# =====================================================================
# Styling
# =====================================================================

def _stylesheet() -> List[dict]:
    return [
        {"selector": "node", "style": {
            "label": "data(label)",
            "background-color": "#4A90E2",
            "color": "#fff",
            "font-size": 14,
            "text-wrap": "wrap",
            "text-max-width": 140,
            "shape": "round-rectangle",
            "padding": 12,
            "border-width": 1,
            "border-color": "#1b4d8f",
        }},
        {"selector": ".selectedTable", "style": {
            "background-color": "#FFC107",
            "color": "#111",
            "border-width": 3,
            "border-color": "#000",
        }},
        {"selector": "edge", "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "label": "data(label)",
            "font-size": 10,
            "text-background-opacity": 1,
            "text-background-color": "#ffffff",
        }},
        {"selector": ":selected", "style": {
            "border-width": 3,
            "border-color": "#6bb1ff",
        }},
    ]


# =====================================================================
# Cytoscape wrapper
# =====================================================================

def _call_cyto(elements: List[dict], stylesheet: List[dict], key: str, height: str = "700px"):
    if CYTO_NAME in ["st_cytoscapejs", "cytoscape_in_streamlit_cytoscapejs"]:
        # streamlit-cytoscapejs nu primește width/height/layout
        return CYTO(elements, stylesheet, key=key)  # type: ignore
    elif CYTO_NAME == "st_cytoscape.cytoscape":
        # st-cytoscape are API extins
        return CYTO(elements, stylesheet, width="100%", height=height, layout={}, key=key)  # type: ignore
    else:
        raise RuntimeError("No Cytoscape renderer available.")


# =====================================================================
# Public API — full graph (no depth)
# =====================================================================

def render_table_neighborhood(schema: dict, selected_table: str, height: int = 760) -> None:
    """
    Afișează GRAFUL COMPLET (toate tabelele + toate FK-urile), fără depth/BFS.
    - Numele tabelei pe fiecare nod
    - Container full-width
    - Tabela selectată este evidențiată
    - Click pe muchie → afișează FK
    - Dublu-click pe nod → deschide un modal cu coloane
    """
    if _IMPORT_ERROR is not None:
        st.error(str(_IMPORT_ERROR))
        return

    by_id, _, _, edges, edge_fk = _build_index(schema)

    # Nodes
    nodes: List[dict] = []
    for tid in by_id.keys():
        cls = "selectedTable" if selected_table and tid == selected_table else ""
        nodes.append({"data": {"id": tid, "label": tid}, "classes": cls})

    # Full width container
    st.markdown("<div style='width:100%;margin:0;padding:0;'>", unsafe_allow_html=True)
    result = _call_cyto(
        elements=nodes + edges,
        stylesheet=_stylesheet(),
        key=f"graph_full_{selected_table or 'all'}",
        height=f"{height}px",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    # Handle interactions
    if isinstance(result, dict):
        sel_nodes = result.get("nodes") or []
        sel_edges = result.get("edges") or []

        # Edge -> show FK
        if sel_edges:
            eid = sel_edges[0]
            info = edge_fk.get(eid)
            if info:
                st.info(f"Foreign Key: {info}")

        # Double-click simulation on node
        st.session_state.setdefault("nb_last_nodes", [])
        st.session_state.setdefault("nb_ts", 0.0)
        st.session_state.setdefault("nb_modal_for", None)

        now = time.time()
        if sel_nodes:
            last = st.session_state["nb_last_nodes"]
            if last == sel_nodes and (now - st.session_state["nb_ts"]) <= 0.6:
                st.session_state["nb_modal_for"] = sel_nodes[0]
            st.session_state["nb_last_nodes"] = sel_nodes
            st.session_state["nb_ts"] = now

        tid = st.session_state.get("nb_modal_for")
        if tid and tid in by_id:
            t = by_id[tid]
            with st.modal(f"Table: {tid}"):
                rows = [
                    {
                        "Column": c.get("name") or "?",
                        "Type": c.get("type") or c.get("data_type") or "",
                        "Nullable": "YES" if c.get("nullable", True) else "NO",
                        "PK": "YES" if (c.get("pk") or c.get("primary_key")) else "NO",
                    }
                    for c in (t.get("columns") or [])
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)
                if st.button("Close"):
                    st.session_state["nb_modal_for"] = None
