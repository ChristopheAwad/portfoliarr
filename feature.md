# Feature: Test Suite (Unit + Integration)

## Status: ✅ COMPLETE — 58 tests passing

Ran `python -m pytest` → 58 passed (~17s after first-run warmup).
No application code was changed; tests only. Real `instance/` DB never
touched (all DB tests run against temp files).

## What was built

### 1. Tooling
- `pytest==9.1.1` pinned in `requirements.txt`
- `.gitignore` += `.pytest_cache/`
- `conftest.py` (project root): makes `from app import ...` work in
  tests + holds shared fixtures:
  - `fresh_db` — monkeypatches `db.DB_PATH` to a `tmp_path` SQLite file,
    runs `db.init()`; auto-restored per test
  - `client` — Flask test client built on `fresh_db`

### 2. `tests/test_validate_tx_fields.py` (12)
The shared POST/PUT validator: happy path + key translation
(date→transaction_date), type normalization, fractional qty,
parametrized date failures (missing / US format / Feb 30),
string price, **bool-is-int qty trap**, zero/negative, bad type.
Gotcha learned: error paths call `jsonify()` → tests must wrap calls
in `with app.app_context():`.

### 3. `tests/test_db.py` (11)
Round-trips, insertion-order + newest-first ordering, PRIMARY KEY
duplicate → IntegrityError, CHECK constraint rejects bad type
(defence in depth), delete/update return False on missing id,
**update touches only date/price/qty/type — ticker/currency immutable**.

### 4. `tests/test_market_data.py` (9)
yfinance faked via `monkeypatch` (patch where it's USED: `market_data.yf`).
Quote math, TTL cache hit/refetch, permanent name cache + fallback,
incomplete-data ValueError, daily/intraday label formatting.
Autouse fixture clears `_cache`/`_name_cache` (isolation).

### 5. `tests/test_routes.py` (26)
Flask test client + fake market data (absent dict key = "Yahoo down").
Contracts locked: 201/204/400/404/409/503 semantics, "aapl"→"AAPL",
PUT ignores ticker in body, 404-before-validation ordering, live gain
math on /api/transactions, indices partial-failure vs 503-all-fail,
portfolio-history buy/sell/unpriced-ticker math.
Gotcha learned: `from app import app` gives the Flask OBJECT, not the
module — must `import app as app_module` to patch route globals.

## Verification
- Full suite green; first run 86s (one-time pandas/numpy bytecode
  warmup), steady state ~17s; `pytest --durations=15` confirmed no
  test touches the network.

## Known gaps / future work
- Intraday branch of portfolio_history untested (depends on
  `date.today()` — brittle; needs clock injection first).
- Importing `app` still runs `db.init()` on the real DB once
  (harmless/idempotent). Proper fix = move `validate_tx_fields` and
  init into importable-without-side-effects modules (future refactor).
- `static/js/main.js` has no tests — needs a JS toolchain; out of MVP.
- Commands: run tests with `python -m pytest` (see AGENTS.md).
