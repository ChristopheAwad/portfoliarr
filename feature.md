# Feature: Transaction Ledger

Track buy/sell transactions and — eventually — derive everything the
dashboard needs from them: holdings, average cost, unrealized P/L, and the
real portfolio-value-over-time chart (replacing the placeholder series).

This file is the feature's running context. Update it as steps complete so
work can resume here after a break.

---

## Core design decision (do not undo casually)

**Store immutable facts; compute derived values live.**

The original field wishlist included Total Gain $, Total Gain %, and Total
Value as database columns. Those are *derived* values — they depend on the
CURRENT market price, which changes every second. Storing them would freeze
them at insert time and be instantly, permanently wrong. So the database
stores only what actually happened (facts that never change), and every
displayed gain/value is computed on the fly from live quotes:

| Computed at display time | Formula |
|---|---|
| Total Value | current_price × qty |
| Total Gain $ | (current_price − purchase_price) × qty |
| Total Gain % | (current_price − purchase_price) / purchase_price × 100 |

Rule of thumb: if a value would need to be *updated* whenever the market
moves, it doesn't belong in this table.

### Field naming notes

- Column is `price`, NOT `purchase_price` — a SELL row's price is the sale
  price, and the neutral name stays honest for both row types.
- Column is `transaction_date` (not `date`) and `transaction_type` (not
  `type`) — explicit beats clever, and avoids brushing against SQLite
  keywords.
- `currency` is auto-filled by the backend from yfinance at insert time —
  the user never types it (they'd get it wrong; Yahoo knows the security's
  trading currency).

## Schema (the facts table)

```sql
CREATE TABLE IF NOT EXISTS transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker           TEXT NOT NULL,
    transaction_date TEXT NOT NULL,          -- ISO "YYYY-MM-DD" (sorts correctly as text)
    price            REAL NOT NULL,          -- per-unit price at transaction time
    qty              REAL NOT NULL,          -- REAL: fractional shares / crypto allowed
    currency         TEXT NOT NULL,          -- auto-filled from yfinance
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('BUY', 'SELL'))
);
```

Details worth remembering:

- SQLite has no DATE type — dates are TEXT in ISO format, which has the
  nice property that lexicographic order == chronological order.
- The CHECK constraint is a second line of defence behind route validation:
  the database itself refuses any transaction_type that isn't BUY or SELL.
- `id` is `INTEGER PRIMARY KEY`, which in SQLite auto-increments (it's an
  alias for the hidden rowid).

### Known limitation (accepted for now, revisit later)

"Total Gain" is well-defined for BUY rows (unrealized gain vs live price).
For SELL rows the honest number is *realized* gain: sale price vs the
cost basis of the shares sold — which requires average-cost tracking
across prior buys. Deferred to a later step (see step 3); nothing in this
feature's early steps needs it.

---

## Steps

### Step 1 — Backend: table + CRUD endpoints ✅ DONE

- [x] Design settled (this file)
- [x] `db.py`: add `transactions` table to `init()`
- [x] `db.py`: `add_transaction(...)` — parameterized INSERT, returns new id
- [x] `db.py`: `get_transactions()` — all rows, newest first
      (`ORDER BY transaction_date DESC, id DESC`), as dicts for jsonify
- [x] `app.py`: `POST /api/transactions` — body `{"ticker", "date", "price", "qty", "type"}`
      - 400 for missing/invalid fields (date via `date.fromisoformat`,
        qty/price must be > 0, type must be BUY/SELL — case-insensitive input,
        normalized to uppercase before the DB sees it)
      - 404 if ticker fails `get_quote()` validation (same pattern as
        watchlist add — and it warms the price cache as a side effect)
      - currency auto-filled from that quote
      - 201 with the stored row
- [x] `app.py`: `GET /api/transactions` — raw stored facts as a JSON list
- [x] Verified live (2026-08-31): POST BUY (AAPL, USD auto-filled) and SELL
      (SHOP.TO, CAD auto-filled; lowercase "sell" normalized), all four
      rejection paths (fake ticker 404, bad date 400, price ≤ 0 400, bad
      type 400), newest-first list, and rows persisted across a server
      restart. Test rows deleted afterwards — ledger starts clean.

### Step 2 — Frontend: log + display transactions ✅ DONE

Decisions made (2026-08-31):

- **Backend decorates.** `GET /api/transactions` joins live prices
  server-side: unique tickers → `get_quote()` (120s cache makes repeats
  free), each row gains `price_now`, `value`, `gain`, `gain_pct` as raw
  floats. This does NOT violate the facts-only rule — that governs the DB;
  per-request computation from live quotes is exactly the design. Keeps
  `main.js` rendering-only (AGENTS.md layering) and handles tickers not on
  the watchlist (the frontend otherwise has no way to price them). A quote
  failure leaves that row undecorated → frontend gap-fills with "—".
- **Inline form** (not prompt() chain, not modal): 5 fields — ticker,
  date (type="date", defaults to today), price (number, step="any"),
  qty (number, step="any"), type (BUY/SELL select) + Log button. Backend
  error messages (400/404) shown inline in a hidden error <p>.
