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

import pytchat
import leaderboard

# GitHub-hosted runners sometimes receive a YouTube HTML page without the
# channelId field pytchat normally scrapes. Try oEmbed first, then retain
# pytchat's original lookup as a fallback.
def _oembed_channel_id(video_id):
    try:
        watch_url = "https://www.youtube.com/watch?v=" + video_id
        request = urllib.request.Request(
            "https://www.youtube.com/oembed?url=" + urllib.parse.quote(watch_url, safe="") + "&format=json",
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        author_url = data.get("author_url", "")
        match = re.search(r"/channel/(UC[0-9A-Za-z_-]{22})", author_url)
        if match:
            return match.group(1)
        if "/@" in author_url:
            about_url = author_url.rstrip("/") + "/about"
            request = urllib.request.Request(
                about_url,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                page = response.read().decode("utf-8", errors="replace")
            match = re.search(r'"externalId"\\s*:\\s*"(UC[0-9A-Za-z_-]{22})"', page)
            if match:
                return match.group(1)
    except Exception as exc:
        print(f"[CHAT] oEmbed channel lookup unavailable: {type(exc).__name__}: {exc}", flush=True)
    return None


def _install_pytchat_channel_lookup_fallback():
    try:
        import importlib
        import pytchat.util as pytchat_util
        core_module = importlib.import_module("pytchat.core.pytchat")
        original = getattr(core_module, "get_channelid", None) or getattr(pytchat_util, "get_channelid", None)
        if original is None:
            print("[CHAT] pytchat lookup hook unavailable; using default lookup.", flush=True)
            return
        def lookup(video_id, *args, **kwargs):
            channel_id = _oembed_channel_id(video_id)
            return channel_id or original(video_id, *args, **kwargs)
        pytchat_util.get_channelid = lookup
        if hasattr(core_module, "get_channelid"):
            core_module.get_channelid = lookup
        print("[CHAT] Installed oEmbed-first channel lookup fallback.", flush=True)
    except Exception as exc:
        print(f"[CHAT] Could not install channel lookup fallback: {type(exc).__name__}: {exc}", flush=True)


_install_pytchat_channel_lookup_fallback()

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = ROOT / "background.jpg"
COMMAND_IMAGES = {"!blue": ROOT / "blue.jpg", "!pink": ROOT / "pink.jpg", "!rain": ROOT / "rain.jpg", "!lofi": ROOT / "lofi.jpg"}
RTMP_URL = "rtmp://a.rtmp.youtube.com/live2/" + os.environ["YT_STREAM_KEY"]
VIDEO_ID = os.environ.get("YT_VIDEO_ID", "").strip()
CONTROL_URL = os.environ.get("CONTROL_API_URL", "").rstrip("/")
RUNNER_TOKEN = os.environ.get("CONTROL_RUNNER_TOKEN", "")
SONGS = sorted(p for p in (ROOT / "songs").rglob("*") if p.is_file() and p.suffix.lower() == ".mp3")
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
    """Keep chat commands and leaderboard connected, retrying after reader failures."""
    global current_image
    if not VIDEO_ID:
        print("Chat commands disabled: set YT_VIDEO_ID.", flush=True)
        return

    retry_delay = 10
    while not stop_event.is_set():
        chat = None
        try:
            print(f"[CHAT] Connecting to YouTube live chat for video {VIDEO_ID}...", flush=True)
            chat = pytchat.create(video_id=VIDEO_ID, interruptable=False)
            while not stop_event.is_set() and chat.is_alive():
                for item in chat.get().sync_items():
                    message = (getattr(item, "message", "") or "").strip().lower()
                    author_obj = getattr(item, "author", None)
                    author = getattr(author_obj, "name", "viewer") or "viewer"
                    avatar_url = (getattr(author_obj, "image", None)
                                  or getattr(author_obj, "thumbnail", None)
                                  or getattr(author_obj, "photo", None))
                    raw_message = (getattr(item, "message", "") or "").strip()
                    if raw_message:
                        leaderboard.award_message(author, avatar_url=avatar_url)
                        leaderboard.add_chat_message(author, raw_message, avatar_url=avatar_url)
                    if handle_song_command(message, author):
                        continue
                    if message in COMMAND_IMAGES:
                        with image_lock:
                            current_image = COMMAND_IMAGES[message]
                        print(f"[CHAT] {author}: {message} -> {current_image.name}", flush=True)
                time.sleep(0.5)

            if not stop_event.is_set():
                print(f"[CHAT] Reader stopped; reconnecting in {retry_delay}s.", flush=True)
        except Exception as exc:
            if not stop_event.is_set():
                print(f"Chat reader failed: {type(exc).__name__}: {exc}", flush=True)
                print(f"[CHAT] Retrying in {retry_delay}s; music publisher will continue.", flush=True)
        finally:
            if chat:
                try:
                    chat.terminate()
                except Exception:
                    pass

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

    threading.Thread(target=listen_to_chat, daemon=True).start()
    if CONTROL_URL and RUNNER_TOKEN: threading.Thread(target=remote_control, daemon=True).start()

    publisher = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "image2pipe", "-framerate", "1", "-vcodec", "mjpeg", "-i", "pipe:0",
        "-f", "s16le", "-ar", "44100", "-ac", "2", "-i", audio_fifo,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-b:v", "1500k",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-t", "05:50:00", "-f", "flv", RTMP_URL
    ]
    proc = subprocess.Popen(publisher, stdin=subprocess.PIPE)
    audio_thread = threading.Thread(target=audio_producer, args=(audio_fifo,), daemon=True)
    audio_thread.start()
    try:
        while proc.poll() is None:
            with image_lock: image_path = current_image
            try:
                proc.stdin.write(leaderboard.render_overlay(image_path.read_bytes(), audio_level=audio_level))
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
                        decoder = subprocess.Popen(["ffmpeg","-hide_banner","-loglevel","error","-re","-i",str(SONGS[idx]),"-vn","-af",f"volume={volume/100:.3f}","-ac","2","-ar","44100","-f","s16le","pipe:1"],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
                    print(f"[MUSIC] {'Paused' if paused else SONGS[idx].name} | volume {volume}%", flush=True)
                if paused or decoder is None:
                    output.write(silence)
                    time.sleep(0.046)
                    continue
                chunk = decoder.stdout.read(4096)
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
