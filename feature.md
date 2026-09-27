# Ledger Trade Sanity Warnings (roadmap #45)

Status: in progress

The ledger's write routes validate field SHAPE only. This feature adds
server-computed, NON-BLOCKING sanity warnings returned with a saved
transaction. The write always happens; the form shows the warnings so a
mistake is visible. This is deliberately separate from #31 (import duplicate
detection), which compares paste-imported rows BEFORE writing.

Three warnings, in this fixed order:
1. a date in the future,
2. a SELL larger than the position held on that date,
3. a same-day duplicate (same ticker, date, type, quantity, AND price).

Write every failing test named below FIRST, then implement, then run the
FULL `python -m pytest` suite. Never commit.

## Locked decisions (user-approved)
- Duplicate match fields: ticker, date, type, qty, AND price (fee ignored).
  qty and price compared with the module tolerance `FLAT_QTY_TOL` (1e-9).
- Warnings are non-blocking: POST still returns 201 and stores; PUT still
  returns 200 and stores.
- Display: an inline `.tx-warnings` block under the form (persists until the
  next submit). Adds `static/style.css` to the roadmap's file list.
- Import preview/commit replies are NOT touched.
- No schema change, no new endpoint, no new migration.

## 1. app.py — pure helper `compute_trade_warnings`

Place immediately AFTER `validate_tx_fields` (so it sits with the other
transaction-field logic) and BEFORE `_derive_fx_rate`.

```python
def compute_trade_warnings(rows, *, ticker, transaction_date, qty, price,
                           transaction_type, exclude_id, today=None):
    """Return human-readable, NON-BLOCKING warnings for one saved trade.

    `rows` is db.get_transactions(portfolio_id) — stored facts, newest
    first (order is irrelevant: the future check is per-field and the
    oversell fold is a sum). `exclude_id` is the row the route just
    wrote (POST) or updated (PUT): a row must never flag itself.

    Pure and side-effect free: no DB, no network. The route owns the
    fetch and the reply. Warnings never block a write.
    """
    warnings = []
    today_iso = (today or date.today()).isoformat()

    if transaction_date > today_iso:
        warnings.append("date is in the future")

    if transaction_type == "SELL":
        held = 0.0
        for row in rows:
            if row["id"] == exclude_id:
                continue
            if row["ticker"] != ticker:
                continue
            if row["transaction_date"] > transaction_date:
                continue
            if row["transaction_type"] == "BUY":
                held += row["qty"]
            else:
                held -= row["qty"]
        if qty > held + FLAT_QTY_TOL:
            warnings.append(
                f"sell of {qty:g} exceeds the {held:g} shares held on "
                f"{transaction_date}"
            )

    for row in rows:
        if row["id"] == exclude_id:
            continue
        if (row["ticker"] == ticker
                and row["transaction_date"] == transaction_date
                and row["transaction_type"] == transaction_type
                and abs(row["qty"] - qty) <= FLAT_QTY_TOL
                and abs(row["price"] - price) <= FLAT_QTY_TOL):
            warnings.append(
                "duplicate: same ticker, date, type, quantity and price "
                "already logged"
            )
            break

    return warnings
```

Notes for the implementer:
- `date` and `FLAT_QTY_TOL` already exist at module scope. Do not add imports.
- The oversell branch uses `<=` on the date so same-day buys count and
  same-day other sells subtract. A SELL that opens a short therefore warns
  by design (shorting is supported; this is a warning, not an error).
- `{qty:g}` / `{held:g}` format without trailing zeros. `held` may be
  negative (already short) — the message shows the negative number; that is
  honest.

## 2. app.py — wire into POST `log_transaction`

After the `tx_id = db.add_transaction(...)` call and the existing INFO log,
compute warnings and add them to the 201 reply:

```python
    warnings = compute_trade_warnings(
        db.get_transactions(g.portfolio_id),
        ticker=ticker,
        transaction_date=fields["transaction_date"],
        qty=fields["qty"],
        price=fields["price"],
        transaction_type=fields["transaction_type"],
        exclude_id=tx_id,
    )
```

Then add `"warnings": warnings,` to the returned dict (anywhere among the
keys; put it last for readability).

## 3. app.py — wire into PUT `edit_transaction`

Immediately before the `return jsonify(stored)`:

```python
    stored["warnings"] = compute_trade_warnings(
        db.get_transactions(g.portfolio_id),
        ticker=stored["ticker"],
        transaction_date=fields["transaction_date"],
        qty=fields["qty"],
        price=fields["price"],
        transaction_type=fields["transaction_type"],
        exclude_id=tx_id,
    )
```

The reply is still the DB row plus this one added key; the existing
log line and re-read behavior are unchanged.

## 4. Frontend — inline warning block

### 4a. templates/ledger.html

Immediately after `<p class="tx-error" hidden></p>` (line ~191), add:

```html
                <!-- Non-blocking sanity warnings for a JUST-SAVED trade
                     (future date, oversell, same-day duplicate). The write
                     already happened — this is a notice, not an error. -->
                <ul class="tx-warnings" hidden></ul>
```

Keep it INSIDE `#tx-logger-wrap`, directly below the error line.

### 4b. static/js/ledger.js

1. Near the existing `const txErrorEl = document.querySelector(".tx-error");`
   (line ~43), add:
   ```js
   const txWarningsEl = document.querySelector(".tx-warnings");
   ```

2. Add a small paint helper near `setLedgerMessage` (or just above the
   submit handler) that wipes and rebuilds the list:
   ```js
   function setTradeWarnings(messages) {
       txWarningsEl.textContent = "";
       for (const message of messages) {
           const item = document.createElement("li");
           item.textContent = message;
           txWarningsEl.append(item);
       }
       txWarningsEl.hidden = messages.length === 0;
   }
   ```

