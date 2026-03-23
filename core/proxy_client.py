# core/proxy_client.py
import os
import json
import requests
from typing import Optional, Dict, Any

DEFAULT_TIMEOUT = (5, 30)  # (connect, read) seconds

def _read_proxy_info(schema_path: str) -> Dict[str, Optional[str]]:
    """
    Given a project schema path, look for a sibling 'proxy.json'.
    Returns: {"url": str|None, "token": str|None}
    """
    info = {"url": None, "token": None}
    if not schema_path:
        return info

    folder = os.path.dirname(schema_path)
    proxy_path = os.path.join(folder, "proxy.json")
    if os.path.isfile(proxy_path):
        try:
            with open(proxy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                info["url"] = data.get("url")
                info["token"] = data.get("token")
        except Exception:
            pass

    # Fallback to environment (optional)
    if not info["url"]:
        info["url"] = os.getenv("SAFE_PROXY_URL")
    if not info["token"]:
        info["token"] = os.getenv("SAFE_PROXY_TOKEN")

    return info

def _headers(token: Optional[str]) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _endpoint(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path

def validate_sql(schema_path: str, sql: str, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
    info = _read_proxy_info(schema_path)
    if not info["url"]:
        return {"ok": False, "error": "No Data Firewall URL configured for this project."}
    url = _endpoint(info["url"], "/validate_sql")
    r = requests.post(url, headers=_headers(info["token"]),
                      json={"sql": sql}, timeout=timeout)
    if not r.ok:
        return {"ok": False, "error": r.text}
    data = r.json()
    data["ok"] = True
    return data

def explain_sql(schema_path: str, sql: str, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
    info = _read_proxy_info(schema_path)
    if not info["url"]:
        return {"ok": False, "error": "No Data Firewall URL configured for this project."}
    url = _endpoint(info["url"], "/explain_sql")
    r = requests.post(url, headers=_headers(info["token"]),
                      json={"sql": sql}, timeout=timeout)
    if not r.ok:
        return {"ok": False, "error": r.text}
    data = r.json()
    data["ok"] = True
    return data

def safe_query(schema_path: str, sql: str, timeout=DEFAULT_TIMEOUT) -> Dict[str, Any]:
    info = _read_proxy_info(schema_path)
    if not info["url"]:
        return {"ok": False, "error": "No Data Firewall URL configured for this project."}
    url = _endpoint(info["url"], "/safe_query")
    r = requests.post(url, headers=_headers(info["token"]),
                      json={"sql": sql}, timeout=timeout)
    if not r.ok:
        return {"ok": False, "error": r.text}
    data = r.json()
    data["ok"] = True
    return data

def save_proxy_info(schema_path: str, url: str, token: Optional[str]) -> str:
    """
    Write proxy.json next to schema file.
    """
    folder = os.path.dirname(schema_path)
    os.makedirs(folder, exist_ok=True)
    proxy_path = os.path.join(folder, "proxy.json")
    with open(proxy_path, "w", encoding="utf-8") as f:
        json.dump({"url": url, "token": (token or None)}, f, indent=2)
    return proxy_path
