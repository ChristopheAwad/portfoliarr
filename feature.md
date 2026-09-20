# Feature: Comparison Session State and Bottom Performance Readout

## Roadmap

- Parent feature: Roadmap #17, Arbitrary Comparison Overlays.
- Roadmap status: `shipped 2026-09-20 (PR #60)`.
- This is a requested refinement to the active feature, not a new roadmap item.

## Status

IMPLEMENTED. The comparison overlays and requested refinement are complete.
Tests were written first and failed for the intended persistence, readout,
tooltip, and degraded-data gaps. The final full suite passes (`641 passed`).
This file preserves the implementation contract and verification checklist for
future maintenance.

## User Request

1. A comparison must be removed when the user navigates away. Comparisons must
   not persist across pages, reloads, or browser Back/Forward Cache restoration.
2. While comparison mode is active, the floating chart tooltip must contain
   only the hovered date.
3. Comparison performance and the legend must be below the chart.
4. Each performance number must sit directly beside its matching line-color
   marker.

## Locked Interpretation

Use a custom bottom comparison readout instead of Chart.js's built-in legend.
Each entry has this visual and DOM order:

```text
[colored marker] [+12.40%] [Portfolio]
[colored marker] [ +8.15%] [S&P 500]
```

The marker comes first, the percentage comes second, and the symbol/name comes
third. This places the number directly beside its line color, as requested.

The bottom percentages are cumulative performance at the active chart point:

```text
(growth_index_value / 100 - 1) * 100
```

- On mouse or touch hover, use the hovered data index.
- Before hover, and after mouse leave or touch dismissal, use the latest valid
  chart point for each dataset.
- A positive or zero percentage uses the existing positive color class.
- A negative percentage uses the existing negative color class.
- A missing value displays the app's unavailable glyph (`—`), never `0.00%`.
- The floating tooltip title continues to use the existing human-readable date
  formatting.
- In comparison mode, floating-tooltip body and footer content are empty. The
  tooltip therefore shows the date only.
- Outside comparison mode, preserve all current tooltip behavior exactly:
  stock raw price, portfolio value/cost/gain, and portfolio Performance without
  overlays must not change.

## State Contract

Comparison symbols are page-local JavaScript state only.

- Do not read `compareSymbols` from `localStorage`.
- Do not write `compareSymbols` to `localStorage`.
- Do not use `sessionStorage`, cookies, URL parameters, or backend persistence.
- Every normal page load starts with no comparisons.
- Navigating dashboard -> stock, stock -> dashboard, or stock A -> stock B starts
  the destination page with no comparisons.
- A browser Back/Forward Cache restoration can preserve the old DOM and JS heap.
  Handle `pageshow` with `event.persisted === true`: clear the picker state,
  repaint its chips/quick picks, and reload the current chart without a
  `benchmark` query parameter.
- Changing timeframe or Value/Performance mode is not page navigation. Keep
  active comparisons during those in-page actions.

## Existing Contracts That Must Stay Intact

- Maximum 3 comparison symbols.
- Ordered, uppercase, de-duplicated symbols.
- Dashboard comparisons appear only in Performance/TWR mode. Adding the first
  comparison auto-switches to Performance.
- Stock charts use raw prices with no comparison and growth-of-$100 while a
  comparison is active.
- Clearing all stock comparisons restores raw-price tools, including previous
  close and price-difference measurement.
- Dashboard benchmark history never changes the portfolio label axis.
- History endpoint replies stay byte-identical when no `benchmark` parameter is
  sent.
- Failed benchmarks degrade independently and do not fail the primary chart.
- Keep the existing backend implementation and `tests/test_compare.py` green.
- Do not add polling or a new endpoint.

## Files To Change

- `tests/test_compare_ui.py`: replace persistence expectations and add contracts
  for the custom bottom readout and comparison-only tooltip behavior.
- `tests/test_chart_tooltip.py`: lock date-only comparison callbacks while
  preserving normal tooltip callbacks.
