# Performance first pass: responsive charts, startup, and ledger

Status: in progress. Owner approved the reviewed five-item plan on 2026-11-14.
Roadmap: #64. Base: `origin/main` / HEAD `c784bfd`.
Branch: `audit-app-performance-loading-times`, an existing linked worktree.
The name differs from the normal feature/fix pattern. Adopt it without renaming
or switching the main checkout, which holds unrelated security work.

The owner requested OpenAI Terra Max implementation subagents and confirmed
`openai/gpt-6.1-terra`, maximum reasoning. Four agents have separate ownership.
Independent plan review is complete with no remaining blockers or nits after
fixing chart-state races, recovery semantics, and honest measurement checks.

## Approved scope and ownership

1. Browser agent: `static/js/common.js`, `static/js/main.js`, the chart-ready
   mark and null-selection response guard in `static/js/stock.js`,
   `tests/test_loading_performance_behavior.py`,
   and directly affected chart/portfolio contracts.
   - Nonanimated period/view/recovery drawing; retain layout-aware frame resize.
   - Always store the newest previous-close value, but skip unchanged or
     irrelevant redraws. Preserve donut animation and tooltip appearance.
   - Share pending history reads by scope, period, and benchmarks. Invalidation
     prevents joining old scope/revision reads; identity-safe cleanup preserves
     replacement requests and current stale-response guards.
   - Commit datasets, last reply, current period, selected button, and readout
     together inside the accepted draw frame. A superseded frame commits none.
     Check data at draw completion and again at the next frame opportunity.
     Never claim physical display timing. Valid empty replies complete their
     draw but do not emit finite-series-ready metrics.
   - Start eight distinct parallel preloads for the other periods after the
     first successful current-scope visible draw, including a later selection
     or retry when the default fails. The full period set includes 5D.
   - Reuse number formatters without changing formatting/exception semantics.
   - Share equivalent initial/recovery portfolio-list reads; post-write
     Preferences reads must be fresh. On failed initial null-to-valid recovery,
     emit one `portfoliochange` with `{id, previous: null}` and the normal
     `portfoliolistchange`; use the existing four page consumers. Normal initial
     success emits no extra scope event. Empty lists show an explicit no-
     portfolios state with Retry. Preserve 401/login behavior.
2. Ledger agent: `static/js/ledger.js`, `tests/test_ledger_lazy_behavior.py`,
   and directly affected ledger/group/privacy/quick-sell contracts.
   - Build only expanded groups' details, insert on expansion, remove on
     collapse, and preserve ordering, actions, masks, column order, and expanded
     selection across refreshes. Use summary rows for failed-poll preservation
     and restore open caret state after a rebuild.
   - Lazy caches follow latest request, currency, and portfolio. Old replies
     cannot restore stale rows; expansion waits for matching currency data.
   - Closed Sales always updates its header total, builds details only when
     open, and clears cached rows/header/classes on failure or portfolio reset.
3. Assets agent: `templates/base.html`, `templates/_auth_head.html`, all four
   page templates, `static/style.css`, new `static/vendor/` and `static/fonts/`,
   `scripts/measure_perf.py`, asset/harness tests and fixture source records.
   - Copy pinned Chart.js 4.6.1 and annotation 3.1.0 with MIT licenses and hashes
     into production static paths. Keep chart libraries page-specific.
   - Serve matching Fraunces v38 normal variable weight 400-700 / opsz 9-144
     subsets vietnamese/latin-ext/latin, and Instrument Sans v4 normal variable
     weight 400-700 / width 100% subsets latin-ext/latin. Preserve exact unicode
     ranges, `font-display: swap`, fallback stacks and typography. Record all
     upstream URLs, hashes, and the two pinned SIL OFL licenses.
   - Theme bootstrap precedes stylesheets. Apply ordered defer to Chart/plugin,
     perf/common, and page scripts on all authenticated pages together.
   - Shared hidden status IDs: `portfolio-load-status`, `portfolio-load-message`,
     and native keyboard-accessible `portfolio-load-retry` button. Browser agent
     owns state/wiring; assets agent owns markup/styles.
   - Harness serves actual production asset paths, separates missing-chart and
     empty-success cases, and requires real finite-data draw readiness for its
     seeded success runs. Wrap Playwright route callbacks explicitly so a
     Request cannot bind to the `missing_chart` argument.
4. Volume agent: `market_data.py`, `tests/test_volume_leaders.py`.
   - One composite owner Future under the existing lock; wait/provider work
     outside it. Preserve 33 candidates, eight workers, five-minute TTL,
     partial/total-failure behavior, output and same-sector tie behavior.
   - Independent return copies; complete every waiter on error; identity-check
     cache publication and cleanup after clearing/replacement. Old owners can
     finish old waiters but cannot overwrite the replacement cache.
