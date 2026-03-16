import json
import os

PROJECTS_FILE = 'projects.json'

def list_projects():
    if not os.path.exists(PROJECTS_FILE):
        return []
    with open(PROJECTS_FILE) as f:
        return json.load(f)

def save_project(name: str, schema_path: str):
    projs = list_projects()
    projs.append({'name': name, 'schema': schema_path})
    with open(PROJECTS_FILE, 'w') as f:
        json.dump(projs, f, indent=2)

def load_project(name: str):
    for p in list_projects():
        if p["name"] == name:
            return p
    return None