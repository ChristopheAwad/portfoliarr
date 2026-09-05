# AGENTS.md

## Read first
- `project-brief.md` — authoritative spec (stack, UI, MVP scope); takes precedence over assumptions.
- `feature.md` — context file for the feature in progress; read it before resuming work. Starting a new feature? Follow the **Feature workflow** section below: write the plan there first and get user approval before any implementation code.
- Design decisions that outlive a feature go in their permanent home: the "why" lives in code comments next to the code, cross-cutting rules go in `project-brief.md`'s Design Rules section. Never leave durable rationale only in `feature.md` — it's wiped per feature, so no long-lived file may reference it.
- `revert-to-table-plan.md` is a DORMANT contingency (the shipped feature kept phone holding cards) — never execute it unless the user asks.

## Feature workflow (required)
Applies to every NEW feature; small bug fixes and one-line tweaks skip the gate.
Follow these steps in order — never skip one:
1. **Plan before code.** Work out the whole feature first (subtasks, files to touch, data flow) and write the plan to `feature.md`. Overwrite any previous feature's content.
2. **Approval gate.** Summarize the plan for the user and ask whether to proceed. Do not write implementation code until the user says yes.
3. **Tests first.** The plan's first part is its test plan: detailed pytest unit tests that will run at the end to prove the feature works. Cover every part of the feature AND edge cases (empty/invalid input, boundary values, failure paths). Writing these tests is the first implementation step; they must fail until the feature exists.
4. **Implement.** Build the feature, parallelizing independent chunks with subagents (see **Parallel implementation** below). Done only when the FULL suite is green: `python -m pytest` (new tests + all existing ones).
5. **GUI gate.** With all tests passing, ask the user to check the feature in the browser GUI. Wait for their confirmation.
6. **Commit gate.** Only after the user approves the GUI, ask if you should commit and push to the GitHub repo. Never commit/push without that explicit yes.
- Resuming work? Read `feature.md` to see which step you're on and continue from there.

## Parallel implementation (subagents)
Use subagents to run independent implementation chunks concurrently — but only where it actually helps.
- Split at natural seams only (e.g., Python backend vs. frontend JS, unrelated modules). If chunk B needs chunk A's output, do them sequentially yourself — fake parallelism just creates merge conflicts.
- Tests first still governs: the failing test suite exists BEFORE any chunk is delegated. Subagents implement; they never write the tests that judge their own work.
- Brief each subagent like a new teammate: exact files to touch, the relevant Stack & architecture rules, and EVERY "Contracts that are easy to break" entry its files touch. A subagent starts with fresh context — it will break contracts you didn't spell out.
- The lead keeps the gates: plan, user approval, final integration, and the FULL-suite `python -m pytest` run are always yours. Subagents may run scoped tests for their chunk only; the green light is yours to confirm.
- Review every subagent's diff before integrating — you own the result.
- Never delegate: the plan, any gate (approval/GUI/commit), or anything touching git.
- Small fixes rarely need this; don't parallelize for its own sake.

## Stack & architecture
- Flask serves JSON; the browser does all rendering (vanilla JS `fetch` + DOM, no framework).
- Two pages, one shared shell: `templates/base.html` owns the head, Chart.js CDN, navbar, and the search box + suggestion dropdown. Pages extend it and fill the `title` / `content` / `scripts` (and optionally `body_attrs`) blocks. `static/js/common.js` (formatters, `paintChange`, search UI, `setupTimeframeChart`) is loaded by base.html BEFORE each page script — page scripts just use the globals.
- Layering: `market_data.py` = data layer (yfinance + caching, knows nothing about Flask); `db.py` = persistence layer (SQLite, knows nothing about Flask/yfinance); `app.py` = routes (decides WHICH symbols); `static/js/main.js` = dashboard rendering, `static/js/stock.js` = detail-page rendering.
- Logging lives ONLY in `app.py` (three tiers, console-only). The pure layers (`market_data.py`, `db.py`) never catch or log — they raise; the route layer catches wide, logs with `exc_info=True`, and translates failures to HTTP.
- Timeframe buttons (1D–MAX) and `/api/portfolio/history` both go through `PERIOD_MAP` (`market_data.py`) — the route validates client-supplied period keys against it. Adding a timeframe = edit it there once.
- Quote cache is an in-memory dict in `market_data.py` (TTL 120s), deliberately NOT SQLite despite the brief's stack table. Dies on restart — acceptable. Rework trigger documented in `project-brief.md`.
- SQLite DBs go in `instance/` (gitignored, per Flask convention).

## Commands
- Activate venv: `source .venv/bin/activate`
- Python is pinned at 3.14 (venv, CI, Dockerfile base image); all deps `==`-pinned in `requirements.txt`.
- Run dev server: `python app.py` (debug mode, port 5000)
- Verify live data: `curl http://localhost:5000/api/indices`

## Deploy (Docker & CI)
- Dev machine has NO Docker — never build/run the image locally. `tests/test_docker.py` meta-tests the container config by string-checking `Dockerfile`, `docker-compose.yml`, `.dockerignore`, and `.github/workflows/docker.yml`; editing any of those files means keeping the asserted contracts (right things present, wrong things absent, in both directions).
- CI on every push to `main` (`.github/workflows/docker.yml`): full `python -m pytest` → build & push `ghcr.io/christopheawad/portfoliarr:latest` + `:<sha>`. A red main never produces an image; `workflow_dispatch` exists for manual rebuilds.
- Server adopts updates: `docker compose pull && docker compose up -d` (pulls the published image, never builds locally). App at `http://localhost:9967` (host 9967 → container 5000).
- Prod = gunicorn `app:app`, 1 worker + 8 threads — deliberate: the in-memory quote cache and SQLite want a single process. Dev keeps `python app.py`.
- Container boots as root ONLY so `docker-entrypoint.sh` can chown the data volume, then `exec gosu appuser` — no `USER` directive by design (locked by test). Named volume `portfoliarr-data` mounted over `/app/instance` keeps the SQLite ledger across image updates; `TZ=America/Toronto` in compose.

