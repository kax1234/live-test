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

_STREAM_STARTED = time.monotonic()
_ACTIVITY_WINDOW = 600
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY = {}
_AVATARS = {}
_AVATAR_LOADING = set()
_CHAT_MESSAGES = []
_CHAT_LOCK = threading.Lock()
_CHAT_TTL = 18.0
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


def _duration_label(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0):
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
    px1, py1, px2, py2 = width - 390, 264, width - 42, 760
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

    # Animated live-chat panel. Bubbles slide in, then gently fade out.
    chat_rows = get_recent_chat()
    cx1, cy1, cx2 = 42, 270, 560
    draw.rounded_rectangle((cx1, cy1, cx2, 760), radius=22, fill=(4, 8, 24, 210),
                           outline=(184, 81, 255, 210), width=2)
    draw.text((cx1 + 20, cy1 + 16), "KAXMOK  /  LIVE CHAT", font=_font(17, True), fill=neon_cyan)
    draw.text((cx1 + 20, cy1 + 42), "REAL-TIME COMMUNITY", font=_font(10, True), fill=muted)
    if not chat_rows:
        draw.text((cx1 + 20, cy1 + 92), "Say hello in the live chat...", font=_font(13, True), fill=white)
    for index, row in enumerate(reversed(chat_rows)):
        age = max(0.0, time.time() - row["time"])
        progress = min(1.0, age / 0.45)
        slide = int((1.0 - progress) * 24)
        ry = cy1 + 72 + index * 108 + slide
        if ry + 94 > 752:
            continue
        fade = max(0.25, min(1.0, (_CHAT_TTL - age) / 3.0))
        alpha = int(218 * fade)
        draw.rounded_rectangle((cx1 + 12, ry, cx2 - 12, ry + 96), radius=14,
                               fill=(12, 19, 43, alpha), outline=(62, 92, 150, int(180 * fade)), width=1)
        key = row["key"]
        avatar = _AVATARS.get(key)
        ax, ay = cx1 + 24, ry + 14
        if avatar:
            overlay.paste(avatar, (ax, ay))
            draw.ellipse((ax, ay, ax + 38, ay + 38), outline=(44, 246, 255, int(255 * fade)), width=2)
        else:
            draw.ellipse((ax, ay, ax + 38, ay + 38), fill=(35, 36, 78, alpha),
                         outline=(184, 81, 255, int(255 * fade)), width=2)
            draw.text((ax + 12, ay + 10), row["name"][:1].upper(), font=_font(15, True), fill=white)
        tx = cx1 + 74
        draw.text((tx, ry + 14), row["name"][:22], font=_font(12, True),
                  fill=(44, 246, 255, int(255 * fade)))
        words = row["message"].split()
        lines, line = [], ""
        for word in words:
            candidate = (line + " " + word).strip()
            if draw.textlength(candidate, font=_font(11)) > 420 and line:
                lines.append(line)
                line = word
                if len(lines) == 2:
                    break
            else:
                line = candidate
        if line and len(lines) < 2:
            lines.append(line)
        for line_index, line_text in enumerate(lines[:2]):
            draw.text((tx, ry + 39 + line_index * 18), line_text, font=_font(11), fill=(239, 245, 255, int(255 * fade)))

    # Treasure Hunt panel, driven by live-chat commands.
    game = None
    try:
        import treasure_hunt
        game = treasure_hunt.snapshot()
    except Exception:
        game = None
    if game is not None:
        gx1, gy1, gx2, gy2 = 585, 264, 1510, 760
        draw.rounded_rectangle((gx1, gy1, gx2, gy2), radius=22, fill=(4, 8, 24, 226),
                               outline=(255, 190, 65, 235), width=2)
        draw.rounded_rectangle((gx1 + 10, gy1 + 10, gx2 - 10, gy2 - 10), radius=16,
                               outline=(184, 81, 255, 120), width=1)
        gold = (255, 203, 83, 255)
        draw.text((gx1 + 24, gy1 + 18), "KAXMOK  /  TREASURE HUNT", font=_font(20, True), fill=gold)
        draw.text((gx1 + 24, gy1 + 49), "TYPE  !DIG  TO SEARCH   •   !COINS  FOR YOUR BALANCE", font=_font(11, True), fill=white)
        draw.text((gx1 + 24, gy1 + 78), f"EXPLORERS  {game['players']}     DIGS  {game['total_digs']}     COINS FOUND  {game['total_coins']}",
                  font=_font(13, True), fill=neon_cyan)
        draw.line((gx1 + 24, gy1 + 108, gx2 - 24, gy1 + 108), fill=(255, 190, 65, 150), width=1)
        draw.text((gx1 + 24, gy1 + 126), "RECENT FINDS", font=_font(12, True), fill=gold)
        recent = list(reversed(game["recent"]))
        if not recent:
            draw.text((gx1 + 24, gy1 + 158), "The ground is untouched... be the first to dig!", font=_font(14), fill=white)
        for index, row in enumerate(recent[:4]):
            yy = gy1 + 154 + index * 48
            rarity_color = (255, 203, 83, 255) if row["rarity"] in ("Epic", "Legendary") else neon_cyan
            draw.rounded_rectangle((gx1 + 20, yy, gx1 + 440, yy + 38), radius=9,
                                   fill=(16, 22, 42, 230), outline=(70, 85, 125, 180), width=1)
            draw.text((gx1 + 32, yy + 5), f"{row['name'][:18]}  found {row['treasure']}", font=_font(11, True), fill=white)
            draw.text((gx1 + 32, yy + 21), row["rarity"].upper(), font=_font(9, True), fill=rarity_color)
            draw.text((gx1 + 360, yy + 10), f"+{row['coins']}", font=_font(13, True), fill=gold)
        draw.text((gx1 + 490, gy1 + 126), "TOP TREASURE HUNTERS", font=_font(12, True), fill=gold)
        if not game["top"]:
            draw.text((gx1 + 490, gy1 + 158), "No treasure yet", font=_font(12), fill=muted)
        for index, row in enumerate(game["top"]):
            yy = gy1 + 158 + index * 49
            draw.rounded_rectangle((gx1 + 480, yy - 4, gx2 - 20, yy + 38), radius=8,
                                   fill=(15, 21, 42, 220))
            draw.text((gx1 + 494, yy + 1), f"{index + 1}. {row['name'][:20]}", font=_font(11, True),
                      fill=gold if index == 0 else white)
            draw.text((gx1 + 494, yy + 21), f"{row['coins']} coins  •  {row['finds']} finds", font=_font(10), fill=muted)

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
