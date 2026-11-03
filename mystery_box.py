"""KAXMOK Mystery Box: timed clue-and-guess chat game."""
import io
import random
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

def _new_round():
    global _ROUND, _ROUND_ID
    answer, clues = random.choice(_BANK)
    _ROUND_ID += 1
    _ROUND = {"answer": answer, "clues": clues, "start": time.monotonic(), "id": _ROUND_ID}
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
        expected = "".join(ch for ch in answer.casefold() if ch.isalnum())
        if cleaned != expected:
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
    with _LOCK:
        if _ROUND is None:
            return frame_bytes
        now = time.monotonic()
        round_data = dict(_ROUND)
        idx = _clue_index(round_data, now)
        scores = sorted(_SCORES.values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5]
        winner = _RECENT_WINNER if now < _LAST_RESULT_UNTIL else ""
        remaining = max(0, _ROUND_SECONDS - int(now - round_data["start"]))
    try:
        base = Image.open(io.BytesIO(frame_bytes)).convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x1, y1, x2, y2 = 520, 285, 1400, 735
        cyan = (50, 235, 255, 255)
        gold = (255, 205, 90, 255)
        white = (245, 248, 255, 255)
        muted = (165, 185, 215, 255)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=(5, 10, 27, 235), outline=cyan, width=4)
        draw.text((x1+34, y1+24), "KAXMOK  /  MYSTERY BOX", font=_font(29), fill=gold)
        draw.text((x2-190, y1+32), f"ROUND {round_data['id']}", font=_font(17), fill=cyan)
        draw.text((x1+36, y1+88), f"CLUE {idx+1} / 3", font=_font(18), fill=cyan)
        clue = round_data["clues"][idx]
        # Wrap clue to fit the overlay panel.
        words = clue.split()
        lines, line = [], ""
        for word in words:
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=_font(27)) > 790 and line:
                lines.append(line); line = word
            else:
                line = candidate
        if line: lines.append(line)
        for i, row in enumerate(lines[:2]):
            draw.text((x1+36, y1+135+i*42), row, font=_font(27), fill=white)
        draw.rounded_rectangle((x1+36, y1+245, x2-36, y1+253), radius=4, fill=(55,65,85,255))
        draw.rounded_rectangle((x1+36, y1+245, x1+36+int((x2-x1-72)*remaining/_ROUND_SECONDS), y1+253), radius=4, fill=cyan)
        draw.text((x1+36, y1+270), f"TIME LEFT  {remaining}s", font=_font(15), fill=muted)
        draw.text((x1+36, y1+320), "TYPE YOUR ANSWER IN LIVE CHAT", font=_font(19), fill=gold)
        if winner:
            draw.text((x1+36, y1+354), f"★ {winner} SOLVED IT!", font=_font(21), fill=(120,255,170,255))
        else:
            draw.text((x1+36, y1+354), "Need help? Type !hint", font=_font(17), fill=muted)
        draw.text((x1+540, y1+320), "TOP SOLVERS", font=_font(16), fill=cyan)
        for i, row in enumerate(scores[:4]):
            draw.text((x1+540, y1+350+i*23), f"{i+1}. {row['name'][:18]}  •  {row['points']}", font=_font(14), fill=white)
        base.alpha_composite(layer)
        out = io.BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=86)
        return out.getvalue()
    except Exception as exc:
        print(f"[MYSTERY] Overlay error: {type(exc).__name__}: {exc}", flush=True)
        return frame_bytes
