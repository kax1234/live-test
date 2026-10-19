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
_answered = {}
_round_no = 0
_question = None
_started = 0.0
_phase = "waiting"
_last_winner = ""
_last_answer = ""


def _start_round(now):
    global _round_no, _question, _started, _phase, _last_winner, _last_answer, _answered
    choices = [q for q in QUESTIONS if q != _question] or QUESTIONS
    _question = random.choice(choices)
    _round_no += 1
    _started = now
    _phase = "open"
    _last_winner = ""
    _last_answer = ""
    _answered = set()


def tick(now=None):
    global _phase, _last_winner, _last_answer
    now = time.monotonic() if now is None else now
    with _lock:
        if _question is None:
            _start_round(now)
        elif _phase == "open" and now - _started >= ROUND_SECONDS:
            _phase = "reveal"
            _last_answer = _question[2]
            correct = [name for name, answer in _answered.items() if answer == _question[2]]
            _last_winner = correct[0] if correct else ""
        elif _phase == "reveal" and now - _started >= ROUND_SECONDS + REVEAL_SECONDS:
            _start_round(now)


def handle_message(author, message):
    """Score one public A/B/C answer per viewer in each round."""
    msg = (message or "").strip().lower()
    if msg not in ("!a", "!b", "!c", "a", "b", "c"):
        return False
    answer = msg.replace("!", "").upper()
    with _lock:
        if _phase != "open" or _question is None or author in _answered:
            return False
        _answered[author] = answer
        if answer == _question[2]:
            _scores[author] = _scores.get(author, 0) + 1
    return True


def get_state(now=None):
    tick(now)
    now = time.monotonic() if now is None else now
    with _lock:
        if _question is None:
            return {"active": False}
        elapsed = now - _started
        seconds = max(0, int(ROUND_SECONDS - elapsed + 0.999)) if _phase == "open" else 0
        ranked = sorted(_scores.items(), key=lambda item: (-item[1], item[0].casefold()))[:3]
        return {
            "active": True, "round": _round_no, "phase": _phase,
            "question": _question[0], "options": tuple(zip(LETTERS, _question[1])),
            "seconds": seconds, "answer": _last_answer, "winner": _last_winner,
            "top": tuple(ranked),
        }
