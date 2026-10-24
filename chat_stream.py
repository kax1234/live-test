import array
import os
import subprocess
import threading
import time
from pathlib import Path

import pytchat
import arcade_overlay as leaderboard

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = ROOT / "background.jpg"
COMMAND_IMAGES = {
    "!blue": ROOT / "blue.jpg",
    "!pink": ROOT / "pink.jpg",
    "!rain": ROOT / "rain.jpg",
    "!lofi": ROOT / "lofi.jpg",
}
RTMP_URL = "rtmp://a.rtmp.youtube.com/live2/" + os.environ["YT_STREAM_KEY"]
VIDEO_ID = os.environ.get("YT_VIDEO_ID", "").strip()
AUDIO_FILE = "/tmp/combined.mp3"

current_image = DEFAULT_IMAGE
image_lock = threading.Lock()
stop_event = threading.Event()
audio_level = 0.0


def listen_to_chat():
    """Read public live chat with pytchat; no YouTube Data API polling/OAuth token."""
    global current_image
    if not VIDEO_ID:
        print("Chat commands disabled: set repository/environment variable YT_VIDEO_ID to the live video's ID.", flush=True)
        return

    chat = None
    try:
        chat = pytchat.create(video_id=VIDEO_ID, interruptable=False)
        print(f"Chat reader starting for video {VIDEO_ID}. Waiting for live chat...", flush=True)
        while not stop_event.is_set() and chat.is_alive():
            batch = chat.get()
            for item in batch.sync_items():
                message = (getattr(item, "message", "") or "").strip().lower()
                author_obj = getattr(item, "author", None)
                author = getattr(author_obj, "name", "viewer") or "viewer"
                if not message:
                    continue
                # Every chat message is handled locally; game state makes no API calls.
                leaderboard.award_message(author, message)
                if message in COMMAND_IMAGES:
                    with image_lock:
                        current_image = COMMAND_IMAGES[message]
                    print(f"[CHAT] {author}: {message} -> {current_image.name}", flush=True)
                elif message in ("!join", "!play", "!leave") or message.startswith("!vote "):
                    print(f"[ARCADE] {author}: {message}", flush=True)
            time.sleep(0.5)
        if chat and not chat.is_alive():
            print("Chat reader stopped: the video may have ended, chat may be disabled, or the video ID may be wrong.", flush=True)
    except Exception as exc:
        print(f"Chat reader failed: {type(exc).__name__}: {exc}", flush=True)
        print("Check YT_VIDEO_ID and confirm the target video has an active public live chat.", flush=True)
    finally:
        if chat:
            try:
                chat.terminate()
            except Exception:
                pass


def measure_audio():
    """Read a low-cost PCM tap from the same music file; no YouTube API calls."""
    global audio_level
    meter = None
    try:
        meter_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-stream_loop", "-1", "-re", "-i", AUDIO_FILE,
            "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
        ]
        meter = subprocess.Popen(meter_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        while not stop_event.is_set():
            raw = meter.stdout.read(1600)
            if not raw:
                break
            samples = array.array("h")
            samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
            if samples:
                rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
                audio_level = min(1.0, rms / 9000.0)
    except Exception as exc:
        print(f"Audio visualizer meter unavailable: {exc}", flush=True)
    finally:
        if meter and meter.poll() is None:
            meter.terminate()


def main():
    if not DEFAULT_IMAGE.is_file():
        raise SystemExit("background.jpg is missing.")
    for command, image in COMMAND_IMAGES.items():
        if not image.is_file():
            raise SystemExit(f"Missing image for {command}: {image.name}")
    if not Path(AUDIO_FILE).is_file():
        raise SystemExit("Combined audio file is missing.")

    listener = threading.Thread(target=listen_to_chat, daemon=True)
    listener.start()
    meter_thread = threading.Thread(target=measure_audio, daemon=True)
    meter_thread.start()

    # Keep one FFmpeg publisher connected; chat commands only change rendered frames.
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "image2pipe", "-framerate", "1", "-vcodec", "mjpeg", "-i", "pipe:0",
        "-stream_loop", "-1", "-re", "-i", AUDIO_FILE,
        "-map", "0:v:0", "-map", "1:a:0",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,fps=30",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
        "-pix_fmt", "yuv420p", "-r", "30", "-g", "60", "-b:v", "1500k",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-t", "05:50:00", "-f", "flv", RTMP_URL,
    ]

    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        while proc.poll() is None:
            with image_lock:
                image_path = current_image
            try:
                frame = leaderboard.render_overlay(image_path.read_bytes(), audio_level=audio_level)
                proc.stdin.write(frame)
                proc.stdin.flush()
            except (BrokenPipeError, OSError):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
