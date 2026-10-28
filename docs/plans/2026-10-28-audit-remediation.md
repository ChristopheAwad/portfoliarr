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
   permissions and cannot delete or modify another user's records.
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
- Before schema/data changes, document an offline backup/restore procedure
  for `instance/portfolio.db` / the Docker named volume. Test restoration
  against a disposable copy. Never run migration probes on the live volume.
- Track all eight audit IDs in PR checklists; separate **confirmed defects**
  from AUD-08's unresolved performance-definition decision.

## Phase 1 — Owner/regular-user authorization and session hardening

Targets: **AUD-03, AUD-05**. Highest priority because ordinary users can
currently delete someone else's data.

### Schema and migration

1. Add a persistent `users.role` (`owner` or `user`) with a checked default
   of `user`. Introduce a partial unique index permitting at most one owner.
   Keep a DB-layer guard against deleting/demoting the last owner.
2. Fresh setup creates the first account as `owner`; both owner-created
   accounts and self-signup accounts are always `user`.
3. Existing installation migration: assign `owner` to user ID `1` **only
   if that record exists** (its ID identifies the original first account
   in an intact database). If user 1 is absent or account history is
   ambiguous, do not promote the lowest surviving ID silently. Provide
   a local, operator-only owner-recovery/assignment command and document
   the one-time recovery path. Until resolved, fail closed for admin writes
   without blocking ordinary login and private portfolio reads.
4. Make migration idempotent, transactional and safe across restarts;
   explicitly test old schemas and partially migrated cases. No default
   user should ever acquire owner rights through a missing/NULL role.

### Authorization and UI

5. Centralize an owner-only authorization guard returning JSON 403 to
   authenticated regular users (401 remains for signed-out callers).
   Apply it to:
   - `POST /api/users` and `DELETE /api/users/<id>`;
   - `POST /api/auth/signup-toggle`;
   - any owner-management/recovery API introduced in implementation.
   Consider making `GET /api/users` owner-only, since it powers the admin
   People card; no regular-user feature should depend on that list.
6. Keep `POST /api/auth/password` available to regular users **for their
   own password only**, along with their existing portfolios, watchlist,
   transactions and widget tokens.
7. Forbid deleting/demoting the owner in the browser. Do not add an
   owner-transfer UI without separate approval. Owner recovery stays a
   local operator action. Preserve the current no-self-delete policy for
   regular users unless the owner explicitly changes it.
8. Hide or replace owner-only People/sign-up controls in regular-user
   Preferences, but treat server-side checks as authoritative. Avoid
   relying on JavaScript visibility for access control.
9. For cookies without a password-version marker, require a fresh login
   rather than upgrading an unversioned cookie on access; changing a
   password must invalidate every other session, including pre-upgrade
   ones. Tell users they may need to log in once after deployment.

### Required tests / acceptance

- Fresh-first user is owner; second and subsequent users are regular.
- An owner can create/delete a regular user, control self-registration,
  and still use their own ledger.
- A regular user receives 403 on every admin mutation, including forged
  JSON requests and a known owner ID; cannot delete owner data.
- A regular user can change their *own* password and use *their own*
  portfolios/watchlist/widget tokens; cross-user data remains 404/403.
- No owner can be deleted or silently replaced; migration and recovery
  scenarios are deterministic, including ID 1 absent.
- Old unversioned cookies are rejected after a password change; current
  versioned sessions still function and other sessions are revoked.
- UI tests for owner vs regular visibility and API denial, plus full suite.

## Phase 2 — Idempotent transaction imports and numeric safety

Targets: **AUD-01, AUD-06**.

1. Add a client-generated import idempotency key retained across retries
   of the **same** commit attempt, scoped by user + portfolio. Record a
   canonical text/body hash with its result; the same key + same payload
   returns the original receipt, while reusing a key with changed content
   returns 409. A *new* intentional import gets a new key.
2. Persist the import receipt and row writes atomically. Prepare quotes
   and FX data before the SQLite write transaction; consider savepoints
   to retain the existing best-effort per-row error semantics. A crash
   after commit must be replay-safe, not half-recorded.
