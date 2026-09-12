# tests/test_ledger_col_count.py
# ==============================
# The ledger column count (11, incl. the actions column) lives in FOUR
# places that must stay in sync:
#   1. <th> row in templates/index.html (the source of truth)
#   2. setLedgerMessage's colSpan in static/js/main.js
#   3. buildGroupRow's cells object in static/js/main.js
#   4. buildTxRow's cells object in static/js/main.js
#
# If a developer adds or removes a column in the template but forgets
# one of the other three, cells silently misalign — the eye is the only
# test. These string-check tests (same pattern as test_price_diff.py and
# test_prev_close.py) read the source files and enforce the contract.

import re
from pathlib import Path

import pytest

# ── Paths ─────────────────────────────────────────────────────────────

JS_PATH = Path("static/js/main.js")
HTML_PATH = Path("templates/index.html")


# ── Helpers ───────────────────────────────────────────────────────────

def _read_js():
    return JS_PATH.read_text()


def _read_html():
    return HTML_PATH.read_text()


def _th_data_cols(html):
    """Extract every data-col value from the ledger <th> row."""
    return re.findall(r'<th\s[^>]*data-col="([^"]+)"', html)


def _colspan_in_set_ledger_message(js):
    """Extract the colSpan value from setLedgerMessage."""
    m = re.search(r'cell\.colSpan\s*=\s*(\d+)', js)
    return int(m.group(1)) if m else None


def _cell_keys_in_function(js, func_name):
    """Extract the key names from the cells = { ... } object inside a
    named function. Works for both buildGroupRow and buildTxRow."""
    # Find the function body
    pattern = rf'function\s+{func_name}\s*\('
    m = re.search(pattern, js)
    if not m:
        return None
    # Find the cells = { block within the function
    cells_start = js.find('cells = {', m.start())
    if cells_start == -1:
        return None
    # Find the matching closing brace
    depth = 0
    i = js.index('{', cells_start)
    for j in range(i, len(js)):
        if js[j] == '{':
            depth += 1
        elif js[j] == '}':
            depth -= 1
            if depth == 0:
                block = js[i:j+1]
                break
    # Extract keys from the block
    return sorted(re.findall(r'(\w+):\s', block))


# ── Tests ─────────────────────────────────────────────────────────────

def test_set_ledger_message_colspan_matches_th_count():
    """setLedgerMessage uses colSpan = 11 (hardcoded). This is the safety
    net for empty-state rows — a wrong colSpan stretches or compresses
    the "no transactions" message across the wrong number of columns."""
    js = _read_js()
    html = _read_html()
    colspan = _colspan_in_set_ledger_message(js)
    th_count = len(_th_data_cols(html))
    assert colspan == th_count == 11


def test_build_group_row_has_11_cell_keys():
    """buildGroupRow's cells object must have exactly 11 keys — one per
    <th> column. Fewer = missing cell; more = phantom column."""
    js = _read_js()
    keys = _cell_keys_in_function(js, 'buildGroupRow')
    assert keys is not None, "buildGroupRow not found in main.js"
    assert len(keys) == 11


def test_build_tx_row_has_11_cell_keys():
    """buildTxRow's cells object must have exactly 11 keys — same contract
    as buildGroupRow. The two builders MUST order cells identically."""
    js = _read_js()
    keys = _cell_keys_in_function(js, 'buildTxRow')
    assert keys is not None, "buildTxRow not found in main.js"
    assert len(keys) == 11


def test_cell_keys_match_th_data_cols():
    """The JS cell keys must match the HTML data-col values (order-
    insensitive). A mismatch means a cell is being appended to the wrong
    column — invisible without the eye unless this test catches it."""
    html = _read_html()
    js = _read_js()
    th_cols = sorted(_th_data_cols(html))
    group_keys = _cell_keys_in_function(js, 'buildGroupRow')
    tx_keys = _cell_keys_in_function(js, 'buildTxRow')
    assert group_keys == th_cols
    assert tx_keys == th_cols
