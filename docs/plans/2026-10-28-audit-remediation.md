# Remediation plan for the 2026-10-28 Portfoliarr audit

Status: **proposed plan; awaiting reviewer and owner approval**. This PR
changes documentation only. Do not implement, merge, deploy, or modify a
real portfolio database as part of plan review.

Evidence: [bug audit](../audits/2026-10-28-bug-audit.md).

## Goals and non-negotiable decisions

1. Preserve existing ledger facts and per-user portfolio isolation.
2. Make import retries safe without prohibiting intentionally identical
   transactions.
3. Make degraded market data conspicuous rather than presenting partial
   valuations as a complete portfolio.
4. **Owner model (explicit owner decision):** the first account created
   during first-run setup is the single owner. Accounts created thereafter
   are regular users. Regular users have no account/registration admin
   permissions, cannot mutate installation-wide classification settings,
   and cannot delete or modify another user's records.
5. Keep production Gunicorn behavior and Android WebView sign-in working.
6. Add regression tests that fail before each fix; run the full suite on
   every implementation PR. Use disposable SQLite fixtures and market stubs.

This plan intentionally splits implementation into **five reviewable PRs**.
Each phase starts only after its plan/diff review is accepted. Changes to
database schema and monetary definitions receive explicit owner approval.

## Phase 0 — Pre-implementation safeguards and baseline

- Rebase the implementing branch on current `main` before each phase. The
  original evidence was reproduced at `a6870a0`; current plan base is
  `85ff828`, which introduced hourly 1M chart data.
- Record baseline full test count and capture API shapes; verify the
  development image starts without any real database mounted.
- Before schema/data changes, stop the service and take a consistent SQLite
  backup including WAL state (or use SQLite's online backup API with explicit
  consistency verification); document the exact named-volume backup and
  restore commands, and rehearse both against a disposable copy. A file copy
  of an active SQLite database alone is **not** a sufficient backup. Never
  run migration probes on the live volume.
- Track all nine audit IDs in PR checklists; separate **confirmed defects**
  from AUD-08's unresolved performance-definition decision.

## Phase 1 — Owner/regular-user authorization and session hardening

Targets: **AUD-03, AUD-04, AUD-05, AUD-09**. Highest priority because ordinary
users can delete someone else's data or alter shared classification settings,
and setup is not an atomic owner claim.

### Schema and migration

1. Add a persistent `users.role` (`owner` or `user`) with a checked default
   of `user`. Introduce a partial unique index permitting at most one owner.
   Keep a DB-layer guard against deleting/demoting the last owner.
2. Fresh setup creates the first account as `owner`; both owner-created
   accounts and self-signup accounts are always `user`. Implement a **single
   `BEGIN IMMEDIATE` transaction** that rechecks `count_users() == 0` inside
   the write lock, inserts the owner, claims the legacy unowned portfolio
   and watchlist, or seeds Main, and commits all changes together. Do not
   call the existing `create_user()`/`claim_unowned_data()` helpers as
   independently committed transactions. A losing concurrent setup POST
   must receive 409 even with a different username, never create a user.
3. Existing installation migration: assign `owner` to user ID `1` **only
   if that record exists** (its ID identifies the original first account
   in an intact database). If user 1 is absent or account history is
   ambiguous, do not promote the lowest surviving ID silently. Provide
   a local, operator-only owner-recovery/assignment command and document
   the one-time recovery path. Until resolved, fail closed for admin writes
   without blocking ordinary login and private portfolio reads.
4. Make migration idempotent, transactional and safe across restarts;
   explicitly test old schemas and partially migrated cases. No default
   user should ever acquire owner rights through a missing/NULL role. The
   unique-owner index is defense in depth, **not** a substitute for the
   setup transaction's empty-table check.

### Authorization and UI

