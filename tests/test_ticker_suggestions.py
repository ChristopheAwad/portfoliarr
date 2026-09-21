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


def test_common_locks_enter_interception_guard():
    """The Enter guard must not drift.

    The line deciding WHEN Enter intercepts (pick a suggestion — only
    while the field could actually hand over a .search-row, or always for
    the navbar's opt-in) versus when it falls through to the browser
    default (form submit) is the most regression-prone part of the
    factory. Pinning it means a refactor can't silently steal the
    ledger's Enter-to-submit or make the form submit mid-pick.
    """
    src = _read("static/js/common.js")
    assert (
        "if ((!dropdownOpen || !first) && !pickTypedTextOnEnter) return;"
        in src
    ), (
        "common.js must keep the Enter guard that falls through to the "
        "browser default unless a suggestion is actually pickable"
    )


# ---------------------------------------------------------------------------
# optional benchmark defaults — the comparison picker's helper surface (C/D/G)
# ---------------------------------------------------------------------------

def test_factory_reads_optional_default_results_options():
    """The factory must read optional defaultResults/defaultHeading options.

    The comparison picker shows S&P 500/Nasdaq/TSX in the dropdown whenever
    the empty field gains focus. The navbar and ledger call sites pass no
    defaults, so the options must default to none and leave those call sites
    behaviorally unchanged.
    """
    src = _read("static/js/common.js")
    assert "options.defaultResults" in src, (
        "setupTickerSuggestions must read optional defaultResults from options"
    )
    assert "options.defaultHeading" in src, (
        "setupTickerSuggestions must read optional defaultHeading from options"
    )
    assert "options.defaultResults || []" in src, (
        "defaultResults must default to an empty list when not supplied"
    )


def test_render_search_results_accepts_optional_heading():
    """renderSearchResults builds a quiet .search-section-label heading.

    The heading is optional, assigned through textContent (never innerHTML),
    rendered before the result rows, and the message/row paths stay intact.
    """
    src = _read("static/js/common.js")
    start = src.index("function renderSearchResults")
    end = src.index("function setupTickerSuggestions", start)
    body = src[start:end]
    assert "function renderSearchResults(resultsEl, results, message, heading)" in (
        body
    ), "renderSearchResults must accept an optional heading argument"
    assert '"search-section-label"' in body
    assert "if (heading)" in body
    assert "section.textContent = heading" in body
    assert "innerHTML" not in body, (
        "the heading must be set through textContent, never innerHTML"
    )
    assert "buildSearchRow(result)" in body
    assert "search-empty" in body


def test_factory_shows_defaults_only_for_empty_focused_input():
    """A local showDefaults() renders whenever the list is non-empty.

    The focus handler only calls it for an EMPTY field; a focus with text
    already in it must keep showing whatever the search produced.
    """
    src = _read("static/js/common.js")
    assert "function showDefaults()" in src
    assert "if (defaultResults.length === 0) return false;" in src
    assert 'inputEl.addEventListener("focus"' in src
    assert 'if (inputEl.value.trim() === "") showDefaults();' in src


def test_factory_empty_input_renders_defaults_instead_of_hiding():
    """Deleting all text while focused must open the defaults, not close.

    The input handler's empty-query branch renders defaults when available
    and only falls back to hiding when none exist.
    """
    src = _read("static/js/common.js")
    assert "if (!showDefaults()) hide();" in src


def test_factory_typed_query_still_schedules_search():
    """A typed non-empty query must still run the debounced /api/search."""
    src = _read("static/js/common.js")
    assert "searchTimer = setTimeout(() => runSearch(query), DEBOUNCE_MS);" in src


def test_factory_escape_and_outside_click_still_hide():
    """Escape and outside clicks must keep closing the dropdown."""
    src = _read("static/js/common.js")
    assert 'if (event.key === "Escape") {' in src
    assert 'scopeEl.contains(event.target)' in src
    assert "resultsEl.contains(event.target)" in src


def test_factory_click_and_enter_still_route_to_onpick():
    """Delegated .search-row clicks and Enter picks stay on onPick."""
    src = _read("static/js/common.js")
    assert 'event.target.closest(".search-row")' in src
    assert "onPick(row.dataset.symbol)" in src
    assert "onPick(symbol)" in src


def test_factory_keeps_no_match_and_failure_messages():
    """Zero-result and failed searches keep their honest status lines."""
    src = _read("static/js/common.js")
    assert '"No matches"' in src
    assert '"Search unavailable"' in src


def test_factory_keeps_stale_typed_response_guard():
    """A stale typed response must not overwrite the empty-input defaults.

    The existing query/value equality guard is what protects the suggested
    benchmark list after the user deletes text while a search is in flight.
    """
    src = _read("static/js/common.js")
    assert "if (inputEl.value.trim() !== query) return;" in src


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