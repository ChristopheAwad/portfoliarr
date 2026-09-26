# Portfolio Tracker — Feature Roadmap

Organized by priority tier. Effort is in working days (solo dev, includes tests).

---

## Tier 1 — Quick Wins (1–2 days each)

### 1. Average Cost per Position
The ledger group row's Price column currently shows "—". Compute and display
the current open position's average acquisition price with an oldest-first
average-cost replay. Partial closes preserve the remaining position's average;
crossing through flat starts a new opposite-side pool at the crossing
transaction's price. The value follows the ledger's CAD/native display mode
and remains available when a live quote fails.

**Files:** `app.py`, `static/js/ledger.js`, `tests/test_ledger_groups.py`, `tests/test_ledger_average_price.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-22 (PR #68)

---

### 2. CSV Export
Import exists (`parse_import_text`), but there's no export. One new route (`GET /api/transactions/export`) that formats `db.get_transactions()` as downloadable CSV. Add a button in the ledger UI next to the import panel.

**Files:** `app.py` (new route), `templates/index.html` (button), `static/js/main.js` (download handler)
**Depends on:** Nothing
**Priority:** Back burner (user request)

---

### 3. Transaction Fees
Currently no fee tracking. Add a nullable native-currency `fee` column to the `transactions` table. Fees increase buy costs and reduce sell proceeds in ledger, portfolio, and realized-gain calculations. The DB migration pattern already exists (see fx_rate migration in `db.py`). Detailed plan in `feature.md`.

**Files:** `db.py` (schema + migration), `app.py` (validator + accounting routes), `static/js/ledger.js` (form + display), `templates/ledger.html` (input + column), `project-brief.md`, tests
**Depends on:** Nothing
**Status:** shipped 2026-09-23 (PR #79)

---

### 4. Sector Breakdown Donut
The dashboard allocation carousel has a By Sector view. The server groups priced holdings by sector and returns their CAD values and weights. This shipped as part of the multi-dimension allocation donut, rather than as a second chart.

**Files:** `app.py`, `market_data.py`, `static/js/main.js`, `tests/test_allocation.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-15 (PR #34)

---

### 5. Cash Balance Tracking
Track uninvested cash in the portfolio. One row in a `portfolio` settings table (`cash_balance REAL DEFAULT 0`). Buys deduct cash, sells add back. Deposit/withdraw actions to move cash in/out. Portfolio total becomes cash + holdings. Allocation chart includes cash as a segment.

**Files:** `db.py` (new table + functions), `app.py` (new routes), `static/js/main.js` (summary strip + allocation chart), `templates/index.html` (UI elements)
**Depends on:** Nothing

---

### 16. Android Biometric/PIN App Lock
Add an optional local privacy lock to the Android APK using Android's
`BiometricPrompt`, with fingerprint/face authentication and the device PIN,
pattern, or password as fallback. Lock on a configurable return-from-background
timeout without destroying or reloading the WebView, and provide settings to
enable, disable, and test the lock. Handle cancellation, repeated failures,
devices without enrolled credentials, activity recreation, and renderer
recovery safely. This protects the portfolio on the phone only; it does not
authenticate or secure the Flask server.

**Effort:** 1–2 days
**Files:** `android/app/src/main/java/com/portfoliarr/app/MainActivity.kt`, `android/app/src/main/java/com/portfoliarr/app/SettingsActivity.kt`, `android/app/src/main/res/layout/activity_settings.xml`, `android/gradle/libs.versions.toml`, `android/app/build.gradle.kts`, Android tests
**Depends on:** Nothing
**Priority:** Back burner (user request)

---

### 18. Ledger Quick Sell
Add a Sell action to each positively held, currently quoted ticker group in the
ledger. It prepares the existing transaction form with the ticker, complete net
quantity, exact current native price, local date, and SELL operation. The user
reviews and logs the transaction; the action never submits automatically. Hide
it for closed, short, and unquoted groups, and remove it when a failed refresh
makes the displayed quote stale.

**Effort:** 1 day
**Files:** `static/js/ledger.js`, `static/style.css` if needed, `tests/test_ledger_quick_sell.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-21 (PR #65)

---

### 19. Date-Aware Ledger Price Auto-Fill
Make the ledger form's Price auto-fill depend on the selected Date. Pick a
ticker → the field fills with the latest recorded close on or before the date.
Change the date → the price refreshes. Today (or an empty date) keeps the
existing live quote. A manually typed price and edit mode are never overwritten,
and a missing historical bar leaves the field empty rather than guessing.

**Effort:** 1 day
**Files:** `market_data.py`, `app.py`, `static/js/ledger.js`, `conftest.py`, `tests/test_market_data.py`, `tests/test_quote.py`, `tests/test_price_autofill.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-21 (PR #67)

---

### 21. High-Value Operational Logging
Add searchable console logs that explain failures and confirmed data changes
without recording portfolio amounts or request bodies. Configure production at
INFO, attach a generated request ID to responses and route logs, record concise
mutation audit events, aggregate routine Yahoo degradation, warn on requests
slower than two seconds, and bound Docker's local log retention. Keep full
tracebacks for unexpected bugs only; do not add an external logging service,
Gunicorn access-log duplication, or logging inside the pure data layers.

**Effort:** 1–2 days
**Files:** `app.py`, `docker-compose.yml`, `project-brief.md`, `tests/test_logging.py`, `tests/test_docker.py`, existing route-log assertions
**Depends on:** Nothing
**Status:** shipped 2026-09-22 (PR #71)

---

### 22. In-App Version Display
Show the current Portfoliarr release in a quiet About card at the bottom of
Preferences. Use one root version file for both the Flask UI and Android's
`versionName`, while Android's independently increasing `versionCode` remains
in Gradle properties. Reject a missing or malformed shared version at startup
or build time so the two clients cannot silently drift.

**Effort:** less than 1 day
**Files:** `VERSION`, `app.py`, `templates/preferences.html`, `static/style.css`, `android/app/build.gradle.kts`, `android/gradle.properties`, `project-brief.md`, `tests/test_app_version.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-22 (PR #72)

---

## Tier 2 — Core Features (3–5 days each)

### 23. Several Named Portfolios
Replace the single implicit ledger with independent named portfolios. Assign old
transactions to `Main`; select the active portfolio on the dashboard or ledger,
manage names and order in Preferences, and scope transactions, summary, history,
allocation, and closed sales to it. Market pages remain shared; the
watchlist stayed shared until #26 made it per-person.
Selection persists per browser and updates its other tabs immediately. Deleting
a portfolio requires typed confirmation and cannot remove the last portfolio.
Detailed tests-first implementation plan: `feature.md`.

**Effort:** 5 days
**Files:** `db.py`, `app.py`, `static/js/common.js`, `static/js/main.js`, `static/js/ledger.js`, `static/js/preferences.js`, `static/js/stock.js` if needed, `templates/index.html`, `templates/ledger.html`, `templates/preferences.html`, `static/style.css`, `project-brief.md`, portfolio tests and existing fixture/route tests
**Depends on:** Nothing; preserve #3 fee accounting and #13/#14 performance history behavior
**Status:** shipped 2026-09-24 (PR #80)

---

### 6. Dividend Tracking
The `transaction_type` CHECK constraint needs a new value (`DIVIDEND`). Add it to the validator, the form, and the ledger display. Dividends don't affect cost basis (they're income, not a reinvestment unless logged as a BUY). The ledger already handles multiple transaction types — this extends the pattern.

**Files:** `db.py` (CHECK constraint update), `app.py` (validator + routes), `static/js/main.js` (form + ledger display), `templates/index.html` (form radio)
**Depends on:** Nothing (but fees make dividend math more realistic)

---

### 7. Benchmark Comparison Line on Chart
Ghostfolio overlays S&P 500 against your portfolio. Overlay a normalized benchmark line on the portfolio value chart. The data pipeline exists (`get_history` + `PERIOD_MAP`). Needs Chart.js multi-dataset support and normalization (rebase both series to 100 at start date).

**Files:** `app.py` (new endpoint or extend `/api/portfolio/history`), `static/js/common.js` (chart factory), `static/js/main.js` (second dataset)
**Depends on:** Nothing

---

### 8. Multi-Currency Support Beyond USD/CAD
Currently only USD↔CAD via Yahoo's `USDCAD=X`. Extending to EUR, GBP, JPY, etc. means adding more FX pairs to `get_fx_rate`. The architecture (per-transaction stored rates + live rates) is already correct — just needs more pairs and a currency selector or auto-detection.

**Files:** `market_data.py` (FX pair expansion), `app.py` (currency logic), `db.py` (schema if adding default currency)
**Depends on:** Nothing

---

### 17. Arbitrary Comparison Overlays (supersedes #7)
Overlay up to 3 user-chosen tickers (search + quick picks: S&P 500, Nasdaq,
TSX) as growth-of-$100 lines. On the dashboard the overlays appear ONLY in the
Performance (TWR) view, rebased onto the portfolio's own label axis. On the
stock detail page, adding any comparison normalizes the primary symbol and all
overlays to growth-of-$100 on a union axis (raw price when none are active).
One shared picker in `common.js`; benchmark history is fetched inside the same
request (no new endpoint). Currency-agnostic by construction (ratios only).

**Files:** `app.py` (history routes + helpers), `static/js/common.js`
(picker, multi-dataset, legend), `static/js/main.js`, `static/js/stock.js`,
`templates/index.html`, `templates/stock.html`, `static/style.css`,
`tests/test_compare.py`, `tests/test_compare_ui.py`
**Depends on:** #13 (shipped) for the growth-of-$100 index
**Status:** shipped 2026-09-20 (PR #60)

---

### 26. Multi-User Accounts (Login + Ownership)
Make the server require a login and give each person their own data. A `users`
table (username, Werkzeug password hash) is created on a first-run setup page
that also claims the migration's existing portfolios and watchlist rows; every
later person is created from the Preferences People card. A `before_request`
auth gate signs Flask session cookies (secret generated once, stored in an
`app_settings` table so restarts keep sessions) and turns pages 302 and `/api/*`
401 when signed out. Ownership: portfolios gain a `user_id` (per-user "Main",
per-user name uniqueness, per-user last-portfolio rule), transactions stay
owned through their portfolio's FK, and the watchlist becomes per-user. The
portfolio-resolution hook checks the session user before honoring any
`portfolio_id`, so no request can ever read another person's ledger. People
management (list/add/delete/reset rules: no self-delete, no last-user delete,
typed-username confirm for the cascade) and change-own-password live in
Preferences. Signed-out 401s redirect the browser to login through one common.js
fetch hook; Android needs no changes (the WebView logs in and keeps cookies).
No open registration, no roles, no rate limiting (home-LAN trust model).

**Effort:** 5 days
**Files:** `db.py`, `app.py`, `templates/base.html`, `templates/login.html`, `templates/setup.html`, `templates/preferences.html`, `static/js/common.js`, `static/js/preferences.js`, `static/style.css`, `conftest.py`, `project-brief.md`, `tests/test_users.py`, `tests/test_auth.py`, `tests/test_multiuser_scoping.py`, `tests/test_users_ui.py`, existing fixture/db/route tests
**Depends on:** Nothing; preserves #23's portfolio contracts per user
**Status:** in progress

---

## Tier 2.5 — Quick Extends (1 day each)

### 9. Dashboard Period Return Readout
Add a quiet, period-aware return directly above the dashboard chart while
keeping the header's live `Today` and cost-based `Total` facts unchanged. Use
the portfolio history endpoint's existing `twrr_pct`, not a first-to-last value
delta, so buys and sells cannot fake performance. The readout follows the
successfully painted 1D–MAX period in both Value and Performance modes, explains
that deposits and withdrawals are excluded, and degrades honestly when no
return is computable. The ledger's daily columns remain daily.

**Effort:** 1 day
**Files:** `templates/index.html`, `static/js/common.js`, `static/js/main.js`, `static/style.css`, `tests/test_period_return_ui.py`
**Depends on:** #13 (shipped) for `twrr_pct`
**Status:** shipped 2026-09-21 (PR #63)

---

### 13. Time-Weighted Return (TWR) Performance Chart
The dashboard's value chart is money-weighted (cost-basis %), so deposits dilute a real gain. Add a toggleable second view: a growth-of-$100 index computed by per-bar chaining with flows removed (every BUY = injection, SELL = withdrawal — there is no cash account). Reuses `portfolio_history`'s existing tx-absorption walk (flows fold where shares already fold); the reply gains `index_values` + `twrr_pct`. Full plan in `feature.md`. The rebase-to-100 + multi-dataset machinery built here is exactly what #7 (Benchmark Line) needs — doing this first makes #7 mostly plumbing.

**Files:** `app.py` (history route + pure helper), `static/js/common.js` (chart factory toggle), `static/js/main.js`, `templates/index.html`
**Depends on:** Nothing
**Status:** shipped 2026-09-16 (PR #45)

---

### 14. TWR Flow-Timing Alignment
Edge-case refinement to #13's mirror rule (found in PR #45's review round 2, non-blocking). The mirror rule gates per-SYMBOL ("ever priced in the window"), but flows are removed at the transaction's absorption LABEL. If a ticker's first bar in the window lands after its tx's absorption label (Yahoo data gap — plausible for small caps on 5D, or a MAX window where Yahoo's history for the ticker starts later than a logged buy), the flow is removed while the ticker still contributes 0 to values: a one-bar phantom dip that recovers next bar, and in the extreme (flow ≥ rest of portfolio) truncates the whole index at that bar. Fix: hold each symbol's flows in a pending accumulator and flush at the first label where the symbol actually prices — flow removal mirrors value entry per-BAR, not just per-symbol.

**Files:** `app.py` (flow fold in the `portfolio_history` walk), `tests/test_twrr.py` (regression tests)
**Depends on:** #13 (shipped)
**Status:** shipped 2026-09-20 (PR #59)

---

### 15. Allocation Carousel Pagination
Turn the dashboard's existing six-view allocation donut switcher into a clear
carousel: add clickable pagination dots, a current/total counter, accessible
active-page state, and a subtle reduced-motion-safe crossfade. Keep the current
single-canvas architecture, arrows, touch swipe, and saved position. Also load
a restored non-ticker view immediately and prevent stale async responses from
painting after rapid navigation.

**Files:** `templates/index.html`, `static/js/main.js`, `static/style.css`, `tests/test_allocation_ui.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-18 (PR #54)

---

### 20. Dashboard Market Overview Tabs
Move the dashboard's market snapshot above the complete portfolio and expand it
into a full-width tabbed strip. North America, Europe, Asia-Pacific, Crypto,
Commodities, and Currencies each show a small approved set of representative
instruments. Fetch and poll only the active category, preserve per-symbol
failure handling and native stock-detail links, use adaptive precision for
CAD-base currency pairs, and render a one-row horizontally scrolling instrument
strip on phones (a later design correction in PR #73 replaced the original
two-column phone grid).

**Effort:** 2 days
**Files:** `app.py`, `templates/index.html`, `static/js/main.js`, `static/style.css`, `project-brief.md`, `tests/test_routes.py`, `tests/test_market_tabs.py`, `tests/test_compare_ui.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-22 (PR #70)

---

### 24. Parallel Market Tab Preload
Start all six dashboard market-category requests in parallel on page load so a
completed tab opens without another network round-trip. Reuse a pending request
and short-lived successful panel data on tab changes; refresh only the selected
category on the normal poll. Keep per-category failure retries and response-order
guards.

**Effort:** 1 day
**Files:** `static/js/main.js`, `templates/index.html`, `project-brief.md`, `tests/test_market_tabs.py`, `tests/test_market_preload.py`
**Depends on:** #20 (shipped)
**Status:** shipped 2026-09-24 (PR #82)

---

## Tier 3 — Nice-to-Have (1–3 days each)

### 10. PWA Manifest — SCRAPPED (2026-09-12)
Attempted and reverted (commit `d4cd772`). Chrome only installs PWAs from a trusted-HTTPS secure context — unreachable for a LAN-only app without per-device CA installs or third-party infrastructure (Tailscale/Cloudflare/domain). Full postmortem in `feature.md`; do not re-attempt without first solving the trusted-cert problem.

---

### 11. Ticker Search Caching
Already has a rework trigger in `project-brief.md`. A dict with 30s TTL keyed by lowercased query. Prevents Yahoo rate-limiting on repeated searches.

**Files:** `market_data.py` (new cache dict + TTL check)
**Depends on:** Nothing

---

### 12. Stats Caching
`get_stats` isn't cached (one fetch per page load). A short-TTL cache (e.g., 1 hour) would reduce slow Yahoo `.info` calls. The quote cache pattern already exists.

**Files:** `market_data.py` (new cache dict + TTL)
**Depends on:** Nothing

---

### 25. Coin-Stack Brand Mark
Replace the inconsistent web logo set (a green sparkline navbar mark and a
blue/green Google-Finance-style bar-chart favicon) with one "coin stack with
growth arrow" mark drawn in the accent palette: ink-navy in light mode,
banknote gold in dark mode. Apply the mark to the navbar, the favicon, and
the master asset. Back up the existing logo first. The web mark takes its
color from `--accent`, which also frees green/red to mean market up/down
only. Android launcher icons are intentionally NOT changed in this item;
they are deferred to a later Android-only change.

**Effort:** 1 day
**Files:** `assets/logo/` (mark, icon, lockup, dated backup), `static/favicon.png`, `templates/base.html`, `static/style.css`, `tests/test_brand_assets.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-25 (PR #86)

---

## Dependency Graph

```
Tier 1 (all independent):
  1. Average Cost ─────────────────────┐
  2. CSV Export ───────────────────────┤
  3. Transaction Fees ─────────────────┤── can be done in any order
  4. Sector Breakdown (shipped) ───────┤
  5. Cash Balance ─────────────────────┤
  16. Android Biometric/PIN Lock ────────┤
  18. Ledger Quick Sell ─────────────────┤
  19. Date-Aware Price Auto-Fill ────────┤
  21. High-Value Operational Logging ────┤
  22. In-App Version Display ─────────────┘

Tier 2 (all independent of each other):
  6. Dividend Tracking ────────────────┐
  7. Benchmark Line ────── superseded ─┤── can be done in any order
  8. Multi-Currency ───────────────────┤   (#17 replaces #7)
  17. Comparison Overlays ──────────────┤
  23. Several Named Portfolios ─────────┤
  26. Multi-User Accounts ──────────────┘

Tier 2.5:
  9. Dashboard Period Return ─────────── depends on #13 (shipped)
  13. TWR Performance Chart ──────────── independent (its rebase-to-100
                                           machinery makes #7 cheaper)
  14. TWR Flow Timing ────────────────── depends on #13 (refines its flow fold)
  15. Allocation Carousel Pagination ─── independent frontend quick extend
  20. Dashboard Market Tabs ──────────── independent frontend/API quick extend
  24. Parallel Market Tab Preload ────── depends on #20 (shipped)

Tier 3 (all independent):
  11. Search Caching ──────────────────┐
  12. Stats Caching ───────────────────┤── can be done in any order
  25. Coin-Stack Brand Mark ────────────┘
```

---

## Suggested Implementation Order

For maximum compounding value:

1. **Transaction Fees** → makes cost basis realistic
2. **Average Cost** → displays the now-real cost basis (shipped)
18. **Ledger Quick Sell** → prepares an exact full-position sale for review from the ledger row
19. **Date-Aware Ledger Price Auto-Fill** → prices a logged transaction at its actual date
4. **Sector Breakdown** → deeper allocation insight (shipped)
5. **Cash Balance** → full portfolio picture
6. **Dividend Tracking** → most-requested feature in any portfolio app
7. **Benchmark Line** → context for performance (superseded by #17)
8. **Multi-Currency** → international expansion
17. **Comparison Overlays** → arbitrary ticker/portfolio comparison; replaces #7
9. **Dashboard Period Return** → shows the selected chart period's TWR without replacing live daily facts
13. **TWR Performance Chart** → honest performance measurement; builds the rebase-to-100 machinery #7 needs
14. **TWR Flow Timing** → tightens #13's mirror rule (edge-case correctness)
15. **Allocation Carousel Pagination** → clarifies the existing six allocation views
20. **Dashboard Market Overview Tabs** → puts broad live market context before the portfolio
21. **High-Value Operational Logging** → makes production failures, slow requests, and data changes diagnosable without exposing financial amounts
22. **In-App Version Display** → identifies the deployed web and Android release from one shared version source
23. **Several Named Portfolios** → separates ledgers and portfolio calculations (#26 later scoped them per person, replacing the shared watchlist)
24. **Parallel Market Tab Preload** → starts all market tabs together and reuses recent results on tab changes
26. **Multi-User Accounts** → login + ownership, so portfolios and the watchlist belong to a person
11. **Search Caching** → resilience
12. **Stats Caching** → performance
25. **Coin-Stack Brand Mark** → one consistent brand across web and Android

Back burner (user request): #2 CSV Export and #16 Android Biometric/PIN Lock.

---

## Not On This Roadmap

These are Ghostfolio features that don't fit Portfoliarr's scope:

- **Broker-account hierarchies** — #23 separates ledgers by portfolio and #26 separates them by person; no broker-account layer on top of either
- **AI assistant** — "no AI" in the project brief
- **FIRE calculator** — out of scope
- **Fear & Greed Index** — out of scope
- **Wealth items / liabilities** — not investment tracking
- **Bond tracking** — Yahoo Finance bond data is limited
- **Zen Mode** — nice but not essential
- **Multi-language** — English only by design