3. In the submit handler, at the same place `txErrorEl.hidden = true;`
   runs (fresh attempt), also clear warnings:
   `setTradeWarnings([]);`

4. On the SUCCESS branch, BEFORE `exitEditMode();`, read the reply body and
   paint its warnings. The response body may not be JSON (defensive):
   ```js
   const saved = await response.json().catch(() => null);
   setTradeWarnings(saved?.warnings || []);
   ```
   Order matters: `exitEditMode()` resets the FORM fields but must not wipe
   the warning block, so paint before or after it — the helper only touches
   `.tx-warnings`, never the form. Keep `exitEditMode(); refreshLedgerViews();`
   exactly as they are.

### 4c. static/style.css

Directly after the `.tx-error` rule (line ~1922) add:

```css
/* Non-blocking trade warnings — the amber "state, not error" palette (the
   write already happened), so red stays reserved for a failed save. */
.tx-warnings {
    color: var(--accent);
    font-size: 13px;
    margin: 0 0 10px;
    padding-left: 18px;
}
```

Use the existing `--accent` token (no new variable). If `--accent` is a
link/button color that reads oddly, fall back to the existing warning/state
token in style.css — pick ONE and keep the class name `.tx-warnings`.

## 5. NEW tests/trade_warnings tests — write FIRST, all must fail

File: `tests/test_trade_warnings.py`.

Imports:
```python
import db
import app as app_module
from app import compute_trade_warnings
from conftest import make_quote, seed_user, main_portfolio_id
```

Helper:
```python
def seed(price, qty, side="BUY", date="2026-08-01",
         currency="CAD", fx=1.0, ticker="ABC", pid=1):
    return db.add_transaction(ticker, date, price, qty, currency, side, fx,
                              portfolio_id=pid)
```

For every route test set a quote so POST accepts the ticker:
```python
fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
```

Route tests use the `client` fixture (signed in as tester, portfolio 1).
CAD tickers avoid FX fetches (fx_rate derived as 1.0 with no market call).

### Pure-helper tests
1. `test_helper_future_date_warns` — `today=date(2026,1,1)` and
   `transaction_date="2026-01-02"` → `["date is in the future"]`; pass the
   same date as `today` → `[]` (boundary: today is not future).
   Import `date` from `datetime`.
2. `test_helper_oversell` — rows = one BUY 10 on 2026-08-01; call with SELL
   qty 15 date 2026-08-02, exclude_id=999 (the saved row is NOT in rows).
   Assert one warning containing "exceeds the 10 shares held".
3. `test_helper_oversell_boundary_and_partial` — hold 10, sell 10 → no
   oversell warning; hold 10, sell 4 → none.
4. `test_helper_oversell_tolerance` — hold 0.1+0.2 (two rows), sell 0.3 →
   no oversell warning (float residue, locked).
5. `test_helper_oversell_ignores_later_rows` — hold 10 on 2026-08-01, a BUY
   dated 2026-09-01 must NOT count toward a 2026-08-02 sell.
6. `test_helper_duplicate_requires_all_five_fields` — a matching row
   (ticker/date/type/qty/price) warns; then one field changed each time
   (ticker, date, type, qty, price) does NOT warn.
7. `test_helper_duplicate_excludes_self` — pass `exclude_id` equal to the
   matching row's id → no warning.
8. `test_helper_clean_buy_has_no_warnings` — no rows, BUY qty 5 price 10
   date in the past → `[]`.

### Route tests
9. `test_post_returns_empty_warnings_for_clean_buy` — 201, body
   `"warnings" == []`, row stored.
10. `test_post_reports_oversell_but_still_writes` — seed BUY 10, POST SELL
    15 → 201; `body["warnings"]` has one oversell entry; the new row is in
    `db.get_transactions(1)` (the write happened).
11. `test_post_reports_future_date_but_still_writes` — POST date
    "2999-01-01" → 201, warning mentions future, row stored.
12. `test_post_reports_same_day_duplicate` — happy POST, then POST the SAME
    body again → second reply has a duplicate warning and the row count is 2.
13. `test_put_does_not_flag_itself` — seed a row, PUT it with unchanged
    values → 200 and `body["warnings"] == []` (self is excluded, so no
    duplicate and no oversell on the edited SELL).
14. `test_put_reports_warning_and_applies_edit` — seed BUY 10 then a SELL
    row of qty 4; PUT the SELL to qty 15 → 200, warning mentions oversell,
    and the stored qty is 15.
15. `test_import_preview_and_commit_have_no_warnings_field` — import preview
    reply has no `warnings` key; commit reply has no `warnings` key.
16. `test_warning_log_does_not_leak_amounts` — optional if caplog is easy;
    the route log lines (`event=transaction_created`) must not contain the
    warning text or the qty. If this proves brittle, drop it — the existing
    logging tests already lock the no-amount rule.

If any assertion about a helper's return shape turns out wrong (e.g.
`db.add_transaction` positional args), read `db.py` and adjust the TEST,
never the contract. `db.add_transaction` signature is
`(ticker, transaction_date, price, qty, currency, transaction_type, fx_rate,
fee=None, *, portfolio_id)`.

## 6. Order of work
1. Write ALL failing tests → `python -m pytest tests/test_trade_warnings.py`
   (expect failures / collection errors).
2. Implement `compute_trade_warnings`.
3. Wire POST and PUT.
4. Implement the frontend block (html, js, css).
5. `python -m pytest tests/test_trade_warnings.py` to green.
6. Run the FULL `python -m pytest` (Docker + ledger meta-tests stay green).
7. Capture a screenshot of the ledger form showing warnings (UI PR rule).
8. Report; await the user's GUI gate and commit approval. Do not commit.
