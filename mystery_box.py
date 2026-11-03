"""KAXMOK Mystery Box: timed clue-and-guess chat game."""
import io
import random
import os
import json
import urllib.request
import urllib.error
import threading
import time
from PIL import Image, ImageDraw, ImageFont

_LOCK = threading.RLock()
_STARTED = False
_ROUND_SECONDS = 60
_HINT_INTERVAL = 15
_BANK = [
    ("shadow", ["I follow you but never speak.", "I grow when light is near.", "You can see me, but cannot touch me."]),
    ("keyboard", ["I have many keys but open no doors.", "You use me to talk to a computer.", "I have letters, numbers and a space bar."]),
    ("rainbow", ["I appear after rain and sunlight.", "I have seven familiar colours.", "You cannot reach the end of me."]),
    ("clock", ["I keep moving but stay in one place.", "I have a face and two or three hands.", "I tell you the time."]),
    ("candle", ["I become shorter while doing my job.", "I need a flame to shine.", "I can light up a dark room."]),
    ("echo", ["I repeat what you say, but have no voice of my own.", "You may hear me in a valley.", "Sound bounces back as me."]),
    ("mirror", ["I show you something but keep nothing.", "I copy every move you make.", "You see your reflection in me."]),
    ("piano", ["I have keys but no locks.", "I can be played with both hands.", "I am a musical instrument with black and white keys."]),
    ("map", ["I help you find a way without moving.", "I show places, roads and borders.", "You use me to navigate."]),
    ("book", ["I have a spine but no bones.", "I contain pages but cannot speak.", "You read me for stories or knowledge."]),
    ("ice", ["I am water that has changed.", "Heat makes me disappear.", "I am frozen water."]),
    ("bottle", ["I have a neck but no head.", "I can hold a drink.", "You may close me with a cap."]),
    ("comb", ["I have many teeth but cannot bite.", "I help untangle hair.", "You use me to groom your hair."]),
    ("keyboard", ["I have keys but no doors.", "I help you type messages.", "I sit in front of a computer."]),
    ("telephone", ["I connect voices across distance.", "I can ring when someone wants you.", "You use me to call someone."]),
]
_ROUND = None
_ROUND_ID = 0
_SCORES = {}
_RECENT_WINNER = ""
_LAST_RESULT_UNTIL = 0.0

