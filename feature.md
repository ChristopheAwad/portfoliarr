# Feature: Multi-dimension allocation donut (arrow-carousel)

## What

The dashboard's allocation donut only answers "what % is each TICKER?".
We want the same circle sliced by everything Yahoo can classify: sector,
industry, country, asset type, exchange, market-cap bucket, and currency.
One donut, **8 views**, flipped with `‹ ›` arrows in the card header (+
touch-swipe on the donut box for phones):

    By Ticker → By Sector → By Industry → By Country → By Type
              → By Exchange → By Cap Bucket → By Currency

User-approved decisions from the brainstorm:

- **All seven dimensions** (plus the existing By Ticker view).
- **Arrow/swipe carousel** — a new UI pattern; the sidebar is too narrow
  for seven tabs and stacked donuts double the page height.
- **Exclude + note for missing metadata** — a ticker Yahoo can't classify
  (crypto has no sector) is EXCLUDED from that view's wedges and listed
  in a note under the donut ("Excludes BTC-USD — no sector data"), never
  fabricated into an "Unknown" category. Same degradation-never-fabrication
  philosophy as the rest of the app, just with the gap surfaced as text
  instead of a wedge.
- **Out of scope:** look-through ETF holdings (`funds_data`) — a separate
  feature someday.

## Approved design decisions

- **One cached `.info` call per ticker serves six dimensions.**
  `Ticker.info` carries `sector`, `industry`, `country`, `quoteType`,
  `exchange`, and `marketCap` — a new `get_profile()` in `market_data.py`
  caches the whole profile PROCESS-LIFETIME (the `_name_cache` pattern:
  these facts never change). Cost: one slow call per ticker after each
  restart, then free forever. Deliberately a SEPARATE cache from
  `_name_cache` (get_name RAISES when no name exists — a profile must not
  inherit that rule; missing FIELDS are fine, missing DATA is not).
- **One endpoint, whitelist-validated `by` param** (the `PERIOD_MAP`
  pattern): `GET /api/portfolio/allocation?by=sector|industry|country|
  type|exchange|cap|currency`, bad key → 400 listing the valid options.
  `ticker` is deliberately NOT a valid `by` — that view is already served
  by the summary's `holdings` slice; two sources for one view would drift.
- **Same holdings math as the summary, always**: net-qty fold, parallel
  quotes, live USDCAD rate, LONG-ONLY wedges (a short is a bet against,
  not an allocation), priced-only (an unpriced ticker is in no slice and
  no denominator — a weight over a phantom denominator misstates every
  holding that DID price). Backend computes, frontend paints — raw floats.
- **Cap buckets are CAD-consistent**: `marketCap` is native-currency, so
  USD caps convert at the LIVE rate before bucketing. Thresholds (CAD):
  Large ≥ $10B, Mid $2–10B, Small < $2B; missing `marketCap` → excluded
  with reason.
- **The 60s poll refreshes only the ACTIVE dimension.** The others'
  payloads sit in a small per-dimension JS cache; an arrow flip paints the
  cached view instantly and refetches in the background if stale. The
  allocation endpoint reuses `get_quote`, so the summary poll already
  warmed the quote cache — steady-state allocation fetches are nearly free.
- **Privacy eye masks CAD values in tooltips across ALL views** (weights
  stay visible — the same rule the ticker donut already follows).

## Files to touch

| File | Change |
|---|---|
| `market_data.py` | Add `get_profile(symbol)` → `{sector, industry, country, quote_type, exchange, market_cap}` from one `Ticker.info`, process-lifetime cache (`_profile_cache`), missing fields → `None` (the `get_stats` convention), empty profile raises, camelCase→snake_case at this boundary. Add `clear_profile_cache()` (the `clear_history_cache` escape hatch) so tests can't inherit a neighbour's cache. |
| `app.py` | New `GET /api/portfolio/allocation` route: validate `by` against an `ALLOCATION_DIMENSIONS` whitelist dict; aggregation mirrors the summary's math (fold → parallel quotes → live FX → long-only, priced-only); `currency` groups off `quote["currency"]` (zero extra network), the other six consult `get_profile`; `excluded` list carries `{ticker, reason}` for unpriced AND unclassified tickers; weights divide by the sum of slice values only; slices sorted value-desc. Route-layer logging per house style (wide catch, `exc_info=True`, TIER 1 warnings). |
| `templates/index.html` | Donut card header gains `‹ ›` arrow buttons around a current-view label; a note element under the donut for the excluded list. |
| `static/js/main.js` | Generalize `paintAllocation` to arbitrary `{label, value, weight}` slices; `ALLOCATION_VIEWS` array (order + labels, `null` key = ticker view from the summary); localStorage persistence of the last-viewed dimension; arrow + swipe (touchstart/touchend delta on the donut box) handlers with wrap-around; per-dimension payload cache; poll refreshes the ACTIVE dimension only; empty-state variant for "holdings exist but nothing classified"; privacy mask + themechange keep working across all views. |
| `static/css/` (whatever file owns the donut card) | Styles for the arrow buttons (match the existing `.btn-text`/`.tab-btn` aesthetic) and the excluded note. |
| `tests/test_allocation.py` | NEW — the pytest surface below. |
| `tests/test_allocation_ui.py` | NEW — meta-tests locking the template/JS contracts. |
| `project-brief.md` | AFTER the GUI gate: extend the UI Layout line ("Allocation donut chart (% weight per holding)") to mention the switchable views, and record the permanent rule (same-holdings-math + exclude-with-note, never fabricated categories) in Design Rules. |

