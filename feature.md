# Feature: x-axis label cleanup — uncrowd the chart ticks

Status: plan approved by user ("shortened + 5D day labels" + the unified
year-span rule). Next step: write the failing tests.

## Test plan (write FIRST — locks the JS contract pytest can't execute)

New file `tests/test_chart_axis.py` — string-check meta-tests in the
house style of `tests/test_ledger_css.py` / `tests/test_docker.py`.
pytest cannot run a browser or JavaScript, so the tests assert the exact
needles that keep the contract honest in BOTH directions (right things
present, wrong things absent).

Scope helper `x_scale_body()` slices the `x: { ... }` block out of
`common.js` (from the `x: {` after `scales:` to the following `y: {`)
so y-axis config never bleeds in — the y-scale KEEPS its own
`maxTicksLimit: 6` (short price labels never crowded).

1. `test_x_axis_never_rotates_labels` — x body contains `maxRotation: 0`.
   (LOCK test: green before AND after — the old config already had it.)
2. `test_x_axis_paints_precomputed_labels` — x body contains
   `autoSkip: false` AND the callback expression
   `xTickLabels[index] || ""` (wiring + hidden-tick default in one
   needle). FAILS first.
3. `test_old_tick_limit_removed_from_x_axis` — x body does NOT contain
   `maxTicksLimit`. FAILS first.
4. `test_label_formatter_contract` — common.js contains
   `function buildXTickLabels`, `const MONTHS`, and `spansYears`.
   FAILS first.

Run scoped (`python -m pytest tests/test_chart_axis.py`) to prove the
failure, again after implementation to prove the pass.

## Design (user-approved)

Problem: both charts crowd their x-axis — `maxTicksLimit: 8`
(`common.js:693`) with the backend's full ISO labels painted verbatim
("2026-09-04 14:30" × 8 on 5D is 16-character noise).

Rule: display-time reformatting ONLY, inside the shared chart factory
(`setupTimeframeChart` in `static/js/common.js`) so both pages inherit
it. The backend label formats are load-bearing (dict keys for the
portfolio merge, lexicographic sorting, transaction-date comparisons in
`app.py`) and must not change. Matches the app's iron rule: backend
sends raw data, browser formats.

### Label spec — keyed on the DATA, not the period button

| Data window | Axis shows | ~count |
|---|---|---|
| 1D (`HH:MM`) | `09:30` unchanged, sparse | ~5 |
| 5D (`YYYY-MM-DD HH:MM`) | month+day at each day's FIRST bar (`Sep 3`, `Sep 4`); `""` elsewhere | ~5 |
| daily bars, one calendar year | `Sep 4` | ~6 |
| daily bars spanning ≥2 calendar years | `Sep 2025` (no day; tooltip keeps the exact date) | ~6 |

Unified data-driven rule: compare the first and last parseable labels'
years (`spansYears`). 1Y/5Y/MAX always span; 3M/6M/1M flip automatically
across New Year. 5D across New Year still reads `Dec 30, Jan 2` —
month+day is unambiguous in a 5-day window.

### Mechanics (all in common.js)

- Top-level pure helper `buildXTickLabels(labels)` (placed between
  `crosshairPlugin` and `setupTimeframeChart`) → parallel array of axis
  text, `""` = hidden. Per-label shape detection by fixed anchored
  regexes (datetime / date; anything else falls to pass-through).
  Series shapes are homogeneous by construction (one PERIOD_MAP format
  per request) but dispatch is defensive: unparseable labels pass
  through raw, never crash the chart.
- Sparse placement: `stridedIndices(count)` — stride = ceil(count ÷ 6),
  index 0 always, last index forced in only when ≥ half a stride from
  the previous pick (keeps 1D's freshest time visible without
  right-edge crowding). 5D uses day boundaries instead of stride,
  thinned only if boundaries ever exceed 6 (defensive).
- x-scale: keep `maxRotation: 0`, set `autoSkip: false`, REMOVE
  `maxTicksLimit`; callback `(value, index) => xTickLabels[index] || ""`.
  With grid and border already hidden, empty strings paint nothing, so
  text lands exactly on chosen bars. y-scale untouched.
- Closure variable `xTickLabels` in `setupTimeframeChart`; `refresh()`
  rebuilds it BEFORE `chart.update()` (the callback reads it at draw
  time, so it must describe the NEW series).
- Tooltips untouched — full raw label on hover.

### Files touched

- `static/js/common.js` (only production file)
- `tests/test_chart_axis.py` (new)

## Steps

1. ✅ Plan approved (two question rounds + go-ahead).
2. Write `tests/test_chart_axis.py` → scoped run proves failure.
3. Implement the common.js changes (house-style teaching comments).
4. Full `python -m pytest` green.
5. GUI gate: user checks dashboard + stock page across 1D/5D/1M/1Y/MAX
   (1Y/5Y/MAX exercise the `Sep 2025` branch — no waiting for January).
6. Commit gate: explicit user yes before any git action.
