"""KAXMOK neon overlay: local clock, rotating ticker, and stream milestones.

This module is intentionally self-contained: no chat, OAuth, network, or API calls.
"""
import math
import time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

_STREAM_STARTED = time.monotonic()
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


def award_message(viewer_name, now=None):
    """Compatibility no-op; overlay features never depend on chat."""
    return None


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

    # Wide futuristic world-clock HUD inspired by the supplied reference.
    # Keep the card compact enough to leave the central background visible.
    hx1, hy1, hx2, hy2 = 42, 42, width - 42, 222
    draw.rounded_rectangle((hx1, hy1, hx2, hy2), radius=28, fill=(4, 12, 29, 232),
                           outline=(24, 151, 255, 245), width=3)
    draw.rounded_rectangle((hx1 + 8, hy1 + 8, hx2 - 8, hy2 - 8), radius=22,
                           outline=(44, 246, 255, 190), width=2)
    draw.text((hx1 + 28, hy1 + 14), "KAXMOK  //  WORLD CLOCK", font=_font(16, True), fill=neon_cyan)
    draw.ellipse((hx2 - 116, hy1 + 20, hx2 - 104, hy1 + 32), fill=(255, 65, 105, 255))
    draw.text((hx2 - 95, hy1 + 16), "LIVE", font=_font(12, True), fill=white)

    # India gets the prominent clock panel on the left.
    india_x = hx1 + 28
    draw.text((india_x, hy1 + 47), "INDIA  /  IST", font=_font(18, True), fill=white)
    draw.text((india_x, hy1 + 69), now.strftime("%I:%M:%S").lstrip("0"), font=_font(43, True), fill=neon_cyan)
    draw.text((india_x + 270, hy1 + 89), now.strftime("%p"), font=_font(18, True), fill=white)
    draw.text((india_x + 4, hy1 + 128), now.strftime("%a, %d %b %Y").upper(), font=_font(12, True), fill=muted)
    draw.line((hx1 + 350, hy1 + 45, hx1 + 350, hy2 - 18), fill=(70, 110, 165, 210), width=2)

    cities = [
        ("NEW YORK", "America/New_York", "NY"),
        ("LONDON", "Europe/London", "UK"),
        ("DUBAI", "Asia/Dubai", "AE"),
        ("TOKYO", "Asia/Tokyo", "JP"),
    ]
    right_x = hx1 + 374
    available = hx2 - right_x - 20
    cell_w = available // len(cities)
    for index, (city, zone_name, country_code) in enumerate(cities):
        cx = right_x + index * cell_w
        city_now = datetime.now(ZoneInfo(zone_name))
        if index:
            draw.line((cx - 14, hy1 + 55, cx - 14, hy2 - 30), fill=(70, 110, 165, 180), width=1)
        draw.text((cx, hy1 + 52), city, font=_font(14, True), fill=white)
        draw.text((cx, hy1 + 84), city_now.strftime("%I:%M").lstrip("0"), font=_font(29, True), fill=neon_cyan)
        draw.text((cx + 106, hy1 + 95), city_now.strftime("%p"), font=_font(12, True), fill=white)
        offset = city_now.strftime("%z")
        offset = f"UTC {int(offset[:3]):+d}" + (f":{offset[3:]}" if offset[3:] != "00" else "")
        draw.text((cx, hy1 + 127), offset, font=_font(13, True), fill=muted)

    # Stream status ribbon below the clock; milestones are calculated locally.
    draw.rounded_rectangle((hx1 + 20, hy2 - 34, hx2 - 20, hy2 - 10), radius=8,
                           fill=(8, 20, 45, 235))
    draw.text((hx1 + 32, hy2 - 31), f"STREAM  {duration_text}", font=_font(10, True), fill=white)
    draw.text((hx1 + 210, hy2 - 31), milestone_text, font=_font(10, True), fill=milestone_color)

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


def get_points(viewer_name):
    return 0


def get_leaderboard(limit=10):
    return []
