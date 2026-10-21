"""Run the x-axis tick builder in a small JavaScript engine.

Source-string checks (test_chart_axis.py) cannot prove the formatting
decision. These do. The tick plan is what decides whether a 1D chart
shows clock times or dates, so the 1D label-shape change is pinned here.
The multi-year cases pin the 5Y/MAX bare-year rule: weekly/monthly bars
must label the first bar of each calendar year, not arbitrary months.
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


# Weekly-bar shape of a real 5Y window: the partial first year (2021) is
# not a boundary; 2022-2026 are. Interior months keep the indices honest.
MULTI_YEAR = [
    "2021-12-20",
    "2022-01-03", "2022-05-02",
    "2023-01-03", "2023-08-01",
    "2024-01-02", "2024-09-03",
    "2025-01-06", "2025-11-03",
    "2026-01-05", "2026-10-19",
]


def test_multi_year_labels_are_bare_years():
    """5Y/MAX: one bare-year label at the first bar of each year, never a
    month. The partial first year (Oct 2021) is deliberately omitted."""
    ticks = _ticks(MULTI_YEAR, 6)
    assert [tick for tick in ticks if tick] == [
        "2022", "2023", "2024", "2025", "2026",
    ]


def test_five_year_window_never_skips_a_year_on_phone():
    """Bare years are short, so a 5Y window keeps all five even when the
    phone target is 3. A gap between years reads as missing data."""
    ticks = _ticks(MULTI_YEAR, 3)
    assert [tick for tick in ticks if tick] == [
        "2022", "2023", "2024", "2025", "2026",
    ]


def test_max_scale_thins_many_year_boundaries_to_the_target():
    """MAX can hold ~100 year boundaries. They are thinned to six, still
    one bare year each, and the current year survives. The six-slot floor
    applies on a phone target of 3 too."""
    labels = []
    for year in range(1997, 2027):
        labels.extend([f"{year}-01-03", f"{year}-07-05"])
    expected = ["2001", "2006", "2011", "2016", "2021", "2026"]
    for target in (6, 3):
        ticks = _ticks(labels, target)
        assert [tick for tick in ticks if tick] == expected


def test_diff_two_short_history_flips_to_bare_years():
    """A 5Y series with only 2024-2026 of data still spans 3 calendar
    years, so it earns bare years. The partial 2024 start is skipped."""
    labels = [
        "2024-06-03", "2024-12-02",
        "2025-01-06", "2025-09-02",
        "2026-01-05", "2026-09-01",
    ]
    ticks = _ticks(labels, 6)
    assert [tick for tick in ticks if tick] == ["2025", "2026"]


def test_one_year_window_keeps_month_and_year():
    """1Y spans two calendar years (diff 1), so it must keep the familiar
    month + year labels rather than switching to bare years."""
    labels = [
        "2025-09-15", "2025-11-03", "2026-01-05", "2026-03-02",
        "2026-05-04", "2026-07-06", "2026-09-08",
    ]
    ticks = _ticks(labels, 6)
    assert [tick for tick in ticks if tick] == [
        "Sep 2025", "Jan 2026", "May 2026", "Sep 2026",
    ]


def test_single_year_window_keeps_month_and_day():
    """A window inside one calendar year keeps the short month + day."""
    labels = [
        "2026-01-05", "2026-03-02", "2026-05-04",
        "2026-07-06", "2026-09-08",
    ]
    ticks = _ticks(labels, 6)
    assert [tick for tick in ticks if tick] == [
        "Jan 5", "Mar 2", "May 4", "Jul 6", "Sep 8",
    ]


def test_empty_labels_paint_nothing():
    assert _ticks([], 6) == []


def test_unparseable_labels_pass_through_raw():
    """No parseable label means the old raw passthrough still applies."""
    assert _ticks(["a", "b", "c"], 6) == ["a", "b", "c"]


def test_interior_malformed_labels_do_not_break_year_ticks():
    """A null (missing bar label) and a junk string inside an otherwise
    daily series are skipped; the year plan around them still paints."""
    labels = [
        "2021-12-20",
        "2022-01-03", "2022-05-02", None,
        "2023-08-01",
        "2024-01-02", "junk",
        "2025-01-06", "2025-11-03",
        "2026-01-05", "2026-10-19",
    ]
    ticks = _ticks(labels, 6)
    assert [tick for tick in ticks if tick] == [
        "2022", "2023", "2024", "2025", "2026",
    ]


def test_invalid_calendar_parts_fall_back_to_raw_text():
    """The regex shape alone would accept month 13 / day 40 and print
    "undefined 40". Invalid parts parse as null, so the label passes
    through raw instead."""
    assert _ticks(["2026-13-40"], 6) == ["2026-13-40"]
