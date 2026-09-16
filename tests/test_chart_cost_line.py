"""Cost-basis hover-line contract tests for the portfolio chart.

These are string checks, not rendering tests — pytest can't run a browser.
What they lock is the PERIOD WHITELIST that decides when the dashed cost
line (and the y-axis expansion that keeps it on-screen) is allowed:

  * `common.js` declares it as `COST_LINE_PERIODS = new Set([...])`;
  * that set must equal `set(PERIOD_MAP) - {"1D", "5D", "1M"}` — the
    3M-and-longer windows whose range can actually contain the cost series.

Without this lock, adding a timeframe to `PERIOD_MAP` (market_data.py) would
silently leave `COST_LINE_PERIODS` stale — a new medium/long period would
just lose its cost line, with no visible error. The comment in common.js
points here.

Also locked: BOTH hooks (axis expansion and the drawing) honour the
whitelist, so the axis and the line can never disagree about a period.
"""

import re
from pathlib import Path

from market_data import PERIOD_MAP

ROOT = Path(__file__).resolve().parent.parent

# The windows too short for net contributions to sit inside the plotted
# value range — no line, and no axis expansion, on these.
SHORT_PERIODS = {"1D", "5D", "1M"}


def common_js() -> str:
    return (ROOT / "static" / "js" / "common.js").read_text()


def test_cost_line_periods_match_period_map():
    """COST_LINE_PERIODS must be exactly PERIOD_MAP's keys minus the short
    periods. Adding a timeframe to PERIOD_MAP fails this until the JS set
    is updated too — the two sources of truth stay in sync."""
    js = common_js()
    match = re.search(
        r'COST_LINE_PERIODS\s*=\s*new Set\(\[([^\]]*)\]\)', js)
    assert match, (
        "common.js must define COST_LINE_PERIODS as `new Set([...])`"
    )
    declared = set(re.findall(r'"([^"]+)"', match.group(1)))
    expected = set(PERIOD_MAP) - SHORT_PERIODS
    assert declared == expected, (
        "COST_LINE_PERIODS must equal set(PERIOD_MAP) - {1D, 5D, 1M}; "
        f"got {sorted(declared)}, expected {sorted(expected)}"
    )


def test_cost_line_gated_in_both_hooks():
    """The axis expansion (afterDataLimits) AND the drawing
    (afterDatasetsDraw) must both check the whitelist — otherwise the axis
    could resize for a period whose line never draws, or vice versa."""
    js = common_js()
    assert js.count("COST_LINE_PERIODS.has(currentPeriod)") >= 2, (
        "costLine's afterDataLimits and afterDatasetsDraw must both gate on "
        "COST_LINE_PERIODS.has(currentPeriod)"
    )
