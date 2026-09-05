# tests/test_ui_revamp.py
# =======================
# Server-rendered locks for the UI revamp ("Portfoliarr, polished").
#
# WHY ONLY THESE TESTS? The revamp is mostly CSS + browser JS, which no
# pytest can see (the responsive feature established that rule: pytest
# judges what the SERVER renders). What the server renders and what this
# file locks is:
#   1. The REBRAND: favicon linked + served, "Portfoliarr" in the titles,
#      and the old "Google Finance Clone" branding gone from rendered html.
#   2. The JS HOOKS: every id the page scripts query by must survive the
#      template restyle — a renamed id breaks a feature silently (the
#      script's querySelector returns null), which is exactly the class of
#      breakage a template restyle can cause. Locking them turns a silent
#      break into a red test.
#   3. The SKELETON contract: the shimmer is pure CSS keyed on `:empty`,
#      so the loading placeholders must ship with TRULY EMPTY content
#      (no "…" text, not even whitespace — whitespace makes :empty false
#      and the shimmer never appears).
#
# The richer contracts (ledger columns, chip links, scroll wrapper) keep
# their own locks in test_routes.py — those must stay green through the
# restyle, which is precisely how this feature proves it changed looks,
# not structure.

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def strip_comments(html):
    """Remove HTML comments before asserting on rendered content — the
    same hygiene ledger_header_tags uses. Template comments freely mention
    the old brand name in prose ("used to be the Google Finance clone"),
    and comments are not rendered content, so they must not count."""
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


# ── 1. Favicon ────────────────────────────────────────────────────────

def test_base_links_favicon_and_file_exists(client):
    """base.html (shared by both pages) must link the favicon, the file
    must exist on disk, and Flask's static route must serve it as PNG —
    a link to a 404 icon is the bug this triple-check catches. (PNG, not
    the earlier SVG: Firefox and Safari ignore SVG favicons entirely, so
    the tab showed nothing in those browsers.)"""
    html = client.get("/").get_data(as_text=True)
    assert 'rel="icon"' in html
    assert "favicon.png" in html

    favicon = Path(PROJECT_ROOT, "static", "favicon.png")
    assert favicon.is_file(), "static/favicon.png is missing"

    served = client.get("/static/favicon.png")
    assert served.status_code == 200
    assert served.content_type.startswith("image/png")


def test_stock_page_links_favicon_too(client):
    """The favicon link lives in base.html, so the detail page gets it for
    free — but 'for free' is an assumption until asserted: if a future
    edit copies the <head> into stock.html instead of extending base,
    the link could drift away on this page."""
    html = client.get("/stock/AAPL").get_data(as_text=True)
    assert "favicon.png" in html


# ── 2. Branding ───────────────────────────────────────────────────────

def test_dashboard_rebranded_to_portfoliarr(client):
    """The dashboard's tab title and rendered navbar carry the new brand,
    and the old 'Google Finance' branding is gone from RENDERED content
    (comments are prose, not UI — stripped)."""
    html = strip_comments(client.get("/").get_data(as_text=True))
    assert "Google" not in html
    assert "Portfoliarr" in html


def test_stock_page_rebranded_to_portfoliarr(client):
    """Same brand rule on the detail page, including its browser-tab
    title ('<symbol> — Portfoliarr')."""
    html = strip_comments(client.get("/stock/AAPL").get_data(as_text=True))
    assert "Google" not in html
    assert "Portfoliarr" in html


# ── 3. JS hooks survive the restyle ───────────────────────────────────

DASHBOARD_HOOK_IDS = [
    # base.html (navbar + search)
    "ticker-search", "search-results",
    # portfolio header card + chart
    "portfolio-value", "portfolio-day-change", "portfolio-total-return",
    "portfolioChart",
    # ledger card: form, toggle, import machinery, table body
    "tx-form", "usd-native-toggle", "ledger-body",
    "import-btn", "import-panel", "import-text", "import-report",
    # watchlist
    "add-ticker-btn",
]

STOCK_HOOK_IDS = [
    "stock-name", "stock-price", "stock-day-change",
    "add-to-watchlist-btn", "log-tx-btn", "stockChart",
    "stock-action-error",
    # a representative slice of the stats grid (full id list lives in
    # stock.js's STAT_IDS; the restyle must not rename ANY of these)
    "stat-open", "stat-market-cap", "stat-industry",
]


def test_dashboard_js_hooks_present(client):
    """Every id main.js queries must still render. One missing id = one
    silently dead feature (the script's querySelector returns null and
    the section never paints) — this test makes it loud instead."""
    html = client.get("/").get_data(as_text=True)
    missing = [i for i in DASHBOARD_HOOK_IDS if f'id="{i}"' not in html]
    assert missing == [], f"dashboard lost JS hook ids: {missing}"


def test_stock_js_hooks_present(client):
    """Same hook lock for the detail page's script (stock.js)."""
    html = client.get("/stock/AAPL").get_data(as_text=True)
    missing = [i for i in STOCK_HOOK_IDS if f'id="{i}"' not in html]
    assert missing == [], f"stock page lost JS hook ids: {missing}"


# ── 4. Skeleton loading contract ──────────────────────────────────────

def test_loading_placeholders_ship_empty(client):
    """The shimmer is CSS keyed on `:empty`, so these placeholders must
    ship with NOTHING between their tags — the old mockup '…' text would
    both masquerade as a loading state and keep :empty false forever.
    Regex group between the tag's > and </: must be exactly ""."""
    html = client.get("/").get_data(as_text=True)
    match = re.search(
        r'<span class="current-price" id="portfolio-value">([^<]*)</span>',
        html)
    assert match, "dashboard portfolio-value span not found"
    assert match.group(1) == "", "portfolio-value must ship empty (:empty shimmer)"

    stock_html = client.get("/stock/AAPL").get_data(as_text=True)
    price = re.search(r'<span class="current-price" id="stock-price">([^<]*)</span>',
                      stock_html)
    assert price, "stock-price span not found"
    assert price.group(1) == "", "stock-price must ship empty (:empty shimmer)"

    stat = re.search(r'<dd id="stat-open">([^<]*)</dd>', stock_html)
    assert stat, "stat-open dd not found"
    assert stat.group(1) == "", "stat dds must ship empty (:empty shimmer)"
