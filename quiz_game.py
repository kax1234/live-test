"""Low-overhead public-chat quiz for the KAXMOK livestream."""
import random
import threading
import time

QUESTIONS = [
    ("Which planet is known as the Red Planet?", ("Venus", "Mars", "Jupiter"), "B"),
    ("How many sides does a hexagon have?", ("5", "6", "8"), "B"),
    ("What is the capital of Japan?", ("Seoul", "Beijing", "Tokyo"), "C"),
    ("Which ocean is the largest?", ("Pacific", "Indian", "Arctic"), "A"),
    ("How many minutes are in 2 hours?", ("100", "120", "140"), "B"),
    ("Which gas do plants absorb?", ("Oxygen", "Hydrogen", "Carbon dioxide"), "C"),
    ("What is 9 × 7?", ("56", "63", "72"), "B"),
    ("Which animal is the tallest?", ("Giraffe", "Elephant", "Camel"), "A"),
    ("How many colours are in a traditional rainbow?", ("5", "6", "7"), "C"),
    ("Which is the nearest star to Earth?", ("Sirius", "The Sun", "Polaris"), "B"),
    ("Which language runs in a web browser?", ("JavaScript", "C", "SQL"), "A"),
    ("What is the chemical symbol for water?", ("CO2", "H2O", "O2"), "B"),
    ("Which continent is India in?", ("Europe", "Africa", "Asia"), "C"),
    ("How many days are in a leap year?", ("365", "366", "364"), "B"),
    ("Which instrument has keys, pedals and strings?", ("Piano", "Flute", "Drum"), "A"),
]
LETTERS = ("A", "B", "C")
ROUND_SECONDS = 35
REVEAL_SECONDS = 8
_lock = threading.Lock()
_scores = {}
_round_no = 0
_question = None
_started = 0.0
_phase = "waiting"
_last_winner = ""
_last_answer = ""


def _start_round(now):
    global _round_no, _question, _started, _phase, _last_winner, _last_answer
    choices = list(QUESTIONS)
    if _question and len(choices) > 1:
        choices = [q for q in choices if q != _question]
    _question = random.choice(choices)
    _round_no += 1
    _started = now
    _phase = "open"
    _last_winner = ""
    _last_answer = ""


def tick(now=None):
    """Advance the round clock; safe to call from the chat polling thread."""
    global _phase
    now = time.monotonic() if now is None else now
    with _lock:
        if _question is None:
            _start_round(now)
        elif _phase == "open" and now - _started >= ROUND_SECONDS:
            _phase = "reveal"
            _last_answer = _question[2]
            ranked = sorted(_scores.items(), key=lambda item: (-item[1], item[0].casefold()))
            _last_winner = ranked[0][0] if ranked else ""
        elif _phase == "reveal" and now - _started >= ROUND_SECONDS + REVEAL_SECONDS:
            _start_round(now)


def handle_message(author, message):
    """Accept public !a/!b/!c answers; each viewer scores at most once per round."""
    msg = (message or "").strip().lower()
    if msg not in ("!a", "!b", "!c", "a", "b", "c"):
        return False
    answer = msg.replace("!", "").upper()
    with _lock:
        if _phase != "open" or _question is None:
            return False
        if author in _answered:
            return False
        _answered.add(author)
        if answer == _question[2]:
            _scores[author] = _scores.get(author, 0) + 1
    return True


_answered = set()
_original_start_round = _start_round


def _start_round(now):
    global _round_no, _question, _started, _phase, _last_winner, _last_answer, _answered
    choices = list(QUESTIONS)
    if _question and len(choices) > 1:
        choices = [q for q in choices if q != _question]
    _question = random.choice(choices)
    _round_no += 1
    _started = now
    _phase = "open"
    _last_winner = ""
    _last_answer = ""
    _answered = set()


def get_state(now=None):
    tick(now)
    now = time.monotonic() if now is None else now
    with _lock:
        if _question is None:
            return {"active": False}
        elapsed = now - _started
        open_left = max(0, int(ROUND_SECONDS - elapsed + 0.999)) if _phase == "open" else 0
        ranked = sorted(_scores.items(), key=lambda item: (-item[1], item[0].casefold()))[:3]
        return {
            "active": True,
            "round": _round_no,
            "phase": _phase,
            "question": _question[0],
            "options": tuple(zip(LETTERS, _question[1])),
            "seconds": open_left,
            "answer": _last_answer,
            "winner": _last_winner,
            "top": tuple((name, points) for name, points in ranked),
            "scores_count": len(_scores),
        }
