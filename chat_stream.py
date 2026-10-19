import array
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import leaderboard
import quiz_game
import vibe_map

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
TOKEN_JSON = os.environ.get("YT_CHAT_TOKEN_JSON", "").strip()
AUDIO_FILE = "/tmp/combined.mp3"

current_image = DEFAULT_IMAGE
image_lock = threading.Lock()
stop_event = threading.Event()
audio_level = 0.0
welcome_name = ''
welcome_until = 0.0
seen_viewers = set()


def listen_to_chat():
    global current_image, welcome_name, welcome_until

    if not TOKEN_JSON or not VIDEO_ID:
        print("Chat commands disabled: configure YT_CHAT_TOKEN_JSON and YT_VIDEO_ID.", flush=True)
        return

    try:
        token_data = json.loads(TOKEN_JSON)
        creds = Credentials.from_authorized_user_info(
            token_data, ["https://www.googleapis.com/auth/youtube.readonly"]
        )
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

        details = youtube.videos().list(
            part="liveStreamingDetails", id=VIDEO_ID
        ).execute()
        items = details.get("items", [])
        if not items:
            print("Chat listener: video ID not found or inaccessible.", flush=True)
            return

        chat_id = items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
        if not chat_id:
            print("Chat listener: no active live chat for YT_VIDEO_ID.", flush=True)
            return

        print("YouTube chat connected. Commands: !blue !pink !rain !lofi; quiz answers: !a !b !c", flush=True)
        page_token = None

        while not stop_event.is_set():
            try:
                result = youtube.liveChatMessages().list(
                    liveChatId=chat_id,
                    part="snippet,authorDetails",
                    pageToken=page_token,
                ).execute()
                page_token = result.get("nextPageToken", page_token)

                for item in result.get("items", []):
                    message = item.get("snippet", {}).get("displayMessage", "").strip().lower()
                    author = item.get("authorDetails", {}).get("displayName", "viewer")
                    leaderboard.award_message(author)
                    vibe_map.mark_chat(author)
                    if quiz_game.handle_message(author, message):
                        print(f"[QUIZ] {author} answered {message}", flush=True)
                    viewer_key = author.casefold().strip()
                    if viewer_key and viewer_key not in seen_viewers:
                        seen_viewers.add(viewer_key)
                        with image_lock:
                            welcome_name = author
                            welcome_until = time.monotonic() + 8.0
                        print(f"[WELCOME] First chat appearance: {author}", flush=True)
                    if message in COMMAND_IMAGES:
                        with image_lock:
                            current_image = COMMAND_IMAGES[message]
                        print(f"[CHAT] {author}: {message} -> {current_image.name}", flush=True)

                wait_seconds = max(1.0, result.get("pollingIntervalMillis", 5000) / 1000)
                stop_event.wait(wait_seconds)

            except HttpError as exc:
                print(f"YouTube chat API error: {exc}", flush=True)
                # Quota exhaustion will not recover by polling repeatedly.
                # Stop this listener for the rest of this run to avoid wasting quota.
                if "quotaExceeded" in str(exc) or "quota exceeded" in str(exc).lower():
                    print("Chat listener paused for this run because YouTube API quota is exhausted. Stream and visualizer continue.", flush=True)
                    return
                stop_event.wait(30)
    except Exception as exc:
        print(f"Chat listener could not start: {exc}", flush=True)


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
            raw = meter.stdout.read(1600)  # about 0.1 second of mono 8 kHz audio
            if not raw:
                break
            samples = array.array("h")
            samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
            if samples:
                rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
                # Normalize RMS to a stable 0..1 visual response.
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

    # One FFmpeg publisher stays connected; chat commands only change its video frames.
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
                # MJPEG accepts concatenated JPEG frames; repeated frames keep video alive.
                with image_lock:
                    shown_name, shown_until = welcome_name, welcome_until
                quiz_state = quiz_game.get_state()
                frame = leaderboard.render_overlay(image_path.read_bytes(), audio_level=audio_level, welcome_name=shown_name, welcome_until=shown_until, quiz_state=quiz_state)
                frame = vibe_map.render(frame)
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
