# Coin-Stack Brand Mark (roadmap #25)

## Status and scope

Plan approved by the user 2026-09-25. Not yet implemented. The user picked
the "coin stack with growth arrow" mark (candidate D) from the demo page at
`assets/logo/candidates/index.html`. The mark uses the accent palette:
ink-navy `#1c3a5e` in light mode, banknote gold `#d0a959` in dark mode.

This replaces the current inconsistent web logo set (green sparkline navbar
mark plus a blue/green Google-Finance-style bar-chart favicon) with ONE mark
on the web surfaces: navbar, favicon, and master asset. Android launcher
icons are intentionally NOT changed (deferred to a later Android-only
change).

Decisions locked with the user:
- Backup the current logo into a dated copy folder BEFORE any replacement.
- Web only. Android launcher icons stay exactly as they are and are NOT
  exported or changed.
- Roadmap item #25 added and marked in progress.
- No new Python dependency; tests read PNG size with the standard library.
- The web mark takes its color from `--accent` (CSS token), so it flips
  navy/gold with the theme and frees green/red to mean market up/down only.

Note on the mark: the approved demo had the two coins overlapping, which at
icon size looked like one blob (a "mushroom"). The final mark adds a small
gap between the two coins. Same concept, clearer. This is the geometry
specified below; do NOT use `assets/logo/candidates/D.svg` verbatim.

## Hard contracts that must not break

- `class="logo"` must stay in `templates/base.html`. Locked by
  `tests/test_ledger_page.py:83` and `tests/test_stock.py:38-46`.
- The wordmark text must stay `Portfoli<span class="logo-accent">arr</span>`.
- The favicon must stay at `static/favicon.png` and be served as PNG. Locked
  by `tests/test_ui_revamp.py:42` and `:60`.
- The logo stays a link to `/` (`<a href="/" class="logo">`).
- Android icons stay at
  `android/app/src/main/res/mipmap-<density>/ic_launcher.png` with the same
  filenames and counts; `AndroidManifest.xml` references `@mipmap/ic_launcher`
  and must not change.
- No change to routes, DB, or JavaScript.

## Step 0 — Backup (ALREADY DONE by the lead agent)

The backup already exists at `assets/logo/backup-2026-09-25/` containing:
`favicon.png`, `portfoliarr-icon.png`, `navbar-mark.svg`, and
`mipmap-<density>/ic_launcher.png` for the five densities. Do not modify or
delete this folder.

## Step 1 — Tests first (write these, confirm RED, then implement)

Create `tests/test_brand_assets.py` with EXACTLY this content:

```python
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
```

Run `python -m pytest tests/test_brand_assets.py`. Record the red failures.
Expected red: `test_mark_svg_exists_and_uses_currentcolor` (file missing),
`test_icon_svg_exists` (file missing), `test_navbar_mark_uses_accent_token`
(still `--green-pos`), `test_base_logo_mark_is_coin_stack` (still `polyline`).
The size/guard tests (favicon, master, and the unchanged Android icons)
should already be green from the old assets; they become guards for the new
web exports. The Android parametrization is kept as a passive guard only —
Android icons are not changed by this feature.

## Step 2 — Create the two canonical SVGs

### A. `assets/logo/portfoliarr-mark.svg` (new file)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <path d="M12 5.6 V1.6 M9.7 3.8 L12 1.5 L14.3 3.8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  <ellipse cx="12" cy="10.4" rx="8.6" ry="3.1" fill="currentColor"/>
  <ellipse cx="12" cy="17.2" rx="8.6" ry="3.1" fill="currentColor"/>
</svg>
```

### B. `assets/logo/portfoliarr-icon.svg` (new file)

The launcher/favicon source: navy rounded tile, gold mark. The `scale(30)`
and `translate(152,185)` center the 24-unit mark on the 1024 tile (mark
center is at 12,10.9 in its own coordinates).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <rect width="1024" height="1024" rx="220" fill="#1c3a5e"/>
  <g transform="translate(152,185) scale(30)">
    <path d="M12 5.6 V1.6 M9.7 3.8 L12 1.5 L14.3 3.8" fill="none" stroke="#d0a959" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    <ellipse cx="12" cy="10.4" rx="8.6" ry="3.1" fill="#d0a959"/>
    <ellipse cx="12" cy="17.2" rx="8.6" ry="3.1" fill="#d0a959"/>
  </g>
</svg>
```

