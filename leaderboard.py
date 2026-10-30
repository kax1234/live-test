"""KAXMOK neon overlay: local clock, rotating ticker, and stream milestones.

This module is intentionally self-contained: no chat, OAuth, network, or API calls.
"""
import math
import time
import threading
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import re

_STREAM_STARTED = time.monotonic()
_ACTIVITY_WINDOW = 600
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY = {}
_AVATARS = {}
_AVATAR_LOADING = set()
_CHAT_MESSAGES = []
_CHAT_LOCK = threading.Lock()
_CHAT_TTL = 18.0
_PIN_LOCK = threading.Lock()
_PINNED_MESSAGE = None
_PINNED_BY = ""
_MILESTONES_MINUTES = (5, 15, 30, 60, 120, 180, 240, 300)
_TICKER_MESSAGES = (
    "GOOD MUSIC. GOOD MOOD. STAY AWHILE.",
    "YOUR KAXMOK SOUNDTRACK STARTS HERE.",
    "TAKE A BREATH • LET THE MUSIC PLAY.",
    "SHARE THE VIBE WITH SOMEONE.",
    "HEADPHONES ON • WORLD OFF.",
    "NEW TRACKS, NEW MOOD, SAME KAXMOK.",
    "THANKS FOR BEING PART OF THE NIGHT.",
    "RELAX • RECHARGE • REPEAT.",
)


def _font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


_YT_EMOJI_CACHE = {}
_YT_EMOJI_LOCK = threading.Lock()
_YT_EMOJI_TOKEN = re.compile(r"⟦YTEMOJI:(https://[^⟧]+)⟧")
_EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"


def _load_yt_emoji(url, size):
    key = (url, int(size))
    with _YT_EMOJI_LOCK:
        if key in _YT_EMOJI_CACHE:
            return _YT_EMOJI_CACHE[key]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KAXMOK-Live-Overlay/1.0"})
        with urllib.request.urlopen(req, timeout=2) as response:
            raw = response.read(500000)
        with Image.open(BytesIO(raw)) as im:
            icon = im.convert("RGBA")
            icon.thumbnail((size, size), Image.Resampling.LANCZOS)
        with _YT_EMOJI_LOCK:
            _YT_EMOJI_CACHE[key] = icon.copy()
        return icon
    except Exception:
        return None


