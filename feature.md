# Feature: Portfolio Value Chart (Real Data)

## Goal

Replace the placeholder chart data on the dashboard with a real
portfolio-value-over-time line chart, computed from the transaction
ledger + historical prices. All 9 timeframe buttons work:
1D · 5D · 1M · 3M · 6M · YTD · 1Y · 5Y · MAX.

Default period on boot: **5D**.

## How the math works

For each trading day (or intraday tick for 1D) in the selected period:

```
portfolio_value(point) = Σ net_position(ticker) × close_price(ticker, point)
                         across every ticker the user has ever traded
```

`net_position` is a running total: buys add qty, sells subtract qty.
Before a ticker's first buy its contribution is 0 (you didn't own it).
A ticker bought mid-period simply starts contributing from its buy date
forward.

## Subtasks

### 1. `templates/index.html` — add 3M button, change default active

- Add `<button class="time-btn">3M</button>` between the 1M and 6M
  buttons (after current line 83).
- Move the `active` class from the 1D button to the 5D button.
- Final button order: 1D · 5D · 1M · 3M · 6M · YTD · 1Y · 5Y · MAX.

### 2. `market_data.py` — add `get_history()` function

Add a `PERIOD_MAP` dict at module level:

```python
PERIOD_MAP = {
    "1D":  {"period": "1d",  "interval": "5m"},
    "5D":  {"period": "5d",  "interval": "1d"},
    "1M":  {"period": "1mo", "interval": "1d"},
    "3M":  {"period": "3mo", "interval": "1d"},
    "6M":  {"period": "6mo", "interval": "1d"},
    "YTD": {"period": "ytd", "interval": "1d"},
    "1Y":  {"period": "1y",  "interval": "1d"},
    "5Y":  {"period": "5y",  "interval": "1d"},
    "MAX": {"period": "max", "interval": "1d"},
}
```

New function `get_history(symbol, period_key)`:

- Looks up period/interval from `PERIOD_MAP`.
- Calls `yf.Ticker(symbol).history(period=..., interval=...)`.
- Normalizes the timezone-aware DatetimeIndex to plain strings:
  - Daily data → `"YYYY-MM-DD"` (e.g. `"2026-08-31"`).
  - Intraday (1D) → `"HH:MM"` (e.g. `"09:30"`).
- Returns a dict: `{"2026-08-25": 309.90, "2026-08-26": 313.45, ...}`.
- Raises on failure — same boundary rule as `get_quote`: this layer
  reports problems, the route layer decides the HTTP response.

### 3. `app.py` — new `GET /api/portfolio/history` route

`GET /api/portfolio/history?period=5D`

Query param `period` defaults to `"5D"`. Validate against
`PERIOD_MAP` keys — return 400 if invalid.

Algorithm:

1. Get all transactions from DB via `db.get_transactions()`.
   Sort ascending by date then id (chronological — opposite of the
   default newest-first, because we need to walk forward in time).
2. Collect unique tickers from the transactions.
3. For each ticker, call `get_history(ticker, period)`. Per-ticker
   failures are skipped (same resilience as the indices/watchlist
   routes) — that ticker simply contributes 0 for the whole period.
4. Build a union of all date/time labels across all tickers' histories.
   This is the x-axis — sorted ascending.
5. Walk through each label chronologically, maintaining a `net_qty`
   dict per ticker:
   - Before processing a label, check if any transaction falls on
     that date → update `net_qty[ticker]` (+qty for BUY, −qty for SELL).
   - For each label, sum `net_qty[ticker] × history[ticker][label]`
     across all tickers with a price at that label.
   - Append the sum to the values list.
6. Return `{"labels": [...], "values": [...]}`.

Edge cases:

- **No transactions** → return `{"labels": [], "values": []}`.
  Frontend shows "No transactions yet."
- **Ticker not quotable for the period** (delisted, Yahoo hiccup) →
  skip that ticker entirely; its contribution is 0.
- **Weekend/holiday gaps** → labels just skip those dates. Chart.js
  handles uneven x-axis spacing fine.
- **SELL reduces net_qty to 0** → ticker contributes nothing from
  that point forward (correct).
- **Mixed-currency portfolios** → raw sum regardless of currency.
  Known MVP limitation (documented in project-brief.md: "no FX
  conversion").

### 4. `main.js` — replace fake chart data + add button handlers

**Replace the entire PORTFOLIO CHART block** (lines ~908–987):

Keep the Chart.js init but with empty starting data:

```javascript
portfolioChart = new Chart(portfolioCtx, {
    type: "line",
    data: { labels: [], datasets: [{ label: "Portfolio Value", data: [] ... }] },
    options: { ... },  // same config as today
});
```

**New function `refreshPortfolioChart(period)`**:

- `period` defaults to `"5D"`.
- Fetches `/api/portfolio/history?period=${period}`.
- On success: sets `portfolioChart.data.labels` and
  `portfolioChart.data.datasets[0].data`, then calls
  `portfolioChart.update()`.
- On empty response (no labels): clears the chart data and shows
  "No transactions yet" via a sibling `<p>` element (or Chart.js
  annotation plugin if we add it later — for now a simple DOM
  element below the canvas is fine).

**New delegated click handler** on `.chart-timeframe-selectors`:

- Reads `textContent` of the clicked `.time-btn` (e.g. `"3M"`).
- Calls `refreshPortfolioChart(period)`.
- Swaps the `active` class from the old button to the new one.

**Boot**: call `refreshPortfolioChart()` (no arg → defaults to `"5D"`).

### 5. `style.css` — minimal if any

The chart area already exists and is styled. The only possible CSS
addition is styling the "No transactions yet" empty-state message
below the canvas — reuse the existing `.empty-state` class if it
fits, or a small inline style.

## Files changed

| File | What changes |
|---|---|
| `templates/index.html` | Add 3M button, move `active` to 5D |
| `market_data.py` | Add `PERIOD_MAP` + `get_history()` |
| `app.py` | Add `GET /api/portfolio/history` route |
| `main.js` | Replace fake chart block with real fetch + handlers |
| `style.css` | Possibly minor empty-state styling |

`db.py` — no changes.

## Verification

1. Start dev server: `python app.py`
2. `curl http://localhost:5000/api/portfolio/history?period=5D`
   → should return `{"labels":[...],"values":[...]}` or empty if
   no transactions exist.
3. Open `http://localhost:5000` in browser.
4. Log a few transactions across different tickers.
5. Chart should populate with real data on 5D (default).
6. Click each timeframe button — chart updates, `active` class
   follows the click.
7. Delete all transactions → chart shows "No transactions yet."
8. Verify mixed-currency portfolio renders without errors (values
   are raw sums — correct for MVP).
