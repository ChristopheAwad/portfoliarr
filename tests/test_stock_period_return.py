# tests/test_stock_period_return.py
# ==================================
# Contracts for the stock detail page's period return pill.
#
# The stock page paints its change pill with a stock-only painter,
# `paintPeriodChange`, because the pill has a shape of its own:
#
#   period: +$4.27 (+2.34%)   ->   "5D: +$4.27 (+2.34%)"
#   period: -$4.27 (-2.34%)   ->   "5D: -$4.27 (-2.34%)"
#   period: +$4.27            ->   zero first bar (no percent base)
#
# The period leads so the timeframe reads first; the dollar move and its
# percent follow in one pair. Plain "$" is correct for both USD and CAD
# because the big native price above already carries the code.
#
# The bug this locks out shipped a bare percent as the AMOUNT argument, so
# the pill read "+2.34 5D" — a percent with no "%" and no dollar figure.
#
# WHY SOURCE CHECKS? pytest cannot execute browser JavaScript. What it CAN
# lock is the callback's wiring and the painter's shape: which argument
# carries the dollar move, which carries the percentage, and how the text
# is assembled.

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOCK_JS = (ROOT / "static/js/stock.js").read_text()


# ── Source-slice helpers ──────────────────────────────────────────────

def _period_callback_body() -> str:
    """The onPeriodData(...) callback body inside setupTimeframeChart."""
    start = STOCK_JS.index("onPeriodData({")
    end = STOCK_JS.index("\n    },", start)
    return STOCK_JS[start:end]


def _quote_branch_body() -> str:
    """The 1D quote-pill branch in refreshStockQuote()."""
    start = STOCK_JS.index('if (activePeriod === "1D") {')
    end = STOCK_JS.index("\n        }", start)
    return STOCK_JS[start:end]


def _painter_body() -> str:
    start = STOCK_JS.index("function paintPeriodChange(")
    end = STOCK_JS.index("\n}", start)
    return STOCK_JS[start:end]


# ---------------------------------------------------------------------------
# A. The callback passes BOTH units to the stock painter
# ---------------------------------------------------------------------------

def test_period_callback_computes_the_dollar_move():
    body = _period_callback_body()
    assert "const change = lastValue - firstValue" in body, (
        "the callback must derive the dollar move from the chart's own bars"
    )


def test_period_callback_computes_percent_from_the_same_move():
    body = _period_callback_body()
    assert "(change / firstValue) * 100" in body, (
        "the percentage must be the dollar move over the first bar"
    )


def test_period_callback_paints_period_amount_and_percent():
    body = _period_callback_body()
    assert "paintPeriodChange(stockDayChangeEl, period, change, pct)" in body, (
        "the painter must receive the period, dollar move, AND percentage"
    )


def test_period_callback_does_not_ship_percent_as_the_amount():
    """The regression: percent used to be passed in the amount slot with a
    null percentage, so the pill lost its dollar figure and its "%"."""
    body = _period_callback_body()
    assert "paintPeriodChange(stockDayChangeEl, period, pct" not in body


# ---------------------------------------------------------------------------
# B. Zero base degrades to amount-only (never Infinity)
# ---------------------------------------------------------------------------

def test_period_callback_guards_a_zero_first_bar():
    body = _period_callback_body()
    assert "firstValue !== 0" in body, (
        "a zero first bar has no percentage base and must not divide by zero"
    )
    assert ": null" in body, (
        "the percentage must degrade to null so the painter drops only the %"
    )


# ---------------------------------------------------------------------------
# C. The 1D quote branch uses the same painter
# ---------------------------------------------------------------------------

def test_1d_quote_branch_still_uses_quote_facts():
    body = _quote_branch_body()
    assert "paintPeriodChange(stockDayChangeEl, \"Today\"," in body
    assert "quote.change" in body
    assert "quote.change_pct" in body


def test_callback_still_owns_the_active_period():
    body = _period_callback_body()
    assert "activePeriod = period" in body


# ---------------------------------------------------------------------------
# D. The painter's shape
# ---------------------------------------------------------------------------

def test_painter_leads_with_the_period():
    body = _painter_body()
    assert "${period}: ${amount}" in body, (
        "the timeframe must lead, e.g. '5D: +$4.27 (+2.34%)'"
    )


def test_painter_prefixes_the_dollar_sign_on_the_absolute_amount():
    body = _painter_body()
    assert "$${formatNumber(Math.abs(value))}" in body, (
        "the amount must be a plain '$' over the absolute value"
    )
    assert 'value >= 0 ? "+" : "-"' in body, (
        "the sign must come from the value so negatives render '-$4.27'"
    )


def test_painter_appends_the_percent_pair():
    body = _painter_body()
    assert "pct.toFixed(2)" in body
    assert "%" in body
    assert "pct === null" in body, (
        "a null percentage must drop the parenthetical, not print NaN"
    )


def test_painter_toggles_sign_classes():
    body = _painter_body()
    assert 'classList.toggle("pos", value >= 0)' in body
    assert 'classList.toggle("neg", value < 0)' in body
