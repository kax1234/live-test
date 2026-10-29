"""KAXMOK: THE MYSTERY FILE — collaborative live-chat mystery game.

State persists in Cloudflare Workers KV through the existing authenticated music relay
when CONTROL_API_URL and CONTROL_RUNNER_TOKEN are configured. Local JSON is a fallback
for testing only; GitHub-hosted runners have ephemeral disks.
"""
import json
import os
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

_LOCK = threading.RLock()
_API_URL = os.environ.get("CONTROL_API_URL", "").rstrip("/")
_RUNNER_TOKEN = os.environ.get("CONTROL_RUNNER_TOKEN", "")
_LOCAL_STATE = Path(__file__).with_name("mystery_state.json")
_GUESS_COOLDOWN = 8.0
_CLUE_COOLDOWN = 5.0
_last_guess = {}
_last_clue = {}

_CASES = [
    {
        "id": "case-001",
        "title": "THE MISSING MASTER TAPE",
        "brief": "At 00:13, the studio's final song vanished. The door was locked.",
        "answer": "echo",
        "clues": [
            "No footprints. No open window. Yet something left the studio.",
            "It repeated every sound in the room, but could not keep the final note.",
            "It is not a person. It gives back what it hears.",
        ],
    },
    {
        "id": "case-002",
        "title": "THE SILENT DJ",
        "brief": "The midnight broadcast continued, but nobody could hear the host.",
        "answer": "mute",
        "clues": [
            "The microphone was on and the signal was strong.",
            "One tiny control changed the whole broadcast.",
            "The answer is the sound setting that makes audio silent.",
        ],
    },
    {
        "id": "case-003",
        "title": "THE VANISHING TRACK",
        "brief": "A track disappeared from the playlist, but the file was never deleted.",
        "answer": "shuffle",
        "clues": [
            "The file still exists. The playlist order is acting strangely.",
            "The next song is chosen without following the usual order.",
            "It is a playback mode that randomizes the sequence.",
        ],
    },
]


def _fresh_state():
    return {
        "version": 1,
        "case_index": 0,
        "revealed": {},
        "scores": {},
        "solved": [],
        "recent": [],
        "cases_solved": 0,
        "last_event": "The first case is waiting for investigators.",
    }


def _normalize_state(value):
    state = _fresh_state()
    if not isinstance(value, dict):
        return state
    try:
        idx = int(value.get("case_index", 0))
        state["case_index"] = max(0, min(idx, len(_CASES) - 1))
        state["revealed"] = value.get("revealed", {}) if isinstance(value.get("revealed"), dict) else {}
        state["scores"] = value.get("scores", {}) if isinstance(value.get("scores"), dict) else {}
        state["solved"] = value.get("solved", []) if isinstance(value.get("solved"), list) else []
        state["recent"] = value.get("recent", []) if isinstance(value.get("recent"), list) else []
        state["cases_solved"] = max(0, int(value.get("cases_solved", 0)))
        state["last_event"] = str(value.get("last_event", state["last_event"]))[:180]
    except (ValueError, TypeError):
        return _fresh_state()
    # Bound persisted collections so a busy chat cannot grow state forever.
    state["scores"] = dict(list(state["scores"].items())[:500])
    state["solved"] = state["solved"][-100:]
    state["recent"] = state["recent"][-6:]
    return state


