# Feature: Richer stock detail stats grid (11 cheap fields)

## What & why

The stock detail page's stats grid shows 7 fields today. The route it reads
from (`/api/stock/<symbol>/stats` → `get_stats`) already fetches Yahoo's
heaviest endpoint, `Ticker.info`, but extracts only 8 keys from the ~50+ the
profile carries. Surfacing more fields is therefore nearly FREE: the network
call already happens, we just read more keys out of the same dict.

User-approved scope: **all 11 fields** (both the "very high value" valuation
set AND the "high value context" set).

## Fields added (7 → 18 cells)

| New backend key | Yahoo `.info` key | Display | Format |
|---|---|---|---|
| `pe_ratio` | `trailingPE` | 25.43 | `formatNumber` |
| `eps` | `trailingEps` | 6.10 | `formatPrice` |
| `dividend_yield` | `dividendYield` | 0.33% (pass-through) | `formatNumber` + "%" |
| `beta` | `beta` | 1.20 | `formatNumber` |
| `fifty_day_average` | `fiftyDayAverage` | 228.40 | `formatPrice` |
| `two_hundred_day_average` | `twoHundredDayAverage` | 210.15 | `formatPrice` |
| `avg_volume` | `avgVolume10days` | 42,000,000 | `integerFormat` |
| `target_price` | `targetMeanPrice` | 260.00 | `formatPrice` |
| `recommendation` | `recommendationKey` | Buy | text, title-cased |
| `sector` | `sector` | Technology | text |
| `industry` | `industry` | Consumer Electronics | text |

Grid order after the existing Market Cap: P/E, EPS, Div Yield, Beta,
50-Day Avg, 200-Day Avg, Avg Volume, Analyst Target, Rating, Sector, Industry.

### The one unit gotcha: dividend yield is ALREADY a percent
Initial assumption (a fraction needing ×100) was WRONG — caught live in the
GUI at CM.TO showing 263%. Verified across CM.TO / RY.TO / AAPL / VZ (Sep
2026): `Ticker.info["dividendYield"]` ships as a percent (2.63, 0.33, 5.59),
each matching `dividendRate / currentPrice`. So `get_stats` passes it through
VERBATIM and the frontend appends "%". No scaling anywhere.

### `recommendation` display
Yahoo sends lowercase keys, sometimes camelCase ("strongBuy"). A 2-line
title-caser in stock.js splits on the camelCase boundary + capitalizes:
"strongBuy" → "Strong Buy". Unknown values fall through as before.

## Files

| File | Change |
|---|---|
| `market_data.py` | `get_stats()`: add 11 `.get()` extractions (`dividend_yield` VERBATIM — Yahoo already ships it as a percent), update docstring. Same None-gap-fill convention. |
| `templates/stock.html` | 11 new `<div class="stat">` cells in the `<dl class="stats-grid">`. |
| `static/js/stock.js` | `paintStats`: map the 11 ids; `STAT_IDS`: add the 11 ids (failure path degrades whole grid still). |
| `static/style.css` | EXPECTED no change — 4-col grid absorbs 18 cells; mobile 2-col = exactly 9 rows. |
| `tests/test_market_data.py` | get_stats tests for the new keys. |
| `tests/test_stock.py` | extend the stats pass-through test's dict. |

## Contracts checked

- Stats endpoint is a pure pass-through; new keys ride the SAME payload —
  no route change, no new endpoint, no extra API call.
- None-gap-fill holds: absent fields → None → "—" (indices show "—" for most
  of these; an unprofitable company has no P/E).
- `get_name` shares `Ticker.info` and is untouched (name cache unchanged).
- Formatting stays frontend-only except the dividend unit normalization.
- Nothing touches PERIOD_MAP, quote cache, ledger math, or the chart.

## Test plan (tests-first)

`tests/test_market_data.py`:
1. Extend `test_get_stats_extracts_and_renames_the_grid_fields` with all 11
   Yahoo keys → asserts the full 18-key naming contract.
2. New `test_get_stats_dividend_yield_is_a_percent_pass_through`:
   `dividendYield: 0.33` → `dividend_yield == 0.33` (pins pass-through, the
   anti-263% regression guard); absent → None.
3. Extend `test_get_stats_missing_fields_become_none`: assert all 11 new keys
   are None too.

`tests/test_stock.py`:
4. Extend `test_stock_stats_returned_untouched`'s fake dict with all 11 keys —
   the existing `body == fake_market.stats["AAPL"]` assertion then locks the
   route pass-through for the new fields.

## Steps

1. ✅ Plan approved (see above).
2. Tests first: edits 1–4 above → run scoped → they FAIL (keys absent).
3. Implement: `get_stats` → template cells → `paintStats` + `STAT_IDS`.
4. Full `python -m pytest` green.
5. GUI gate: check AAPL (dividend payer, all fields populated), a non-yield /
   unprofitable ticker (some "—"), and ^GSPC (most "—"). Check 2-col mobile.
6. Commit gate: explicit yes only.