5. Lead: integration, handoff/roadmap, checkpoints, required verification,
   performance evidence, GUI screenshots, PR/review, merge and image publication.

Preserve existing market tabs, financial calculations, ownership, storage and
all eight parallel period preloads. Provider budgets/deadlines/thread changes,
metadata caching, payload/import changes and Android work are later audit work.
No schema, route, dependency upgrade, plugin removal or visual redesign.

## Tests and acceptance

Write failing behavior tests first. Cover same-key/different-key pending reads,
failed/replaced requests, invalidation, a successful 1M reply superseded before
its frame by pending/failed 3M, empty versus failed drawing, 5D failure then 1D
success and correct eight other preloads, newest prev-close after switching
5D to 1D, formatter parity, initial success without duplicate boot, retry and
empty-list recovery on all four pages, and forced post-write list freshness.

Ledger tests cover zero collapsed details, multiple expanded groups, repeated
expansion, polling, sort/column/privacy/currency changes, stale success/failure
ordering, punctuation tickers, edit/delete/group delete/quick sell, zero/closed/
short/unquoted positions, latest/empty/degraded/failed Closed Sales and keyboard
toggle. Volume tests use bounded synchronization for cold/expired sharing,
success/partial/total/unexpected failure, defensive copies, TTL boundary,
cache-clear old-before/new-before completion, metrics and unrelated quote work.

Use the main checkout venv. Lead runs the full suite once after integration:

```bash
/home/Chris/Documents/code/portfoliarr/.venv/bin/python -c 'import pathlib,tempfile,db,pytest; db.DB_PATH=pathlib.Path(tempfile.mkdtemp(dir="/tmp/opencode"))/"tests.db"; raise SystemExit(pytest.main(["-q"]))'
```

Agents run affected files only, with DB_PATH redirected before app import. New
shared-JS tests execute Node; ledger tests use installed system Playwright and
Chromium. Both must execute locally. CI browser skips are reported explicitly.
No package/venv/browser installs. Run `node --check` on changed JS. There is no
configured frontend build/lint/type command. Docker is unavailable locally;
the existing merged-main workflow builds, smoke-tests and publishes the image.

Standard all-screen comparison, 1,002 verified rows across ten tickers:

```bash
/usr/bin/python3 scripts/measure_perf.py --python /home/Chris/Documents/code/portfoliarr/.venv/bin/python --stub-ms 150 --runs 2 --settle 0.3 --ledger-rows 1000 --offline-assets --out /tmp/opencode/portfoliarr-audit-20261113/after-desktop
```

Focused exact-fixture acceptance:

```bash
/usr/bin/python3 /tmp/opencode/portfoliarr-audit-20261113/verify_first_pass.py --out /tmp/opencode/portfoliarr-audit-20261113/after-focused.json
```

The focused script uses a disposable inherited-socket server, real setup/session,
then verified direct synthetic inserts only in its own DB. Fixtures are exactly
1,000 and 5,000 CAD BUY rows across eight `.TO` groups, and 1,000 mixed BUY/SELL
rows across 200 groups with 200 sales. Check 390x844 at normal and 4x CPU. Time
real qty/value/ticker sorts synchronously and report next-frame opportunities
separately. Assert zero collapsed transaction/sale details after load/sorts,
exact expanded counts and zero after closing. Target all 5,000-row/eight-group
sort samples below 100 ms at 4x CPU. The many-group stress case has no invented
100 ms requirement. Target cached 1Y draw below 100 ms at normal CPU, matching
its successful preload data at afterRender, with selected button on the next
frame and zero new history requests. Baseline mode allows only explicitly known
legacy count/timing failures; incomplete/error runs always remain failed.

Also verify two cold Volume consumers perform 33 provider reads, pending-period
selection sends one HTTP read, initial 503 recovers without reload, and blocked
external hosts do not stop local fonts/chart/app. Final GUI covers all four
screens/auth forms, relevant actions/errors, themes, phone/desktop, keyboard/
focus, screenshots, failed requests and server logs. Delayed-font checks observe
API/fallback text while bytes are held, without waiting for the load event.

## Gates, release and current evidence

- Plan review: pass, independent Terra Max reviewer, no outstanding findings.
- Implementation and focused checks: pass. Four agents wrote failing tests
  before their fixes; all changes are integrated through `523707c`.
- Full suite: **1614 passed in 114.97 s**, lead-run on the combined code in an
  isolated network namespace with loopback enabled and a disposable DB.
  No local browser/Node skips. JavaScript syntax and `git diff --check` pass.
