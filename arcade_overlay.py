"""KAXMOK Live Arcade: lightweight local state + overlay."""
import math, threading, time
from datetime import datetime, timezone, timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

_lock = threading.RLock()
_players = {}
_recent = []
_votes = {"PORTAL": 0, "STARS": 0, "CHAOS": 0}
_round_seconds = 180
_round_started = time.time()
_round_no = 1
_status = "Type !join to enter this round"

def _font(size, bold=False):
    paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()

def _advance(now):
    global _round_started, _round_no, _votes, _status
    while now - _round_started >= _round_seconds:
        joined = [n for n,p in _players.items() if p["round"] == _round_no]
        if joined:
            winner = max(joined, key=lambda n: _players[n]["points"])
            _players[winner]["points"] += 10
            _status = f"{winner} earned +10 round bonus!"
        else: _status = "New round! Type !join to play."
        _round_no += 1
        _round_started += _round_seconds
        _votes = {"PORTAL": 0, "STARS": 0, "CHAOS": 0}

def award_message(viewer_name, message="", now=None):
    global _status
    now = time.time() if now is None else now
    name = (viewer_name or "viewer").strip()[:24] or "viewer"
    msg = (message or "").strip().lower()
    with _lock:
        _advance(now)
        p = _players.setdefault(name, {"points":0, "messages":0, "round":0, "last":now})
        p["messages"] += 1; p["last"] = now
        if msg in ("!join", "!play"):
            if p["round"] != _round_no:
                p["round"] = _round_no; p["points"] += 1
                _status = f"{name} joined the crew!"
                _recent.insert(0, f"{name} joined")
        elif msg == "!leave":
            p["round"] = 0; _status = f"{name} left the round"
            _recent.insert(0, f"{name} left")
        elif msg.startswith("!vote "):
            val = msg[6:].strip().upper()
            val = {"1":"PORTAL","2":"STARS","3":"CHAOS"}.get(val,val)
            if val in _votes:
                _votes[val] += 1; _status = f"{name} voted {val}"
                _recent.insert(0, f"{name} voted {val}")
        elif not msg.startswith("!"):
            p["points"] += 1
        del _recent[6:]
        return dict(p)

def get_points(viewer_name):
    with _lock: return _players.get(viewer_name, {}).get("points", 0)

def get_leaderboard(limit=10):
    with _lock:
        return [{"name":n,"points":p["points"]} for n,p in sorted(_players.items(), key=lambda kv:kv[1]["points"], reverse=True)[:limit]]

