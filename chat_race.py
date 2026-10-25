"""KAXMOK chat race game state and overlay panel."""
import random
import threading
import time

_LOCK = threading.Lock()
_STATE = {"active": False, "finish_at": 0.0, "racers": {}, "last_boost": {}}


def handle_command(name, message, now=None):
    now = time.monotonic() if now is None else now
    name = (name or "viewer").strip()[:32]
    command = (message or "").strip().lower()
    with _LOCK:
        if command == "!race":
            _STATE.update({"active": True, "finish_at": now + 90, "racers": {}, "last_boost": {}})
            return "started"
        if command in ("!racehelp", "!race-help"):
            return "help"
        if command == "!join" and _STATE["active"] and now < _STATE["finish_at"]:
            _STATE["racers"].setdefault(name, 0)
            return "joined"
        if command == "!boost" and _STATE["active"] and now < _STATE["finish_at"] and name in _STATE["racers"]:
            if now - _STATE["last_boost"].get(name, -100) < 2:
                return "cooldown"
            _STATE["last_boost"][name] = now
            _STATE["racers"][name] += random.randint(4, 10)
            return "boost"
    return None


def draw_panel(draw, width, now, font, cyan, purple, white, muted):
    with _LOCK:
        active = _STATE["active"] and now < _STATE["finish_at"]
        remaining = max(0, int(_STATE["finish_at"] - now)) if _STATE["active"] else 0
        racers = sorted(_STATE["racers"].items(), key=lambda pair: pair[1], reverse=True)[:6]
    x1, y1, x2, y2 = width - 430, 260, width - 42, 610
    draw.rounded_rectangle((x1, y1, x2, y2), radius=20, fill=(4, 8, 24, 224), outline=cyan, width=2)
    draw.text((x1+18, y1+14), "KAXMOK // CHAT RACE", font=font(17, True), fill=cyan)
    status = ("RACE LIVE  •  %ds LEFT" % remaining) if active else "TYPE !race TO START"
    draw.text((x1+18, y1+44), status, font=font(12, True), fill=purple if not active else (255, 104, 145, 255))
    draw.text((x1+18, y1+68), "!join to enter  •  !boost to race", font=font(10, True), fill=muted)
    if not racers:
        draw.text((x1+18, y1+120), "WAITING FOR RACERS...", font=font(13, True), fill=white)
    for i, (name, distance) in enumerate(racers):
        yy = y1 + 100 + i*35
        draw.text((x1+18, yy), "%d. %s" % (i+1, name[:18]), font=font(11, True), fill=white)
        bx1, bx2 = x1+190, x2-18
        draw.rounded_rectangle((bx1, yy+2, bx2, yy+17), radius=6, fill=(26,36,62,255))
        fillw = int((bx2-bx1)*min(1.0, distance/100.0))
        if fillw:
            draw.rounded_rectangle((bx1, yy+2, bx1+fillw, yy+17), radius=6, fill=cyan if i == 0 else purple)
    if _STATE["active"] and now >= _STATE["finish_at"]:
        draw.text((x1+18, y2-28), "FINISH! TYPE !race FOR A NEW ROUND", font=font(9, True), fill=cyan)
