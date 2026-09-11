# Portfolio Tracker — Feature Roadmap

Organized by priority tier. Effort is in working days (solo dev, includes tests).

---

## Tier 1 — Quick Wins (1–2 days each)

### 1. Average Cost per Position
The ledger group row's Price column currently shows "—". Compute and display the average cost basis per holding (total cost ÷ net shares held). The math is already computed in `group_*` fields on every row — this is a display-only change in `main.js`'s `buildGroupRow()`.

**Files:** `static/js/main.js`, `app.py` (add `group_avg_cost` to ledger response)
**Depends on:** Nothing

---

### 2. CSV Export
Import exists (`parse_import_text`), but there's no export. One new route (`GET /api/transactions/export`) that formats `db.get_transactions()` as downloadable CSV. Add a button in the ledger UI next to the import panel.

**Files:** `app.py` (new route), `templates/index.html` (button), `static/js/main.js` (download handler)
**Depends on:** Nothing

---

### 3. Transaction Fees
Currently no fee tracking. Add a nullable `fee` column to the `transactions` table. Fees roll into cost basis (buy fee increases cost, sell fee decreases proceeds). The DB migration pattern already exists (see fx_rate migration in `db.py`).

**Files:** `db.py` (schema + migration), `app.py` (validator + routes), `static/js/main.js` (form field + display), `templates/index.html` (form input)
**Depends on:** Nothing

---

### 4. Sector Breakdown Donut
The stock page already fetches sector/industry from Yahoo stats. Aggregate holdings by sector server-side (the data is in the quote response), render a second donut chart next to the allocation one. Ghostfolio charges for this; you get it for free.

**Files:** `app.py` (new endpoint or extend `/api/portfolio/summary`), `static/js/main.js` (new donut chart), `templates/index.html` (new canvas)
**Depends on:** Nothing (but fees/average cost make the sector weights more meaningful)

---

### 5. Cash Balance Tracking
Track uninvested cash in the portfolio. One row in a `portfolio` settings table (`cash_balance REAL DEFAULT 0`). Buys deduct cash, sells add back. Deposit/withdraw actions to move cash in/out. Portfolio total becomes cash + holdings. Allocation chart includes cash as a segment.

**Files:** `db.py` (new table + functions), `app.py` (new routes), `static/js/main.js` (summary strip + allocation chart), `templates/index.html` (UI elements)
**Depends on:** Nothing

---

## Tier 2 — Core Features (3–5 days each)

### 6. Dividend Tracking
The `transaction_type` CHECK constraint needs a new value (`DIVIDEND`). Add it to the validator, the form, and the ledger display. Dividends don't affect cost basis (they're income, not a reinvestment unless logged as a BUY). The ledger already handles multiple transaction types — this extends the pattern.

**Files:** `db.py` (CHECK constraint update), `app.py` (validator + routes), `static/js/main.js` (form + ledger display), `templates/index.html` (form radio)
**Depends on:** Nothing (but fees make dividend math more realistic)

---

### 7. Benchmark Comparison Line on Chart
Ghostfolio overlays S&P 500 against your portfolio. Overlay a normalized benchmark line on the portfolio value chart. The data pipeline exists (`get_history` + `PERIOD_MAP`). Needs Chart.js multi-dataset support and normalization (rebase both series to 100 at start date).

**Files:** `app.py` (new endpoint or extend `/api/portfolio/history`), `static/js/common.js` (chart factory), `static/js/main.js` (second dataset)
**Depends on:** Nothing

---

### 8. Multi-Currency Support Beyond USD/CAD
Currently only USD↔CAD via Yahoo's `USDCAD=X`. Extending to EUR, GBP, JPY, etc. means adding more FX pairs to `get_fx_rate`. The architecture (per-transaction stored rates + live rates) is already correct — just needs more pairs and a currency selector or auto-detection.

**Files:** `market_data.py` (FX pair expansion), `app.py` (currency logic), `db.py` (schema if adding default currency)
**Depends on:** Nothing

---

## Tier 2.5 — Quick Extends (1 day each)

### 9. Dashboard Period-Aware Return Pills
Extend the stock detail page's dynamic period return (shipped separately) to the dashboard. The portfolio "Today" pill and the ledger's "Day Gain" / "Day %" columns would reflect the selected chart period instead of always showing single-day moves. The portfolio history endpoint already returns aggregate values for any period, so `last - first` gives the period gain in CAD. The ledger column headers would rename ("Day Gain" → "1M Gain") and swap their data source. Touches the column-count contract (4 places per AGENTS.md).

**Files:** `static/js/main.js` (summary strip + ledger rendering), `templates/index.html` (column headers)
**Depends on:** Dynamic Period Return on Stock Detail Page (shipped first as a pattern)

---

## Tier 3 — Nice-to-Have (1–3 days each)

### 10. PWA Manifest
A `manifest.json` and minimal service worker for mobile home-screen install. Lets users treat it like a native app on their phone. ~50 lines total.

**Files:** `static/manifest.json` (new), `templates/base.html` (link tag), `static/js/sw.js` (new, minimal)
**Depends on:** Nothing

---

### 11. Ticker Search Caching
Already has a rework trigger in `project-brief.md`. A dict with 30s TTL keyed by lowercased query. Prevents Yahoo rate-limiting on repeated searches.

**Files:** `market_data.py` (new cache dict + TTL check)
**Depends on:** Nothing

---

### 12. Stats Caching
`get_stats` isn't cached (one fetch per page load). A short-TTL cache (e.g., 1 hour) would reduce slow Yahoo `.info` calls. The quote cache pattern already exists.

**Files:** `market_data.py` (new cache dict + TTL)
**Depends on:** Nothing

---

## Dependency Graph

```
Tier 1 (all independent):
  1. Average Cost ─────────────────────┐
  2. CSV Export ───────────────────────┤
  3. Transaction Fees ─────────────────┤── can be done in any order
  4. Sector Breakdown ─────────────────┤
  5. Cash Balance ─────────────────────┘

Tier 2 (all independent of each other):
  6. Dividend Tracking ────────────────┐
  7. Benchmark Line ───────────────────┤── can be done in any order
  8. Multi-Currency ───────────────────┘

Tier 2.5:
  9. Dashboard Period Return ─────────── depends on stock detail page version

Tier 3 (all independent):
  10. PWA Manifest ────────────────────┐
  11. Search Caching ──────────────────┤── can be done in any order
  12. Stats Caching ───────────────────┘
```

---

## Suggested Implementation Order

For maximum compounding value:

1. **Transaction Fees** → makes cost basis realistic
2. **Average Cost** → displays the now-real cost basis
3. **CSV Export** → makes data portable
4. **Sector Breakdown** → deeper allocation insight
5. **Cash Balance** → full portfolio picture
6. **Dividend Tracking** → most-requested feature in any portfolio app
7. **Benchmark Line** → context for performance
8. **Multi-Currency** → international expansion
9. **Dashboard Period Return** → extends stock page pattern to dashboard
10. **PWA Manifest** → mobile experience
11. **Search Caching** → resilience
12. **Stats Caching** → performance

---

## Not On This Roadmap

These are Ghostfolio features that don't fit Portfoliarr's scope:

- **Multi-user auth** — single-user by design
- **Multi-account / multi-broker** — single portfolio by design
- **AI assistant** — "no AI" in the project brief
- **FIRE calculator** — out of scope
- **Fear & Greed Index** — out of scope
- **Wealth items / liabilities** — not investment tracking
- **Bond tracking** — Yahoo Finance bond data is limited
- **Zen Mode** — nice but not essential
- **Multi-language** — English only by design
