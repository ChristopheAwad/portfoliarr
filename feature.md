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

Deferred (recorded, not scheduled): prefilling the price field from the
live quote once a ticker is entered. (Row edit/delete WAS deferred here —
now scheduled as Step 2d below.)

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

### Step 2c — Grouped ledger view (collapsed by ticker, expandable) ✅ DONE

The flat one-row-per-transaction table repeats the same ticker over and
over and grows without bound. Now transactions group by ticker: one
collapsed summary row per ticker, expandable to reveal the individual
transactions underneath.

Decisions made (2026-08-31):

- **Pure frontend.** `/api/transactions` already returns the flat
  decorated list; grouping is display logic, so `app.py` is untouched
  (AGENTS.md layering: main.js renders, the backend sends facts + floats).
- **Summary aggregates = BUY rows only.** The collapsed row reflects
  CURRENT holdings: net Qty = Σ(buy qty) − Σ(sell qty); Value / Total
  Gain / Day Gain sum BUY rows only; Total Gain % = Σ total_gain ÷
  Σ(price × qty of BUYs) × 100. Why: a SELL row's "value" is what the
  *sold* shares would be worth today — summing that into a group total
  inflates it. This matches Step 3's upcoming holdings math. SELL
  details stay visible when expanded.
- **Day Gain % in the summary** is the ticker's daily move — price-level,
  identical for every row in the group (see Step 2b semantics), so it's
  read from any decorated row rather than aggregated.
- **Grouping preserves backend order.** Groups appear in first-appearance
  order of the newest-first list — the most recently transacted ticker
  on top.
- **Expansion state lives in a Set, not the DOM.** `renderLedger` rebuilds
  the tbody every 60s poll (watchlist pattern), so anything stored only in
  the DOM dies with each rebuild. `expandedTickers` (a Set of tickers)
  survives rebuilds; clicking a summary row toggles membership AND flips
  the `hidden` attribute on that group's detail rows directly — instant,
  no re-fetch.
- **Collapsed by default, always** — even a lone-transaction group.
  One exception: after a successful POST, the logged ticker's group
  auto-expands so the row just entered is visible immediately.
- **Guarded percentages.** A SELL-only group has no cost basis → Σ cost
  is 0 → Total Gain % shows "—" instead of dividing by zero.
- **Undecorated groups degrade wholesale.** app.py decorates per *unique
  ticker*, so within a group either every row has live math or none —
  the summary's live cells either fill or all gap-fill to "—". No
  partial-group ambiguity exists by construction.

Subtasks:

- [x] feature.md: this section
- [x] main.js: extract `buildTxRow(tx)` from renderLedger's loop (returns
      the existing 10-cell `.ledger-row`, unchanged)
- [x] main.js: `expandedTickers` Set + reworked renderLedger — group via
      Map (first-appearance order), summary row per group (caret +
      "N txns" in the Date cell, blank Type, bold ticker, net qty, "—"
      price, BUY-only sums with pos/neg, guarded Total Gain %, day % from
      any decorated row), then hidden detail rows via buildTxRow
      (`row.hidden = !expandedTickers.has(ticker)`)
- [x] main.js: delegated click listener on ledgerBody (watchlist ×-button
      pattern — survives rebuilds): toggle ticker in expandedTickers,
      flip `hidden` on `.tx-detail` rows directly; CSS.escape for tickers
      like "BRK.B"
- [x] main.js: POST success adds the logged ticker to expandedTickers
      before refreshLedger()
- [x] style.css: .ledger-group (cursor pointer, hover bg, bold ticker),
      caret rotates on .open, detail rows visually subordinate
- [x] AGENTS.md: extended the colSpan contract line — the group summary
      row (`buildGroupRow`) is a third place the 10-column count matters
- [x] Verified (2026-08-31, Flask test client — same process as the quote
      cache): seeded 2 AAPL BUYs + 1 AAPL SELL + 1 SHOP.TO SELL; confirmed
      all-or-nothing decoration per group, net qty = 12 (buys − sells),
      BUY-only sums match the closed forms by hand
      (gain = 15×live − 3100), Total % = Σgain ÷ Σcost, SELL-only group
      has cost 0 → "—" guard, day_gain_pct uniform within a group.
      Smoke test: `GET /` 200, `/api/transactions` decorated.
      LESSON: the ledger held real user rows (ids 1–2, CM + AAPL) — test
      scripts must filter/assert by seeded id only, never assume an empty
      table; cleanup deleted exactly the seeded ids, user rows untouched.
      (No node on this machine — JS reviewed by read-through; no automated
      frontend test exists yet.)
- [ ] UI check by user: groups collapsed by default; clicking a summary
      row expands/collapses its transactions; expansion survives the 60s
      poll; logging a new transaction auto-expands its group; summary
      shows net qty + BUY-only aggregates; a ticker whose quote fails
      shows "—" in the summary's live columns

### Step 2d — Edit & delete transactions ← CURRENT

The ledger was append-only (an explicit Step 2 decision, since un-deferred
here): a typo'd price or qty was in there forever. Now each transaction can
be corrected in place or removed — with one hard boundary: **edits touch
only what the USER typed, never anything yfinance-derived.**

Decisions made (2026-08-31):

- **The ticker is the row's identity and is NOT editable.** Editable
  fields: date, price, qty, type. Why: currency was auto-derived from the
  ticker at insert time (a yfinance fact); letting the ticker change would
  force the backend to re-quote and silently rewrite that fact mid-edit.
  The user's rule — "edit my input, not yfinance's data" — makes the
  boundary exact. A wrong ticker is a wrong identity: delete + re-log.
  (User confirmed date IS editable; only price/qty/type was the
  alternative on the table.)
