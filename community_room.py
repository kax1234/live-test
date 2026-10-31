"""Lightweight chat-controlled shared room for the KAXMOK livestream."""
import threading
import time

_LOCK = threading.Lock()
_MEMBERS = {}
_MAX_MEMBERS = 8
_ACTIONS = {"!sit": "SITTING", "!dance": "DANCING", "!wave": "WAVING", "!chill": "CHILLING"}
_COLORS = [(44, 210, 255), (184, 110, 255), (255, 120, 160), (255, 190, 85),
           (110, 230, 160), (120, 155, 255), (255, 115, 90), (220, 220, 245)]

def handle_command(author, message):
    """Return True when a community-room command was handled."""
    parts = (message or "").strip().split()
    if not parts:
        return False
    command = parts[0].casefold()
    if command not in {"!join", "!leave", "!sit", "!dance", "!wave", "!chill"}:
        return False
    name = (author or "viewer").strip()[:22] or "viewer"
    key = name.casefold()
    with _LOCK:
        if command == "!join":
            if key not in _MEMBERS and len(_MEMBERS) >= _MAX_MEMBERS:
                print(f"[ROOM] {name}: room is full ({_MAX_MEMBERS} guests).", flush=True)
            else:
                _MEMBERS.setdefault(key, {"name": name, "action": "CHILLING",
                                          "joined": time.monotonic(), "color": _COLORS[sum(map(ord, key)) % len(_COLORS)]})
                print(f"[ROOM] {name} joined the Community Room.", flush=True)
        elif command == "!leave":
            _MEMBERS.pop(key, None)
            print(f"[ROOM] {name} left the Community Room.", flush=True)
        else:
            member = _MEMBERS.get(key)
            if member:
                member["action"] = _ACTIONS[command]
                print(f"[ROOM] {name} is {member['action'].lower()}.", flush=True)
            else:
                print(f"[ROOM] {name}: type !join first.", flush=True)
    return True

def snapshot():
    with _LOCK:
        return [dict(member) for member in _MEMBERS.values()]