5. Centralize an owner-only authorization guard returning JSON 403 to
   authenticated regular users (401 remains for signed-out callers). Load
   the authoritative role from SQLite on each request; **never** trust a
   role cached in the session or supplied by the browser. Apply it to:
   - `GET /api/users`, `POST /api/users` and `DELETE /api/users/<id>`;
   - `POST /api/auth/signup-toggle` (the read-only GET may remain available);
   - `PUT /api/fund-classification/<symbol>` and
     `DELETE /api/fund-classification/<symbol>`; read-only GET remains shared;
   - any owner-management/recovery API introduced in implementation.
   Make any ordinary user's own-account identity available separately if
   the UI needs it; never expose the all-users list to regular accounts.
6. Keep `POST /api/auth/password` available to regular users **for their
   own password only**, along with their existing portfolios, watchlist,
   transactions and widget tokens.
7. Forbid deleting/demoting the owner in the browser. Do not add an
   owner-transfer UI without separate approval. Owner recovery stays a
   local operator action. Preserve the current no-self-delete policy for
   regular users unless the owner explicitly changes it.
8. Hide or replace owner-only People/sign-up controls in regular-user
   Preferences **and shared fund-classification edit/delete controls**
   (`static/js/stock.js`); retain read-only classification views. Treat
   server-side checks as authoritative, not JavaScript visibility.
9. For cookies without a password-version marker, require a fresh login
   rather than upgrading an unversioned cookie on access; changing a
   password must invalidate every other session, including pre-upgrade
   ones. Tell users they may need to log in once after deployment.
10. As part of the first security implementation PR, change the direct
    `python app.py` developer launch to bind `127.0.0.1`, with any debugger
    explicitly opt-in and loopback-only; keep production Gunicorn unchanged.

### Required tests / acceptance

- Fresh-first user is owner; second and subsequent users are regular.
- An owner can create/delete a regular user, control self-registration,
  and still use their own ledger.
- A regular user receives 403 on `GET /api/users` and every admin mutation,
  including forged JSON requests and a known owner ID; cannot delete owner
  data or PUT/DELETE another user's shared fund-classification view. Owner
  classification edits still work, and read-only GET remains available.
- A regular user can change their *own* password and use *their own*
  portfolios/watchlist/widget tokens; cross-user data remains 404/403.
- Two concurrent first-run setup POSTs with distinct usernames result in
  **exactly one** owner/account and one claim/seed of orphaned data; the
  other request gets 409. Test with separate clients and overlapping entry
  windows, plus an interrupted setup transaction that rolls back fully.
- No owner can be deleted or silently replaced; migration and recovery
  scenarios are deterministic, including ID 1 absent, existing role data,
  and mixed-version session cookies.
- Old unversioned cookies are rejected **immediately after deployment**,
  whether or not a password changed; current versioned sessions still
  function and other sessions are revoked after password changes.
- The dev server binds loopback and does not expose the debugger to LAN.
- UI tests for owner vs regular visibility and API denial, plus full suite.

## Phase 2 — Idempotent transaction imports and numeric safety

Targets: **AUD-01, AUD-06**.

1. Add a client-generated import idempotency key retained across retries
   of the **same** commit attempt, scoped by user + portfolio, with a DB
   uniqueness constraint and a canonical request-body hash. The same key
   and hash return the *original* stored receipt; the same key with changed
   content returns 409, including after a partial-success response. A new
   intentional import gets a new key. A retry of failed rows must likewise
   use a fresh key and a **failed-rows-only** payload.
2. Check the persisted completed receipt **before any quote, FX or other
   external provider calls**, so successful retries work even during a
   market-data outage. For new keys only, prepare market data outside the
   write transaction. Then acquire `BEGIN IMMEDIATE`, recheck the key/hash
   under the write lock to resolve concurrent requests, write eligible
   rows and the result receipt, and commit together. Refactor
   `db.add_transaction()` (currently opens a new connection per row) so
   import writes join the **same connection/transaction** as the receipt.
   Use per-row savepoints if preserving best-effort import semantics;
   receipt insertion failure must roll back all new rows. A crash or lost
   response after commit must return the original result on replay.
