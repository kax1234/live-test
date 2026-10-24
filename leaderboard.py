"""Lightweight KAXMOK audio visualizer."""
import math
import time
from datetime import datetime, timezone, timedelta
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


def _font(size, bold=False):
    paths = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def award_message(viewer_name, now=None):
    return None


def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0):
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGB")
    if base.size != (width, height):
        base = base.resize((width, height), Image.Resampling.BILINEAR)
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    sw, sh = 620, 66
    sx, sy = (width - sw) // 2, height - sh - 28
    draw.rounded_rectangle((sx - 18, sy - 22, sx + sw + 18, sy + sh + 12), radius=16, fill=(5, 8, 20, 135))
    draw.text((sx, sy - 17), "K A X M O K  •  LIVE AUDIO", font=_font(12, True), fill=(245, 211, 132, 235))
    # Local, API-free livestream info card: clock + rotating short messages.
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    clock_text = now.strftime("%I:%M %p  •  %d %b").lstrip("0")
    messages = [
        "🎧 Stay tuned • Good music, good mood",
        "💬 Say hi in live chat!",
        "🌙 Late-night vibes, nonstop music",
        "🎵 Which song matches your mood?",
        "💜 You are listening to KAXMOK LIVE",
        "✨ Relax • Recharge • Repeat",
        "🎶 Share the vibe with a friend",
        "☁️ Take a breath and enjoy the music",
    ]
    message = messages[int(time.time() // 18) % len(messages)]
    card_x1, card_y1, card_x2, card_y2 = 45, 45, 620, 150
    draw.rounded_rectangle(
        (card_x1, card_y1, card_x2, card_y2), radius=20,
        fill=(5, 8, 20, 190), outline=(118, 135, 255, 210), width=2
    )
    draw.text((card_x1 + 22, card_y1 + 15), "KAXMOK  •  LIVE NOW",
              font=_font(20, True), fill=(245, 211, 132, 255))
    draw.text((card_x1 + 22, card_y1 + 47), clock_text,
              font=_font(17, True), fill=(240, 244, 255, 255))
    draw.text((card_x1 + 22, card_y1 + 76), message,
              font=_font(14, False), fill=(190, 202, 235, 255))
    level = max(0.0, min(1.0, float(audio_level)))
    bars, gap = 32, 7
    bw = (sw - gap * (bars - 1)) // bars
    for i in range(bars):
        wave = 0.25 + 0.75 * abs(math.sin(i * 0.55))
        bh = max(3, int(4 + 42 * level * wave))
        bx, by = sx + i * (bw + gap), sy + sh - bh
        color = (245, 211, 132, 225) if i % 4 == 0 else (118, 135, 255, 215)
        draw.rounded_rectangle((bx, by, bx + bw, sy + sh), radius=3, fill=color)
    out = BytesIO()
    Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB").save(out, format="JPEG", quality=68)
    return out.getvalue()


def get_points(viewer_name):
    return 0


def get_leaderboard(limit=10):
    return []