def _draw_pin_rich_text(draw, target, text, x, y, font, fill, max_width):
    """Draw normal text, Unicode emoji, and YouTube custom emoji image tokens."""
    tokens = _YT_EMOJI_TOKEN.split(text)
    cursor_x = x
    base_size = max(16, getattr(font, "size", 24))
    for token in tokens:
        if not token:
            continue
        if token.startswith("⟦YTEMOJI:") and token.endswith("⟧"):
            url = token[len("⟦YTEMOJI:"):-1]
            icon = _load_yt_emoji(url, base_size)
            if icon is not None:
                iy = y + max(0, (base_size - icon.height) // 2)
                target.alpha_composite(icon, (int(cursor_x), int(iy)))
                cursor_x += icon.width + 5
            continue
        # Draw ordinary text with DejaVu, then overlay Unicode emoji using Noto Color Emoji.
        parts = re.split(r"([\U0001F000-\U0001FAFF\u2600-\u27BF]+)", token)
        for part in parts:
            if not part:
                continue
            if any(ord(ch) >= 0x1F000 or 0x2600 <= ord(ch) <= 0x27BF for ch in part):
                try:
                    ef = ImageFont.truetype(_EMOJI_FONT_PATH, size=109)
                    bbox = ef.getbbox(part, embedded_color=True)
                    ew = max(1, bbox[2] - bbox[0])
                    eh = max(1, bbox[3] - bbox[1])
                    layer = Image.new("RGBA", (ew + 8, eh + 8), (0, 0, 0, 0))
                    ed = ImageDraw.Draw(layer)
                    ed.text((4 - bbox[0], 4 - bbox[1]), part, font=ef, embedded_color=True)
                    layer.thumbnail((base_size, base_size), Image.Resampling.LANCZOS)
                    target.alpha_composite(layer, (int(cursor_x), int(y + max(0, (base_size - layer.height) // 2))))
                    cursor_x += layer.width + 2
                    continue
                except Exception:
                    pass
            draw.text((cursor_x, y), part, font=font, fill=fill)
            cursor_x += draw.textlength(part, font=font)
    return cursor_x - x


def award_message(viewer_name, avatar_url=None, now=None):
    """Track recent messages for the active-chatters leaderboard."""
    name = (viewer_name or "viewer").strip()[:32] or "viewer"
    stamp = time.time() if now is None else float(now)
    key = name.casefold()
    with _ACTIVITY_LOCK:
        entry = _ACTIVITY.setdefault(key, {"name": name, "times": [], "avatar_url": ""})
        entry["name"] = name
        entry["times"] = [t for t in entry["times"] if stamp - t <= _ACTIVITY_WINDOW]
        entry["times"].append(stamp)
        if avatar_url and str(avatar_url).startswith("https://"):
            entry["avatar_url"] = str(avatar_url)
    if avatar_url and str(avatar_url).startswith("https://"):
        _queue_avatar(key, str(avatar_url))


def _queue_avatar(key, url):
    with _ACTIVITY_LOCK:
        if key in _AVATARS or key in _AVATAR_LOADING:
            return
        _AVATAR_LOADING.add(key)
    def load():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "KAXMOK-Live-Overlay/1.0"})
            with urllib.request.urlopen(req, timeout=3) as response:
                raw = response.read(1000000)
            with Image.open(BytesIO(raw)) as im:
                _AVATARS[key] = im.convert("RGB").resize((38, 38), Image.Resampling.LANCZOS)
        except Exception:
            pass
        finally:
            with _ACTIVITY_LOCK:
                _AVATAR_LOADING.discard(key)
    threading.Thread(target=load, daemon=True).start()


def add_chat_message(viewer_name, message, avatar_url=None, now=None):
    """Queue a chat bubble for the on-stream animated chat panel."""
    name = (viewer_name or "viewer").strip()[:32] or "viewer"
    text = " ".join((message or "").split())[:180]
    if not text:
        return
    stamp = time.time() if now is None else float(now)
    key = name.casefold()
    with _CHAT_LOCK:
        _CHAT_MESSAGES.append({"name": name, "message": text, "time": stamp, "key": key})
        del _CHAT_MESSAGES[:-6]
    if avatar_url and str(avatar_url).startswith("https://"):
        _queue_avatar(key, str(avatar_url))


def get_recent_chat(now=None, limit=4):
    stamp = time.time() if now is None else float(now)
    with _CHAT_LOCK:
        _CHAT_MESSAGES[:] = [row for row in _CHAT_MESSAGES if stamp - row["time"] < _CHAT_TTL]
        return [dict(row) for row in _CHAT_MESSAGES[-limit:]]


def get_points(viewer_name):
    with _ACTIVITY_LOCK:
        item = _ACTIVITY.get((viewer_name or "").casefold(), {})
        cutoff = time.time() - _ACTIVITY_WINDOW
        return sum(1 for stamp in item.get("times", []) if stamp >= cutoff)


def get_leaderboard(limit=8):
    now = time.time()
    cutoff = now - _ACTIVITY_WINDOW
    rows = []
    with _ACTIVITY_LOCK:
        for key, item in list(_ACTIVITY.items()):
            item["times"] = [stamp for stamp in item["times"] if stamp >= cutoff]
            if item["times"]:
                rows.append({"name": item["name"], "points": len(item["times"]), "avatar": _AVATARS.get(key)})
            else:
                del _ACTIVITY[key]
    rows.sort(key=lambda row: (-row["points"], row["name"].casefold()))
    return rows[:max(0, int(limit))]


def set_pinned_message(message, author="moderator"):
    """Set the large on-stream pinned banner text."""
    global _PINNED_MESSAGE, _PINNED_BY
    text = " ".join((message or "").split())[:180]
    if not text:
        return False
    with _PIN_LOCK:
        _PINNED_MESSAGE = text
        _PINNED_BY = (author or "moderator")[:32]
    return True


def clear_pinned_message():
    """Hide the on-stream pinned banner."""
    global _PINNED_MESSAGE, _PINNED_BY
    with _PIN_LOCK:
        _PINNED_MESSAGE = None
        _PINNED_BY = ""


def get_pinned_message():
    with _PIN_LOCK:
        return {"message": _PINNED_MESSAGE, "author": _PINNED_BY}


def _duration_label(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0, cafe_state=None):
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGB")
    if base.size != (width, height):
        base = base.resize((width, height), Image.Resampling.BILINEAR)

    monotonic_now = time.monotonic()
    elapsed = max(0, monotonic_now - _STREAM_STARTED)
    elapsed_minutes = int(elapsed // 60)
    completed = [m for m in _MILESTONES_MINUTES if elapsed_minutes >= m]
    next_milestone = next((m for m in _MILESTONES_MINUTES if elapsed_minutes < m), None)
    if completed:
        milestone_text = f"MILESTONE UNLOCKED  //  {completed[-1]} MIN LIVE"
        milestone_color = (44, 246, 255, 255)
    else:
        target = next_milestone or 360
        milestone_text = f"NEXT MILESTONE IN  //  {max(0, target - elapsed_minutes):02d} MIN"
        milestone_color = (184, 121, 255, 255)

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    clock_text = now.strftime("%I:%M:%S %p").lstrip("0")
    date_text = now.strftime("%a  •  %d %b %Y").upper()
    ticker = _TICKER_MESSAGES[int(monotonic_now // 20) % len(_TICKER_MESSAGES)]
    duration_text = _duration_label(elapsed)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    neon_cyan = (44, 246, 255, 255)
    neon_purple = (184, 81, 255, 255)
    white = (239, 245, 255, 255)
    muted = (164, 184, 218, 255)
    panel = (4, 8, 24, 218)

    # Wide world-clock HUD based on the user's reference image.
    hx1, hy1, hx2, hy2 = 42, 42, width - 42, 232
    draw.rounded_rectangle((hx1, hy1, hx2, hy2), radius=28, fill=(4, 12, 29, 238),
                           outline=(24, 151, 255, 245), width=3)
    draw.rounded_rectangle((hx1 + 8, hy1 + 8, hx2 - 8, hy2 - 8), radius=22,
                           outline=(44, 246, 255, 190), width=2)
    draw.text((hx1 + 28, hy1 + 14), "KAXMOK  //  WORLD CLOCK", font=_font(16, True), fill=neon_cyan)
    draw.ellipse((hx2 - 116, hy1 + 20, hx2 - 104, hy1 + 32), fill=(255, 65, 105, 255))
    draw.text((hx2 - 95, hy1 + 16), "LIVE", font=_font(12, True), fill=white)

    # Large India clock on the left.
    india_x = hx1 + 30
    draw.text((india_x, hy1 + 48), "INDIA  /  IST", font=_font(18, True), fill=white)
    draw.text((india_x, hy1 + 72), now.strftime("%I:%M:%S").lstrip("0"), font=_font(43, True), fill=neon_cyan)
    draw.text((india_x + 270, hy1 + 92), now.strftime("%p"), font=_font(18, True), fill=white)
    draw.text((india_x + 4, hy1 + 130), now.strftime("%a, %d %b %Y").upper(), font=_font(12, True), fill=muted)
    draw.line((hx1 + 350, hy1 + 45, hx1 + 350, hy2 - 18), fill=(70, 110, 165, 210), width=2)

    # Four independently time-zone-aware clocks, including DST changes.
    cities = [
        ("NEW YORK", "America/New_York"),
        ("LONDON", "Europe/London"),
        ("DUBAI", "Asia/Dubai"),
        ("TOKYO", "Asia/Tokyo"),
    ]
    right_x = hx1 + 374
    available = hx2 - right_x - 22
    cell_w = available // len(cities)
    for index, (city, zone_name) in enumerate(cities):
        cx = right_x + index * cell_w
        city_now = datetime.now(ZoneInfo(zone_name))
        if index:
            draw.line((cx - 13, hy1 + 55, cx - 13, hy2 - 40), fill=(70, 110, 165, 180), width=1)
        draw.text((cx, hy1 + 55), city, font=_font(14, True), fill=white)
        draw.text((cx, hy1 + 86), city_now.strftime("%I:%M").lstrip("0"), font=_font(29, True), fill=neon_cyan)
        draw.text((cx + 104, hy1 + 97), city_now.strftime("%p"), font=_font(12, True), fill=white)
        offset = city_now.strftime("%z")
        hours = int(offset[:3])
        minutes = offset[3:]
        offset_text = f"UTC {hours:+d}" + (f":{minutes}" if minutes != "00" else "")
        draw.text((cx, hy1 + 130), offset_text, font=_font(13, True), fill=muted)

    # Compact status line at the bottom of the HUD.
    draw.rounded_rectangle((hx1 + 20, hy2 - 34, hx2 - 20, hy2 - 10), radius=8,
                           fill=(8, 20, 45, 235))
    draw.text((hx1 + 32, hy2 - 31), f"STREAM  {duration_text}", font=_font(10, True), fill=white)
    draw.text((hx1 + 210, hy2 - 31), milestone_text, font=_font(10, True), fill=milestone_color)

    # Active chatters panel, ranked by messages in the last ten minutes.
    active_rows = get_leaderboard(8)
    px1, py1, px2, py2 = 42, 264, 390, 760
    draw.rounded_rectangle((px1, py1, px2, py2), radius=22, fill=(4, 8, 24, 224),
                           outline=(44, 246, 255, 220), width=2)
    draw.text((px1 + 22, py1 + 18), "KAXMOK  /  ACTIVE CHATTERS", font=_font(17, True), fill=neon_cyan)
    draw.text((px1 + 22, py1 + 44), "LAST 10 MINUTES  •  LIVE RANKING", font=_font(10, True), fill=muted)
    if not active_rows:
        draw.text((px1 + 22, py1 + 100), "Waiting for chat activity...", font=_font(13, True), fill=white)
    for rank, row in enumerate(active_rows):
        ry = py1 + 78 + rank * 49
        if ry + 42 > py2 - 8:
            break
        if rank == 0:
            draw.rounded_rectangle((px1 + 12, ry - 3, px2 - 12, ry + 40), radius=10, fill=(22, 40, 66, 230))
        avatar = row.get("avatar")
        ax, ay = px1 + 20, ry + 1
        if avatar:
            overlay.paste(avatar, (ax, ay))
            draw.ellipse((ax, ay, ax + 38, ay + 38), outline=neon_cyan if rank == 0 else (100, 130, 170, 255), width=2)
        else:
            draw.ellipse((ax, ay, ax + 38, ay + 38), fill=(30, 44, 75, 255),
                         outline=neon_purple if rank == 0 else (100, 130, 170, 255), width=2)
            draw.text((ax + 12, ay + 10), row["name"][:1].upper(), font=_font(15, True), fill=white)
        label_x = px1 + 72
        draw.text((label_x, ry + 2), f"{rank + 1:02d}  {row['name'][:18]}", font=_font(12, True),
                  fill=neon_cyan if rank == 0 else white)
        draw.text((label_x, ry + 23), f"{row['points']} messages", font=_font(10), fill=muted)

    # Live-chat message board intentionally removed; chat commands still work.

    # KAXMOK CAFE — pixel-art isometric café driven by live chat.
    cafe_state = cafe_state or {}
    cx1, cy1, cx2, cy2 = 420, 264, width - 42, 760
    draw.rounded_rectangle((cx1,cy1,cx2,cy2),radius=22,fill=(7,10,25,242),outline=(255,184,92,235),width=3)
    draw.text((cx1+28,cy1+20),"KAXMOK  /  CAFE",font=_font(23,True),fill=(255,211,139,255))
    draw.text((cx1+29,cy1+54),"A LITTLE COFFEE WORLD BUILT BY LIVE CHAT",font=_font(11,True),fill=muted)
    def tile(x,y,w,h):
        draw.polygon([(x,y),(x+w,y-h//2),(x+2*w,y),(x+w,y+h//2)],fill=(66,72,78,255),outline=(27,35,48,255))
        draw.polygon([(x,y),(x+w,y+h//2),(x+w,y+h//2+12),(x,y+12)],fill=(39,45,56,255))
        draw.polygon([(x+w,y+h//2),(x+2*w,y),(x+2*w,y+12),(x+w,y+h//2+12)],fill=(29,35,46,255))
    fx,fy=cx1+50,cy1+300
    for rr in range(4):
        for cc in range(6): tile(fx+cc*76+rr*38,fy+rr*38,38,22)
    bx,by=cx1+205,cy1+205
    draw.polygon([(bx,by),(bx+210,by-105),(bx+430,by),(bx+220,by+108)],fill=(130,72,55,255),outline=(245,177,112,255))
    draw.polygon([(bx,by),(bx+220,by+108),(bx+220,by+245),(bx,by+137)],fill=(105,59,49,255),outline=(51,34,39,255))
    draw.polygon([(bx+220,by+108),(bx+430,by),(bx+430,by+137),(bx+220,by+245)],fill=(75,48,49,255),outline=(40,31,42,255))
    draw.polygon([(bx-12,by-5),(bx+210,by-122),(bx+442,by-5),(bx+220,by+116)],fill=(44,35,55,255),outline=(255,196,117,255),width=4)
    for wx,wy in [(bx+45,by+55),(bx+125,by+97),(bx+262,by+48),(bx+350,by+27)]:
        draw.rectangle((wx,wy,wx+58,wy+54),fill=(255,205,116,255),outline=(35,35,48,255),width=5)
    draw.rectangle((bx+194,by+158,bx+246,by+245),fill=(42,35,48,255),outline=(255,185,105,255),width=4)
    draw.rounded_rectangle((bx+128,by-32,bx+294,by+8),radius=4,fill=(27,24,38,255),outline=(255,197,112,255),width=3)
    draw.text((bx+148,by-24),"KAX CAFE",font=_font(19,True),fill=(255,213,145,255))
    for n,person in enumerate(cafe_state.get("visitors",[])[:7]):
        px=cx1+80+(n%4)*100; py=cy1+375+(n//4)*45
        draw.rectangle((px+8,py+18,px+27,py+43),fill=(45,75,122,255))
        draw.rectangle((px+10,py+2,px+26,py+19),fill=(232,177,130,255))
        draw.rectangle((px+8,py,px+27,py+7),fill=(57,39,35,255))
        draw.rectangle((px+4,py+43,px+13,py+50),fill=(31,30,38,255))
        draw.rectangle((px+23,py+43,px+32,py+50),fill=(31,30,38,255))
        draw.text((px-9,py+53),str(person)[:11],font=_font(9,True),fill=(255,225,178,255))
    sx,sy=cx1+900,cy1+105
    draw.rounded_rectangle((sx,sy,cx2-28,cy2-28),radius=16,fill=(14,19,34,245),outline=(164,112,74,220),width=2)
    draw.text((sx+22,sy+20),"TODAY AT THE CAFE",font=_font(15,True),fill=(255,208,137,255))
    for n,(label,value) in enumerate([("CUSTOMERS",cafe_state.get("customers",0)),("OPEN ORDERS",cafe_state.get("open_orders",0)),("CAFE LEVEL",cafe_state.get("level",1)),("SERVED",cafe_state.get("served",0))]):
        yy=sy+62+n*62
        draw.text((sx+22,yy),label,font=_font(10,True),fill=muted)
        draw.text((sx+22,yy+17),str(value),font=_font(24,True),fill=(255,211,139,255))
    draw.line((sx+20,sy+322,cx2-48,sy+322),fill=(116,88,75,220),width=2)
    draw.text((sx+22,sy+338),"LIVE ACTIVITY",font=_font(11,True),fill=(255,208,137,255))
    for n,event in enumerate(cafe_state.get("recent",[])[:3]):
        draw.text((sx+22,sy+365+n*23),str(event)[:35],font=_font(10),fill=white)
    draw.text((cx1+30,cy2-48),"CHAT: !join  !order  !serve  !work  !upgrade  !menu  !wallet  !top",font=_font(12,True),fill=(255,211,139,255))
    # Premium pinned-message spotlight banner, shown until !unpin.
    pinned = get_pinned_message()
    if pinned["message"]:
        bx1, by1, bx2, by2 = 280, 770, width - 280, 892

        # Layered neon halo and bold outer frame.
        for pad, color, line_width in (
            (16, (184, 81, 255, 35), 7),
            (10, (255, 40, 105, 75), 5),
            (4, (44, 246, 255, 115), 3),
        ):
            draw.rounded_rectangle(
                (bx1 - pad, by1 - pad, bx2 + pad, by2 + pad),
                radius=30 + pad, outline=color, width=line_width
            )

        # Dark glass panel with a double border.
        draw.rounded_rectangle(
            (bx1, by1, bx2, by2), radius=28,
            fill=(4, 7, 22, 248), outline=(255, 45, 105, 255), width=3
        )
        draw.rounded_rectangle(
            (bx1 + 7, by1 + 7, bx2 - 7, by2 - 7), radius=22,
            outline=(44, 246, 255, 175), width=2
        )

        # Header strip and spotlight badge.
        draw.rounded_rectangle(
            (bx1 + 20, by1 + 13, bx2 - 20, by1 + 42), radius=10,
            fill=(25, 10, 35, 245)
        )
        draw.rounded_rectangle(
            (bx1 + 20, by1 + 13, bx1 + 26, by1 + 42), radius=3,
            fill=(255, 45, 105, 255)
        )
        draw.text(
            (bx1 + 38, by1 + 17), "KAXMOK  •  MESSAGE SPOTLIGHT",
            font=_font(14, True), fill=(255, 215, 115, 255)
        )
        badge_w = 104
        draw.rounded_rectangle(
            (bx2 - badge_w - 28, by1 + 15, bx2 - 28, by1 + 40), radius=12,
            fill=(255, 40, 95, 235), outline=(255, 140, 165, 255), width=1
        )
        draw.ellipse((bx2 - badge_w - 15, by1 + 23, bx2 - badge_w - 7, by1 + 31),
                     fill=(255, 255, 255, 255))
        draw.text((bx2 - badge_w + 1, by1 + 19), "PINNED LIVE",
                  font=_font(10, True), fill=(255, 255, 255, 255))

        # Small decorative end caps make the banner feel like a broadcast callout.
        draw.line((bx1 + 24, by2 - 15, bx1 + 92, by2 - 15),
                  fill=(255, 45, 105, 230), width=3)
        draw.line((bx2 - 92, by2 - 15, bx2 - 24, by2 - 15),
                  fill=(44, 246, 255, 230), width=3)

        pin_text = pinned["message"]
        # Keep Unicode emoji and YouTube custom emoji image support.
        pin_font = _font(28 if len(pin_text) < 55 else 22, True)
        max_text_width = bx2 - bx1 - 64
        plain_for_measure = _YT_EMOJI_TOKEN.sub("   ", pin_text)
        while draw.textlength(plain_for_measure, font=pin_font) > max_text_width and pin_font.size > 15:
            pin_font = _font(pin_font.size - 1, True)
            plain_for_measure = _YT_EMOJI_TOKEN.sub("   ", pin_text)
        text_width = draw.textlength(plain_for_measure, font=pin_font)
        _draw_pin_rich_text(
            draw, overlay, pin_text,
            bx1 + (bx2 - bx1 - text_width) / 2,
            by1 + 55, pin_font, (255, 255, 255, 255), max_text_width
        )

    # Bottom ticker: local time-based rotation, independent of chat or APIs.
    ticker_y = height - 82
    draw.rounded_rectangle((42, ticker_y, width - 42, height - 30), radius=13,
                           fill=(4, 8, 24, 222), outline=(85, 75, 180, 220), width=1)
    draw.rounded_rectangle((58, ticker_y + 12, 63, height - 42), radius=2, fill=neon_cyan)
    draw.text((78, ticker_y + 15), "KAXMOK  /  VIBE TRANSMISSION", font=_font(12, True), fill=neon_purple)
    draw.text((width // 2 - 170, ticker_y + 14), ticker, font=_font(15, True), fill=white)
    draw.text((width - 255, ticker_y + 15), "IST  •  24/7 MUSIC", font=_font(12, True), fill=neon_cyan)

    # Audio-reactive neon bars retain the existing audio_level interface.
    level = max(0.0, min(1.0, float(audio_level)))
    bars, gap = 32, 7
    sw, sh = 620, 52
    sx, sy = (width - sw) // 2, height - 154
    draw.rounded_rectangle((sx - 16, sy - 28, sx + sw + 16, sy + sh + 8), radius=14,
                           fill=(5, 8, 20, 135))
    draw.text((sx, sy - 22), "AUDIO SIGNAL  //  LIVE", font=_font(11, True), fill=neon_cyan)
    bw = (sw - gap * (bars - 1)) // bars
    for i in range(bars):
        wave = 0.25 + 0.75 * abs(math.sin(i * 0.55 + monotonic_now * 3.2))
        bh = max(3, int(4 + 42 * level * wave))
        bx = sx + i * (bw + gap)
        color = neon_cyan if i % 4 else neon_purple
        draw.rounded_rectangle((bx, sy + sh - bh, bx + bw, sy + sh), radius=3, fill=color)

    out = BytesIO()
    Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB").save(out, format="JPEG", quality=78)
    return out.getvalue()
