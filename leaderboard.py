"""Lightweight KAXMOK audio visualizer."""
import math
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
