import array
import json
import os
import queue
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
ANALYTICS_URL = os.environ.get("ANALYTICS_URL", "").rstrip("/")
ANALYTICS_INGEST_TOKEN = os.environ.get("ANALYTICS_INGEST_TOKEN", "")
analytics_queue = queue.Queue(maxsize=5000)
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



def enqueue_analytics_event(event):
    """Queue viewer metadata only; never send or store chat message text."""
    if not ANALYTICS_URL or not ANALYTICS_INGEST_TOKEN:
        return
    author = str(event.get("author") or "Viewer").strip() or "Viewer"
    author_id = str(event.get("author_id") or "").strip()
    if not author_id and author.lower() != "viewer":
        author_id = "display-name:" + author.lower()
    if not author_id:
        print("[ANALYTICS] Skipped chat event: reader supplied no author ID or name.", flush=True)
        return
    item = {
        "author_id": author_id[:200],
        "author": author[:100],
        "avatar_url": str(event.get("avatar_url") or "")[:1000],
        "is_moderator": bool(event.get("is_moderator")),
    }
    try:
        analytics_queue.put_nowait(item)
    except queue.Full:
        print("[ANALYTICS] Queue full; dropping one metadata event.", flush=True)


def analytics_sender():
    """Batch metadata to the Cloudflare Worker without blocking the music/chat loop."""
    endpoint = ANALYTICS_URL + "/api/ingest"
    while not stop_event.is_set() or not analytics_queue.empty():
        try:
            first = analytics_queue.get(timeout=1)
        except queue.Empty:
            continue
        batch = [first]
        deadline = time.monotonic() + 1.0
        while len(batch) < 100 and time.monotonic() < deadline:
            try:
                batch.append(analytics_queue.get_nowait())
            except queue.Empty:
                time.sleep(0.05)
        payload = json.dumps({"messages": batch}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Authorization": "Bearer " + ANALYTICS_INGEST_TOKEN,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        sent = False
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and result.get("ok"):
                        print(
                            f"[ANALYTICS] Sent {result.get('accepted', len(batch))} chat metadata events.",
                            flush=True,
                        )
                        sent = True
                        break
                    raise RuntimeError("Worker rejected analytics batch")
            except Exception as exc:
                print(f"[ANALYTICS] Send attempt {attempt + 1}/3 failed: {type(exc).__name__}: {exc}", flush=True)
                time.sleep(2 * (attempt + 1))
        if not sent:
            print(f"[ANALYTICS] Dropped batch of {len(batch)} events after retries.", flush=True)


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
    last_slap_command_at = {}
    last_interaction_command_at = {}
    interaction_cooldown_seconds = 8
    slap_cooldown_seconds = 8
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

                print(
                    "[CHAT DEBUG] Message event received; author_id_present="
                    + str(bool(event.get("author_id")))
                    + "; author_present="
                    + str(bool(event.get("author")))
                    + "; analytics_queue="
                    + str(analytics_queue.qsize()),
                    flush=True,
                )
                enqueue_analytics_event(event)
                raw_message = (event.get("message") or "").strip()
                if not raw_message:
                    continue
                author = (event.get("author") or "viewer").strip() or "viewer"
                avatar_url = event.get("avatar_url")
                message = raw_message.lower()
                if message.startswith("!game"):
                    # Public game control: every viewer may switch the active chat game.
                    parts = message.split()
                    if len(parts) == 2 and game_manager.switch(parts[1]):
                        print(f"[GAME] {author} switched game to {game_manager.active_game()}.", flush=True)
                    else:
                        print("[GAME] Usage: !game mystery | !game whoami | !game codebreaker | !game off", flush=True)
                    continue


                # Public playful interactions; profile pictures are used when already available.
                interaction_parts = raw_message.split()
                interaction_command = interaction_parts[0].casefold() if interaction_parts else ""
                interaction_kinds = {
                    "!hug": "hug", "!highfive": "highfive", "!duel": "duel",
                    "!crown": "crown", "!shield": "shield", "!dance": "dance",
                    "!love": "love", "!hate": "hate"
                }
                if interaction_command in interaction_kinds:
                    kind = interaction_kinds[interaction_command]
                    needs_target = kind != "dance"
                    if (needs_target and len(interaction_parts) != 2) or (not needs_target and len(interaction_parts) != 1):
                        print(f"[INTERACTION] Usage: {interaction_command}" + (" @username" if needs_target else ""), flush=True)
                    else:
                        target = interaction_parts[1].lstrip("@")[:24] if needs_target else None
                        user_key = author.casefold()
                        now = time.monotonic()
                        previous = last_interaction_command_at.get(user_key, 0.0)
                        if now - previous < interaction_cooldown_seconds:
                            print(f"[INTERACTION] Cooldown active for {author}", flush=True)
                        elif target and target.casefold() == author.lstrip("@").casefold():
                            print(f"[INTERACTION] Choose another viewer, {author}.", flush=True)
                        else:
                            last_interaction_command_at[user_key] = now
                            score = __import__("random").randint(0, 100) if kind in {"love", "hate"} else None
                            leaderboard.set_interaction_animation(kind, author, target, score, avatar_url)
                            print(f"[INTERACTION] {kind}: {author}" + (f" -> {target}" if target else "") + (f" ({score}%)" if score is not None else ""), flush=True)
                    continue

                # Public comic !slap @viewer command with a per-user cooldown.
                slap_parts = raw_message.split()
                if slap_parts and slap_parts[0].casefold() == "!slap":
                    if len(slap_parts) != 2:
                        print(f"[SLAP] Usage: !slap @username (requested by {author})", flush=True)
                    else:
                        target = slap_parts[1].lstrip("@")[:24]
                        slap_key = author.casefold()
                        now = time.monotonic()
                        previous = last_slap_command_at.get(slap_key, 0.0)
                        if now - previous < slap_cooldown_seconds:
                            print(f"[SLAP] Cooldown active for {author}", flush=True)
                        elif target.casefold() == author.lstrip("@").casefold():
                            print(f"[SLAP] {author} tried to slap themselves; ignored.", flush=True)
                        else:
                            last_slap_command_at[slap_key] = now
                            leaderboard.set_slap_animation(author, target)
                            print(f"[SLAP] Comic animation: {author} -> {target}", flush=True)
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

    if CONTROL_URL and RUNNER_TOKEN:
        leaderboard.configure_persistence(CONTROL_URL, RUNNER_TOKEN)
        threading.Thread(target=leaderboard.persistence_loop, daemon=True).start()
        threading.Thread(target=remote_control, daemon=True).start()
    else:
        print('[LEADERBOARD] Cloudflare persistence is not configured.', flush=True)
    game_manager.start()
    if ANALYTICS_URL and ANALYTICS_INGEST_TOKEN:
        threading.Thread(target=analytics_sender, name="analytics-sender", daemon=True).start()
        print("[ANALYTICS] Cloudflare analytics sender enabled.", flush=True)
    else:
        print("[ANALYTICS] Disabled: set ANALYTICS_URL and ANALYTICS_INGEST_TOKEN.", flush=True)
    threading.Thread(target=listen_to_chat, daemon=True).start()

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
        leaderboard.flush_persistent_leaderboard()
        stop_event.set()
        if proc.poll() is None: proc.terminate()
        try: proc.wait(timeout=10)
        except subprocess.TimeoutExpired: proc.kill()
        try: os.unlink(audio_fifo)
        except OSError: pass


def audio_producer(fifo):
    """Keep the single audio FIFO alive; recover if an individual track decoder fails."""
    global audio_level
    with open(fifo, "wb", buffering=0) as output:
        decoder = None
        active_revision = -1
        silence = bytes(4096)
        try:
            while not stop_event.is_set():
                with control_lock:
                    idx = control["index"] % len(SONGS)
                    paused = control["paused"]
                    volume = control["volume"]
                    revision = control["revision"]

                # Drain all buffered PCM before treating a finished FFmpeg process as EOF.
                # Checking poll() here can restart the same track and discard unread pipe data.
                if revision != active_revision:
                    if decoder:
                        try:
                            if decoder.stdout:
                                decoder.stdout.close()
                            if decoder.poll() is None:
                                decoder.terminate()
                                decoder.wait(timeout=2)
                        except Exception:
                            try: decoder.kill()
                            except Exception: pass
                    decoder = None
                    active_revision = revision
                    if not paused:
                        try:
                            decoder = subprocess.Popen(
                                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                                 "-threads", "1", "-re", "-i", str(SONGS[idx]),
                                 "-map", "0:a:0", "-vn",
                                 "-af", f"aresample=44100:async=1:first_pts=0,volume={volume/100:.3f}",
                                 "-ac", "2", "-ar", "44100", "-sample_fmt", "s16",
                                 "-f", "s16le", "pipe:1"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                            )
                            print(f"[MUSIC] Playing {SONGS[idx].name} | volume {volume}%", flush=True)
                        except Exception as exc:
                            print(f"[MUSIC] Could not start {SONGS[idx].name}: {type(exc).__name__}: {exc}", flush=True)
                            with control_lock:
                                control["index"] = (idx + 1) % len(SONGS)
                                control["revision"] += 1
                            output.write(silence)
                            time.sleep(0.25)
                            continue
                    else:
                        print(f"[MUSIC] Paused | volume {volume}%", flush=True)

                if paused or decoder is None:
                    output.write(silence)
                    time.sleep(0.046)
                    continue

                try:
                    chunk = decoder.stdout.read(8192)
                except (OSError, ValueError) as exc:
                    print(f"[MUSIC] Decoder read failed: {exc}; moving to next track.", flush=True)
                    chunk = b""

                if chunk:
                    output.write(chunk)
                    samples = array.array("h")
                    samples.frombytes(chunk[:len(chunk) - len(chunk) % 2])
                    if samples:
                        rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
                        audio_level = min(1.0, rms / 9000.0)
                else:
                    print(f"[MUSIC] Track finished or decoder stopped: {SONGS[idx].name}; loading next.", flush=True)
                    if decoder and decoder.stdout:
                        try: decoder.stdout.close()
                        except OSError: pass
                    if decoder and decoder.poll() is None:
                        decoder.terminate()
                    decoder = None
                    with control_lock:
                        if control["revision"] == active_revision:
                            control["index"] = (idx + 1) % len(SONGS)
                            control["revision"] += 1
                    time.sleep(0.08)
        finally:
            if decoder:
                try:
                    if decoder.stdout: decoder.stdout.close()
                    if decoder.poll() is None: decoder.terminate()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
