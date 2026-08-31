# Feature: Live watchlist with add/remove

Goal: watchlist items behave like the four index chips — live prices polled
every 60s — plus the ability to add/remove tickers from the UI.

## Decisions made (2026-08-31)

- **Storage: SQLite table** in `instance/portfolio.db` (file already existed,
  empty). Survives server restarts; establishes the DB pattern we'll need for
  the transaction ledger. New `db.py` module keeps SQLite out of app.py.
- **Add UX: "+ Add" button opens `prompt()`** for a ticker. Backend validates
  the ticker is real (via `get_quote`, which doubles as cache warm-up) before
  inserting. Duplicate → 409, unknown → 404.
- **Names: fetched once via `get_name()`** in market_data.py with a separate
  process-lifetime cache (names never change → no TTL, unlike prices).

## Key design point

Unlike the indices bar (chips are fixed in HTML, JS finds them by
`data-symbol`), watchlist rows come and go — the frontend must learn the
symbol list from the backend. So `GET /api/watchlist` returns
`{"symbols": [...], "quotes": [...]}`: rows render for ALL symbols, quotes
gap-fill with "—" for failures, same contract as `/api/indices`.

## Subtasks

- [x] `db.py`: SQLite helpers (init / get_symbols / add_symbol / remove_symbol),
      parameterized queries, connection per call
- [x] `market_data.py`: `get_name(symbol)` with process-lifetime `_name_cache`
- [x] `app.py`: GET/POST/DELETE `/api/watchlist`; copy quote dicts before
      adding `name` (cache returns shared objects — never mutate them);
      remove dead `watchlist = []` placeholder from index()
- [x] `index.html`: Jinja loop + static mock rows out; empty `<ul>` JS fills,
      empty-state element, per-row remove button
- [x] `main.js`: renderWatchlistRows (createElement + textContent),
      updateWatchRow (reuse formatPrice + pos/neg), refreshWatchlist on boot +
      shared interval; + Add prompt → POST; remove via event delegation → DELETE
- [x] `style.css`: .remove-btn + empty-state styling
- [x] Verify: curl happy paths + 409/404; browser add/remove; restart server
      and confirm rows persist
