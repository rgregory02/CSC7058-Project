# secrets_utils.py
import json, os, threading

_LOCK = threading.Lock()
_SECRETS_FILE = os.environ.get("SECRETS_FILE", "secrets.json")

def _load():
    if not os.path.exists(_SECRETS_FILE):
        return {}
    try:
        with open(_SECRETS_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save(obj):
    tmp = _SECRETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.replace(tmp, _SECRETS_FILE)

def set_secret(name: str, value: str) -> None:
    if not name:
        return
    with _LOCK:
        data = _load()
        if value == "":
            data.pop(name, None)
        else:
            data[name] = value
        _save(data)

def get_secret(name: str) -> str:
    if not name:
        return ""
    with _LOCK:
        data = _load()
        return data.get(name, "") or ""

def has_secret(name: str) -> bool:
    return bool(get_secret(name))