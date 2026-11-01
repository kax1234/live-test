import array
import json
import os
import re
import urllib.parse
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import leaderboard
import game_manager

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = ROOT / "background.jpg"
COMMAND_IMAGES = {"!blue": ROOT / "blue.jpg", "!pink": ROOT / "pink.jpg", "!rain": ROOT / "rain.jpg", "!lofi": ROOT / "lofi.jpg"}
RTMP_URL = "rtmp://a.rtmp.youtube.com/live2/" + os.environ["YT_STREAM_KEY"]
VIDEO_ID = os.environ.get("YT_VIDEO_ID", "").strip()
CONTROL_URL = os.environ.get("CONTROL_API_URL", "").rstrip("/")
RUNNER_TOKEN = os.environ.get("CONTROL_RUNNER_TOKEN", "")
GAME_OWNER_CHANNEL_ID = os.environ.get("GAME_OWNER_CHANNEL_ID", "").strip()
GAME_ADMIN_IDS = {value.strip() for value in os.environ.get("GAME_ADMIN_IDS", "").split(",") if value.strip()}
SONGS = sorted(p for p in (ROOT / "songs").rglob("*") if p.is_file() and p.suffix.lower() == ".mp3")
print(f"[MUSIC] Loaded {len(SONGS)} MP3 tracks.", flush=True)
current_image = DEFAULT_IMAGE
image_lock = threading.Lock()
stop_event = threading.Event()
audio_level = 0.0
control_lock = threading.Lock()
control = {"index": 0, "paused": False, "volume": 80, "revision": 0}
last_command_id = None


def control_request(path, payload):
    if not CONTROL_URL or not RUNNER_TOKEN:
        return None
    req = urllib.request.Request(CONTROL_URL + path, data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + RUNNER_TOKEN, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode())


def remote_control():
    global last_command_id
    while not stop_event.is_set():
        try:
            result = control_request("/api/poll", {"status": {"track": SONGS[control["index"]].name if SONGS else "", "paused": control["paused"], "volume": control["volume"]}})
            cmd = (result or {}).get("command")
            if cmd and cmd.get("id") != last_command_id:
                action = cmd.get("action")
                with control_lock:
                    if action == "next":
                        control["index"] = (control["index"] + 1) % len(SONGS)
                    elif action == "previous":
                        control["index"] = (control["index"] - 1) % len(SONGS)
                    elif action == "choose":
                        match = next((i for i, p in enumerate(SONGS) if p.name == cmd.get("song")), None)
                        if match is not None: control["index"] = match
                    elif action == "pause": control["paused"] = True
                    elif action == "resume": control["paused"] = False
                    elif action == "volume": control["volume"] = max(0, min(100, int(cmd.get("value", 80))))
                    control["revision"] += 1
                    last_command_id = cmd.get("id")
                control_request("/api/poll", {"ack": last_command_id, "status": {"track": SONGS[control["index"]].name if SONGS else "", "paused": control["paused"], "volume": control["volume"]}})
        except Exception as exc:
            print(f"[CONTROL] relay unavailable: {exc}", flush=True)
        stop_event.wait(2)


def is_game_admin(event):
    """Authorize by immutable YouTube channel ID, never display name."""
    channel_id = str(event.get("author_id") or "").strip()
    if not channel_id:
        return False
    return channel_id == GAME_OWNER_CHANNEL_ID or channel_id in GAME_ADMIN_IDS


def handle_song_command(message, author):
    """Apply song commands directly from YouTube chat."""
    parts = message.split()
    action = parts[0] if parts else ""
    if action not in {"!next", "!prev", "!pause", "!resume", "!song", "!volume"}:
        return False
    with control_lock:
        if action == "!next":
            control["index"] = (control["index"] + 1) % len(SONGS)
        elif action == "!prev":
            control["index"] = (control["index"] - 1) % len(SONGS)
        elif action == "!pause":
            control["paused"] = True
        elif action == "!resume":
            control["paused"] = False
        elif action == "!song":
            if len(parts) != 2 or not parts[1].isdigit() or not 1 <= int(parts[1]) <= len(SONGS):
                print(f"[MUSIC] Usage: !song 1-{len(SONGS)}", flush=True)
                return True
            control["index"] = int(parts[1]) - 1
        elif action == "!volume":
            if len(parts) != 2 or not parts[1].isdigit() or not 0 <= int(parts[1]) <= 100:
                print("[MUSIC] Usage: !volume 0-100", flush=True)
                return True
            control["volume"] = int(parts[1])
        control["revision"] += 1
        idx, paused, volume = control["index"], control["paused"], control["volume"]
    print(f"[MUSIC CHAT] {author}: {message} -> {SONGS[idx].name}, paused={paused}, volume={volume}%", flush=True)
    return True


