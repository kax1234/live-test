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


def listen_to_chat():
    global current_image

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

        print("YouTube chat connected. Commands: !blue !pink !rain !lofi", flush=True)
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
                    if message in COMMAND_IMAGES:
                        with image_lock:
                            current_image = COMMAND_IMAGES[message]
                        print(f"[CHAT] {author}: {message} -> {current_image.name}", flush=True)

                wait_seconds = max(1.0, result.get("pollingIntervalMillis", 5000) / 1000)
                stop_event.wait(wait_seconds)

            except HttpError as exc:
                print(f"YouTube chat API error: {exc}", flush=True)
                stop_event.wait(5)
    except Exception as exc:
        print(f"Chat listener could not start: {exc}", flush=True)


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
                frame = leaderboard.render_overlay(image_path.read_bytes())
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