- `tests/test_chart_refresh.py`: only change if a new reload/reset contract needs
  a source assertion; do not weaken existing request-generation assertions.
- `static/js/common.js`: remove persistence, add BFCache reset, render the bottom
  readout, and suppress comparison-mode tooltip body/footer.
- `static/js/main.js`: pass the dashboard readout element to the chart factory.
- `static/js/stock.js`: pass the stock readout element to the chart factory.
- `templates/index.html`: add an empty readout container directly below the
  dashboard `.chart-box`.
- `templates/stock.html`: add the same readout container directly below the
  stock `.chart-box`.
- `static/style.css`: style responsive bottom entries, markers, values, names,
  unavailable state, and hidden empty state.
- `feature.md`: this handoff.

Backend changes are limited to additive benchmark behavior in the existing
history routes. Do not change `db.py`, `market_data.py`, or the no-benchmark
response shapes.

## Part 1: Write Failing Tests First

### 1.1 Update `tests/test_compare_ui.py`

Remove or replace the current test named `test_picker_persists_symbols`. The new
tests must enforce page-local state.

Add `test_picker_does_not_persist_symbols` with source assertions that:

- `setupComparePicker` still exists.
- The `setupComparePicker` source does not contain `localStorage.getItem`.
- The `setupComparePicker` source does not contain `localStorage.setItem`.
- The source does not contain the string `compareSymbols`.
- The source does not contain `sessionStorage`.

Extract only the `setupComparePicker` function body for these negative checks.
Do not search all of `common.js`, because unrelated chart preferences correctly
use `localStorage`.

Add `test_picker_clears_bfcache_restoration` with source assertions that the
picker or its caller:

- Registers a `pageshow` listener.
- Checks `event.persisted`.
- Clears the comparison symbol array.
- Renders the empty chips/quick-pick state.
- Notifies the chart so it reloads without benchmarks.

Add `test_comparison_readout_markup_is_below_each_canvas`:

- Require one `.comparison-readout` container on each page.
- Require stable IDs: `portfolio-comparison-readout` and
  `stock-comparison-readout`.
- Verify by string position that each readout appears after its chart `<canvas>`
  and before the chart controls/picker.
- Do not use `aria-live`: hover changes can otherwise cause a burst of screen-
  reader announcements. The readout remains ordinary visible text.

Add `test_chart_factory_receives_comparison_readout`:

- `setupTimeframeChart` accepts a `comparisonReadout` option.
- `main.js` passes `document.getElementById("portfolio-comparison-readout")`.
- `stock.js` passes `document.getElementById("stock-comparison-readout")`.

Add `test_comparison_readout_renders_marker_value_then_name`:

- Require creation/use of `.comparison-readout-item`.
- Require child classes `.comparison-readout-marker`,
  `.comparison-readout-value`, and `.comparison-readout-name`.
- Lock their append order as marker, value, name. Use a narrow source assertion
  around the item builder rather than an assertion against unrelated DOM code.
- Require a helper named `renderComparisonReadout`.

Add `test_comparison_readout_uses_growth_return_math`:

- Require the implementation to calculate `(value / 100 - 1) * 100`.
- Require two decimal places and an explicit `+` sign for non-negative values.
- Require unavailable values to render `—`.

Add `test_comparison_readout_tracks_hover_and_falls_back_to_latest`:

- Require chart hover handling to pass the active data index to
  `renderComparisonReadout`.
- Require mouse-leave/no-active handling to render the latest valid point.
- Require touch cleanup to restore the latest-point readout after the tooltip is
  dismissed.

Keep all existing quick-pick, maximum, wiring, color palette, and normalized
chart assertions.

### 1.2 Update `tests/test_chart_tooltip.py`

Read the existing tests before editing. Preserve every assertion that protects
normal Value, Performance-without-comparison, and stock raw-price tooltips.

Add a comparison-mode source contract that requires:

- The tooltip `title` callback remains active.
- The tooltip `label` callback returns no body line when comparison overlays are
  visible.
