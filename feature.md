# Performance release 2: slower loading and duplicate work

Status: shipped 2026-11-10 (PR #106). Approved by the user 2026-11-10 after an independent
plan review (two rounds; no remaining blockers).

Branch: `plan-portfoliarr-speed-performance` (existing linked worktree,
based on `origin/main` `10e272b`). The branch name does not match the
`feat/<id>-<slug>` pattern. The worktree is adopted as-is; the main
checkout holds unrelated security work and must stay untouched.

Roadmap: added as item 63 (Tier 2) after approval.

## Scope approved

Honor the previous owner decision: keep the eight parallel dashboard
period preloads and all Volume Leaders behavior. Do not ship the deferred
ledger prototype. Do not pre-plan Tier 3 items.

1. Make the performance harness trustworthy: race-free child server with
   an inherited listening socket and ready token, disposable verified
   seeds, real pinned Chart.js fixtures offline, chart-paint readiness,
   explicit cold/warm modes, honest error reporting, and no private
   symbols or amounts in timing data.
2. Share in-flight history requests for the same (symbol, period).
3. Load Closed Sales company names with at most four workers, one row pass.
4. Read one ticker's transactions through the existing index for the stock
   page position card.
5. Load Chart.js and the annotation plugin only on Dashboard and Stock.
6. Measure Gunicorn 8/12/16 threads under 2-client, slow/failed-provider,
   concurrent-write load. Change the setting only if the approved safety
   gate passes; otherwise keep eight and report.

## Tests first

- `tests/test_market_data.py` / `tests/test_chart_speed.py`: eight
  simultaneous cold same-key history calls make one provider call; warm
  hit adds none; different keys run concurrently; failure wakes all
  waiters and stays retryable; invalid period raises before any slot;
  callers get independent copies; successful `{}` keeps the normal TTL.
- `tests/test_realized.py`: name lookups use 2-4 workers, tolerate one
  failure, make zero calls with no sales, and preserve rows/order/totals.
- `tests/test_db.py` / `tests/test_stock_position.py`: one-ticker query
  ordering, exact ticker match, portfolio isolation, query plan uses
  `tx_portfolio_ticker`, and stock-position JSON parity.
- `tests/test_prev_close.py`, `tests/test_ledger_page.py`,
  `tests/test_stock.py`, `tests/test_allocation_ui.py`: chart libraries
  on Dashboard/Stock in the right order; absent on Ledger/Preferences.
- `tests/test_perf_js.py`, `tests/test_perf.py`: fund-classification path
  normalization on both client and server; no symbol in payloads.
- `tests/test_perf_harness.py`: DB redirect before import, seeded counts,
  no repo baseline writes, no real instance DB writes, offline smoke with
  real charts and zero unexpected console/page errors, missing-CDN case
  separate, and occupied-port/wrong-child protection.

## Implementation notes

- `market_data.py`: `_inflight_history` keyed by `(symbol, period_key)`,
  owner-only cache write, identity-checked cleanup, waiters get copies.
- `app.py`: parallel realized names; `_CLIENT_DYNAMIC_ENDPOINTS` gains
  `/api/fund-classification/:symbol`; stock position uses the new query.
- `db.py`: `get_transactions_for_ticker(portfolio_id, ticker)` with
  `ORDER BY transaction_date DESC, id DESC`.
- `templates/base.html`: `head_extra` block; `index.html` and
  `stock.html` load Chart.js + annotation plugin; ledger/preferences do
  not.
- `static/js/perf.js`: path template for fund classification.
- `scripts/perf_server.py` / `scripts/measure_perf.py`: FD handoff,
  ready token, verified seed, fixture assets, cold mode, chart checks.
- `tests/fixtures/perf/`: pinned Chart.js 4.6.1 and annotation 3.1.0
  assets with licenses and a source/version record.

## Verification

Focused files during development; full suite once before code review.
Disposable DBs only. Docker is unavailable locally, so the image build
must be validated by GitHub Actions. GUI checks at 1280x800 and 390x844
with screenshots in the PR.

## Results

- History single-flight: eight simultaneous identical cold requests now make
  one provider call; a ninth warm request makes none; different keys still
  overlap; failures wake every waiter and stay retryable.
- Closed Sales names: with 10 distinct sold tickers and a 50 ms fake
  provider, the measured median dropped from ~503 ms to ~153 ms. 20
  tickers measured ~254 ms. Results, totals, and row order are unchanged.
- Stock position reads only its ticker through the existing
  `tx_portfolio_ticker` index; the query is pinned with `INDEXED BY` because
  SQLite otherwise prefers the date index and scans every portfolio row.
- Chart.js and the annotation plugin now load only on Dashboard and Stock.
  The offline harness confirms real charts render on those pages and
  `Chart` is absent on Ledger and Preferences.
- Harness: the old offline route pattern (`https://**`) never matched in
  this Playwright build, which is why the smoke test failed with
  `ERR_INTERNET_DISCONNECTED`. It now matches the scheme with a regex and
  serves pinned Chart.js 4.6.1 / annotation 3.1.0. The driver passes an
  inherited listening socket and verifies a random ready token before
  seeding, verifies stored transaction counts, and supports `--cold`
  (fresh server per page). A missing-chart run is a separate expected
  degradation test.
- Gunicorn threads: **kept at 8**. Two-client, 16-chart, concurrent-write
  test: peak simultaneous provider calls rose from 48-56 to 64 (one
  baseline rep +33%, beyond the 25% gate), so the safety gate failed.
  Light-request latency during that burst was ~918-950 ms at 8 threads and
  ~475-615 ms at 16. The reduced light latency is real but not worth the
  added provider pressure without a bounded provider budget, which is
  deferred to a separate plan. `Dockerfile`, `README.md`, and
  `tests/test_docker.py` are unchanged.
- Deferred ledger prototype remains unshipped: 1,000 synthetic rows still
  build hidden detail rows (`ledger:rows` 414-508 ms in the new harness).

## Checks

- Focused performance/feature files: **323 passed**.
- Full suite in an isolated network namespace with a redirected disposable
  database: **1545 passed** (83.4 s) after the review fixes.
- Offline browser run, desktop 1280x800 and phone-width 390x844, 1,002
  verified synthetic transactions: 0 unexpected console/page errors,
  real charts on Dashboard and Stock, no Chart.js on Ledger/Preferences.
- GUI check, offline with real pinned charts and 1,002 verified synthetic
  transactions: Dashboard (1M switch), Ledger (group expanded), Stock
  (chart), Preferences, each at 1280x800 and 390x844. No page or console
  errors. Screenshots in `docs/perf/screenshots-2026-11-10/`.
- Docker is not installed on this host; the image build and publish must be
  validated by GitHub Actions after the PR merges.

## Review

- PR https://github.com/ChristopheAwad/portfoliarr/pull/106
- Code review: one blocker (seed ticker count for `--ledger-rows` 1-7),
  fixed with a shared tested helper; follow-up review found no blockers.
  Reviewed base `10e272b`, first head `2df6932`, fix range through
  `e33b4d1`. Boundary test added for 7 rows afterwards.
- Merge gates still pending at this record: PR CI (none configured), Docker
  workflow after merge.

## Evidence

- `/tmp/opencode/portfoliarr-speed-study-20261110/after-desktop.md` and
  `.json` (new harness, 1,000 rows).
- `/tmp/opencode/portfoliarr-speed-study-20261110/probe.py`,
  `probe2.py`, `measure_realized.py` (controlled synthetic measurements).
- `/tmp/opencode/portfoliarr-speed-study-20261110/plan.md` (approved plan).

## Progress log

- 2026-11-10: approved plan recorded; implementation started.
- 2026-11-10: implementation and local checks complete; code review next.

---

# Chart tooltip: translucent and more compact

Status: implemented, awaiting code review and merge.
Branch: `make-chart-hover-tooltip-transparent-smaller` from main `10e272b`.
This is a small fix: one source file and one test file, no schema, auth,
money, or route change. Plan review gate skipped; code review gate applies.

## Request

The portfolio/stock line-chart hover tooltip was a large opaque dark card that
hid most of the chart. Make it more transparent and reduce its footprint.

## Approved plan

1. `static/js/common.js`: change the shared line-chart tooltip background from
   opaque `#1a1f36` to `hexToRgba("#1a1f36", 0.75)` so the plot shows through,
   and shrink padding 10 -> 8 and body font 13 -> 12. White title/body text and
   the existing green/red footer stay unchanged.
2. `tests/test_chart_tooltip.py`: add a source-level test that locks a
   translucent `hexToRgba` background and rejects the old opaque literal.
3. Run the tooltip tests, the full suite, code review, and a Playwright
   screenshot check in light and dark mode.

Acceptance: the tooltip is visibly see-through in both themes, white text stays
readable, the card is smaller, and no other chart's tooltip changes (the
allocation donut keeps its own config).