def _remote_request(method, payload=None):
    if not (_API_URL and _RUNNER_TOKEN):
        return None
    req = urllib.request.Request(
        _API_URL + "/api/game-state",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Authorization": "Bearer " + _RUNNER_TOKEN, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result
    except Exception as exc:
        print(f"[MYSTERY] Persistent storage unavailable ({type(exc).__name__}); keeping local state.", flush=True)
        return None


def _load_state():
    remote = _remote_request("GET")
    if isinstance(remote, dict) and isinstance(remote.get("state"), dict):
        return _normalize_state(remote["state"])
    try:
        if _LOCAL_STATE.is_file():
            return _normalize_state(json.loads(_LOCAL_STATE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return _fresh_state()


_STATE = _load_state()


def _save_state():
    payload = {"state": _STATE}
    # Always keep a local backup, but don't mistake runner disk for persistent storage.
    try:
        _LOCAL_STATE.write_text(json.dumps(_STATE, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    result = _remote_request("POST", payload)
    if result is not None and result.get("ok"):
        return True
    return False


def _case():
    return _CASES[_STATE["case_index"]]


def _key(name):
    return (name or "viewer").strip()[:32].casefold() or "viewer"


def _display_name(name):
    return (name or "viewer").strip()[:32] or "viewer"


def _add_recent(text, name="SYSTEM"):
    _STATE["recent"].append({"text": str(text)[:130], "name": str(name)[:24]})
    del _STATE["recent"][:-5]
    _STATE["last_event"] = str(text)[:180]


def handle_command(message, viewer_name, now=None):
    """Process mystery commands; returns a status string for workflow logs."""
    parts = (message or "").strip().split()
    if not parts:
        return None
    command = parts[0].casefold()
    allowed = {"!mystery", "!case", "!clue", "!investigate", "!guess", "!solve", "!score", "!top"}
    if command not in allowed:
        return None

    name = _display_name(viewer_name)
    key = _key(name)
    stamp = time.time() if now is None else float(now)

    with _LOCK:
        case = _case()
        revealed = int(_STATE["revealed"].get(case["id"], 0))
        if command in {"!mystery", "!case"}:
            return f'{case["title"]}: {case["brief"]} Clues {revealed}/{len(case["clues"])}. Use !clue, !guess <answer>, !score, !top.'
        if command == "!investigate":
            return f'Investigation status: {revealed}/{len(case["clues"])} clues revealed. Type !clue to reveal the next shared clue.'
        if command == "!clue":
            previous = _last_clue.get(key, 0.0)
            if stamp - previous < _CLUE_COOLDOWN:
                return f"{name}, wait a moment before requesting another clue."
            _last_clue[key] = stamp
            if revealed >= len(case["clues"]):
                return "All clues are already revealed. Discuss the answer and use !guess <answer>."
            clue = case["clues"][revealed]
            _STATE["revealed"][case["id"]] = revealed + 1
            _add_recent(f"CLUE {revealed + 1}: {clue}", name)
            _save_state()
            return f"Clue {revealed + 1}/{len(case['clues'])} revealed by {name}: {clue}"
        if command in {"!guess", "!solve"}:
            if len(parts) < 2:
                return f"Usage: {command} <answer>"
            previous = _last_guess.get(key, 0.0)
            if stamp - previous < _GUESS_COOLDOWN:
                return f"{name}, wait a few seconds before another guess."
            _last_guess[key] = stamp
            guess = " ".join(parts[1:]).casefold().strip(" .!?,'\"")
            if guess != case["answer"]:
                _add_recent(f"{name} submitted a guess. Keep investigating!", name)
                _save_state()
                return f"{name}'s guess is not correct yet. Share theories and try again."
            if case["id"] in _STATE["solved"]:
                return f'Case already solved! Current case: {case["title"]}.'
            row = _STATE["scores"].setdefault(key, {"name": name, "points": 0, "solves": 0, "clues": 0})
            row["name"] = name
            row["points"] = int(row.get("points", 0)) + 25
            row["solves"] = int(row.get("solves", 0)) + 1
            _STATE["solved"].append(case["id"])
            _STATE["cases_solved"] += 1
            _add_recent(f"CASE SOLVED by {name}! +25 INTEL", name)
            if _STATE["case_index"] < len(_CASES) - 1:
                _STATE["case_index"] += 1
                next_case = _case()
                _STATE["last_event"] = f"Case solved! Next file opened: {next_case['title']}"
            else:
                _STATE["case_index"] = 0
                _STATE["revealed"] = {}
                _STATE["solved"] = []
                next_case = _case()
                _STATE["last_event"] = f"All files solved! A new archive cycle has opened: {next_case['title']}."
            _save_state()
            return f"CASE SOLVED by {name}! +25 Intel. The next mystery file is now open."
        if command == "!score":
            row = _STATE["scores"].get(key, {})
            return f"{name}: {int(row.get('points', 0))} Intel, {int(row.get('solves', 0))} cases solved."
        if command == "!top":
            top = sorted(_STATE["scores"].values(), key=lambda row: (-int(row.get("points", 0)), str(row.get("name", "")).casefold()))[:5]
            if not top:
                return "No investigators ranked yet. Solve the first case to earn Intel!"
            return "TOP INVESTIGATORS: " + " | ".join(f"{i+1}. {r.get('name','viewer')} {int(r.get('points',0))} Intel" for i, r in enumerate(top))
    return None


def snapshot():
    """Thread-safe state consumed by the existing on-stream overlay."""
    with _LOCK:
        case = _case()
        revealed = int(_STATE["revealed"].get(case["id"], 0))
        top = sorted(_STATE["scores"].values(), key=lambda row: (-int(row.get("points", 0)), str(row.get("name", "")).casefold()))[:5]
        return {
            "title": case["title"],
            "brief": case["brief"],
            "clues_revealed": revealed,
            "clue_total": len(case["clues"]),
            "clues": list(case["clues"][:revealed]),
            "top": [dict(row) for row in top],
            "recent": [dict(row) for row in _STATE["recent"][-5:]],
            "players": len(_STATE["scores"]),
            "cases_solved": _STATE["cases_solved"],
            "last_event": _STATE["last_event"],
            "storage": "cloudflare" if _API_URL and _RUNNER_TOKEN else "local",
        }