- **PUT semantics, honest body.** `PUT /api/transactions/<id>` takes
  exactly `{date, price, qty, type}` — no ignored fields. If a client
  sends a `ticker` anyway, the backend IGNORES it (validated in a test).
- **Validation is shared, not duplicated.** The date/price/qty/type checks
  move out of `log_transaction` into one `validate_tx_fields(body)` helper
  used by BOTH POST and PUT — otherwise the two routes' rules could drift
  and an edit could create a state the POST route would have rejected.
  POST keeps its ticker validation inline (it's the only route that needs
  one).
- **404 before validation.** PUT/DELETE look the row up by id FIRST —
  "no transaction with id 99" beats "date must be YYYY-MM-DD" when the id
  was the wrong part. `get_transaction()` in db.py serves the existence
  check; `<int:tx_id>` in the route makes Flask 404 non-numeric ids
  itself.
- **Edit reuses the top form** (user choice). Edit mode: prefill the 4
  editable fields, DISABLE the ticker input (visual "identity locked"
  cue), Log → Save, a quiet "Editing TICKER …" notice + Cancel link
  appear. One form, one validation UX, one submit handler that branches
  POST vs PUT. Same reasoning as Step 2's "inline form, not prompt chain":
  the form IS the transaction vocabulary of this UI.
- **Delete asks first.** `confirm()` dialog naming the transaction — the
  DELETE is immediate and the backend has no undo. 204/404 handling
  mirrors the watchlist remove (404 = already gone elsewhere → refresh
  shows the truth).
- **Edit state lives outside the DOM.** `editingTxId` (null = log mode) —
  same reasoning as `expandedTickers`: the tbody rebuilds every 60s, so
  form mode must not depend on rows staying put. On submit success OR
  404 the mode exits; on a 400 it STAYS (fix the field, resave).
- **Actions live on detail rows only** — group summary rows are
  aggregates, not records; they gain a blank 11th cell to keep the
  columns aligned. Edit/delete buttons are only reachable when a group is
  expanded, which is the intended friction: collapsed = overview.
- **Column count 10 → 11** (new trailing actions `<th>`). Per the
  AGENTS.md contract this now lives in FOUR places: thead, colSpan,
  buildGroupRow's blank cell, buildTxRow's actions cell.

Subtasks:

- [x] feature.md: this section + Step 2 deferral note updated
- [x] db.py: `get_transaction(tx_id)` (dict or None),
      `update_transaction(tx_id, transaction_date, price, qty,
      transaction_type)` (touches ONLY the 4 editable columns; returns
      rowcount > 0), `delete_transaction(tx_id)` (returns rowcount > 0) —
      parameterized SQL throughout; ledger banner comment now names all
      four verbs
- [x] app.py: extracted `validate_tx_fields(body)` from log_transaction
      (date/price/qty/type checks, named 400s unchanged, returns
      normalized fields under DB-column names); POST keeps its ticker
      check + get_quote/currency flow
- [x] app.py: `PUT /api/transactions/<int:tx_id>` — 404 unknown id first,
      shared validation, UPDATE of the 4 fields, 200 returns the re-read
      stored row (ticker/currency untouched, sent tickers ignored)
- [x] app.py: `DELETE /api/transactions/<int:tx_id>` — 204 on success,
      404 if already gone
- [x] index.html: 11th blank `<th class="actions">` for actions; tbody +
      card comments mention per-row actions and the form's double duty
- [x] main.js: `editingTxId` + `lastTransactions` cache (refreshLedger
      stores what it fetched); buildTxRow sets `row.dataset.id` and gains
      the actions cell; buildGroupRow + setLedgerMessage go to 11 columns
- [x] main.js: second delegated ledgerBody listener — edit click looks up
      the tx BY ID in the cache and prefills the form (ticker disabled,
      Log→Save, "Editing…" notice, scrollIntoView); delete click
      confirm()s then DELETEs (404 tolerated like the watchlist; exits
      edit mode if the deleted row was the one being edited)
- [x] main.js: submit handler branches POST/PUT on editingTxId; exits
      edit mode on success or 404, stays on 400 (fixable); cancel + reset
      restore log mode and the today-default date
- [x] style.css: quiet hover-reveal .tx-action-btn pair (delete red,
      edit blue), .tx-editing blue notice, .tx-cancel underline button
- [x] AGENTS.md: column-count contract line — FOUR places, 11 columns;
      NEW contract line for the PUT body `{date, price, qty, type}` +
      shared-validator rule
- [x] Verified (2026-08-31, Flask test client — seeded ids only per the
      Step 2c lesson): PUT happy path reflects on GET with ticker/currency
      unchanged; PUT with a "ticker" in the body → field ignored, stored
      ticker unchanged; PUT 404 unknown id AND non-numeric id (Flask's
      <int:> converter); 6 named 400 rejection paths (bad/real-but-impossible
      dates, price 0, qty −5, string price, bad type) + non-JSON body 400;
      DELETE → 204, again → 404, gone from GET; POST regression after the
      validator refactor (lowercase "sell" normalized, CAD auto-filled);
      user's real rows untouched. Live smoke: `GET /` 200, page carries
      the new actions `<th>`, `/api/transactions` decorated.
      (No node on this machine — JS reviewed by read-through.)
- [ ] UI check by user: expand a group, hover a row → ✎/× appear; edit
      prefills the form with the ticker locked, Save applies, Cancel
      returns to Log; delete asks first; a 400 (e.g. qty 0) shows inline
      and KEEPS edit mode; edit mode survives a 60s poll rebuild

### Step 3 — Holdings view + sell semantics

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
