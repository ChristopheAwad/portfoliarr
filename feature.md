# Feature #9: Dashboard Period Return Readout

## Status

IMPLEMENTED 2026-09-21. All 708 tests pass and the user approved the dashboard
GUI, including the final grouped label/value alignment. Roadmap item #9 ships
with this PR.

This plan replaces the stale allocation-donut handoff that shipped in PR #62.

## Problem

The dashboard header always shows two portfolio changes:

- `Today`, calculated from live quote changes relative to previous close; and
- `Total`, calculated from current value relative to net cost basis.

The chart can display 1D, 5D, 1M, 3M, 6M, YTD, 1Y, 5Y, or MAX, but the page
does not show the portfolio return for the selected chart period. Changing the
timeframe therefore changes the line without providing a concise result for
that period.

Replacing `Today` is not correct. It would remove a useful live fact, and the
chart's 1D span starts at its first available intraday bar rather than at the
previous close used by the live daily calculation. Adding a third hero pill is
also not desirable because it crowds the headline on mobile and mixes a
chart-specific metric with the live summary facts.

Calculating `last portfolio value - first portfolio value` is not an honest
investment return. A buy can make the value line rise without investment
performance, and a sell can make it fall. The history endpoint already returns
`twrr_pct`, a time-weighted return that removes those cash flows.

## Goal

Add one quiet, period-aware return readout directly above the dashboard chart.
It must:

- keep the header's `Today`, `Total`, and cost-basis facts unchanged;
- show the selected chart period, for example `5D return`;
- show the history endpoint's cash-flow-neutral `twrr_pct`;
- explain the metric with `Deposits and withdrawals excluded`;
- update only when matching chart data successfully becomes visible;
- remain correct through cached loads, rapid period changes, failed requests,
  chart mode changes, comparison changes, and mobile-tab recovery; and
- degrade to `Return unavailable` when the selected response cannot define a
  return.

## Approved Design

The readout is part of the chart card, not the portfolio hero:

```text
5D return                         +2.14%
Deposits and withdrawals excluded

┌─────────────────────────────────────────┐
│               chart                     │
└─────────────────────────────────────────┘
 Value  Performance
 1D  5D  1M  3M  6M  YTD  1Y  5Y  MAX
```

Design rules:

1. Keep the established typefaces, spacing system, and light/dark palettes.
2. Use an unboxed, left-aligned text treatment. Do not add a card, pill, icon,
   border, gradient, or decorative label.
3. Use tabular numerals for the percentage.
4. Use the existing `--green-pos` and `--red-neg` tokens for finite results.
5. Keep the explanatory sentence in `--text-secondary` and visually quieter
   than the result.
6. Let the row wrap or stack deliberately on narrow screens. It must not cause
   horizontal page overflow.
7. Use plain sentence case. Do not expose `TWR` as unexplained jargon in the
   visible interface.

## Locked Product Decisions

1. The portfolio header keeps its current `Today` and `Total` pills.
2. The ledger keeps `Day Gain` and `Day %`; this feature does not alter ledger
   columns, group math, sorting, or the 11-column contract.
3. The displayed result is always `twrr_pct` from
   `GET /api/portfolio/history`, not a first-to-last value delta.
4. The result remains TWR in both Value and Performance chart modes. Changing
   chart mode must not change the period result or its wording.
5. The readout describes the portfolio only. Comparison overlays do not alter
   it, average into it, or replace it.
6. `1D` is labeled `1D return`, not `Today`, because its chart span is not the
   live quote's previous-close span.
7. `MAX` means the available portfolio chart history, which starts at the
   earliest logged transaction under the existing backend contract.
8. Finite values show an explicit sign and two decimal places:
   `+2.14%`, `-2.14%`, and `+0.00%`.
9. Zero uses the positive color, matching existing gain/change presentation.
10. Null, missing, non-finite, empty, or otherwise non-computable results show
    `Return unavailable`, with no positive or negative class.
11. Privacy mode leaves this percentage visible, matching the current behavior
    of the header's percentage portions. The readout contains no dollar value.
12. No endpoint, database, market-data, cache-TTL, or response-shape change is
    needed. The backend already computes and tests `twrr_pct`.

## Existing Contracts To Preserve

