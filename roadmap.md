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
**Depends on:** #57 (ships `BiometricGate.kt` and `SecretStore.kt`, which this reuses for the background-timeout half)
**Priority:** Back burner (user request)

---

### 57. Android Biometric Unlock (fingerprint replaces the login typing)
Offer an optional local lock on the Android APK. The first time the app opens
after a login exists, a single dialog offers fingerprint unlock; "No thanks"
is recorded permanently. Once armed, every COLD START runs `BiometricPrompt`
(fingerprint, falling back to the device PIN) and restores a saved session, so
the dashboard opens with no typing. Cancelling loads the password page at once
and floats three ways out on top of it: use my password / stop asking / forget
this phone. This is OFF BY DEFAULT on purpose — PR #75 shipped a lock enabled
and the user rejected that APK. The saved `session` cookie is encrypted with
AES-256-GCM under a non-exportable `AndroidKeyStore` key, and restored with
`HttpOnly; SameSite=Lax` so the app never downgrades the server's session
protections. The password form is untouched and is the automatic fallback. The
login is captured even while the feature is off, because the one-time offer is
impossible without it. NO server change: no route, no table, no new Python
dependency, no web UI change. Not WebAuthn/passkeys, which are blocked on this
deployment by plain HTTP, an IP-address RP ID, and the Android WebView. There
is no visible Settings gear: `MainActivity` hides the action bar and the gear
was removed at the user's request, so the dialogs are the reachable path.

