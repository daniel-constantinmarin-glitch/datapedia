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


def _build_index(schema: dict) -> Tuple[Dict[str, dict], Dict[str, str], Dict[str, Set[str]]]:
    by_id: Dict[str, dict] = {}
    canon_to_orig: Dict[str, str] = {}
    neighbors: Dict[str, Set[str]] = {}

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
        for r in t.get("relations", []) or []:
            dst = r.get("to")
            if not src or not dst:
                continue
            src_o = canon_to_orig.get(_canon(src))
            dst_o = canon_to_orig.get(_canon(dst))
            if src_o and dst_o:
                neighbors[src_o].add(dst_o)
                neighbors[dst_o].add(src_o)

    return by_id, canon_to_orig, neighbors


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


def _build_cytoscape_elements(schema: dict) -> Tuple[List[dict], List[dict]]:
    nodes = []
    edges = []

    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        if not tid:
            continue
        nodes.append({"data": {"id": tid, "label": tid}})

    for t in schema.get("tables", []):
        tid = t.get("id") or t.get("name")
        for r in t.get("relations", []) or []:
            to_id = r.get("to")
            if not tid or not to_id:
                continue
            from_col = r.get("from_col") or "?"
            to_col = r.get("to_col") or "?"
            eid = f"{tid}__{from_col}__{to_id}__{to_col}"
            label = f"{from_col} → {to_col}"
            edges.append(
                {
                    "data": {
                        "id": eid,
                        "source": tid,
                        "target": to_id,
                        "label": label,
                        "fk": f"{tid}.{from_col} → {to_id}.{to_col}",
                    }
                }
            )
    return nodes, edges


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
        {"selector": ".level1", "style": {"background-color": "#03A9F4"}},
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


# -------------------- Public render_graph() --------------------
def render_graph(schema: dict) -> None:
    if _IMPORT_ERROR is not None:
        st.error(
            f"streamlit-cytoscapejs is not available: {_IMPORT_ERROR}. "
            "Run: pip install --upgrade streamlit-cytoscapejs"
        )
        return

    by_id, canon_to_orig, neighbors = _build_index(schema)

    # keep persistent state
    st.session_state.setdefault("graph_center_table", None)
    st.session_state.setdefault("graph_last_click_id", None)
    st.session_state.setdefault("graph_last_click_ts", 0.0)
    st.session_state.setdefault("graph_modal_for", None)
    st.session_state.setdefault("graph_depth", 2)

    st.caption("Click a node to focus; double-click to open table columns; click an edge to see FK info.")

    # UNIQUE KEY
    st.session_state["graph_depth"] = st.slider(
        "BFS depth",
        1,
        5,
        st.session_state["graph_depth"],
        key="graph_depth_slider"
    )

    nodes, edges = _build_cytoscape_elements(schema)
    levels = _compute_levels(neighbors, st.session_state["graph_center_table"], st.session_state["graph_depth"])

    # style nodes by BFS levels
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

    # Handle click events
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

    # Modal
    if st.session_state["graph_modal_for"]:
        tid = st.session_state["graph_modal_for"]
        t = by_id.get(tid)
        if t:
            with st.modal(f"Table details: {tid}"):
                cols = t.get("columns", []) or []
                rows = [
                    {
                        "Column": c.get("name") or "?",
                        "Type": c.get("type") or "",
                        "Nullable": "YES" if c.get("nullable", True) else "NO",
                        "PK": "YES" if c.get("pk") else "NO"
                    }
                    for c in cols
                ]

                st.dataframe(rows, use_container_width=True, hide_index=True)

                # UNIQUE KEY HERE
                if st.button("Close", key="graph_modal_close_btn", use_container_width=True):
                    st.session_state["graph_modal_for"] = None
        else:
            st.session_state["graph_modal_for"] = None