def listen_to_chat():
    """Read live chat using youtubei.js, the reader verified by the diagnostic workflow."""
    global current_image
    if not VIDEO_ID:
        print("Chat commands disabled: set YT_VIDEO_ID.", flush=True)
        return

    retry_delay = 10
    # Anyone may pin/unpin, with a 15-second per-user cooldown to limit spam.
    last_pin_command_at = {}
    pin_cooldown_seconds = 15
    helper = ROOT / "chat_reader.js"
    while not stop_event.is_set():
        proc = None
        try:
            print(f"[CHAT] Starting youtubei.js reader for video {VIDEO_ID}...", flush=True)
            proc = subprocess.Popen(
                ["node", str(helper), VIDEO_ID],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            # Forward helper diagnostics without allowing stderr to block the reader.
            def forward_stderr(child):
                for line in child.stderr:
                    print(line.rstrip(), flush=True)
            threading.Thread(target=forward_stderr, args=(proc,), daemon=True).start()

            while not stop_event.is_set():
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        raise RuntimeError(f"youtubei.js reader exited with code {proc.returncode}")
                    time.sleep(0.2)
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    print(f"[CHAT] Ignoring malformed reader event: {line[:160].rstrip()}", flush=True)
                    continue
                if event.get("type") == "error":
                    raise RuntimeError(event.get("message", "youtubei.js live-chat error"))
                if event.get("type") != "message":
                    continue

                raw_message = (event.get("message") or "").strip()
                if not raw_message:
                    continue
                author = (event.get("author") or "viewer").strip() or "viewer"
                avatar_url = event.get("avatar_url")
                message = raw_message.lower()
                if message.startswith("!game"):
                    if not is_game_admin(event):
                        print(f"[GAME AUTH] Rejected game-control command from {author}.", flush=True)
                    else:
                        parts = message.split()
                        if len(parts) == 2 and game_manager.switch(parts[1]):
                            print(f"[GAME] {author} switched game to {game_manager.active_game()}.", flush=True)
                        else:
                            print("[GAME] Usage: !game whoami | !game codebreaker | !game off", flush=True)
                    continue

                leaderboard.award_message(author, avatar_url=avatar_url)
                leaderboard.add_chat_message(author, raw_message, avatar_url=avatar_url)
                # Public !pin/!unpin commands; apply a per-user cooldown to reduce banner spam.
                command_parts = raw_message.split(maxsplit=1)
                command = command_parts[0].casefold() if command_parts else ""
                if command in {"!pin", "!unpin"}:
                    pin_user_key = author.lstrip("@").strip().casefold()
                    now = time.monotonic()
                    previous_pin_command = last_pin_command_at.get(pin_user_key, 0.0)
                    if now - previous_pin_command < pin_cooldown_seconds:
                        wait_left = max(1, int(pin_cooldown_seconds - (now - previous_pin_command)))
                        print(f"[PIN] Cooldown: ignored {command} from {author}; wait {wait_left}s", flush=True)
                    else:
                        last_pin_command_at[pin_user_key] = now
                        if command == "!unpin":
                            leaderboard.clear_pinned_message()
                            print(f"[PIN] Banner cleared by {author}", flush=True)
                        else:
                            pin_text = command_parts[1].strip() if len(command_parts) > 1 else ""
                            if not pin_text:
                                pin_text = "✨ REDEEM REWARDS WITH !SHOP 👑"
                            leaderboard.set_pinned_message(pin_text[:180], author)
                            print(f"[PIN] Banner updated by {author}: {pin_text[:200]}", flush=True)
                    continue
                if handle_song_command(message, author):
                    continue
                if game_manager.handle_guess(author, raw_message):
                    continue
                if message.strip() in COMMAND_IMAGES:
                    with image_lock:
                        current_image = COMMAND_IMAGES[message.strip()]
                    print(f"[CHAT] {author}: {message.strip()} -> {current_image.name}", flush=True)

        except Exception as exc:
            if not stop_event.is_set():
                print(f"[CHAT] Reader failed: {type(exc).__name__}: {exc}", flush=True)
                print(f"[CHAT] Retrying in {retry_delay}s; music publisher will continue.", flush=True)
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if not stop_event.is_set():
            stop_event.wait(retry_delay)


def main():
    global audio_level
    if not DEFAULT_IMAGE.is_file(): raise SystemExit("background.jpg is missing.")
    for image in COMMAND_IMAGES.values():
        if not image.is_file(): raise SystemExit(f"Missing image: {image.name}")
    if not SONGS: raise SystemExit("No MP3 files found in songs/.")
    audio_fifo = "/tmp/kaxmok-audio.pcm"
    try: os.unlink(audio_fifo)
    except FileNotFoundError: pass
    os.mkfifo(audio_fifo)

    game_manager.start()
    threading.Thread(target=listen_to_chat, daemon=True).start()
    if CONTROL_URL and RUNNER_TOKEN: threading.Thread(target=remote_control, daemon=True).start()

    publisher = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "image2pipe", "-framerate", "1", "-vcodec", "mjpeg", "-i", "pipe:0",
        "-thread_queue_size", "512", "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", audio_fifo,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-b:v", "1500k",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-af", "aresample=async=1:first_pts=0", "-max_muxing_queue_size", "2048", "-flvflags", "no_duration_filesize", "-t", "05:50:00", "-f", "flv", RTMP_URL
    ]
    proc = subprocess.Popen(publisher, stdin=subprocess.PIPE)
    audio_thread = threading.Thread(target=audio_producer, args=(audio_fifo,), daemon=True)
    audio_thread.start()
    try:
        while proc.poll() is None:
            with image_lock: image_path = current_image
            try:
                proc.stdin.write(game_manager.render_overlay(leaderboard.render_overlay(image_path.read_bytes(), audio_level=audio_level)))
                proc.stdin.flush()
            except (BrokenPipeError, OSError): break
            time.sleep(1)
    except KeyboardInterrupt: pass
    finally:
        stop_event.set()
        if proc.poll() is None: proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        try: os.unlink(audio_fifo)
        except OSError: pass


