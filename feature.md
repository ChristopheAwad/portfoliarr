# Feature: Live Portfolio Header (value, day change, total return)

## Goal

The "Your Portfolio" card's numbers are hardcoded mockup data:

- `$143.96` — `<span class="current-price">` (templates/index.html:68)
- `+1.85 (+1.30%) Today` — `<span class="price-change pos">` (line 69)

Nothing in main.js ever touches them. This feature replaces them with
real computed numbers: **total value**, **day change**, and **total
return**, each with its % — the first slice of the project brief's full
"value summary strip" (cost basis stays server-side for now; the strip
can add it as a fourth number later).

## Decisions locked (with the user)

| Decision | Choice | Why | Rework trigger |
|---|---|---|---|
| Where computed | New backend route, not client-side sums | main.js is rendering-only (AGENTS.md architecture rule); backend owns market math | — |
| Scope | Value + day change + total return (3 numbers) | User's choice; full strip (4th number: cost basis) is a later feature reusing this endpoint | The full summary strip ships |
| Currency | Mixed native-currency sum, documented | MVP no-FX rule, same as the ledger's per-row values | Dashboard routinely shows ≥2 currencies |
| Unpriced tickers | Excluded from ALL sums + returned in `unpriced` list | Per-symbol resilience (indices bar rule): successes only, frontend flags the gap | — |
| Display | Plain number, no `$` prefix | The total isn't reliably one currency; chips already show bare numbers | — |

## Math (mirrors existing code)

- Net qty per ticker: BUY adds, SELL subtracts — same walk as
  `portfolio_history` (app.py).
- `total_value = Σ net_qty × quote.price` (priced tickers only)
- `day_gain = Σ net_qty × quote.change` — quote.change = live −
  previous close, the same per-row rule as the ledger's Day column.
- `cost_basis = Σ ±(price × qty)` over the SAME priced tickers — SELL
  proceeds subtract, giving net invested capital. Then
  `total_gain = total_value − cost_basis`, which blends realized +
  unrealized gains in one formula. (Excluding unpriced tickers from
  cost_basis too keeps every number describing the same portfolio slice.)
- `day_gain_pct = day_gain ÷ (total_value − day_gain) × 100` (yesterday's
  value is the base). `total_gain_pct = total_gain ÷ cost_basis × 100`.
  Zero/meaningless denominators → `null` → frontend shows the signed
  amount without a %.

## Subtasks

### 1. `app.py` — `GET /api/portfolio/summary`

Placed next to `portfolio_history`. No params, no validation needed.
Returns raw floats + nullable pcts:

```json
{"total_value": 630.0, "day_gain": 30.0, "day_gain_pct": 5.0,
 "total_gain": 70.0, "total_gain_pct": 12.5, "cost_basis": 560.0,
 "unpriced": []}
```

Empty ledger = normal 200 with zeros + null pcts (same rule as the
history route). One `get_quote` per unique ticker; a dead ticker lands
in `unpriced` (sorted) and contributes to nothing.

### 2. `templates/index.html` + `static/style.css`

- ids: `portfolio-value`, `portfolio-day-change`, new span
  `portfolio-total-return`. Mockup numbers → "…".
- CSS: `.price-change` becomes a stacked block line (value on line 1,
  two change lines below).

### 3. `static/js/main.js` — `refreshPortfolioSummary()`

Fetch → paint. Signed change lines: `+30.00 (+5.00%) Today` /
`+70.00 (+12.50%) Total`; pos/neg classes; null pct drops the
parenthetical. Partial unpriced → tooltip on the value names them; all
contributions zero WHILE tickers are unpriced → whole header degrades
to "—" (nothing priced is contributing). Fetch failure → "—" too.

Call sites: boot, 60s interval, and next to all three existing
`refreshLedger()` calls (log/edit submit, delete, import commit).

### 4. `tests/test_portfolio_summary.py`

House patterns (`fake_market` style: patch `app_module.get_quote`;
`client`/`fresh_db` fixtures; seed via `db.add_transaction`):

- empty ledger → zeros, null pcts, 200
- buy-only math (value, day gain/pct, total gain/pct)
- buy + sell: netted cost basis, realized+unrealized blend
- unpriced ticker excluded from every sum and listed
- all-unpriced → zeros + listed (the frontend "—" shape)
- fully-sold portfolio → zeros + null pcts
- mixed currencies sum as-is (documents the temporary decision)

### 5. `project-brief.md` — temporary decision entry

Mixed-currency total, rework trigger documented there (permanent home;
this file gets wiped).

## Files changed

| File | What changes |
|---|---|
| `app.py` | `GET /api/portfolio/summary` |
| `templates/index.html` | ids + third span, mockup numbers removed |
| `static/style.css` | `.price-change` stacks as block lines |
| `static/js/main.js` | `refreshPortfolioSummary()` + 5 call sites |
| `tests/test_portfolio_summary.py` | New: route tests |
| `feature.md` | This document |
| `project-brief.md` | Temporary decision entry |

`db.py`, `market_data.py` — **no changes** (pure layers untouched).

## Non-goals

- Cost basis / total-return as DISPLAYED strip columns (endpoint returns
  cost_basis; the UI adds it when the strip ships).
- FX conversion (see the brief's rule).
- Chart/header synchronization (header uses live quotes; chart uses
  history closes — close but not identical by design).