3. Keep duplicate comparison in preview as a warning; do **not** add a
   five-field uniqueness constraint that would reject legitimate identical
   trades. Preserve row-level success/error positions in the receipt.
   After partial success, the UI must explicitly offer **Retry failed rows**
   with only failed records selected; re-uploading the entire corrected
   paste under a new key can reimport successes and must be warned against.
4. Retain completed idempotency receipts for the lifetime of the owning
   portfolio, or formally approve an expiration/tombstone strategy that
   will not silently admit replay of an old successful key. User/portfolio
   deletion must cascade cleanup of receipts and any bounded payload data.
5. Validate numeric range/derived arithmetic at the API write boundary.
   Positive finite operands are insufficient if `price * qty` overflows;
   make unsafe transactions return an actionable 400. Keep fractional
   shares and realistic high-priced securities supported.
6. Add finite-number checks at response-computation boundaries to safely
   degrade legacy/manual DB anomalies. Require standards-compliant JSON
   (no `NaN`/`Infinity`) across financial endpoints; prefer clear failure
   markers to plausible-looking zero values.

### Required tests / acceptance

- Same import key committed twice, serially and concurrently: exactly one
  set of ledger writes and the same receipt.
- Successful replay returns the original receipt with all quotes/FX
  providers unavailable; changed payload with old key returns 409 **before**
  market calls or ledger writes.
- Lost-response retry and partial import failure: no duplicates; failed
  rows remain identifiable and retryable **without successful rows** under
  a fresh key; test erroneous whole-paste retry warnings.
- Concurrent same-key submissions yield one persisted result; injected
  receipt-write error rolls back all associated transaction inserts.
- Identical trades with distinct intentional request keys remain possible.
- Cross-user/portfolio key collisions cannot reveal or alter data.
- Overflow payload receives 400; no financial API returns nonstandard
  JSON tokens after malformed persisted data.
- Ledger/portfolio UI still handles valid fractional shares and fees.

## Phase 3 — Honest history and cross-market time alignment

Targets: **AUD-02, AUD-07**. Work with the latest 1M hourly mode.

1. Change history response semantics to expose which symbols failed and
   whether **each bar** is complete relative to tickers actually held at
   that instant. A global `partial` boolean alone cannot express changing
   holdings and data coverage. Decide a clear UI state: warning plus
   explicitly partial bars/lines, or an unavailable chart until sources
   recover. Never present a partial sum as the complete portfolio total.
2. Value and comparison cost lines must describe a consistent priced
   universe, or the overlay must explicitly label costs that include
   unpriced positions. Do not silently turn a missing quote into zero
   economic value. Preserve legitimate historical zero/short positions.
3. Retain timezone-aware/UTC instants as the history alignment keys for
   1D, 5D and now hourly 1M; convert to display-local labels only at
   presentation. Take special care with exchange-local trade dates,
   weekends, DST transitions and mixed-exchange portfolios. Define exactly
   how a date-only trade is activated on a UTC intraday timeline, including
   its market's timezone, pre-open and after-hours behavior.
4. Update chart serialization and frontend interpolation/tooltip logic
   together. Maintain deterministic ordering, benchmark reconciliation,
   cost line and TWR behavior. **Do not chain a TWR return through any
   incomplete valuation bar**; mark such intervals unavailable and resume
   only when a well-defined complete valuation anchor exists. Avoid
   breaking cache keys silently.

### Required tests / acceptance

- Two tickers, one Yahoo timeout: user-visible partial/unavailable state;
  no unlabeled false loss; summary/history discrepancy is explained.
- Coverage changes as holdings are bought/sold: completeness applies only
  to active holdings at each bar; TWR does not bridge missing-price bars.
- All histories fail: explicit unavailable/empty state; no false zero.
- New York and Tokyo 09:30 bars do **not** map to the same instant.
- Repeated-hour DST transitions, pre-open bars, weekend buys and partial
  trading days remain ordered and apply trades once.
- 1D, 5D and 1M modes, value/performance, comparison and mobile chart
  smoke tests pass.

## Phase 4 — CAD performance definition and implementation

Target: **AUD-08**. **Blocking product decision before implementation**:

