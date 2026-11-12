"""Capture the public WOS room as a live JPEG background for the FFmpeg stream."""
import os
import time
from pathlib import Path


def capture_loop(room_url, output_path, stop_event):
    """Keep one Chromium page open and atomically refresh its screenshot."""
    output = Path(output_path)
    temp = output.with_suffix(".tmp.jpg")
    retry_delay = 10

    while not stop_event.is_set():
        browser = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page(
                    viewport={"width": 1920, "height": 1080},
                    device_scale_factor=1,
                )
                page.goto(room_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(10000)
                print(f"[WOS] Room loaded: {page.url}", flush=True)

                while not stop_event.is_set():
                    image = page.screenshot(
                        type="jpeg",
                        quality=90,
                        full_page=False,
                        animations="disabled",
                    )
                    temp.write_bytes(image)
                    os.replace(temp, output)
                    stop_event.wait(1)

        except Exception as exc:
            print(
                f"[WOS] Browser capture failed: {type(exc).__name__}: {exc}. "
                f"Retrying in {retry_delay}s.",
                flush=True,
            )
            stop_event.wait(retry_delay)
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass
