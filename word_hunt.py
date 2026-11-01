"""Chat-driven Code Breaker puzzle for the KAXMOK YouTube livestream."""
import random
import re
import threading
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
ROUND_SECONDS = 60
RESULT_SECONDS = 7
_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False
_USED_CODES = set()
_STATE = {
    "round": 0, "code": "", "ends_at": 0.0, "status": "waiting",
    "scores": {}, "round_scores": {}, "guesses": [], "seen": {},
    "last_finder": "", "last_answer": "", "results_until": 0.0,
    "used_count": 0,
}


def _font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _make_code():
    # Four distinct digits; leading zero is allowed.
    while True:
        code = "".join(random.SystemRandom().sample("0123456789", 4))
        if code not in _USED_CODES:
            _USED_CODES.add(code)
            return code


def _new_round():
    code = _make_code()
    with _LOCK:
        _STATE.update({
            "code": code, "round": _STATE["round"] + 1,
            "ends_at": time.monotonic() + ROUND_SECONDS,
            "status": "live", "guesses": [], "seen": {},
            "last_finder": "", "last_answer": "",
            "used_count": len(_USED_CODES),
        })
    print(f"[CODE BREAKER] Round {_STATE['round']} started; secret code hidden.", flush=True)


def _game_loop():
    while not _STOP.is_set():
        try:
            with _LOCK:
                expired = _STATE["status"] == "live" and time.monotonic() >= _STATE["ends_at"]
                start_next = _STATE["status"] in {"waiting", "generating"} or (
                    _STATE["status"] == "results" and time.monotonic() >= _STATE["results_until"])
                if expired:
                    _STATE["status"] = "results"
                    _STATE["last_answer"] = _STATE["code"]
                    _STATE["results_until"] = time.monotonic() + RESULT_SECONDS
                    start_next = False
            if start_next:
                _new_round()
            _STOP.wait(0.5)
        except Exception as exc:
            with _LOCK:
                _STATE["status"] = "generating"
            print(f"[CODE BREAKER] Round error: {type(exc).__name__}: {exc}", flush=True)
            _STOP.wait(3)


def start():
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_game_loop, daemon=True, name="code-breaker").start()


def handle_guess(author, message):
    raw = (message or "").strip()
    # Only a standalone four-digit guess is treated as a game entry.
    if not re.fullmatch(r"\d{4}", raw):
        return False
    name = (author or "viewer").strip()[:32] or "viewer"
    key = name.casefold()
    now = time.monotonic()
    with _LOCK:
        if _STATE["status"] != "live":
            return True
        seen = _STATE["seen"].setdefault(key, set())
        if raw in seen:
            return True
        seen.add(raw)
        exact = sum(a == b for a, b in zip(raw, _STATE["code"]))
        misplaced = sum(min(raw.count(d), _STATE["code"].count(d)) for d in set(raw)) - exact
        feedback = f"{exact} exact  |  {misplaced} misplaced"
        _STATE["guesses"].insert(0, {"name": name, "guess": raw, "feedback": feedback})
        _STATE["guesses"] = _STATE["guesses"][:5]
        if raw == _STATE["code"]:
            score = _STATE["scores"].get(key, {"name": name, "points": 0})
            score["name"] = name
            score["points"] += 10
            _STATE["scores"][key] = score
            round_score = _STATE["round_scores"].get(key, {"name": name, "points": 0})
            round_score["name"] = name
            round_score["points"] += 10
            _STATE["round_scores"][key] = round_score
            _STATE["last_finder"] = name
            _STATE["last_answer"] = _STATE["code"]
            _STATE["status"] = "results"
            _STATE["results_until"] = now + RESULT_SECONDS
            print(f"[CODE BREAKER] {name} cracked the code (+10).", flush=True)
        return True


