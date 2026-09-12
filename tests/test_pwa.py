# tests/test_pwa.py
# ===================
# Contract tests for PWA (Progressive Web App) install-to-homescreen.
#
# These tests verify that the manifest, icons, and meta tags are present
# and correct. They are string-check / file-existence tests — the same
# pattern as test_docker.py: read the artifact as text and assert on it.
# No browser or network needed.
#
# WHAT THESE TESTS LOCK:
# - manifest.json exists, is valid JSON, and has the right properties
# - Icon files exist at the required sizes
# - base.html links the manifest and has PWA meta tags
#
# WHY: If someone removes the manifest, a meta tag, or an icon, these
# tests fail — keeping the app installable.

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
TEMPLATES = ROOT / "templates"


def _read(filename: str) -> str:
    """Read a file from the repo root, failing loudly if missing."""
    path = ROOT / filename
    assert path.exists(), f"{filename} is missing — create it at the repo root"
    return path.read_text()


def _read_static(filename: str) -> str:
    """Read a file from static/, failing loudly if missing."""
    path = STATIC / filename
    assert path.exists(), f"static/{filename} is missing"
    return path.read_text()


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------


def test_manifest_exists():
    """manifest.json must exist in static/."""
    assert (STATIC / "manifest.json").exists(), (
        "static/manifest.json is missing — create the PWA manifest"
    )


def test_manifest_is_valid_json():
    """manifest.json must parse as valid JSON."""
    raw = _read_static("manifest.json")
    data = json.loads(raw)
    assert isinstance(data, dict), "manifest.json must be a JSON object"


def test_manifest_name():
    """The app name must be 'Portfoliarr'."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("name") == "Portfoliarr", (
        "manifest.json 'name' must be 'Portfoliarr'"
    )


def test_manifest_short_name():
    """short_name must be set (used on homescreen icons)."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("short_name"), "manifest.json must have a 'short_name'"


def test_manifest_display_standalone():
    """display must be 'standalone' — no browser chrome."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("display") == "standalone", (
        "manifest.json 'display' must be 'standalone'"
    )


def test_manifest_theme_color():
    """theme_color must match the dark theme background."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("theme_color") == "#0f1117", (
        "manifest.json 'theme_color' must be '#0f1117' (dark theme)"
    )


def test_manifest_background_color():
    """background_color must match the dark theme background."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("background_color") == "#0f1117", (
        "manifest.json 'background_color' must be '#0f1117' (dark theme)"
    )


def test_manifest_start_url():
    """start_url must be '/' — opens the dashboard."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("start_url") == "/", (
        "manifest.json 'start_url' must be '/'"
    )


def test_manifest_scope():
    """scope must be '/' — the PWA must control the whole app, not just
    the directory the manifest lives in (/static/). Without this, Chrome
    treats start_url as outside the SW scope and refuses to show the
    install prompt."""
    data = json.loads(_read_static("manifest.json"))
    assert data.get("scope") == "/", (
        "manifest.json 'scope' must be '/' — without it, Chrome defaults "
        "to '/static/' (the manifest's directory) and rejects installability"
    )


def test_manifest_icons():
    """manifest must declare icons at 192x192 and 512x512."""
    data = json.loads(_read_static("manifest.json"))
    icons = data.get("icons", [])
    assert len(icons) >= 2, "manifest.json must have at least 2 icons"

    sizes = [icon.get("sizes") for icon in icons]
    assert "192x192" in sizes, "manifest.json icons must include 192x192"
    assert "512x512" in sizes, "manifest.json icons must include 512x512"


def test_manifest_icons_have_types():
    """Each icon must have a 'type' field."""
    data = json.loads(_read_static("manifest.json"))
    for icon in data.get("icons", []):
        assert icon.get("type"), (
            f"Icon with sizes '{icon.get('sizes')}' missing 'type'"
        )


# ---------------------------------------------------------------------------
# Icon files
# ---------------------------------------------------------------------------


def test_icon_192_exists():
    """static/icon-192.png must exist."""
    assert (STATIC / "icon-192.png").exists(), (
        "static/icon-192.png is missing — resize from assets/logo/portfoliarr-icon.png"
    )


def test_icon_512_exists():
    """static/icon-512.png must exist."""
    assert (STATIC / "icon-512.png").exists(), (
        "static/icon-512.png is missing — resize from assets/logo/portfoliarr-icon.png"
    )


# ---------------------------------------------------------------------------
# base.html meta tags
# ---------------------------------------------------------------------------


def _base_html() -> str:
    """Read the base template as text."""
    return _read("templates/base.html")


