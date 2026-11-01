"""AI-generated multi-word word hunt for the KAXMOK YouTube livestream."""
import json
import os
import random
import re
import threading
import time
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
GRID_SIZE = 12
ROUND_SECONDS = 120
WORDS_PER_ROUND = 8
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

_LOCK = threading.RLock()
_STATE = {
    "category": "WAITING FOR THE NEXT PUZZLE",
    "hint": "AI is preparing a fresh word hunt...",
    "grid": [],
    "remaining": set(),
    "found": [],
    "scores": {},
    "round_scores": {},
    "last_finder": "",
    "last_word": "",
    "last_find_at": 0.0,
    "results_until": 0.0,
    "round": 0,
    "ends_at": 0.0,
    "status": "waiting",
    "recent": [],
}
_STARTED = False
_STOP = threading.Event()


def _font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _ai_word_set():
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret is not configured")
    prompt = (
        "Create one original word-search puzzle theme. Return ONLY valid JSON with keys "
        "category, hint, words. words must be an array of exactly 8 distinct common English "
        "single words, each 3 to 9 letters, A-Z only. Choose a fun varied theme and words "
        "that fit it. Do not include spaces, hyphens, numbers, or proper names. "
        "Do not return a grid. Example shape: "
        '{"category":"OCEAN LIFE","hint":"Creatures found beneath the waves","words":["DOLPHIN","CORAL",...]}'
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=35) as response:
        data = json.loads(response.read().decode("utf-8"))
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(raw)
    category = re.sub(r"[^A-Za-z0-9 &'-]", "", str(parsed.get("category", "WORD HUNT")))[:28].upper()
    hint = re.sub(r"[^A-Za-z0-9 ,.!?'-]", "", str(parsed.get("hint", "Find the hidden words")))[:75]
    words = []
    for value in parsed.get("words", []):
        word = re.sub(r"[^A-Za-z]", "", str(value)).upper()
        if 3 <= len(word) <= 9 and word not in words:
            words.append(word)
    if len(words) != WORDS_PER_ROUND:
        raise ValueError(f"AI returned {len(words)} valid unique words; expected {WORDS_PER_ROUND}")
    return category or "WORD HUNT", hint or "Find the hidden words", words


def _make_grid(words):
    grid = [["" for _ in range(GRID_SIZE)] for _ in range(GRID_SIZE)]
    directions = [(0, 1), (1, 0), (1, 1), (-1, 1), (0, -1), (-1, 0), (-1, -1), (1, -1)]
    for word in sorted(words, key=len, reverse=True):
        placements = []
        for dr, dc in directions:
            for r in range(GRID_SIZE):
                for c in range(GRID_SIZE):
                    end_r, end_c = r + dr * (len(word) - 1), c + dc * (len(word) - 1)
                    if not (0 <= end_r < GRID_SIZE and 0 <= end_c < GRID_SIZE):
                        continue
                    cells = [(r + dr * i, c + dc * i) for i in range(len(word))]
                    if all(not grid[rr][cc] or grid[rr][cc] == word[i] for i, (rr, cc) in enumerate(cells)):
                        placements.append(cells)
        if not placements:
            raise ValueError("Could not place every word in the grid")
        cells = random.choice(placements)
        for i, (rr, cc) in enumerate(cells):
            grid[rr][cc] = word[i]
    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            if not grid[r][c]:
                grid[r][c] = random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return grid


def _new_round():
    category, hint, words = _ai_word_set()
    grid = _make_grid(words)
    with _LOCK:
        _STATE["category"] = category
        _STATE["hint"] = hint
        _STATE["grid"] = grid
        _STATE["remaining"] = set(words)
        _STATE["found"] = []
        _STATE["round_scores"] = {}
        _STATE["last_finder"] = ""
        _STATE["last_word"] = ""
        _STATE["last_find_at"] = 0.0
        _STATE["round"] += 1
        _STATE["ends_at"] = time.monotonic() + ROUND_SECONDS
        _STATE["status"] = "live"
        _STATE["recent"] = []


