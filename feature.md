# Feature: Ticker Search + Stock Detail Page

## What (user story)

The navbar's search box becomes real: typing shows live ticker suggestions
(debounced fetch to the backend → Yahoo's search API). Clicking a suggestion
(or pressing Enter) navigates to `/stock/<symbol>` — a detail page that looks
like the dashboard:

- Large current price + name (where the portfolio value would be)
- Daily change in $ AND % (pos/neg coloured) — **no total return** (a
  security has no ledger; that number wouldn't exist)
- Price-over-time chart with the SAME 1D–MAX timeframe buttons
  (`PERIOD_MAP` keys, default 5D — no map edits needed)
- Stats grid: Open, Day High, Day Low, Prev Close, Volume, 52W Range,
  Market Cap
- Buttons: **Add to Watchlist** (reuses `POST /api/watchlist`) and
  **Log Transaction** (navigates to `/?ticker=SYM#tx-form`; main.js reads
  the `?ticker=` param and prefills the form — ONE form, one submit handler)

Bonus navigation (agreed): watchlist rows and ledger group-row tickers link
to the detail page too.

## Decisions already made (planning session — don't re-litigate)

- **Scope**: full brief spec for `/stock/<symbol>` (stats grid + both
  buttons), not just price/chart/day-change.
- **Reuse strategy**: refactor to shared code — `templates/base.html`
  (navbar + search + head/CDN) and `static/js/common.js` (formatters,
  `REFRESH_MS`, `paintChange`, search UI, shared chart helper).
  NO duplicated navbar/search JS.
- **"Log Transaction" = URL-param prefill** (`/?ticker=SYM#tx-form`), not an
  inline form on the detail page.
- **Search is uncached** (every query is user-typed, hit rate ≈ 0).
- **Stats are one-shot per page load**, not polled — they come from the heavy
  `yf.Ticker().info` endpoint and are daily figures; only the quote is polled.
- **Unquotable symbol → 404** on the single-symbol endpoints (same convention
  as watchlist-add / transaction-log).
- Native currency display everywhere, no FX (permanent brief rule).

## Subtasks (in order — check off as done)

- [ ] **1. `market_data.py` data layer** (+ Fake-yf tests)
      - `search_tickers(query, limit=8)` via `yf.Search(...).quotes`
        (verified working on yfinance 1.7.0). Normalize to
        `{symbol, name, exchange, type}` from `symbol` /
        `shortname`→`longname` fallback / `exchDisp`→`exchange` / `typeDisp`.
        `[]` on no matches; RAISES on failure (boundary rule, no logging).
      - `get_stats(symbol)` via one `yf.Ticker(symbol).info` call →
        `{open, day_high, day_low, prev_close, volume, week52_low,
        week52_high, market_cap}` (from `open`, `dayHigh`, `dayLow`,
        `regularMarketPreviousClose`, `volume`, `fiftyTwoWeekLow`,
        `fiftyTwoWeekHigh`, `marketCap`). Missing fields → `None`
        (indices/crypto lack some); frontend gap-fills "—".
      - Tests: Fake `yf` module via `monkeypatch.setattr(market_data, "yf",
        Fake)` — normalization, longname fallback, empty results, raise
        propagates.

- [x] **2. `app.py` routes** (+ route tests: new `tests/test_search.py`,
      `tests/test_stock.py`)
      - `GET /stock/<symbol>` — render `stock.html`, symbol uppercased and
        passed to the template (becomes `<body data-symbol>` + `<title>`).
      - `GET /api/search?q=` — q required/non-blank → else 400;
        success → `{"results": [...]}`; failure → 503 (indices all-fail
        convention), warning + `exc_info`.
      - `GET /api/stock/<symbol>` — `dict(get_quote(sym))` (COPY before
        decorating — cache-mutation rule) + name via `get_name`
        (failure → `None`, watchlist rule). Quote failure → 404
        "unknown or unquotable symbol". This is the POLLED endpoint (60s).
      - `GET /api/stock/<symbol>/stats` — `get_stats` → 200; failure → 404.
      - `GET /api/stock/<symbol>/history?period=` — validate against
        `PERIOD_MAP` (same pattern as portfolio history; 400 lists options)
        → `get_history` dict → sorted `{labels, values}`. Empty dict → 200
        empty; fetch failure → 404.
      - Test rule: patch names WHERE USED — `app_module.search_tickers`,
        `app_module.get_stats`, etc. (`from app import app` binds the Flask
        object, not the module).

- [x] **3. Shared refactor** — `templates/base.html`, `templates/index.html`,
      `static/js/common.js`
      - `base.html`: head + Chart.js CDN + navbar. Logo `<span>` becomes
        `<a href="/">`. Search input gets `id="ticker-search"` + hidden
        `<div id="search-results">` dropdown. Jinja blocks: `title`,
        `content`, `scripts`.
      - `index.html` extends base; dashboard content unchanged — ALL
        existing hooks preserved (chips `data-symbol`, `portfolio-value`,
        `ledger-body`, `tx-form`, `import-panel`...).
      - `common.js` (loads BEFORE page scripts): move `REFRESH_MS`,
        `formatPrice`, `formatNumber`, `formatSigned` from main.js;
        generalize `paintPortfolioChange` → `paintChange(el, value, pct,
        label)`. Search UI: 300ms debounce → `/api/search?q=` → dropdown
        (createElement + textContent only); click/Enter navigates to
        `/stock/<encodeURIComponent(symbol)>`; Escape/outside-click hides;
        "No matches" / "Search unavailable" states.
      - Verify dashboard looks/behaves identically before moving on.

- [x] **4. Detail page** — `templates/stock.html`, `static/js/stock.js`,
      `static/style.css`, shared chart helper
      - `common.js` gains `setupTimeframeChart({canvas, label, endpoint,
        defaultPeriod})` — creates the Chart.js line (keeps the
        `typeof Chart === "undefined"` CDN guard), wires the delegated
        `.time-btn` listener, returns `refresh(period)`. main.js then uses
        it with `/api/portfolio/history` (kills ~70 duplicated lines).
      - `stock.html` (extends base): header card (symbol + JS-filled name,
        large price `<currency>`, day change $/% via `paintChange`,
        NO total-return span, Add-to-Watchlist + Log-Transaction buttons),
        chart card (canvas + 1D–MAX, 5D active), stats card (grid, ships
        "…", 52W Range = `low – high`, Market Cap compact notation "2.52T").
      - `stock.js`: symbol from `document.body.dataset.symbol`;
        `refreshStockQuote()` on load + poll; `refreshStockStats()` once;
        404 → "Unknown symbol" degraded state; Add button → POST
        `/api/watchlist` (201 → disable + "✓ Watching", 409/404 relayed
        inline); Log button → `/?ticker=SYM#tx-form`.
      - CSS: search dropdown, stats grid, watchlist-row hover, ticker-link.

- [x] **5. `main.js` wiring**
      - Read `?ticker=` URL param → prefill + focus the tx form (and the
        `#tx-form` anchor does the scrolling).
      - Watchlist rows clickable → navigate to detail page (guard: a click
        on the × remove-btn must NOT navigate).
      - Ledger group-row ticker cell → `<a class="ticker-link">`; the
        expand/collapse delegated listener returns early when
        `event.target.closest("a")`. Cell COUNT unchanged.

- [x] **6. Docs + verification**
      - `project-brief.md` Temporary Decisions: (a) stats via heavy `.info`
        once per load, not polled; (b) search uncached. — DONE
      - `python -m pytest` green: 115 passed. — DONE
      - Live curl pass: search / quote / stats / history / 400s / 404s /
        both page shells (incl. %5EGSPC) — all correct. — DONE
      - REMAINING (needs a human at the browser): typing in the search box
        (dropdown, click + Enter navigation), Add-to-Watchlist and
        Log-Transaction buttons, watchlist/ledger link navigation, and the
        dashboard looking unchanged.

## Contracts that must NOT break (AGENTS.md)

- Ledger 11-column contract lives in FOUR places (th row, setLedgerMessage
  colSpan, buildGroupRow, buildTxRow) — this feature touches the group
  ticker CELL CONTENT only, never the count.
- `PERIOD_MAP` is the single source of truth for timeframes — new page
  reuses the same 9 keys/buttons; no map edits.
- Backend sends raw floats; formatting + pos/neg classes are frontend-only.
- Logging lives ONLY in app.py; market_data/db raise.
- Quote dicts come back from the cache SHARED — copy before decorating.
- Two vocabularies: JSON API short keys vs DB explicit columns (not really
  triggered here — the stock endpoints have no DB rows — but keep the rule
  in mind for any reply shapes).
