"""KAX City: persistent community city and individual viewer plots."""
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

_LOCK = threading.RLock()
_API_URL = os.environ.get("CONTROL_API_URL", "").rstrip("/")
_RUNNER_TOKEN = os.environ.get("CONTROL_RUNNER_TOKEN", "")
_LOCAL_STATE = Path(__file__).with_name("kax_city_state.json")
_TYPES = {
    "house": {"cost": 10, "label": "house", "points": 10},
    "road": {"cost": 8, "label": "road", "points": 8},
    "park": {"cost": 15, "label": "park", "points": 15},
    "studio": {"cost": 25, "label": "music studio", "points": 25},
}
_COOLDOWN = 4.0
_last_action = {}


def _fresh():
    return {
        "version": 2, "resources": 100,
        "buildings": {"house": 0, "road": 0, "park": 0, "studio": 0},
        "players": {}, "recent": [], "level": 1,
        "last_event": "KAX City is ready! Type !join to claim your plot.",
    }


def _normalize(value):
    state = _fresh()
    if not isinstance(value, dict):
        return state
    try:
        state["resources"] = max(0, min(10000000, int(value.get("resources", 100))))
        raw_buildings = value.get("buildings", {})
        for kind in _TYPES:
            state["buildings"][kind] = max(0, min(100000, int(raw_buildings.get(kind, 0))))
        raw_players = value.get("players", {})
        if isinstance(raw_players, dict):
            for key, old in list(raw_players.items())[:500]:
                if not isinstance(old, dict):
                    continue
                row = {
                    "name": str(old.get("name", "viewer"))[:32],
                    "points": max(0, int(old.get("points", 0))),
                    "built": max(0, int(old.get("built", 0))),
                    "joined": bool(old.get("joined", True)),
                    "materials": max(0, min(100000, int(old.get("materials", 20)))),
                    "plot": old.get("plot") if isinstance(old.get("plot"), dict) else {},
                }
                for kind in _TYPES:
                    row["plot"][kind] = max(0, min(10000, int(row["plot"].get(kind, 0))))
                state["players"][str(key)[:64]] = row
        state["recent"] = value.get("recent", [])[-4:] if isinstance(value.get("recent"), list) else []
        state["level"] = max(1, min(100000, int(value.get("level", 1))))
        state["last_event"] = str(value.get("last_event", state["last_event"]))[:150]
    except (ValueError, TypeError, AttributeError):
        return state
    return state


