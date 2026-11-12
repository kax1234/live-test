"""One-shot WOS room preview for GitHub Actions; does not start a livestream."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

url = os.environ.get("WOS_ROOM_URL", "").strip()
if not url.startswith("https://wos.gg/"):
    raise SystemExit("WOS_ROOM_URL must be an HTTPS wos.gg room URL")

Path("artifacts").mkdir(exist_ok=True)
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    page.screenshot(path="artifacts/wos-preview.jpg", type="jpeg", quality=90)
    print(f"[WOS PREVIEW] Captured page: {page.url}")
    print(f"[WOS PREVIEW] Title: {page.title()}")
    browser.close()
