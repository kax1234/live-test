"""Who Am I? character-guessing game for the KAXMOK YouTube livestream."""
import random
import re
import threading
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1920, 1080
ROUND_SECONDS = 48
RESULT_SECONDS = 7
CLUE_INTERVAL = 12
_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False

# Each entry: category, accepted answers, three clues (from harder to easier).
CHARACTERS = [
    ("MALAYALAM MOVIES", ["georgekutty", "george kutty"], ["I always think several steps ahead.", "My family is at the centre of a crime mystery.", "I am the father in Drishyam."]),
    ("MALAYALAM MOVIES", ["aadu thoma", "thoma", "thoma chakko"], ["People know me for my explosive temper.", "My story is connected to a famous old family feud.", "Mohanlal plays me in Spadikam."]),
    ("MALAYALAM MOVIES", ["sethurama iyer", "sethuramaiyer", "sethuraman"], ["I notice the smallest details.", "I solve complicated murder cases.", "I am the famous CBI officer played by Mammootty."]),
    ("MALAYALAM MOVIES", ["das an", "das", "dasettan"], ["My friend is often beside me in comic situations.", "I am part of a legendary comedy duo.", "I am one half of Dasan and Vijayan."]),
    ("MALAYALAM MOVIES", ["vijayan"], ["I get into trouble with my closest friend.", "My name is often said together with Dasan.", "I am one half of Dasan and Vijayan."]),
    ("MALAYALAM MOVIES", ["neelakandan", "mangalassery neelakandan"], ["My pride and reputation are legendary.", "I have a strong connection to a traditional Kerala household.", "Mohanlal plays me in Devasuram."]),
    ("MALAYALAM MOVIES", ["vasco", "vasco da gama"], ["My gang and I are known around Fort Kochi.", "I have a memorable nickname linked to a famous explorer.", "Mohanlal plays me in Chotta Mumbai."]),
    ("MALAYALAM MOVIES", ["stephen nedumpally", "stephen", "abraham khureshi", "abraham quraishi"], ["My public image hides a powerful identity.", "People know me by another name too.", "I am the central character of Lucifer."]),
    ("MALAYALAM MOVIES", ["jaison", "jaison tekkel"], ["An unexpected event changes my ordinary life.", "I discover unusual powers in a small Kerala town.", "I am the hero of Minnal Murali."]),
    ("MALAYALAM MOVIES", ["manavalan", "manavalan weds"], ["My wedding plans become a comedy of errors.", "My friends are never far from chaos.", "I am a memorable character from the movie of the same name?"]),
    ("HINDI MOVIES", ["rancho", "phunsukh wangdu", "phunsuk wangdu"], ["I believe learning should be about understanding.", "My two college friends never forget me.", "I am the central character of 3 Idiots."]),
    ("HINDI MOVIES", ["munna bhai", "murli prasad sharma", "munna"], ["I have a big heart and a street-smart style.", "My best friend is Circuit.", "Sanjay Dutt plays me in the Munna Bhai films."]),
    ("HINDI MOVIES", ["gabbar singh", "gabbar"], ["My name became a famous movie catchphrase.", "I am feared by a village.", "I am the iconic villain of Sholay."]),
    ("HINDI MOVIES", ["chulbul pandey", "chulbul"], ["I have a playful attitude and a unique style.", "My belt and sunglasses are part of my look.", "Salman Khan plays me in Dabangg."]),
    ("HINDI MOVIES", ["geet", "geet dhillon"], ["I talk a lot and follow my heart.", "A train journey changes my life.", "Kareena Kapoor plays me in Jab We Met."]),
    ("HINDI MOVIES", ["mogambo"], ["I have a dramatic way of speaking.", "I command a secret base.", "My famous line begins with 'Mogambo khush hua'."]),
    ("HINDI MOVIES", ["babu bhaiya", "baburao ganpatrao apte", "baburao"], ["My glasses and comic timing are unforgettable.", "I share a chaotic house with Raju and Shyam.", "Paresh Rawal plays me in Hera Pheri."]),
    ("HINDI MOVIES", ["kabir khan", "kabir"], ["I coach a team that faces huge expectations.", "My story is about teamwork and determination.", "Shah Rukh Khan plays me in Chak De! India."]),
    ("TAMIL MOVIES", ["vikram", "arun kumar vikram"], ["I have a hidden past and a dangerous mission.", "My story is linked to a secret organisation.", "Kamal Haasan plays me in Vikram."]),
    ("TAMIL MOVIES", ["rolex"], ["My arrival is brief but unforgettable.", "I am connected to a drug empire.", "Suriya plays me in the end of Vikram."]),
    ("TAMIL MOVIES", ["amb i", "ambi", "anniyan", "remo"], ["I have more than one personality.", "My actions are connected to a strange sense of justice.", "Vikram plays me in Anniyan."]),
    ("TAMIL MOVIES", ["durai singam", "duraisingam", "singam"], ["I am known for my speed and strong sense of duty.", "I work as a police officer.", "Suriya plays me in the Singam films."]),
    ("TAMIL MOVIES", ["manikkam", "muthu", "muthuvel pandian", "jailer"], ["I appear calm, but I have a powerful past.", "My family story pulls me into action.", "Rajinikanth plays me in Jailer."]),
    ("TAMIL MOVIES", ["leo", "parthiban", "parthi"], ["I run a quiet business away from my past.", "My family lives in Himachal Pradesh.", "Vijay plays me in Leo."]),
    ("CARTOONS", ["doraemon"], ["I have a pocket full of futuristic gadgets.", "I travel from the future to help a boy.", "I am a blue robotic cat."]),
    ("CARTOONS", ["shinchan", "shinnosuke"], ["I love silly jokes and dancing.", "My family often gets embarrassed by me.", "I am a mischievous five-year-old from Kasukabe."]),
    ("CARTOONS", ["nobita", "nobi"], ["I often need help with homework.", "My best friend has amazing gadgets.", "I am the boy Doraemon helps."]),
    ("CARTOONS", ["spongebob", "spongebob squarepants"], ["I work at a fast-food restaurant under the sea.", "My best friend is Patrick.", "I am a cheerful yellow sea sponge."]),
    ("CARTOONS", ["tom"], ["I spend much of my time chasing someone.", "My rival is a clever little mouse.", "I am the cat in Tom and Jerry."]),
    ("CARTOONS", ["jerry"], ["I am small, clever and hard to catch.", "A cat is always chasing me.", "I am the mouse in Tom and Jerry."]),
    ("CARTOONS", ["pikachu"], ["I am a loyal companion to a young trainer.", "I can store electricity in my cheeks.", "I am a famous yellow Pokémon."]),
    ("CARTOONS", ["scooby doo", "scooby"], ["I love snacks and get scared easily.", "I solve mysteries with a group of friends.", "I am a talking Great Dane."]),
    ("CARTOONS", ["ben tennyson", "ben 10", "ben"], ["I can transform into many alien forms.", "A special device gives me my powers.", "I am the hero of Ben 10."]),
    ("GLOBAL FAMOUS", ["sherlock holmes", "sherlock"], ["I solve mysteries using observation and deduction.", "My close companion is Dr. Watson.", "My famous address is 221B Baker Street."]),
    ("GLOBAL FAMOUS", ["harry potter", "harry"], ["I received a letter that changed my life.", "I study at Hogwarts.", "I am a young wizard with a lightning-shaped scar."]),
    ("GLOBAL FAMOUS", ["jack sparrow", "captain jack sparrow"], ["My plans rarely go exactly as expected.", "I am obsessed with finding and keeping a ship.", "I am the eccentric pirate captain from Pirates of the Caribbean."]),
    ("GLOBAL FAMOUS", ["tony stark", "iron man"], ["I am a genius inventor and billionaire.", "I built a powerful suit of armour.", "I am also known as Iron Man."]),
    ("GLOBAL FAMOUS", ["peter parker", "spiderman", "spider man"], ["I balance everyday life with secret responsibilities.", "A spider bite gave me special abilities.", "I am Spider-Man."]),
    ("GLOBAL FAMOUS", ["batman", "bruce wayne"], ["I work in the shadows of Gotham City.", "I have no superpowers, but I use technology and training.", "I am the Dark Knight."]),
    ("GLOBAL FAMOUS", ["wednesday addams", "wednesday"], ["I have a very dry sense of humour.", "I attend Nevermore Academy.", "My name is also the title of a popular series."]),
    ("GLOBAL FAMOUS", ["mr bean", "mister bean", "bean"], ["I rarely need words to make people laugh.", "I have a teddy bear called Teddy.", "Rowan Atkinson plays me."]),
    ("GLOBAL FAMOUS", ["elsa"], ["I have powers connected to ice and snow.", "My sister is Anna.", "I sing 'Let It Go' in Frozen."]),
    ("GLOBAL FAMOUS", ["shrek"], ["I prefer peace and quiet in my swamp.", "My best friend is a talkative donkey.", "I am a green ogre."]),
]