1. `PERIOD_MAP` remains the only timeframe source.
2. `/api/portfolio/history` retains
   `{labels, values, costs, index_values, twrr_pct}` plus optional benchmarks.
3. `index_values` may be null or shorter than labels. `twrr_pct` is null exactly
   when the backend cannot compute it.
4. Value mode continues to plot `values`; Performance mode continues to plot
   `index_values`.
5. Dashboard comparisons remain visible only in Performance mode.
6. Stock-detail chart behavior remains unchanged. Its existing
   `onPeriodData` callback continues to calculate one stock's first-to-last
   price return.
7. A silent chart prefetch warms the cache without painting any visible state.
8. Only the latest visible request can paint after A -> B or A -> B -> A races.
9. The active timeframe button describes data that successfully reached the
   canvas. A failed later request leaves the old chart and old button intact.
10. Frontend cache keys continue to include the period and ordered comparison
    list.
11. Reconnect and foreground recovery continue to retry `requestedPeriod`.
12. Chart mode swaps continue to repaint from `lastReply` without fetching.
13. Backend raw floats remain unformatted; all percentage formatting stays in
    frontend code.
14. Privacy state remains the localStorage string under `hidePortfolio`, with
    `data-hidden` as the painter source of truth.
15. The comparison readout under the chart remains unchanged.

## Files

Planned production changes:

- `templates/index.html`
- `static/js/common.js`
- `static/js/main.js`
- `static/style.css`

Planned tests:

- add `tests/test_period_return_ui.py`
- update another focused test only if an existing helper contract makes that
  more precise than duplicating it

Planning/status files:

- `feature.md`
- `roadmap.md`

No changes are planned for `app.py`, `market_data.py`, `db.py`, ledger files,
stock-detail files, Android files, dependencies, or deployment files.

## Test-First Plan

Create `tests/test_period_return_ui.py` before production edits. Follow the
repository's existing source/meta-test style because pytest does not execute a
browser JavaScript runtime. Read rendered HTML through the Flask `client` when
the test concerns server output; read source files only for JS/CSS contracts.

### A. Template Structure And Copy

1. Request `/` and assert a period-return container exists.
2. Assert the container includes stable JS hooks for:
   - the changing period label; and
   - the changing return value.
3. Assert the readout appears before `.chart-box` / `#portfolioChart` in the
   dashboard chart card.
4. Assert the visible explanatory copy is exactly
   `Deposits and withdrawals excluded`.
5. Assert the container has `aria-live="polite"` so an asynchronously loaded
   period is announced without interrupting the user.
6. Assert the readout is dashboard-only and does not appear on `/stock/AAPL` or
   `/ledger`.
7. Assert no extra dashboard hero pill is added and the existing
   `portfolio-day-change` and `portfolio-total-return` hooks remain present.

### B. Shared Chart Callback Wiring

Add a new optional callback to `setupTimeframeChart`; use a distinct name such
as `onPeriodSummary`. Do not overload or change the stock page's existing
`onPeriodData` semantics.

Tests must lock these behaviors:

1. The factory destructures the optional callback.
2. A successful visible `paint(data, period)` calls it with:
   - the exact period that is being painted; and
   - `data.twrr_pct` only when it is finite, otherwise `null`.
3. The callback is reached from `paint`, after stale-request guards and before
   or with the successful visible state update. It must never run directly from
   a timeframe click.
4. Silent prefetches return before `paint`, so they cannot update the readout.
5. Stale visible responses return before `paint`, so they cannot update it.
6. A successful response with empty labels or null `twrr_pct` still calls the
   summary callback with `null`; unavailable is a valid painted state, not a
   reason to preserve a stale number.
7. A mode-only repaint from `lastReply` can call the callback again with the
   same period/result; it must not derive a different value from the active
   mode.
8. A comparison reload can call the callback from its matching response, but it
   still passes only the portfolio's `data.twrr_pct`.
9. The existing `onPeriodData` callback and its finite primary endpoint payload
   remain intact for the stock page.

### C. Failure And Recovery State

The initial request and later-request cases must differ:

1. Track whether any reply has painted by using the existing `lastReply` state;
   do not create a second competing source of chart readiness.
