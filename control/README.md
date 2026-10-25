# KAXMOK private song control — implementation notes

This branch contains a private song-control panel UI prototype only. It is intentionally not wired to the production stream.

## Why it is not live-connected yet
The current `chat_stream.py` streams `/tmp/combined.mp3` in a looping FFmpeg input. The workflow concatenates all MP3 files into that one file. That architecture has no per-track queue control, and the UI cannot safely pause, skip, or change the live volume by itself.

## Required next implementation step
Replace the combined-file input with a supervised playlist player that reports current track and supports next/pause/resume/volume. Keep the existing FFmpeg RTMP publisher alive while switching audio source. Then add a small authenticated control service bound to localhost, exposed only through a private authenticated tunnel or VPN. Never put `YT_STREAM_KEY` in browser code or send it to the panel.

## Security and deployment
- Use a separate control token stored as a GitHub Actions secret; never hard-code it.
- Require HTTPS and authentication, rate-limit requests, validate song IDs against the server-side playlist, and do not expose arbitrary shell commands.
- A GitHub-hosted runner is ephemeral; the panel is only reachable while that workflow run is alive. A private tunnel/VPN is needed for remote access.
- Do not run or merge this branch to production until playback control is implemented and tested with a non-production stream.