- **Recommended:** CAD value, CAD daily gain and CAD-denominated TWR should
  incorporate historical FX movements, using previous CAD market value
  and dated exchange-rate bars. Document how missing historical FX
  degrades, and cache/batch lookups to avoid per-ticker network fan-out.
- **Alternative:** intentionally report price-only performance in native
  trading currencies, but define the aggregation: a mixed CAD/USD
  portfolio has no meaningful single unweighted "native-currency return".
  Specify per-position currency weighting, baseline conversion and flow
  treatment, label it clearly, and stop implying that the CAD daily move
  equals true CAD P&L. Keep CAD total-value conversion separate.

The owner and reviewer must choose one before formulas change; avoid
quietly redefining a metric. If the recommended path is approved:

1. Specify FX timestamps and valuation-day boundaries across trading
   holidays, intraday bars and weekend crypto. Convert **both holdings
   and external cash flows** at their respective historical FX times for
   CAD TWR; state a no-lookahead rule and an explicit missing/holiday FX
   fallback. Retain date-specific FX facts for cost basis.
2. Update summary day gain, previous-close line, historical values and
   performance flow math consistently; do not mix current rates on past
   bars with historical rates on adjacent bars.
3. Use deterministic tests: constant USD share price + changing FX must
   show the correct CAD change; flat FX must preserve existing results;
   CAD-only portfolios must not make FX calls. Include a mixed CAD/USD
   portfolio with a cash flow between two FX timestamps and an FX holiday.
4. Add cross-currency regression and clear handling for unavailable FX.

Not in scope without a separate decision: dividends, stock splits, other
quote currencies, tax/accounting methodology, or cash-balance tracking.

## Phase 5 — Deployment verification and rollout

Targets: final integration validation of all earlier phases; **AUD-04
developer debugger hardening lands in Phase 1**, not at the end.

1. Verify auth and cookies behind the *actual* deployment topology
   before external exposure. HTTPS termination may warrant Secure cookies
   and proxy settings; avoid breaking existing HTTP-only LAN access.
2. Run full tests, JS tests, security lint, Docker smoke tests and a
   logged-in Android WebView/widget regression pass where SDK/device
   tooling exists. Do not claim Android native test coverage when absent.
3. Stage a migration rehearsal against a *copy* of a representative
   existing database, confirm original row counts, portfolio ownership,
   one-owner invariant, role-based access, legacy-session behavior and
   restore procedures, then roll out with a stopped-service backup and
   explicit rollback window. Rehearse a **restore**, not just a backup.

### Release gate

- All audit IDs have a closing regression or an explicit documented
  owner-approved product decision.
- Security matrix green for all users/classification endpoints; two-client
  setup race green; import concurrency/replay tests green; old and current
  session-cookie tests green; migration verifies exactly one owner.
- CI green, migration rehearsal green, reviewer approves full diff.
- No merge/deploy/live-data mutation until separately authorized.

## Reviewer decisions requested

1. **Owner recovery/transfer:** Is ID-1-only automatic migration plus a
   local operator recovery command sufficient? No ownership transfer UI
   is proposed.
2. **Account visibility (proposed default):** `GET /api/users` is
   owner-only; ordinary users may access only their own identity using a
   separate existing/new current-user response. Flag any dependent feature
   before implementation rather than widening account enumeration.
3. **CAD performance:** Choose historical-FX-inclusive CAD returns
   (recommended) or explicitly security-price-only returns.
4. **Partial chart:** Prefer a clearly labeled partial chart or a
   temporarily unavailable chart during missing holdings?
5. **Rollout:** Confirm that existing users can tolerate one re-login
   after versioned-cookie tightening and that a database backup can be
   taken before schema migration.

## Delivery protocol

- This is **plan PR 0**, documentation only. Review and revise it first.
- Each implementation phase gets its own branch/PR and independent diff
  review. Land only after approval, in order, to keep regression search
  and rollback manageable.
- Before each PR, update this plan if its approved decisions or upstream
  code changed. Never treat this report as permission to manipulate a
  deployed user's data.