def _normalise(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _new_round():
    with _LOCK:
        remaining = [c for c in CHARACTERS if c[1][0] not in _STATE["used"]]
        if not remaining:
            _STATE["used"] = []
            remaining = CHARACTERS[:]
        category, answers, clues = random.choice(remaining)
        _STATE["used"].append(answers[0])
        _STATE.update({
            "category": category, "answers": answers, "clues": clues,
            "round": _STATE["round"] + 1, "started_at": time.monotonic(),
            "ends_at": time.monotonic() + ROUND_SECONDS, "status": "live",
            "last_finder": "", "last_answer": answers[0],
            "round_scores": {}, "used_count": len(_STATE["used"]),
        })
    print(f"[WHO AM I] Round {_STATE['round']} started | {category} | answer hidden.", flush=True)


def _game_loop():
    while not _STOP.is_set():
        try:
            with _LOCK:
                expired = _STATE["status"] == "live" and time.monotonic() >= _STATE["ends_at"]
                start_next = _STATE["status"] in {"waiting", "generating"} or (
                    _STATE["status"] == "results" and time.monotonic() >= _STATE["results_until"])
                if expired:
                    _STATE["status"] = "results"
                    _STATE["last_finder"] = ""
                    _STATE["results_until"] = time.monotonic() + RESULT_SECONDS
                    start_next = False
            if start_next:
                _new_round()
            _STOP.wait(0.5)
        except Exception as exc:
            with _LOCK:
                _STATE["status"] = "generating"
            print(f"[WHO AM I] Round error: {type(exc).__name__}: {exc}", flush=True)
            _STOP.wait(3)


def start():
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_game_loop, daemon=True, name="who-am-i").start()


