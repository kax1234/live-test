"""Code Breaker mini-game for KAXMOK livestream."""
import random, re, threading, time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

W,H=1920,1080
LOCK=threading.RLock()
STATE={"round":0,"secret":"","started":0.0,"ends":0.0,"status":"waiting","scores":{},"last_finder":"","last_guess":"","feedback":"","results_until":0.0}
STOP=threading.Event()
_STARTED=False
ROUND_SECONDS=60
RESULT_SECONDS=7

def font(size,bold=False):
    path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try: return ImageFont.truetype(path,size)
    except OSError: return ImageFont.load_default()

def new_round():
    with LOCK:
        digits=list("0123456789")
        random.shuffle(digits)
        STATE.update(round=STATE["round"]+1,secret="".join(digits[:4]),started=time.monotonic(),ends=time.monotonic()+ROUND_SECONDS,status="live",last_finder="",last_guess="",feedback="",results_until=0.0)
    print(f"[CODE BREAKER] Round {STATE['round']} started.",flush=True)

def loop():
    while not STOP.is_set():
        now=time.monotonic()
        with LOCK:
            expired=STATE["status"]=="live" and now>=STATE["ends"]
            next_round=STATE["status"]=="waiting" or (STATE["status"]=="results" and now>=STATE["results_until"])
            if expired:
                STATE["status"]="results"; STATE["results_until"]=now+RESULT_SECONDS
                next_round=False
        if next_round: new_round()
        STOP.wait(.4)

def start():
    global _STARTED
    if not _STARTED:
        _STARTED=True
        threading.Thread(target=loop,daemon=True,name="code-breaker").start()

def normalise(s): return re.sub(r"\D","",s or "")

def handle_guess(author,message):
    guess=normalise(message)
    if len(guess)!=4 or len(set(guess))!=4: return False
    name=(author or "viewer")[:32]
    with LOCK:
        if STATE["status"]!="live": return False
        secret=STATE["secret"]
        exact=sum(a==b for a,b in zip(guess,secret))
        misplaced=sum(min(guess.count(d),secret.count(d)) for d in set(guess))-exact
        STATE["last_guess"]=guess
        STATE["feedback"]=f"{exact} EXACT  •  {misplaced} MISPLACED"
        if guess==secret:
            key=name.casefold(); row=STATE["scores"].get(key,{"name":name,"points":0})
            row["name"]=name; row["points"]+=10; STATE["scores"][key]=row
            STATE["last_finder"]=name; STATE["status"]="results"; STATE["results_until"]=time.monotonic()+RESULT_SECONDS
            print(f"[CODE BREAKER] {name} cracked code (+10).",flush=True)
    return True

def render_overlay(frame_bytes):
    now=time.monotonic()
    with LOCK:
        state={k:(v.copy() if isinstance(v,dict) else v) for k,v in STATE.items()}
    with Image.open(BytesIO(frame_bytes)) as im:
        base=im.convert("RGBA").resize((W,H))
    layer=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(layer)
    # Same reserved centre-right safe zone as Who Am I; no overlap with stream panels.
    x1,y1,x2,y2=420,270,1878,735
    cyan=(52,239,255,255); purple=(190,94,255,255); white=(245,248,255,255); muted=(177,195,225,255)
    d.rounded_rectangle((x1+7,y1+8,x2+7,y2+8),radius=28,fill=(0,0,0,145))
    d.rounded_rectangle((x1,y1,x2,y2),radius=28,fill=(3,8,27,246),outline=purple,width=4)
    d.text((x1+26,y1+18),"KAXMOK  /  CODE BREAKER",font=font(27,True),fill=cyan)
    d.text((x1+28,y1+57),f"ROUND {state['round']:02d}  •  CRACK THE 4-DIGIT CODE  •  +10 PTS",font=font(14,True),fill=muted)
    split=x1+900; left=x1+28; right=split+26
    d.line((split,y1+100,split,y2-24),fill=(65,91,151,220),width=2)
    d.text((left,y1+115),"GUESS A 4-DIGIT NUMBER",font=font(24,True),fill=white)
    d.text((left,y1+153),"All digits are different. Type your guess in chat.",font=font(15),fill=muted)
    d.rounded_rectangle((left,y1+205,split-24,y1+300),radius=18,fill=(13,24,54,255),outline=cyan,width=2)
    shown=state["secret"] if state["status"]=="results" else "•   •   •   •"
    d.text((left+28,y1+222),shown,font=font(43,True),fill=cyan)
    seconds=max(0,int(state["ends"]-now)) if state["status"]=="live" else 0
    d.text((left,y1+325),f"TIME LEFT  {seconds:02d}s",font=font(20,True),fill=cyan)
    feedback=state["feedback"] or "Feedback appears after each valid guess"
    d.text((left,y1+365),feedback,font=font(17,True),fill=white)
    if state["last_finder"]:
        d.text((left,y1+407),f"{state['last_finder'][:26]} CRACKED IT!  +10",font=font(18,True),fill=purple)
    d.text((right,y1+112),"HOW TO PLAY",font=font(21,True),fill=cyan)
    instructions=["Guess 4 unique digits","EXACT = right digit, right place","MISPLACED = right digit, wrong place","First correct answer wins +10 points"]
    for i,line in enumerate(instructions):
        d.rounded_rectangle((right,y1+158+i*48,x2-28,y1+196+i*48),radius=9,fill=(13,24,54,255))
        d.text((right+12,y1+168+i*48),line,font=font(14,True),fill=white)
    d.text((right,y1+365),"ALL-TIME TOP PLAYERS",font=font(18,True),fill=cyan)
    rows=sorted(state["scores"].values(),key=lambda r:(-r["points"],r["name"].casefold()))[:4]
    for i,row in enumerate(rows):
        yy=y1+398+i*28
        d.text((right,yy),f"{i+1}. {row['name'][:22]}",font=font(13,True),fill=white)
        pts=f"{row['points']} PTS"; tw=d.textbbox((0,0),pts,font=font(12,True))[2]
        d.text((x2-34-tw,yy+1),pts,font=font(12,True),fill=cyan)
    out=BytesIO()
    Image.alpha_composite(base,layer).convert("RGB").save(out,format="JPEG",quality=80)
    return out.getvalue()