def audio_producer(fifo):
    global audio_level
    # Open once: this remains connected to the single publisher for the entire stream.
    with open(fifo, "wb", buffering=0) as output:
        decoder = None
        active_revision = -1
        current_song = -1
        silence = bytes(4096)
        try:
            while not stop_event.is_set():
                with control_lock:
                    idx, paused, volume, revision = control["index"], control["paused"], control["volume"], control["revision"]
                if revision != active_revision or decoder is None:
                    if decoder and decoder.poll() is None:
                        decoder.terminate()
                        try: decoder.wait(timeout=2)
                        except subprocess.TimeoutExpired: decoder.kill()
                    active_revision = revision
                    current_song = idx
                    decoder = None
                    if not paused:
                        decoder = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-re", "-i", str(SONGS[idx]), "-vn", "-af", f"aresample=44100:async=1:first_pts=0,volume={volume/100:.3f}", "-ac", "2", "-ar", "44100", "-sample_fmt", "s16", "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
                    print(f"[MUSIC] {'Paused' if paused else SONGS[idx].name} | volume {volume}%", flush=True)
                if paused or decoder is None:
                    output.write(silence)
                    time.sleep(0.046)
                    continue
                chunk = decoder.stdout.read(16384)
                if chunk:
                    output.write(chunk)
                    samples = array.array("h")
                    samples.frombytes(chunk[:len(chunk) - len(chunk)%2])
                    if samples:
                        rms = (sum(s*s for s in samples)/len(samples))**0.5
                        audio_level = min(1.0, rms/9000.0)
                else:
                    with control_lock:
                        if control["revision"] == active_revision:
                            control["index"] = (control["index"] + 1) % len(SONGS)
                            control["revision"] += 1
        finally:
            if decoder and decoder.poll() is None: decoder.terminate()


if __name__ == "__main__":
    main()
