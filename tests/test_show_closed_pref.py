# tests/test_show_closed_pref.py
# ==============================
# "Show closed positions" — a Preferences switch (Ledger card) that hides
# fully-sold tickers (net qty 0) from the transaction ledger's group list
# by default, so a traded-out position stops crowding the "what do I hold"
# view.
#
# WHY STRING CHECKS (no browser in the suite): every piece of this feature
# is wiring — a control that must exist on /preferences, a localStorage
# key that must round-trip, and a filter inside renderLedger that must
# read the key on EVERY render (not once at boot, or a poll cycle would
# silently resurrect hidden groups / keep hiding them after the flip).
# The same checks that pin the privacy eyes and column order pin this.
#
# THE CONTRACTS UNDER TEST HERE:
#   - the switch lives in the Ledger card of the preferences page
#   - preferences.js persists "showClosedPositions" as "true"/"false",
#     defaulting OFF when the key is absent (the privacy-eye convention)
#   - renderLedger reads the key INSIDE its function body — every poll
#     cycle re-applies the preference, so a flip in one tab reaches a
#     ledger open in another within 60s, no event wiring needed
#   - EXACT ZERO hides; a negative netQty (short) is an active position
#     and must stay visible
#   - when transactions exist but every group is hidden, the table says
#     "No open positions … Preferences" — never the misleading
#     "No transactions yet"
#   - the ledger NEVER deletes: hiding is presentation; the stored facts
#     are the cost basis the Closed sales replay depends on

import re
from pathlib import Path

PREFS_HTML = Path("templates/preferences.html")
PREFS_JS = Path("static/js/preferences.js")
LEDGER_JS = Path("static/js/ledger.js")


def _function_body(js, signature):
    """Extract a top-level function's text: from its signature line to the
    closing brace at column 0. (Same helper as test_privacy_toggles —
    main.js/ledger.js indent nested braces, so the first '\\n}' ends it.)"""
    start = js.find(signature)
    assert start != -1, f"{signature} not found"
    end = js.find("\n}", start)
    assert end != -1, f"{signature} has no closing brace"
    return js[start:end]


# ── The control exists, in the right place ────────────────────────────

def test_preferences_page_ships_the_switch():
    """preferences.html must carry the switch, inside the Ledger card.
    The Ledger card is the page's LAST card, so 'after the Ledger h3'
    pins the placement — a switch appended to some future card would
    fail this."""
    html = PREFS_HTML.read_text()
    assert 'id="pref-show-closed"' in html, \
        "preferences.html is missing the show-closed switch"
    assert html.find('id="pref-show-closed"') > html.find("<h3>Ledger</h3>"), \
        "the switch must live in the Ledger card (after its h3)"


def test_switch_wraps_a_real_checkbox():
    """The control must be a real <input type="checkbox"> wrapped in the
    .fx-toggle switch markup — keyboard/AT operable for free, and the
    same visual language as the ledger's currency switch."""
    html = PREFS_HTML.read_text()
    start = html.find('id="pref-show-closed"')
    chunk = html[max(0, start - 400):start + 200]
    assert 'type="checkbox"' in chunk, "switch must wrap a checkbox"
    assert "fx-toggle" in chunk and "fx-knob" in chunk, \
        "switch must reuse the .fx-toggle switch markup"


# ── The persistence round-trip ────────────────────────────────────────

def test_preferences_js_persists_show_closed():
    """preferences.js must sync the checkbox FROM localStorage and save
    TO it on change — the read and write sides of the same key, with
    '=== "true"' as the parse rule so an absent key means OFF (the
    privacy-eye convention: strings, never truthy parsing)."""
    js = PREFS_JS.read_text()
    assert 'localStorage.getItem("showClosedPositions")' in js, \
        "preferences.js must read showClosedPositions"
    assert re.search(
        r'localStorage\.setItem\(\s*"showClosedPositions"', js), \
        "preferences.js must save showClosedPositions"
    assert '=== "true"' in js, \
        "the stored value must be compared as the string 'true'"


# ── The ledger-side filter ────────────────────────────────────────────

def test_ledger_js_filters_closed_groups_per_render():
    """renderLedger must read the preference INSIDE its own body — every
    render (boot + each 60s poll) re-applies it, so the filter can never
    go stale against a fresh preference flip. The KEEP condition must be
    netQty !== 0: that pins the semantics both ways — exact zero drops
    out, and every non-zero group (including a NEGATIVE netQty, i.e. a
    short) stays. A '> 0' keep-condition would pass the eye but hide
    shorts — this string check fails it. netQty is the same fact-
    arithmetic sum (groupSortKeys) the group row's Qty cell shows, so
    the filter always matches what the row would display, unquoted
    tickers included. The read result must actually gate something (the
    showClosed flag feeding the filter), not just be computed."""
    js = LEDGER_JS.read_text()
    body = _function_body(js, "function renderLedger(")
    assert 'localStorage.getItem("showClosedPositions")' in body, \
        "renderLedger must read the preference per render, not at boot"
    assert "netQty !== 0" in body, \
        "the keep condition must be !== 0 (exact zero hides, shorts stay)"
    assert "showClosed" in body, \
        "the read result must gate the filter"


def test_ledger_js_honest_empty_state():
    """When transactions exist but every group is closed and hidden, the
    ledger must say so and point at Preferences — the old 'No
    transactions yet' would be a lie about WHY the table is empty (the
    stored facts are still there)."""
    js = LEDGER_JS.read_text()
    body = _function_body(js, "function renderLedger(")
    assert "No open positions" in body, \
        "the all-hidden empty state must say what's actually going on"
    assert "Preferences" in body, \
        "the empty state must point the user at the switch's home"
