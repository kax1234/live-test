"""KAXMOK neon overlay: local clock, rotating ticker, and stream milestones.

This module is intentionally self-contained: no chat, OAuth, network, or API calls.
"""
import math
import json
import time
import threading
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
import re

_STREAM_STARTED = time.monotonic()
_ACTIVITY_WINDOW = None  # Entire running livestream
_ACTIVITY_LOCK = threading.Lock()
_ACTIVITY = {}
_PERSIST_LOCK = threading.Lock()
_PERSIST_URL = ""
_PERSIST_TOKEN = ""
_PERSISTED_COUNTS = {}
_PERSISTED_AVATARS = {}
_PENDING_COUNTS = {}
_AVATARS = {}
_AVATAR_LOADING = set()
_CHAT_MESSAGES = []
_CHAT_LOCK = threading.Lock()
_CHAT_TTL = 18.0
_PIN_LOCK = threading.Lock()
_PINNED_MESSAGE = None
_PINNED_BY = ""
_SLAP_LOCK = threading.Lock()
_SLAP_EVENT = None


def set_slap_animation(from_user, to_user):
    """Trigger a short, harmless comic-book slap animation on the stream overlay."""
    global _SLAP_EVENT
    with _SLAP_LOCK:
        _SLAP_EVENT = {"from": (from_user or "viewer")[:24], "to": (to_user or "viewer")[:24], "time": time.monotonic()}


def _draw_slap_animation(overlay, draw, now):
    with _SLAP_LOCK:
        event = dict(_SLAP_EVENT) if _SLAP_EVENT else None
    if not event:
        return
    elapsed = now - event["time"]
    if elapsed < 0 or elapsed >= 4.0:
        return
    # Three-frame comic-book gag; deliberately playful and non-realistic.
    phase = min(3, int(elapsed))
    cx, cy = 960, 505
    pulse = (0, 12, -8, 0)[phase]
    draw.rounded_rectangle((560, 365, 1360, 650), radius=34,
                           fill=(4, 8, 25, 225), outline=(255, 91, 151, 245), width=4)
    draw.text((610, 395), event["from"], font=_font(27, True), fill=(44, 246, 255, 255))
    draw.text((1110, 395), event["to"], font=_font(27, True), fill=(255, 210, 90, 255))
    draw.text((cx - 170 + pulse, cy - 55), "✋", font=_font(92, True), fill=(255, 225, 170, 255))
    draw.text((cx - 10, cy - 72), "✨", font=_font(70, True), fill=(255, 230, 90, 255))
    draw.text((cx + 72 - pulse, cy - 35), "💥", font=_font(86, True), fill=(255, 105, 125, 255))
    label = ("READY?", "SLAP!", "POW!", "GOTCHA!")[phase]
    font = _font(43 if phase in (1, 2) else 34, True)
    label_w = draw.textlength(label, font=font)
    draw.text((cx - label_w / 2, 570), label, font=font, fill=(255, 245, 255, 255))

_INTERACTION_LOCK = threading.Lock()
_INTERACTION_EVENT = None


def set_interaction_animation(kind, from_user, to_user=None, score=None, avatar_url=None):
    """Queue a short, playful chat interaction with cached YouTube profile pictures."""
    global _INTERACTION_EVENT
    sender_key = (from_user or "viewer").lstrip("@").casefold()
    target_key = (to_user or "").lstrip("@").casefold()
    if avatar_url and str(avatar_url).startswith("https://"):
        _queue_avatar(sender_key, str(avatar_url))
    target_url = ""
    if target_key:
        with _ACTIVITY_LOCK:
            target_url = _ACTIVITY.get(target_key, {}).get("avatar_url", "")
    if target_url:
        _queue_avatar(target_key, target_url)
    with _INTERACTION_LOCK:
        _INTERACTION_EVENT = {
            "kind": kind, "from": (from_user or "viewer")[:24],
            "to": (to_user or "")[:24], "from_key": sender_key,
            "to_key": target_key, "score": score,
            "time": time.monotonic()
        }