2. If the initial visible request fails while `lastReply` is null, call the new
   summary callback with the requested period and `null`. This replaces an
   endless loading appearance with `Return unavailable`.
3. If a later visible request fails after a prior reply painted, do not call the
   summary callback. Preserve the existing readout because the old chart and
   active button are also preserved.
4. A later reconnect, foreground recovery, or successful retry paints and
   replaces the unavailable state through the normal callback.
5. Silent prefetch failure must never affect the visible readout, including on
   first load.
6. Add source-order assertions that make the initial-failure callback subject
   to the same visible request generation guard. An old failed request must not
   overwrite a newer successful result with unavailable.

### D. Dashboard Painter

Tests must lock a small dashboard-only painter in `static/js/main.js`:

1. The dashboard passes the new callback to `setupTimeframeChart`.
2. The period label is rendered as `${period} return` without special-casing
   `1D` to `Today`.
3. A finite positive value renders `+N.NN%` and adds `pos` while removing
   `neg`.
4. A finite negative value renders `-N.NN%` and adds `neg` while removing
   `pos`.
5. Zero renders `+0.00%` and uses `pos`.
6. Null and non-finite values render `Return unavailable` and remove both sign
   classes.
7. The painter does not calculate `(lastValue - firstValue) / firstValue`.
8. The painter does not inspect chart mode, benchmark datasets, costs, summary
   data, or live quote data.
9. The period return elements are not added to the privacy geometry-lock target
   list and are not replaced with `****`.
10. The summary poll does not own or overwrite the period return.

### E. Styling And Responsive Behavior

Tests must assert focused CSS contracts without over-locking exact decoration:

1. The readout selector exists and uses a simple flex or grid layout.
2. The result uses `font-variant-numeric: tabular-nums`.
3. Positive and negative states use `var(--green-pos)` and
   `var(--red-neg)`.
4. The explanatory text uses `var(--text-secondary)`.
5. The base readout does not add a background, border, box-shadow, or pill-like
   radius.
6. A `@media (max-width: 600px)` rule gives the readout a deliberate narrow
   layout that can stack or wrap without fixed viewport widths.
7. The mobile rule does not use `100vw` or hidden overflow as a workaround.
8. Existing comparison-readout and chart-control mobile rules remain intact.

### F. Existing Backend Coverage

Do not duplicate the complete TWR calculation suite. Confirm that the existing
`tests/test_twrr.py` coverage remains green for:

- empty and fewer-than-two-bar histories;
- deposits and withdrawals;
- buys and sells on bars;
- null/unpriceable cases;
- truncation at non-positive bases;
- pending flow timing; and
- finite positive, negative, and zero returns.

Add backend tests only if implementation reveals an untested API contract. A
frontend-only readout must not trigger speculative backend refactoring.

## Implementation Plan

Implementation starts only after the tests above fail for the intended missing
behavior.

### 1. Add The Dashboard Markup

In `templates/index.html`:

1. Inside `.chart-card`, insert the readout immediately before `.chart-box`.
2. Use one semantic container with `aria-live="polite"`.
3. Add a label span with a stable id, initially describing the default period
   as `5D return`.
4. Add an empty value span with a stable id. The browser painter owns its
   content; do not ship a mock return.
5. Add the fixed explanatory sentence in a secondary text element.
6. Keep the canvas, comparison readout, mode tray, timeframe tray, and compare
   picker in their current relative order.

### 2. Extend The Shared Chart Factory

In `static/js/common.js`:

1. Add optional `onPeriodSummary` to the `setupTimeframeChart` options.
2. Keep `onPeriodData` unchanged for stock-detail consumers.
3. In `paint(data, period)`, normalize the summary value with
   `Number.isFinite(data.twrr_pct) ? data.twrr_pct : null`.
4. Invoke `onPeriodSummary({period, returnPct})` for every successful visible
   paint, including a valid unavailable result.
5. Do not derive this callback from `plotValues`; `index_values` can truncate,
   and the backend's `twrr_pct` is the authority for the same covered span.
6. Ensure silent prefetch and stale-generation exits remain before `paint`.
7. In `refresh`'s catch path, report `{period, returnPct: null}` only when:
   - the request is visible;
   - it is still the latest visible generation; and
   - `lastReply` is null.
