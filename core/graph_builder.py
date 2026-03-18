
# =====================================================================
#  core/graph_builder.py — full graph, full width, orange labels, dispersed
# =====================================================================
from __future__ import annotations
import time, math
from typing import Dict, List, Set, Callable, Optional, Tuple
import streamlit as st

# --------------------------------------------------------------
# Load Cytoscape (streamlit-cytoscapejs / st-cytoscape)
# --------------------------------------------------------------
CYTO: Optional[Callable] = None
CYTO_NAME: str = ""

def _load_cyto() -> Tuple[Optional[Callable], str]:
    try:
        from streamlit_cytoscapejs import st_cytoscapejs  # type: ignore
        return st_cytoscapejs, "st_cytoscapejs"
    except Exception:
        pass
    try:
        from streamlit_cytoscapejs import cytoscape  # type: ignore
        return cytoscape, "cytoscape_in_streamlit_cytoscapejs"
    except Exception:
        pass
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
    "  pip install st-cytoscape
"
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
    by_id: Dict[str, dict] = {}
    canon_to_orig: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}
    edges: List[dict] = []
    edge_fk: Dict[str, str] = {}

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
                    "id": eid, "source": src_o, "target": dst_o,
                    "label": label, "fk": fk_str
                }
            })
            edge_fk[eid] = fk_str

    return by_id, canon_to_orig, neighbors, edges, edge_fk


def _scatter_positions(ids: List[str], radius_step: int = 180) -> Dict[str, Dict[str, float]]:
    n = max(1, len(ids))
    positions: Dict[str, Dict[str, float]] = {}
    per_ring = max(8, min(24, int(2*math.sqrt(n))))
    ring_index = 0
    idx_on_ring = 0
    angle_step = 2*math.pi / per_ring

    for k, tid in enumerate(ids):
        if idx_on_ring >= per_ring:
            ring_index += 1
            idx_on_ring = 0
        angle = idx_on_ring * angle_step
        radius = (ring_index + 1) * radius_step
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        positions[tid] = {"x": x, "y": y}
        idx_on_ring += 1

    return positions

# =====================================================================
# Styling
# =====================================================================

def _stylesheet() -> List[dict]:
    return [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "color": "#FFA500",
                "background-color": "#FA9B1E",
                "font-size": 16,
                "text-wrap": "wrap",
                "text-max-width": 160,
                "shape": "round-rectangle",
                "padding": 14,
                "border-width": 2,
                "border-color": "#0d2d53",
            },
        },
        {
            "selector": ".selectedTable",
            "style": {
                "background-color": "#FFC107",
                "color": "#000",
                "border-width": 4,
                "border-color": "#000",
            },
        },
        {
            "selector": "edge",
            "style": {
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "label": "data(label)",
                "font-size": 10,
                "text-background-opacity": 1,
                "text-background-color": "#ffffff",
            },
        },
        {
            "selector": ":selected",
            "style": {
                "border-width": 4,
                "border-color": "#ff8800",
            }
        }
    ]

# =====================================================================
# Cytoscape call wrapper
# =====================================================================

def _call_cyto(elements, stylesheet, key, height="700px"):
    if CYTO_NAME in ["st_cytoscapejs", "cytoscape_in_streamlit_cytoscapejs"]:
        return CYTO(elements=elements, stylesheet=stylesheet, key=key)  # no height/layout support
    elif CYTO_NAME == "st_cytoscape.cytoscape":
        return CYTO(elements, stylesheet, width="100%", height=height,
                    layout={"name": "cose"}, key=key)
    else:
        raise RuntimeError("No Cytoscape renderer available.")

# =====================================================================
# Public API
# =====================================================================

def render_table_neighborhood(schema: dict, selected_table: str, height: int = 760) -> None:
    if _IMPORT_ERROR is not None:
        st.error(str(_IMPORT_ERROR))
        return

    by_id, _, _, edges, edge_fk = _build_index(schema)

    node_ids = list(by_id.keys())
    preset_pos = _scatter_positions(node_ids)
    nodes: List[dict] = []

    for tid in node_ids:
        cls = "selectedTable" if selected_table and tid == selected_table else ""
        node = {"data": {"id": tid, "label": tid}, "classes": cls}

        if CYTO_NAME in ["st_cytoscapejs", "cytoscape_in_streamlit_cytoscapejs"]:
            node["position"] = preset_pos[tid]
            node["grabbable"] = True
            node["locked"] = False

        nodes.append(node)

    graph_key = f"graph_full_{selected_table or 'all'}"

    if CYTO_NAME in ["st_cytoscapejs", "cytoscape_in_streamlit_cytoscapejs"]:
        forced_height = max(height, 1000)
        anchor_id = f"cyto-anchor-{graph_key}"
        st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <style>
              div#{anchor_id} + div {{
                width: 100% !important;
                max-width: 100% !important;
              }}
              div#{anchor_id} + div > div {{
                width: 100% !important;
                max-width: 100% !important;
              }}
              div#{anchor_id} + div [data-testid="stIFrame"] {{
                width: 100% !important;
                min-width: 100% !important;
                height: {forced_height}px !important;
                min-height: {forced_height}px !important;
                display: block !important;
              }}
              div#{anchor_id} + div iframe {{
                width: 100% !important;
                min-width: 100% !important;
                height: {forced_height}px !important;
                min-height: {forced_height}px !important;
                display: block !important;
              }}
            </style>
            """,
            unsafe_allow_html=True,
        )

    with st.container():
        result = _call_cyto(
            elements=nodes + edges,
            stylesheet=_stylesheet(),
            key=graph_key,
            height=f"{max(height,1000)}px",
        )

    if isinstance(result, dict):
        sel_nodes = result.get("nodes") or []
        sel_edges = result.get("edges") or []

        if sel_edges:
            eid = sel_edges[0]
            fk = edge_fk.get(eid)
            if fk:
                st.info(f"Foreign Key: {fk}")

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
                st.dataframe(rows, width='stretch', hide_index=True)
                if st.button("Close"):
                    st.session_state["nb_modal_for"] = None
