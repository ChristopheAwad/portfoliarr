# Feature: Live S&P 500 Index Chip

> Context file for resuming work in a new session. Read `project-brief.md` first — it is the authoritative spec.

## Goal

Replace the hardcoded values in the top indices bar (S&P 500 chip) with live data from yfinance, following the brief's architecture: **Flask serves JSON, browser renders via `fetch`**.

```
yfinance (Python) → Flask JSON endpoint → JS fetch() → DOM update
```

## Decisions Already Made

| Decision | Choice |
|---|---|
| Scope | **S&P 500 only** (`^GSPC`). The other 3 chips (Nasdaq, Dow, Russell) stay static placeholders for now. |
| Cache | **In-memory dict with TTL** (~60s). SQLite cache comes later with the transaction ledger. |
| Refresh | **Poll every 60s** via `setInterval` in JS. |

## Relevant Current State

- `app.py` — Flask entrypoint, has root route `/` serving `index.html` with an empty watchlist.
- `templates/index.html:26-47` — `indices-bar` section with 4 hardcoded chips; the S&P 500 chip is the target.
- `templates/index.html:8` — stylesheet linked as `../static/style.css` (fragile; fix to `url_for`).
- `static/style.css` — `.chip`, `.index-name`, `.index-price`, `.index-change`, `.pos`/`.neg` classes already exist.
- No `requirements.txt`, no venv, no JS files yet.

## Subtasks

### 1. Environment setup
- Create `requirements.txt` with `flask` + `yfinance`.
- Create virtual environment, `pip install -r requirements.txt`.
- Verify network access to Yahoo works before continuing.

### 2. yfinance scratch experiment (`/tmp/opencode/scratch.py`)
- Fetch `^GSPC` via `.fast_info` and `.history(period="2d")`.
- Inspect what fields come back (`last_price`, `previous_close`, etc.) before wiring anything up.

### 3. `market_data.py` — data module
- `get_sp500_quote()` → `{symbol, name, price, change, change_pct}` computed from last close vs previous close.
- In-memory TTL cache (~60s): module-level dict holding `{data, fetched_at}`; stale entries trigger a fresh yfinance call.
- Return an error indicator on network failure so the route can respond cleanly.

### 4. `GET /api/indices` in `app.py`
- Calls the module, `jsonify`s the result.
- Returns `503` + error JSON if Yahoo is unreachable.

### 5. Frontend wiring
- Add `data-symbol="^GSPC"` to the S&P chip in `templates/index.html`.
- Create `static/js/main.js`:
  - `fetch('/api/indices')` → update price (formatted like `5,088.80` via `Intl.NumberFormat`), change %, toggle `pos`/`neg` class.
  - Run once on load, then `setInterval(..., 60000)`.
- Fix stylesheet link to `{{ url_for('static', filename='style.css') }}`.

### 6. Verify end-to-end
- `curl http://localhost:5000/api/indices`.
- Load page, confirm live value + 60s refresh.
- Test error path (e.g., disconnect network) — page should degrade gracefully, not break.

## Learning Notes (user is a beginner — explain as we go)

1. venv + dependency pinning
2. Exploring an unfamiliar API before using it
3. Separation of concerns; what a TTL cache is and why (rate-limit protection)
4. JSON endpoints, `jsonify`, HTTP status codes
5. `fetch` + async/await, DOM manipulation, number formatting
6. Tracing a request through the full stack; browser dev tools Network tab
