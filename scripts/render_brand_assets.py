"""Rasterize the Portfoliarr icon SVG into the favicon, master, and Android mipmaps.

Playwright lives in the system Python, not the project venv:

    /usr/bin/python3 scripts/render_brand_assets.py

Every output is rendered at its exact pixel size with a transparent page
background, so the rounded tile's corners stay transparent (RGBA).
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "logo" / "portfoliarr-icon.svg"
ANDROID_RES = ROOT / "android" / "app" / "src" / "main" / "res"

TARGETS = [
    (ROOT / "assets" / "logo" / "portfoliarr-icon.png", 1254),
    (ROOT / "static" / "favicon.png", 64),
    (ANDROID_RES / "mipmap-mdpi" / "ic_launcher.png", 48),
    (ANDROID_RES / "mipmap-hdpi" / "ic_launcher.png", 72),
    (ANDROID_RES / "mipmap-xhdpi" / "ic_launcher.png", 96),
    (ANDROID_RES / "mipmap-xxhdpi" / "ic_launcher.png", 144),
    (ANDROID_RES / "mipmap-xxxhdpi" / "ic_launcher.png", 192),
]


def main():
    svg = ICON.read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(device_scale_factor=1)
        for path, size in TARGETS:
            path.parent.mkdir(parents=True, exist_ok=True)
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(
                "<!doctype html><html><head><style>"
                "html,body{margin:0;padding:0;background:transparent;}"
                f"svg{{display:block;width:{size}px;height:{size}px;}}"
                "</style></head><body>" + svg + "</body></html>"
            )
            page.screenshot(path=str(path), omit_background=True)
            print(f"{path.relative_to(ROOT)}  {size}x{size}")
        browser.close()


if __name__ == "__main__":
    main()
