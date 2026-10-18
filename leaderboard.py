"""Temporary in-memory points and cinematic overlay renderer for KAXMOK.

No YouTube API requests are made here. Points reset when the Python process
restarts. The existing stream script can call award_message() and render_overlay()
when connected in a later step.
"""

import time
from collections import defaultdict
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

POINTS_PER_MESSAGE = 1
VIEWER_COOLDOWN_SECONDS = 60
LEADERBOARD_LIMIT = 10

_points = defaultdict(int)
_last_award_at = {}


def award_message(viewer_name, now=None):
    """Award one point, at most once per cooldown per viewer."""
    name = str(viewer_name or "").strip()
    if not name:
        return None

    timestamp = time.monotonic() if now is None else float(now)
    key = name.casefold()
    last = _last_award_at.get(key)
    if last is not None and timestamp - last < VIEWER_COOLDOWN_SECONDS:
        return None

    _last_award_at[key] = timestamp
    _points[name] += POINTS_PER_MESSAGE
    return _points[name]


def get_points(viewer_name):
    """Return the current points for a viewer, or zero."""
    name = str(viewer_name or "").strip()
    if not name:
        return 0
    key = name.casefold()
    return next((total for stored_name, total in _points.items()
                 if stored_name.casefold() == key), 0)


def get_leaderboard(limit=LEADERBOARD_LIMIT):
    """Return [(viewer_name, points), ...], highest points first."""
    safe_limit = max(0, int(limit))
    return sorted(_points.items(), key=lambda item: (-item[1], item[0].casefold()))[:safe_limit]


def _font(size, bold=False):
    """Load a common Linux font, with Pillow's default as a fallback."""
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


def render_overlay(frame_bytes, width=1920, height=1080, audio_level=0.0):
    """Return a JPEG frame with a compact always-visible top-right leaderboard.

    The caller supplies the current background JPEG. This function does not
    touch video/audio publishing or call any external service.
    """
    base = Image.open(BytesIO(frame_bytes)).convert("RGB")
    base = base.resize((width, height), Image.Resampling.LANCZOS)

    panel_w = 360
    row_h = 36
    header_h = 58
    panel_h = header_h + row_h * LEADERBOARD_LIMIT + 18
    margin = 32
    x0 = width - panel_w - margin
    y0 = margin
    x1, y1 = x0 + panel_w, y0 + panel_h

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18,
                           fill=(8, 12, 27, 218),
                           outline=(198, 165, 91, 220), width=2)
    draw.rounded_rectangle((x0 + 2, y0 + 2, x1 - 2, y0 + header_h),
                           radius=16, fill=(27, 31, 57, 238))
    draw.rectangle((x0 + 2, y0 + header_h - 12, x1 - 2, y0 + header_h),
                   fill=(27, 31, 57, 238))

    draw.text((x0 + 18, y0 + 14), "KAXMOK  TOP 10", font=_font(23, True),
              fill=(245, 211, 132, 255))
    draw.text((x0 + 18, y0 + 38), "VIEWER LOYALTY", font=_font(11, True),
              fill=(185, 195, 220, 255))

    rows = get_leaderboard(LEADERBOARD_LIMIT)
    for index in range(LEADERBOARD_LIMIT):
        yy = y0 + header_h + 8 + index * row_h
        if index % 2 == 0:
            draw.rounded_rectangle((x0 + 10, yy, x1 - 10, yy + row_h - 2),
                                   radius=7, fill=(255, 255, 255, 13))
        if index < len(rows):
            name, points = rows[index]
            label = name[:22]
            color = (245, 211, 132, 255) if index == 0 else (236, 239, 249, 255)
            draw.text((x0 + 18, yy + 8), f"{index + 1:02d}", font=_font(15, True),
                      fill=(156, 169, 205, 255))
            draw.text((x0 + 55, yy + 8), label, font=_font(15, True), fill=color)
            score = f"{points} pts"
        else:
            draw.text((x0 + 18, yy + 8), f"{index + 1:02d}", font=_font(15, True),
                      fill=(115, 124, 150, 255))
            draw.text((x0 + 55, yy + 8), "Waiting for viewers", font=_font(13),
                      fill=(139, 148, 171, 255))
            score = "—"
        score_font = _font(13, True)
        bbox = draw.textbbox((0, 0), score, font=score_font)
        draw.text((x1 - 18 - (bbox[2] - bbox[0]), yy + 9), score,
                  font=score_font, fill=(190, 206, 255, 255))

    # Cinematic audio-reactive spectrum along the bottom edge.
    # audio_level is a normalized RMS estimate from the currently playing audio.
    level = max(0.0, min(1.0, float(audio_level)))
    spectrum_w = 620
    spectrum_h = 82
    sx = (width - spectrum_w) // 2
    sy = height - spectrum_h - 28
    draw.rounded_rectangle((sx - 22, sy - 12, sx + spectrum_w + 22, sy + spectrum_h + 12),
                           radius=18, fill=(5, 8, 20, 150),
                           outline=(198, 165, 91, 150), width=1)
    draw.text((sx, sy - 2), "K A X M O K   •   LIVE AUDIO", font=_font(12, True),
              fill=(245, 211, 132, 235))
    import math
    bars = 48
    gap = 5
    bar_w = (spectrum_w - gap * (bars - 1)) // bars
    for i in range(bars):
        # A moving cinematic pattern shaped by the measured audio RMS level.
        wave = 0.20 + 0.80 * abs(math.sin(i * 0.39 + time.monotonic() * 2.4))
        height_px = max(3, int((8 + 45 * level * wave)))
        bx = sx + i * (bar_w + gap)
        by = sy + spectrum_h - height_px
        color = (245, 211, 132, 230) if i % 4 == 0 else (118, 135, 255, 220)
        draw.rounded_rectangle((bx, by, bx + bar_w, sy + spectrum_h), radius=3, fill=color)

    return _jpeg_bytes(base, overlay)


def _jpeg_bytes(base, overlay):
    """Encode the composited frame as JPEG bytes."""
    out = BytesIO()
    Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB").save(
        out, format="JPEG", quality=92, optimize=True
    )
    return out.getvalue()


def reset():
    """Clear points and cooldowns; useful for tests."""
    _points.clear()
    _last_award_at.clear()
