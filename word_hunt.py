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

# Shared game state used by the round loop, answer checker and overlay renderer.
_STATE = {
    "category": "GET READY",
    "answers": ["ready"],
    "clues": ["A new character is coming.", "Watch the next clue.", "Guess in live chat."],
    "round": 0,
    "started_at": time.monotonic(),
    "ends_at": 0.0,
    "results_until": 0.0,
    "status": "waiting",
    "last_finder": "",
    "last_answer": "",
    "round_scores": {},
    "scores": {},
    "used": [],
    "used_count": 0,
}

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
    ("MALAYALAM MOVIES", ["manjummel boys", "subhash"], ["My friends refuse to give up on me.", "A trip with friends turns into a rescue mission.", "I am Subhash from Manjummel Boys."]),
    ("MALAYALAM MOVIES", ["ranga", "rangannan"], ["I have a very unusual way of welcoming guests.", "My world is full of strange rules and rituals.", "I am Fahadh Faasil's character in Aavesham."]),
    ("MALAYALAM MOVIES", ["amban", "ambili"], ["I am fiercely loyal to my gang leader.", "I am known for my funny, fearless energy.", "I am a memorable character in Aavesham."]),
    ("MALAYALAM MOVIES", ["murugan", "pulimurugan"], ["I am known for my courage in the forest.", "My village faces a dangerous animal threat.", "Mohanlal plays me in Pulimurugan."]),
    ("MALAYALAM MOVIES", ["unni mukundan", "marco"], ["People know me for my intense screen presence.", "My story is connected to the movie Marco.", "I am the title character played by Unni Mukundan."]),
    ("MALAYALAM MOVIES", ["arjun", "charlie"], ["I live life on my own terms.", "A young woman follows the trail of my sketches.", "Dulquer Salmaan plays me in Charlie."]),
    ("MALAYALAM MOVIES", ["koshy", "kurian koshy"], ["I am stubborn and proud.", "A road incident brings me into conflict with an officer.", "I am Prithviraj's character in Ayyappanum Koshiyum."]),
    ("MALAYALAM MOVIES", ["ayyappan nair", "ayyappan"], ["I am a police officer with a strong sense of duty.", "I clash with a wealthy ex-army man.", "Biju Menon plays me in Ayyappanum Koshiyum."]),
    ("MALAYALAM MOVIES", ["vinod", "premam george", "george david"], ["My love life changes through different stages.", "My friends and I study at a college in Kerala.", "Nivin Pauly plays me in Premam."]),
    ("MALAYALAM MOVIES", ["michael appan", "michael"], ["I return to my hometown with a hidden past.", "My story is filled with stylish action and family ties.", "Mammootty plays me in Bheeshma Parvam."]),
    ("MALAYALAM MOVIES", ["josemon"], ["I am part of a family with a mysterious secret.", "A strange event changes life in our village.", "I am a child character in the Malayalam film Romancham?"]),
    ("MALAYALAM MOVIES", ["shaji pappan", "pappan"], ["I am part of a quirky gang.", "My team is known for its comic adventures.", "Jayasurya plays me in the Aadu films."]),
    ("MALAYALAM MOVIES", ["sagar alias jacky", "sagar jacky"], ["I am stylish, mysterious and connected to the underworld.", "I have a memorable name with two parts.", "Mohanlal plays me in Sagar Alias Jacky."]),
    ("HINDI MOVIES", ["raju", "raju hera pheri"], ["I am always looking for a way to make money.", "My friends are Shyam and Baburao.", "Akshay Kumar plays me in Hera Pheri."]),
    ("HINDI MOVIES", ["circuit", "arkeshwar"], ["I am loyal to my best friend.", "I often help him with his unusual plans.", "I am Munna Bhai's sidekick."]),
    ("HINDI MOVIES", ["simran"], ["I meet someone during a trip across Europe.", "My family plans a traditional wedding for me.", "Kajol plays me in Dilwale Dulhania Le Jayenge."]),
    ("HINDI MOVIES", ["bajrangi", "pawan kumar chaturvedi"], ["I promise to help a lost child reunite with family.", "My journey takes me across a border.", "Salman Khan plays me in Bajrangi Bhaijaan."]),
    ("HINDI MOVIES", ["basanti"], ["I am a talkative village girl.", "I drive a horse cart.", "Hema Malini plays me in Sholay."]),
    ("HINDI MOVIES", ["veeru"], ["I am one of two close friends.", "I am known for my bold and funny nature.", "Dharmendra plays me in Sholay."]),
    ("HINDI MOVIES", ["raj", "raj malhotra"], ["I fall in love during a trip abroad.", "My love story involves a train and a mustard field.", "Shah Rukh Khan plays me in DDLJ."]),
    ("HINDI MOVIES", ["ranveer singh", "bajirao singham"], ["I am a police officer with a strong personality.", "I face corruption and crime head-on.", "Ajay Devgn plays me in the Singham films."]),
    ("HINDI MOVIES", ["virus", "viru sahastrabuddhe"], ["I am a strict college director.", "I believe in discipline and competition.", "Boman Irani plays me in 3 Idiots."]),
    ("TAMIL MOVIES", ["sivaji", "sivaji the boss"], ["I return home with a big dream for society.", "I want to fight corruption through education and charity.", "Rajinikanth plays me in Sivaji."]),
    ("TAMIL MOVIES", ["dilli", "kaithi dilli"], ["I am trying to reunite with my daughter.", "One night turns into a dangerous journey.", "Karthi plays me in Kaithi."]),
    ("TAMIL MOVIES", ["amar", "agent amar"], ["I investigate a series of mysterious events.", "My mission connects to a secret team.", "Fahadh Faasil plays me in Vikram."]),
    ("TAMIL MOVIES", ["adithya karikalan"], ["I am a prince in a historic epic.", "My story is part of a battle for the Chola throne.", "Vikram plays me in Ponniyin Selvan."]),
    ("TAMIL MOVIES", ["vandhiyathevan", "vandiyathevan"], ["I am a brave and witty messenger.", "I travel across the Chola kingdom.", "Karthi plays me in Ponniyin Selvan."]),
    ("TAMIL MOVIES", ["arun", "96 ram"], ["I am a photographer who revisits old memories.", "A school reunion brings back my first love.", "Vijay Sethupathi plays me in 96."]),
    ("TAMIL MOVIES", ["jigarthanda sethu", "assault sethu"], ["I am feared in Madurai.", "A filmmaker becomes interested in my life.", "Bobby Simha plays me in Jigarthanda."]),
    ("TAMIL MOVIES", ["karnan"], ["I stand up for the people of my village.", "My story is about dignity and justice.", "Dhanush plays me in Karnan."]),
    ("CARTOONS", ["patrick star", "patrick"], ["I live under the sea.", "My best friend is a yellow sponge.", "I am a pink starfish from Bikini Bottom."]),
    ("CARTOONS", ["sandy cheeks", "sandy"], ["I am a clever scientist and karate expert.", "I live in an air-filled dome underwater.", "I am SpongeBob's squirrel friend."]),
    ("CARTOONS", ["mr krabs", "eugene krabs"], ["I own a famous underwater restaurant.", "I care a lot about money.", "I am SpongeBob's boss."]),
    ("CARTOONS", ["po", "kung fu panda"], ["I am a big fan of kung fu.", "I unexpectedly become a legendary warrior.", "I am the Dragon Warrior panda."]),
    ("CARTOONS", ["shifu", "master shifu"], ["I train a group of kung fu fighters.", "I am a small but wise red panda.", "I am Po's master in Kung Fu Panda."]),
    ("CARTOONS", ["elsa", "queen elsa"], ["I have powers connected to ice and snow.", "My sister is Anna.", "I am the queen from Frozen."]),
    ("CARTOONS", ["anna frozen"], ["I am brave and optimistic.", "I go on a journey to find my sister.", "I am Elsa's younger sister in Frozen."]),
    ("CARTOONS", ["mickey mouse", "mickey"], ["I am a cheerful mouse with round ears.", "My best friends include Donald and Goofy.", "I am one of Disney's most famous characters."]),
    ("CARTOONS", ["donald duck", "donald"], ["I am a short-tempered duck.", "My voice is famously unusual.", "I am Mickey Mouse's friend."]),
    ("CARTOONS", ["garfield"], ["I love lasagna and naps.", "My owner is Jon.", "I am a lazy orange cat."]),
    ("CARTOONS", ["oggy"], ["I am a blue cat.", "Three troublesome cockroaches make my life difficult.", "I am the star of Oggy and the Cockroaches."]),
    ("CARTOONS", ["motu"], ["I get extra strength after eating my favourite snack.", "My best friend is Patlu.", "I am one half of Motu Patlu."]),
    ("CARTOONS", ["patlu"], ["I am clever and usually plan things.", "My best friend loves samosas.", "I am one half of Motu Patlu."]),
    ("CARTOONS", ["dora", "dora the explorer"], ["I go on adventures with a talking backpack.", "My friend Boots is a monkey.", "I ask viewers to help me explore."]),
    ("CARTOONS", ["peppa pig", "peppa"], ["I enjoy jumping in muddy puddles.", "My little brother is George.", "I am a cheerful little pig."]),
    ("CARTOONS", ["ash ketchum", "ash"], ["I travel with Pokémon and dream of becoming a champion.", "My first partner is Pikachu.", "I am the Pokémon trainer from the anime."]),
    ("GLOBAL FAMOUS", ["superman", "clark kent"], ["I come from the planet Krypton.", "I work as a reporter at the Daily Planet.", "I am the Man of Steel."]),
    ("GLOBAL FAMOUS", ["wonder woman", "diana prince"], ["I come from the island of Themyscira.", "I carry a lasso that reveals the truth.", "I am an Amazon superhero."]),
    ("GLOBAL FAMOUS", ["joker", "arthur fleck"], ["I am known for my chaotic sense of humour.", "I am one of Batman's most famous enemies.", "I am the Clown Prince of Crime."]),
    ("GLOBAL FAMOUS", ["thanos"], ["I believe the universe needs balance.", "I seek powerful stones.", "I am the purple villain from the Avengers films."]),
    ("GLOBAL FAMOUS", ["thor"], ["I come from Asgard.", "My weapon is a mighty hammer.", "I am the God of Thunder."]),
    ("GLOBAL FAMOUS", ["hulk", "bruce banner"], ["I am a scientist.", "Strong emotions can transform me.", "I am the giant green Avenger."]),
    ("GLOBAL FAMOUS", ["captain america", "steve rogers"], ["I carry a shield.", "I was a soldier from another era.", "I am an Avenger known as Captain America."]),
    ("GLOBAL FAMOUS", ["black panther", "tchalla"], ["I protect the nation of Wakanda.", "My suit is inspired by a big cat.", "I am the Black Panther."]),
    ("GLOBAL FAMOUS", ["deadpool", "wade wilson"], ["I often break the fourth wall.", "I am known for jokes and a red suit.", "I am the Merc with a Mouth."]),
    ("GLOBAL FAMOUS", ["gandalf"], ["I carry a staff and guide a fellowship.", "I appear in Middle-earth.", "I am the wizard from The Lord of the Rings."]),
    ("GLOBAL FAMOUS", ["frodo baggins", "frodo"], ["I inherit a very important ring.", "I travel with Sam to Mount Doom.", "I am the hobbit at the centre of The Lord of the Rings."]),
    ("GLOBAL FAMOUS", ["james bond", "007"], ["I work for a secret intelligence service.", "My code number is 007.", "I am a famous British secret agent."]),
    ("GLOBAL FAMOUS", ["indiana jones"], ["I am an archaeologist and adventurer.", "I wear a fedora and carry a whip.", "I am the hero of the Indiana Jones films."]),
    ("GLOBAL FAMOUS", ["yoda"], ["I speak with an unusual word order.", "I train Jedi knights.", "I am a small green Jedi master from Star Wars."]),
    ("GLOBAL FAMOUS", ["darth vader"], ["I wear a black helmet and breathe mechanically.", "I was once a Jedi named Anakin.", "I am Luke Skywalker's father."]),
    ("GLOBAL FAMOUS", ["rocky balboa", "rocky"], ["I am an underdog boxer from Philadelphia.", "My story is about determination in the ring.", "Sylvester Stallone plays me in Rocky."]),
    ("GLOBAL FAMOUS", ["forrest gump"], ["I have a simple way of looking at life.", "I run across America.", "Tom Hanks plays me in Forrest Gump."]),
    ("GLOBAL FAMOUS", ["mario"], ["I am a plumber who explores the Mushroom Kingdom.", "My brother is Luigi.", "I am Nintendo's famous red-capped hero."]),
    ("GLOBAL FAMOUS", ["luigi"], ["I am often nervous but brave when needed.", "My brother is Mario.", "I wear a green cap."]),
    ("GLOBAL FAMOUS", ["sonic the hedgehog", "sonic"], ["I am famous for my incredible speed.", "I collect golden rings.", "I am a blue hedgehog from video games."]),
    ("GLOBAL FAMOUS", ["minions"], ["I speak a funny made-up language.", "I work for a supervillain.", "I am one of the small yellow characters from Despicable Me."])

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
    now=time.monotonic()
    with _LOCK:
        state={
            "category":_STATE["category"],"clues":list(_STATE["clues"]),
            "started_at":_STATE["started_at"],"ends_at":_STATE["ends_at"],
            "status":_STATE["status"],"round":_STATE["round"],
            "answer":_STATE["answers"][0],"last_finder":_STATE["last_finder"],
            "scores":sorted(_STATE["scores"].values(),key=lambda x:(-x["points"],x["name"].casefold()))[:8],
        }
    elapsed=max(0,now-state["started_at"])
    clue_count=min(3,1+int(elapsed//CLUE_INTERVAL))
    with Image.open(BytesIO(frame_bytes)) as source:
        base=source.convert("RGBA").resize((WIDTH,HEIGHT))
    layer=Image.new("RGBA",(WIDTH,HEIGHT),(0,0,0,0)); d=ImageDraw.Draw(layer)
    # Reserved centre-right safe zone: avoids header, chatters, spotlight, audio bars and ticker.
    x1,y1,x2,y2=420,270,1878,735
    cyan=(52,239,255,255); purple=(190,94,255,255); white=(245,248,255,255); muted=(177,195,225,255)
    d.rounded_rectangle((x1+7,y1+8,x2+7,y2+8),radius=28,fill=(0,0,0,145))
    d.rounded_rectangle((x1,y1,x2,y2),radius=28,fill=(3,8,27,246),outline=purple,width=4)
    d.text((x1+26,y1+18),"KAXMOK  /  WHO AM I?",font=_font(27,True),fill=cyan)
    d.text((x1+28,y1+57),f"ROUND {state['round']:02d}  •  FIRST CORRECT GUESS  +10 PTS",font=_font(14,True),fill=muted)
    # Two balanced columns with fixed bounds.
    lx=x1+28; split=x1+900; rx=split+24
    d.line((split,y1+100,split,y2-24),fill=(65,91,151,220),width=2)
    d.rounded_rectangle((lx,y1+98,split-22,y1+155),radius=13,fill=(35,16,73,255),outline=purple,width=2)
    d.text((lx+16,y1+115),f"CATEGORY  {state['category']}",font=_font(18,True),fill=white)
    d.text((lx,y1+175),"WHO AM I?",font=_font(24,True),fill=cyan)
    d.text((lx,y1+211),"Guess the character in live chat",font=_font(15,True),fill=muted)
    clue_top=y1+250
    for i in range(clue_count):
        yy=clue_top+i*62
        d.rounded_rectangle((lx,yy,split-22,yy+52),radius=12,fill=(13,24,54,255),outline=(57,100,165,255),width=1)
        d.text((lx+14,yy+13),f"CLUE {i+1}",font=_font(14,True),fill=cyan)
        clue=state["clues"][i]
        f=_font(15,True)
        while d.textlength(clue,font=f)>split-lx-145 and f.size>11: f=_font(f.size-1,True)
        d.text((lx+105,yy+15),clue,font=f,fill=white)
    seconds=max(0,int(state["ends_at"]-now)) if state["status"]=="live" else 0
    d.text((lx,y2-42),f"TIME LEFT  {seconds:02d}s",font=_font(19,True),fill=cyan)
    # Permanent leaderboard column.
    d.text((rx,y1+112),"ALL-TIME LEADERBOARD",font=_font(21,True),fill=cyan)
    d.text((rx,y1+145),"TOP PLAYERS  •  TOTAL POINTS",font=_font(12,True),fill=muted)
    if state["scores"]:
        for i,row in enumerate(state["scores"]):
            yy=y1+183+i*34
            d.rounded_rectangle((rx,yy,x2-26,yy+29),radius=8,fill=(15,28,54,255))
            d.text((rx+12,yy+6),f"{i+1:02d}",font=_font(13,True),fill=purple if i else cyan)
            d.text((rx+52,yy+6),row["name"][:24],font=_font(13,True),fill=white)
            pts=f"{row['points']} PTS"
            tw=d.textbbox((0,0),pts,font=_font(12,True))[2]
            d.text((x2-42-tw,yy+7),pts,font=_font(12,True),fill=cyan)
    else:
        d.text((rx,y1+210),"No players yet — be first!",font=_font(16,True),fill=white)
    if state["status"]=="results":
        result=f"{state['last_finder'][:24]} GOT IT!  +10" if state["last_finder"] else f"ANSWER: {state['answer'].upper()}"
        d.text((rx,y2-55),result,font=_font(17,True),fill=purple)
    out=BytesIO(); Image.alpha_composite(base,layer).convert("RGB").save(out,format="JPEG",quality=80)
    return out.getvalue()
