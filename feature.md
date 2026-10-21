# Fix: show compared dates in the chart measurement box

Status: in progress
Branch: fix/measurement-dates
Scope: bug/tweak (not a roadmap item)

## Problem

The price-difference ruler (desktop drag, mobile two-finger) draws two
vertical guides, two endpoint dots, and a box with only the price difference
and percent. A user who measures two points cannot tell which dates they
picked. `pixelToData` already returns each point's raw label, but the
priceDiff plugin never reads it (`static/js/common.js`).

## Behavior contract

- The measurement box gains a top line with both compared dates:
  `Sep 4, 2025 → Sep 18, 2025`.
- Date text matches the hover tooltip exactly:
  - single-year window: `Sep 4`;
  - window spanning calendar years: `Sep 4, 2025`;
  - intraday label: `Sep 4, 09:30`.
- Endpoints are ordered by `dataIndex` before formatting and before the
  arithmetic. A right-to-left drag or reversed two-finger order therefore
  shows the earlier date first and computes `later - earlier`.
- Comparing the same point twice paints one date, not `Sep 4 → Sep 4`.
- The box keeps its rounded dark pill, green/red numbers, and clamp. Height
  grows from 38px to 52px.
- Realistic date text fits at 360px: measure the diff at bold 12px, the
  percent at 11px, then the dates at 10px; if the date line is still too
  wide, re-measure at 9px. Final box width is capped at the plot width.
- Value mode only, as today: Performance mode and normalized comparison
  overlays still show no ruler (`canMeasurePrice`).

## Files

1. `static/js/common.js`
   - Add pure helpers immediately after `monthYear` and before
     `stridedIndices`, so the MiniRacer test slice includes them:
     * `formatBarDate(raw, spansYears)`: DATETIME + valid parts ->
       `Sep 4, 09:30` (ignores `spansYears`); DATE + valid parts ->
       `Sep 4, 2025` or `Sep 4`; otherwise raw.
     * `labelsSpanYears(labels)`: counts only string labels matching
       `DATE_RE` with valid month/day; `find`/`findLast`; compares the
       first four characters. DATETIME, junk, null, and empty input are
       ignored, so an intraday series returns false.
     * `orderMeasurementPoints(a, b)`: `a.dataIndex <= b.dataIndex` keeps
       `[a, b]`, otherwise `[b, a]`.
   - Tooltip title becomes `return formatBarDate(raw, labelsSpanYears(lastLabels));`
     with the existing `lastLabels[items[0].dataIndex] || ""` fallback.
   - priceDiff plugin: order endpoints, build `dateText`, draw the date in
     neutral `#e5e7eb`, use the ordered values for diff/pct, and keep the
     guides/dots at their original pixels.
2. `tests/test_chart_ticks_behavior.py`
   - Add `_value(expression)` using `json.dumps` for string arguments.
   - `formatBarDate` cases: single-year, cross-year, intraday with
     `spansYears` false and true, junk, empty, invalid date, invalid
     datetime.
   - `labelsSpanYears` cases: cross-year true, same-year false, empty
     false, junk false, null+junk+two-date true, cross-year DATETIME false,
     single-date intraday false.
   - `orderMeasurementPoints`: reversed, already ordered, equal index.
   - Existing tick tests stay green.
3. `tests/test_chart_tooltip.py`
   - Add a `formatBarDate` body slicer.
   - Point exact template/`validDateParts` assertions at the helper.
   - Title body asserts the raw fallback and shared-formatter call, and
     does not contain inline parsers/templates or `validDateParts`.
   - Comparison title test asserts `formatBarDate`, not `monthDay`.
4. `tests/test_price_diff.py`
   - Select the priceDiff `afterDatasetsDraw` body via `_hook_bodies`
     (the body containing `measureStart` and `diffText`).
   - Lock the date line, literal `→`, `samePoint` ternary, ordered values,
     `const boxH = 52`, `#e5e7eb`, `Math.min`, `right - left`, and
     `9px sans-serif`.
   - Update the module docstring: compared dates are now in scope.
5. `feature.md` — this plan.

## Verification

1. Write tests first; run
   `python -m pytest tests/test_chart_ticks_behavior.py tests/test_chart_tooltip.py tests/test_price_diff.py`
   and confirm the new cases fail.
2. Implement, then rerun the targeted tests.
3. Run the full suite: `python -m pytest`.
4. Browser at desktop and 360px:
   - stock 5Y and 1D, drag both directions;
   - dashboard portfolio chart;
   - same-point measurement;
   - measurement near both edges;
   - light and dark;
   - Performance mode and comparison overlays show no ruler.
5. Diff review with the `reviewer` subagent, then wait for the user's GUI
   approval before merging.

## Edge cases

- Same point twice.
- Reversed drag / reversed finger order.
- 5D across New Year (DATETIME labels never add a year).
- Invalid DATETIME parts.
- Empty, null, and junk labels.
- Box near edges; long cross-year date text at 360px.
- Value-mode only; comparison and TWR paths unchanged.