def _game_loop():
    while not _STOP.is_set():
        try:
            with _LOCK:
                live = _STATE["status"] == "live"
                expired = live and time.monotonic() >= _STATE["ends_at"]
                show_results = (_STATE["status"] == "results" and time.monotonic() >= _STATE["results_until"])
                should_start = _STATE["status"] in {"waiting", "generating"} or show_results
                if expired:
                    _STATE["status"] = "results"
                    _STATE["results_until"] = time.monotonic() + 8
                    should_start = False
            if should_start:
                _new_round()
                print(f"[WORD HUNT] Round {_STATE['round']} started: {_STATE['category']} | {len(_STATE['remaining'])} words", flush=True)
            _STOP.wait(1)
        except Exception as exc:
            with _LOCK:
                _STATE["status"] = "generating"
                _STATE["category"] = "PUZZLE RELOADING"
                _STATE["hint"] = "A fresh AI puzzle is being prepared..."
            print(f"[WORD HUNT] Puzzle generation failed: {type(exc).__name__}: {exc}", flush=True)
            _STOP.wait(15)


def start():
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    if not API_KEY:
        print("[WORD HUNT] Disabled: add GEMINI_API_KEY to GitHub Actions secrets.", flush=True)
        return
    threading.Thread(target=_game_loop, daemon=True, name="word-hunt").start()


def handle_guess(author, message):
    """Accept one exact hidden-word guess from YouTube chat."""
    guess = re.sub(r"[^A-Za-z]", "", (message or "").strip()).upper()
    if not (3 <= len(guess) <= 9):
        return False
    name = (author or "viewer").strip()[:32] or "viewer"
    with _LOCK:
        if _STATE["status"] != "live" or guess not in _STATE["remaining"]:
            return False
        _STATE["remaining"].remove(guess)
        _STATE["found"].append(guess)
        score = _STATE["scores"].get(name.casefold(), {"name": name, "points": 0})
        score["name"] = name
        score["points"] += 10
        _STATE["scores"][name.casefold()] = score
        round_score = _STATE["round_scores"].get(name.casefold(), {"name": name, "points": 0})
        round_score["name"] = name
        round_score["points"] += 10
        _STATE["round_scores"][name.casefold()] = round_score
        _STATE["last_finder"] = name
        _STATE["last_word"] = guess
        _STATE["last_find_at"] = time.monotonic()
        _STATE["recent"].insert(0, f"{name[:15]} found {guess}")
        _STATE["recent"] = _STATE["recent"][:3]
        left = len(_STATE["remaining"])
        print(f"[WORD HUNT] {name} found {guess} (+10). {left} words remain.", flush=True)
        if left == 0:
            _STATE["status"] = "results"
            _STATE["results_until"] = time.monotonic() + 8
            _STATE["ends_at"] = time.monotonic()
    return True