**Effort:** 1–2 days
**Files:** `android/app/src/main/java/com/portfoliarr/app/BiometricGate.kt` (new), `android/app/src/main/java/com/portfoliarr/app/SecretStore.kt` (new), `android/app/src/main/java/com/portfoliarr/app/CookieHeader.kt` (new), `android/app/src/main/java/com/portfoliarr/app/StartGate.kt` (new), `android/app/src/main/java/com/portfoliarr/app/SessionControl.kt` (new), `android/app/src/test/java/com/portfoliarr/app/` (new), `android/app/src/main/java/com/portfoliarr/app/MainActivity.kt`, `android/app/src/main/java/com/portfoliarr/app/SettingsActivity.kt`, `android/app/src/main/res/layout/activity_settings.xml`, `android/app/src/main/res/values/strings.xml`, `android/app/src/main/AndroidManifest.xml`, `android/gradle/libs.versions.toml`, `android/app/build.gradle.kts`, `android/gradle.properties`, `.github/workflows/build-android.yml`, `tests/test_android_biometric.py`, `project-brief.md`, `AGENTS.md`, `README.md`
**Depends on:** Nothing
**Status:** shipped 2026-09-29 (PR #98)
**Revert:** if the on-device trial fails, the whole feature comes out of main
with `git revert f00a5b9` (the PR #98 merge). No server, web, or database code
was touched, so the revert stays inside `android/`, `tests/test_android_biometric.py`,
and docs. To return the phone itself to the old behaviour, uninstall the code-6
APK first — Android refuses a downgrade to the code-5 stock build — then install
the APK from branch `release/android-baseline-1.4` and re-enter the server URL once.

---

### 58. Android In-App APK Update
CI publishes each new phone build to a GitHub Release tagged
`android-<VERSION>-<VERSION_CODE>` with the APK and a `SHA-256:` line in the
notes. On every cold start, after the #57 unlock gate resolves, the app asks
the public releases API over HTTPS whether a strictly higher `versionCode`
exists and stays silent unless one does. An available update shows what is new
with Download / Later / Skip-this-version; the download streams to the
app-private cache with a cancelable progress box, then the file is hash-checked
and handed to the Android installer through a `FileProvider` that exposes only
that one directory. A missing or mismatched hash deletes the file and never
installs. Android always keeps its own final tap on Install — a fully silent
install is impossible — and its installer remains the signature authority. The
manual Check-for-update menu item ships as tested but dormant code beside the
unreachable Settings gear, because the action bar stays hidden. No server, web,
or database change.

**Effort:** 1–2 days
**Files:** `android/app/src/main/java/com/portfoliarr/app/UpdateGate.kt` (new), `android/app/src/main/java/com/portfoliarr/app/UpdateChecker.kt` (new), `android/app/src/main/java/com/portfoliarr/app/ApkDownloader.kt` (new), `android/app/src/main/java/com/portfoliarr/app/ApkInstaller.kt` (new), `android/app/src/test/java/com/portfoliarr/app/UpdateGateTest.kt` (new), `android/app/src/main/res/xml/file_paths.xml` (new), `.github/workflows/release-android.yml` (new), `tests/test_android_update.py` (new), `android/app/src/main/java/com/portfoliarr/app/MainActivity.kt`, `android/app/src/main/AndroidManifest.xml`, `android/app/src/main/res/menu/main_menu.xml`, `android/app/src/main/res/values/strings.xml`
**Depends on:** #57 (shipped; the cold-start check hooks after its gate)
**Status:** in progress

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

### 30. Holdings Age on the Ledger
Add a Days Held cell to each ledger ticker group: days elapsed from the current
open position's first buy to today (the replay is already in `app.py`'s group
aggregates, so it is a count, not new math). A crossed-then-reopened position
ages from the reopen buy. SELL-only groups stay blank, and the value sorts as
a number.

**Effort:** less than 1 day
**Files:** `app.py`, `static/js/ledger.js`, `templates/ledger.html`, `tests/test_ledger_groups.py`
**Depends on:** Nothing

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

### 36. Calendar-Year Realized Gains Report
The realized replay behind the Closed sales table already computes each sale's
CAD result from stored facts. Add a yearly grouping on top of it: for each tax
year, the per-ticker realized total and the year total, shown in a small card
below Closed sales on the ledger page. The grouping is a pure fold of the
existing replay, so it makes no quote or FX calls and never goes stale. A year
whose legs lack a usable rate degrades the same way single rows do, never a
fake 1:1.

**Effort:** 1–2 days
**Files:** `app.py` (realized route + pure grouping helper), `static/js/ledger.js`, `templates/ledger.html`, `tests/test_realized_annual.py`
**Depends on:** Nothing (reuses the shipped realized replay)

---

### 37. Total Return Readout (Realized + Unrealized)
The dashboard shows unrealized gain and the ledger shows realized-to-date, but
no single number answers "how much have I made in total". Combine the two into
one CAD figure (realized + unrealized) with the split shown in a caption. Both
values come from endpoints already loaded, so nothing new is stored. An
unpriced holding or a missing rate degrades the figure rather than assuming
1:1.

**Effort:** 1 day
**Files:** `app.py` (reuse summary + realized), `static/js/main.js`, `templates/index.html`, `tests/test_total_return.py`
**Depends on:** Nothing

---

### 39. Historical FX Backfill
Transactions logged before FX capture can carry a null `fx_rate`, which
degrades their ledger rows and realized legs. Add a terminal maintenance
command (`python app.py backfill-fx <username|--all>`) that finds USD rows
missing `fx_rate`, fetches the USDCAD close on each transaction's date through
the existing historical-FX path, and writes it. It never guesses: a date with
no bar stays null and is reported with its count. It uses historical bars only
(no live-rate fallback), so it cannot freeze an approximate rate as a fact.

**Effort:** 1 day
**Files:** `db.py`, `app.py`, `tests/test_fx_backfill.py`
**Depends on:** Nothing (#19 shipped the historical-bar path; #27 set the CLI command pattern)
**Status:** shipped 2026-09-27 (PR #90)

---

### 40. Calendar Returns Table
The TWR index returned by `/api/portfolio/history` is already flow-adjusted.
Turn it into a month and year returns table: month rows for roughly the last
year, year rows for the portfolio's life, each the percentage change of the
index across that span. The table reads `index_values`; it never re-derives
returns from raw value deltas, so buys and sells cannot fake a result.

**Effort:** 1–2 days
**Files:** `app.py` (pure chaining helper + reply field), `static/js/common.js`, `static/js/main.js`, `templates/index.html`, `tests/test_calendar_returns.py`
**Depends on:** #13 (shipped, provides `index_values`)

---

### 45. Ledger Trade Sanity Warnings
The ledger form checks field shape only. Add server-computed warnings returned
with the saved transaction: a date in the future, a SELL larger than the
position held at that date, and a same-day duplicate (same ticker, type,
quantity, and price). The write still happens; the form shows the warning so a
mistake is visible. This is separate from #31, which compares paste-imported
rows only.

**Effort:** 1 day
**Files:** `app.py` (warning helper in the transaction route), `static/js/ledger.js`, `templates/ledger.html`, `static/style.css`, `tests/test_trade_warnings.py`
**Depends on:** Nothing (#31 covers import rows only)
**Status:** shipped 2026-09-27 (PR #91)

---

### 47. Database Backup and Restore
A signed-in action in Preferences downloads the whole SQLite file, and a
matching upload replaces it after a typed confirmation and a schema check.
Download uses a consistent snapshot taken while no writes run. Restore is a
full replacement, not a merge, and refuses a file whose schema is newer than
the running app. On a home-LAN install any signed-in person may restore; the
typed confirmation and the schema guard are the only protections.

**Effort:** 1–2 days
**Files:** `db.py` (backup/restore helpers), `app.py` (routes), `static/js/preferences.js`, `templates/preferences.html`, `tests/test_backup_restore.py`
**Depends on:** #26 (shipped, for signed-in scope)

---

### 52. Ticker Page Fundamentals Expansion
The stock detail page's stats grid already fetches Yahoo's full company profile
but shows only 18 values. Add the rest to the SAME once-per-load call: forward
P/E, price/book, PEG, payout ratio; gross/operating/profit margin, return on
equity, revenue and earnings growth; total cash, total debt, debt/equity, free
cash flow, EBITDA; shares outstanding and float; target low/high/median,
analyst count, recommendation mean; country, quote type, website, employees,
and a business summary. Fraction ratios (payout, margins, ROE, growth) become
percent numbers at the data boundary; debt/equity is already scaled and stays
verbatim. No new endpoint, no new network call; a missing field shows "—".

**Effort:** 1 day
**Files:** `market_data.py`, `templates/stock.html`, `static/js/stock.js`, `static/style.css`, `tests/test_stock_stats.py`, `project-brief.md`
**Depends on:** Nothing
**Status:** shipped 2026-09-27 (PR #92)

---

### 53. Ticker Page Position Card
Show the signed-in person's holding in the security on its detail page: net
quantity, average cost, cost basis, live value, unrealized gain $/%, and the
day move, all in the security's NATIVE currency (matching the page's rule).
One new route, `GET /api/portfolio/position?symbol=<symbol>`, whose path sits
under `/api/portfolio/` so the existing ownership hook enforces it. The card
reads the active portfolio only; a symbol not held hides it, a failed quote
degrades to facts only, and USD without a rate shows no fake CAD. The ledger
fold is the same average-cost replay the group aggregates use, computed for
one symbol.

**Effort:** 1.5 days
**Files:** `app.py`, `templates/stock.html`, `static/js/stock.js`, `static/style.css`, `tests/test_stock_position.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-28 (PR #95)

---

### 54. Ticker Page Financials Table
Add a small income-statement table to the stock detail page: Total Revenue,
Gross Profit, Operating Income, Net Income, and Diluted EPS for the last four
fiscal years (Yahoo's annual `income_stmt`), plus a grouped-bar chart of the
same rows above the table. A new `get_financials(symbol)` in
the data layer returns raw native-currency floats and a long-TTL process cache;
a new `GET /api/stock/<symbol>/financials` route 404s only when the statement
is empty, and the frontend hides the table for securities with no statement
(ETFs, crypto, indices).

**Effort:** 2 days
**Files:** `market_data.py`, `app.py`, `templates/stock.html`, `static/js/stock.js`, `static/style.css`, `tests/test_stock_financials.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-28 (PR #93)

---

### 55. Ticker Page Dividends and Earnings
Add an "Events" cluster to the stock detail page: the next earnings date, the
ex-dividend and dividend dates, and the recent dividend history with a
trailing-12-month total. One new `get_events(symbol)` merges Yahoo's
`Ticker.calendar` with `Ticker.dividends` behind a process-memory cache; a new
`GET /api/stock/<symbol>/events` route serves it, and instruments with no
dividends or calendar (crypto, many growth ETFs) show the cluster hidden or
degraded, never fake dates.

**Effort:** 1.5 days
**Files:** `market_data.py`, `app.py`, `templates/stock.html`, `static/js/stock.js`, `static/style.css`, `tests/test_stock_events.py`
**Depends on:** Nothing
**Status:** shipped 2026-09-28 (PR #96)

---

### 56. Ticker Page Volume Bars
Draw trading volume under the stock page's price line. The stock history reply
gains a `volumes` array aligned to its labels, fetched without changing the
shared `get_history` the portfolio chart uses. The chart factory draws volume
as a bar dataset (on a hidden second y-axis behind the price line) only when a
reply carries volumes, so the dashboard chart is untouched. Reworked or
reverted freely if it fights the chart's existing hover/measure/cost plugins.

**Effort:** 2 days
**Files:** `market_data.py`, `app.py`, `static/js/common.js`, `static/js/stock.js`, `static/style.css`, `tests/test_stock_volume.py`
**Depends on:** Nothing

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
No open registration (owner opt-in came with #27), no roles. Login
throttling arrived later with the security audit.

**Effort:** 5 days
**Files:** `db.py`, `app.py`, `templates/base.html`, `templates/login.html`, `templates/setup.html`, `templates/preferences.html`, `static/js/common.js`, `static/js/preferences.js`, `static/style.css`, `conftest.py`, `project-brief.md`, `tests/test_users.py`, `tests/test_auth.py`, `tests/test_multiuser_scoping.py`, `tests/test_users_ui.py`, existing fixture/db/route tests
**Depends on:** Nothing; preserves #23's portfolio contracts per user
**Status:** shipped 2026-09-26 (PR #88)

---

### 28. Target Allocation with Drift
Set a target weight per holding inside each portfolio: one form on the ledger
page lists the portfolio's live tickers and takes whole-number targets that
sum to exactly 100 (a number input, a clear inline error, and nothing saved
otherwise). The dashboard allocation view and ledger group rows then show each
holding's delta CAD and delta percentage points versus target; unallocated
tickers are marked 0% and drift from the current mix only. Targets are deleted
with their portfolio and survive ticker changes untouched; clearing the form
saves a targetless portfolio and removes every mark. The server returns
`target_pct` per group from ledger data in the reply; the JS paints the delta.

**Effort:** 2 days
**Files:** `db.py` (new per-portfolio table), `app.py` (routes + drift in
group aggregates), `static/js/main.js`, `static/js/ledger.js`,
`templates/index.html`, `templates/ledger.html`, `tests/test_alloc_targets.py`

---

### 32. Server-Side User Preferences
Move the portable browser state into the user's account so phone and PC agree.
A `preferences` table keyed by user ID (`json TEXT DEFAULT '{}'`) stores each
signed-in person's ledger display mode, chart period and view, allocation
carousel page, and active portfolio choice. One pair of endpoints serves and
accepts the blob (`GET/PUT /api/preferences`, last write wins, plain enough to
autosave); `common.js` consults it before any saved localStorage value, and
the first signed-in run rebuilds the blob from whatever `localStorage` still
holds on that browser and clears it (no migration). Not carried: the privacy
toggles stay local-only by design, and Android stays cookie-only.

**Effort:** 1 day
**Files:** `db.py`, `app.py`, `static/js/common.js`, `static/js/main.js`,
`static/js/ledger.js`, `static/js/preferences.js`,
`tests/test_preferences.py`

---

### 33. Watchlist Target Prices
Add an optional target price to each watchlist row. A small input on the
watchlist row (and the same field on the stock page for a watched ticker)
sets it; the row's price cell tints when the live quote crosses the target
(green at or above a buy target, red at or below a sell target). The tint is
display-only: the stored fact is the target price, and the hit state is
computed from live quotes at paint time so it can never go stale. Which side
a target means (buy or sell) is implicit: a target below your cost basis is
a buy target, at or above it is a sell target. Nothing is ever sent: no
email, no push, no Android intent — the tint waits for someone to look.

**Effort:** 1 day
**Files:** `db.py` (nullable `target_price` on watchlist rows), `app.py`,
`static/js/main.js`, `static/js/stock.js`, `templates/index.html`,
`templates/stock.html`, `tests/test_watchlist_targets.py`

---

### 27. Account Recovery + Owner-Controlled Open Sign-Up
Close the two gaps #26 left on purpose. `python app.py reset-password
<username>` sets a new password for any account from the server terminal
(typed twice with hidden input, 8–128 chars, old password dies, so even the
only user can always get back in). A signed-in toggle in Preferences →
People ("Allow anyone on this network to sign up") stores `allow_signup`
in the `app_settings` table so it survives restarts; when on, the login
page shows a Create-an-account link and `/auth/signup` — a plain form page
like setup — creates a person with their own Main portfolio and signs them
in. Same validation ladder and uniform failure messages as setup/login;
the toggle and forged POSTs are re-checked server-side. Still no email,
no roles: home-LAN trust, now owner-opt-in. Login throttling (10 fails per
IP per 10 minutes) arrived later with the security audit.

**Effort:** 2 days
**Files:** `app.py`, `templates/login.html`, `templates/signup.html`,
`templates/preferences.html`, `static/js/preferences.js`,
`project-brief.md`, `tests/test_auth.py`, `tests/test_users_ui.py`
**Depends on:** #26 (shipped)
**Status:** shipped 2026-09-26 (PR #89)

---

### 29. Transaction Notes and Tags
Add an optional note and optional tags to each transaction. A NOTE is free
text the ledger shows on the transaction's detail row and nowhere else ("why
I bought", "stop-loss plan"). A TAG is a short saved word for grouping
("RRSP", "speculative"): the ledger form offers the portfolio's existing tag
names in a datalist (typing exactly the saved spelling), and the detail row
shows it as a passive chip; clicking a group row's chips filters that
ledger's detail rows to the tag. Tags live in a nullable text column on the
transaction row (comma-separated within one row is enough; no tag table). No
new endpoints beyond a per-portfolio tag list; fees (PR #79) set the
`ALTER TABLE` migration pattern.

**Effort:** 2 days
**Files:** `db.py`, `app.py`, `static/js/ledger.js`,
`templates/ledger.html`, `tests/test_tx_notes_tags.py`

---

### 42. Contribution to Return
For the selected chart period, show each holding's contribution to the
portfolio's TWR in percentage points. The `portfolio_history` walk already
prices every symbol at every bar, so record each symbol's start-of-window value
and its value change per bar, then divide by the portfolio's start value. A
reconciliation line shows the gap between the summed contributions and the
total return, which comes from flow timing. Shown as a small ranked list near
the chart.

**Effort:** 2–3 days
**Files:** `app.py` (pure fold helper + reply field), `static/js/main.js`, `templates/index.html`, `static/style.css`, `tests/test_contribution.py`
**Depends on:** #13 (shipped) for the flow-adjusted index

---

### 46. Stock-Split Adjustment
A split changes share count and average cost with no trade. Add a `SPLIT`
transaction type: a row stores the ratio, and the replays fold it by
multiplying quantity and dividing average cost, with no cash effect. Extend the
`transaction_type` CHECK constraint, the validator, the ledger form and display,
and both the average-cost replay (#1) and the realized replay. Existing rows
never change, and the split folds at its own date like any other fact.

**Effort:** 2–3 days
**Files:** `db.py` (CHECK constraint + migration), `app.py` (validator + replays), `static/js/ledger.js`, `templates/ledger.html`, `project-brief.md`, `tests/test_splits.py`
**Depends on:** Nothing (touches the average-cost and realized replays)

---

### 48. Broker-Specific CSV Import Maps
Paste import expects one generic shape (`parse_import_text`). Add named column
maps for common broker exports (for example a Questrade or Wealthsimple
activity CSV), chosen in the import panel. The maps live server-side and feed
the same `parse_import_text` path, so preview, commit, and duplicate detection
(#31) keep working. An unrecognized column set falls back to the generic parser
with a clear message.

**Effort:** 2–3 days
**Files:** `app.py` (map definitions + parser), `static/js/ledger.js`, `templates/ledger.html`, `tests/test_import_maps.py`
**Depends on:** Nothing (extends cleanly alongside #31)

---

### 51. Android Home-Screen Widget
A resizable widget shows one portfolio's total and day change. Since no app
process runs in a widget, it fetches a small read-only JSON on a WorkManager
schedule. Add a scoped, revocable read-only token tied to one portfolio when
the token is created in Preferences; the widget stores it locally. Refresh uses
Android's minimum interval (about 30 minutes) plus a manual tap.

**Effort:** 3–5 days
**Files:** `android/app/src/main/java/com/portfoliarr/app/widget/` (new), `android/app/src/main/AndroidManifest.xml`, `android/app/build.gradle.kts`, `android/app/src/main/res/xml/` (widget info), `app.py` (token endpoint), `db.py` (token table), `static/js/preferences.js`, `templates/preferences.html`, `tests/test_widget_token.py`
**Depends on:** #26 (shipped) for accounts; the token names its own portfolio, so it does not need #32

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

### 31. Import Duplicate Detection
Compare paste-imported rows against the portfolio's existing transactions
during the preview: a row is a duplicate when symbol, date, type, quantity,
native price, and fee all match an existing row (fees default to null on both
sides). The preview marks duplicated rows and adds a count line above the
commit buttons; commit stays all-or-nothing, so confirming the import of
flagged duplicates is one visible click. Tests cover a date written with
digit pairs transposed (the kind of mistype a duplicate check must not
silently wave through) and the null-fee-on-both-sides comparison.

**Effort:** 1 day
**Files:** `app.py` (`parse_import_text` reply), `static/js/ledger.js`,
`static/style.css`, `tests/test_import_duplicates.py`

---

### 34. Quick-Watch Star in Search
Add a star button to each result in the dashboard search dropdown: one click
adds the ticker to the signed-in person's watchlist and fills the star; a
second click removes it. No page navigation, no stock-page round trip, and
rows you already watch show a filled star from the existing watchlist cache.

**Effort:** less than 1 day
**Files:** `static/js/main.js`, `templates/index.html`, `static/style.css`,
`tests/test_search_star_ui.py`

---

### 50. Rebalance Share Counts
Extends #28. Where #28 shows each holding's drift from its target, this turns
the drift into a count. Given the portfolio total and each holding's live
price, show the whole number of shares to buy or sell to reach the target, plus
the cash to add or withdraw. Display only; the user still logs the trades. Uses
the target table from #28 and quotes already loaded. Lower priority.

**Effort:** 1 day
**Files:** `app.py` (share-count math in the allocation reply), `static/js/main.js`, `static/js/ledger.js`, `tests/test_rebalance.py`
**Depends on:** #28
**Priority:** Back burner (lower priority per user)

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

### 35. Android Pull-to-Refresh and Share
Two small native-client touches that keep business logic in the web app and
Kotlin to WebView lifecycle and navigation. First, swipe-to-refresh: Android
browsers refresh with a pull from the top of the screen but a WebView does
not, so wrap the existing WebView in a SwipeRefreshLayout that reloads when
the pull starts from the top. Second, share: a button on the stock detail
page opens the Android share sheet with the page's plain URL, so a ticker
page can be handed to someone through any installed app.

**Effort:** 1 day
**Files:** `android/app/src/main/java/com/portfoliarr/app/MainActivity.kt`, `android/app/src/main/res/values/strings.xml`, `android/app/src/main/res/drawable/` for the pull indicator tint, `templates/stock.html`, `static/js/stock.js`, Android tests

---

## Dependency Graph

```
Tier 1 (all independent; shipped dependencies are noted but do not block):
  1. Average Cost ─────────────────────┐
  2. CSV Export ───────────────────────┤
  3. Transaction Fees ─────────────────┤── can be done in any order
  4. Sector Breakdown (shipped) ───────┤
  5. Cash Balance ─────────────────────┤
  16. Android Biometric/PIN Lock ────────┤── #57 first: it ships the gate
  57. Android Biometric Unlock ───────────┤   and secret store this reuses
  58. Android In-App APK Update ──────────┤── needs #57's gate (shipped)
  18. Ledger Quick Sell ─────────────────┤
  19. Date-Aware Price Auto-Fill ────────┤
  21. High-Value Operational Logging ────┤
  22. In-App Version Display ────────────┤
  30. Holdings Age on the Ledger ────────┤
  36. Calendar-Year Realized Gains ──────┤
  37. Total Return Readout ──────────────┤
  39. Historical FX Backfill ────────────┤
  40. Calendar Returns Table (#13) ──────┤
  45. Ledger Trade Sanity Warnings ──────┤
  47. Database Backup and Restore (#26) ─┤
  52. Ticker Fundamentals ──────────────┤
  53. Ticker Position Card ─────────────┤
  54. Ticker Financials ────────────────┤
  55. Ticker Dividends/Earnings ────────┤
  56. Ticker Volume Bars ───────────────┘

Tier 2 (all independent of each other):
  6. Dividend Tracking ────────────────┐
  7. Benchmark Line ────── superseded ─┤── can be done in any order
  8. Multi-Currency ───────────────────┤   (#17 replaces #7)
  17. Comparison Overlays ──────────────┤
  23. Several Named Portfolios ─────────┤
  26. Multi-User Accounts ──────────────┤
  28. Target Allocation with Drift ─────┤
  29. Transaction Notes and Tags ───────┤
  42. Contribution to Return (#13) ─────┤
  46. Stock-Split Adjustment ───────────┤
  48. Broker-Specific CSV Import Maps ──┤
  51. Android Home-Screen Widget ───────┘

Tier 2.5:
  9. Dashboard Period Return ─────────── depends on #13 (shipped)
  13. TWR Performance Chart ──────────── independent (its rebase-to-100
                                           machinery makes #7 cheaper)
  14. TWR Flow Timing ────────────────── depends on #13 (refines its flow fold)
  15. Allocation Carousel Pagination ─── independent frontend quick extend
  20. Dashboard Market Tabs ──────────── independent frontend/API quick extend
  24. Parallel Market Tab Preload ────── depends on #20 (shipped)
  31. Import Duplicate Detection ─────── independent
  32. Server-Side User Preferences ───── independent
  33. Watchlist Target Prices ────────── independent
  50. Rebalance Share Counts ─────────── depends on #28

Tier 3 (all independent):
  11. Search Caching ──────────────────┐
  12. Stats Caching ───────────────────┤── can be done in any order
  25. Coin-Stack Brand Mark (shipped) ──┤
  34. Quick-Watch Star in Search ───────┤
  35. Android Pull-to-Refresh and Share ┘
```

---

## Suggested Implementation Order

For maximum compounding value:

1. **Transaction Fees** → makes cost basis realistic
2. **Average Cost** → displays the now-real cost basis (shipped)
39. **Historical FX Backfill** → repairs old rows so cost and realized math stop degrading
18. **Ledger Quick Sell** → prepares an exact full-position sale for review from the ledger row
19. **Date-Aware Ledger Price Auto-Fill** → prices a logged transaction at its actual date
4. **Sector Breakdown** → deeper allocation insight (shipped)
5. **Cash Balance** → full portfolio picture
6. **Dividend Tracking** → most-requested feature in any portfolio app
46. **Stock-Split Adjustment** → keep quantity and cost honest through a split
7. **Benchmark Line** → context for performance (superseded by #17)
8. **Multi-Currency** → international expansion
17. **Comparison Overlays** → arbitrary ticker/portfolio comparison; replaces #7
9. **Dashboard Period Return** → shows the selected chart period's TWR without replacing live daily facts
13. **TWR Performance Chart** → honest performance measurement; builds the rebase-to-100 machinery #7 needs
14. **TWR Flow Timing** → tightens #13's mirror rule (edge-case correctness)
40. **Calendar Returns Table** → month and year returns from the TWR index
42. **Contribution to Return** → which holdings drove the period
15. **Allocation Carousel Pagination** → clarifies the existing six allocation views
20. **Dashboard Market Overview Tabs** → puts broad live market context before the portfolio
21. **High-Value Operational Logging** → makes production failures, slow requests, and data changes diagnosable without exposing financial amounts
22. **In-App Version Display** → identifies the deployed web and Android release from one shared version source
23. **Several Named Portfolios** → separates ledgers and portfolio calculations (#26 later scoped them per person, replacing the shared watchlist)
24. **Parallel Market Tab Preload** → starts all market tabs together and reuses recent results on tab changes
26. **Multi-User Accounts** → login + ownership, so portfolios and the watchlist belong to a person
27. **Account Recovery + Sign-Up** → closes #26's two deliberate gaps (shipped)
28. **Target Allocation with Drift** → you set the mix, the app shows how far each holding has wandered from it
50. **Rebalance Share Counts** → target drift turned into shares to trade (back burner)
29. **Transaction Notes and Tags** → record why you traded; filter the ledger by tag
36. **Calendar-Year Realized Gains** → the tax-year view of results you already compute
31. **Import Duplicate Detection** → the preview flags rows you already logged so a double paste cannot double your cost basis
45. **Ledger Trade Sanity Warnings** → a future date, an oversell, or a duplicate surfaces at save
48. **Broker-Specific CSV Import Maps** → paste a broker export without reshaping it
32. **Server-Side User Preferences** → phone and PC stop disagreeing about display mode, chart period, and active portfolio
33. **Watchlist Target Prices** → the row tints when the live quote crosses your target
37. **Total Return Readout** → realized plus unrealized in one number
30. **Holdings Age on the Ledger** → days held per group, a count on aggregates that already exist
34. **Quick-Watch Star in Search** → add to the watchlist without leaving the dropdown
35. **Android Pull-to-Refresh and Share** → the two gestures phone users expect from a client app
57. **Android Biometric Unlock** → a fingerprint on cold start opens the app and restores the session, so the portfolio is private to you and the monthly password is gone
58. **Android In-App APK Update** → the phone notices, downloads, verifies, and offers to install new builds itself
52. **Ticker Fundamentals Expansion** → the cheap stock-page win: more numbers from the profile call the page already makes
53. **Ticker Position Card** → turns the page from "this security" into "your stake in this security"
54. **Ticker Financials Table** → revenue/profit/loss context behind the price
55. **Ticker Dividends and Earnings** → the dates and payouts a holder watches
56. **Ticker Volume Bars** → trading activity under the price line
51. **Android Home-Screen Widget** → the portfolio total on the launcher
47. **Database Backup and Restore** → a copy of the whole ledger you can put back
11. **Search Caching** → resilience
12. **Stats Caching** → performance
25. **Coin-Stack Brand Mark** → one consistent brand across web and Android

Back burner (user request): #2 CSV Export, #16 Android Biometric/PIN Lock (now only the background-timeout half; #57 shipped the gate it reuses), and #50 Rebalance Share Counts.

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