def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _generate_ai_mystery():
    """Ask Gemini for a fresh, unambiguous three-clue mystery."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
    prompt = (
        "Create one original, family-friendly guessing riddle for a public livestream. "
        "Choose a widely recognizable object, animal, place, food, or everyday concept. "
        "Make three short clues, easiest only at clue 3, and ensure exactly one clear answer. "
        "Avoid people, copyrighted character names, sensitive topics, and obscure trivia. "
        "Return ONLY valid JSON with keys answer, aliases, clues. "
        "answer must be one short common English word or phrase; aliases an array of up to 4 "
        "valid equivalent answers; clues an array of exactly 3 short strings. "
        "Do not reveal the answer in any clue."
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"}
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=14) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload["candidates"][0]["content"]["parts"][0]["text"]
        item = json.loads(raw)
        answer = " ".join(str(item.get("answer", "")).strip().casefold().split())
        aliases = item.get("aliases", [])
        clues = item.get("clues", [])
        if (not answer or len(answer) > 45 or not isinstance(clues, list)
                or len(clues) != 3 or any(not isinstance(x, str) or not x.strip() or len(x) > 150 for x in clues)):
            raise ValueError("Gemini returned an invalid mystery format")
        aliases = [" ".join(str(x).casefold().split()) for x in aliases[:4] if str(x).strip()]
        print("[MYSTERY AI] Gemini generated a new mystery.", flush=True)
        return {"answer": answer, "aliases": aliases, "clues": [x.strip() for x in clues]}
    except Exception as exc:
        print(f"[MYSTERY AI] Generation failed; using built-in question bank ({type(exc).__name__}).", flush=True)
        return None

def _new_round():
    global _ROUND, _ROUND_ID
    generated = _generate_ai_mystery()
    if generated is None:
        answer, clues = random.choice(_BANK)
        generated = {"answer": answer, "aliases": [], "clues": clues}
    _ROUND_ID += 1
    _ROUND = {**generated, "start": time.monotonic(), "id": _ROUND_ID}
    print(f"[MYSTERY] Round {_ROUND_ID} started. Answer hidden; clue 1 is live.", flush=True)

def start():
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
        _new_round()
    def loop():
        while True:
            time.sleep(1)
            with _LOCK:
                if _ROUND is None or time.monotonic() - _ROUND["start"] >= _ROUND_SECONDS:
                    _new_round()
    threading.Thread(target=loop, name="mystery-rounds", daemon=True).start()

def _clue_index(round_data, now):
    elapsed = max(0, now - round_data["start"])
    return min(2, int(elapsed // _HINT_INTERVAL))

def handle_guess(author, message):
    global _RECENT_WINNER, _LAST_RESULT_UNTIL
    text = " ".join((message or "").strip().casefold().split())
    if not text or text.startswith("!"):
        return False
    with _LOCK:
        if _ROUND is None:
            return False
        answer = _ROUND["answer"]
        # Accept the exact answer, ignoring punctuation and extra spaces.
        cleaned = "".join(ch for ch in text if ch.isalnum())
        accepted = [answer] + _ROUND.get("aliases", [])
        expected_answers = {"".join(ch for ch in item.casefold() if ch.isalnum()) for item in accepted}
        if cleaned not in expected_answers:
            return False
        name = (author or "viewer").strip()[:28]
        key = name.casefold()
        _SCORES[key] = {"name": name, "points": _SCORES.get(key, {}).get("points", 0) + 1}
        _RECENT_WINNER = name
        _LAST_RESULT_UNTIL = time.monotonic() + 8
        print(f"[MYSTERY] {name} solved round {_ROUND['id']}! Answer: {answer}. Score: {_SCORES[key]['points']}", flush=True)
        _new_round()
        return True

def handle_command(author, message):
    command = (message or "").strip().casefold()
    if command not in {"!mystery", "!hint", "!mysterytop"}:
        return False
    with _LOCK:
        if command == "!mystery":
            print("[MYSTERY] Mystery Box is active. Guess the hidden answer from the clues on screen!", flush=True)
        elif command == "!hint":
            idx = _clue_index(_ROUND, time.monotonic()) if _ROUND else 0
            print(f"[MYSTERY] Current clue: {_ROUND['clues'][idx] if _ROUND else 'A new mystery is loading.'}", flush=True)
        else:
            top = sorted(_SCORES.values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5]
            print("[MYSTERY] TOP SOLVERS: " + (" | ".join(f"{x['name']} {x['points']}" for x in top) if top else "No winners yet"), flush=True)
    return True

def render_overlay(frame_bytes):
    """Draw the Mystery Box game board and a separate all-rounds session leaderboard."""
    with _LOCK:
        if _ROUND is None:
            return frame_bytes
        now = time.monotonic()
        round_data = dict(_ROUND)
        idx = _clue_index(round_data, now)
        scores = sorted(_SCORES.values(), key=lambda x: (-x["points"], x["name"].casefold()))[:8]
        winner = _RECENT_WINNER if now < _LAST_RESULT_UNTIL else ""
        remaining = max(0, _ROUND_SECONDS - int(now - round_data["start"]))
        solved_count = sum(item["points"] for item in _SCORES.values())

    try:
        base = Image.open(io.BytesIO(frame_bytes)).convert("RGBA")
        width, height = base.size
        scale = min(width / 1920, height / 1080)
        scale = max(0.55, min(scale, 1.0))
        def px(value):
            return int(value * scale)
        def font(size):
            return _font(px(size))

        # Keep the complete HUD centered and safely inside different stream sizes.
        panel_w = px(1120)
        panel_h = px(500)
        gap = px(18)
        board_w = px(700)
        side_w = panel_w - board_w - gap
        left = max(px(24), (width - panel_w) // 2)
        top = max(px(24), (height - panel_h) // 2)
        board = (left, top, left + board_w, top + panel_h)
        side = (left + board_w + gap, top, left + panel_w, top + panel_h)

        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        cyan = (58, 225, 255, 255)
        gold = (255, 204, 92, 255)
        white = (244, 248, 255, 255)
        muted = (157, 179, 207, 255)
        green = (112, 255, 176, 255)
        bg = (5, 10, 27, 238)
        edge = (58, 225, 255, 210)

        def rounded(rect, radius, fill, outline=None, width=1):
            draw.rounded_rectangle(rect, radius=px(radius), fill=fill,
                                   outline=outline, width=px(width) if outline else 1)

        # Main mystery game board.
        rounded(board, 26, bg, edge, 3)
        draw.text((board[0]+px(34), board[1]+px(24)), "KAXMOK", font=font(22), fill=gold)
        draw.text((board[0]+px(34), board[1]+px(61)), "MYSTERY BOX", font=font(36), fill=white)
        draw.text((board[2]-px(210), board[1]+px(35)), f"ROUND {round_data['id']:03d}",
                  font=font(18), fill=cyan)

        # Three clue indicators.
        clue_y = board[1] + px(125)
        for i in range(3):
            cx = board[0] + px(42 + i*112)
            active = i <= idx
            rounded((cx, clue_y, cx+px(96), clue_y+px(30)), 12,
                    (24, 74, 91, 255) if active else (25, 35, 54, 255),
                    cyan if active else (75, 91, 116, 255), 1)
            draw.text((cx+px(18), clue_y+px(5)), f"CLUE {i+1}",
                      font=font(13), fill=white if active else muted)

        # Current clue, wrapped to fit the board.
        clue = round_data["clues"][idx]
        words = clue.split()
        lines, line = [], ""
        max_text_width = board_w - px(76)
        for word in words:
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=font(27)) > max_text_width and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        text_y = board[1] + px(190)
        for i, row in enumerate(lines[:3]):
            draw.text((board[0]+px(38), text_y+i*px(43)), row, font=font(27), fill=white)

        # Timer bar and status.
        bar_left, bar_top = board[0]+px(38), board[1]+px(340)
        bar_right = board[2]-px(38)
        rounded((bar_left, bar_top, bar_right, bar_top+px(10)), 5, (38, 51, 73, 255))
        fill_right = bar_left + int((bar_right-bar_left) * remaining / _ROUND_SECONDS)
        if fill_right > bar_left:
            rounded((bar_left, bar_top, fill_right, bar_top+px(10)), 5, cyan)
        draw.text((bar_left, bar_top+px(22)), f"{remaining:02d}s LEFT",
                  font=font(17), fill=cyan)
        draw.text((bar_left+px(175), bar_top+px(22)),
                  "TYPE YOUR ANSWER IN LIVE CHAT", font=font(16), fill=gold)
        if winner:
            draw.text((bar_left, board[3]-px(70)), f"★  {winner[:24]} SOLVED IT!",
                      font=font(22), fill=green)
        else:
            draw.text((bar_left, board[3]-px(70)), "Need a clue? Type  !hint",
                      font=font(17), fill=muted)

        # Separate leaderboard panel.
        rounded(side, 26, (8, 17, 38, 242), (255, 204, 92, 210), 2)
        draw.text((side[0]+px(25), side[1]+px(26)), "TOP SOLVERS",
                  font=font(23), fill=gold)
        draw.text((side[0]+px(25), side[1]+px(62)), "SESSION LEADERBOARD",
                  font=font(12), fill=muted)
        draw.text((side[2]-px(112), side[1]+px(31)), f"{solved_count} WINS",
                  font=font(13), fill=cyan)
        draw.line((side[0]+px(24), side[1]+px(94),
                   side[2]-px(24), side[1]+px(94)), fill=(68, 91, 119, 220), width=px(1))
        row_y = side[1] + px(112)
        if not scores:
            draw.text((side[0]+px(25), row_y), "Waiting for the first winner...",
                      font=font(14), fill=muted)
        else:
            for i, item in enumerate(scores[:8]):
                y = row_y + i*px(40)
                if i == 0:
                    rounded((side[0]+px(18), y-px(5), side[2]-px(18), y+px(29)),
                            9, (49, 42, 25, 210))
                rank_color = gold if i == 0 else cyan if i < 3 else muted
                draw.text((side[0]+px(27), y), f"{i+1:02d}",
                          font=font(16), fill=rank_color)
                draw.text((side[0]+px(75), y), item["name"][:16],
                          font=font(15), fill=white)
                score_text = f"{item['points']} pts"
                score_width = draw.textlength(score_text, font=font(14))
                draw.text((side[2]-px(25)-score_width, y+px(1)),
                          score_text, font=font(14), fill=gold)
        draw.text((side[0]+px(25), side[3]-px(42)),
                  "!mysterytop  •  !hint", font=font(12), fill=muted)

        base.alpha_composite(layer)
        out = io.BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception as exc:
        print(f"[MYSTERY] Overlay error: {type(exc).__name__}: {exc}", flush=True)
        return frame_bytes
