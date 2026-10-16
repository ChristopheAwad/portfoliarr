"""Run the x-axis tick builder in a small JavaScript engine.

Source-string checks (test_chart_axis.py) cannot prove the formatting
decision. These do. The tick plan is what decides whether a 1D chart
shows clock times or dates, so the 1D label-shape change is pinned here.
No browser or network is needed.
"""

import json
from pathlib import Path

import pytest


COMMON = (Path(__file__).resolve().parents[1] / "static/js/common.js")


def _engine():
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    js = MiniRacer()
    # The bundled V8 predates Array.prototype.findLast (ES2023); the
    # browser has it, so polyfill it here rather than change real code.
    js.eval(
        "if (!Array.prototype.findLast) {"
        "  Array.prototype.findLast = function (fn) {"
        "    for (let i = this.length - 1; i >= 0; i--) {"
        "      if (fn(this[i], i, this)) return this[i];"
        "    }"
        "    return undefined;"
        "  };"
        "}"
    )
    src = COMMON.read_text()
    # MONTHS, the tick target, both regexes, the small helpers and
    # buildXTickLabels are one contiguous block; eval it whole so the
    # constants live in the same script scope as the function.
    start = src.index("const MONTHS")
    end = src.index("\n}", src.index("function buildXTickLabels(")) + 2
    js.eval(src[start:end])
    return js


def _ticks(labels, target):
    js = _engine()
    return json.loads(js.eval(
        f"JSON.stringify(buildXTickLabels({json.dumps(labels)}, {target}))"
    ))


def test_single_date_intraday_shows_clock_times():
    """1D: one date, many 5-minute bars → time ticks, no date clutter."""
    labels = [
        "2026-10-16 09:30", "2026-10-16 09:35",
        "2026-10-16 09:40", "2026-10-16 09:45",
    ]
    ticks = _ticks(labels, 2)
    assert ticks == ["09:30", "", "09:40", "09:45"]


def test_multi_date_intraday_labels_each_day_boundary():
    """A 1D union across two sessions (or 5D) labels each day's first bar
    with the date, and paints nothing for the other bars."""
    labels = [
        "2026-09-01 09:30", "2026-09-01 15:30",
        "2026-09-02 09:30", "2026-09-02 15:30",
    ]
    ticks = _ticks(labels, 6)
    assert ticks == ["Sep 1", "", "Sep 2", ""]
