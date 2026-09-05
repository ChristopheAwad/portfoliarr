# Feature: 5D → 30-minute bars

Follow-up to "Faster chart loading": after 5Y went weekly and MAX went
monthly, 5D (daily, 5 points) became the odd one out — a 5-point zigzag.
User decision: 5D serves 30-minute bars (~65 points, Google Finance's
choice). 1D stays 5m; 1M–MAX unchanged.

## Plan

1. **PERIOD_MAP** (market_data.py): `5D` interval → `"30m"`. Add two
   per-entry flags so code stops keying on magic interval strings:
   - `intraday: True` on 1D ONLY — drives the label shape and the route's
     ledger-math branch (1D = whole position at today's first bar).
   - `live: True` on 1D AND 5D — today's bar is still moving, so TTL 120s;
   everything else `live: False` → settled TTL 600s.
   Flags replace the `interval == "5m"` checks (the same check that
   already bit us once as `!= "1d"` when 5Y/MAX moved off daily bars).
2. **Labels** (get_history): three shapes, keyed off `intraday` + label
   uniqueness needs —
   - 1D (one day): `"HH:MM"` as today.
   - 5D (multi-day intraday): `"YYYY-MM-DD HH:MM"` — plain `"HH:MM"` would
     collide 5× in the `{label: price}` dict and silently drop days.
   - all date-spaced bars: `"YYYY-MM-DD"` as today.
3. **TTL**: `live` flag picks 120s (1D, 5D); 600s for settled bars.
4. **app.py** `is_intraday`: read `PERIOD_MAP[period]["intraday"]` instead
   of `interval == "5m"`. The daily branch needs NO other change — its
   ledger math is lexicographic string comparison (`label >=
   first_tx_date`, `tx_date <= label`), and `"YYYY-MM-DD HH:MM"` labels
   sort correctly against `"YYYY-MM-DD"` transaction dates. A 5D
   transaction applies at that day's first 30m bar — same honest
   date-driven model, finer bars.
5. **Docs**: contract rewrite in project-brief.md Design Rules ("5m is the
   only intraday" → flag-based contract), AGENTS.md:35, code comments.

## Known accepted behavior

- 5D now shows intraday wiggle — that's the point.
- A 5D transaction applies at its day's FIRST 30m bar (date-only ledger
  can't know the minute) — same approximation 1D uses, applied per-day.
- Cross-ticker label unions: tickers from different markets (TSX vs NYSE)
  have different 30m timestamps → the union axis may be denser than any
  single ticker's bars; forward-fill handles gaps (existing mechanism).

## Test plan (written FIRST, must fail until implemented)

Extend `tests/test_chart_speed.py` + `tests/test_market_data.py`:

- **5D unpacking**: fake yf records `("AAPL", "5d", "30m")` in calls.
- **5D labels are datetime-shaped**: `"YYYY-MM-DD HH:MM"`, unique across
  several days (multi-day fake index → no dict-key collisions).
- **1D labels stay HH:MM** (regression), **1M/5Y/MAX labels stay dates**
  (regression).
- **TTL live**: 5D entry goes stale at 121s (refetch), like 1D; **TTL
  settled**: 1M entry survives past 601s? — NO, stale at 601s; existing
  601s test moves from 5D → 1M.
- **Route 5D daily-shaped**: transactions on separate days apply at that
  day's first 30m bar; axis trims at first_tx_date; labels pre-first-buy
  dropped. End-to-end via `/api/portfolio/history?period=5D`.
- **Route 1D regression**: existing first-bar intraday branch tests stay
  green untouched.

## Status

- [x] Plan approved by user (30m chosen from options)
- [x] Tests written & failing (4 new-contract tests failed; 3 old tests
      encoding "5D = daily/settled" moved to 1M)
- [x] Implemented
- [x] Full suite green: 226 passed
- [x] GUI check by user (2026-09-05, "ok good")
- [ ] Commit decision

## Notes from implementation

- The moved tests surfaced a FOURTH 5D-contract test the plan missed:
  `test_routes.py::test_history_nan_close_carries_forward_and_stays_strict_json`
  (real get_history through the route with date-only 5D bars) — moved to
  1M like its siblings in test_market_data.py / test_stock.py.
- PERIOD_MAP gained a third per-entry key beyond the planned two: a
  `label` strftime format. Deriving the shape from `intraday`/`live`
  would have re-created a mini string-sniff (5D needs the datetime shape
  while NOT being intraday-flagged); an explicit format per row keeps
  "adding a timeframe = edit the map once" true.
- `get_history`'s local `is_intraday` disappeared entirely — label
  format and TTL each read their own key; `app.py`'s route-level
  `is_intraday` now reads the `intraday` flag.
