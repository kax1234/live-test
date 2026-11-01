"""AI-generated Guess the Movie game for the KAXMOK YouTube livestream."""
import json
import os
import re
import threading
import time
import urllib.request
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
ROUND_SECONDS = 35
RESULT_SECONDS = 7
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_LOCK = threading.RLock()
_STATE = {
    "title": "GUESS THE MOVIE", "clue": "🎬 🍿 ❓", "hint": "Type the movie title in chat!",
    "scores": {}, "round_scores": {}, "round": 0, "ends_at": 0.0,
    "status": "waiting", "last_finder": "", "last_find_at": 0.0,
    "results_until": 0.0, "last_answer": "", "used_count": 0,
}
_USED_TITLES = set()
_STARTED = False
_STOP = threading.Event()


def _font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _normalise(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _generate_movie():
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret is not configured")
    previous = sorted(_USED_TITLES)
    prompt = (
        "Create ONE widely known family-friendly movie guessing puzzle. Return ONLY JSON with "
        "keys title, emojis, hint. title must be a real movie title, 1-5 words. emojis must be "
        "3-6 relevant emoji characters that hint at the movie without spelling its title. "
        "hint must be a short, helpful clue that does not reveal the title. Prefer popular "
        "international and Indian movies, rotate genres/languages, avoid obscure films. "
        "Never choose any title from this already-used list: " + json.dumps(previous[-300:]) +
        ". Choose a different movie every time."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 1.0, "responseMimeType": "application/json"}}
    for attempt in range(3):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=35) as response:
            data = json.loads(response.read().decode())
        parsed = json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
        title = " ".join(str(parsed.get("title", "")).split())[:70].strip()
        emojis = str(parsed.get("emojis", "🎬 🍿 ❓"))[:80]
        hint = re.sub(r"[^A-Za-z0-9 ,.!?'-]", "", str(parsed.get("hint", "Guess the movie")))[:100]
        key = _normalise(title)
        if title and key and key not in {_normalise(x) for x in _USED_TITLES}:
            _USED_TITLES.add(title)
            return title, emojis, hint or "Guess the movie"
        prompt += " Your previous response repeated a used movie. Generate a different title."
    raise ValueError("AI repeated a previously used movie three times; retrying.")


def _new_round():
    title, clue, hint = _generate_movie()
    with _LOCK:
        _STATE.update({
            "title": title, "clue": clue, "hint": hint,
            "round_scores": {}, "round": _STATE["round"] + 1,
            "ends_at": time.monotonic() + ROUND_SECONDS,
            "status": "live", "last_finder": "", "last_find_at": 0.0,
            "last_answer": "", "used_count": len(_USED_TITLES),
        })
    print(f"[MOVIE GAME] Round {_STATE['round']} ready (answer hidden); used unique titles: {len(_USED_TITLES)}", flush=True)


def _game_loop():
    while not _STOP.is_set():
        try:
            with _LOCK:
                expired = _STATE["status"] == "live" and time.monotonic() >= _STATE["ends_at"]
                start_next = _STATE["status"] in {"waiting", "generating"} or (
                    _STATE["status"] == "results" and time.monotonic() >= _STATE["results_until"])
                if expired:
                    _STATE["status"] = "results"
                    _STATE["last_answer"] = _STATE["title"]
                    _STATE["results_until"] = time.monotonic() + RESULT_SECONDS
                    start_next = False
            if start_next:
                _new_round()
            _STOP.wait(0.5)
        except Exception as exc:
            with _LOCK:
                _STATE["status"] = "generating"
            print(f"[MOVIE GAME] Puzzle generation failed: {type(exc).__name__}: {exc}", flush=True)
            _STOP.wait(10)


def start():
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    if not API_KEY:
        print("[MOVIE GAME] Disabled: add GEMINI_API_KEY.", flush=True)
        return
    threading.Thread(target=_game_loop, daemon=True, name="movie-guess").start()


def handle_guess(author, message):
    guess = _normalise(message)
    if len(guess) < 2:
        return False
    name = (author or "viewer").strip()[:32] or "viewer"
    with _LOCK:
        if _STATE["status"] != "live" or guess != _normalise(_STATE["title"]):
            return False
        score = _STATE["scores"].get(name.casefold(), {"name": name, "points": 0})
        score["name"] = name
        score["points"] += 10
        _STATE["scores"][name.casefold()] = score
        round_score = _STATE["round_scores"].get(name.casefold(), {"name": name, "points": 0})
        round_score["name"] = name
        round_score["points"] += 10
        _STATE["round_scores"][name.casefold()] = round_score
        _STATE["last_finder"] = name
        _STATE["last_find_at"] = time.monotonic()
        _STATE["last_answer"] = _STATE["title"]
        _STATE["status"] = "results"
        _STATE["results_until"] = time.monotonic() + RESULT_SECONDS
        print(f"[MOVIE GAME] {name} guessed {_STATE['title']} (+10)", flush=True)
    return True


