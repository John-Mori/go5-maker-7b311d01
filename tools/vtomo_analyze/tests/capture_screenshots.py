import json
from pathlib import Path

from playwright.sync_api import sync_playwright


TOOL_DIR = Path(__file__).resolve().parents[1]
VERIFY_DIR = TOOL_DIR / "_verify"


def main() -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto((TOOL_DIR / "index.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_selector(".video-card")
        page.wait_for_function(
            """() => [...document.images].filter(img => {
                const box = img.getBoundingClientRect();
                return box.bottom > 0 && box.top < innerHeight + 100;
            }).every(img => img.complete && img.naturalWidth > 0)""",
            timeout=15_000,
        )
        counts = page.evaluate("window.__VTOMO_STATE__ && window.__VTOMO_STATE__.counts")
        page.screenshot(path=str(VERIFY_DIR / "own-tab.png"))
        page.click("#tab-subs")
        page.wait_for_selector("#panel-subs .video-card")
        page.wait_for_function(
            """() => [...document.images].filter(img => {
                const box = img.getBoundingClientRect();
                return box.bottom > 0 && box.top < innerHeight + 100;
            }).every(img => img.complete && img.naturalWidth > 0)""",
            timeout=15_000,
        )
        page.screenshot(path=str(VERIFY_DIR / "subscriptions-tab.png"))
        page.click('[data-sort="views"]')
        assert page.locator('[data-sort="views"]').get_attribute("aria-pressed") == "true"
        channel_id = page.evaluate("window.VTOMO_DATA.subscriptions.videos[0].channel_id")
        page.select_option("#channelFilter", channel_id)
        filtered_count = page.locator("#panel-subs .video-card").count()
        if filtered_count < 1:
            raise RuntimeError("channel filter rendered no cards for a channel with videos")
        browser.close()
    if not counts or errors:
        raise RuntimeError(f"render failed counts={counts!r} errors={errors!r}")
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
