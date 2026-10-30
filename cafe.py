"""KAXMOK Cafe: chat-driven community cafe with Cloudflare KV persistence."""
import json, os, threading, time, urllib.request
from pathlib import Path

_LOCK=threading.RLock()
_API=os.environ.get("CONTROL_API_URL","").rstrip("/")
_TOKEN=os.environ.get("CONTROL_RUNNER_TOKEN","")
_LOCAL=Path(__file__).with_name("kax_cafe_state.json")
_MENU={"espresso":8,"latte":12,"mocha":14,"tea":6,"cake":10}
_LAST={}
def _fresh():
    return {"level":1,"treasury":0,"customers":0,"served":0,"players":{},"orders":[],"recent":["KAXMOK CAFE is opening! Type !join"],"next_order":1}
def _normalize(raw):
    s=_fresh()
    if not isinstance(raw,dict): return s
    try:
        s["level"]=max(1,min(50,int(raw.get("level",1)))); s["treasury"]=max(0,int(raw.get("treasury",0)))
        s["customers"]=max(0,int(raw.get("customers",0))); s["served"]=max(0,int(raw.get("served",0)))
        for k,v in list(raw.get("players",{}).items())[:500]:
            if isinstance(v,dict): s["players"][str(k)[:64]]={"name":str(v.get("name","viewer"))[:32],"coins":max(0,int(v.get("coins",20))),"joined":bool(v.get("joined",True)),"orders":max(0,int(v.get("orders",0))),"served":max(0,int(v.get("served",0)))}
        s["orders"]=[x for x in raw.get("orders",[]) if isinstance(x,dict)][-12:]
        s["recent"]=[str(x)[:90] for x in raw.get("recent",[])][-4:]; s["next_order"]=max(1,int(raw.get("next_order",1)))
    except (ValueError,TypeError,AttributeError): return _fresh()
    return s
def _remote(method,payload=None):
    if not (_API and _TOKEN): return None
    req=urllib.request.Request(_API+"/api/cafe-state",data=json.dumps(payload).encode() if payload is not None else None,headers={"Authorization":"Bearer "+_TOKEN,"Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=3) as r: return json.loads(r.read().decode())
    except Exception as e:
        print(f"[CAFE] Cloud save unavailable ({type(e).__name__}); local fallback.",flush=True); return None
def _load():
    remote=_remote("GET")
    if isinstance(remote,dict) and isinstance(remote.get("state"),dict): return _normalize(remote["state"])
    try:
        if _LOCAL.is_file(): return _normalize(json.loads(_LOCAL.read_text(encoding="utf-8")))
    except Exception: pass
    return _fresh()
_STATE=_load()
def _save():
    try: _LOCAL.write_text(json.dumps(_STATE,ensure_ascii=False),encoding="utf-8")
    except Exception: pass
    _remote("POST",{"state":_STATE})
def _event(msg):
    _STATE["recent"].append(str(msg)[:90]); _STATE["recent"]=_STATE["recent"][-4:]
def handle_message(message,author,now=None):
    parts=(message or "").strip().split()
    if not parts: return None
    cmd=parts[0].casefold()
    if cmd not in {"!cafe","!join","!order","!serve","!work","!upgrade","!menu","!wallet","!top"}: return None
    name=(author or "viewer").strip()[:32] or "viewer"; key=name.casefold(); stamp=time.time() if now is None else float(now)
    with _LOCK:
        row=_STATE["players"].setdefault(key,{"name":name,"coins":20,"joined":False,"orders":0,"served":0}); row["name"]=name
        if cmd=="!menu": return "CAFE MENU: "+" | ".join(f"{k.title()} {v} coins" for k,v in _MENU.items())
        if cmd=="!cafe": return f"KAXMOK CAFE Lv{_STATE['level']} | {_STATE['customers']} customers | {sum(not o.get('served') for o in _STATE['orders'])} open orders | !join"
        if cmd=="!join":
            if not row["joined"]: row["joined"]=True; _STATE["customers"]+=1; _event(f"{name} joined the cafe"); _save()
            return f"{name} joined KAXMOK CAFE! You have {row['coins']} coins. Try !order latte."
        if not row["joined"]: return f"{name}, type !join to enter KAXMOK CAFE."
        if cmd=="!wallet": return f"{name}: {row['coins']} coins | {row['orders']} orders | {row['served']} served."
        if cmd=="!top":
            top=sorted(_STATE["players"].values(),key=lambda p:(-p["coins"],p["name"].casefold()))[:5]
            return "CAFE REGULARS: "+" | ".join(f"{i+1}. {p['name']} {p['coins']}c" for i,p in enumerate(top))
        if stamp-_LAST.get(key,0)<3: return f"{name}, take a little break before your next cafe action."
        if cmd=="!order":
            item=parts[1].casefold() if len(parts)>1 else "latte"
            if item not in _MENU: return "Choose: !order espresso/latte/mocha/tea/cake"
            price=_MENU[item]
            if row["coins"]<price: return f"{name}, {item} costs {price} coins. Earn coins with !work."
            row["coins"]-=price; row["orders"]+=1; _STATE["treasury"]+=price; oid=_STATE["next_order"]; _STATE["next_order"]+=1
            _STATE["orders"].append({"id":oid,"name":name,"item":item,"served":False}); _STATE["orders"]=_STATE["orders"][-12:]
            _event(f"{name} ordered {item}"); result=f"Order #{oid}: {name} ordered {item}. A barista can use !serve."
        elif cmd=="!serve":
            order=next((o for o in _STATE["orders"] if not o.get("served")),None)
            if not order: return "No open orders. Try !work or !order."
            order["served"]=True; row["coins"]+=5; row["served"]+=1; _STATE["served"]+=1
            _event(f"{name} served {order['name']}'s {order['item']}"); result=f"{name} served {order['name']}'s {order['item']}! +5 coins."
        elif cmd=="!work":
            row["coins"]+=8; _STATE["treasury"]+=3; _event(f"{name} worked a cafe shift (+8 coins)"); result=f"{name} finished a cafe shift! +8 coins."
        elif cmd=="!upgrade":
            cost=50*_STATE["level"]
            if _STATE["treasury"]<cost: return f"Cafe upgrade needs {cost} cafe coins. Orders and shifts grow the cafe fund."
            _STATE["treasury"]-=cost; _STATE["level"]+=1; _event(f"KAXMOK CAFE upgraded to level {_STATE['level']}!"); result=f"KAXMOK CAFE reached level {_STATE['level']}! New decor unlocked."
        else: return None
        _LAST[key]=stamp; _save(); return result
def snapshot():
    with _LOCK:
        pending=[o for o in _STATE["orders"] if not o.get("served")]
        visitors=[p["name"] for p in sorted(_STATE["players"].values(),key=lambda p:p["name"].casefold()) if p.get("joined")]
        return {"level":_STATE["level"],"treasury":_STATE["treasury"],"customers":_STATE["customers"],"served":_STATE["served"],"open_orders":len(pending),"visitors":visitors[:7],"recent":list(reversed(_STATE["recent"][-3:]))}
