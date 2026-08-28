# AGENTS.md

## Source of truth
`project-brief.md` is the authoritative spec for this project (a personal stock/ETF
portfolio tracker). Read it before writing code — it defines the stack, UI layout,
and MVP scope. It takes precedence over any assumptions.

## Stack (from the brief)
- Backend: Python 3 + Flask — serves JSON endpoints; the browser does all rendering
- Frontend: Jinja2 templates, vanilla JS (`fetch` + DOM), Chart.js
- Database: SQLite — transaction ledger + short-lived price cache (short TTL to avoid
  hammering Yahoo)
- Price feed: yfinance

## Current state
- `app.py` is the intended Flask entrypoint but is currently empty (not yet implemented).
- `templates/index.html` and `static/style.css` are frontend stubs.
- No package manifest, tests, or tooling config exist yet — expect to create them.

## MVP scope guard (do not build outside this)
Explicitly **not** in MVP: dividends, cash-balance tracking, multi-user auth,
"Most Active" trends section, multiple named portfolios. Quotes display in each
security's native currency (no FX conversion for MVP).

## Additional notes
- User is an absolute beginner and whats to learn everything.
- Treat every new feature we're working on as a learning experience, breaking it down into digestible topics and expplaining the concepts.