- **Placement:** Transactions card in the main column BELOW the chart card
  (a table needs width; the 340px sidebar doesn't fit it).
- **Append-only this step:** no row edit/delete — that's deferred.
- Ledger joins the 60s poll + instant refresh after a successful POST.

Subtasks:

- [x] `app.py`: extend `GET /api/transactions` with the decoration pass
      (unique-ticker quote map; floats per row; facts untouched; no
      division-by-zero risk since price > 0 enforced at insert)
- [x] `index.html`: Transactions card — header, `<form id="tx-form">`
      (5 inputs + Log button), hidden inline error <p>, `<table>` with
      empty `<tbody id="ledger-body">` (watchlist pattern: JS builds rows)
- [x] `main.js`: `refreshLedger()` — fetch → rebuild rows; joins the 60s
      poll and the boot sequence; instant re-fetch after successful POST
- [x] `main.js`: row rendering — Type as BUY/SELL badge (green/red bg),
      pos/neg classes on gain cells, "—" for undecorated rows and full
      failures, empty state "No transactions yet". createElement +
      textContent only, never innerHTML.
- [x] `main.js`: submit handler — FormData → JSON (Number() for price/qty),
      POST, reset form on 201, show data.error inline on failure
- [x] `main.js`: today-default for the date input via a LOCAL date helper
      (teaching note: toISOString() is UTC — near midnight it can be
      "yesterday" locally)
- [x] `style.css`: .tx-form (flex row, search-box-styled inputs),
      .ledger-table (full-width, right-aligned numerics, hairline row
      borders), .tx-badge.buy/.sell (reuse --green-bg/--red-bg), .tx-error
- [x] Backend verified (2026-08-31): decorated GET returns facts + floats
      (AAPL BUY @229.50 → price_now 315.38, value 3153.80, gain +858.80,
      +37.42% — math checked by hand); SELL rows decorate with the same
      formula (interim semantics per the known-limitation note above);
      fake ticker still 404s; test rows deleted, ledger clean.
- [ ] UI check by user: log a BUY via the form, watch the row appear with
      live gain, sanity-check the math, confirm the inline error line on a
      bad input (e.g. fake ticker)

Deferred (recorded, not scheduled): row edit/delete; prefilling the price
field from the live quote once a ticker is entered.

### Step 2b — Day gain columns (follow-up) ✅ DONE

Clarification settled (2026-08-31): the existing `gain`/`gain_pct` are
TOTAL gain — accumulated since the transaction date
(`(live_price − purchase_price) × qty`). What was missing is DAILY gain:
today's market move applied to the position. Nearly free to add — the
quote already carries today's move (`change` = live − previous close,
and `change_pct`), validated inside `get_quote`, so every row decoratable
with total gain is decoratable with day gain. No new failure modes.

Semantics (the permanent "why" lives in the app.py decoration comments):

- Total Gain % = this position's return since purchase (qty matters).
- Day Gain % = the ticker's move today — price-level, identical for any
  qty (1 share or 1000).
- Edge case: a transaction dated TODAY shows total ≈ day gain. Correct,
  not a bug.
- SELL rows keep interim semantics (gain vs live price) — known
  limitation above, resolved in Step 3.

Decisions:

- Rename keys `gain` → `total_gain`, `gain_pct` → `total_gain_pct`
  (self-documenting now that two kinds exist; only consumer is main.js).
- TWO separate columns — "Day Gain" (+ currency, mirroring Total Gain)
  and "Day Gain %". Table grows to 10 columns.
- Easy-to-break contract found: the ledger's column count lives in TWO
  places (the `<th>` row AND `setLedgerMessage`'s colSpan) — one-line
  entry added to AGENTS.md "Contracts that are easy to break".

Subtasks:

- [x] `app.py`: decoration loop — rename to total_gain/total_gain_pct,
      add day_gain (`quote["change"] * qty`) and day_gain_pct
      (`quote["change_pct"]`) with total-vs-day comments; docstring key
      list updated
- [x] `index.html`: rename Gain → Total Gain, Gain % → Total Gain %;
      append Day Gain and Day Gain % headers (class="num")
- [x] `main.js`: renderLedger — read renamed keys; two new cells
      (.num .ledger-live, pos/neg from day_gain >= 0, "—" gap-fill,
      formatSigned with currency for Day Gain, +x.xx% for Day Gain %);
      row.append updated; setLedgerMessage colSpan 8 → 10; banner comment
      key list updated. Total and Day pairs colour INDEPENDENTLY (a
      position can be green overall while red today).
- [x] AGENTS.md: added the colSpan-vs-th-count contract line
- [x] Verified (2026-08-31, Flask test client — same process as the
      decoration, so the quote cache is shared and the comparison is
      race-free): day_gain == change × qty, day_gain_pct == change_pct,
      total_gain semantics unchanged. First curl-based check showed a
      false mismatch — lesson: two separate processes = two separate
      Yahoo fetches = prices drift between them. Test rows cleaned.
- [ ] UI check by user (now 10 columns)

### Step 3 — Holdings view + sell semantics ← CURRENT

- [ ] Aggregate transactions into holdings (net qty per ticker)
- [ ] Average cost basis (how: average-cost method — decide exact rule when
      partial sells arrive)
- [ ] Realized gain on SELL rows (needs the cost basis above)

### Step 4 — Real portfolio chart (documented rework trigger)

- [ ] Replace the hardcoded placeholder series in main.js with real
      portfolio value history computed from the ledger + historical prices
      (project-brief.md says this trigger fires "as soon as the transaction
      ledger exists")
- [ ] Wire up the decorative timeframe buttons (1D–MAX) to fetch ranges

### Housekeeping opportunity (noted, not scheduled)

- project-brief.md's rework trigger: consider moving the in-memory quote
  cache into the same SQLite database now that one exists. Deliberately NOT
  done in step 1 — don't couple the two changes.