8. Preserve an existing readout after a later failure, matching the preserved
   chart and selected timeframe button.
9. Do not change cache policy, request URLs, generation counters, button sync,
   recovery listeners, or returned chart-handle methods.

### 3. Add The Dashboard Painter

In `static/js/main.js`:

1. Query the two new element ids once near the dashboard chart setup.
2. Define a small painter that accepts `{period, returnPct}`.
3. Always update the label to `${period} return` for the state being painted.
4. For a finite value:
   - use `toFixed(2)`;
   - prepend `+` when the value is zero or positive;
   - append `%`;
   - apply exactly one of `pos` or `neg`.
5. For an unavailable value:
   - render `Return unavailable`;
   - remove both sign classes.
6. Pass the painter as `onPeriodSummary` in the dashboard's existing
   `setupTimeframeChart` call.
7. Do not add the readout to `lastPortfolioPaint`, `applyPortfolioPrivacy`,
   `clearPortfolioGeometryLocks`, or `refreshPortfolioSummary`.

### 4. Style The Readout

In `static/style.css`:

1. Add a compact top-of-card readout style before the chart canvas rules.
2. Align the period label and result on a clear shared baseline.
3. Give the result modest emphasis rather than hero-size typography.
4. Put the explanation on a quiet secondary line.
5. Reuse the existing sign-color tokens and tabular-number convention.
6. Add a narrow-screen rule in the established final mobile section so the
   label/result and explanation fit without clipping.
7. Do not move or redesign the Value/Performance and timeframe controls.

### 5. Keep Documentation Accurate

Code comments must explain only non-obvious contracts:

- why TWR is used instead of first-to-last portfolio value;
- why initial failure becomes unavailable but later failure preserves the old
  result; and
- why `1D return` is not called `Today`.

Do not add comments that restate assignments or CSS declarations.

## Focused Verification

Run these commands after implementation:

```bash
source .venv/bin/activate
python -m pytest tests/test_period_return_ui.py
python -m pytest tests/test_chart_refresh.py tests/test_chart_recovery.py tests/test_compare_ui.py
python -m pytest tests/test_twrr.py tests/test_privacy_toggles.py tests/test_ui_revamp.py
```

Resolve every failure without weakening unrelated contracts.

## Full Verification

The lead agent must run:

```bash
source .venv/bin/activate
python -m pytest
```

No implementation is complete until the full suite passes.

## Browser GUI Approval Checklist

After pytest passes, stop and ask the user to inspect the browser. Do not commit
or push before this approval.

The browser check must cover:

1. Desktop light mode: the readout is above the chart and visually quiet.
2. Desktop dark mode: text and green/red results have clear contrast.
3. Mobile width: no horizontal page overflow, clipped copy, or collision with
   the chart.
4. Default load: `5D return` matches the default 5D chart.
5. Every timeframe: label and return update together after the chart loads.
6. Rapid 1M -> 1Y -> 1M clicks: only the final successfully painted chart and
   return are shown.
7. Value/Performance switching: return stays the same while the line mode
   changes.
8. Add/remove comparison overlays: the portfolio return stays correct and the
   existing comparison readout remains usable.
9. Privacy on/off: the period percentage remains visible and no hero layout
   shift is introduced.
10. Empty or non-computable portfolio history: `Return unavailable` appears
    without green/red styling.
11. Temporary failed period request after a valid chart: the prior chart,
    selected button, and readout remain paired.
12. Reconnect or return from a hidden tab: a successful retry updates the
    readout with the recovered chart.

## Completion Gates

1. Detailed plan written and roadmap item pulled: this document.
2. User approves this plan before implementation.
3. Failing tests are written first.
4. Production code is implemented.
5. Focused tests pass.
6. Full `python -m pytest` passes.
7. User approves the browser GUI.
8. Only then ask whether to commit and push.
9. Mark roadmap item #9 shipped only in the approved commit, with the required
   date and PR number or direct-main date.

## Definition Of Done

The feature is complete when the dashboard keeps its stable live summary,
shows an honest cash-flow-neutral return for the successfully displayed chart
period, preserves request-order correctness and graceful failure behavior,
fits desktop and mobile in both themes, passes the full test suite, and has the
user's browser approval.
