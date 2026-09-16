# Feature: Ledger ticker pick auto-fills the latest price

## Status
Implemented (both increments); FULL suite green (461 passed). NEXT STEP:
user GUI check of the 2-decimal display + accurate-value behavior on
/ledger, then commit gate on explicit yes.

## Delivered
- `app.py`: `GET /api/quote/<symbol>` — the get_quote dict WITHOUT the
  heavy get_name call (copy-before-return, case-normalized, 404 on
  unquotable symbols).
- `ledger.js`: `prefillPriceForTicker()` helper + form state
  (`autofillPrice` / `priceEdited` + a Price-field `input` listener):
  clears the field, fetches the quote, stale-guards the reply, keeps the
  FULL price in `autofillPrice` and displays `toFixed(2)`; wired into BOTH
  the dropdown onPick and the deep-link prefill block. `enterEditMode` uses
  the exact stored `tx.price` (no live fetch) with a 2-decimal display;
  `exitEditMode` resets the backing; the submit ships the accurate price
  when untouched and the typed value when edited.
- `tests/test_quote.py` (4 route tests) + `tests/test_price_autofill.py`
  (11 string-lock tests, updated for the display/backing split).

## Plan
When a symbol lands in the ledger form's Ticker field — via the suggestion
dropdown OR the stock page's deep-link (`/ledger?ticker=AAPL`) — the Price
field first CLEARS, then fills with the live native-currency price from the
quote. A failed fetch leaves Price empty (quiet, no toast — the backend
re-validates at submit anyway). Both were user-approved decisions.

INCREMENT (approved): the field DISPLAYS only 2 decimals, while everything
that gets LOGGED keeps the full accurate number (user: "all calcs should
use actual accurate numbers not rounded"). The app-wide rule elsewhere
(stored full floats, painted 2 decimals) now applies to the form too.

1. `app.py` — new lightweight `GET /api/quote/<symbol>` route beside the
   stock routes: case-normalizes, `dict(get_quote(symbol))` (copy — the
   shared-cache rule), 200 with the get_quote payload (price,
   previous_close, currency, change, change_pct), and 404 on unquotable
   symbols — all mirroring `stock_quote`, but WITHOUT the heavy `get_name`
   `.info` fetch (the form only needs the number).
2. `static/js/ledger.js` — a shared `prefillPriceForTicker()` helper plus
   form-level accurate-value state:
   - `autofillPrice` (module var) — the ACCURATE number behind a cosmetic
     2-decimal display; `priceEdited` (module var) — flipped true by an
     `input` listener on the Price field (programmatic `.value` sets never
     fire `input`, so a fill stays "untouched").
   - `prefillPriceForTicker`: clears the field, fetches
     `/api/quote/<URL-encoded symbol>`, stale-guards the reply, then
     `autofillPrice = quote.price; priceEdited = false;` and DISPLAYS
     `value = quote.price.toFixed(2)` (raw number string — no Intl grouping,
     which a type="number" input rejects). Failure → Price stays empty,
     console.error only.
   - `enterEditMode`: `autofillPrice = tx.price` (the STORED fact — no live
     fetch, edit mode never quotes), `priceEdited = false`, DISPLAYS
     `tx.price.toFixed(2)` — one consistent "show 2, back with accurate"
     rule for every programmatic fill.
   - `exitEditMode`: `autofillPrice = null` (form reset() clears the field;
     for BOTH success paths).
   - submit handler: `price: priceEdited ? Number(fields.price) :
     (autofillPrice ?? Number(fields.price))` — your typed value wins when
     you edited the field; otherwise the exact accurate price reaches the
     backend and every calculation.
   - Edit mode stays quote-inert: the ticker input is disabled there, and
     `prefillPriceForTicker` is never called in edit mode.

## Test plan (FIRST — must fail until implemented)
1. `tests/test_quote.py` (backend route, fake_market style like
   test_stock.py / test_routes.py):
   - 200 + full get_quote payload, with NO `name` key;
   - case normalization (`/api/quote/aapl`);
   - 404 for an unquotable symbol;
   - 200 even when `get_name` would raise (names dict empty) — proves the
     route never touches the heavy name fetch.
2. `tests/test_price_autofill.py` (string-lock style) — UPDATED for the
   increment:
   - `@app.route("/api/quote/<symbol>")` present in app.py;
   - ledger.js defines `function prefillPriceForTicker(`; clears
     `price.value = ""`; fetches `/api/quote/`;
   - display is 2-decimal: `price.value = quote.price.toFixed(2)` present;
   - accurate backing: `autofillPrice = quote.price` present;
   - dirty listener: `priceEdited = true` present on the price input;
   - submit substitution: `priceEdited ? Number(fields.price)` and
     `autofillPrice ?? Number(fields.price)` present;
   - edit mode: `autofillPrice = tx.price` + `tx.price.toFixed(2)` present;
   - reset: `autofillPrice = null` present;
   - called from BOTH the dropdown onPick path and the deep-link prefill
     block (unchanged locks).

Existing tests must keep passing: `test_stock.py`'s quote tests are
unaffected (separate route); `test_ticker_suggestions.py`'s locks on the
`onPick` ticker assignment stay intact (we only ADD the prefill call).

## Gates
Full `python -m pytest` green → user GUI check on /ledger → commit only on
explicit yes.