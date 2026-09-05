# Feature: Faster chart loading (dashboard 5Y/MAX)

User report: the dashboard portfolio chart is slow on 5Y and MAX. Root causes
found while reading the code:

1. `get_history` hits Yahoo on EVERY click — no cache (quotes have one; history doesn't).
2. `/api/portfolio/history` fetches tickers SERIALLY — time = sum of all Yahoo calls.
3. MAX fetches every daily bar since IPO (^GSPC → ~25k points); 5Y ~1,260 daily bars.

User decisions: dashboard is the pain point (fix helps both pages anyway);
5Y → weekly bars, MAX → monthly bars (daily kept for 1D–1Y).

## Plan

1. **PERIOD_MAP** (market_data.py): `5Y: interval "1wk"`, `MAX: interval "1mo"`.
2. **Label fix**: `get_history` gives date labels only when interval == "1d";
   flip to "date labels for everything except intraday". The only intraday
   interval is "5m", so the check becomes `interval == "5m"` for time labels.
   Same flip for the route's `is_intraday` check (app.py) — it must treat
   1wk/1mo as daily-shaped (transactions applied per date, axis trimmed at
   first_tx_date).
3. **History cache** in market_data.py: `{(symbol, period_key): {"data": dict,
   "fetched_at": epoch}}`. TTL: 600s for daily/weekly/monthly (history is
   settled), 120s for 1D (today's bar keeps moving). Cache successes only —
   a failed fetch is never cached. `clear_history_cache()` helper for tests.
4. **Parallel fetch** in `/api/portfolio/history`: ThreadPoolExecutor over the
   unique tickers, keeping the exact contract — per-ticker try/except, warn
   log with exc_info, `{}` on failure, successes stored in `histories`.

## Known accepted behavior

Weekly/monthly bars are coarser: a mid-period buy enters the line at the
NEXT bar (a mid-August buy appears at September's bar on MAX). Same
"next trading day" approximation already used for weekend buys, just coarser.
Long-horizon cosmetic shift, accepted by user.

## Test plan (written FIRST, must fail until implemented)

New file `tests/test_chart_speed.py`:

- autouse fixture calls `clear_history_cache()` before each test (no leakage).
- **cache**: with a counting fake `yf.Ticker`, two identical `get_history`
  calls → exactly ONE network fetch, same result both times.
- **TTL**: second call after monkeypatched `time.time() + 601` → refetches.
- **1D TTL**: 1D entries go stale after 121s (shorter TTL), not after 601s.
- **no cache on failure**: fake raises → first call raises, cache stays
  empty; a second (working) fake → real fetch happens.
- **cache key includes period**: same symbol, "5D" then "1M" → two fetches.
- **weekly labels are dates**: fake yf returns 1wk bars → labels match
  "YYYY-MM-DD", not "HH:MM".
- **monthly labels are dates**: same for "1mo".
- **portfolio route treats 5Y as daily-shaped**: end-to-end — a transaction
  dated before some weekly bars trims the axis at first_tx_date (labels are
  dates, pre-first-buy bars dropped).
- **parallel fetch**: fake `app.get_history` that blocks on a
  `threading.Barrier(2)` for two tickers — serial execution would deadlock
  (pytest-timeout / the test fails), parallel passes.
- **parallel failure isolation**: one ticker's fake raises, other succeeds →
  route still 200, failed ticker contributes 0 (contract unchanged).

Existing suite must stay green (fake_market patches app.get_history, so the
cache is invisible there).

## Status

- [x] Plan approved by user
- [x] Tests written & failing (7 failed, 3 regression locks passed — as designed)
- [x] Implemented
- [x] Full suite green: 223 passed
- [x] GUI check by user (dashboard + stock page, 2026-09-05)
- [x] Commit decision (review nits addressed, squash-merging into main)

## Notes from implementation (things the tests caught)

- Test-side arithmetic slips fixed: monthly bars carry their own date as
  the label (no first-of-month normalization); the parallel test's first
  bar only includes that bar's transactions (1320 = 12 × 110), the 08-31
  buys land on the 08-31 bar (2400 = 20 × 120).
- REAL leak found by the full suite: any test running the real
  get_history (test_routes' NaN regression caches ("META","5D")) could
  poison a later file's identical lookup (test_stock's META test). Fix:
  suite-wide autouse `fresh_history_cache` fixture in conftest.py — the
  one place that covers every file, present and future.
