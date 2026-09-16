# tests/test_price_autofill.py
# ============================
# Meta-tests for the ledger's Price auto-fill: picking a symbol (from the
# suggestion dropdown OR the stock page's deep-link) fills the Price field
# with the live quote.
#
# Same string-lock approach as test_ticker_suggestions.py — the frontend
# JS has no pytest harness, so these tests READ the source and assert the
# wiring IS there. The backend half (/api/quote/<symbol>) gets REAL route
# tests in test_quote.py.
#
# WHAT THESE TESTS CANNOT PROVE: that the price visibly lands in the
# browser. That's the user's manual GUI gate.

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    """Read a file from the repo, failing loudly if missing."""
    path = ROOT / relpath
    assert path.exists(), f"{relpath} is missing — create it at the repo root"
    return path.read_text()


# ---------------------------------------------------------------------------
# app.py — the lightweight /api/quote/<symbol> route
# ---------------------------------------------------------------------------

def test_app_registers_quote_route():
    """app.py must register the lightweight quote route the prefill calls."""
    src = _read("app.py")
    assert '@app.route("/api/quote/<symbol>")' in src, (
        "app.py must register GET /api/quote/<symbol> for the price prefill"
    )


# ---------------------------------------------------------------------------
# ledger.js — the prefillPriceForTicker helper
# ---------------------------------------------------------------------------

def test_ledger_defines_prefill_helper():
    """ledger.js must define a shared prefillPriceForTicker helper — ONE
    implementation used by both the dropdown pick and the deep-link prefill,
    so neither path can drift."""
    src = _read("static/js/ledger.js")
    assert "function prefillPriceForTicker(" in src, (
        "ledger.js must define prefillPriceForTicker"
    )


def test_ledger_clears_price_before_filling():
    """The prefill must CLEAR the price field first — a stale price from a
    prior pick must never sit under a different ticker."""
    src = _read("static/js/ledger.js")
    assert 'txForm.elements.price.value = ""' in src, (
        "prefillPriceForTicker must clear the price field before fetching"
    )


def test_ledger_fills_price_two_decimals_with_accurate_backing():
    """The prefill must DISPLAY 2 decimals but keep the full accurate price
    for the calculations: `autofillPrice = quote.price` (the exact value
    that gets logged) + a `toFixed(2)` cosmetic fill of the field. Rounding
    the stored number down would silently change the transaction's facts."""
    src = _read("static/js/ledger.js")
    assert "autofillPrice = quote.price" in src, (
        "prefillPriceForTicker must keep the accurate quote price as autofillPrice"
    )
    assert "txForm.elements.price.value = quote.price.toFixed(2)" in src, (
        "the Price field must DISPLAY quote.price rounded to 2 decimals "
        "(quote.price.toFixed(2))"
    )


def test_ledger_tracks_manual_price_edits():
    """A user typing in the Price field must flip priceEdited — so the submit
    honors the TYPED value over the prefill's accurate number. Programmatic
    fills never fire `input`, so a fill leaves priceEdited false."""
    src = _read("static/js/ledger.js")
    assert "priceEdited = true" in src, (
        "ledger.js must mark the price as user-edited (priceEdited = true) "
        "when its input event fires"
    )


def test_ledger_submit_uses_accurate_unless_edited():
    """The submit must ship the accurate price when untouched, the typed one
    when edited: `priceEdited ? Number(fields.price) : (autofillPrice ?? ...)`
    — rounding is a display concern, never the stored fact."""
    src = _read("static/js/ledger.js")
    # Whitespace-agnostic: the ternary's condition and branches may span
    # lines, so allow any whitespace between the parts (regex escapes the
    # parentheses — they're metacharacters).
    assert re.search(
        r"priceEdited\s+\?\s*Number\(fields\.price\)\s*:"
        r"\s*\(autofillPrice \?\? Number\(fields\.price\)\)",
        src,
    ), (
        "the submit must use the typed price when the field was edited, and "
        "fall back to the accurate autofillPrice when it was untouched"
    )


def test_ledger_edit_mode_backs_stored_price_accurately():
    """Edit mode must DISPLAY the stored price rounded to 2 decimals while
    backing the submit with the exact stored tx.price (NO live quote — edit
    never fetches). A stale autofill from a prior log-mode pick must not
    leak into an edited row's save."""
    src = _read("static/js/ledger.js")
    assert "autofillPrice = tx.price" in src, (
        "enterEditMode must back the edited price with the exact stored "
        "tx.price (so a 2-decimal display never rounds it on save)"
    )
    assert "txForm.elements.price.value = tx.price.toFixed(2)" in src, (
        "enterEditMode must DISPLAY the stored price rounded to 2 decimals"
    )


def test_ledger_resets_autofill_on_form_reset():
    """exitEditMode (the form's general reset, used after every successful
    save) must clear autofillPrice — without it, a stale accurate number
    could resurface on the next log-long-form submit."""
    src = _read("static/js/ledger.js")
    assert "autofillPrice = null" in src, (
        "exitEditMode must reset autofillPrice to null"
    )


def test_ledger_fetches_the_quote_endpoint():
    """The prefill must call the lightweight /api/quote/<symbol> endpoint
    (never /api/stock/<symbol> — that one pays for the heavy name fetch)."""
    src = _read("static/js/ledger.js")
    assert "fetch(`/api/quote/" in src, (
        "prefillPriceForTicker must fetch /api/quote/<symbol>"
    )
    assert "encodeURIComponent(symbol)" in src, (
        "the symbol must be URL-encoded into the path (BRK.B, ^GSPC)"
    )


def test_ledger_wires_prefill_to_dropdown_pick():
    """The dropdown's onPick must call prefillPriceForTicker after filling
    the ticker field — the original feature's lock, extended."""
    src = _read("static/js/ledger.js")
    assert "txForm.elements.ticker.value = symbol" in src, (
        "onPick must fill the ticker input with the picked symbol"
    )
    assert re.search(
        r"txForm\.elements\.ticker\.value = symbol;\s*prefillPriceForTicker\(\)",
        src,
    ), (
        "the dropdown's onPick must call prefillPriceForTicker right after "
        "setting the ticker"
    )


def test_ledger_wires_prefill_to_deep_link():
    """The deep-link prefill (/ledger?ticker=AAPL, from the stock page's
    'Log Transaction' button) must also call prefillPriceForTicker — both
    ways a ticker lands in the field get the same latest-price help."""
    src = _read("static/js/ledger.js")
    # Both uses appear: the prefill helper must be CALLED somewhere besides
    # its own definition. Count occurrences — the definition + dropdown +
    # deep-link should total at least 3.
    assert src.count("prefillPriceForTicker(") >= 3, (
        "prefillPriceForTicker must be defined AND called from the deep-link "
        "prefill path"
    )
    # And the deep-link call must sit after the ticker is set there.
    assert re.search(
        r"txForm\.elements\.ticker\.value = prefillTicker\.trim\(\)"
        r"\.toUpperCase\(\);\s*prefillPriceForTicker\(\)",
        src,
    ), (
        "the deep-link prefill block must call prefillPriceForTicker after "
        "setting the ticker"
    )