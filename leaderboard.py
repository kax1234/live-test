"""Lightweight KAXMOK audio visualizer with selective Words Become Light chat overlay."""
import math
import re
import time
from collections import deque
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

_words = deque(maxlen=3)
_recent = deque(maxlen=40)
_last_shown = 0.0

def _font(size, bold=False):
    paths = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()

def award_message(viewer_name, now=None):
    return None

def consider_chat_message(message, now=None):
    global _last_shown
    now = time.monotonic() if now is None else now
    text = re.sub(r"\\s+", " ", str(message or "")).strip()
    low = text.casefold()
    if not 4 <= len(text) <= 54 or text.startswith(("!", "/")):
        return False
    if "http://" in low or "https://" in low or not re.search(r"[a-zA-Z\\u00C0-\\u024F\\u0D00-\\u0D7F]", text):
        return False
    if re.search(r"(.)\\1{5,}", low) or low in _recent:
        return False
    _recent.append(low)
    if now - _last_shown < 9:
        return False
    _last_shown = now
    _words.append({"text": text, "created": now})
    return True

def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0):
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGB")
    if base.size != (width, height):
        base = base.resize((width, height), Image.Resampling.BILINEAR)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    now = time.monotonic()
    while _words and now - _words[0]["created"] > 12:
        _words.popleft()
    for i, item in enumerate(list(_words)):
        age = now - item["created"]
        alpha = int(230 * max(0.0, min(1.0, (12 - age) / 3.0)))
        font = _font(34 if len(item["text"]) < 28 else 25, True)
        box = draw.textbbox((0, 0), item["text"], font=font)
        tw = box[2] - box[0]
        x = max(35, min(width - tw - 35, (width - tw) // 2))
        y = 325 + i * 78
        draw.text((x, y), item["text"], font=font, fill=(150, 215, 255, alpha), stroke_width=3, stroke_fill=(35, 100, 255, alpha // 3))
        draw.ellipse((min(width - 20, x + tw + 10), y + 15, min(width - 12, x + tw + 18), y + 23), fill=(190, 230, 255, alpha))
    sw, sh = 620, 66
    sx, sy = (width - sw) // 2, height - sh - 28
    draw.rounded_rectangle((sx - 18, sy - 22, sx + sw + 18, sy + sh + 12), radius=16, fill=(5, 8, 20, 135))
    draw.text((sx, sy - 17), "K A X M O K  •  LIVE AUDIO", font=_font(12, True), fill=(245, 211, 132, 235))
    level = max(0.0, min(1.0, float(audio_level)))
    bars, gap = 32, 7
    bw = (sw - gap * (bars - 1)) // bars
    for i in range(bars):
        wave = 0.25 + 0.75 * abs(math.sin(i * 0.55 + now * 1.8))
        bh = max(3, int(4 + 42 * level * wave))
        bx, by = sx + i * (bw + gap), sy + sh - bh
        color = (245, 211, 132, 225) if i % 4 == 0 else (118, 135, 255, 215)
        draw.rounded_rectangle((bx, by, bx + bw, sy + sh), radius=3, fill=color)
    out = BytesIO()
    Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB").save(out, format="JPEG", quality=68)
    return out.getvalue()

def get_points(viewer_name): return 0
def get_leaderboard(limit=10): return []
def reset():
    _words.clear()
    _recent.clear()
