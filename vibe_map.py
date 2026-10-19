"""Tiny Vibe Map overlay for the existing KAXMOK FFmpeg stream."""
import math
import time
from collections import deque
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

MAX_ACTIVE = 4
ACTIVE_SECONDS = 300
_recent = {}


def mark_chat(name, now=None):
    """Record a chatter's latest activity; keep the map to four recent people."""
    now = time.monotonic() if now is None else now
    name = str(name or "viewer").strip()[:22] or "viewer"
    key = name.casefold()
    _recent[key] = (name, now)
    expired = [k for k, (_, stamp) in _recent.items() if now - stamp > ACTIVE_SECONDS]
    for key_to_remove in expired:
        _recent.pop(key_to_remove, None)
    if len(_recent) > 40:
        for key_to_remove, _ in sorted(_recent.items(), key=lambda item: item[1][1])[:-40]:
            _recent.pop(key_to_remove, None)


def _font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render(frame_bytes, now=None):
    """Draw four active-chat slots on the existing frame; never touches audio."""
    now = time.monotonic() if now is None else now
    active = sorted(
        ((name, stamp) for name, stamp in _recent.values() if now - stamp <= ACTIVE_SECONDS),
        key=lambda item: item[1], reverse=True
    )[:MAX_ACTIVE]
    with Image.open(BytesIO(frame_bytes)) as source:
        base = source.convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    x, y = 1510, 42
    draw.rounded_rectangle((x, y, 1880, y + 214), radius=18,
                           fill=(5, 10, 25, 168), outline=(115, 157, 255, 190), width=2)
    draw.text((x + 20, y + 16), "KAXMOK VIBE MAP", font=_font(20), fill=(245, 211, 132, 255))
    draw.text((x + 20, y + 46), "ACTIVE CHATTERS · 5 MIN", font=_font(12), fill=(173, 196, 235, 255))
    # Fixed four slots; subtle constellation links avoid expensive effects.
    centers = [(x + 31, y + 91 + i * 29) for i in range(MAX_ACTIVE)]
    for i in range(1, len(active)):
        draw.line((centers[i-1][0], centers[i-1][1], centers[i][0], centers[i][1]),
                  fill=(105, 155, 255, 90), width=1)
    for i in range(MAX_ACTIVE):
        cx, cy = centers[i]
        if i < len(active):
            name, stamp = active[i]
            draw.ellipse((cx-5, cy-5, cx+5, cy+5), fill=(135, 190, 255, 255))
            draw.ellipse((cx-9, cy-9, cx+9, cy+9), outline=(135, 190, 255, 100), width=1)
            draw.text((cx + 20, cy - 9), name[:22], font=_font(15), fill=(240, 245, 255, 255))
        else:
            draw.ellipse((cx-3, cy-3, cx+3, cy+3), fill=(90, 110, 150, 160))
            draw.text((cx + 20, cy - 8), "waiting for a chatter...", font=_font(13),
                      fill=(130, 145, 175, 210))
    out = BytesIO()
    base.convert("RGB").save(out, format="JPEG", quality=68, optimize=False)
    return out.getvalue()