- The tooltip `footer` callback returns no footer when comparison overlays are
  visible.
- `footerColor` does not attempt comparison return coloring when the comparison
  footer is absent.
- The condition is tied to visible comparison mode, not only
  `data.normalized === true`. Dashboard Performance overlays must get the same
  date-only tooltip behavior as stock comparisons.

Use one closure boolean such as `comparisonMode` or `showOverlays` as the source
of truth. Do not duplicate different stock/dashboard conditions throughout the
callbacks.

### 1.3 Add CSS source contracts

In `tests/test_compare_ui.py`, require these selectors:

- `.comparison-readout`
- `.comparison-readout-item`
- `.comparison-readout-marker`
- `.comparison-readout-value`
- `.comparison-readout-name`

Require a mobile media-query treatment that permits wrapping or horizontal
scrolling without clipping. Do not lock exact pixel values.

### 1.4 Run the red tests

Run:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py tests/test_chart_tooltip.py -q
```

Expected failures before implementation:

- Current picker still reads/writes `compareSymbols` in `localStorage`.
- No BFCache reset exists.
- No bottom readout containers exist.
- Current comparison tooltip still includes dataset values and a Return footer.
- No bottom readout renderer or styles exist.

If a new test passes before implementation, confirm that it protects a real
contract rather than only matching an unrelated string.

## Part 2: Make Comparison State Page-Local

### 2.1 Edit `setupComparePicker` in `static/js/common.js`

Keep the current function interface for input/results/chips/quick picks,
`primarySymbol`, and `onChange`, except remove the `storageKey` option and its
default.

Make these exact state changes:

1. Initialize `let symbols = [];` unconditionally.
2. Delete the `try/catch` that parses `localStorage`.
3. Delete the `persist()` function.
4. In `notify()`, call only `renderChips()` and `onChange(getSymbols())`.
5. Keep `getSymbols`, `addSymbol`, and `removeSymbol` behavior unchanged.
6. Add a `clearSymbols({ notifyChange = true } = {})` helper:
   - Return early only when the list is already empty and no repaint is needed.
   - Set `symbols = []`.
   - Call `renderChips()`.
   - If `notifyChange` and `onChange` exist, call `onChange(getSymbols())`.
7. Return `clearSymbols` with the existing picker methods.

Do not remove the primary-symbol exclusion, de-duplication, uppercase
normalization, maximum-three toast, chip removal, or quick-pick active state.

### 2.2 Handle browser Back/Forward Cache

Inside `setupComparePicker`, register:

```javascript
window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    clearSymbols();
});
```

`clearSymbols()` must call the page's existing `onChange`, which invokes the
chart handle's `reload()`. The resulting URL must omit `benchmark=` because
`getSymbols()` is empty.

Do not use `pagehide` to fetch during navigation. The destination page already
starts empty, and `pageshow` handles restoration of a cached source page.

### 2.3 Correct stale comments

Update comments in both templates and JavaScript that currently claim the
comparison list is shared or persisted. State that the picker is page-local.
Do not alter persistence for `chartMode` or other unrelated preferences.

## Part 3: Add Bottom Readout Markup and Styles

### 3.1 Template markup

In `templates/index.html`, immediately after the closing `</div>` for the
`.chart-box` containing `#portfolioChart`, add:

```html
<div id="portfolio-comparison-readout"
     class="comparison-readout"
     hidden></div>
```

In `templates/stock.html`, immediately after the `.chart-box` containing
`#stockChart`, add:

```html
<div id="stock-comparison-readout"
     class="comparison-readout"
     hidden></div>
```

The container belongs below the chart and above timeframe controls. Do not put
it inside the canvas wrapper; the canvas height must remain unchanged.

### 3.2 CSS in `static/style.css`

Add styles near the existing chart and comparison-picker rules.

- `.comparison-readout`: flex row, centered vertically, compact gap, modest top
  margin, and wrapping enabled. It is informational, not another card.