## Verification

| Check | Result | Evidence |
|---|---|---|
| Tooltip tests | Pass | `pytest tests/test_chart_tooltip.py` - 10 passed |
| Full suite | Pass | `pytest` - 1546 passed after merging origin/main |
| Build/lint/type | Not applicable | Project has no JS build, lint, or type step; CI runs pytest only |
| GUI check | Pass | Playwright hover screenshots, light + dark |
| CI | Pending | Checked after PR push |
| Code review | Pending | Reviewer runs on the PR diff |

GUI evidence: PR #107 comment, images under
`pr-107-screenshots:docs/screenshots/chart-tooltip-*.png`.

## Review log

Reviewer on PR #107 (base 5250bef, head 32dfeb0): no blocking issues. Nits
fixed without a re-review: the test now locks the exact alpha 0.75, padding 8,
and body size 12. The PR body test count was synced to 1546.

## Results

Semi-transparent, smaller tooltip shipped for the shared line charts only.
Full suite 1546 passed after merging origin/main. GUI screenshots in the PR.

---

# Mobile chart tooltip: compact labels

Status: implemented, awaiting review and merge.
Branch: `fix/mobile-tooltip-compact` from `origin/main` `77edeca` (PR #107
already shipped the translucent fix).
Small fix: one source file and one test file.

