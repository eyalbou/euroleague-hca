"""Phase G.1 -- capture full-page and cropped screenshots of the dashboards
for use as static frames in the Remotion walkthrough video.

Requirements: `pip install playwright && playwright install chromium`.

Outputs to `video/public/frames/`:
  intro.png, index.png, index_kpis.png
  dashboard_overview.png, dashboard_attendance.png, dashboard_covid.png,
    dashboard_models.png, dashboard_verdict.png, dashboard_mechanisms.png
  transitions_bars.png, transitions_hca.png, transitions_bigrams.png
  referees.png, referees_funnel.png
  report.png

All shots are 1920x1080 for a 16:9 (1080p) output, DPR=2 for Retina.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("21_capture_frames")

ROOT = Path(__file__).resolve().parents[1]
DASHBOARDS = ROOT / "dashboards"
OUT = ROOT / "video" / "public" / "frames"
OUT.mkdir(parents=True, exist_ok=True)

WIDTH = 1920
HEIGHT = 1080


async def _viewport_shot(page, url: str, dest: Path, *, wait: int = 1200,
                         scroll: int = 0, before_js: str | None = None) -> None:
    """Navigate, optionally scroll/evaluate, then take a viewport (not full-page)
    screenshot sized WIDTH x HEIGHT -- that's what the video frame needs."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle", timeout=10_000)
    await page.wait_for_timeout(wait)
    if before_js:
        await page.evaluate(before_js)
        await page.wait_for_timeout(700)
    if scroll:
        await page.evaluate(f"window.scrollTo({{top: {scroll}, behavior: 'instant'}})")
        await page.wait_for_timeout(500)
    await page.screenshot(path=str(dest), full_page=False,
                          clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT})
    log.info("captured %s (%.0f KB)", dest.name, dest.stat().st_size / 1024)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=2,
        )
        page = await ctx.new_page()

        # index.html -- hero + KPIs
        idx = "file://" + str(DASHBOARDS / "index.html")
        await _viewport_shot(page, idx, OUT / "index.png")

        # analyst dashboard -- visit each tab programmatically
        db = "file://" + str(DASHBOARDS / "dashboard.html")
        tabs = [
            ("tab-overview", "dashboard_overview.png"),
            ("tab-attendance", "dashboard_attendance.png"),
            ("tab-covid", "dashboard_covid.png"),
            ("tab-models", "dashboard_models.png"),
            ("tab-verdict", "dashboard_verdict.png"),
            ("tab-mechanisms", "dashboard_mechanisms.png"),
        ]
        for target, fn in tabs:
            js = (
                f"document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));"
                f"document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));"
                f"document.querySelector('[data-target=\"{target}\"]')?.classList.add('active');"
                f"document.getElementById('{target}')?.classList.add('active');"
                f"document.getElementById('{target}')?.scrollIntoView({{block:'start'}});"
            )
            await _viewport_shot(page, db, OUT / fn, before_js=js, wait=1500)

        # transitions.html -- three views
        tr = "file://" + str(DASHBOARDS / "transitions.html")
        await _viewport_shot(page, tr, OUT / "transitions_bars.png", wait=2000)
        js_hca = (
            "document.querySelectorAll('[data-view]').forEach(b=>b.classList.remove('active'));"
            "document.querySelector('[data-view=\"hca\"]')?.click();"
        )
        await _viewport_shot(page, tr, OUT / "transitions_hca.png",
                             before_js=js_hca, wait=2200)
        js_bg = (
            "document.querySelectorAll('[data-view]').forEach(b=>b.classList.remove('active'));"
            "document.querySelector('[data-view=\"bigrams\"]')?.click();"
        )
        await _viewport_shot(page, tr, OUT / "transitions_bigrams.png",
                             before_js=js_bg, wait=2200)

        # referees.html -- hero + funnel
        rf = "file://" + str(DASHBOARDS / "referees.html")
        await _viewport_shot(page, rf, OUT / "referees.png", wait=1500)
        # zoomed funnel shot -- scroll to funnel section
        await _viewport_shot(page, rf, OUT / "referees_funnel.png",
                             scroll=780, wait=1800)

        # final report -- first viewport
        rp = "file://" + str(DASHBOARDS / "final_report.html")
        await _viewport_shot(page, rp, OUT / "report.png", wait=800)

        await browser.close()

    log.info("done -- %d frames in %s", len(list(OUT.glob("*.png"))), OUT)


if __name__ == "__main__":
    asyncio.run(main())