## Testing
- Run: `python -m pytest` from the project root. Test files live in `tests/`; shared fixtures (`fresh_db`, `client`, `fake_market`) and the `make_quote` helper in root `conftest.py`.
- Tests never touch the real `instance/` DB — `fresh_db` monkeypatches `db.DB_PATH` to a per-test `tmp_path` file.
- Patch names WHERE THEY'RE USED, not where they're defined: `market_data` calls `yf` → `monkeypatch.setattr(market_data, "yf", Fake)`; routes call imported `get_quote`/`get_name`/`get_stats`/`get_history`/`search_tickers` → patch on the module: `import app as app_module`, then `monkeypatch.setattr(app_module, "get_quote", ...)`. (`from app import app` binds the Flask object, not the module — classic trap.)
- `fake_market` also patches the FX helpers: `fx_rates["USDCAD"]` (live) and `fx_on[("USDCAD", "YYYY-MM-DD")]` (historical); an ABSENT key = "Yahoo couldn't answer".
- Validator error paths call `jsonify()`, which needs app context → wrap calls in `with app.app_context():`.
- Importing `app` runs `db.init()` on the real DB once — harmless (idempotent).
- First run is slow (~90s pandas/numpy warmup), steady state ~17s. No test touches the network.

## Git & GitHub
- Repo: `ChristopheAwad/portfoliarr`, remote `origin` over HTTPS. Default branch `main` tracks `origin/main` — plain `git push` / `git pull` just work.
- Auth is handled by the `gh` CLI credential helper (token in system keyring) — no passwords or SSH keys needed. `gh` is installed and logged in; use it for PRs/issues if asked.
- Commit identity is pre-configured in `.git/config`. Never commit secrets (`.env`, tokens) — see `.gitignore`.

## Contracts that are easy to break
- Adding an index chip = TWO edits: symbol in `INDEX_SYMBOLS` (`app.py`) AND a chip with matching `data-symbol` in `templates/index.html`. JS finds chips by `data-symbol`, not position. Each chip is ALSO a real `<a>` to its detail page — generate the href with `url_for('stock_page', symbol=...)` (it percent-encodes `^GSPC` → `/stock/%5EGSPC`; Flask decodes it back) and keep it in sync with `data-symbol`. `tests/test_routes.py::test_dashboard_chips_are_links_to_detail_pages` locks this.
- `/api/indices` returns successes only (failed symbols absent); `503` only when ALL symbols fail; frontend gap-fills missing chips with "—". Keep both sides in sync.
- Ledger table column count (11, incl. the trailing actions column) lives in FOUR places: the `<th>` row (`templates/index.html`), `setLedgerMessage`'s `colSpan`, `buildGroupRow`'s cell list (summary rows end with a BLANK actions cell), AND `buildTxRow`'s cell list (`static/js/main.js`). Adding/removing a column = edit all four.
- Edits go through `PUT /api/transactions/<id>` with body `{date, price, qty, type}` ONLY — ticker/currency are identity + a yfinance fact and are excluded from the UPDATE's SET list by design (`fx_rate` IS in the SET list: it's yfinance-derived but derives from the DATE, so it must follow date corrections). POST and PUT share `validate_tx_fields` in `app.py`; add new field rules there once.
- Display currency: the summary strip, value chart, and ledger are CAD (summary/chart ALWAYS; the ledger via `?currency=CAD|NATIVE` — the dashboard toggle flips ONLY that param). Ledger rows' stored facts (`price`, `currency`, `fx_rate`) stay native and feed the edit form; display fields (`price_display`, `display_currency`) are converted. Cost side = stored `fx_rate` (frozen at buy date); value side = live rate. USD↔CAD only — anything else degrades (native display / unpriced / contributes 0), never a fake 1:1 rate.
- Two vocabularies for the same data: the JSON API uses short keys (`date`, `type`); the DB uses explicit columns (`transaction_date`, `transaction_type`). Routes are the translator. PUT's reply is re-read from the DB, not echoed from the request.
- Importer: `POST /api/transactions/import/preview` and `/commit` share ONE parser (`parse_import_text`, `app.py`). Commit RE-parses the same `{text}` body — never accept a client-sent row list between the two calls. Preview writes NOTHING; every imported row is forced BUY; best-effort per row (200 even when `imported == 0` — the report is the answer).
- Ledger group aggregates: `list_transactions` (`app.py`) attaches each ticker's `group_*` fields (value, cost_basis, total_gain, day_gain + pcts) to EVERY row of that ticker, computed with the SAME holdings math as `/api/portfolio/summary` (sells net out; value side = live rate, cost side = stored `price_display`). `main.js`'s `groupSortKeys` only READS them — never re-derive portfolio math in JS. Unquoted tickers get NO `group_*` keys (the frontend's "—" path keys on their absence). `tests/test_ledger_groups.py` locks the math.
- Backend sends raw floats; number formatting and `pos`/`neg` classes are frontend-only.

## MVP scope guard
Not in MVP: dividends, cash-balance tracking, multi-user auth, "Most Active" trends section, multiple named portfolios, currencies other than USD/CAD. Portfolio views (summary strip, value chart, ledger) display in CAD (see Design Rules in `project-brief.md`); the watchlist, index chips, and stock detail page stay native.

## Working style (user preference)
- User is an absolute beginner learning everything: break features into digestible topics and explain concepts as you go.
- Match the codebase's verbose teaching-comment style — comments explain concepts for the learner.
