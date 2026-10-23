# tests/test_brand_assets.py
# =========================
# Source/meta locks for the beveled coin-stack brand mark (roadmap #25,
# refined 2026-10-22).
#
# pytest cannot see rendered CSS+SVG, so these tests lock the ASSET FILES on
# disk and the two source strings the browser draws from: the navbar mark in
# templates/base.html and the accent token in static/style.css. PNG sizes and
# corner alpha are read with the standard library only (PNG IHDR + zlib) so
# no new dependency is added.

import re
import struct
import zlib
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


def png_rgba(path):
    """Decode an 8-bit, non-interlaced RGBA PNG, stdlib only."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    pos = 8
    width = height = None
    bit_depth = color_type = interlace = None
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if chunk_type == b"IHDR":
            (width, height, bit_depth, color_type,
             _compression, _filter, interlace) = struct.unpack(">IIBBBBB", chunk)
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break
        pos += 12 + length
    assert bit_depth == 8, f"{path}: expected 8-bit pixels"
    assert color_type == 6, f"{path}: expected RGBA"
    assert interlace == 0, f"{path}: expected non-interlaced"

    raw = zlib.decompress(idat)
    bpp = 4
    stride = width * bpp
    pixels = bytearray(height * stride)
    previous = bytearray(stride)
    offset = 0
    for row in range(height):
        filter_type = raw[offset]
        offset += 1
        line = bytearray(raw[offset:offset + stride])
        offset += stride
        for i in range(stride):
            left = line[i - bpp] if i >= bpp else 0
            up = previous[i]
            up_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                pa = abs(up - up_left)
                pb = abs(left - up_left)
                pc = abs(left + up - 2 * up_left)
                predictor = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else up_left)
                line[i] = (line[i] + predictor) & 0xFF
            elif filter_type != 0:
                raise AssertionError(f"{path}: unsupported filter {filter_type}")
        pixels[row * stride:(row + 1) * stride] = line
        previous = line
    return width, height, pixels


def png_corners_and_center(path):
    """One decode; return the four corner alphas and the center alpha."""
    width, height, pixels = png_rgba(path)

    def alpha(x, y):
        return pixels[(y * width + x) * 4 + 3]

    return (
        alpha(0, 0),
        alpha(width - 1, 0),
        alpha(0, height - 1),
        alpha(width - 1, height - 1),
        alpha(width // 2, height // 2),
    )


# ── Exports: favicon, master, Android ────────────────────────────────

def test_favicon_is_64_square_and_transparent():
    path = PROJECT_ROOT / "static" / "favicon.png"
    assert png_size(path) == (64, 64)
    assert png_color_type(path) == 6
    top_left, top_right, bottom_left, bottom_right, center = (
        png_corners_and_center(path))
    assert top_left == top_right == bottom_left == bottom_right == 0, (
        "favicon corners must be transparent")
    assert center == 255, "favicon tile must be opaque"


def test_master_icon_is_1254_rgba():
    path = PROJECT_ROOT / "assets" / "logo" / "portfoliarr-icon.png"
    assert png_size(path) == (1254, 1254)
    assert png_color_type(path) == 6
    top_left, top_right, bottom_left, bottom_right, center = (
        png_corners_and_center(path))
    assert top_left == top_right == bottom_left == bottom_right == 0
    assert center == 255


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
    assert png_color_type(path) == 6
    top_left, top_right, bottom_left, bottom_right, center = (
        png_corners_and_center(path))
    assert top_left == top_right == bottom_left == bottom_right == 0
    assert center == 255


# ── Source: canonical mark + web wire-up ─────────────────────────────

def test_mark_svg_has_bevel_and_rim():
    path = PROJECT_ROOT / "assets" / "logo" / "portfoliarr-mark.svg"
    text = path.read_text()
    assert 'viewBox="0 0 24 24"' in text
    assert "currentColor" in text
    assert text.count('opacity=".78"') == 2
    assert text.count('stroke-opacity=".55"') == 2
    assert text.count("<ellipse") == 4
    assert text.count("v1.5") == 2
    assert 'mask="url(#logoDollarMark)"' in text
    assert 'stroke-width="1.2"' in text
    assert 'stroke-width=".55"' in text
    assert "M12 9" in text
    assert "M12 5.6" not in text


def test_icon_svg_exists():
    path = PROJECT_ROOT / "assets" / "logo" / "portfoliarr-icon.svg"
    assert path.is_file(), "assets/logo/portfoliarr-icon.svg is missing"
    text = path.read_text()
    assert "#1c3a5e" in text
    assert "#d0a959" in text


def test_icon_svg_uses_beveled_mark():
    text = (PROJECT_ROOT / "assets" / "logo" / "portfoliarr-icon.svg").read_text()
    assert 'opacity=".78"' in text
    assert 'stroke-opacity=".55"' in text
    assert "translate(164,154) scale(29)" in text
    assert "M12 9" in text
    assert "M12 5.6" not in text
    assert text.count("<ellipse") == 4
    assert 'stroke="#7a5f27"' in text
    assert 'stroke="#f2d78f"' in text
    assert 'stroke="#1c3a5e"' not in text
    assert 'transform="translate(0,-0.34)"' in text
    assert 'stroke-width="1.35"' in text
    assert 'stroke-width=".45"' in text
    assert 'stroke-width=".75"' in text
    assert text.count("M12 10.2") == 3


def test_navbar_mark_uses_accent_token():
    css = (PROJECT_ROOT / "static" / "style.css").read_text()
    assert ".logo-mark { color: var(--accent);" in css
    assert ".logo-accent { color: var(--accent);" in css


def _assert_coin_mark(region, mask_id):
    assert "<ellipse" in region
    assert region.count("<ellipse") == 4
    assert region.count('opacity=".78"') == 2
    assert region.count('stroke-opacity=".55"') == 2
    assert region.count("v1.5") == 2
    assert f'id="{mask_id}"' in region
    assert f'mask="url(#{mask_id})"' in region
    assert 'stroke-width="1.2"' in region
    assert 'stroke-width=".55"' in region
    assert "M12 9" in region
    assert "M12 5.6" not in region
    assert "polyline" not in region


def test_base_logo_mark_is_coin_stack():
    html = (PROJECT_ROOT / "templates" / "base.html").read_text()
    start = html.index('class="logo-mark"')
    region = html[start:html.index("</svg>", start)]
    _assert_coin_mark(region, "logoDollarNav")
    assert 'class="logo-accent"' in html


def test_auth_logo_mark_is_coin_stack():
    html = (PROJECT_ROOT / "templates" / "_auth_head.html").read_text()
    start = html.index('class="logo-mark"')
    region = html[start:html.index("</svg>", start)]
    _assert_coin_mark(region, "logoDollarAuth")


def test_lockup_uses_beveled_mark():
    text = (PROJECT_ROOT / "assets" / "logo" / "portfoliarr-lockup.svg").read_text()
    assert "translate(6,9) scale(2.4)" in text
    assert text.count('opacity=".78"') == 2
    assert text.count('stroke-opacity=".55"') == 2
    assert text.count("<ellipse") == 4
    assert 'stroke-width="2.6"' in text
    assert 'stroke-width=".66"' in text
    assert 'stroke-width="1.2"' in text
    assert 'stroke-width=".55"' in text
    assert 'mask="url(#logoDollarLockup)"' in text
    assert "currentColor" in text
    assert "#d0a959" not in text
    assert 'font-size="46"' in text
    assert "Portfoli" in text and "arr" in text
    assert "M12 5.6" not in text


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
    assert 'android:width="108dp"' in text
    assert 'android:height="108dp"' in text
    assert 'android:viewportWidth="1024"' in text
    assert 'android:viewportHeight="1024"' in text
    assert "#d0a959" in text
    assert text.count("a7.8,3") == 6
    assert text.count("a6.1,1.9") == 4
    assert text.count('android:fillAlpha="0.78"') == 2
    assert text.count('android:strokeAlpha="0.55"') == 2
    assert 'android:strokeWidth="2.6"' in text
    assert 'android:strokeWidth="0.66"' in text
    assert 'android:strokeWidth="1.35"' in text
    assert 'android:strokeWidth="0.45"' in text
    assert 'android:strokeWidth="0.75"' in text
    assert 'android:strokeColor="#7a5f27"' in text
    assert 'android:strokeColor="#f2d78f"' in text
    assert 'android:translateY="-0.34"' in text
    assert "#1c3a5e" not in text
    assert re.search(r"M12[ ,]9", text)
    assert "M12 5.6" not in text
    assert "opacity=" not in text
    assert 'android:scaleX="0.95"' in text
    assert 'android:scaleY="0.95"' in text
    assert 'android:translateX="164"' in text
    assert 'android:translateY="154"' in text
    assert 'android:scaleX="29"' in text
    assert 'android:scaleY="29"' in text


def test_manifest_keeps_ic_launcher_name():
    text = (PROJECT_ROOT / "android" / "app" / "src" / "main"
            / "AndroidManifest.xml").read_text()
    assert 'android:icon="@mipmap/ic_launcher"' in text
