# Fix: year-only x-axis labels on 5Y and MAX charts

Status: in progress
Branch: fix/5y-chart-axis-labels
Scope: bug/tweak (not a roadmap item)

## Problem

The dashboard portfolio chart and the stock detail chart share the chart
factory in `static/js/common.js` (`setupTimeframeChart`). Its x-axis helper
`buildXTickLabels` picks ticks by bar index and, when the window spans two
calendar years, prints month + year. The 5Y series uses weekly bars and MAX
uses monthly bars (`market_data.py` `PERIOD_MAP`), so those index-stride picks
land on arbitrary months. A current 5Y window reads:

`Oct 2021, Aug 2022, Jun 2023, Apr 2024, Feb 2025, Dec 2025, Oct 2026`

The user hates these labels on both pages. Chosen fix: for multi-year
windows, print only the year at the first bar of each calendar year, e.g.
`2022, 2023, 2024, 2025, 2026`.

## Behavior contract

- A multi-year window is `yearSpan >= 2`, where `yearSpan` is
  `lastYear - firstYear` from the first/last parseable labels.
- Multi-year windows paint bare years (`2022`) at year-boundary bars only.
- A boundary is an index `i > 0` where the parsed label is non-null and its
  year differs from the nearest prior non-null parsed label. Index 0 is never
  a boundary, so a partial first year (Oct 2021 in a 5Y window) is not
  labeled.
- Year labels use at least six slots (`Math.max(target, 6)`), so a 5Y
  window never skips one of its five or six years, even on a phone. MAX
  uses the same slots and is thinned newest-first:
  `step = max(1, ceil(boundaries.length / yearTarget))`, walking backward
  from the newest boundary. The newest year always shows.
- The chart gets 16px of right layout padding. The newest year sits almost
  at the plot's right edge on MAX, and a centered 4-digit label would clip
  without that room. The padding costs 16px of plot width.
- `yearSpan` 0 or 1 keeps today's behavior:
  - 1Y (always 2 calendar years) keeps `Sep 2025`;
  - a window inside one calendar year keeps `Sep 4`;
  - a 5Y series with only 3 calendar years of data (diff 2) flips to bare
    years, because it is still multi-year.
- 5D/1D intraday branches are unchanged.
- Tooltips, raw backend labels, `PERIOD_MAP`, HTML, and y-axis config are
  unchanged.
- Interior `null`/malformed labels are skipped safely. Leading corrupt labels
  keep today's raw passthrough.
- Invalid calendar parts (month outside 1-12, day outside 1-31) parse as
  null instead of printing `undefined`.

## Files

1. `static/js/common.js`
   - Rewrite the x-axis comment block above `buildXTickLabels`.
   - Add a date-parts validity guard in the label parser.
   - Add `yearBoundaryIndices(parsed)` and `yearTickIndices(boundaries, target)`
     after `stridedIndices`, inside the contiguous pure block so the MiniRacer
     test can eval it.
   - In the daily date branch, use the year-only path when `yearSpan >= 2`.
   - In the 5D datetime branch, skip null entries and compare against the
     nearest prior non-null entry.
   - Update the stale tooltip comment that mentions `Sep 2025`.
2. `tests/test_chart_ticks_behavior.py` (extend the existing MiniRacer suite)
   - Multi-year target 6 -> `["2022","2023","2024","2025","2026"]`.
   - Multi-year target 3 -> the same five years (no year skipped).
   - MAX-style 29 boundaries, target 6 -> six evenly spaced years ending
     on the current one.
   - Diff-2 short history -> `["2025","2026"]`.
   - 1Y diff-1 stays month+year; single year stays month+day.
   - Empty -> `[]`; all-junk passes through raw.
   - Interior null/junk does not throw and still paints years.
   - Invalid date parts (`2026-13-40`) do not print `undefined`.
   - Existing 1D/5D tests stay green.
3. `tests/test_chart_axis.py`
   - Lock the new helper names, `yearSpan >= 2`, and the bare-year template.
4. `project-brief.md`
   - Append one sentence after the long-horizon bullet's intraday contract:
     `Multi-year windows (5Y/MAX) label the first bar of each calendar year
     with the bare year; shorter windows keep month+year or month+day.`

## Verification

1. Write the behavior tests first; run
   `python -m pytest tests/test_chart_ticks_behavior.py tests/test_chart_axis.py`
   and confirm the new cases fail before implementation.
2. Implement, then run the same targeted tests.
3. Run the full suite: `python -m pytest`.
4. Manual browser check on dashboard and stock detail: 5Y and MAX show bare
   years; 1Y/3M/6M/YTD unchanged; 1D/5D unchanged; hover tooltips show exact
   dates; at 375px the 5Y chart shows all five years and MAX shows six,
   including the newest year; light and dark.
5. Diff review gate with the `reviewer` subagent in diff mode. Then wait for
   the user's explicit merge approval.

## Edge cases

- Empty labels array.
- All-unparseable labels.
- Interior null/junk labels.
- Leading corrupt label (raw passthrough, existing behavior).
- `yearSpan` 0, 1, and exactly 2.
- MAX with ~100 year boundaries thinned to the target.
- Partial first year omitted.
- Resize rebuilds the tick plan with the new target.
- Truncated TWR labels still label only the sliced series.
