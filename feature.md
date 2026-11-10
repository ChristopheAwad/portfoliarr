# Performance audit remediation, phase 1

Status: implemented, reviewed, and delivered 2026-11-10.
Branch: `fix/perf-harness-db-connections` from main `957875e`.
Base checkout `fix/audit-owner-security` stays untouched with its uncommitted
security work. The user chose NOT to ship the deferred-ledger prototype;
measure-first was the earlier decision and it remains just a measurement.

Audit source: the 2026-11-10 performance audit. The user rejected changes to
dashboard period preloading and Volume Leaders: the eight parallel chart
periods and all volume behavior stay exactly as they are.

Scope:

1. Repair the performance measurement fixtures and reporting.
2. Close SQLite connections deterministically.
3. Measure the ledger initial load and group expansion with a temporary
   prototype. No product ledger change without separate approval.
4. Later item-5 work (import batching, slow-provider budgets, stock metadata,
   asset loading) needs its own plan.

## Tests first

`tests/test_perf_harness.py` (new):

- The simulated history labels follow `PERIOD_MAP`: 1D, 5D, and 1M use
  `YYYY-MM-DD HH:MM`; 3M, 6M, YTD, and 1Y use dates; 5Y uses weekly dates;
  MAX uses monthly dates. No two same-day bars collide.
- The simulated stats, financials, events, and profile payloads contain the
  keys the real getters and page scripts read, and the stock page paints them.
- Empty financials/events and a missing profile degrade without a page error.
- A stubbed run of all four pages records zero unexpected console errors.
- `DB_PATH` is redirected before `app` is imported.
- `--out` writes only to the chosen path. The repository baseline files are
  unchanged by a test run.

`tests/test_db.py`:

- A read and a write each open and close exactly one real connection.
- A failing operation, a PRAGMA failure, and a failing commit each still
  close the connection.
- A successful write commits; an error rolls the whole transaction back,
  including multi-step setup and migration.
- Foreign keys stay enabled and the existing row_factory reads keep working.

## Implementation

1. `scripts/perf_server.py`: keep the throwaway database redirect, the Flask
   development server, and the app-level fixed-latency stub boundary. Align
   the fake payloads and labels with the current getters and `PERIOD_MAP`.
   Do not change `market_data.py`, `app.py` routes, `PERIOD_MAP`, or
   `MARKET_CATEGORIES`.
2. `scripts/measure_perf.py`: report the stub boundary honestly, surface
   console errors in the Markdown report, fail the run on an unexpected page
   error, and add the phone-width ledger measurement needed for item 3.
   Existing default `--out` behavior stays; tests write to `/tmp/opencode/`.
3. `db.py`: keep `_connect()` returning a raw connection. Close it when setup
   fails after the connection opens. Add a `contextlib.contextmanager`
   helper that enters the SQLite transaction context and closes in `finally`.
   Replace every `with _connect() as conn:` use with it. No schema,
   transaction-rule, or financial-math change.
4. Ledger measurement: throwaway scripts and synthetic data only. Compare the
   current render with an on-demand prototype at 1280x800 and 390x844, on
   0, 1, 1,000-same-group, and 1,000-across-10-row ledgers. Measure the
   setup-warmed initial visit and the first and second expansion, three runs
   per case. Keep server `group_*` totals, the `1e-9` tolerance, and short
   symmetry. Preserve the group and detail row behavior.

## Verification

```bash
.venv/bin/python -m pytest tests/test_perf_harness.py tests/test_db.py tests/test_perf.py
.venv/bin/python -m pytest
/usr/bin/python3 scripts/measure_perf.py --runs 1 --stub-ms 80 --settle 1 --port 53145 --out /tmp/opencode/portfoliarr-perf-check-1
```

Run the full suite against a disposable database. The Playwright checks use
throwaway data and stubbed market data. Save screenshots for the database
change and the ledger measurement.

Compatibility check: copy the dirty security working tree to a disposable
checkout without `instance/`, apply this diff there, and run the affected
owner, security, database, and harness tests. Stop and ask if a conflict is
not mechanical.

## Review log

Plan reviewer found no blockers after two revision rounds. Fixes: kept the
real cache boundary honest, removed the unneeded Gunicorn mode, defined the
warmed measurement language, preserved the dirty branch, and excluded
`instance/` from the compatibility copy.

