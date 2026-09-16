# tests/test_closed_sales_collapse.py
# =====================================
# The Closed sales card collapses by default: on every page load the table
# ships hidden, while the card header — "Closed sales" + "Realized to
# date: X" — stays fully visible. Clicking anywhere on the header toggles
# the table, guided by a caret that rotates when expanded.
#
# WHY STRING CHECKS AGAIN: pytest can't run a browser, and the failures
# that plague this wiring are wiring failures — a header that lost its
# toggle hook, a wrapper id that got renamed, a JS listener that toggles
# the wrong attribute. These checks read the SHIPPED HTML (via the Flask
# test client, so Jinja has rendered it) and the JS/CSS source files,
# pinning the collapse contract:
#   - the collapsed-by-default state lives in HTML (`hidden` on the
#     wrapper), so no boot-time JS is needed to make "collapsed" true;
#   - the header carries role/tabindex/aria-expanded, so the toggle is
#     keyboard- and screen-reader-reachable like the sortable <th>s;
#   - the realized-total span sits in the HEADER, outside the hidden
#     wrapper — always visible even when the table is collapsed;
#   - ledger.js owns the toggle wiring; style.css owns the caret rotation.

import re
from pathlib import Path

LEDGER_JS = Path("static/js/ledger.js")
STYLE_CSS = Path("static/style.css")


def rendered(client, url):
    res = client.get(url)
    assert res.status_code == 200
    return res.get_data(as_text=True)


# ── Collapsed by default (HTML is the source of truth) ──────────────────

def test_ledger_ships_closed_sales_collapsed_by_default(client):
    """/ledger must ship the Closed sales table's wrapper HIDDEN — the
    collapsed-by-default promise lives in HTML, so it can't be lost to a
    missing JS boot call. The wrapper is identified by id so ledger.js has
    a stable handle to flip."""
    html = rendered(client, "/ledger")
    wrap = re.search(r'<div[^>]*id="closed-sales-wrap"[^>]*>', html)
    assert wrap is not None, "closed-sales-wrap element is missing"
    assert "hidden" in wrap.group(0), \
        "closed-sales table must ship collapsed by default (hidden attr)"


def test_ledger_ships_closed_sales_toggle_header(client):
    """The card header is the toggle control: a real button-ish element
    (role/tabindex), its initial aria-expanded speaking the truth
    (collapsed → "false"). These are the keyboard + screen-reader
    reachability hooks — without them the collapse would be mouse-only."""
    html = rendered(client, "/ledger")
    header = re.search(r'<div[^>]*id="closed-sales-toggle"[^>]*>', html)
    assert header is not None, "closed-sales-toggle header is missing"
    for attr in ('role="button"', 'tabindex="0"', 'aria-expanded="false"'):
        assert attr in header.group(0), f"toggle header lacks {attr}"


# ── Realized to date stays visible ──────────────────────────────────────

def test_realized_total_always_visible(client):
    """The 'Realized to date' figure lives in the card HEADER, which never
    collapses — it must render BEFORE the hidden wrapper in the HTML, so
    collapsing the table can never take the total off screen."""
    html = rendered(client, "/ledger")
    assert 'id="realized-total"' in html, "realized-total span is missing"
    assert html.index('id="realized-total"') < html.index(
        'id="closed-sales-wrap"'), \
        "realized-total must sit in header, outside the collapsible wrapper"


# ── ledger.js owns the toggle wiring ────────────────────────────────────

def test_ledger_js_wires_closed_sales_toggle():
    """ledger.js must query both hooks, flip the wrapper's hidden on click,
    keep aria-expanded in sync, and offer Enter/Space keyboard parity —
    the same interaction surface the sortable <th>s get."""
    js = LEDGER_JS.read_text()
    assert '#closed-sales-toggle"' in js or "closed-sales-toggle" in js
    assert '"#closed-sales-wrap"' in js or "closed-sales-wrap" in js
    assert "ClosedSalesWrap.hidden" in js or "closedSalesWrap.hidden" in js
    assert "aria-expanded" in js
    assert "Enter" in js and '" "' in js


# ── style.css owns the caret + pointer ──────────────────────────────────

def test_closed_sales_toggle_css():
    """The header must read as a control (pointer cursor) and its caret
    must rotate when expanded — the same visual language as the ledger's
    group rows (.ledger-group .caret / .open)."""
    css = STYLE_CSS.read_text()
    assert re.search(
        r"\.closed-sales-toggle\s*\{[^}]*cursor:\s*pointer", css, re.S), \
        "toggle header must show a pointer cursor"
    assert re.search(
        r"\.closed-sales-toggle\.open \.caret[^{]*\{[^}]*rotate\(90deg\)",
        css, re.S), "open state caret must rotate 90deg"