- `.comparison-readout[hidden]`: `display: none`.
- `.comparison-readout-item`: inline flex, center aligned, no decorative border
  or pill background.
- `.comparison-readout-marker`: small circular marker using inline
  `background-color`; `flex: 0 0 auto`.
- `.comparison-readout-value`: tabular numerals, semibold, immediately after the
  marker.
- `.comparison-readout-name`: secondary text after the value.
- Positive/negative value classes must reuse the app's established positive and
  negative colors. Do not introduce a new semantic palette.
- On narrow screens, permit natural wrapping with readable row/column gaps. Do
  not reduce text below the existing chart-control font size and do not clip or
  truncate percentages.

## Part 4: Render Dynamic Performance Below the Chart

### 4.1 Extend `setupTimeframeChart`

Add `comparisonReadout` to the options object accepted by
`setupTimeframeChart`.

Add closure state:

```javascript
let comparisonMode = false;
let comparisonReadoutIndex = null;
```

`comparisonMode` is true only when overlays are actually visible:

- Dashboard: at least one benchmark and mode is `performance`.
- Stock: at least one benchmark and `data.normalized === true`.

Do not equate `mode === "performance"` alone with comparison mode. Portfolio
Performance without overlays retains its current tooltip.

### 4.2 Build readout entries

Add a local function `renderComparisonReadout(index = null)` inside the chart
factory.

Exact behavior:

1. If no `comparisonReadout` element was supplied, return.
2. If `comparisonMode` is false, clear the container and set `hidden = true`.
3. If comparison mode is true, set `hidden = false` and clear old children.
4. Iterate all currently visible chart datasets in chart order: primary first,
   then comparison symbols.
5. Resolve the requested index:
   - If a valid hover index was supplied, try that index for every dataset.
   - If no index was supplied, find each dataset's final finite value.
   - If a dataset has no finite value at the hover index, display `—`; do not
     silently use a value from another date.
6. Calculate return as `(value / 100 - 1) * 100`.
7. Format finite return with an explicit plus sign for values >= 0 and exactly
   two decimals, followed by `%`.
8. Build each item in marker -> value -> name DOM order.
9. Marker color must match the actual dataset line:
   - Primary uses its current resolved border color.
   - Overlay `i` uses `getCompareColors()[i]`.
10. Use the dataset label for the name. Preserve the primary labels already set
    by `paint()`.

Use `document.createElement` and `textContent`; do not concatenate untrusted
symbols into `innerHTML`.

### 4.3 Keep the readout synchronized

At the end of `paint()`, after datasets and `comparisonMode` are updated but
before the resize/update request, call `renderComparisonReadout()` so the
latest-point values appear immediately.

When the user switches dashboard Value/Performance mode, the existing `paint()`
call must hide or show the readout correctly without another fetch.

When all comparisons are removed, `paint()` must:

- Remove overlay datasets through the existing reconciliation helper.
- Set `comparisonMode = false`.
- Clear and hide the bottom readout.
- Restore the current non-comparison tooltip and raw-price tools.

### 4.4 Track hover without re-fetching or rebuilding the chart

Use Chart.js's existing interaction path. Add an `onHover` option or a small
local plugin/event hook that receives active elements.

- If comparison mode is false, do nothing.
- If there is an active element, read its `index`, save it in
  `comparisonReadoutIndex`, and call `renderComparisonReadout(index)`.
- If there is no active element (mouse leaves the plot), set the index to null
  and call `renderComparisonReadout()` for latest values.
- Avoid `chart.update()` inside hover. Updating the external DOM is sufficient
  and prevents hover recursion/layout churn.
- Existing crosshair and tooltip positioning must continue to work.

In existing touch-end/touch-cancel cleanup, restore the latest bottom values by
calling `renderComparisonReadout()` after clearing the tooltip. Keep current
ghost-event prevention intact.

### 4.5 Make comparison tooltips date-only

The existing `title(items)` callback remains unchanged.

At the top of `label(item)`:

