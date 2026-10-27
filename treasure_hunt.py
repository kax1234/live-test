"""In-memory YouTube chat treasure hunt for the KAXMOK livestream."""
import random
import threading
import time

_LOCK = threading.Lock()
_COOLDOWN = 12.0
_last_dig = {}
_coins = {}
_recent = []
_total_digs = 0
_total_coins = 0
_started = time.time()

# Weighted outcomes: the rewards are virtual points only.
_OUTCOMES = [
    (42, "Pebbles", 1, 8, "Common"),
    (30, "Silver coins", 9, 18, "Uncommon"),
    (18, "Gold chest", 20, 35, "Rare"),
    (8, "Crystal cache", 36, 60, "Epic"),
    (2, "Legendary relic", 75, 100, "Legendary"),
]
_TOTAL_WEIGHT = sum(item[0] for item in _OUTCOMES)


def handle_command(message, viewer_name, now=None):
    """Return a status string for game commands; return None for other chat."""
    global _total_digs, _total_coins
    parts = (message or "").strip().lower().split()
    if not parts or parts[0] not in {"!dig", "!coins", "!hunt"}:
        return None
    name = (viewer_name or "viewer").strip()[:32] or "viewer"
    key = name.casefold()
    stamp = time.time() if now is None else float(now)

    with _LOCK:
        if parts[0] == "!coins":
            balance = _coins.get(key, {}).get("coins", 0)
            return f"{name} has {balance} treasure coins."
        if parts[0] == "!hunt":
            return "Treasure Hunt: type !dig to search, !coins to check your balance. 12s cooldown."

        last = _last_dig.get(key, 0.0)
        remaining = _COOLDOWN - (stamp - last)
        if remaining > 0:
            return f"{name}, your next dig is ready in {int(remaining) + 1}s."
        _last_dig[key] = stamp
        _total_digs += 1

        roll = random.randint(1, _TOTAL_WEIGHT)
        selected = _OUTCOMES[-1]
        for outcome in _OUTCOMES:
            roll -= outcome[0]
            if roll <= 0:
                selected = outcome
                break
        _, treasure, low, high, rarity = selected
        reward = random.randint(low, high)
        entry = _coins.setdefault(key, {"name": name, "coins": 0, "finds": 0, "best": "—"})
        entry["name"] = name
        entry["coins"] += reward
        entry["finds"] += 1
        entry["best"] = rarity
        _total_coins += reward
        _recent.append({"name": name, "treasure": treasure, "rarity": rarity, "coins": reward, "time": stamp})
        del _recent[:-5]
        return f"{name} found {treasure} (+{reward} coins)!"


def snapshot():
    """Return a lock-safe view for the overlay."""
    with _LOCK:
        top = sorted(_coins.values(), key=lambda row: (-row["coins"], row["name"].casefold()))[:5]
        recent = [dict(row) for row in _recent]
        return {
            "top": [dict(row) for row in top],
            "recent": recent,
            "total_digs": _total_digs,
            "total_coins": _total_coins,
            "players": len(_coins),
            "uptime": max(0, int(time.time() - _started)),
        }