def render_overlay(frame_bytes):
    now = time.monotonic()
    with _LOCK:
        state = {
            "round": _STATE["round"], "ends_at": _STATE["ends_at"],
            "status": _STATE["status"], "guesses": list(_STATE["guesses"]),
            "scores": sorted(_STATE["scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:3],
            "round_scores": sorted(_STATE["round_scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5],
            "last_finder": _STATE["last_finder"], "last_answer": _STATE["last_answer"],
            "used_count": _STATE["used_count"],
        }
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGBA")
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x1, y1, x2, y2 = 1378, 264, 1878, 760
    cyan, purple = (44, 246, 255, 255), (184, 81, 255, 255)
    white, muted = (239, 245, 255, 255), (164, 184, 218, 255)
    d.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(4, 8, 24, 248), outline=purple, width=3)
    d.text((x1 + 24, y1 + 20), "KAXMOK  /  CODE BREAKER", font=_font(20, True), fill=cyan)
    d.text((x1 + 24, y1 + 57), f"ROUND {state['round']:02d}  •  CRACK THE CODE  •  +10 PTS", font=_font(11, True), fill=muted)
    d.text((x1 + 24, y1 + 105), "ENTER A 4-DIGIT CODE IN CHAT", font=_font(16, True), fill=purple)
    d.text((x1 + 24, y1 + 150), "0-9 digits  |  no repeated digits", font=_font(15, True), fill=white)
    d.text((x1 + 24, y1 + 190), "EXAMPLE:  2581", font=_font(17, True), fill=cyan)
    seconds = max(0, int(state["ends_at"] - now)) if state["status"] == "live" else 0
    d.text((x1 + 24, y1 + 235), f"TIME LEFT  {seconds:02d}s", font=_font(19, True), fill=cyan)
    d.text((x1 + 24, y1 + 273), "FEEDBACK: exact = right digit + position", font=_font(11, True), fill=muted)
    d.text((x1 + 24, y1 + 293), "misplaced = right digit, wrong position", font=_font(11, True), fill=muted)
    d.line((x1 + 22, y1 + 325, x2 - 22, y1 + 325), fill=(70, 110, 165, 180), width=1)
    d.text((x1 + 24, y1 + 339), "LATEST GUESSES", font=_font(12, True), fill=purple)
    for i, row in enumerate(state["guesses"][:4]):
        yy = y1 + 365 + i * 23
        d.text((x1 + 24, yy), f"{row['name'][:13]}  {row['guess']}", font=_font(11, True), fill=white)
        d.text((x1 + 245, yy), row["feedback"], font=_font(10, True), fill=cyan)
    d.text((x1 + 24, y2 - 31), f"ALL-TIME TOP: " + ("  •  ".join(f"{r['name'][:12]} {r['points']}" for r in state["scores"][:2]) or "Be the first!"), font=_font(10, True), fill=muted)
    if state["status"] == "results":
        d.rounded_rectangle((x1 + 12, y1 + 12, x2 - 12, y2 - 12), radius=18, fill=(3, 6, 25, 244), outline=cyan, width=2)
        d.text((x1 + 38, y1 + 35), "CODE CRACKED!" if state["last_finder"] else "TIME'S UP!", font=_font(25, True), fill=cyan)
        d.text((x1 + 38, y1 + 100), f"SECRET CODE:  {state['last_answer']}", font=_font(25, True), fill=white)
        if state["last_finder"]:
            d.text((x1 + 38, y1 + 150), f"CRACKED BY  {state['last_finder'][:24]}  +10 PTS", font=_font(14, True), fill=purple)
        else:
            d.text((x1 + 38, y1 + 150), "Nobody cracked this round.", font=_font(14, True), fill=purple)
        d.text((x1 + 38, y1 + 205), "ROUND LEADERBOARD", font=_font(14, True), fill=cyan)
        for i, row in enumerate(state["round_scores"][:5]):
            yy = y1 + 245 + i * 34
            d.text((x1 + 45, yy), f"{i+1}. {row['name'][:22]}", font=_font(14, True), fill=white)
            d.text((x2 - 110, yy), f"+{row['points']}", font=_font(14, True), fill=cyan)
        d.text((x1 + 38, y2 - 52), "NEXT CODE IN A MOMENT", font=_font(11, True), fill=muted)
    output = BytesIO()
    Image.alpha_composite(base, layer).convert("RGB").save(output, format="JPEG", quality=78)
    return output.getvalue()
