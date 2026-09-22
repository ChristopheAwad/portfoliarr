# tests/test_ledger_average_price.py
# ====================================
# Frontend meta-tests for the ledger ticker parent row's Price cell:
# it must show the backend's group_avg_cost — the current open position's
# average acquisition price — instead of the old hard-coded "—".
#
# WHY STRING CHECKS: pytest cannot run the browser, so these tests READ
# the shipped static/js/ledger.js and pin the wiring contracts the same
# way the other ledger meta-tests do. The backend half (the
# group_avg_cost cost-pool replay) is covered by tests/test_ledger_groups.py.
#
# WHAT THESE TESTS CANNOT PROVE: that the number is visibly correct in a
# browser. That remains the user's manual GUI gate.

import re
from pathlib import Path

import pytest

LEDGER_JS = Path("static/js/ledger.js")


@pytest.fixture(scope="module")
def js():
    return LEDGER_JS.read_text()


def function_block(js, name):
    """Return the source between a named function's outer braces. Used to
    scope assertions to ONE function so a string elsewhere in the file
    cannot satisfy them by accident."""
    marker = f"function {name}("
    start = js.find(marker)
    assert start != -1, f"{name} not found in ledger.js"
    brace = js.index("{", start)
    depth = 0
    for i in range(brace, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[brace:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


# ── groupSortKeys: the single group-data reading point ────────────────

def test_group_sort_keys_reads_backend_average_cost(js):
    """groupSortKeys must expose the first row's group_avg_cost as a
    nullable avgCost, using ?? null so an absent key (legacy reply) is
    unavailable rather than undefined."""
    block = function_block(js, "groupSortKeys")
    assert "avgCost: first.group_avg_cost ?? null" in block, (
        "groupSortKeys must read group_avg_cost off the group's first row"
    )


# ── buildGroupRow: the parent Price cell ──────────────────────────────

def test_group_row_renders_average_cost_in_price_cell(js):
    """The parent Price cell must render the average through formatNumber
    with the group's display currency — raw backend floats, frontend
    formatting, same rule as every other numeric cell."""
    block = function_block(js, "buildGroupRow")
    assert "avgCost" in block, "buildGroupRow must read avgCost"
    assert "formatNumber(avgCost)" in block, (
        "the Price cell must format the backend average, not print raw floats"
    )
    assert "${formatNumber(avgCost)} ${currency}" in block or \
        re.search(r"formatNumber\(avgCost\).*\$\{currency\}", block), (
        "the Price cell must carry the group's display currency suffix"
        " (display_currency || currency)"
    )


def test_group_row_uses_dash_when_average_cost_is_null(js):
    """A flat position (group_avg_cost null) renders "—". The check must
    be an explicit null comparison — a truthiness test would also hide a
    legitimate 0, and undefined must not slip through as '0 undefined'."""
    block = function_block(js, "buildGroupRow")
    assert "avgCost === null" in block, (
        "an unavailable average must be tested explicitly against null"
    )
    # The dash branch must exist for the null case.
    null_branch = re.search(
        r"avgCost === null[^}]*?textContent = \"—\"", block, re.S
    )
    assert null_branch, (
        "a null avgCost must write an em dash into the Price cell"
    )


def test_group_average_price_does_not_require_live_quote(js):
    """Average price is a stored-facts calculation. Its rendering must
    run BEFORE/outside the hasLive branch so a failed Yahoo quote still
    paints the parent Price while Value/Gain cells degrade to "—"."""
    block = function_block(js, "buildGroupRow")
    avg_render = block.find("formatNumber(avgCost)")
    has_live = block.find("if (hasLive)")
    assert avg_render != -1, "buildGroupRow must render avgCost"
    assert has_live != -1, "buildGroupRow's live branch is the control"
    assert avg_render < has_live, (
        "Price must be painted from stored facts before/independently of "
        "the hasLive branch — a quote failure must not hide the average"
    )


def test_group_average_price_does_not_replace_quick_sell_price(js):
    """Quick Sell still prefills the exact NATIVE live quote
    (txs[0].price_now), never the displayed average cost."""
    block = function_block(js, "buildGroupRow")
    assert "const priceNow = txs[0].price_now" in block, (
        "quick-sell eligibility must stay keyed on the live native quote"
    )
    prep = function_block(js, "prepareFullSale")
    assert "avgCost" not in prep, (
        "prepareFullSale must never fill the form from the average cost"
    )
    assert "price_now" not in prep or "livePrice" in prep, (
        "prepareFullSale keeps its live-price parameter contract"
    )
