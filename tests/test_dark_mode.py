# tests/test_dark_mode.py
# =======================
# Server-rendered locks for the dark mode feature.
#
# WHY ONLY THESE TESTS? Dark mode is mostly CSS + browser JS, which no
# pytest can see. What the server renders and what this file locks is:
#   1. The TOGGLE BUTTON: exists in the navbar on both pages, with the
#      correct id so common.js can wire the click handler.
#   2. The FOUC-PREVENTION SCRIPT: an inline <script> in <head> that reads
#      localStorage / OS preference and sets class="dark" on <html> BEFORE
#      first paint — without it, the page flashes light then snaps dark.
#   3. The CSS CONTRACT: style.css contains a .dark selector that redefines
#      the core palette tokens, proving the dark palette exists.
#   4. HARDCODED COLOR CLEANUP: key selectors use CSS custom properties
#      instead of hardcoded hex values, so they respond to .dark.

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── 1. Toggle button renders ─────────────────────────────────────────

def test_dark_toggle_renders_on_dashboard(client):
    """The navbar must contain a theme-toggle button with id="theme-toggle"
    so common.js can attach the click handler."""
    html = client.get("/").get_data(as_text=True)
    assert 'id="theme-toggle"' in html, "theme-toggle button missing from dashboard"


def test_dark_toggle_renders_on_stock_page(client):
    """Same toggle on the detail page (it lives in base.html, shared by
    both — but 'for free' is an assumption until asserted)."""
    html = client.get("/stock/AAPL").get_data(as_text=True)
    assert 'id="theme-toggle"' in html, "theme-toggle button missing from stock page"


def test_toggle_is_button_element(client):
    """The toggle must be a <button> (not a <div> or <a>) for keyboard
    accessibility — buttons are focusable and fire Enter/Space natively."""
    html = client.get("/").get_data(as_text=True)
    match = re.search(r'<button[^>]*id="theme-toggle"[^>]*>', html)
    assert match, "theme-toggle is not a <button> element"


# ── 2. FOUC-prevention script ────────────────────────────────────────

def test_fouc_script_in_head(client):
    """An inline <script> in <head> must read localStorage('theme') (or
    OS preference) and set class='dark' on <html> before first paint.
    Without this, the page flashes light then snaps dark — the FOUC
    (Flash Of Unstyled Content) problem."""
    html = client.get("/").get_data(as_text=True)
    # The script must appear BEFORE </head> — inside the <head> block.
    head_match = re.search(r'<head>(.*?)</head>', html, re.S)
    assert head_match, "couldn't find <head> in rendered HTML"
    head_content = head_match.group(1)
    assert "theme" in head_content.lower(), \
        "no FOUC-prevention theme script found in <head>"
    # Must reference localStorage
    assert "localStorage" in head_content, \
        "FOUC script doesn't reference localStorage"


# ── 3. CSS contract: .dark exists ─────────────────────────────────────

def test_css_contains_dark_selector():
    """style.css must contain a `.dark` selector that redefines the core
    palette tokens — the mechanism that makes dark mode work."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    assert ".dark" in css, "style.css has no .dark selector"


def test_css_dark_redefines_bg_color():
    """The .dark block must redefine --bg-color to a dark value, proving
    the dark palette actually overrides the light defaults."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    # Find the .dark block and check it contains --bg-color
    dark_match = re.search(r'\.dark\s*\{([^}]+)\}', css)
    assert dark_match, "no .dark { ... } block found in style.css"
    dark_body = dark_match.group(1)
    assert "--bg-color" in dark_body, \
        ".dark block doesn't redefine --bg-color"


def test_css_dark_redefines_card_bg():
    """The .dark block must redefine --card-bg to a dark value."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    dark_match = re.search(r'\.dark\s*\{([^}]+)\}', css)
    assert dark_match, "no .dark { ... } block found in style.css"
    dark_body = dark_match.group(1)
    assert "--card-bg" in dark_body, \
        ".dark block doesn't redefine --card-bg"


# ── 4. Hardcoded color cleanup ───────────────────────────────────────

def test_navbar_uses_token_not_hardcoded_white():
    """The .navbar background must use a CSS custom property, not a
    hardcoded rgba(255, 255, 255, ...) — otherwise dark mode can't
    override it."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    # Find the .navbar rule
    navbar_match = re.search(r'\.navbar\s*\{([^}]+)\}', css)
    assert navbar_match, "no .navbar rule found"
    navbar_body = navbar_match.group(1)
    assert "255, 255, 255" not in navbar_body, \
        ".navbar still has hardcoded white background"


def test_btn_text_uses_token_not_hardcoded_white():
    """Primary/danger button text color must use a CSS variable, not
    hardcoded #fff — dark mode needs these buttons legible on dark."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    # Check .btn-action, .btn-primary, .btn-danger, .tx-form button,
    # .import-actions button — they all had hardcoded color: #fff
    selectors_to_check = [
        r'\.btn-action\s*\{([^}]+)\}',
        r'\.btn-primary\s*\{([^}]+)\}',
        r'\.btn-danger\s*\{([^}]+)\}',
        r'\.tx-form\s+button\s*\{([^}]+)\}',
        r'\.import-actions\s+button\s*\{([^}]+)\}',
    ]
    for pattern in selectors_to_check:
        match = re.search(pattern, css)
        if match:
            body = match.group(1)
            # Should NOT contain color: #fff (might use var(--btn-text) instead)
            assert "#fff" not in body.lower(), \
                f"selector matching {pattern} still has hardcoded #fff color"


def test_modal_overlay_uses_token():
    """The .modal-overlay background must use a CSS variable, not a
    hardcoded rgba — dark mode needs a darker overlay."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    overlay_match = re.search(r'\.modal-overlay\s*\{([^}]+)\}', css)
    assert overlay_match, "no .modal-overlay rule found"
    overlay_body = overlay_match.group(1)
    assert "16, 24, 40" not in overlay_body, \
        ".modal-overlay still has hardcoded rgba overlay"


def test_shimmer_uses_tokens():
    """The skeleton shimmer gradient must use CSS variables, not hardcoded
    #eef1f5 / #f8fafc — dark mode needs different shimmer colors."""
    css_path = PROJECT_ROOT / "static" / "style.css"
    css = css_path.read_text()
    # Find the shimmer animation context — look for the gradient near
    # the @keyframes shimmer or the :empty::before rules
    shimmer_section = css[css.find("@keyframes shimmer"):]
    # Only check the first 500 chars (the keyframe + the ::before rules)
    shimmer_section = shimmer_section[:800]
    assert "#eef1f5" not in shimmer_section, \
        "shimmer gradient still has hardcoded #eef1f5"
    assert "#f8fafc" not in shimmer_section, \
        "shimmer gradient still has hardcoded #f8fafc"