## Request

After PR #107 the tooltip was still too large on a phone: on a 390px-wide
chart the card covered about 54% of the width because of the long
"Portfolio Value (CAD): ..." labels.

## Change

- `static/js/common.js`: add `compactTooltip`, true when
  `matchMedia("(max-width: 640px)")` matches.
- Narrow screens: padding 6 (vs 8), title 10px (vs 11), body 11px (vs 12);
  body lines become `Value: …` / `Cost: …`; the performance view shows the
  index level alone. Desktop keeps the full labels.
- `tests/test_chart_tooltip.py`: source test locks the compact branch.

Acceptance: on a 390x844 viewport the card is about 85 CSS px wide (about 26%
of the 336px chart), the line and crosshair stay visible, and white text stays
readable in light and dark mode. Desktop labels are unchanged.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Tooltip tests | Pass | `pytest tests/test_chart_tooltip.py` - 11 passed |
| Full suite | Pass | `pytest` - 1547 passed |
| Build/lint/type | Not applicable | No JS build/lint/type step; CI runs pytest |
| GUI check | Pass | Playwright 390x844 hover, light + dark, left + right |
| CI | Pending | Checked after PR push |
| Code review | Pending | Reviewer runs on the PR diff |

Mobile screenshots: `/tmp/opencode/mobile-chart-{light,dark}-{left,right}.png`.

## Review log

Reviewer on PR #108 (base 77edeca, head c3a728a): no blocking issues. Safe test
nits fixed without a re-review: assert the desktop full labels, the performance
compact literal, and the compact title font. Left as-is by choice: the
breakpoint is read once at chart construction (reload fixes rotation), and the
compact labels omit the "(CAD)" qualifier to save width.

## Results

Compact tooltip shipped for narrow screens only. Full suite 1547 passed. Mobile
screenshots in the PR.
