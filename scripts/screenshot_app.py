#!/usr/bin/env python3
"""Pictures of the Streamlit app for the overview (GitHub cannot run it).

    python scripts/screenshot_app.py     # writes docs/media/app_run.png and docs/media/app_trajectories.png

Starts `streamlit run streamlit_app.py` headless on a free port, ticks "Fixed random seed" (seed 0, the default
settings: scenario B, 0.40 cars/s, a 15 s stop), clicks Run Simulation and photographs the result and the
trajectory chart in headless Chromium (playwright). Emoji need an emoji font on the machine."""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEDIA = REPO / "docs" / "media"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    from playwright.sync_api import sync_playwright
    port = _free_port()
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "streamlit_app.py", "--server.headless", "true",
                            "--server.port", str(port), "--browser.gatherUsageStats", "false"], cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1400, "height": 950})
            page.goto(url)
            page.wait_for_selector("text=Run Simulation", timeout=60000)
            page.wait_for_timeout(1500)
            page.get_by_text("Fixed random seed").click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="Run Simulation").click()
            page.wait_for_timeout(2000)
            page.wait_for_function("!document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=300000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(MEDIA / "app_run.png"))
            page.get_by_text("Traffic Visualization").scroll_into_view_if_needed()
            page.wait_for_timeout(1500)
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(MEDIA / "app_trajectories.png"))
            browser.close()
    finally:
        app.terminate()
        app.wait(timeout=30)
    for name in ("app_run.png", "app_trajectories.png"):
        print("written", (MEDIA / name).relative_to(REPO))


if __name__ == "__main__":
    main()