def _remote(method, payload=None):
    if not (_API_URL and _RUNNER_TOKEN):
        return None
    request = urllib.request.Request(
        _API_URL + "/api/city-state",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + _RUNNER_TOKEN, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        print(f"[CITY] Persistent storage unavailable ({type(exc).__name__}); local fallback only.", flush=True)
        return None


def _load():
    remote = _remote("GET")
    if isinstance(remote, dict) and isinstance(remote.get("state"), dict):
        return _normalize(remote["state"])
    try:
        if _LOCAL_STATE.is_file():
            return _normalize(json.loads(_LOCAL_STATE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return _fresh()


_STATE = _load()


def _save():
    try:
        _LOCAL_STATE.write_text(json.dumps(_STATE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    result = _remote("POST", {"state": _STATE})
    return bool(result and result.get("ok"))


def _key(name):
    return (name or "viewer").strip()[:32].casefold() or "viewer"


def _name(name):
    return (name or "viewer").strip()[:32] or "viewer"


def _event(message, name="CITY"):
    _STATE["recent"].append({"text": str(message)[:100], "name": str(name)[:24]})
    _STATE["recent"] = _STATE["recent"][-4:]
    _STATE["last_event"] = str(message)[:150]


def _ensure_player(name):
    key = _key(name)
    if key not in _STATE["players"]:
        if len(_STATE["players"]) >= 500:
            return None, key
        _STATE["players"][key] = {
            "name": _name(name), "points": 0, "built": 0, "joined": False,
            "materials": 20, "plot": {kind: 0 for kind in _TYPES},
        }
    row = _STATE["players"][key]
    row["name"] = _name(name)
    row.setdefault("points", 0)
    row.setdefault("built", 0)
    row.setdefault("joined", False)
    row.setdefault("materials", 20)
    row.setdefault("plot", {kind: 0 for kind in _TYPES})
    for kind in _TYPES:
        row["plot"].setdefault(kind, 0)
    return row, key


def handle_command(message, viewer_name, now=None):
    parts = (message or "").strip().split()
    if not parts:
        return None
    command = parts[0].casefold()
    commands = {"!city", "!join", "!build", "!gather", "!upgrade", "!profile", "!top"}
    if command not in commands:
        return None
    name = _name(viewer_name)
    stamp = time.time() if now is None else float(now)
    with _LOCK:
        row, key = _ensure_player(name)
        if row is None:
            return "KAX City is full for now (500 plots)."
        if command == "!city":
            buildings = _STATE["buildings"]
            joined = sum(1 for player in _STATE["players"].values() if player.get("joined"))
            return (f"KAX CITY Lv{_STATE['level']} | {joined} plots | "
                    f"Houses {buildings['house']} Roads {buildings['road']} Parks {buildings['park']} Studios {buildings['studio']} | "
                    f"Community materials {_STATE['resources']}. !join to claim your plot.")
        if command == "!join":
            if row["joined"]:
                return f"{name}, your plot is ready! Use !gather, !build house/road/park/studio, or !profile."
            row["joined"] = True
            row["points"] += 5
            _event(f"{name} joined KAX City and claimed a plot!", name)
            _save()
            return f"{name} claimed a KAX City plot! +5 points, 20 materials. Build with !build house/road/park/studio."
        if command == "!profile":
            plot = row["plot"]
            return (f"{name} | {'Plot claimed' if row['joined'] else 'No plot yet'} | {row['points']} points | "
                    f"{row['materials']} materials | H{plot['house']} R{plot['road']} P{plot['park']} S{plot['studio']} | "
                    f"{row['built']} builds. Use !join.")
        if command == "!top":
            top = sorted(_STATE["players"].values(), key=lambda player: (-int(player.get("points", 0)), str(player.get("name", "")).casefold()))[:5]
            return "KAX CITY BUILDERS: " + (" | ".join(f"{i+1}. {p['name']} {p['points']} pts" for i, p in enumerate(top)) if top else "No builders yet!")
        if not row["joined"]:
            return f"{name}, type !join first to claim your own plot."
        previous = _last_action.get(key, 0)
        if stamp - previous < _COOLDOWN:
            return f"{name}, wait a moment before your next city action."
        _last_action[key] = stamp
        if command == "!gather":
            row["materials"] += 5
            _STATE["resources"] += 5
            row["points"] += 2
            _event(f"{name} gathered +5 materials", name)
            _save()
            return f"{name} gathered +5 personal materials! (+2 points; city supplies +5)"
        if command == "!upgrade":
            total = sum(_STATE["buildings"].values())
            cost = 30 * _STATE["level"]
            if total < _STATE["level"] * 5:
                return f"KAX City needs {_STATE['level'] * 5} total buildings to reach its next level."
            if _STATE["resources"] < cost:
                return f"City upgrade needs {cost} shared materials. Everyone gather with !gather."
            _STATE["resources"] -= cost
            _STATE["level"] += 1
            _event(f"KAX CITY upgraded to LEVEL {_STATE['level']}!", name)
            _save()
            return f"KAX CITY LEVEL {_STATE['level']} unlocked by {name}!"
        if len(parts) < 2 or parts[1].casefold() not in _TYPES:
            return "Build: !build house | !build road | !build park | !build studio"
        kind = parts[1].casefold()
        cost = _TYPES[kind]["cost"]
        if row["materials"] < cost:
            return f"{name}, {kind} costs {cost} personal materials; you have {row['materials']}. Use !gather."
        row["materials"] -= cost
        row["plot"][kind] += 1
        row["built"] += 1
        row["points"] += _TYPES[kind]["points"]
        _STATE["resources"] = max(0, _STATE["resources"] - cost) + cost
        _STATE["buildings"][kind] += 1
        _event(f"{name} built a {kind} on their plot", name)
        _save()
        return f"{name} built a {_TYPES[kind]['label']} on their plot! +{cost} points. KAX City grows."


def snapshot():
    with _LOCK:
        top = sorted(_STATE["players"].values(), key=lambda player: (-int(player.get("points", 0)), str(player.get("name", "")).casefold()))[:5]
        plots = []
        for player in sorted(_STATE["players"].values(), key=lambda item: str(item.get("name", "")).casefold()):
            if player.get("joined"):
                plots.append({"name": player["name"], "points": player["points"], "materials": player["materials"], "plot": dict(player["plot"])})
        return {
            "resources": _STATE["resources"], "buildings": dict(_STATE["buildings"]),
            "players": len(_STATE["players"]), "plots": plots[:24], "level": _STATE["level"],
            "total_buildings": sum(_STATE["buildings"].values()),
            "top": [dict(player) for player in top],
            "recent": [dict(item) for item in _STATE["recent"]],
            "last_event": _STATE["last_event"],
            "storage": "cloudflare" if _API_URL and _RUNNER_TOKEN else "local",
        }