### C. `assets/logo/portfoliarr-lockup.svg` (new file, mark + wordmark)

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 96" width="340" height="96">
  <g transform="translate(8,18) scale(2.4)" color="#1c3a5e">
    <path d="M12 5.6 V1.6 M9.7 3.8 L12 1.5 L14.3 3.8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
    <ellipse cx="12" cy="10.4" rx="8.6" ry="3.1" fill="currentColor"/>
    <ellipse cx="12" cy="17.2" rx="8.6" ry="3.1" fill="currentColor"/>
  </g>
  <text x="72" y="63" font-family="Fraunces, Georgia, serif" font-size="46" font-weight="600" fill="#171a20">Portfoli<tspan fill="#1c3a5e">arr</tspan></text>
</svg>
```

## Step 3 — Rasterize the exports (ImageMagick + librsvg are installed)

Run these from the project root, in order:

```bash
magick -background none assets/logo/portfoliarr-icon.svg -resize 64x64 static/favicon.png
magick -background none assets/logo/portfoliarr-icon.svg -resize 1254x1254 assets/logo/portfoliarr-icon.png
```

Then confirm the output sizes:

```bash
magick identify static/favicon.png assets/logo/portfoliarr-icon.png
```

Expected: `64x64` and `1254x1254`. Android launcher icons are NOT exported.

## Step 4 — Wire the mark into the web app

### A. `templates/base.html` — replace the navbar mark

Find this exact block (currently around lines 107-112):

```html
                <svg class="logo-mark" viewBox="0 0 24 24" width="24" height="24"
                     fill="none" stroke="currentColor" stroke-width="2.5"
                     stroke-linecap="round" stroke-linejoin="round"
                     aria-hidden="true">
                    <polyline points="3 17 9 11 13 15 21 7"></polyline>
                </svg>
```

Replace it with:

```html
                <svg class="logo-mark" viewBox="0 0 24 24" width="24" height="24"
                     aria-hidden="true">
                    <path d="M12 5.6 V1.6 M9.7 3.8 L12 1.5 L14.3 3.8"
                          fill="none" stroke="currentColor" stroke-width="2.2"
                          stroke-linecap="round" stroke-linejoin="round"></path>
                    <ellipse cx="12" cy="10.4" rx="8.6" ry="3.1" fill="currentColor"></ellipse>
                    <ellipse cx="12" cy="17.2" rx="8.6" ry="3.1" fill="currentColor"></ellipse>
                </svg>
```

Update the comment above it (currently lines 96-105) so it describes a
coin stack with a growth arrow instead of a sparkline. Keep the sentence
that the SVG uses `stroke`/`fill="currentColor"` and takes its color from
CSS (`.logo-mark`), and keep that the logo doubles as "home".

### B. `static/style.css` — switch the mark to the accent token

Find (currently lines 205-206):

```css
.logo-mark { color: var(--green-pos); flex: 0 0 auto; }
.logo-accent { color: var(--green-pos); }
```

Replace with:

```css
.logo-mark { color: var(--accent); flex: 0 0 auto; }
.logo-accent { color: var(--accent); }
```

Update the comment block above (currently lines 203-206) to say the mark and
the accented tail use the ACCENT token, so they are ink-navy in light mode and
banknote gold in dark mode, which keeps green/red for market up/down only.

Do not change `.logo` sizing, the wordmark structure, or any other rule.

## Step 5 — Full verification

1. `python -m pytest tests/test_brand_assets.py` — green.
2. `python -m pytest` — full suite green (existing logo locks included).
3. Confirm no old colors remain in the changed blocks:
   `grep -n "green-pos" static/style.css` must not list `.logo-mark` or
   `.logo-accent`.
4. Browser GUI approval from the user (this is a gate; do not commit before
   it):
   - Dashboard and ledger navbar: mark is navy beside the wordmark; reload in
     dark mode: mark and wordmark tail are gold.
   - Browser tab: the favicon shows the navy tile with the gold coin stack.
   - `/stock/AAPL` navbar mark matches.
5. Android is out of scope: no `android/**` file is changed, so the Build
   Android APK workflow is not triggered.
6. Do NOT commit or push. Wait for explicit user approval.

## Expected files

Changed:
- `roadmap.md` (item #25, in progress — done by lead agent)
- `feature.md` (this file)
- `static/favicon.png`
- `assets/logo/portfoliarr-icon.png`
- `templates/base.html`
- `static/style.css`

New:
- `assets/logo/portfoliarr-mark.svg`
- `assets/logo/portfoliarr-icon.svg`
- `assets/logo/portfoliarr-lockup.svg`
- `assets/logo/backup-2026-09-25/` (backup, already created)
- `tests/test_brand_assets.py`
