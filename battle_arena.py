"""KAXMOK Chat Battle Arena: lightweight, fictional turn-based chat game."""
import threading
import time
import random
from PIL import Image, ImageDraw, ImageFont

_LOCK = threading.RLock()
_CHALLENGES = {}
_BATTLES = {}
_STATS = {}
_RECENT = "Challenge a viewer with !challenge @name"
_FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"]
W, H = 1920, 1080

def _font(size):
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _key(name):
    return (name or "").strip().lstrip("@").casefold()[:32]

def _record(name, win=False, loss=False):
    key = _key(name)
    row = _STATS.setdefault(key, {"name": name[:24], "wins": 0, "losses": 0})
    row["name"] = name[:24]
    row["wins"] += int(win)
    row["losses"] += int(loss)

def _finish(a, b, winner):
    _record(winner, win=True)
    loser = b if _key(winner) == _key(a) else a
    _record(loser, loss=True)
    _BATTLES.pop(_key(a), None)
    _BATTLES.pop(_key(b), None)
    global _RECENT
    _RECENT = f"{winner} WINS THE BATTLE!"

def handle_command(author, message):
    """Handle battle commands. Returns True when a battle command was consumed."""
    global _RECENT
    parts = (message or "").strip().split()
    if not parts:
        return False
    cmd = parts[0].casefold()
    valid = {"!challenge", "!accept", "!decline", "!attack", "!defend",
             "!heal", "!battle", "!topfighters", "!stats", "!forfeit", "!helpbattle"}
    if cmd not in valid:
        return False
    name = (author or "viewer").strip()[:24]
    key = _key(name)
    now = time.monotonic()
    with _LOCK:
        # Expire unanswered invitations.
        for target, challenge in list(_CHALLENGES.items()):
            if now - challenge["time"] > 30:
                _CHALLENGES.pop(target, None)
                _RECENT = "Challenge expired — try again!"
        if cmd == "!helpbattle":
            print("[BATTLE] !challenge @name | !accept | !decline | !attack | !defend | !heal | !battle | !stats | !topfighters | !forfeit", flush=True)
        elif cmd == "!challenge":
            if len(parts) != 2:
                print("[BATTLE] Usage: !challenge @username", flush=True)
            else:
                target = parts[1].lstrip("@")[:24]
                target_key = _key(target)
                if not target_key or target_key == key:
                    print("[BATTLE] Challenge another viewer.", flush=True)
                elif key in _BATTLES or target_key in _BATTLES or key in _CHALLENGES or target_key in _CHALLENGES:
                    print("[BATTLE] One of those players is already busy.", flush=True)
                else:
                    _CHALLENGES[target_key] = {"from": name, "time": now}
                    _RECENT = f"{name} challenges {target}!"
                    print(f"[BATTLE] {name} challenged {target}; they have 30 seconds to !accept.", flush=True)
        elif cmd in {"!accept", "!decline"}:
            challenge = _CHALLENGES.pop(key, None)
            if not challenge:
                print("[BATTLE] No pending challenge for you.", flush=True)
            elif cmd == "!decline":
                _RECENT = f"{name} declined the challenge."
                print(f"[BATTLE] {name} declined {challenge['from']}.", flush=True)
            else:
                opponent = challenge["from"]
                if now - challenge["time"] > 30 or _key(opponent) in _BATTLES:
                    print("[BATTLE] Challenge expired or opponent is busy.", flush=True)
                else:
                    _BATTLES[key] = {"name": name, "opponent": opponent, "hp": 100, "defend": False, "healed": False}
                    _BATTLES[_key(opponent)] = {"name": opponent, "opponent": name, "hp": 100, "defend": False, "healed": False}
                    _RECENT = f"{name} vs {opponent} — BATTLE START!"
                    print(f"[BATTLE] {name} accepted! Battle started: {name} vs {opponent}.", flush=True)
        elif cmd == "!battle":
            battle = _BATTLES.get(key)
            print(f"[BATTLE] {name}: {battle['hp']} HP" if battle else f"[BATTLE] {name} is not in a battle.", flush=True)
        elif cmd == "!stats":
            s = _STATS.get(key, {"wins": 0, "losses": 0})
            print(f"[BATTLE] {name}: {s['wins']} wins / {s['losses']} losses (this session).", flush=True)
        elif cmd == "!topfighters":
            top = sorted(_STATS.values(), key=lambda x: (x["wins"], -x["losses"]), reverse=True)[:5]
            print("[BATTLE] TOP FIGHTERS (this session): " + (" | ".join(f"{x['name']} {x['wins']}W" for x in top) if top else "No wins yet"), flush=True)
        elif cmd == "!forfeit":
            battle = _BATTLES.get(key)
            if not battle:
                print("[BATTLE] You are not in a battle.", flush=True)
            else:
                _finish(name, battle["opponent"], battle["opponent"])
                print(f"[BATTLE] {name} forfeited. {battle['opponent']} wins!", flush=True)
        else:
            battle = _BATTLES.get(key)
            if not battle:
                print("[BATTLE] You are not in a battle. Use !challenge @username.", flush=True)
            else:
                enemy_key = _key(battle["opponent"])
                enemy = _BATTLES.get(enemy_key)
                if not enemy:
                    _BATTLES.pop(key, None)
                    print("[BATTLE] Battle ended.", flush=True)
                elif cmd == "!attack":
                    damage = random.randint(10, 25)
                    if enemy["defend"]:
                        damage = max(3, damage // 2)
                        enemy["defend"] = False
                    enemy["hp"] = max(0, enemy["hp"] - damage)
                    _RECENT = f"{name} hits {battle['opponent']} for {damage}!"
                    print(f"[BATTLE] {name} dealt {damage} damage to {battle['opponent']} ({enemy['hp']} HP left).", flush=True)
                    if enemy["hp"] <= 0:
                        _finish(name, battle["opponent"], name)
                        print(f"[BATTLE] {name} wins!", flush=True)
                elif cmd == "!defend":
                    battle["defend"] = True
                    _RECENT = f"{name} is guarding!"
                    print(f"[BATTLE] {name} is defending against the next hit.", flush=True)
                elif cmd == "!heal":
                    if battle["healed"]:
                        print("[BATTLE] Heal already used this battle.", flush=True)
                    else:
                        battle["hp"] = min(100, battle["hp"] + 15)
                        battle["healed"] = True
                        _RECENT = f"{name} restored 15 HP!"
                        print(f"[BATTLE] {name} healed to {battle['hp']} HP.", flush=True)
    return True

def start():
    return

def render_overlay(frame_bytes):
    with _LOCK:
        if not _BATTLES and not _CHALLENGES:
            return frame_bytes
        battle = next(iter(_BATTLES.values()), None)
        recent = _RECENT
        challenge = next(iter(_CHALLENGES.values()), None)
    try:
        base = Image.open(__import__("io").BytesIO(frame_bytes)).convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        x0, y0, x1, y1 = 520, 285, 1400, 700
        draw.rounded_rectangle((x0, y0, x1, y1), radius=30, fill=(10, 12, 24, 225), outline=(255, 75, 95, 245), width=5)
        draw.text((x0+35, y0+25), "KAXMOK  •  CHAT BATTLE ARENA", font=_font( thirty:=30), fill=(255, 220, 90, 255))
        draw.text((x0+35, y0+100), recent[:48], font=_font( thirty), fill=(255, 255, 255, 255))
        if battle:
            # Find each side's current HP from the active battle map.
            with _LOCK:
                left = next((v for v in _BATTLES.values() if _key(v["name"]) == _key(battle["name"])), battle)
                right = _BATTLES.get(_key(battle["opponent"]))
            if right:
                draw.text((x0+35, y0+190), f"{left['name']}  {left['hp']} HP", font=_font(26), fill=(110, 220, 255, 255))
                draw.text((x0+470, y0+190), f"{right['name']}  {right['hp']} HP", font=_font(26), fill=(255, 140, 150, 255))
                for bx, hp, color in [(x0+35, left["hp"], (70, 190, 255, 255)), (x0+470, right["hp"], (255, 90, 110, 255))]:
                    draw.rounded_rectangle((bx, y0+245, bx+330, y0+275), radius=12, fill=(65,65,75,255))
                    draw.rounded_rectangle((bx, y0+245, bx+int(330*hp/100), y0+275), radius=12, fill=color)
        elif challenge:
            draw.text((x0+35, y0+205), f"{challenge['from']} is waiting for !accept", font=_font(26), fill=(120, 245, 170, 255))
        draw.text((x0+35, y1-65), "!attack  !defend  !heal  !battle  !forfeit", font=_font(22), fill=(220, 220, 230, 255))
        base.alpha_composite(layer)
        out = __import__("io").BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception as exc:
        print(f"[BATTLE] Overlay error: {type(exc).__name__}: {exc}", flush=True)
        return frame_bytes