def handle_guess(author, message):
    guess = _normalise(message)
    if len(guess) < 2:
        return False
    name = (author or "viewer").strip()[:32] or "viewer"
    with _LOCK:
        if _STATE["status"] != "live":
            return False
        if guess not in {_normalise(a) for a in _STATE["answers"]}:
            return False
        key = name.casefold()
        score = _STATE["scores"].get(key, {"name": name, "points": 0})
        score["name"] = name
        score["points"] += 10
        _STATE["scores"][key] = score
        round_score = _STATE["round_scores"].get(key, {"name": name, "points": 0})
        round_score["name"] = name
        round_score["points"] += 10
        _STATE["round_scores"][key] = round_score
        _STATE["last_finder"] = name
        _STATE["status"] = "results"
        _STATE["results_until"] = time.monotonic() + RESULT_SECONDS
        print(f"[WHO AM I] {name} guessed {_STATE['answers'][0]} (+10).", flush=True)
    return True


def render_overlay(frame_bytes):
    now = time.monotonic()
    with _LOCK:
        state = {
            "category": _STATE["category"], "clues": list(_STATE["clues"]),
            "started_at": _STATE["started_at"], "ends_at": _STATE["ends_at"],
            "status": _STATE["status"], "round": _STATE["round"],
            "answer": _STATE["answers"][0], "last_finder": _STATE["last_finder"],
            "scores": sorted(_STATE["scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:3],
            "round_scores": sorted(_STATE["round_scores"].values(), key=lambda x: (-x["points"], x["name"].casefold()))[:5],
            "used_count": _STATE["used_count"],
        }
    elapsed = max(0, now - state["started_at"])
    clue_count = min(3, 1 + int(elapsed // CLUE_INTERVAL))
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGBA").resize((WIDTH, HEIGHT))
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # Larger right-side panel: approximately 710 x 800 pixels on a 1920x1080 stream.
    x1, y1, x2, y2 = 1165, 135, 1885, 945
    cyan, purple = (52, 239, 255, 255), (190, 94, 255, 255)
    white, muted = (245, 248, 255, 255), (177, 195, 225, 255)
    d.rounded_rectangle((x1 + 8, y1 + 10, x2 + 8, y2 + 10), radius=34, fill=(0, 0, 0, 135))
    d.rounded_rectangle((x1, y1, x2, y2), radius=34, fill=(3, 8, 27, 247), outline=purple, width=5)
    d.rounded_rectangle((x1 + 12, y1 + 12, x2 - 12, y1 + 105), radius=25, fill=(17, 20, 55, 255))
    d.text((x1 + 34, y1 + 27), "KAXMOK  /  WHO AM I?", font=_font(34, True), fill=cyan)
    d.text((x1 + 36, y1 + 76), f"ROUND {state['round']:02d}     •     FIRST CORRECT GUESS  +10 PTS", font=_font(16, True), fill=muted)
    d.rounded_rectangle((x1 + 28, y1 + 132, x2 - 28, y1 + 194), radius=16, fill=(35, 16, 73, 255), outline=purple, width=2)
    d.text((x1 + 48, y1 + 148), f"CATEGORY: {state['category']}", font=_font(24, True), fill=white)
    d.text((x1 + 34, y1 + 220), "WHO AM I?", font=_font(30, True), fill=cyan)
    d.text((x1 + 35, y1 + 264), "Read the clues and type the character's name in chat", font=_font(15, True), fill=muted)

    clue_y = [y1 + 315, y1 + 445, y1 + 575]
    for i in range(clue_count):
        top = clue_y[i]
        d.rounded_rectangle((x1 + 28, top, x2 - 28, top + 106), radius=17,
                            fill=(13, 24, 54, 255), outline=(57, 100, 165, 255), width=2)
        d.rounded_rectangle((x1 + 42, top + 20, x1 + 105, top + 82), radius=14,
                            fill=(43, 25, 91, 255), outline=purple, width=2)
        d.text((x1 + 55, top + 34), str(i + 1), font=_font(30, True), fill=cyan)
        clue = state["clues"][i]
        words, lines, line = clue.split(), [], ""
        for word in words:
            candidate = (line + " " + word).strip()
            if d.textbbox((0, 0), candidate, font=_font(19, True))[2] > 535 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        for j, text_line in enumerate(lines[:2]):
            d.text((x1 + 128, top + 25 + j * 29), text_line, font=_font(19, True), fill=white)

    seconds = max(0, int(state["ends_at"] - now)) if state["status"] == "live" else 0
    d.rounded_rectangle((x1 + 28, y1 + 710, x2 - 28, y1 + 765), radius=15,
                        fill=(9, 34, 60, 255), outline=cyan, width=2)
    d.text((x1 + 52, y1 + 722), f"TIME LEFT     {seconds:02d} SECONDS", font=_font(24, True), fill=cyan)
    d.text((x1 + 34, y2 - 38), "A NEW CLUE APPEARS EVERY 12 SECONDS", font=_font(15, True), fill=muted)

    if state["status"] == "results":
        d.rounded_rectangle((x1 + 18, y1 + 18, x2 - 18, y2 - 18), radius=27,
                            fill=(3, 7, 26, 250), outline=cyan, width=3)
        d.text((x1 + 55, y1 + 70), "CORRECT GUESS!" if state["last_finder"] else "TIME'S UP!", font=_font(39, True), fill=cyan)
        d.text((x1 + 55, y1 + 160), f"ANSWER: {state['answer'][:32].upper()}", font=_font(31, True), fill=white)
        if state["last_finder"]:
            d.text((x1 + 55, y1 + 220), f"FOUND BY  {state['last_finder'][:24]}  +10 PTS", font=_font(21, True), fill=purple)
        else:
            d.text((x1 + 55, y1 + 220), "Nobody guessed the character this round.", font=_font(18, True), fill=purple)
        d.text((x1 + 55, y1 + 300), "ROUND LEADERBOARD", font=_font(24, True), fill=cyan)
        for i, row in enumerate(state["round_scores"][:5]):
            yy = y1 + 360 + i * 57
            d.text((x1 + 70, yy), f"{i+1}. {row['name'][:22]}", font=_font(22, True), fill=white)
            d.text((x2 - 160, yy), f"+{row['points']}", font=_font(22, True), fill=cyan)
        d.text((x1 + 55, y2 - 85), "NEXT CHARACTER COMING UP...", font=_font(17, True), fill=muted)

    output = BytesIO()
    Image.alpha_composite(base, layer).convert("RGB").save(output, format="JPEG", quality=82)
    return output.getvalue()


_STATE = {
    "round": 0, "category": "MIXED", "answers": [""], "clues": ["", "", ""],
    "started_at": 0.0, "ends_at": 0.0, "status": "waiting",
    "scores": {}, "round_scores": {}, "last_finder": "", "last_answer": "",
    "results_until": 0.0, "used": [], "used_count": 0,
}
