# AGENTS.md

## Read first
- `project-brief.md` — authoritative spec (stack, UI, MVP scope); takes precedence over assumptions.
- `feature.md` — context file for the feature in progress; read it before resuming work. If empty and we're starting to work on a new feature, populate it first with subtasks.

## Stack & architecture
- Flask serves JSON; the browser does all rendering (vanilla JS `fetch` + DOM, no framework).
- Layering: `market_data.py` = pure data layer (yfinance + caching, knows nothing about Flask); `app.py` = routes (decides WHICH symbols); `static/js/main.js` = rendering only.
- Quote cache is an in-memory dict in `market_data.py` (TTL 120s), deliberately NOT SQLite despite the brief's stack table. Dies on restart — acceptable. Rework trigger documented in `project-brief.md`.
- SQLite DBs go in `instance/` (gitignored, per Flask convention).

## Commands
- Activate venv: `source .venv/bin/activate`
- Run dev server: `python app.py` (debug mode, port 5000)
- Verify live data: `curl http://localhost:5000/api/indices`
- Deps pinned in `requirements.txt`. No tests, lint, or CI exist yet.

## Git & GitHub
- Repo: `ChristopheAwad/portfoliarr`, remote `origin` over HTTPS. Default branch `main` tracks `origin/main` — plain `git push` / `git pull` just work.
- Auth is handled by the `gh` CLI credential helper (token in system keyring) — no passwords or SSH keys needed. `gh` is installed and logged in; use it for PRs/issues if asked.
- Commit identity is pre-configured in `.git/config`. Never commit secrets (`.env`, tokens) — see `.gitignore`.

## Contracts that are easy to break
- Adding an index chip = TWO edits: symbol in `INDEX_SYMBOLS` (`app.py`) AND a chip with matching `data-symbol` in `templates/index.html`. JS finds chips by `data-symbol`, not position.
- `/api/indices` returns successes only (failed symbols absent); `503` only when ALL symbols fail; frontend gap-fills missing chips with "—". Keep both sides in sync.
- Backend sends raw floats; number formatting and `pos`/`neg` classes are frontend-only.

## MVP scope guard
Not in MVP: dividends, cash-balance tracking, multi-user auth, "Most Active" trends section, multiple named portfolios. Quotes display in native currency — no FX conversion.

## Working style (user preference)
- User is an absolute beginner learning everything: break features into digestible topics and explain concepts as you go.
- Match the codebase's verbose teaching-comment style — comments explain concepts for the learner.
