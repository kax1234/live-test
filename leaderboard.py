"""Lightweight KAXMOK audio visualizer overlay (leaderboard removed)."""

import math
import time
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont


def _font(size, bold=False):
    paths = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"]
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def award_message(viewer_name, now=None):
    """Compatibility no-op: leaderboard scoring is disabled."""
    return None


def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0,
                   welcome_name='', welcome_until=0.0):
    """Draw a compact audio-reactive visualizer and temporary welcome card."""
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGB")
    if base.size != (width, height):
        base = base.resize((width, height), Image.Resampling.BILINEAR)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    now = time.monotonic()

    # Compact bottom-center visualizer. No leaderboard panel or score tracking.
    spectrum_w, spectrum_h = 620, 66
    sx = (width - spectrum_w) // 2
    sy = height - spectrum_h - 28
    draw.rounded_rectangle(
        (sx - 18, sy - 22, sx + spectrum_w + 18, sy + spectrum_h + 12),
        radius=16, fill=(5, 8, 20, 135)
    )
    draw.text((sx, sy - 17), "K A X M O K  •  LIVE AUDIO",
              font=_font(12, True), fill=(245, 211, 132, 235))

    level = max(0.0, min(1.0, float(audio_level)))
    bars, gap = 32, 7
    bar_w = (spectrum_w - gap * (bars - 1)) // bars
    phase = now * 1.8
    for i in range(bars):
        wave = 0.25 + 0.75 * abs(math.sin(i * 0.55 + phase))
        bar_h = max(3, int(4 + 42 * level * wave))
        bx = sx + i * (bar_w + gap)
        by = sy + spectrum_h - bar_h
        color = (245, 211, 132, 225) if i % 4 == 0 else (118, 135, 255, 215)
        draw.rounded_rectangle((bx, by, bx + bar_w, sy + spectrum_h),
                               radius=3, fill=color)

    # Welcome card remains available, but only while a new viewer is announced.
    if welcome_name and now < welcome_until:
        remaining = max(0.0, welcome_until - now)
        alpha = int(205 * min(1.0, remaining / 1.5))
        wx, wy = 36, height - 160
        draw.rounded_rectangle(
            (wx, wy, wx + 410, wy + 88), radius=12,
            fill=(10, 13, 22, alpha),
            outline=(205, 211, 229, alpha), width=1
        )
        draw.text((wx + 18, wy + 13), "WELCOME TO KAXMOK",
                  font=_font(12, True), fill=(195, 203, 225, alpha))
        draw.text((wx + 18, wy + 38), str(welcome_name)[:24],
                  font=_font(22, True), fill=(245, 246, 250, alpha))

    out = BytesIO()
    Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB").save(
        out, format="JPEG", quality=68, optimize=False
    )
    return out.getvalue()


def get_points(viewer_name):
    return 0


def get_leaderboard(limit=10):
    return []


def reset():
    pass
