# tests/test_brand_assets.py
# =========================
# Source/meta locks for the coin-stack brand mark (roadmap #25).
#
# pytest cannot see rendered CSS+SVG, so these tests lock the ASSET FILES on
# disk and the two source strings the browser draws from: the navbar mark in
# templates/base.html and the accent token in static/style.css. PNG sizes are
# read with the standard library only (PNG IHDR bytes 16..24 = width, height)
# so no new dependency is added.

import struct
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def png_size(path):
    """Return (width, height) from a PNG's IHDR chunk, stdlib only."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


def png_color_type(path):
    """Return the PNG IHDR color type byte (2 = RGB, 6 = RGBA)."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return data[25]


# ── Exports: favicon, master, Android ────────────────────────────────

def test_favicon_is_64_square():
    assert png_size(PROJECT_ROOT / "static" / "favicon.png") == (64, 64)


def test_master_icon_is_square():
    w, h = png_size(PROJECT_ROOT / "assets" / "logo" / "portfoliarr-icon.png")
    assert w == h, "master icon must be square"


@pytest.mark.parametrize(
    "density,size",
    [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)],
)
def test_android_launcher_icon(density, size):
    path = (
        PROJECT_ROOT
        / "android" / "app" / "src" / "main" / "res"
        / f"mipmap-{density}" / "ic_launcher.png"
    )
    assert png_size(path) == (size, size)
    # RGBA (type 6), not the old bar-chart RGB (type 2): the coin-stack
    # master has transparent rounded corners.
    assert png_color_type(path) == 6


# ── Source: canonical mark + web wire-up ─────────────────────────────

def test_mark_svg_exists_and_uses_currentcolor():
    path = PROJECT_ROOT / "assets" / "logo" / "portfoliarr-mark.svg"
    assert path.is_file(), "assets/logo/portfoliarr-mark.svg is missing"
    text = path.read_text()
    assert 'viewBox="0 0 24 24"' in text
    assert "currentColor" in text


def test_icon_svg_exists():
    path = PROJECT_ROOT / "assets" / "logo" / "portfoliarr-icon.svg"
    assert path.is_file(), "assets/logo/portfoliarr-icon.svg is missing"
    text = path.read_text()
    assert "#1c3a5e" in text  # navy tile
    assert "#d0a959" in text  # gold mark


def test_navbar_mark_uses_accent_token():
    css = (PROJECT_ROOT / "static" / "style.css").read_text()
    assert ".logo-mark { color: var(--accent);" in css
    assert ".logo-accent { color: var(--accent);" in css


def test_base_logo_mark_is_coin_stack():
    html = (PROJECT_ROOT / "templates" / "base.html").read_text()
    start = html.index('class="logo-mark"')
    region = html[start:html.index("</svg>", start)]
    assert "<ellipse" in region, "mark must contain the two coin ellipses"
    assert "polyline" not in region, "old sparkline polyline must be gone"
    assert 'class="logo-accent"' in html


# ── Android adaptive icon (API 26+) ──────────────────────────────────

ANDROID_RES = PROJECT_ROOT / "android" / "app" / "src" / "main" / "res"


def test_adaptive_icon_points_at_brand_layers():
    text = (ANDROID_RES / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text()
    assert "<adaptive-icon" in text
    assert "@color/ic_launcher_background" in text
    assert "@drawable/ic_launcher_foreground" in text


def test_adaptive_background_is_brand_navy():
    text = (ANDROID_RES / "values" / "ic_launcher_background.xml").read_text()
    assert "ic_launcher_background" in text
    assert "#1c3a5e" in text


def test_adaptive_foreground_is_gold_glyph():
    text = (ANDROID_RES / "drawable" / "ic_launcher_foreground.xml").read_text()
    assert 'android:viewportWidth="1024"' in text
    assert "#d0a959" in text
    assert text.count("a8.6,3.1") == 4, "both coin ellipses (two arcs each) must be in the vector"
    assert "M12 5.6" in text, "the growth arrow must be in the vector"


def test_manifest_keeps_ic_launcher_name():
    text = (PROJECT_ROOT / "android" / "app" / "src" / "main"
            / "AndroidManifest.xml").read_text()
    assert 'android:icon="@mipmap/ic_launcher"' in text
