#!/usr/bin/env python3
"""A picture of the interactive explorer, for the GitHub pages (GitHub shows an HTML file as source, not as a page).

    python scripts/screenshot_explorer.py      # writes docs/media/explorer_preview.{en,he}.png

Opens docs/tools/stop_design_explorer.{lang}.html (built by scripts/build_stop_design_explorer.py) at its starting
values in headless Chromium (playwright) and photographs the conditions and the verdict. Redraw it whenever the explorer
changes."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "docs" / "tools"
MEDIA = REPO / "docs" / "media"


def shoot(lang: str) -> Path:
    from playwright.sync_api import sync_playwright
    out = MEDIA / f"explorer_preview.{lang}.png"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1180, "height": 900}, device_scale_factor=1)
        page.goto((TOOLS / f"stop_design_explorer.{lang}.html").as_uri())
        page.wait_for_selector("#verdict-title")
        page.wait_for_timeout(800)
        top = page.locator("#controls-sec").bounding_box()
        bottom = page.locator("#verdict-box").bounding_box()
        y0, y1 = top["y"] - 16, bottom["y"] + bottom["height"] + 16
        page.screenshot(path=str(out), full_page=True, clip={"x": 0, "y": y0, "width": 1180, "height": y1 - y0})
        browser.close()
    return out


if __name__ == "__main__":
    for lang in ("en", "he"):
        print("written", shoot(lang).relative_to(REPO))