- Focused performance acceptance: pass, all 52 checks. Exactly 5,000 rows/eight
  groups at 4x CPU sorted in 9.2-15.4 ms versus 1786.8-2095.0 ms before.
  Collapsed descendants fell 115,200 -> 200; expanded/collapsed row counts and
  mixed-sale fixture checks pass. Cached 1Y drawing completed in 21.6 ms versus
  about 1046 ms before, matching its preload data with zero new history reads.
- Standard offline harness: both desktop 1280x800 and phone 390x844, two visits
  per screen, all four screens with 1,002 verified synthetic rows. No page or
  console errors and zero external browser requests. Both real charts render;
  Ledger/Preferences load no Chart library. Stub timings are not live Yahoo
  latency or cache measurements.
- Lead cache probe: eight identical history reads plus a warm read still make
  one provider call; two cold Volume reads now make 33 info reads, versus 66
  before, and the following warm read adds none.
- Final GUI/PR review/merge: pending. Required final GUI is scheduled after
  code review and will inspect screenshots, action outcomes and logs.
- PR workflow: none configured for these changes; absence is not a passing run.
- Docker publish: required merged-main workflow, pending. Watch with
  `gh run watch <id> --exit-status`, verify merged-SHA and latest publication,
  then promptly provide `docker compose pull && docker compose up -d` steps.
- Medium risk: async display ordering, lazy action rows, and asset delivery.
  Revert the eventual squash commit through normal PR checks if those regress.
  No migration/data restore is needed; a revert does not undo saved trades.
- Before merge fetch and integrate changed upstream, check final committed/pushed
  head and required gates. Preserve the active worktree branch; record its
  shipped squash SHA here rather than deleting it from under this session.
- Full reviewed plan, audit, exact-font URLs, baseline reports, measurement
  scripts and review notes are under
  `/tmp/opencode/portfoliarr-audit-20261113/` on this host.

Integration boundary fixes stay within scoped recovery: a loaded selection that
becomes empty emits one null `portfoliochange`, clears old Dashboard/Ledger/Stock
content, and suppresses null-scope chart requests. Late Stock position responses
are epoch-guarded. Ledger boot also handles an empty/failed list that settled
before its deferred script subscribed. These regressions were reproduced first
and checked in Node/Chromium; no position calculations or API behavior changed.

Checked code: `523707c3b5a7cb41ebb4ebd3de4837937bf9cbcb`. The subsequent
documentation-only evidence checkpoint will be consistency-checked. PR URL and
reviewed base/head SHAs will be added after creation/review.

---

## Historical shipped handoffs

The sections below predate #64. Git history confirms #106 and #107-#109 shipped;
their old pending-status prose is historical, not active work.

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

---

# Tooltip: keep transparency, restore the old size

Status: implemented, awaiting review and merge.
Branch: `fix/tooltip-restore-size` from `origin/main` `4f016c7`.
Small fix: one source file and one test file.

## Request

The owner wanted ONLY a more transparent tooltip. The size reductions in
PR #107 (padding 10 -> 8, body 13 -> 12) and PR #108 (compact mobile labels
and smaller type) were not wanted. Keep the translucent fill; restore the
original size and labels everywhere.

## Change

- `static/js/common.js`: keep `backgroundColor: hexToRgba("#1a1f36", 0.75)`.
  Restore `padding: 10`, `titleFont` 11, and `bodyFont` 13. Remove the
  `compactTooltip` variable and its label branches, so the full
  "Portfolio Value (CAD): ..." / "Cost Basis (CAD): ..." labels and the
  performance dataset-label line return on every width.
- `tests/test_chart_tooltip.py`: replace the two size tests with one test
  that locks the translucent fill, the original padding/fonts, and the full
  labels, and rejects any `compactTooltip` leftover.

Acceptance: the tooltip is translucent, but its size and text match the
version before PR #107 at desktop and phone widths.

## Verification

| Check | Result | Evidence |
|---|---|---|
| Tooltip tests | Pass | `pytest tests/test_chart_tooltip.py` - 10 passed |
| Full suite | Pass | `pytest` - 1546 passed |
| Build/lint/type | Not applicable | No JS build/lint/type step; CI runs pytest |
| GUI check | Pass | Playwright 1280x800 and 390x844, light + dark |
| CI | Pending | Checked after PR push |
| Code review | Pending | Reviewer runs on the PR diff |

Screenshots: `/tmp/opencode/tooltip-chart-{light,dark}.png` (desktop) and
`/tmp/opencode/mobile-chart-{light,dark}-{left,right}.png` (phone).

## Review log

(Pending)

## Results

(Pending)
