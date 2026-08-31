# Portfolio Tracker — Project Brief

## What

Personal stock/ETF portfolio tracker. You search for securities by ticker, log buy/sell transactions, and see your holdings' current value, unrealized P/L, a portfolio-value-over-time chart, and an allocation breakdown. Also includes a watchlist for securities you're not holding yet.

No news, no AI, no social features.

## Data Source

Prices and historical charts come from the [Yahoo Finance Python library](https://github.com/ranaroussi/yfinance). Anything Yahoo has is searchable and chartable — US/Canadian stocks, ETFs, international tickers, indices, crypto. Quotes display in each security's native currency (no FX conversion for MVP).

## Tech Stack

| Layer | Tool |
|---|---|
| Backend | Python 3 + [Flask](https://flask.palletsprojects.com/) — serves JSON endpoints; browser does all rendering |
| Frontend | Plain HTML (Jinja2), vanilla JavaScript (`fetch` + DOM), [Chart.js](https://www.chartjs.org/) |
| Database | [SQLite](https://www.sqlite.org/) — transaction ledger + short-lived price cache |
| Price feed | [yfinance](https://github.com/ranaroussi/yfinance) |

## UI Layout (Two Pages)

### `/` — Portfolio Dashboard

- Value summary strip (total value, day change, total return, cost basis)
- Holdings table (ticker, name, qty, avg cost, current price, market value, unrealized P/L $/%, day change)
- Portfolio-value-over-time line chart (Chart.js)
- Allocation donut chart (% weight per holding)
- Watchlist sidebar with add/remove
- Search bar for ticker lookup

### `/stock/<symbol>` — Stock Detail

- Large current price display
- Time-segmented price chart with buttons: 1D · 5D · 1M · 6M · YTD · 1Y · 5Y · MAX
- Basic stats grid (open, high, low, prev close, volume, 52-week range, market cap)
- Buttons to add to watchlist or log a transaction

## Scope (MVP — Lean)

- Single portfolio, single implicit user (no auth)
- Transaction ledger: buy and sell events with dates and prices
- yfinance for all market data; anything Yahoo has is searchable
- Price cache with short TTL to avoid hammering Yahoo
- Native currency display per security (no FX conversion)

**Not in MVP:** dividends, cash-balance tracking, multi-user auth, "Most Active" trends section, multiple named portfolios.

## Design Rules (permanent)

- **The transaction ledger stores immutable facts only** (ticker, date,
  price, qty, currency, buy/sell type). Anything market-dependent — total
  value, gain $/% — is computed at display time from live quotes, never
  stored: stored copies would freeze stale the moment they were written.

## Temporary Decisions (will need rework in the future)

- ~~**`/api/indices` fails all-or-nothing.**~~ **RESOLVED — rework done.**
  Was a deliberate MVP simplification while the bar served one chip
  (`^GSPC`). The documented rework trigger fired when the bar grew to four
  chips (`^GSPC`, `^IXIC`, `^GSPTSE` (TSX), `BTC-USD`): the route now uses
  per-symbol resilience — each chip fetched independently, failed symbols
  simply absent from the success-only response, `503` only when *all*
  symbols fail; the frontend marks unanswered chips with `—`. Kept here as
  decision history.
- **Portfolio chart shows hardcoded placeholder data.** The dashboard's
  line chart is real Chart.js (CDN in `index.html` `<head>`, `<canvas>` in
  the `.chart-box`, init code in `main.js`), but its values are a fake
  7-day series literal in `main.js`, added as a learning exercise: to see
  the finished look early and to learn Chart.js's config shape before
  wiring real data. The timeframe buttons (1D–MAX) are still decorative.
  **Must be replaced with a real implementation:** portfolio value
  computed from the transaction ledger + live/historical prices, served
  by a backend endpoint (e.g. `/api/portfolio/history`), with the
  timeframe buttons driving which range is fetched. **Rework trigger:**
  as soon as the transaction ledger exists — updating the chart is then
  just `portfolioChart.data.* = ...; portfolioChart.update()` (handle
  already kept in `main.js`).
- **Quote cache is an in-memory dict** (`market_data.py`, TTL 120s), not
  SQLite as listed in the stack table. Dies on server restart, which is
  acceptable for prices. **Rework trigger:** when the SQLite transaction
  ledger is built, consider moving the price cache into the same database.
