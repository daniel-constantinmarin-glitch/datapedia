import json

def load_schema(path):
 with open(path) as f:return json.load(f)
