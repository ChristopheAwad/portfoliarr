# Chart hover, touch, and ruler interaction fixes

## Status and scope

The user approved the implementation and GUI behavior, then requested a PR.
The full `python -m pytest` suite passed with 903 tests before the PR branch
was created. This is interaction bug-fix work, not a new roadmap item.
No Flask, portfolio-math, or native Android changes are needed.

The shared line-chart factory in `static/js/common.js` controls the dashboard
and stock charts. The allocation donut and its swipe handler live in
`static/js/main.js`. The line canvases use `touch-action: pan-y` in
`static/style.css` to keep page scroll while stopping pinch-zoom on the
two-finger price-difference gesture. Pinch elsewhere on the page is unchanged.

## Approved behavior

- Hover follows the nearest bar. A short mouse click does not start the
  ruler. A drag starts it after a five-pixel threshold. Guides use the bars'
  actual x and y positions, not the pointer x with an unrelated bar value.
  A completed ruler remains visible without a competing tooltip, crosshair,
  or cost hover line. A new click dismisses it; a new drag replaces it.
- One-finger touch inspects the line until finger lift or cancellation.
  Two fingers measure raw prices only. Hover stays suppressed while one
  finger remains after the other lifts. A new one-finger tap clears the
  pinned ruler. Synthetic mouse events after touch cannot restart it.
- The ruler works in portfolio Value and plain stock views. Portfolio
  Performance and normalized stock comparisons use an index axis and do
  not offer raw-price measurement. Switching modes clears the ruler.
- Silent timeframe prefetch does not change the visible ruler; visible
  refresh clears it before fetching, even if the fetch fails. A missing,
  empty, or non-finite primary bar cannot produce a false ruler value.
- The allocation donut changes views on a one-finger, mainly horizontal
  swipe beyond 40 pixels. Vertical scroll, diagonal movement, multiple
  fingers, cancelled touches, and short movements leave the view alone.
  Touch tooltips disappear on the last finger lift or cancellation.
- The line canvases reserve two-finger gestures for the ruler but still
  allow one-finger vertical scrolling. The allocation donut is unaffected.

## Test-first implementation and coverage

1. Add focused pytest source checks in `tests/test_price_diff.py` for both
   mouse and touch ruler eligibility, exclusion of normalized axes, mode
   clearing, empty/non-finite bar refusal, coordinates snapped to the same
   primary bar, click-versus-drag threshold, release inside/outside the
   canvas, persistent ruler hover suppression, staggered finger lifts,
   cancelled touches, and touch ghost handling.
2. Add a check in `tests/test_chart_refresh.py` that only a visible refresh
   resets a ruler before fetching; a background prefetch must not reset it.
   Preserve request-generation, cache, and selection behavior.
3. Add checks in `tests/test_allocation_ui.py` for single-finger horizontal
   swipe qualification, multi-touch rejection, cancelled gestures, and
   tooltip/active-wedge cleanup even when a chart was destroyed.
4. Run the new focused tests first and confirm failures are due to the
   missing interaction behavior rather than a broken test or dependency.
   Python source checks cannot simulate actual browser touch events.

## Implementation steps

1. In `static/js/common.js`, share one raw-value ruler eligibility rule
   between mouse and touch. Resolve each endpoint against the nearest valid
   primary bar and use that bar's x, y, and value; refuse empty/null bars.
2. Keep a pending mouse press separate from active drag and pinned ruler.
   Wait for the threshold; finalize on canvas or document mouseup. Suppress
   Chart.js tooltip, crosshair, and cost hover line while dragging or pinned.
   A click/tap dismisses a pinned ruler and a new drag replaces it.
3. Keep two-finger measurement active until the last finger lifts; freeze
   endpoints while only one remains and prevent that remaining finger from
   starting a page scroll. Finish the ruler on final lift, discard an
   interrupted measurement on cancellation, and clear the hover/ghosts.
4. Clear the ruler on visible refresh, mode switch, or comparison reload.
   Silent prefetch changes only its cache. Keep the existing data shapes and
   period return/tooltip formatting.
5. In `static/js/main.js`, record both swipe coordinates and reject
   multi-touch, cancelled, mainly vertical, and outside-end gestures.
   Clear the donut tooltip and active wedge on final lift/cancellation;
   reject delayed ghost events. Preserve arrow/dot and desktop hover.
6. In `static/style.css`, set `touch-action: pan-y` on `.chart-box > canvas`
   only, so the browser does not claim the two-finger line-chart gesture.

## Verification and shipping gate

Run `python -m pytest tests/test_price_diff.py tests/test_chart_refresh.py
tests/test_allocation_ui.py` and the final full `python -m pytest` suite.
Review the diff for unintended market data, timeframe, comparison, and
allocation changes. GUI checks: desktop hover, click, drag across sparse
bars, outside release, and mode change; phone one-finger inspection and
vertical scroll, two-finger ruler without page zoom, staggered lifts and
cancel, donut horizontal swipe versus diagonal scroll, and empty states.
The user approved the GUI and requested this PR. Commit/push are now
authorized; follow PR checks and review before merge.

## Files

`feature.md`, `static/js/common.js`, `static/js/main.js`,
`static/style.css`, `tests/test_price_diff.py`,
`tests/test_chart_refresh.py`, `tests/test_allocation_ui.py`.