def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0):
    with Image.open(BytesIO(frame_bytes)) as src: base = src.convert("RGB")
    if base.size != (width,height): base = base.resize((width,height), Image.Resampling.BILINEAR)
    now=time.time(); level=max(0,min(1,float(audio_level)))
    with _lock:
        _advance(now); players=sorted(_players.items(),key=lambda kv:kv[1]["points"],reverse=True)
        joined=[n for n,p in _players.items() if p["round"]==_round_no]
        recent=list(_recent); votes=dict(_votes); status=_status; rnd=_round_no
        remain=max(0,int(_round_seconds-(now-_round_started)))
    ov=Image.new("RGBA",(width,height),(0,0,0,0)); d=ImageDraw.Draw(ov)
    navy=(4,8,24,244); panel=(9,16,43,242); purple=(157,62,255,255); cyan=(37,235,255,255); white=(239,244,255,255); muted=(155,178,215,255); pink=(255,65,207,255)
    def txt(x,y,s,size=16,color=white,bold=False): d.text((x,y),str(s),font=_font(size,bold),fill=color)
    d.rectangle((0,0,width,82),fill=navy); d.line((0,80,width,80),fill=purple,width=3)
    d.ellipse((24,16,68,60),outline=cyan,width=3); txt(82,18,"KAXMOK",30,white,True); txt(230,28,"•  24/7 MUSIC LIVE ARCADE",17,muted,True)
    txt(680,26,f"DAILY CREW CHALLENGE  •  ROUND {rnd}",18,cyan,True); txt(1290,26,"● LIVE NOW",18,(255,75,100,255),True)
    ist=timezone(timedelta(hours=5,minutes=30)); txt(1510,28,"IST "+datetime.now(ist).strftime("%I:%M %p • %d %b"),15,white,True)
    rects=[(20,105,335,870),(355,105,1295,870),(1315,105,1900,870)]
    for r in rects: d.rounded_rectangle(r,22,fill=navy,outline=(95,66,220,255),width=2)
    txt(45,128,"THE CREW",22,cyan,True); txt(45,160,"Join the live round",14,muted); d.line((42,190,310,190),fill=(64,76,130,255),width=2)
    txt(45,210,f"{len(joined):02d}",46,white,True); txt(120,229,"PLAYERS IN ROUND",13,muted,True)
    d.rounded_rectangle((44,285,310,300),7,fill=(34,28,68,255)); fw=int(266*min(1,len(joined)/20))
    if fw: d.rounded_rectangle((44,285,44+fw,300),7,fill=cyan)
    txt(45,330,"HOW TO PLAY",17,purple,True); txt(45,365,"!join  — enter round",14); txt(45,395,"!vote 1 / 2 / 3",14); txt(45,425,"Vote for next event",12,muted)
    d.line((42,465,310,465),fill=(64,76,130,255),width=2); txt(45,490,"RECENT ACTIVITY",16,cyan,True)
    for i,s in enumerate(recent[:5]): txt(45,528+i*38,"› "+s[:27],12)
    txt(390,126,"PORTAL RUN",42,white,True); txt(393,178,"MATCH  •  COLLECT  •  UNLOCK",15,cyan,True)
    txt(1085,137,"ROUND ENDS",13,muted,True); txt(1110,158,f"{remain//60:02d}:{remain%60:02d}",25,pink,True)
    for i in range(48):
        wave=.2+.8*abs(math.sin(i*.39+now*3))*(.25+level); x=395+i*17; bh=int(7+32*wave)
        d.rounded_rectangle((x,214-bh,x+8,214),4,fill=cyan if i%3 else purple)
    d.rounded_rectangle((390,240,1260,685),22,fill=(15,20,58,250),outline=purple,width=3)
    syms=["✦","◈","△","◎","✧","◇"]
    for row in range(5):
        for col in range(8):
            x,y=410+col*104,258+row*78; idx=(row*5+col*3+int(now//8))%len(syms); color=cyan if idx%2==0 else purple
            d.rounded_rectangle((x,y,x+88,y+62),12,fill=(18,26,74,255),outline=color,width=2); txt(x+24,y+8,syms[idx],31,color,True)
    txt(395,710,"COMMUNITY PORTAL ENERGY",16,cyan,True); d.rounded_rectangle((395,744,1248,767),10,fill=(36,25,68,255))
    energy=min(1,len(joined)*.06+level*.3)
    if energy: d.rounded_rectangle((395,744,395+int(853*energy),767),10,fill=purple)
    txt(395,788,status[:72],17,white,True); txt(395,821,"Chat updates the arcade. Music keeps playing.",13,muted)
    txt(1345,128,"TOP PORTAL HUNTERS",22,cyan,True); txt(1345,162,"COMMUNITY POINTS",13,muted,True); d.line((1340,190,1870,190),fill=(64,76,130,255),width=2)
    for i,(name,p) in enumerate(players[:7]):
        y=208+i*42; txt(1348,y,f"{i+1:02d}",15,purple,True); txt(1390,y,name[:22],15,white,True); txt(1800,y,f"{p['points']} pts",13,cyan,True)
    d.line((1340,515,1870,515),fill=(64,76,130,255),width=2); txt(1345,535,"VOTE THE NEXT EVENT",18,pink,True)
    total=max(1,sum(votes.values()))
    for i,(label,key) in enumerate([("1  PORTAL","PORTAL"),("2  STARS","STARS"),("3  CHAOS","CHAOS")]):
        y=575+i*52; txt(1348,y,label,14); d.rounded_rectangle((1500,y+3,1810,y+20),6,fill=(37,30,69,255)); amount=int(310*votes[key]/total)
        if amount: d.rounded_rectangle((1500,y+3,1500+amount,y+20),6,fill=cyan if i==1 else purple)
        txt(1820,y+1,votes[key],12,muted)
    d.line((1340,745,1870,745),fill=(64,76,130,255),width=2); txt(1345,764,"ACHIEVEMENTS",16,cyan,True); txt(1345,795,"FIRST PORTAL  •  JOIN A ROUND",13); txt(1345,825,f"Total crew: {len(_players)}  •  Audio pulse: {int(level*100)}%",12,muted)
    d.rectangle((0,895,width,height),fill=navy); d.line((0,895,width,895),fill=purple,width=3); txt(32,922,"MUSIC  ×  COMMUNITY  ×  DISCOVERY",15,muted,True)
    for i in range(48):
        wave=.15+.85*abs(math.sin(i*.42+now*3.3))*level; bh=int(5+42*wave); x=590+i*13
        d.rounded_rectangle((x,970-bh,x+7,970),3,fill=cyan if i%4 else purple)
    txt(1260,937,"TYPE !JOIN TO ENTER",22,cyan,True); txt(1630,940,"STAY TUNED  ♥",18,pink,True)
    out=BytesIO(); Image.alpha_composite(base.convert("RGBA"),ov).convert("RGB").save(out,format="JPEG",quality=82); return out.getvalue()