Diff reviewer: two blockers, both fixed and re-reviewed with no remaining
blockers. They were the three-argument historical-FX stub and the missing
empty-financials/events/missing-profile degrade coverage. Final safe nits:
`--empty-stock` now requires `--stub-ms`, and viewport dimensions must be
positive.

## Results

### Harness repair

- `scripts/perf_stub.py` is the single source for the fake payloads. Labels
  come from `PERIOD_MAP`; stats carry `recommendation` (the missing string
  that used to crash `stock.js`), plus every getter key; financials and events
  match the routes; the profile carries the look-through keys.
- `scripts/measure_perf.py` records the viewport, synthetic ledger size, and
  first/second group expansion. It prints console errors, fails on them
  unless `--allow-console-errors`, reports the stub boundary honestly, rejects
  a bare "cold" reading, and never writes outside `--out`. `--python` names
  the Flask interpreter so the driver can stay on the system python.
- `tests/test_perf_harness.py` pins label shapes against `PERIOD_MAP`, stats
  key parity with the real getter, financials shape, events/profile shapes,
  the install boundary (including the three-argument `get_fx_rate_on`), the
  DB redirect order, a stubbed four-page smoke run with no page/console
  errors and no repo baseline or real-DB writes, and a degrade run where
  financials/events 404 and the stats grid is all nulls. The degrade run
  allows the page's handled console errors but forbids uncaught page errors.

### SQLite connection lifetime

- `db.py` keeps `_connect()` raw for monkeypatch compatibility and adds
  `_connection()`: `with conn` keeps the commit/rollback rules, `finally`
  closes. All 41 call sites in this tree use it. `_connect()` also closes if
  PRAGMA/metric setup fails after the connection opens.
- `tests/test_db.py` tracks real opens and closes on read, write, failed
  write, PRAGMA failure and commit failure. The commit failure is a real
  deferred foreign-key violation (Python 3.14 commits internally, so
  overriding `Connection.commit` cannot inject one). It also proves rollback
  leaves no row and foreign keys stay on.
- Measurements from the audit reproduce the leak: 1,000 synthetic user reads
  sampled a peak of 172 open descriptors before the fix.

### Ledger measurement (no product change)

Throwaway copies of the current tree and a deferred-detail prototype, served
from separate temp databases with stubbed quotes. Medians of three runs per
case. "Initial" is the setup-warmed first visit, not a cold start. The phone
width is a browser viewport, not an Android device.

| case | width | current initial | prototype initial | current 1st expand | prototype 1st expand | current DOM | prototype DOM |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 rows | 1280 | 349 ms | 148 ms | - | - | 2 | 2 |
| 1 row | 1280 | 295 ms | 113 ms | 11 ms | 17 ms | 48 | 25 |
| 1,000 same group | 1280 | 259 ms | 148 ms | 155 ms | 219 ms | 23,025 | 25 |
| 1,000 same group | 390 | 373 ms | 167 ms | 393 ms | 398 ms | 23,025 | 25 |
| 1,000 across 10 | 1280 | 622 ms | 160 ms | 45 ms | 30 ms | 23,250 | 250 |
| 1,000 across 10 | 390 | 261 ms | 158 ms | 29 ms | 30 ms | 23,250 | 250 |

Reading: deferring detail rows cuts the initial DOM from about 23,000 elements
to 25/250 and improves the warmed initial visit by roughly 0.1–0.46 s. The
cost moves to opening a group: the single 1,000-row group is about 65 ms
slower on desktop and about the same on the phone viewport; 100-row groups
are comparable. The 0-row and 1-row numbers are noisy (runs ranged from 85 ms
to 1.7 s), so only the large-ledger DOM and initial-visit differences are
meaningful. Screenshots show no visual difference for an expanded group.
Evidence: `/tmp/opencode/ledger-measure/results.json` and
`/tmp/opencode/ledger-measure/*.png`.

Decision: the prototype is not shipped. The user asked to measure first; the
product change needs separate approval. Recommendation: ship deferred detail
rows only if large ledgers matter more than the one-off pause on the first
opening of a very large group.

### Checks

- Perf worktree full suite: **1533 passed**.
- Combined disposable copy (pending owner/security changes + this work,
  excluding `instance/`): **1630 passed** after a mechanical merge of the
  `db.py` call sites. No conflict required a behaviour decision.
- Playwright smoke: four pages, zero console errors, no repository baseline
  files changed.
- Delivered as one squash commit to main. No live database change.
- Ledger product code, chart preloads, Volume Leaders, market categories,
  `PERIOD_MAP`, and money/FX rules are unchanged.
