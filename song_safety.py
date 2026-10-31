"""Fail-closed song allowlist for the KAXMOK livestream.

YouTube does not expose a reliable per-track Content ID / strike lookup API.
This module therefore blocks every track unless its exact filename is explicitly
approved by the channel owner. It never claims that a track is copyright-safe.
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "song_safety.json"
SONG_DIR = ROOT / "songs"


def load_song_safety():
    if not CONFIG.is_file():
        raise SystemExit("song_safety.json is missing; strict mode refuses to play songs.")
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read song_safety.json: {exc}")
    if config.get("mode") != "strict":
        raise SystemExit("Only strict song-safety mode is supported.")
    approved = config.get("approved", [])
    blocked = config.get("blocked", {})
    if not isinstance(approved, list) or not all(isinstance(x, str) for x in approved):
        raise SystemExit('song_safety.json "approved" must be a list of exact MP3 filenames.')
    if not isinstance(blocked, dict):
        raise SystemExit('song_safety.json "blocked" must be an object of filename: reason.')
    files = sorted(p for p in SONG_DIR.rglob("*") if p.is_file() and p.suffix.lower() == ".mp3")
    by_name = {p.name: p for p in files}
    approved_set = set(approved)
    unknown = sorted(approved_set - set(by_name))
    if unknown:
        raise SystemExit("Approved filenames not found in songs/: " + ", ".join(unknown))
    playable = [by_name[name] for name in sorted(approved_set) if name not in blocked]
    excluded = []
    for path in files:
        if path.name in blocked:
            excluded.append((path.name, str(blocked[path.name]) or "Manually blocked"))
        elif path.name not in approved_set:
            excluded.append((path.name, "Not approved (strict mode)"))
    return playable, excluded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-summary", action="store_true")
    args = parser.parse_args()
    playable, excluded = load_song_safety()
    lines = [
        "## KAXMOK strict song safety report",
        "",
        f"- Approved and playable: **{len(playable)}**",
        f"- Blocked / awaiting approval: **{len(excluded)}**",
        "",
        "### Blocked / awaiting approval",
    ]
    if excluded:
        lines.extend(f"- `{name}` — {reason}" for name, reason in excluded)
    else:
        lines.append("- None")
    lines.extend(["", "### Approved and playable"])
    if playable:
        lines.extend(f"- `{path.name}`" for path in playable)
    else:
        lines.append("- None")
    report = "\n".join(lines) + "\n"
    print(report, flush=True)
    if args.github_summary:
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as handle:
                handle.write(report)
    if not playable:
        raise SystemExit("Strict mode: no approved songs. Add licensed/owned tracks to song_safety.json before starting the stream.")


if __name__ == "__main__":
    main()
