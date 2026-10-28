# Hourly points on the 1M charts

Status: verified; user approved publishing to latest for testing on 2026-10-28
Branch: fix/1m-hourly-chart
Scope: chart-settings tweak, no roadmap item

## Tests first

- `tests/test_market_data.py`: move daily-label fixtures to 3M, including
  NaN/infinity expectations. Add hourly 1M coverage for repeated hours across
  dates, invalid prices, empty data, and failed fetch retry. Assert Yahoo
  receives `period=1mo`, `interval=1h`, and raw prices.
- `tests/test_chart_speed.py`: use 3M for settled-cache coverage. Test 1M
  freshness at 119 seconds and expiry at 120. Update the live flag contract.
  Exercise hourly portfolio labels, costs, values and TWR; trim pre-buy bars,
  apply trades at the first bar of their date, defer weekend trades, exclude
  future trades from a closed session, and carry prices forward across gaps.
- `tests/test_stock.py`: exercise the real data helper with stub Yahoo hourly
  data through the stock route, preserving every valid hourly point.
- `tests/test_compare.py`: cover datetime comparison axes for both charts.
- `tests/test_chart_ticks_behavior.py`: cover a dense month of hourly data,
  including year-boundary labels and exact-time hover formatting.

Targeted command:
`.venv/bin/python -m pytest tests/test_hourly_month.py tests/test_market_data.py tests/test_chart_speed.py tests/test_stock.py tests/test_compare.py tests/test_routes.py tests/test_twrr.py tests/test_chart_ticks_behavior.py tests/test_chart_tooltip.py tests/test_price_adjustment.py`

## Implementation

1. Change only 1M in `market_data.py`'s shared PERIOD_MAP to interval `1h`,
   live true, intraday false, label `%Y-%m-%d %H:%M`.
2. Update comments and `project-brief.md` chart/cache policy. Hourly 1M is the
   user's explicit replacement for the old monotonically increasing point-count
   rule. 3M and longer keep their existing settings.
3. Reuse existing route trade-date logic and frontend datetime formatting.
   Change those only if verification demonstrates a defect.

## Verification and approval

- Run targeted tests, then `.venv/bin/python -m pytest`.
- Check seeded hourly dashboard and stock charts on desktop and phone widths,
  including comparison lines, Value/Performance, day ticks, and time hover.
  Existing capture scripts target auth UI and bind localhost, so use a temporary
  chart-specific capture harness. A user demo must bind a LAN address.
- Run independent reviewer in diff mode on the full change, fix blockers,
  and wait for GUI approval. No merge, commit, or push without explicit request.

## Plan review

Read-only reviewer found no blockers. Incorporated its two nits: migrate the
infinity fixture too, and account for the capture scripts' auth-only scope and
localhost binding. User approved on 2026-10-28.

The prior logo handoff was stale. Logo work shipped in 62d8180 and a6870a0.

## Results

- Tests were written first. The pre-change run failed on hourly label
  preservation, cache expiry, route outputs, and live-period flags as expected.
- Full suite: **1505 passed**, `.venv/bin/python -m pytest`.
- Diff reviewer: no blockers. Its handoff-command nit is fixed above.
- Playwright: both charts at 1280px and 390px show 154 hourly points from
  deterministic Yahoo stubs through the real history helper. Exact-time hover,
  performance mode and comparison lines work. No browser page errors.
- Screenshots: `instance/hourly-chart-previews/`, local only.
- Demo: `http://192.168.0.156:5011`, account `demo`, password `demo-pass-1234`.
  Uses a separate preview database and simulated market data. Its terminal is
  named `Hourly chart preview`; the script is `/tmp/opencode/hourly_preview_server.py`.
- The browser has its own history cache, so `static/js/common.js` also adds
  1M to the two-minute live tier. A test checks browser/server agreement.
- Tests for shared hourly integration paths are centralized in
  `tests/test_hourly_month.py` rather than duplicated across route test files.
- `project-brief.md` is intentionally gitignored in this checkout. Its local
  chart and cache policy has been updated.
- User requested "Push to latest so I can test it" after verification. This
  authorizes the squash merge and push to main for the Docker publish workflow.
  The user's live-data visual test follows the server update.
