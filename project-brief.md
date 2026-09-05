# Portfolio Tracker — Project Brief

## What

Personal stock/ETF portfolio tracker. You search for securities by ticker, log buy/sell transactions, and see your holdings' current value, unrealized P/L, a portfolio-value-over-time chart, and an allocation breakdown. Also includes a watchlist for securities you're not holding yet.

No news, no AI, no social features.

## Data Source

Prices and historical charts come from the [Yahoo Finance Python library](https://github.com/ranaroussi/yfinance). Anything Yahoo has is searchable and chartable — US/Canadian stocks, ETFs, international tickers, indices, crypto. Portfolio views (summary strip, value chart, ledger) display in CAD by default; the watchlist, index chips, and the stock detail page display in each security's native currency.

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
- CAD display conversion for portfolio views (USD↔CAD only, via
  Yahoo's `USDCAD=X` pair), with a ledger toggle for native-USD display

**Not in MVP:** dividends, cash-balance tracking, multi-user auth, "Most Active" trends section, multiple named portfolios, currencies other than USD/CAD.

## Design Rules (permanent)

- **The transaction ledger stores immutable facts only** (ticker, date,
  price, qty, currency, buy/sell type). Anything market-dependent — total
  value, gain $/% — is computed at display time from live quotes, never
  stored: stored copies would freeze stale the moment they were written.
- **The portfolio's display currency is CAD.** The summary strip, the
  value chart, and the ledger convert USD amounts at Yahoo's `USDCAD=X`
  rate; the watchlist, index chips, and stock detail page stay native.
  The ledger's "Show USD in USD" toggle flips ONLY the ledger back to
  native display — the total value and chart are CAD in every mode.
  Two rates by design: current values (value, day gain) use the LIVE
  rate because they answer "what would a sell bring in today?", while
  past costs (the ledger's Price column, the cost basis) use each
  transaction's STORED `fx_rate` — the USDCAD close on the transaction's
  date, captured at log time and never recomputed. A CAD gain therefore
  includes currency movement; that is the honest CAD picture. When a
  rate is unavailable, affected rows/holdings degrade (native display,
  unpriced, zero contribution) — never a fake 1:1 rate.
- **The ledger's sort is frontend-only and controls the GROUP rows, never
  the individual detail rows.** Clicking a sortable column header
  (`data-col` on the `<th>` in `index.html`) reorders the per-ticker
  summary rows only; the detail rows inside each group keep the backend's
  newest-first order (which is also the default group order until the user
  clicks). Sorting keys come from the same `groupSortKeys` values the
  group rows display, so the sort always matches the visible numbers.
  Columns with no single group value (Date, Type, Price) are not sortable.
  Group sort state lives in a JS variable (not the DOM) so it survives the
  60s poll. Group rows with an unavailable value ("—", e.g. a SELL-only
  group's Total Gain %, or an unquoted group's live cells) sort last in
  both directions.
- **A NaN from Yahoo is not a number, and it must never reach a JSON
  payload.** Flask's `jsonify` emits a bare `NaN` token, which is invalid
  JSON for browsers — their `response.json()` throws and the whole section
  (chart, ledger, summary...) renders as unavailable, even when every other
  symbol was healthy. Yahoo ships NaN closes on the unfinalized current-day
  bar (and can ship NaN in quotes; note NaN is truthy, so `not price` can't
  catch it). The data layer defends at the source: `get_history` drops
  NaN-close bars (a NaN close = "no bar printed yet"), and `get_quote`
  rejects NaN prices/previous-closes. The portfolio chart then prices a
  day with no bar for a held ticker at that ticker's LAST KNOWN close,
  carried forward (a position doesn't evaporate between closes; a ticker
  with no bars at all still contributes 0). The stock-page chart is not
  forward-filled — it plots one ticker's own closes, so ending at the last
  real bar is the honest picture there.
- **Long-horizon charts trade bar precision for load speed.** 5Y serves
  WEEKLY bars (`1wk`) and MAX serves MONTHLY bars (`1mo`); the short
  ranges (1M–1Y) stay daily. At that zoom the line is about SHAPE, not
  individual closes — and MAX would otherwise pull ^GSPC's ~25,000 daily
  bars since 1927. Accepted consequence: a mid-period buy enters the line
  at the NEXT bar (a mid-August buy appears at September's monthly bar) —
  the same next-trading-day approximation the weekend-buy rule already
  uses, just coarser. 5D went the OTHER way (finer, not coarser): 30-
  minute bars (`30m`), because plain daily bars left it a 5-point zigzag.
  Contract: PERIOD_MAP entries carry explicit flags — `intraday` (True
  ONLY for 1D: clock-time labels + the route's first-bar ledger branch)
  and `live` (True for 1D AND 5D: the 120s cache TTL, since today's bar
  keeps moving; settled date-spaced bars use 600s). Label formats are a
  PERIOD_MAP `label` field too: 1D "HH:MM", 5D "YYYY-MM-DD HH:MM" (the
  date keeps its five days from colliding in the {label: price} dict),
  everything else "YYYY-MM-DD". No code sniffs interval strings. 5D's
  datetime labels still sort lexicographically against "YYYY-MM-DD"
  transaction dates, so its ledger math stays daily-shaped (a buy applies
  at its day's FIRST 30-minute bar).

## Temporary Decisions (will need rework in the future)

- ~~**`/api/indices` fails all-or-nothing.**~~ **RESOLVED — rework done.**
  Was a deliberate MVP simplification while the bar served one chip
  (`^GSPC`). The documented rework trigger fired when the bar grew to four
  chips (`^GSPC`, `^IXIC`, `^GSPTSE` (TSX), `BTC-USD`): the route now uses
  per-symbol resilience — each chip fetched independently, failed symbols
  simply absent from the success-only response, `503` only when *all*
  symbols fail; the frontend marks unanswered chips with `—`. Kept here as
  decision history.
- **Portfolio chart shows hardcoded placeholder data.** ~~The dashboard's
  line chart is real Chart.js, but its values were a fake series.~~
  **RESOLVED — rework done.** The chart now plots real portfolio value
  over time, computed by `GET /api/portfolio/history` from the
  transaction ledger + historical close prices (`get_history` in
  `market_data.py`, `PERIOD_MAP` maps the 1D–MAX buttons to
  yfinance period/interval pairs). One deliberate simplification kept:
  a transaction dated on a non-trading day (weekend/holiday) is applied
  at the NEXT trading day's bar, since a date-only ledger can't know the
  intraday moment. Kept here as decision history.
- **Quote cache is an in-memory dict** (`market_data.py`, TTL 120s), not
  SQLite as listed in the stack table. Dies on server restart, which is
  acceptable for prices. **Rework trigger:** when the SQLite transaction
  ledger is built, consider moving the price cache into the same database.
- **History cache is an in-memory dict** (`market_data.py`, keyed
  `(symbol, period)`, TTL 600s for settled date-spaced bars / 120s for
  "live" series that include today's still-moving bar — 1D and 5D), not
  SQLite — same call as the quote cache; dies
  on restart, acceptable. Successes only: a failed fetch is never cached,
  so a transient Yahoo hiccup retries on the next click instead of posing
  as a dead ticker for a TTL window. **Rework trigger:** the quote cache's
  — move both into the SQLite database together.
- **The portfolio summary sums native currencies without conversion.**
  ~~`GET /api/portfolio/summary` adds each holding's value, day move, and
  net cost in whatever currency Yahoo quotes it — the ledger's per-row
  convention scaled up to the whole portfolio. With holdings in one
  currency the totals are exact; across currencies they are a mixed sum
  (a test in `tests/test_portfolio_summary.py` locks this decision).~~
  **RESOLVED — rework done.** Its own rework trigger fired (holdings in
  two currencies): the summary, chart, and ledger now display in CAD,
  converted at Yahoo's `USDCAD=X` pair — the ledger's per-row native
  display survives only in the watchlist, chips, and stock page, and
  behind the ledger's "Show USD in USD" toggle. The locking test was
  rewritten to lock the CONVERSION (`test_mixed_currencies_convert_to_cad`)
  and the rule moved to Design Rules. Kept here as decision history.
- **Stock-detail stats come from the heavy `Ticker.info` endpoint,
  fetched once per page load and never polled.** The stats grid's numbers
  (open, day high/low, prev close, volume, 52-week range, market cap)
  reset at most once per trading day, and `.info` is the slowest call
  yfinance offers — polling it every 60s would pay its cost for data that
  cannot move. The quote (fast_info) IS polled; the stats are not.
  **Rework trigger:** if the grid ever needs intraday freshness, give
  `get_stats` a short-TTL cache (the quote-cache pattern) rather than
  polling from the browser.
- **Ticker search (`/api/search`) is uncached.** Every query is
  user-typed and effectively unique, so a cache would almost never hit —
  unlike the quote cache (same symbols every 60s) or the name cache
  (names never change). **Rework trigger:** Yahoo rate-limiting search
  traffic → add a short-TTL cache keyed by the lowercased query.
