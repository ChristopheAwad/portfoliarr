# AGENTS.md

## Read first
- `project-brief.md` — authoritative spec (stack, UI, MVP scope); takes precedence over assumptions.
- `feature.md` — context file for the feature in progress; read it before resuming work. If empty and we're starting to work on a new feature, populate it first with subtasks.
- Design decisions that outlive a feature go in their permanent home: the "why" lives in code comments next to the code, cross-cutting rules go in `project-brief.md`'s Design Rules section. Never leave durable rationale only in `feature.md` — it's wiped per feature, so no long-lived file may reference it.

## Stack & architecture
- Flask serves JSON; the browser does all rendering (vanilla JS `fetch` + DOM, no framework).
- Layering: `market_data.py` = data layer (yfinance + caching, knows nothing about Flask); `db.py` = persistence layer (SQLite, knows nothing about Flask/yfinance); `app.py` = routes (decides WHICH symbols); `static/js/main.js` = rendering only.
- Timeframe buttons (1D–MAX) and `/api/portfolio/history` both go through `PERIOD_MAP` (`market_data.py`) — the route validates client-supplied period keys against it. Adding a timeframe = edit it there once.
- Quote cache is an in-memory dict in `market_data.py` (TTL 120s), deliberately NOT SQLite despite the brief's stack table. Dies on restart — acceptable. Rework trigger documented in `project-brief.md`.
- SQLite DBs go in `instance/` (gitignored, per Flask convention).

## Commands
- Activate venv: `source .venv/bin/activate`
- Run dev server: `python app.py` (debug mode, port 5000)
- Verify live data: `curl http://localhost:5000/api/indices`

## Testing
- Run: `python -m pytest` from the project root. Test files live in `tests/`; shared fixtures (`fresh_db`, `client`) in root `conftest.py`.
- Tests never touch the real `instance/` DB — `fresh_db` monkeypatches `db.DB_PATH` to a per-test `tmp_path` file.
- Patch names WHERE THEY'RE USED, not where they're defined: `market_data` calls `yf` → `monkeypatch.setattr(market_data, "yf", Fake)`; routes call imported `get_quote`/`get_name`/`get_history` → patch on the module: `import app as app_module`, then `monkeypatch.setattr(app_module, "get_quote", ...)`. (`from app import app` binds the Flask object, not the module — classic trap.)
- Validator error paths call `jsonify()`, which needs app context → wrap calls in `with app.app_context():`.
- Importing `app` runs `db.init()` on the real DB once — harmless (idempotent).
- First run is slow (~90s pandas/numpy warmup), steady state ~17s. No test touches the network.

## Git & GitHub
- Repo: `ChristopheAwad/portfoliarr`, remote `origin` over HTTPS. Default branch `main` tracks `origin/main` — plain `git push` / `git pull` just work.
- Auth is handled by the `gh` CLI credential helper (token in system keyring) — no passwords or SSH keys needed. `gh` is installed and logged in; use it for PRs/issues if asked.
- Commit identity is pre-configured in `.git/config`. Never commit secrets (`.env`, tokens) — see `.gitignore`.

## Contracts that are easy to break
- Adding an index chip = TWO edits: symbol in `INDEX_SYMBOLS` (`app.py`) AND a chip with matching `data-symbol` in `templates/index.html`. JS finds chips by `data-symbol`, not position.
- `/api/indices` returns successes only (failed symbols absent); `503` only when ALL symbols fail; frontend gap-fills missing chips with "—". Keep both sides in sync.
- Ledger table column count (11, incl. the trailing actions column) lives in FOUR places: the `<th>` row (`templates/index.html`), `setLedgerMessage`'s `colSpan`, `buildGroupRow`'s cell list (summary rows end with a BLANK actions cell), AND `buildTxRow`'s cell list (`static/js/main.js`). Adding/removing a column = edit all four.
- Edits go through `PUT /api/transactions/<id>` with body `{date, price, qty, type}` ONLY — ticker/currency are identity + a yfinance fact and are excluded from the UPDATE's SET list by design. POST and PUT share `validate_tx_fields` in `app.py`; add new field rules there once.
- Two vocabularies for the same data: the JSON API uses short keys (`date`, `type`); the DB uses explicit columns (`transaction_date`, `transaction_type`). Routes are the translator. PUT's reply is re-read from the DB, not echoed from the request.
- Backend sends raw floats; number formatting and `pos`/`neg` classes are frontend-only.

## MVP scope guard
Not in MVP: dividends, cash-balance tracking, multi-user auth, "Most Active" trends section, multiple named portfolios. Quotes display in native currency — no FX conversion.

## Working style (user preference)
- User is an absolute beginner learning everything: break features into digestible topics and explain concepts as you go.
- Match the codebase's verbose teaching-comment style — comments explain concepts for the learner.