## Test plan (pytest — written FIRST, failing until the feature exists)

`tests/test_allocation.py` — data layer (`fake_yf` pattern from
test_market_data.py; profile cache cleared per test):

1. `test_get_profile_extracts_and_renames_fields` — one `.info` call → all six snake_case keys.
2. `test_get_profile_missing_fields_become_none` — absent fields are `None`, not errors.
3. `test_get_profile_is_cached_for_process_lifetime` — two calls, ONE `yf.Ticker().info` invocation.
4. `test_get_profile_empty_profile_raises` — empty dict → `ValueError` (never nineteen Nones posing as facts).

Route level (`client` + `fake_market` + `app.get_profile` patched where it's USED):

5. `test_bad_dimension_returns_400_with_options`.
6. `test_ticker_is_not_a_valid_by` — 400 (the summary owns that view).
7. `test_empty_ledger_returns_empty_slices`.
8. `test_sector_grouping_sums_and_sorts` — two tickers in one sector + one in another; weights sum to 1; value-desc.
9. `test_usd_converts_at_live_rate` — a USD holding's slice is CAD-valued.
10. `test_currency_dimension_groups_by_quote_currency` — and never calls `get_profile`.
11. `test_short_position_gets_no_wedge` — value still in no slice (long-only rule).
12. `test_fully_sold_portfolio_has_no_slices`.
13. `test_unpriced_ticker_appears_in_excluded_with_reason` — quote failed.
14. `test_missing_sector_appears_in_excluded_with_reason` — profile fetched, field `None` (e.g. crypto).
15. `test_profile_fetch_failure_excluded_with_reason` — `get_profile` raises for one ticker; the rest still slice.
16. `test_all_unclassified_returns_empty_slices_and_full_excluded_list`.
17. `test_cap_buckets_respect_thresholds` — Large/Mid/Small boundaries + a USD cap converted before bucketing + missing `marketCap` excluded.
18. `test_weights_sum_to_one_over_classified_slices_only` — an excluded ticker's value is NOT in the denominator.
19. `test_slice_values_descending`.

`tests/test_allocation_ui.py` — meta-tests (string checks, the
test_web_refresh_wiring.py pattern):

20. `test_donut_card_has_prev_next_buttons_and_label`.
21. `test_main_js_defines_eight_allocation_views` — the `ALLOCATION_VIEWS` list exists with ticker first.
22. `test_js_dimension_keys_match_backend_whitelist` — imports `app.ALLOCATION_DIMENSIONS` and asserts every key appears in `main.js` (the cross-contract lock).
23. `test_main_js_persists_dimension_to_localstorage`.
24. `test_main_js_wires_swipe_on_donut_box`.
25. `test_excluded_note_element_exists_in_template`.
26. `test_poll_refreshes_active_dimension_only` — the interval callback fetches the allocation endpoint only for the current view.

Full suite (`python -m pytest`) must stay green — existing tests double as
the regression net (especially `test_portfolio_summary.py`, whose math the
route deliberately mirrors, and `test_ui_redesign.py::test_dashboard_has_allocation_donut`).

## Manual GUI gate (user verifies)

1. Donut card shows `‹ By Ticker ›`; arrows cycle through all 8 views and wrap around.
2. Each view paints real slices; sector/industry/etc. all agree with the ticker view's total.
3. A holding with no sector (e.g. BTC-USD) vanishes from By Sector and the note names it; By Currency/By Type still include it.
4. Flip is instant after first fetch; the 60s poll keeps the ACTIVE view fresh.
5. Last-viewed dimension survives a reload.
6. Privacy eye masks tooltip values in every view; theme flip repaints wedges.
7. Phone: swiping the donut flips views.

## Status

- [x] Brainstorm + plan approved (7 dimensions, arrow carousel, exclude+note)
- [x] feature.md written
- [ ] Tests written first (failing)
- [ ] Implementation (backend `get_profile` + route → frontend carousel)
- [ ] Full suite green (`python -m pytest`)
- [ ] GUI gate
- [ ] Commit gate