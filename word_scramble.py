"""KAXMOK Word Scramble: timed chat puzzle with first-correct scoring."""
import random
import threading
import time
import re

_LOCK = threading.RLock()
_WORDS = [
    ("MALAYALAM", "A language spoken in Kerala"),
    ("MUSIC", "What keeps the livestream alive"),
    ("CINEMA", "Movies are also called this"),
    ("RAINBOW", "Seven colours in the sky"),
    ("GUITAR", "A six-string musical instrument"),
    ("GALAXY", "A huge collection of stars"),
    ("POPCORN", "A classic movie-time snack"),
    ("THUNDER", "A loud sound during a storm"),
    ("JOURNEY", "A trip from one place to another"),
    ("MELODY", "A tune that is easy to remember"),
    ("PUZZLE", "A challenge for your brain"),
    ("SUNRISE", "The start of a new day"),
    ("HEADPHONE", "You wear these to enjoy music"),
    ("KEYBOARD", "You type on this"),
    ("BUTTERFLY", "An insect with colourful wings"),
]
_ROUND_SECONDS = 20
_scores = {}
_round_number = 0
_round_started = 0.0
_word = ""
_scrambled = ""
_hint = ""
_winner = ""
_last_winners = []


def _new_round(now):
    global _round_number, _round_started, _word, _scrambled, _hint, _winner
    _round_number += 1
    _word, _hint = random.choice(_WORDS)
    letters = list(_word)
    for _ in range(8):
        random.shuffle(letters)
        candidate = "".join(letters)
        if candidate != _word:
            break
    _scrambled = candidate if candidate != _word else _word[::-1]
    _round_started = now
    _winner = ""


def _ensure_round(now):
    if not _word or now - _round_started >= _ROUND_SECONDS:
        _new_round(now)


def handle_message(message, author, now=None):
    global _winner
    text = re.sub(r"[^A-Z]", "", (message or "").upper())
    if not text:
        return None
    stamp = time.time() if now is None else float(now)
    with _LOCK:
        _ensure_round(stamp)
        if _winner or text != _word:
            return None
        _winner = (author or "viewer").strip()[:32] or "viewer"
        key = _winner.casefold()
        _scores[key] = {"name": _winner, "points": _scores.get(key, {}).get("points", 0) + 10, "wins": _scores.get(key, {}).get("wins", 0) + 1}
        _last_winners.append({"name": _winner, "word": _word, "round": _round_number})
        del _last_winners[:-5]
        return f"WORD SCRAMBLE: {_winner} solved {_word}! +10 points."


def snapshot(now=None):
    stamp = time.time() if now is None else float(now)
    with _LOCK:
        _ensure_round(stamp)
        remaining = max(0, _ROUND_SECONDS - int(stamp - _round_started))
        top = sorted(_scores.values(), key=lambda row: (-row["points"], row["name"].casefold()))[:5]
        return {"round": _round_number, "scrambled": _scrambled, "hint": _hint,
                "remaining": remaining, "winner": _winner, "answer": _word if _winner else "",
                "top": [dict(row) for row in top], "wins": sum(row["wins"] for row in _scores.values()),
                "last_winners": [dict(row) for row in _last_winners]}
