# Feature: Chart restyle (Option A — restyle Chart.js in place)

## What & why

The user dislikes the current chart's look and hover interaction on BOTH pages
(dashboard portfolio chart + stock detail chart — both come from the ONE shared
factory `setupTimeframeChart` in `static/js/common.js`). The eyesores:

- `pointRadius: 3` paints a dot on EVERY data point (fuzzy line on MAX)
- `tension: 0.3` curves the line — reads as "smoothed", not real data
- Flat rgba fill wash, dark-ish grid, default Chart.js tooltip (colored
  square box that only snaps to dots)

Chosen direction: **Option A now, Option B (TradingView lightweight-charts)
later if the user still dislikes it.** Plan approved by user; line flips
red/green by direction (Google Finance's signature look).

Note: the SELL-aggregates feature plan that was in this file turned out to be
already implemented and committed (81b7399; its tests exist and pass).

## Scope — frontend-only

| File | Change |
|---|---|
| `static/js/common.js` | ONLY the chart section: dataset config, direction colors, gradient fill, interaction + tooltip config, crosshair plugin, and a direction-color update in `refresh()`. Factory signature unchanged → `main.js` / `stock.js` untouched. |
| `static/style.css` | None expected. |
| Backend | None. |

## Concrete changes (common.js)

1. `pointRadius: 0` (no dots), `pointHoverRadius: 4` (dot only under cursor)
2. `tension: 0` — straight segments
3. Scriptable `backgroundColor`: canvas linear gradient from the line color
   (top) to transparent (chart bottom) — replaces the flat fill
4. Direction colors mirroring the CSS palette (`--green-pos: #137333`,
   `--red-neg: #c5221f`): `refresh()` compares first vs last value and sets
   `borderColor` + the gradient base; empty data keeps the previous color
5. Softer y-grid (`#f1f3f4`), borderless axes, x `maxTicksLimit: 8` +
   `maxRotation: 0`, y `maxTicksLimit: 6`
6. `interaction: { mode: "index", intersect: false }` — hover follows the
   cursor anywhere, snaps to the nearest x point
7. Tooltip restyle: `displayColors: false` (no colored square), dark rounded
   pill, date title, price body via `formatPrice` (frontend-only formatting
   rule holds)
8. ~15-line chart-local crosshair plugin: vertical line at the hovered point
   (afterDatasetsDraw, from the active tooltip element)

## Contracts checked

- Factory input/output contract `{canvas, buttonBar, datasetLabel, endpoint,
  defaultPeriod}` → `{chart, refresh}`: UNCHANGED (callers untouched).
- Formatting frontend-only: tooltip price goes through `formatPrice`.
- Timeframe buttons / `PERIOD_MAP` / endpoints: untouched.
- Chart.js stays the `chart.js@4` CDN script in `base.html` (no dep change).

## Test plan

Frontend-only visual change — pytest cannot judge chart pixels and the
backend is untouched, so there are NO new pytest tests (the tests-first rule
collapses here by design). Verification:

1. Full `python -m pytest` stays green as the regression guard.
2. GUI gate (the real test): user checks BOTH pages — every timeframe button
   (1D–MAX), the hover readout + crosshair, red/green coloring, gradient fill.

## Steps

1. Restyle `setupTimeframeChart` in `common.js`.
2. Full `python -m pytest` green.
3. GUI gate → then, if the user still dislikes the chart, plan the Option B
   swap (lightweight-charts). Commit gate: explicit yes only.