def render_overlay(frame_bytes):
    """Draw the live word hunt, found-word slots, finder toast and round results."""
    now = time.monotonic()
    with _LOCK:
        state = {
            "category": _STATE["category"], "hint": _STATE["hint"],
            "grid": [row[:] for row in _STATE["grid"]],
            "remaining": len(_STATE["remaining"]), "found": list(_STATE["found"]),
            "round_scores": sorted(_STATE["round_scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5],
            "round": _STATE["round"], "ends_at": _STATE["ends_at"],
            "status": _STATE["status"], "last_finder": _STATE["last_finder"],
            "last_word": _STATE["last_word"], "last_find_at": _STATE["last_find_at"],
        }
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGBA")
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x1, y1, x2, y2 = 1378, 264, 1878, 760
    cyan, purple = (44, 246, 255, 255), (184, 81, 255, 255)
    white, muted = (239, 245, 255, 255), (164, 184, 218, 255)
    d.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=(4, 8, 24, 248), outline=purple, width=3)
    d.text((x1 + 22, y1 + 17), "KAXMOK  /  AI WORD HUNT", font=_font(18, True), fill=cyan)
    d.text((x1 + 22, y1 + 47), f"ROUND {state['round']:02d}  •  TYPE WORDS IN CHAT  •  +10 PTS", font=_font(10, True), fill=muted)
    d.text((x1 + 22, y1 + 73), state["category"][:28], font=_font(20, True), fill=white)
    d.text((x1 + 22, y1 + 101), state["hint"][:62], font=_font(11), fill=muted)
    gx, gy, cell = x1 + 20, y1 + 137, 24
    for rr, row in enumerate(state["grid"]):
        for cc, letter in enumerate(row):
            xx, yy = gx + cc * cell, gy + rr * cell
            d.rounded_rectangle((xx, yy, xx + 26, yy + 26), radius=5, fill=(13, 23, 49, 255), outline=(54, 90, 145, 230), width=1)
            d.text((xx + 7, yy + 4), letter, font=_font(14, True), fill=cyan if (rr + cc) % 3 else white)
    sx = x1 + 320
    d.text((sx, gy), "WORDS LEFT", font=_font(11, True), fill=muted)
    d.text((sx, gy + 20), str(state["remaining"]), font=_font(32, True), fill=cyan)
    d.text((sx, gy + 72), "FOUND", font=_font(11, True), fill=muted)
    d.text((sx, gy + 91), f"{len(state['found'])}/8", font=_font(25, True), fill=purple)
    seconds = max(0, int(state["ends_at"] - now)) if state["status"] == "live" else 0
    d.text((sx, gy + 132), "TIME LEFT", font=_font(11, True), fill=muted)
    d.text((sx, gy + 151), f"{seconds:02d}s", font=_font(26, True), fill=white)
    d.text((x1 + 22, y1 + 438), "FOUND WORDS", font=_font(11, True), fill=purple)
    slot_x, slot_y, slot_w, slot_h, slot_gap = x1 + 22, y1 + 462, 54, 24, 7
    for i in range(8):
        col, row = i % 4, i // 4
        xx, yy = slot_x + col * (slot_w + slot_gap), slot_y + row * (slot_h + 7)
        d.rounded_rectangle((xx, yy, xx + slot_w, yy + slot_h), radius=6, fill=(20, 18, 48, 255), outline=cyan if i < len(state["found"]) else (70, 90, 130, 255), width=1)
        label = state["found"][i] if i < len(state["found"]) else "????"
        font = _font(10, True)
        tw = d.textlength(label, font=font)
        d.text((xx + (slot_w - tw) / 2, yy + 6), label, font=font, fill=cyan if i < len(state["found"]) else muted)
    if state["last_finder"] and now - state["last_find_at"] < 4:
        d.rounded_rectangle((x1 + 105, y1 + 300, x2 - 105, y1 + 356), radius=12, fill=(22, 12, 54, 245), outline=cyan, width=2)
        msg = f"{state['last_finder'][:18]} FOUND {state['last_word']}  +10"
        d.text((x1 + 125, y1 + 319), msg, font=_font(13, True), fill=white)
    if state["status"] == "results":
        d.rounded_rectangle((x1 + 12, y1 + 12, x2 - 12, y2 - 12), radius=18, fill=(3, 6, 25, 238), outline=cyan, width=2)
        d.text((x1 + 42, y1 + 38), f"ROUND {state['round']:02d} RESULTS", font=_font(23, True), fill=cyan)
        d.text((x1 + 42, y1 + 82), "TOP WORD HUNTERS  •  THIS ROUND", font=_font(13, True), fill=purple)
        if state["round_scores"]:
            for i, row in enumerate(state["round_scores"]):
                yy = y1 + 125 + i * 43
                d.text((x1 + 48, yy), f"{i+1}.  {row['name'][:20]}", font=_font(16, True), fill=white)
                d.text((x2 - 125, yy), f"+{row['points']}", font=_font(16, True), fill=cyan)
        else:
            d.text((x1 + 48, y1 + 145), "No words found this round", font=_font(14, True), fill=white)
        d.text((x1 + 42, y2 - 65), "NEXT AI PUZZLE IN A MOMENT", font=_font(12, True), fill=muted)
    output = BytesIO()
    Image.alpha_composite(base, layer).convert("RGB").save(output, format="JPEG", quality=78)
    return output.getvalue()
