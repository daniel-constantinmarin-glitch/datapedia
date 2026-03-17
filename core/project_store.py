# core/project_store.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict
import json

# projects.json este la rădăcina repo-ului (un nivel mai sus față de core/)
PROJECTS_FILE = (Path(__file__).resolve().parents[1] / "projects.json")

def _read_projects_raw():
    if not PROJECTS_FILE.exists():
        return []
    try:
        text = PROJECTS_FILE.read_text(encoding="utf-8")
        data = json.loads(text)
    except Exception:
        return []
    return data

def _write_projects_raw(data) -> None:
    PROJECTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def list_projects() -> List[Dict]:
    """
    Returnează o listă de proiecte sub forma:
    [{"name": "<nume>", "schema": "<cale_catre_schema.json>"}]
    Suportă atât format listă, cât și {"projects": [...]}, pentru retro-compatibilitate.
    """
    raw = _read_projects_raw()
    if isinstance(raw, dict) and "projects" in raw:
        return list(raw.get("projects") or [])
    if isinstance(raw, list):
        return raw
    return []

def load_project(name: str) -> Dict:
    for p in list_projects():
        if (p.get("name") or "") == name:
            return p
    return {}

def save_project(name: str, schema_path: str) -> None:
    raw = _read_projects_raw()
    # normalizăm la format listă
    current = []
    if isinstance(raw, dict) and "projects" in raw:
        current = list(raw.get("projects") or [])
    elif isinstance(raw, list):
        current = raw

    # elimină intrările cu același nume și adaugă/înlocuiește
    current = [p for p in current if (p.get("name") or "") != name]
    current.append({"name": name, "schema": schema_path})

    # scriem înapoi în același „stil” (dacă era dict, păstrăm dict)
    if isinstance(raw, dict) and "projects" in raw:
        out = {"projects": current}
    else:
        out = current

    _write_projects_raw(out)