def _draw_interaction_animation(overlay, draw, now):
    with _INTERACTION_LOCK:
        event = dict(_INTERACTION_EVENT) if _INTERACTION_EVENT else None
    if not event:
        return
    elapsed = now - event["time"]
    if elapsed < 0 or elapsed >= 5.0:
        return
    labels = {
        "hug": ("HUG TIME", "💖"), "highfive": ("HIGH FIVE!", "🙌"),
        "duel": ("FUN FACE-OFF", "⚡"), "crown": ("ROYALTY!", "👑"),
        "shield": ("PROTECTED!", "🛡"), "dance": ("DANCE BREAK!", "🎵"),
        "love": ("LOVE METER", "💗"), "hate": ("RIVALRY METER", "😈")
    }
    label, symbol = labels.get(event["kind"], ("KAXMOK!", "✨"))
    # Large broadcast-style profile spotlight; avatar fetching stays off the audio path.
    x1, y1, x2, y2 = 390, 285, 1530, 795
    draw.rounded_rectangle((x1 + 10, y1 + 12, x2 + 10, y2 + 12), radius=42, fill=(0, 0, 0, 150))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=38, fill=(4, 12, 29, 246),
                           outline=(24, 151, 255, 255), width=5)
    draw.rounded_rectangle((x1 + 10, y1 + 10, x2 - 10, y2 - 10), radius=30,
                           outline=(44, 246, 255, 145), width=2)
    draw.text((x1 + 42, y1 + 28), "KAXMOK  //  VIEWER SPOTLIGHT", font=_font(20, True), fill=(44, 246, 255, 255))
    draw.text((x2 - 180, y1 + 30), "LIVE MOMENT", font=_font(13, True), fill=(184, 81, 255, 255))
    def avatar(key, cx, cy, fallback):
        image = _AVATARS.get(key) if key else None
        size = 190
        if image is not None:
            image = image.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
            overlay.paste(image, (cx - size // 2, cy - size // 2), mask)
        else:
            draw.ellipse((cx-size//2, cy-size//2, cx+size//2, cy+size//2),
                         fill=(28, 44, 76, 255), outline=(184, 81, 255, 255), width=4)
            draw.text((cx-18, cy-24), fallback[:1].upper(), font=_font(38, True), fill=(255,255,255,255))
        draw.ellipse((cx-size//2, cy-size//2, cx+size//2, cy+size//2),
                     outline=(44, 246, 255, 255), width=4)
    if event["to"]:
        avatar(event["from_key"], 700, 520, event["from"])
        avatar(event["to_key"], 1220, 520, event["to"])
        from_font, to_font = _font(25, True), _font(25, True)
        draw.text((700-draw.textlength(event["from"], font=from_font)/2, 635), event["from"], font=from_font, fill=(44, 246, 255, 255))
        draw.text((1220-draw.textlength(event["to"], font=to_font)/2, 635), event["to"], font=to_font, fill=(255, 210, 90, 255))
        draw.text((930, 470), symbol, font=_font(66, True), fill=(255, 230, 120, 255))
    else:
        avatar(event["from_key"], 960, 505, event["from"])
        name_font = _font(27, True)
        draw.text((960-draw.textlength(event["from"], font=name_font)/2, 625), event["from"], font=name_font, fill=(44, 246, 255, 255))
        draw.text((930, 390), symbol, font=_font(66, True), fill=(255, 230, 120, 255))
    title_font = _font(36, True)
    title_w = draw.textlength(label, font=title_font)
    draw.text((960-title_w/2, 700), label, font=title_font, fill=(255, 245, 255, 255))
    if event["score"] is not None:
        score = int(event["score"])
        draw.rounded_rectangle((700, 660, 1220, 680), radius=10, fill=(65, 22, 32, 255))
        draw.rounded_rectangle((700, 660, 700 + int(520 * score / 100), 680),
                               radius=10, fill=(255, 80, 160, 255))
        score_text = f"{score}%  •  JUST FOR FUN"
        score_font = _font(18, True)
        draw.text((960-draw.textlength(score_text, font=score_font)/2, 682),
                  score_text, font=score_font, fill=(230, 235, 255, 255))

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


def configure_persistence(api_url, runner_token):
    """Load all-time chatter counts from the Cloudflare Worker."""
    global _PERSIST_URL, _PERSIST_TOKEN, _PERSISTED_COUNTS, _PERSISTED_AVATARS
    _PERSIST_URL = (api_url or "").rstrip("/")
    _PERSIST_TOKEN = runner_token or ""
    if not _PERSIST_URL or not _PERSIST_TOKEN:
        print("[LEADERBOARD] Persistence not configured; using session-only scores.", flush=True)
        return False
    try:
        req = urllib.request.Request(
            _PERSIST_URL + "/api/leaderboard",
            headers={"Authorization": "Bearer " + _PERSIST_TOKEN},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read(500000).decode("utf-8"))
        saved = data.get("leaderboard", {})
        with _PERSIST_LOCK:
            _PERSISTED_COUNTS = {str(k): max(0, int(v.get("points", 0))) for k, v in saved.items() if isinstance(v, dict)}
            _PERSISTED_AVATARS = {str(k): str(v.get("avatar_url", "")) for k, v in saved.items() if isinstance(v, dict) and v.get("avatar_url")}
        for key, url in _PERSISTED_AVATARS.items():
            if url.startswith("https://"):
                _queue_avatar(key, url)
        print(f"[LEADERBOARD] Restored {len(_PERSISTED_COUNTS)} all-time chatters from Cloudflare KV.", flush=True)
        return True
    except Exception as exc:
        print(f"[LEADERBOARD] Restore failed: {type(exc).__name__}: {exc}", flush=True)
        return False


def flush_persistent_leaderboard():
    """Persist current all-time totals; safe to call periodically."""
    if not _PERSIST_URL or not _PERSIST_TOKEN:
        return False
    with _PERSIST_LOCK:
        payload = {}
        keys = set(_PERSISTED_COUNTS) | set(_PENDING_COUNTS)
        for key in keys:
            points = _PERSISTED_COUNTS.get(key, 0) + _PENDING_COUNTS.get(key, 0)
            payload[key] = {"points": points, "avatar_url": _PERSISTED_AVATARS.get(key, "")}
        # Include latest profile URLs observed in this process.
        with _ACTIVITY_LOCK:
            for key, item in _ACTIVITY.items():
                if item.get("avatar_url"):
                    payload.setdefault(key, {"points": _PERSISTED_COUNTS.get(key, 0) + _PENDING_COUNTS.get(key, 0), "avatar_url": ""})
                    payload[key]["avatar_url"] = item["avatar_url"]
        body = json.dumps({"leaderboard": payload}).encode("utf-8")
    try:
        req = urllib.request.Request(
            _PERSIST_URL + "/api/leaderboard",
            data=body,
            headers={"Authorization": "Bearer " + _PERSIST_TOKEN, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            response.read(10000)
        with _PERSIST_LOCK:
            _PERSISTED_COUNTS = {k: int(v["points"]) for k, v in payload.items()}
            _PERSISTED_AVATARS = {k: v.get("avatar_url", "") for k, v in payload.items() if v.get("avatar_url")}
            _PENDING_COUNTS.clear()
        return True
    except Exception as exc:
        print(f"[LEADERBOARD] Save failed: {type(exc).__name__}: {exc}", flush=True)
        return False


def persistence_loop():
    while True:
        time.sleep(10)
        flush_persistent_leaderboard()


def award_message(viewer_name, avatar_url=None, now=None):
    """Track recent messages for the active-chatters leaderboard."""
    name = (viewer_name or "viewer").strip()[:32] or "viewer"
    stamp = time.time() if now is None else float(now)
    key = name.casefold()
    with _ACTIVITY_LOCK:
        entry = _ACTIVITY.setdefault(key, {"name": name, "times": [], "avatar_url": ""})
        entry["name"] = name
        # Keep every message for this stream session; no rolling 10-minute expiry.
        entry["times"].append(stamp)
        if avatar_url and str(avatar_url).startswith("https://"):
            entry["avatar_url"] = str(avatar_url)
    with _PERSIST_LOCK:
        _PENDING_COUNTS[key] = _PENDING_COUNTS.get(key, 0) + 1
        if avatar_url and str(avatar_url).startswith("https://"):
            _PERSISTED_AVATARS[key] = str(avatar_url)
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
                _AVATARS[key] = im.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS)
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
        return len(item.get("times", []))


def get_leaderboard(limit=8):
    now = time.time()
    rows = []
    with _ACTIVITY_LOCK:
        for key, item in _ACTIVITY.items():
            if item["times"]:
                rows.append({"key": key, "name": item["name"], "points": len(item["times"]), "avatar": _AVATARS.get(key)})
    with _PERSIST_LOCK:
        totals = dict(_PERSISTED_COUNTS)
        for key, count in _PENDING_COUNTS.items():
            totals[key] = totals.get(key, 0) + count
    by_key = {row["key"]: row for row in rows}
    for key, points in totals.items():
        if key not in by_key:
            name = key
            rows.append({"key": key, "name": name, "points": points, "avatar": _AVATARS.get(key)})
        else:
            by_key[key]["points"] += _PERSISTED_COUNTS.get(key, 0)
    for row in rows:
        row.pop("key", None)
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

    # Premium broadcast header: compact time-zone rail with a clear brand hierarchy.
    hx1, hy1, hx2, hy2 = 42, 42, width - 42, 220
    draw.rounded_rectangle((hx1 + 8, hy1 + 10, hx2 + 8, hy2 + 10), radius=30,
                           fill=(0, 0, 0, 105))
    draw.rounded_rectangle((hx1, hy1, hx2, hy2), radius=28, fill=(4, 12, 29, 242),
                           outline=(36, 126, 220, 230), width=2)
    draw.rounded_rectangle((hx1 + 8, hy1 + 8, hx2 - 8, hy2 - 8), radius=22,
                           outline=(44, 246, 255, 105), width=1)
    draw.rounded_rectangle((hx1 + 20, hy1 + 18, hx1 + 27, hy2 - 18), radius=3,
                           fill=neon_cyan)
    draw.text((hx1 + 46, hy1 + 23), "KAXMOK", font=_font(25, True), fill=white)
    draw.text((hx1 + 48, hy1 + 55), "24/7 MUSIC  /  LIVE TRANSMISSION",
              font=_font(11, True), fill=neon_cyan)
    draw.ellipse((hx1 + 49, hy1 + 91, hx1 + 60, hy1 + 102), fill=(255, 70, 105, 255))
    draw.text((hx1 + 70, hy1 + 88), "ON AIR", font=_font(12, True), fill=white)
    draw.text((hx1 + 48, hy1 + 121), f"STREAM  {duration_text}",
              font=_font(13, True), fill=muted)
    draw.text((hx1 + 48, hy1 + 145), milestone_text,
              font=_font(10, True), fill=neon_purple if not completed else neon_cyan)

    # Featured India clock.
    india_left = hx1 + 330
    draw.rounded_rectangle((india_left, hy1 + 22, india_left + 310, hy2 - 22),
                           radius=18, fill=(9, 25, 51, 230),
                           outline=(44, 246, 255, 115), width=1)
    draw.text((india_left + 20, hy1 + 35), "INDIA  /  IST",
              font=_font(13, True), fill=neon_cyan)
    draw.text((india_left + 18, hy1 + 60), now.strftime("%I:%M:%S").lstrip("0"),
              font=_font(39, True), fill=white)
    draw.text((india_left + 226, hy1 + 80), now.strftime("%p"),
              font=_font(14, True), fill=neon_cyan)
    draw.text((india_left + 20, hy1 + 113), date_text,
              font=_font(10, True), fill=muted)

    # Global clocks: evenly spaced, no hard-coded time offsets.
    cities = [
        ("NEW YORK", "America/New_York"),
        ("LONDON", "Europe/London"),
        ("DUBAI", "Asia/Dubai"),
        ("TOKYO", "Asia/Tokyo"),
    ]
    right_x = india_left + 340
    available = hx2 - right_x - 24
    cell_w = available // len(cities)
    for index, (city, zone_name) in enumerate(cities):
        cx = right_x + index * cell_w
        city_now = datetime.now(ZoneInfo(zone_name))
        if index == 0:
            draw.line((cx - 14, hy1 + 30, cx - 14, hy2 - 30),
                      fill=(55, 112, 170, 150), width=1)
        else:
            draw.line((cx - 14, hy1 + 30, cx - 14, hy2 - 30),
                      fill=(55, 112, 170, 105), width=1)
        draw.text((cx + 4, hy1 + 48), city, font=_font(12, True), fill=muted)
        draw.text((cx + 2, hy1 + 78), city_now.strftime("%I:%M").lstrip("0"),
                  font=_font(27, True), fill=neon_cyan)
        draw.text((cx + 105, hy1 + 90), city_now.strftime("%p"),
                  font=_font(10, True), fill=white)
        draw.text((cx + 4, hy1 + 119), "UTC " + city_now.strftime("%z")[:3],
                  font=_font(10, True), fill=muted)

    # Active chatters panel, ranked by total messages across this entire stream.
    active_rows = get_leaderboard(8)
    px1, py1, px2, py2 = 42, 264, 390, 760
    draw.rounded_rectangle((px1 + 6, py1 + 8, px2 + 6, py2 + 8), radius=24,
                           fill=(0, 0, 0, 105))
    draw.rounded_rectangle((px1, py1, px2, py2), radius=22, fill=(4, 12, 29, 238),
                           outline=(36, 126, 220, 225), width=2)
    draw.rounded_rectangle((px1 + 14, py1 + 14, px1 + 18, py2 - 14), radius=2,
                           fill=neon_cyan)
    draw.text((px1 + 30, py1 + 18), "COMMUNITY", font=_font(10, True), fill=neon_purple)
    draw.text((px1 + 30, py1 + 35), "TOP CHATTERS", font=_font(17, True), fill=white)
    draw.text((px1 + 30, py1 + 59), "FULL STREAM  •  TOTAL MESSAGES", font=_font(9, True), fill=muted)
    draw.line((px1 + 24, py1 + 75, px2 - 18, py1 + 75), fill=(55, 112, 170, 145), width=1)
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
            small_avatar = avatar.resize((38, 38), Image.Resampling.LANCZOS)
            overlay.paste(small_avatar, (ax, ay))
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

    # Right-hand panel is reserved for the AI word-hunt game.


    # Premium KAXMOK pinned-message spotlight.
    pinned = get_pinned_message()
    if pinned["message"]:
        bx1, by1, bx2, by2 = 250, 754, width - 250, 910

        # Soft shadow, neon frame, and layered glass surface.
        draw.rounded_rectangle((bx1 + 10, by1 + 12, bx2 + 10, by2 + 12),
                               radius=32, fill=(0, 0, 0, 145))
        draw.rounded_rectangle((bx1 - 7, by1 - 7, bx2 + 7, by2 + 7),
                               radius=37, outline=(184, 81, 255, 75), width=3)
        draw.rounded_rectangle((bx1 - 2, by1 - 2, bx2 + 2, by2 + 2),
                               radius=33, outline=(44, 246, 255, 145), width=2)
        draw.rounded_rectangle((bx1, by1, bx2, by2), radius=30,
                               fill=(4, 8, 25, 250), outline=(105, 92, 255, 245), width=2)
        draw.rounded_rectangle((bx1 + 9, by1 + 9, bx2 - 9, by2 - 9),
                               radius=23, outline=(44, 246, 255, 85), width=1)

        # Header capsule and dual-color accent.
        draw.rounded_rectangle((bx1 + 24, by1 + 17, bx1 + 330, by1 + 51),
                               radius=16, fill=(13, 24, 51, 255),
                               outline=(44, 246, 255, 100), width=1)
        draw.rounded_rectangle((bx1 + 24, by1 + 17, bx1 + 31, by1 + 51),
                               radius=4, fill=(44, 246, 255, 255))
        draw.text((bx1 + 45, by1 + 25), "KAXMOK  /  MESSAGE SPOTLIGHT",
                  font=_font(14, True), fill=(220, 245, 255, 255))

        # Live status pill.
        badge_w = 118
        draw.rounded_rectangle((bx2 - badge_w - 25, by1 + 19, bx2 - 25, by1 + 50),
                               radius=15, fill=(47, 13, 43, 255),
                               outline=(255, 74, 130, 220), width=1)
        draw.ellipse((bx2 - badge_w - 10, by1 + 30, bx2 - badge_w - 1, by1 + 39),
                     fill=(255, 75, 115, 255))
        draw.text((bx2 - badge_w + 8, by1 + 26), "LIVE PIN",
                  font=_font(11, True), fill=(255, 235, 245, 255))

        # Decorative quote marks frame the message without stealing focus.
        draw.text((bx1 + 34, by1 + 69), "“", font=_font(43, True),
                  fill=(184, 81, 255, 220))
        pin_text = pinned["message"]
        plain_for_measure = _YT_EMOJI_TOKEN.sub("   ", pin_text)
        available_width = bx2 - bx1 - 150
        pin_font = _font(31 if len(pin_text) < 48 else 26, True)
        while draw.textlength(plain_for_measure, font=pin_font) > available_width and pin_font.size > 16:
            pin_font = _font(pin_font.size - 1, True)
        text_width = draw.textlength(plain_for_measure, font=pin_font)
        text_x = bx1 + 88 + max(0, (available_width - text_width) / 2)
        _draw_pin_rich_text(
            draw, overlay, pin_text, text_x, by1 + 77,
            pin_font, (250, 252, 255, 255), available_width
        )

        # Subtle footer and author credit.
        draw.line((bx1 + 30, by2 - 25, bx1 + 170, by2 - 25),
                  fill=(44, 246, 255, 155), width=2)
        author_label = (pinned.get("author") or "KAXMOK")[:28]
        author_text = f"PINNED BY  {author_label}"
        author_font = _font(10, True)
        author_width = draw.textlength(author_text, font=author_font)
        draw.text((bx2 - author_width - 30, by2 - 32), author_text,
                  font=author_font, fill=(164, 184, 218, 235))

    _draw_slap_animation(overlay, draw, monotonic_now)
    _draw_interaction_animation(overlay, draw, monotonic_now)

    # Bottom ticker: local time-based rotation, independent of chat or APIs.
    ticker_y = height - 82
    draw.rounded_rectangle((42, ticker_y, width - 42, height - 30), radius=13,
                           fill=(7, 3, 8, 222), outline=(85, 75, 180, 220), width=1)
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