def render_overlay(frame_bytes):
    now = time.monotonic()
    with _LOCK:
        state = {
            "title": _STATE["title"], "clue": _STATE["clue"], "hint": _STATE["hint"],
            "scores": sorted(_STATE["scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5],
            "round_scores": sorted(_STATE["round_scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5],
            "round": _STATE["round"], "ends_at": _STATE["ends_at"], "status": _STATE["status"],
            "last_finder": _STATE["last_finder"], "last_find_at": _STATE["last_find_at"],
            "last_answer": _STATE["last_answer"], "used_count": _STATE["used_count"],
        }
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGBA")
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x1, y1, x2, y2 = 1378, 264, 1878, 760
    cyan, purple = (44, 246, 255, 255), (184, 81, 255, 255)
    white, muted = (239, 245, 255, 255), (164, 184, 218, 255)
    d.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(4, 8, 24, 248), outline=purple, width=3)
    d.text((x1 + 24, y1 + 20), "KAXMOK  /  GUESS THE MOVIE", font=_font(19, True), fill=cyan)
    d.text((x1 + 24, y1 + 55), f"ROUND {state['round']:02d}  •  TYPE MOVIE TITLE IN CHAT  •  +10 PTS", font=_font(10, True), fill=muted)
    d.text((x1 + 24, y1 + 105), "DECODE THE EMOJIS", font=_font(14, True), fill=purple)
    clue = state["clue"]
    try:
        ef = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)
        d.text((x1 + 35, y1 + 150), clue, font=ef, embedded_color=True)
    except Exception:
        d.text((x1 + 35, y1 + 165), clue, font=_font(42, True), fill=white)
    d.text((x1 + 24, y1 + 265), state["hint"], font=_font(13, True), fill=white)
    seconds = max(0, int(state["ends_at"] - now)) if state["status"] == "live" else 0
    d.text((x1 + 24, y1 + 315), f"TIME LEFT  {seconds:02d}s", font=_font(18, True), fill=cyan)
    d.text((x1 + 24, y1 + 355), f"UNIQUE MOVIES PLAYED  {state['used_count']}", font=_font(10, True), fill=muted)
    d.line((x1 + 22, y1 + 395, x2 - 22, y1 + 395), fill=(70, 110, 165, 180), width=1)
    d.text((x1 + 24, y1 + 410), "ALL-TIME TOP MOVIE GUESSERS", font=_font(11, True), fill=purple)
    for i, row in enumerate(state["scores"][:3]):
        d.text((x1 + 24, y1 + 435 + i * 17), f"{i+1}. {row['name'][:18]}  {row['points']} PTS", font=_font(10, True), fill=white)
    if state["last_finder"] and now - state["last_find_at"] < 4:
        d.rounded_rectangle((x1 + 50, y1 + 300, x2 - 50, y1 + 350), radius=10, fill=(22, 12, 54, 245), outline=cyan, width=2)
        d.text((x1 + 66, y1 + 315), f"{state['last_finder'][:18]} GOT IT! +10", font=_font(13, True), fill=white)
    if state["status"] == "results":
        d.rounded_rectangle((x1 + 12, y1 + 12, x2 - 12, y2 - 12), radius=18, fill=(3, 6, 25, 242), outline=cyan, width=2)
        d.text((x1 + 38, y1 + 32), "MOVIE REVEALED!", font=_font(23, True), fill=cyan)
        d.text((x1 + 38, y1 + 78), state["last_answer"][:34], font=_font(22, True), fill=white)
        if state["last_finder"]:
            d.text((x1 + 38, y1 + 120), f"FOUND BY  {state['last_finder'][:24]}  +10 PTS", font=_font(13, True), fill=purple)
        else:
            d.text((x1 + 38, y1 + 120), "TIME UP  •  NO CORRECT GUESS", font=_font(13, True), fill=purple)
        d.text((x1 + 38, y1 + 170), "ROUND LEADERBOARD", font=_font(13, True), fill=cyan)
        if state["round_scores"]:
            for i, row in enumerate(state["round_scores"][:5]):
                yy = y1 + 210 + i * 34
                d.text((x1 + 45, yy), f"{i+1}. {row['name'][:22]}", font=_font(14, True), fill=white)
                d.text((x2 - 110, yy), f"+{row['points']}", font=_font(14, True), fill=cyan)
        d.text((x1 + 38, y2 - 52), "NEXT MOVIE IN A MOMENT", font=_font(11, True), fill=muted)
    output = BytesIO()
    Image.alpha_composite(base, layer).convert("RGB").save(output, format="JPEG", quality=78)
    return output.getvalue()
