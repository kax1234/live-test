"""KAXMOK Build KAX City — shared chat-built city with persistent community progress."""
import json, os, threading, time, urllib.request
from pathlib import Path

_LOCK = threading.RLock()
_API_URL = os.environ.get("CONTROL_API_URL", "").rstrip("/")
_RUNNER_TOKEN = os.environ.get("CONTROL_RUNNER_TOKEN", "")
_LOCAL_STATE = Path(__file__).with_name("kax_city_state.json")
_TYPES = {
    "house": {"cost": 10, "label": "Houses"},
    "road": {"cost": 8, "label": "Roads"},
    "park": {"cost": 15, "label": "Parks"},
    "studio": {"cost": 25, "label": "Music studios"},
}
_COOLDOWN = 4.0
_last_action = {}

def _fresh():
    return {"version": 1, "resources": 100, "buildings": {"house": 0, "road": 0, "park": 0, "studio": 0},
            "players": {}, "recent": [], "level": 1, "last_event": "The empty plot is ready. Chat, build your city!"}

def _normalize(v):
    s = _fresh()
    if not isinstance(v, dict): return s
    try:
        s["resources"] = max(0, min(10000000, int(v.get("resources", 100))))
        raw = v.get("buildings", {})
        for k in _TYPES: s["buildings"][k] = max(0, min(100000, int(raw.get(k, 0))))
        s["players"] = v.get("players", {}) if isinstance(v.get("players"), dict) else {}
        s["players"] = dict(list(s["players"].items())[:500])
        for row in s["players"].values():
            if isinstance(row, dict):
                row["points"] = max(0, int(row.get("points", 0)))
                row["built"] = max(0, int(row.get("built", 0)))
                row["name"] = str(row.get("name", "viewer"))[:32]
        s["recent"] = v.get("recent", [])[-4:] if isinstance(v.get("recent"), list) else []
        s["level"] = max(1, int(v.get("level", 1)))
        s["last_event"] = str(v.get("last_event", s["last_event"]))[:150]
    except (ValueError, TypeError, AttributeError): return _fresh()
    return s

def _remote(method, payload=None):
    if not (_API_URL and _RUNNER_TOKEN): return None
    req = urllib.request.Request(_API_URL + "/api/city-state",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + _RUNNER_TOKEN, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as r: return json.loads(r.read().decode())
    except Exception as exc:
        print(f"[CITY] Persistent storage unavailable ({type(exc).__name__}); local fallback only.", flush=True)
        return None

def _load():
    remote = _remote("GET")
    if isinstance(remote, dict) and isinstance(remote.get("state"), dict): return _normalize(remote["state"])
    try:
        if _LOCAL_STATE.is_file(): return _normalize(json.loads(_LOCAL_STATE.read_text(encoding="utf-8")))
    except Exception: pass
    return _fresh()

_STATE = _load()

def _save():
    try: _LOCAL_STATE.write_text(json.dumps(_STATE, ensure_ascii=False), encoding="utf-8")
    except Exception: pass
    result = _remote("POST", {"state": _STATE})
    return bool(result and result.get("ok"))

def _key(name): return (name or "viewer").strip()[:32].casefold() or "viewer"
def _name(name): return (name or "viewer").strip()[:32] or "viewer"

def _event(message, name="CITY"):
    _STATE["recent"].append({"text": str(message)[:100], "name": str(name)[:24]})
    _STATE["recent"] = _STATE["recent"][-4:]
    _STATE["last_event"] = str(message)[:150]

def handle_command(message, viewer_name, now=None):
    parts = (message or "").strip().split()
    if not parts: return None
    cmd = parts[0].casefold()
    if cmd not in {"!city", "!build", "!gather", "!upgrade", "!profile", "!top"}: return None
    name = _name(viewer_name); key = _key(name); stamp = time.time() if now is None else float(now)
    with _LOCK:
        row = _STATE["players"].setdefault(key, {"name": name, "points": 0, "built": 0})
        row["name"] = name
        if cmd == "!city":
            b = _STATE["buildings"]
            return f"KAX CITY | Lv {_STATE['level']} | Houses {b['house']} Roads {b['road']} Parks {b['park']} Studios {b['studio']} | { _STATE['resources']} materials. Use !build house/road/park/studio."
        if cmd == "!profile":
            return f"{name}: {row['points']} city points, {row['built']} builds. Type !gather or !build house."
        if cmd == "!top":
            top = sorted(_STATE["players"].values(), key=lambda x: (-int(x.get("points",0)), str(x.get("name","")).casefold()))[:5]
            return "CITY BUILDERS: " + (" | ".join(f"{i+1}. {p['name']} {p['points']}" for i,p in enumerate(top)) if top else "No builders yet!")
        previous = _last_action.get(key, 0)
        if stamp - previous < _COOLDOWN: return f"{name}, city action cooldown — try again in a moment."
        _last_action[key] = stamp
        if cmd == "!gather":
            _STATE["resources"] += 5
            row["points"] += 2
            _event(f"{name} gathered +5 materials", name)
            _save()
            return f"{name} gathered 5 materials for KAX City! (+2 city points)"
        if cmd == "!upgrade":
            total = sum(_STATE["buildings"].values())
            cost = 30 * _STATE["level"]
            if total < _STATE["level"] * 5: return f"City needs {_STATE['level']*5} total buildings before its next level."
            if _STATE["resources"] < cost: return f"City upgrade needs {cost} materials. Use !gather."
            _STATE["resources"] -= cost; _STATE["level"] += 1
            _event(f"KAX CITY upgraded to LEVEL {_STATE['level']}!", name); _save()
            return f"KAX CITY LEVEL {_STATE['level']} unlocked by {name}!"
        if len(parts) < 2 or parts[1].casefold() not in _TYPES:
            return "Build options: !build house | road | park | studio"
        kind = parts[1].casefold(); cost = _TYPES[kind]["cost"]
        if _STATE["resources"] < cost: return f"Not enough materials for {kind} ({cost} needed). Use !gather."
        _STATE["resources"] -= cost; _STATE["buildings"][kind] += 1
        row["points"] += cost; row["built"] += 1
        _event(f"{name} built a {kind} (-{cost} materials)", name); _save()
        return f"{name} built a {kind}! KAX City grows. (+{cost} city points)"
    return None

def snapshot():
    with _LOCK:
        top = sorted(_STATE["players"].values(), key=lambda x: (-int(x.get("points",0)), str(x.get("name","")).casefold()))[:5]
        return {"resources": _STATE["resources"], "buildings": dict(_STATE["buildings"]), "players": len(_STATE["players"]),
                "level": _STATE["level"], "total_buildings": sum(_STATE["buildings"].values()), "top": [dict(x) for x in top],
                "recent": [dict(x) for x in _STATE["recent"]], "last_event": _STATE["last_event"],
                "storage": "cloudflare" if _API_URL and _RUNNER_TOKEN else "local"}
