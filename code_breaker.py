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

def normalise(s): return re.sub(r"\\D","",s or "")

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
        s={k:(v.copy() if isinstance(v,dict) else v) for k,v in STATE.items()}
    with Image.open(BytesIO(frame_bytes)) as im: base=im.convert("RGBA").resize((W,H))
    layer=Image.new("RGBA",(W,H),(0,0,0,0)); d=ImageDraw.Draw(layer)
    x1,y1,x2,y2=1110,135,1885,945
    cyan=(52,239,255,255); purple=(190,94,255,255); white=(245,248,255,255); muted=(177,195,225,255)
    d.rounded_rectangle((x1+8,y1+10,x2+8,y2+10),radius=34,fill=(0,0,0,135))
    d.rounded_rectangle((x1,y1,x2,y2),radius=34,fill=(3,8,27,249),outline=purple,width=5)
    d.text((x1+30,y1+24),"KAXMOK  /  CODE BREAKER",font=font(32,True),fill=cyan)
    d.text((x1+32,y1+75),f"ROUND {s['round']:02d}  •  CRACK THE 4-DIGIT CODE  •  +10 PTS",font=font(16,True),fill=muted)
    d.text((x1+45,y1+165),"GUESS A 4-DIGIT NUMBER",font=font(27,True),fill=white)
    d.text((x1+45,y1+225),"All digits are different. Type your guess in chat.",font=font(19),fill=muted)
    d.rounded_rectangle((x1+45,y1+300,x2-45,y1+410),radius=20,fill=(13,24,54,255),outline=cyan,width=3)
    shown=s["secret"] if s["status"]=="results" else "  •  •  •  •"
    d.text((x1+90,y1+325),shown,font=font(48,True),fill=cyan)
    seconds=max(0,int(s["ends"]-now)) if s["status"]=="live" else 0
    d.text((x1+45,y1+455),f"TIME LEFT  {seconds:02d}s",font=font(25,True),fill=cyan)
    d.text((x1+45,y1+515),s["feedback"] or "Feedback appears after each valid guess",font=font(21,True),fill=white)
    if s["last_finder"]: d.text((x1+45,y1+580),f"{s['last_finder']} CRACKED IT! +10",font=font(24,True),fill=purple)
    d.text((x1+45,y1+650),"HOW TO PLAY",font=font(22,True),fill=cyan)
    d.text((x1+45,y1+700),"4 unique digits  •  60 seconds  •  First correct guess wins",font=font(17,True),fill=white)
    rows=sorted(s["scores"].values(),key=lambda r:(-r["points"],r["name"].casefold()))[:8]
    d.text((x1+45,y1+770),"TOP PLAYERS",font=font(18,True),fill=cyan)
    for i,row in enumerate(rows):
        d.text((x1+45+i*88,y1+815),f"{i+1}. {row['name'][:8]} {row['points']}",font=font(13,True),fill=white)
    out=BytesIO(); Image.alpha_composite(base,layer).convert("RGB").save(out,format="JPEG",quality=82)
    return out.getvalue()
