# Feature: Highest Volume Leaders Feed (Watchlist Tab)

## What
A "Volume Leaders" tab in the watchlist sidebar that shows the top 10
highest-volume stocks traded today, with top 1 per market sector. Users
can flip between their personal watchlist and the volume leaders feed.

## Decisions locked in the brainstorm
- **Tabbed interface in watchlist sidebar.** Two tabs: "Watchlist"
  (existing) and "Volume Leaders" (new). Clicking a tab shows that
  content; the other hides.
- **Top 1 per sector, then top 10 overall.** Scan one representative
  stock per market sector, pick the highest-volume stock in each sector,
  then return the top 10 by volume.
- **Same display format as watchlist.** Each row shows: ticker, name,
  price, change (with color coding). No remove button (these aren't
  user-managed). Volume badge shows shares traded.
- **Sector leaders are hardcoded.** A predefined dict of sector →
  representative tickers (2-3 per sector for redundancy). This avoids
  scanning hundreds of stocks and keeps API calls fast.
- **Volume data via yfinance `info`.** The `volume` field (today's
  shares traded) comes from the heavy `Ticker.info` endpoint. We cache
  the result for 5 minutes (volume changes slowly during the day).
- **Graceful degradation.** If a sector leader fails to fetch, skip it.
  If all fail, show an error message in the tab. Never 500.
- **Clickable rows.** Clicking a volume leader navigates to its detail
  page (`/stock/<symbol>`), same as watchlist rows.

## How it works
### Backend: `market_data.py`
New function `get_volume_leaders()`:
1. Define `SECTOR_LEADERS` dict: maps sector name → list of candidate
   tickers (2-3 per sector for redundancy).
2. For each sector, fetch `Ticker.info` in parallel (ThreadPoolExecutor,
   max_workers=8).
3. Extract `volume` from each successful fetch.
4. Pick the highest-volume ticker per sector.
5. Sort all sector leaders by volume descending, return top 10.
6. Cache result for 300s (5 min TTL) in a new `_volume_cache` dict.
7. Return list of dicts:
   `[{symbol, name, price, change, change_pct, volume}, ...]`.

### Backend: `app.py`
New route `GET /api/market/volume-leaders`:
1. Call `get_volume_leaders()`.
2. On success: return `{leaders: [...]}`.
3. On failure: log at TIER 1, return `{leaders: []}` (never 500 —
   partial data is fine).
4. No authentication needed (public market data).

### Frontend: `templates/index.html`
Modified the watchlist sidebar section:
1. Added a tab bar above the watchlist: two `<button>` elements
   ("Watchlist" / "Volume Leaders").
2. Added a `<div id="volume-leaders-tab">` container (initially hidden)
   below the tab bar.
3. The existing `<ul class="watchlist">` is wrapped in
   `<div id="watchlist-tab">`.

### Frontend: `static/js/main.js`
New functions:
1. `tabBar` click listener — toggles active state, shows/hides content.
2. `refreshVolumeLeaders()` — fetches `GET /api/market/volume-leaders`,
   builds DOM rows in `#volume-leaders`.
3. `buildVolumeLeaderRow(leader)` — creates a `<li>` with the same
   structure as watchlist rows (symbol, name, price, change) plus a
   volume badge.
4. Added `refreshVolumeLeaders()` to the 60s polling cycle (parallel
   with `refreshWatchlist()`).

### Frontend: `static/style.css`
Added tab bar styles:
- `.tab-bar` — flex container for tab buttons
- `.tab-btn` — individual tab button styling
- `.tab-btn.active` — active tab gets blue accent underline

## Files touched
- `market_data.py` — added `SECTOR_LEADERS` dict + `get_volume_leaders()`
  + `_volume_cache` + `_VOLUME_TTL`
- `app.py` — added `GET /api/market/volume-leaders` route +
  `get_volume_leaders` import
- `templates/index.html` — added tab bar and volume-leaders container
- `static/js/main.js` — added tab logic, `refreshVolumeLeaders()`,
  `buildVolumeLeaderRow()`
- `static/style.css` — added `.tab-bar` and `.tab-btn` styles
- `tests/test_volume_leaders.py` — new test file (13 tests)

## Verification
- **Implemented, tests green:** full suite **385 passed** (13 new tests
  in `tests/test_volume_leaders.py`).
- **GUI check pending:** user confirms the sidebar shows two tabs
  ("Watchlist" / "Volume Leaders"), volume leaders load with correct
  data, rows are clickable, and 60s refresh updates the feed.

## Rollback
Revert the commit. Touches `market_data.py`, `app.py`,
`templates/index.html`, `static/js/main.js`, `static/style.css`,
`tests/test_volume_leaders.py`, `feature.md`. No schema changes, no
data migration.

## Out of scope
- Customizable sector leaders (user picks which sectors to watch).
- Historical volume comparison (today vs. 30-day average).
- Volume chart/sparkline in the feed rows.
- Sorting/filtering within the volume leaders tab.
- "Add to watchlist" button on volume leader rows (could be a follow-up).
