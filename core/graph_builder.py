# =====================================================================
#  graph_builder.py — versiunea fără depth, fără BFS, full-width
# =====================================================================

from __future__ import annotations
import time
from typing import Dict, List, Set, Callable, Optional
import streamlit as st

# --------------------------------------------------------------
# Load Cytoscape (streamlit-cytoscapejs / st-cytoscape)
# --------------------------------------------------------------
CYTO = None
CYTO_NAME = ""

def _load_cyto():
    try:
        from streamlit_cytoscapejs import st_cytoscapejs
        return st_cytoscapejs, "st_cytoscapejs"
    except:
        pass

    try:
        from streamlit_cytoscapejs import cytoscape
        return cytoscape, "cytoscape_in_streamlit_cytoscapejs"
    except:
        pass

    try:
        from st_cytoscape import cytoscape
        return cytoscape, "st_cytoscape.cytoscape"
    except:
        pass

    return None, ""

CYTO, CYTO_NAME = _load_cyto()
_IMPORT_ERROR = None if CYTO else ImportError(
    "No Cytoscape renderer found. Install:\n"
    "  pip install streamlit-cytoscapejs\n"
    "  OR pip install st-cytoscape"
)

# =====================================================================
# Helpers
# =====================================================================

def _canon(s: Optional[str]):
    if not s:
        return None
    return (
        s.strip().strip('"').strip("'").strip("`")
        .replace("\\", ".").replace("/", ".").replace(":", ".")
        .upper()
    )


def _build_index(schema: dict):
    """
    Build:
      - by_id      : table → table object
      - neighbors  : table → set of other tables
      - edges      : Cytoscape edges with FK label
      - edge_fk    : edge_id → string FK
    """
    by_id = {}
    canon_to_orig = {}
    neighbors: Dict[str, Set[str]] = {}
    edges = []
    edge_fk = {}

    # index tables
    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        if tid:
            by_id[tid] = t

    for tid in list(by_id):
        c = _canon(tid)
        if c:
            canon_to_orig[c] = tid

    neighbors = {tid: set() for tid in by_id}

    # relationships
    for t in by_id.values():
        src = t.get("id") or t.get("name")

        for r in t.get("relations", []) or []:
            dst = r.get("to")
            if not src or not dst:
                continue

            src_o = canon_to_orig.get(_canon(src))
            dst_o = canon_to_orig.get(_canon(dst))
            if not src_o or not dst_o:
                continue

            neighbors[src_o].add(dst_o)
            neighbors[dst_o].add(src_o)

            fk_from = r.get("from_col") or "?"
            fk_to = r.get("to_col") or "?"

            edge_id = f"{src_o}__{fk_from}__{dst_o}__{fk_to}"
            label = f"{fk_from} → {fk_to}"
            fk_str = f"{src_o}.{fk_from} → {dst_o}.{fk_to}"

            edges.append({
                "data": {
                    "id": edge_id,
                    "source": src_o,
                    "target": dst_o,
                    "label": label,
                    "fk": fk_str
                }
            })
            edge_fk[edge_id] = fk_str

    return by_id, canon_to_orig, neighbors, edges, edge_fk


# =====================================================================
# Styling — bigger labels, more readable
# =====================================================================

def _stylesheet():
    return [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "background-color": "#4A90E2",
                "color": "#fff",
                "font-size": 14,
                "text-wrap": "wrap",
                "text-max-width": 120,
                "shape": "round-rectangle",
                "padding": 12,
            },
        },
        {"selector": ".selectedTable", "style": {
            "background-color": "#FFC107",
            "color": "#000",
            "border-width": 3,
            "border-color": "#000"
        }},
        {"selector": "edge", "style": {
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "label": "data(label)",
            "font-size": 10,
            "text-background-opacity": 1,
            "text-background-color": "#ffffff",
        }},
    ]


# =====================================================================
# Wrapper pentru Cytoscape
# =====================================================================

def _call_cyto(elements, stylesheet, key, height="700px"):
    if CYTO_NAME in ["st_cytoscapejs", "cytoscape_in_streamlit_cytoscapejs"]:
        return CYTO(elements, stylesheet, key=key)
    elif CYTO_NAME == "st_cytoscape.cytoscape":
        return CYTO(elements, stylesheet, width="100%", height=height, layout={}, key=key)
    else:
        raise RuntimeError("No Cytoscape renderer.")


# =====================================================================
#   PUBLIC API — SINGLE GRAPH MODE (no depth, full width)
# =====================================================================

def render_table_neighborhood(schema: dict, selected_table: str, height: int = 760):
    """
    Displays the COMPLETE graph (all tables, all FK edges)
    - NO BFS
    - NO depth
    - NO neighbor filtering
    - Selected table highlighted
    - Graph is full width
    """
    if _IMPORT_ERROR:
        st.error(str(_IMPORT_ERROR))
        return

    by_id, _, _, edges, edge_fk = _build_index(schema)

    # -----------------------------
    # NODES (all tables)
    # -----------------------------
    nodes = []
    for tid in by_id.keys():
        cls = "selectedTable" if tid == selected_table else ""
        nodes.append({
            "data": {"id": tid, "label": tid},
            "classes": cls
        })

    # -----------------------------
    # Full-width container
    # -----------------------------
    st.markdown("<div style='width:100%; margin:0; padding:0;'>", unsafe_allow_html=True)

    result = _call_cyto(
        elements=nodes + edges,
        stylesheet=_stylesheet(),
        key=f"graph_full_{selected_table}",
        height=f"{height}px"
    )

    st.markdown("</div>", unsafe_allow_html=True)

    # -----------------------------
    # Handle events
    # -----------------------------
    if isinstance(result, dict):

        selected_nodes = result.get("nodes", [])
        selected_edges = result.get("edges", [])

        # show FK details
        if selected_edges:
            eid = selected_edges[0]
            info = edge_fk.get(eid)
            if info:
                st.info(f"Foreign Key: {info}")

        # Table details modal (double click simulation)
        st.session_state.setdefault("nb_last", [])
        st.session_state.setdefault("nb_ts", 0.0)
        st.session_state.setdefault("nb_modal_for", None)

        now = time.time()

        if selected_nodes:
            last = st.session_state["nb_last"]
            if last == selected_nodes and (now - st.session_state["nb_ts"]) <= 0.6:
                st.session_state["nb_modal_for"] = selected_nodes[0]

            st.session_state["nb_last"] = selected_nodes
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
                        "PK": "YES" if (c.get("pk") or c.get("primary_key")) else "NO"
                    }
                    for c in (t.get("columns") or [])
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)

                if st.button("Close"):
                    st.session_state["nb_modal_for"] = None
``
