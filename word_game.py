"""KAXMOK hidden-word rounds and on-screen round/overall leaderboards."""
import random
import threading
import time

from PIL import ImageDraw, ImageFont

LOCK = threading.Lock()
ROUND_SECONDS = 120
WINNER_SECONDS = 18
WORDS = [
    ("PAPAYA", "A tropical fruit"), ("PLANET", "Earth is one"), ("GUITAR", "A musical instrument"),
    ("KETTLE", "Used to boil water"), ("MONKEY", "An animal that climbs trees"),
    ("RAINBOW", "Appears after rain sometimes"), ("PYTHON", "A programming language and a snake"),
    ("COFFEE", "A popular hot drink"), ("KERALAM", "Another name for Kerala"), ("MUSIC", "You are listening to it"),
    ("BANANA", "A yellow fruit"), ("STREAM", "What KAXMOK is doing right now"),
]
state = {
    "round": 0, "word": "", "hint": "", "started": 0.0, "winner": "",
    "winner_answer": "", "winner_until": 0.0, "round_scores": {}, "totals": {},
    "recent_winners": [], "last_announce": 0.0,
}
enabled = True


def _new_round(now=None):
    now = now or time.time()
    word, hint = random.choice(WORDS)
    state.update(round=state["round"] + 1, word=word, hint=hint, started=now,
                 winner="", winner_answer="", winner_until=0.0, round_scores={})
    state["last_announce"] = now
    print(f"[WORD GAME] Round {state['round']} started. Hint: {hint}", flush=True)


def handle_message(viewer_name, message, now=None):
    """Call once for each chat message. Returns a short event string or empty string."""
    now = now or time.time()
    text = " ".join((message or "").strip().upper().split())
    with LOCK:
        if not state["word"]:
            _new_round(now)
        if (state["winner"] and now >= state["winner_until"]) or (not state["winner"] and now - state["started"] >= ROUND_SECONDS):
            _new_round(now)
        if state["winner"]:
            return ""
        if text != state["word"]:
            return ""
        name = (viewer_name or "viewer").strip()[:40]
        state["winner"] = name
        state["winner_answer"] = state["word"]
        state["winner_until"] = now + WINNER_SECONDS
        state["round_scores"][name] = state["round_scores"].get(name, 0) + 10
        state["totals"][name] = state["totals"].get(name, 0) + 10
        state["recent_winners"].insert(0, {"name": name, "round": state["round"], "points": 10})
        state["recent_winners"] = state["recent_winners"][:5]
        print(f"[WORD GAME] Round {state['round']} winner: {name} ({state['word']})", flush=True)
        return f"Round {state['round']} winner: {name}"


def tick(now=None):
    now = now or time.time()
    with LOCK:
        if not state["word"] or (state["winner"] and now >= state["winner_until"]) or (not state["winner"] and now - state["started"] >= ROUND_SECONDS):
            _new_round(now)


def draw_game(draw, width=1920, height=1080):
    """Draw a compact game card and leaderboard over the existing background."""
    now = time.time()
    tick(now)
    with LOCK:
        round_no = state["round"]
        word = state["word"]
        hint = state["hint"]
        winner = state["winner"] if now < state["winner_until"] else ""
        totals = sorted(state["totals"].items(), key=lambda item: (-item[1], item[0].lower()))[:5]
        recent = list(state["recent_winners"][:3])
        elapsed = max(0, now - state["started"])
        remaining = max(0, ROUND_SECONDS - int(elapsed))
        masked = " ".join(ch if ch == " " else (ch if winner else "_") for ch in word)
    # Right-side panel designed to remain readable over changing backgrounds.
    x1, y1, x2, y2 = 1320, 90, 1850, 690
    draw.rounded_rectangle((x1, y1, x2, y2), radius=28, fill=(5, 9, 25, 218), outline=(117, 137, 255, 230), width=3)
    gold = (255, 211, 112, 255)
    white = (244, 247, 255, 255)
    muted = (177, 190, 220, 255)
    draw.text((x1 + 28, y1 + 22), "KAXMOK • WORD CHALLENGE", font=_font(25, True), fill=gold)
    draw.text((x1 + 28, y1 + 70), f"ROUND {round_no:02d}  •  {remaining // 60:02d}:{remaining % 60:02d}", font=_font(20, True), fill=muted)
    draw.text((x1 + 28, y1 + 115), masked, font=_font(48, True), fill=white)
    draw.text((x1 + 28, y1 + 180), "HINT: " + hint, font=_font(19, False), fill=muted)
    if winner:
        draw.rounded_rectangle((x1 + 18, y1 + 225, x2 - 18, y1 + 310), radius=16, fill=(35, 44, 74, 245))
        draw.text((x1 + 32, y1 + 237), "ROUND WINNER  +10 XP", font=_font(19, True), fill=gold)
        draw.text((x1 + 32, y1 + 270), winner[:25], font=_font(25, True), fill=white)
    else:
        draw.text((x1 + 28, y1 + 235), "TYPE YOUR GUESS IN LIVE CHAT", font=_font(18, True), fill=gold)
    yy = y1 + 330
    draw.text((x1 + 28, yy), "TOP PLAYERS", font=_font(21, True), fill=white)
    yy += 34
    if not totals:
        draw.text((x1 + 28, yy), "Be first to win this round!", font=_font(18), fill=muted)
        yy += 28
    for i, (name, score) in enumerate(totals, 1):
        draw.text((x1 + 28, yy), f"{i}. {name[:22]}", font=_font(18, True), fill=white)
        draw.text((x2 - 95, yy), f"{score} XP", font=_font(18, True), fill=gold)
        yy += 29
    if recent:
        yy += 6
        draw.text((x1 + 28, yy), "RECENT ROUND WINNERS", font=_font(16, True), fill=muted)
        yy += 25
        for item in recent[:3]:
            draw.text((x1 + 28, yy), f"R{item['round']}  {item['name'][:24]}", font=_font(16), fill=white)
            yy += 23


def _font(size, bold=False):
    paths = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold
             else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()
