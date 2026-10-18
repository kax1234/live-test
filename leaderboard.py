"""Temporary in-memory viewer points for KAXMOK livestream.

This module is intentionally separate from chat_stream.py.
It does not make any YouTube API requests. The existing chat listener can
call award_message() and get_leaderboard() when we connect it in a later step.
Points reset when the Python process restarts.
"""

import time
from collections import defaultdict

POINTS_PER_MESSAGE = 1
VIEWER_COOLDOWN_SECONDS = 60
LEADERBOARD_LIMIT = 10

_points = defaultdict(int)
_last_award_at = {}


def award_message(viewer_name, now=None):
    """Award points for a qualifying chat message.

    Returns the viewer's updated total, or None if the viewer is still on
    cooldown. This function does not send messages or call external APIs.
    """
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
    """Return the current points for a viewer, or zero if not listed."""
    name = str(viewer_name or "").strip()
    if not name:
        return 0
    key = name.casefold()
    for stored_name, total in _points.items():
        if stored_name.casefold() == key:
            return total
    return 0


def get_leaderboard(limit=LEADERBOARD_LIMIT):
    """Return [(viewer_name, points), ...], highest points first."""
    safe_limit = max(0, int(limit))
    return sorted(_points.items(), key=lambda item: (-item[1], item[0].casefold()))[:safe_limit]


def reset():
    """Clear in-memory points and cooldowns; mainly useful for tests."""
    _points.clear()
    _last_award_at.clear()
