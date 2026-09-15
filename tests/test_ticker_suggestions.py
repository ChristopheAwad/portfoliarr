# tests/test_ticker_suggestions.py
# ==================================
# Meta-tests for the shared ticker-suggestion (autocomplete) wiring.
#
# Same approach as test_web_refresh_wiring.py: the frontend JS has no
# pytest harness, so these tests READ the source text and assert the
# pieces ARE there (and, in the both-directions spots, that the OLD
# hand-wired code is NOT). The feature: the ledger's Ticker field shows
# the same /api/search suggestion dropdown as the navbar search box.
#
# WHAT THESE TESTS CANNOT PROVE: that the dropdown actually renders and
# picks correctly in a browser. That's the user's manual GUI gate.
#
# The shared factory lives in common.js (like setupAutoRefresh and
# setupTimeframeChart); the navbar and the ledger are both call sites.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    """Read a file from the repo, failing loudly if missing."""
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing — create it at the repo root"
    return path.read_text()


# ---------------------------------------------------------------------------
# common.js — the shared setupTickerSuggestions factory
# ---------------------------------------------------------------------------

def test_common_defines_setupTickerSuggestions():
    """common.js must export a setupTickerSuggestions factory.

    One shared implementation of the debounce -> /api/search -> dropdown
    flow, parameterized by the caller (navbar navigates, the ledger fills
    its ticker field). A hand-wired copy in each page script would drift.
    """
    src = _read("static/js/common.js")
    assert "function setupTickerSuggestions(" in src, (
        "common.js must define setupTickerSuggestions"
    )


def test_common_no_longer_wires_navbar_by_hand():
    """The navbar must go through the factory, not a hand-wired block.

    Both-directions lock (test_docker style): the factory call is present
    AND the old module-level searchInput listener wiring is gone — keeping
    both would be two sources of truth for the same dropdown.
    """
    src = _read("static/js/common.js")
    assert 'searchInput.addEventListener("input"' not in src, (
        "common.js must not wire the navbar dropdown by hand — use the "
        "setupTickerSuggestions factory"
    )
    assert 'searchInput.addEventListener("keydown"' not in src, (
        "common.js must not wire the navbar keydown handler by hand — the "
        "factory owns keyboard picking"
    )


def test_common_wires_navbar_through_factory():
    """The navbar is a setupTickerSuggestions call site.

    Its onPick navigates to the stock detail page (the suggestion symbol,
    URL-encoded like every other path segment in the app). The input and
    results ids are the base.html hooks, unchanged.
    """
    src = _read("static/js/common.js")
    # Whitespace-agnostic: the call spans lines, so allow any whitespace
    # between the factory name and the navbar's input hook.
    assert re.search(
        r'setupTickerSuggestions\(\s*'
        r'document\.getElementById\("ticker-search"\)',
        src,
    ), (
        "common.js must call setupTickerSuggestions with the navbar's "
        "ticker-search input"
    )
    assert '/stock/${encodeURIComponent(symbol)}' in src, (
        "the navbar's onPick must navigate to /stock/<symbol>"
    )


# ---------------------------------------------------------------------------
# ledger.js — the ledger's Ticker field is the second call site
# ---------------------------------------------------------------------------

def test_ledger_wires_ticker_suggestions():
    """ledger.js must wire the factory to the ticker field.

    onPick fills the ticker input with the picked symbol — the user then
    flows into Price → Qty → Log with a valid ticker, no typos.
    """
    src = _read("static/js/ledger.js")
    assert "setupTickerSuggestions(" in src, (
        "ledger.js must call the shared setupTickerSuggestions factory"
    )
    assert "txForm.elements.ticker" in src, (
        "ledger.js must wire suggestions to the ticker input "
        "(txForm.elements.ticker)"
    )
    assert "txForm.elements.ticker.value = symbol" in src, (
        "ledger.js's onPick must fill the ticker input with the picked symbol"
    )


# ---------------------------------------------------------------------------
# ledger.html + style.css — the markup the dropdown hangs off
# ---------------------------------------------------------------------------

def test_ledger_html_ships_suggestions_container():
    """ledger.html must ship the suggestion dropdown next to the ticker input.

    The input keeps name="ticker" (the form's data contract) while the new
    #tx-ticker-results div reuses the shared .search-results classes so it
    looks like the navbar's dropdown.
    """
    src = _read("templates/ledger.html")
    assert 'id="tx-ticker-results"' in src, (
        "ledger.html must declare the suggestion container #tx-ticker-results"
    )
    assert 'name="ticker"' in src, (
        "ledger.html's ticker input must keep name=\"ticker\" (FormData "
        "reads it)"
    )


def test_tx_form_css_positions_suggestion_wrapper():
    """style.css must make .tx-ticker-field the dropdown's anchor.

    .search-results is absolutely positioned, so its wrapper needs
    position: relative to hang the dropdown right under the field.
    """
    src = _read("static/style.css")
    assert ".tx-ticker-field" in src, (
        "style.css must define the .tx-ticker-field wrapper"
    )
    assert "position: relative" in src, (
        "style.css must position .tx-ticker-field so the dropdown anchors "
        "to it"
    )