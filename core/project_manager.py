import json,os

def list_projects():
 if not os.path.exists('projects.json'):return []
 with open('projects.json') as f:return json.load(f)

def save_project(name,schema_path):
 projs=list_projects()
 projs.append({'name':name,'schema':schema_path})
 with open('projects.json','w') as f:json.dump(projs,f,indent=2)

def load_project(name):
 for p in list_projects():
  if p['name']==name:return p
 return None
