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
_RECENT_ANSWERS = []  # Prevent repeats during this stream session.

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
    recent = ", ".join(_RECENT_ANSWERS[-40:]) or "none"
    prompt = (
        "Create one original, family-friendly guessing riddle for a public livestream. "
        "Choose a widely recognizable object, animal, place, food, or everyday concept. "
        "Make three short clues, easiest only at clue 3, and ensure exactly one clear answer. "
        "Avoid people, copyrighted character names, sensitive topics, and obscure trivia. "
        "Return ONLY valid JSON with keys answer, aliases, clues. "
        "answer must be one short common English word or phrase; aliases an array of up to 4 "
        "valid equivalent answers; clues an array of exactly 3 short strings. "
        "Do not reveal the answer in any clue. Do not use any of these recent answers: " + recent + ". Choose a completely different answer."
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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        print(f"[MYSTERY AI] HTTP {exc.code}: {detail}. Using fresh fallback.", flush=True)
        return None
    except Exception as exc:
        print(f"[MYSTERY AI] Generation failed: {type(exc).__name__}: {exc}. Using fresh fallback.", flush=True)
        return None

def _new_round():
    global _ROUND, _ROUND_ID
    generated = _generate_ai_mystery()
    recent = {item.casefold() for item in _RECENT_ANSWERS}
    if generated is None or generated["answer"].casefold() in recent:
        available = [item for item in _BANK if item[0].casefold() not in recent]
        if available:
            answer, clues = random.choice(available)
            generated = {"answer": answer, "aliases": [], "clues": clues}
        elif generated is None:
            answer, clues = random.choice(_BANK)
            generated = {"answer": answer, "aliases": [], "clues": clues}
        else:
            print("[MYSTERY AI] Repeated answer rejected; keeping previous round until fresh content is ready.", flush=True)
            generated = {"answer": "brain teaser", "aliases": [], "clues": [
                "I challenge your thinking with a clever question.",
                "You solve me by using logic and creativity.",
                "I am a brain teaser."
            ]}
    answer_key = generated["answer"].casefold()
    if answer_key not in recent:
        _RECENT_ANSWERS.append(answer_key)
        del _RECENT_ANSWERS[:-40]
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
    """Premium neon game-show HUD with a mystery stage and live ranking cards."""
    with _LOCK:
        if _ROUND is None:
            return frame_bytes
        now = time.monotonic()
        round_data = dict(_ROUND)
        idx = _clue_index(round_data, now)
        scores = sorted(_SCORES.values(), key=lambda x: (-x["points"], x["name"].casefold()))[:7]
        winner = _RECENT_WINNER if now < _LAST_RESULT_UNTIL else ""
        remaining = max(0, _ROUND_SECONDS - int(now - round_data["start"]))
        solved_count = sum(item["points"] for item in _SCORES.values())

    try:
        base = Image.open(io.BytesIO(frame_bytes)).convert("RGBA")
        width, height = base.size
        scale = max(0.5, min(width / 1920, height / 1080, 1.0))
        def px(v): return max(1, int(v * scale))
        def font(v): return _font(px(v))

        panel_w, panel_h = px(1400), px(510)
        gap, main_w = px(22), px(840)
        left = max(px(480), (width-panel_w)//2)
        top = px(300)
        main = (left, top, left+main_w, top+panel_h)
        side = (main[2]+gap, top, left+panel_w, top+panel_h)

        # Soft outer glow behind both glass panels.
        glow = Image.new("RGBA", base.size, (0,0,0,0))
        gd = ImageDraw.Draw(glow)
        for spread, alpha in ((18,18),(12,25),(7,35)):
            gd.rounded_rectangle((left-px(spread),top-px(spread),
                side[2]+px(spread),top+panel_h+px(spread)),
                radius=px(34), outline=(255,38,64,alpha), width=px(5))
        layer = Image.new("RGBA", base.size, (0,0,0,0))
        layer.alpha_composite(glow)
        draw = ImageDraw.Draw(layer)

        cyan=(255,38,64,255); blue=(255,80,92,255)
        purple=(255,72,92,255); gold=(255,190,72,255)
        white=(247,249,255,255); muted=(155,177,207,255)
        green=(106,255,183,255); dark=(6,11,29,245)

        def rr(rect, rad, fill, outline=None, ow=1):
            draw.rounded_rectangle(rect, radius=px(rad), fill=fill,
                outline=outline, width=px(ow) if outline else 1)
        def text(x,y,s,size,fill):
            draw.text((x,y),s,font=font(size),fill=fill)

        # Glass cards, gradient header strips and subtle accent rails.
        rr(main,28,dark,(255,38,64,220),2)
        rr(side,28,(9,3,8,247),(255,190,72,220),2)
        draw.rounded_rectangle((main[0]+px(3),main[1]+px(3),main[2]-px(3),main[1]+px(9)),
            radius=px(5), fill=cyan)
        draw.rounded_rectangle((side[0]+px(3),side[1]+px(3),side[2]-px(3),side[1]+px(9)),
            radius=px(5), fill=purple)
        draw.line((main[0]+px(28),main[1]+px(112),main[2]-px(28),main[1]+px(112)),
            fill=(105,35,52,170),width=px(1))

        # Header / round badge.
        text(main[0]+px(32),main[1]+px(22),"KAXMOK  •  LIVE GAME",14,cyan)
        text(main[0]+px(32),main[1]+px(48),"MYSTERY BOX",37,white)
        badge=(main[2]-px(180),main[1]+px(31),main[2]-px(28),main[1]+px(76))
        rr(badge,15,(42,10,18,255),(255,38,64,220),1)
        text(badge[0]+px(16),badge[1]+px(13),f"ROUND {round_data['id']:03d}",15,gold)

        # Clue cards, with active clue illuminated.
        clue_y=main[1]+px(132)
        for i in range(3):
            x=main[0]+px(32+i*150)
            active=i<=idx
            card=(x,clue_y,x+px(132),clue_y+px(43))
            rr(card,12,(72,12,24,255) if active else (18,26,47,255),
                cyan if active else (105,35,52,200),1)
            if active:
                rr((x+px(9),clue_y+px(9),x+px(18),clue_y+px(34)),5,cyan)
            text(x+px(28),clue_y+px(12),f"CLUE {i+1}",14,white if active else muted)

        # Clue appears inside its own featured display card.
        clue=round_data["clues"][idx]
        box=(main[0]+px(28),main[1]+px(205),main[2]-px(28),main[1]+px(335))
        rr(box,18,(16,5,10,255),(105,35,52,180),1)
        text(box[0]+px(20),box[1]+px(14),"YOUR MYSTERY",12,purple)
        words=clue.split(); lines=[]; line=""
        maxw=main_w-px(92)
        for word in words:
            candidate=(line+" "+word).strip()
            if draw.textlength(candidate,font=font(25))>maxw and line:
                lines.append(line); line=word
            else: line=candidate
        if line: lines.append(line)
        for i,row in enumerate(lines[:2]):
            text(box[0]+px(20),box[1]+px(47+i*px(35)),row,25,white)

        # Countdown and call-to-action.
        bar_l=main[0]+px(32); bar_r=main[2]-px(32); bar_y=main[1]+px(365)
        rr((bar_l,bar_y,bar_r,bar_y+px(11)),6,(45,12,20,255))
        fill_r=bar_l+int((bar_r-bar_l)*remaining/_ROUND_SECONDS)
        if fill_r>bar_l:
            rr((bar_l,bar_y,fill_r,bar_y+px(11)),6,cyan if remaining>15 else gold)
        text(bar_l,bar_y+px(22),f"◷  {remaining:02d}s",19,cyan if remaining>15 else gold)
        text(bar_l+px(145),bar_y+px(25),"DROP YOUR ANSWER IN LIVE CHAT",14,gold)
        status_y=main[3]-px(62)
        if winner:
            rr((bar_l,status_y-px(7),main[2]-px(30),main[3]-px(20)),12,(58,12,24,235),(255,190,72,200),1)
            text(bar_l+px(15),status_y+px(3),f"★  {winner[:25]} GOT IT!",19,green)
        else:
            text(bar_l,status_y+px(2),"NEED HELP?  TYPE  !hint",15,muted)

        # Leaderboard side panel.
        text(side[0]+px(25),side[1]+px(25),"HALL OF",13,cyan)
        text(side[0]+px(25),side[1]+px(45),"CHAMPIONS",27,white)
        rr((side[2]-px(125),side[1]+px(28),side[2]-px(22),side[1]+px(67)),
           13,(35,26,61,255),(166,111,255,200),1)
        text(side[2]-px(108),side[1]+px(40),f"{solved_count} WINS",13,gold)
        draw.line((side[0]+px(22),side[1]+px(91),side[2]-px(22),side[1]+px(91)),
            fill=(120,35,48,210),width=px(1))
        row_y=side[1]+px(108)
        if not scores:
            text(side[0]+px(25),row_y,"First champion loading...",14,muted)
        else:
            for i,item in enumerate(scores):
                y=row_y+i*px(46)
                row=(side[0]+px(16),y-px(5),side[2]-px(16),y+px(34))
                if i==0:
                    rr(row,11,(62,35,12,245),(255,205,94,210),1)
                elif i<3:
                    rr(row,10,(25,8,14,225),(75,116,174,110),1)
                medal=gold if i==0 else cyan if i<3 else muted
                text(row[0]+px(12),y+px(5),["♛","◆","◆"][i] if i<3 else f"{i+1:02d}",15,medal)
                text(row[0]+px(48),y+px(6),item["name"][:15],14,white)
                score=f"{item['points']} PTS"
                sw=draw.textlength(score,font=font(12))
                text(row[2]-sw-px(12),y+px(8),score,12,gold)
        text(side[0]+px(24),side[3]-px(39),"!mysterytop   •   !hint",12,muted)

        base.alpha_composite(layer)
        out=io.BytesIO()
        base.convert("RGB").save(out,format="JPEG",quality=90)
        return out.getvalue()
    except Exception as exc:
        print(f"[MYSTERY] Overlay error: {type(exc).__name__}: {exc}",flush=True)
        return frame_bytes