```javascript
if (comparisonMode) return [];
```

At the top of `footer(items)`:

```javascript
if (comparisonMode) return [];
```

At the top of `footerColor(items)` return the neutral current color when
`comparisonMode` is true; there is no visible footer to color.

Remove the old comparison-specific Return footer branches that use
`chartNormalized`. Keep the non-comparison portfolio Performance Return footer
and all Value/cost/gain behavior.

### 4.6 Disable Chart.js's built-in comparison legend

Keep `chart.options.plugins.legend.display = false` for all chart modes. The new
bottom DOM readout is now the legend and performance display. Delete or replace
the current line that sets built-in legend display to `showOverlays`.

This avoids two legends and gives exact marker/value/name ordering.

## Part 5: Wire Both Pages

In `static/js/main.js`, add to the existing `setupTimeframeChart` options:

```javascript
comparisonReadout: document.getElementById("portfolio-comparison-readout"),
```

In `static/js/stock.js`, add:

```javascript
comparisonReadout: document.getElementById("stock-comparison-readout"),
```

Do not create a second picker or second chart. Keep each page's current
`getBenchmarks` function and `onChange -> chartHandle.reload()` flow.

## Part 6: Verification

### 6.1 Focused tests

Run:

```bash
source .venv/bin/activate
python -m pytest tests/test_compare_ui.py tests/test_chart_tooltip.py tests/test_chart_refresh.py -q
python -m pytest tests/test_compare.py -q
```

Then run chart/frontend regressions:

```bash
python -m pytest \
  tests/test_chart_speed.py \
  tests/test_prev_close.py \
  tests/test_price_diff.py \
  tests/test_chart_axis.py \
  tests/test_web_refresh_wiring.py -q
```

If Node is available, run:

```bash
node --check static/js/common.js
node --check static/js/main.js
node --check static/js/stock.js
```

### 6.2 Full suite

The lead agent runs:

```bash
source .venv/bin/activate
python -m pytest
```

Do not report the feature complete unless the full suite passes.

### 6.3 Browser GUI gate

After pytest is green, stop and ask the user to verify all items below.

Dashboard:

- Initial load has no comparison chips or bottom readout.
- Add S&P 500: chart switches to Performance, date-only floating tooltip
  appears on hover, and bottom entries show marker + percentage + name.
- Hover early and late dates: every bottom percentage updates to that date.
- Move away from the chart: bottom percentages return to latest values.
- Switch to Value: overlays and bottom readout disappear.
- Switch back to Performance: active page-local comparisons reappear.
- Navigate to another page and return: comparisons are gone.
- Use browser Back: comparisons are gone even if the page came from BFCache.

Stock page:

- Initial load is raw price with no bottom readout.
- Add a comparison: primary and comparison normalize; tooltip contains only the
  date; bottom readout includes both lines.
- Marker colors match their lines in light and dark themes.
- Remove all chips: bottom readout disappears and raw price tooltip,
  previous-close line, and price-difference measurement return.
- Navigate to a second stock: no comparison carries over.
- Reload: no comparison carries over.

Responsive/accessibility:

- On a narrow phone viewport, entries wrap without clipping.
- Percentage remains directly beside its marker.
- Keyboard focus and picker operation remain usable.
- Readout updates do not steal focus.

## Scope Limits

- No persistence option or preference toggle.
- No new endpoint, database schema, or market-data cache.
- No database changes.
- No configurable legend ordering.
- No absolute price/value in the bottom readout during comparison mode.
- No new chart library or dependency.
- No commit or push until browser approval and explicit user permission.

## Handoff Notes

- The current worktree also contains untracked `comparison.html` and
  `ui-nomenclature-audit.html`. They are unrelated user files. Do not edit,
  delete, stage, or commit them.
- Existing comparison implementation files are already modified but uncommitted.
  Work with those changes; do not revert them.
- Keep the smallest correct diff. This refinement is primarily in
  `common.js`, two templates, CSS, two page wiring files, and frontend tests.