3. Keep duplicate comparison in the preview as a warning; do **not** add
   a five-field uniqueness constraint that would reject legitimate
   identical trades. Expose an unambiguous receipt for valid/failed rows.
4. Set an explicit retention/cleanup policy for stored idempotency keys,
   and ensure deleting a user/portfolio cleans up their receipts.
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
- Lost-response retry and partial import failure: no duplicates; failed
  rows remain identifiable and intentionally retryable.
- Identical trades with distinct intentional request keys remain possible.
- Cross-user/portfolio key collisions cannot reveal or alter data.
- Overflow payload receives 400; no financial API returns nonstandard
  JSON tokens after malformed persisted data.
- Ledger/portfolio UI still handles valid fractional shares and fees.

## Phase 3 — Honest history and cross-market time alignment

Targets: **AUD-02, AUD-07**. Work with the latest 1M hourly mode.

1. Change history response semantics to expose which symbols failed and
   whether the series is complete. Decide a clear UI state for partial
   history: warning plus explicitly partial lines, or an unavailable
   chart until enough sources recover. Never present a partial sum as
   the complete portfolio total.
2. Value and comparison cost lines must describe a consistent priced
   universe, or the overlay must explicitly label costs that include
   unpriced positions. Do not silently turn a missing quote into zero
   economic value. Preserve legitimate historical zero/short positions.
3. Retain timezone-aware/UTC instants as the history alignment keys for
   1D, 5D and now hourly 1M; convert to display-local labels only at
   presentation. Take special care with exchange-local trade dates,
   weekends, DST transitions and mixed-exchange portfolios.
4. Update chart serialization and frontend interpolation/tooltip logic
   together. Maintain deterministic ordering, benchmark reconciliation,
   cost line and TWR behavior. Avoid breaking cache keys silently.

### Required tests / acceptance

- Two tickers, one Yahoo timeout: user-visible partial/unavailable state;
  no unlabeled false loss; summary/history discrepancy is explained.
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
  trading currencies, but label it clearly and stop implying that the
  CAD daily move equals true CAD P&L. Keep CAD total-value conversion
  separate from this stock-only return concept.

The owner and reviewer must choose one before formulas change; avoid
quietly redefining a metric. If the recommended path is approved:

1. Specify FX alignment across trading holidays, intraday bars and
   weekend crypto; retain date-specific FX facts for cost basis.
2. Update summary day gain, previous-close line, historical values and
   performance flow math consistently; do not mix current rates on past
   bars with historical rates on adjacent bars.
3. Use deterministic tests: constant USD share price + changing FX must
   show the correct CAD change; flat FX must preserve existing results;
   CAD-only portfolios must not make FX calls.
4. Add cross-currency regression and clear handling for unavailable FX.

Not in scope without a separate decision: dividends, stock splits, other
quote currencies, tax/accounting methodology, or cash-balance tracking.

## Phase 5 — Development hardening and rollout

Target: **AUD-04**, plus integration validation of earlier phases.

1. Bind the ordinary Flask developer command to `127.0.0.1`; make any
   interactive debugger opt-in and loopback-only. Keep Gunicorn's
   container bind unchanged.
2. Verify auth and cookies behind the *actual* deployment topology
   before external exposure. HTTPS termination may warrant Secure cookies
   and proxy settings; avoid breaking existing HTTP-only LAN access.
3. Run full tests, JS tests, security lint, Docker smoke tests and a
   logged-in Android WebView/widget regression pass where SDK/device
   tooling exists. Do not claim Android native test coverage when absent.
4. Stage a migration rehearsal against a *copy* of a representative
   existing database, confirm row counts/ownership and restore procedures,
   then roll out with an explicit backup and rollback window.

### Release gate

- All audit IDs have a closing regression or an explicit documented
  owner-approved product decision.
- CI green, migration rehearsal green, reviewer approves full diff.
- No merge/deploy/live-data mutation until separately authorized.

## Reviewer decisions requested

1. **Owner recovery/transfer:** Is ID-1-only automatic migration plus a
   local operator recovery command sufficient? No ownership transfer UI
   is proposed.
2. **Account visibility:** Should regular users see only their own
   account identity, while `GET /api/users` becomes owner-only?
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