def test_base_links_manifest():
    """base.html must link to the manifest."""
    html = _base_html()
    assert 'rel="manifest"' in html or "rel='manifest'" in html, (
        "base.html must have <link rel=\"manifest\">"
    )
    assert "manifest.json" in html, (
        "base.html manifest link must reference manifest.json"
    )


def test_base_theme_color_meta():
    """base.html must have a theme-color meta tag."""
    html = _base_html()
    assert "theme-color" in html, (
        "base.html must have <meta name=\"theme-color\">"
    )
    assert "#0f1117" in html, (
        "theme-color must be '#0f1117' (dark theme)"
    )


def test_base_apple_mobile_web_app_capable():
    """base.html must have apple-mobile-web-app-capable for iOS standalone."""
    html = _base_html()
    assert "apple-mobile-web-app-capable" in html, (
        "base.html must have <meta name=\"apple-mobile-web-app-capable\">"
    )


def test_base_apple_touch_icon():
    """base.html must link an apple-touch-icon for iOS homescreen."""
    html = _base_html()
    assert "apple-touch-icon" in html, (
        "base.html must have <link rel=\"apple-touch-icon\">"
    )
    assert "icon-192" in html, (
        "apple-touch-icon must reference the 192x192 icon"
    )


# ---------------------------------------------------------------------------
# Root manifest route (/manifest.json)
# ---------------------------------------------------------------------------


def test_manifest_route_exists(client):
    """The manifest must be reachable at /manifest.json — served from the
    site root with the proper MIME type, instead of only living at
    /static/manifest.json (application/json)."""
    response = client.get("/manifest.json")
    assert response.status_code == 200, "GET /manifest.json must return 200"


def test_manifest_route_content_type(client):
    """The route must serve the spec's MIME type, application/manifest+json.
    Chrome tolerates application/json, but the proper type is the standard
    and what Lighthouse/PWA checkers expect."""
    response = client.get("/manifest.json")
    assert response.headers["Content-Type"].startswith(
        "application/manifest+json"
    ), "manifest route must serve Content-Type application/manifest+json"


def test_manifest_route_serves_the_real_manifest(client):
    """The root route must serve the same manifest.json that lives in
    static/ — name, display, icons all intact."""
    response = client.get("/manifest.json")
    data = response.get_json()
    assert data["name"] == "Portfoliarr"
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"


def test_rendered_page_links_root_manifest(client):
    """base.html must point the manifest <link> at the root route, not the
    /static/ path. The static path still works (Chrome accepts it), but the
    root route is the canonical URL with the proper MIME type."""
    html = client.get("/").get_data(as_text=True)
    assert 'href="/manifest.json"' in html, (
        "rendered pages must link the manifest at /manifest.json"
    )
    assert "/static/manifest.json" not in html, (
        "the /static/manifest.json link is superseded by the root route"
    )


# ---------------------------------------------------------------------------
# Service Worker
# ---------------------------------------------------------------------------


def _sw_js() -> str:
    """Read the service worker as text."""
    path = STATIC / "sw.js"
    assert path.exists(), "static/sw.js is missing — create the service worker"
    return path.read_text()


def test_sw_exists():
    """static/sw.js must exist."""
    assert (STATIC / "sw.js").exists(), (
        "static/sw.js is missing — Chrome requires a SW for standalone mode"
    )


def test_sw_has_install_listener():
    """sw.js must listen for the 'install' event."""
    sw = _sw_js()
    assert "install" in sw, "sw.js must have an install event listener"


def test_sw_has_fetch_listener():
    """sw.js must listen for the 'fetch' event."""
    sw = _sw_js()
    assert "fetch" in sw, "sw.js must have a fetch event listener"


def test_sw_has_activate_listener():
    """sw.js must listen for the 'activate' event (old cache cleanup)."""
    sw = _sw_js()
    assert "activate" in sw, "sw.js must have an activate event listener"


def test_sw_precaches_shell():
    """sw.js must pre-cache the app shell assets on install."""
    sw = _sw_js()
    assert "addAll" in sw or "cache.put" in sw, (
        "sw.js must cache app shell assets (addAll or cache.put)"
    )


def test_base_registers_sw():
    """base.html must register the service worker at the root scope."""
    html = _base_html()
    assert "serviceWorker" in html, (
        "base.html must have service worker registration code"
    )
    assert "/sw.js" in html, (
        "base.html must register /sw.js (root scope, not /static/sw.js)"
    )


def test_base_sw_registration_reports_failures():
    """The registration call must handle rejection with .catch(). A bare
    register() rejects silently on insecure origins (plain HTTP over the
    LAN) — the exact failure mode that hid this feature's root cause for
    days. The catch makes the rejection visible in the phone's console
    instead of an unhandled promise error nobody notices."""
    html = _base_html()
    assert ".catch(" in html, (
        "service worker registration must .catch() and log its failure"
    )
