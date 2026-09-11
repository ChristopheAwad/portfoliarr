# Feature: Chart Price-Difference Tool

## Problem
The user wants to measure the price difference and percentage gain/loss between any two points on the chart. Desktop uses click-and-drag; mobile uses two-finger touch (one finger per endpoint). This is a standard trading-chart "ruler" feature.

## Target State
- **Desktop:** Click point A → drag to point B → release. A dashed line connects the two points with a floating label showing price difference and % change. Click anywhere else (or start a new drag) to dismiss.
- **Mobile:** Place finger 1 on chart (Point A) → place finger 2 on chart (Point B). Same dashed line + label appears between the two touch points. Lift fingers to dismiss (or tap elsewhere).
- The overlay is visible during drag on desktop (live preview). On mobile, it appears once both fingers are down.
- The tooltip and crosshair are suppressed while measuring.
- Switching timeframes clears the measurement.
- Works on both the dashboard portfolio chart AND the stock detail chart (shared factory = automatic).

## Files to touch
- `static/js/common.js` — add `priceDiffPlugin` (custom Chart.js plugin), attach canvas touch listeners in `setupTimeframeChart()`, expose `clearMeasurement()` on the returned handle, clear measurement in `refresh()`
- `static/style.css` — no changes needed (all drawing is canvas-based, matching prevCloseLine pattern)
- `tests/test_price_diff.py` — new contract tests (string checks, same pattern as test_prev_close.py)

## Plan

### 1. Add priceDiffPlugin to `common.js` (below crosshairPlugin, ~line 598)

A Chart.js plugin with id `"priceDiff"` that:

**State (closure variables in setupTimeframeChart):**
- `measureStart` — `{ x, y, dataX, dataY }` or null (the first point)
- `measureEnd` — `{ x, y, dataX, dataY }` or null (the second point, updated live during drag)
- `measuring` — boolean flag, true while a measurement is active (suppresses crosshair + tooltip)

**Hooks:**
- `beforeEvent(chart, args)` — intercept raw events:
  - On desktop: listen for `mousedown` → capture `measureStart` (pixel + data coords via `getRelativePosition` + `getValueForPixel`), set `measuring = true`. `mousemove` → update `measureEnd` live, call `chart.draw()` for live preview. `mouseup` → finalize `measureEnd`, set `measuring = false`.
  - On mobile: listen for `touchstart` on canvas (native, not Chart.js event) → if `e.touches.length >= 2`, grab both touch points, convert to chart coords, set `measureStart` and `measureEnd`, set `measuring = true`. `touchmove` → update both points. `touchend` → if fewer than 2 fingers remain, finalize.
  - On `click` (desktop, non-drag): clear measurement if `measureStart` is set (dismiss gesture).
- `afterDatasetsDraw(chart)` — if both points are set, draw the overlay:
  - Dashed line between the two points (same `setLineDash` pattern as prevCloseLine)
  - Small filled circles at each endpoint
  - Background rounded rect at the midpoint containing two lines of text:
    - Line 1: `±$X.XX` (price difference, formatted with `formatPrice`)
    - Line 2: `±Y.YY%` (percentage change)
  - Color: green if positive, red if negative (read `--green-pos` / `--red-neg` from CSS)
- `beforeTooltipDraw(chart, args)` — if `measuring` is true, cancel the tooltip (set `args.cancel = true` or return early)

**Dismiss:**
- Desktop click (no drag) clears the measurement
- New `touchstart` with 1 finger clears any existing measurement
- `refresh()` (period switch) clears the measurement

### 2. Attach native touch listeners in `setupTimeframeChart()`

After the Chart is created (line ~995), attach `touchstart`, `touchmove`, `touchend` listeners directly on the canvas element. These listeners feed into the plugin's state (closure variables). The plugin hooks read the state and draw.

Why native listeners: Chart.js's `beforeEvent` only passes one touch point in the event object. For two-finger gestures, we need the raw `TouchEvent.touches` array.

The listeners are cleaned up when the chart is destroyed (if Chart.js supports `onDestroy` — otherwise they'll be GC'd with the canvas).

### 3. Expose `clearMeasurement()` on the returned handle

Add to the return object (line ~1084):
```js
clearMeasurement() {
    measureStart = null;
    measureEnd = null;
    measuring = false;
    chart.draw();
}
```

This lets callers programmatically clear the overlay.

### 4. Clear measurement in `refresh()`

At the start of the `refresh()` function (line ~1011), reset measurement state:
```js
measureStart = null;
measureEnd = null;
measuring = false;
```

This ensures switching timeframes drops the overlay.

### 5. Suppress crosshair while measuring

In the existing `crosshairPlugin` (line 579), add an early return when `measuring` is true. The crosshair plugin reads from the closure — it can check `measuring` directly since both live in the same `setupTimeframeChart` scope.

### 6. Tests: `tests/test_price_diff.py`

String-check contract tests (same pattern as `test_prev_close.py`):

1. **Plugin exists:** `priceDiffPlugin` or `id: "priceDiff"` is defined in common.js
2. **Plugin hooks:** `afterDatasetsDraw` hook exists in the priceDiff plugin
3. **Clear method exposed:** `clearMeasurement` is in the return object of setupTimeframeChart
4. **Measurement cleared on refresh:** `refresh()` references `measureStart` or resets measurement state
5. **Crosshair suppressed during measure:** crosshairPlugin checks `measuring` flag
6. **Touch listeners attached:** `touchstart` listener on canvas in setupTimeframeChart
7. **formatPrice used in label:** The price-diff label uses `formatPrice` for consistency
8. **CSS tokens read:** Reads `--green-pos` and `--red-neg` from CSS (not hardcoded colors)
9. **Dashed line:** Uses `setLineDash` for the measurement line (same pattern as prevCloseLine)

## Data flow
```
Desktop:
  mousedown → measureStart = {pixel, data} → measuring = true
  mousemove → measureEnd = {pixel, data} → chart.draw() (live preview)
  mouseup   → measureEnd finalized → measuring = false → chart.draw()
  click     → clear measurement

Mobile:
  touchstart(2 fingers) → measureStart + measureEnd from touches[] → measuring = true
  touchmove              → update both points → chart.draw()
  touchend(< 2 fingers)  → finalize → measuring = false → chart.draw()

Period switch:
  refresh() → measureStart = measureEnd = null → measuring = false → chart.update()
```

## Why this is safe
- All changes are in `common.js` (shared factory) — no backend changes, no new routes, no DB touches
- The plugin is chart-local (passed in the `plugins` array at creation) — doesn't leak into other charts
- Canvas-only drawing — no DOM elements to style or position
- Follows the exact same pattern as `prevCloseLine` (custom plugin with `afterDraw` + canvas drawing)
- No new dependencies — just vanilla JS + Chart.js API
