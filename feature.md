# Feature #18: Ledger Quick Sell

## Status

IMPLEMENTED 2026-09-21. Tests written first (20 new in
`tests/test_ledger_quick_sell.py`), production code in `static/js/ledger.js`
plus a keyboard `:focus-within` reveal in `static/style.css`, and all 732
tests pass. Awaiting the user's browser GUI approval before any commit or push.

This plan replaces the shipped Feature #9 handoff. Feature #9 shipped in PR
#63 and remains recorded in `roadmap.md`.

## Problem

Selling a complete holding currently requires the user to copy five facts into
the transaction form: ticker, net quantity still held, current native price,
current local date, and the `SELL` operation. The collapsed ticker row already
has these facts. Retyping them is slow and can cause quantity, price, or
operation mistakes.

The quick action must only prepare a transaction. It must not submit the sale
without review because price and quantity become permanent ledger facts.

## Goal

Add a `Sell` action to each eligible ticker summary row on `/ledger`. Clicking
it prepares the existing transaction form to sell the complete positive
position at the latest available native-market price on the user's local date.
The user can change every prepared value before pressing `Log`.

## Locked Product Decisions

1. Put the action on ticker group rows, not transaction detail rows.
2. Reuse the existing transaction form. Do not add a modal or second form.
3. Fill quantity with `sum(BUY qty) - sum(SELL qty)` for the ticker.
4. Fill price from `price_now`. This is the exact native quote even when the
   ledger currently displays CAD-converted values.
5. Display the price to two decimals but retain exact `price_now` through the
   existing `autofillPrice` state. A user edit continues to override it.
6. Fill date with the existing local-time `todayLocalISO()` helper.
7. Set the operation to `SELL`.
8. Never submit automatically. The user must review and press `Log`.
9. Show the action only when net quantity is greater than the existing `1e-9`
   flat-position tolerance and `price_now` is finite and positive.
10. Hide it for closed, near-zero, short, SELL-only, and unquoted groups. Do
    not show a disabled control.
11. If a complete refresh fails while old rows remain, remove rendered Sell
    actions when live cells are marked unavailable. Do not offer a quote that
    the page has just identified as stale.
12. A per-symbol quote failure hides the action only for that ticker.
13. Share the existing actions cell with bulk delete. Do not change columns.
14. Keep the action available on touch through the existing action visibility
    rule and on pointer devices through row hover and keyboard focus.
15. Preserve fractional quantity exactly; do not round it before form fill.
16. Keep the existing POST route as the authority for validation, currency,
    historical FX, persistence, and errors.

## Existing Contracts To Preserve

1. The ledger keeps exactly 11 columns. Template headers,
   `setLedgerMessage.colSpan`, `buildGroupRow`, and `buildTxRow` stay aligned.
2. The actions column stays pinned last and cannot be dragged.
3. Group clicks still expand rows, except clicks from links or
   `.tx-action-btn` controls.
4. Group delete-all and detail edit/delete actions remain unchanged.
5. `groupSortKeys()` remains the frontend source for exact net quantity.
6. Closed-position visibility remains controlled by `showClosedPositions`.
7. Shorts remain visible active positions but receive no Sell action.
8. The ledger currency toggle must not convert the prepared native price.
9. Backend floats remain raw; display formatting stays in JavaScript.
10. Programmatic prices retain exact precision through `autofillPrice`, with
    `priceEdited = false`; a user edit sets it true and wins at submit.
11. Quick Sell exits edit mode first, enabling the ticker and ensuring POST is
    used instead of PUT.
12. Successful POST behavior remains: expand ticker, reset form, refresh data.
13. Privacy mode may mask displayed quantity but cannot alter the exact value
    used for form preparation.
14. Polling continues through `setupAutoRefresh`; add no interval.
15. No database, route, response-shape, market-data, Android, dependency, or
    deployment change is needed.

## Files

Production:

- `static/js/ledger.js`
- `static/style.css` only if a minimal Sell-specific focus, hover, or spacing
  rule is necessary

Tests:

- add `tests/test_ledger_quick_sell.py`
- update an existing ledger CSS test only if it is the precise home for a
  touch-visibility assertion

Planning:

- `feature.md`
- `roadmap.md`

No template, Python, database, Android, dependency, or deployment edit is
planned.

## Test-First Plan

Create `tests/test_ledger_quick_sell.py` before production edits. Pytest does
not run browser JavaScript, so use focused source/meta-tests in the repository's
existing style. Do not lock unrelated comments or broad file layout.

### A. Eligibility And Construction

1. Assert `buildGroupRow()` reuses `groupSortKeys(txs).netQty` for displayed
   quantity and Sell eligibility.
2. Assert one Sell button is created in the existing group actions cell.
3. Assert it has `.tx-action-btn`, a stable `.ticker-sell-btn` hook, and a
   button type that cannot submit any surrounding form accidentally.
4. Assert it stores the canonical ticker in `data-ticker`; quantity and price
   must not be serialized from rounded DOM text.
5. Assert it is ordered before destructive delete-all.
6. Assert eligibility requires `netQty > 1e-9`.
7. Assert eligibility requires finite, positive `txs[0].price_now`.
8. Assert exactly one action is produced for a multi-transaction group.
9. Assert no action for zero, `1e-9`, smaller positive residue, negative,
   SELL-only, missing-price, null-price, NaN, infinite-price, or non-positive
   price cases.
10. Assert eligibility is independent of group value, `price_display`, display
    currency, privacy state, and expansion state.

### B. Form Preparation

Add a focused helper such as `prepareFullSale(ticker, txs)` and assert:

1. It defensively rechecks exact net quantity and exact live price at click.
2. It returns without changing the form if either is no longer eligible.
3. It calls `exitEditMode()` before filling to clear an old edit target,
   re-enable ticker, restore `Log`, hide edit state, and clear old errors.
4. It fills ticker from the group identity.
5. It fills unrounded net quantity from transaction facts, not cell text.
6. It fills date with `todayLocalISO()` rather than UTC ISO conversion.
7. It selects `SELL`.
8. It assigns exact live price to `autofillPrice`.
9. It sets `priceEdited = false`.
10. It displays `price.toFixed(2)` without changing exact backing precision.
11. It scrolls the existing form into view with smooth/nearest behavior.
12. It does not call `requestSubmit`, dispatch submit, call `fetch`, show a
    confirmation, or directly invoke POST.

### C. Delegated Click Wiring

1. Assert the existing delegated actions listener recognizes
   `.ticker-sell-btn` before delete branches.
2. Assert it reads the ticker and filters the current `lastTransactions` rows
   for that ticker.
3. Assert it sends cached rows to the preparation helper and returns.
4. Assert the group expansion listener continues to ignore it through the
   shared `.tx-action-btn` guard.
5. Assert no formatted table cells are scraped.

### D. Failed Refresh Safety

1. Assert `markLedgerUnavailable()` removes rendered `.ticker-sell-btn`
   controls on a complete refresh failure.
2. Assert live cells still become `—` and lose sign classes.
3. Assert edit, detail delete, and bulk delete controls remain.
4. Assert later successful rendering recreates eligible actions naturally.
5. Assert per-symbol missing `price_now` suppresses only that ticker's action.
6. Do not clear a form already prepared before a later poll fails; copied
   values are now editable user input awaiting review.

### E. Precision And Submission Regression

1. Keep all `tests/test_price_autofill.py` precision contracts green.
2. Assert untouched Quick Sell uses exact `autofillPrice` at submit.
3. Assert a manually edited prepared price uses the typed number.
4. Assert fractional quantity flows through existing `Number(fields.qty)`.
5. Assert prepared type flows through existing FormData as `SELL`.
6. Assert no second submit implementation is introduced.

### F. Layout And Accessibility

1. Assert visible text or accessible labeling clearly identifies Sell and the
   ticker where appropriate.
2. Assert it shares the actions cell rather than adding a column.
3. Assert shared action controls remain visible under `@media (hover: none)`.
4. If CSS is needed, assert existing tokens, visible keyboard focus, and no
   destructive red treatment for the non-destructive preparation action.
5. Assert no fixed viewport width, overflow workaround, or breakpoint is added.
6. Keep all 11-column tests unchanged and green.

### G. Regression Scope

Run existing coverage for grouping/net quantity, column count, price autofill,
ledger page and mobile CSS, transaction POST, privacy, closed-position display,
sorting, column ordering, refresh, and recovery. Add backend tests only if an
uncovered backend contract is discovered; no backend change is expected.

## Implementation Plan

Implementation begins only after the tests above fail for the intended missing
behavior.

### 1. Add The Group Action

1. In `buildGroupRow(ticker, txs)`, reuse its existing `netQty` value.
2. Read native `price_now` from the group's first transaction.
3. Calculate eligibility from tolerance and finite positive price.
4. For eligible groups, create one text button labeled `Sell` with shared and
   dedicated classes, `data-ticker`, and a concise accessible title.
5. Append it before `deleteTickerBtn` in `actionsCell`.
6. Leave ineligible actions absent.
7. Do not change the `cells` map, column ordering, or row data.

### 2. Prepare The Existing Form

1. Add one helper near `enterEditMode()` and `exitEditMode()`.
2. Recheck eligibility from passed cached transaction rows.
3. Call `exitEditMode()` first.
4. Fill ticker, exact quantity, local date, and `SELL`.
5. Back the two-decimal price display with exact `autofillPrice` and clear
   `priceEdited`.
6. Scroll the form into view.
7. Do not submit, fetch, confirm, or refresh.

### 3. Wire The Action

1. In the delegated action listener, detect `.ticker-sell-btn` before delete.
2. Filter `lastTransactions` by its ticker.
3. Call the preparation helper and return immediately.
4. Preserve edit and both delete branches exactly.

### 4. Remove Stale Actions

1. Extend `markLedgerUnavailable()` to remove only Quick Sell buttons.
2. Keep current live-cell degradation intact.
3. Let the next successful `renderLedger()` recreate valid controls.

### 5. Use Minimal Styling

Prefer existing `.tx-action-btn` styles. Add CSS only if browser inspection
shows a spacing or focus defect. If needed, reuse tokens, retain hover/touch
visibility, keep focus visible, avoid destructive red, and do not alter table
or mobile-card geometry.

### 6. Comments

Document only non-obvious rules: `price_now` remains native in CAD display,
exact precision backs the rounded field, eligibility requires positive owned
quantity plus a quote, and failed refreshes invalidate unclicked actions.

## Verification

Run focused tests:

```bash
source .venv/bin/activate
python -m pytest tests/test_ledger_quick_sell.py
python -m pytest tests/test_price_autofill.py tests/test_ledger_groups.py tests/test_ledger_col_count.py
python -m pytest tests/test_ledger_page.py tests/test_ledger_css.py tests/test_privacy_toggles.py
python -m pytest tests/test_routes.py
```

Then the lead agent runs:

```bash
source .venv/bin/activate
python -m pytest
```

No implementation is complete until the full suite passes.

## Browser GUI Approval Checklist

After pytest passes, stop for user inspection before any commit or push.

1. Desktop light and dark modes: Sell and delete fit without crowding.
2. Pointer and keyboard: Sell reveals/focuses and does not expand the group.
3. Mobile/touch: Sell is visible without hover and causes no overflow.
4. Positive and partially sold holdings: full remaining quantity is filled.
5. Fractional holding: precise complete quantity is filled.
6. Ticker, current native price, local date, and SELL are all filled.
7. Price shows two decimals; untouched submission stores exact quote precision.
8. User changes to price or quantity are honored.
9. Clicking Sell during edit mode prepares a new POST, not a PUT correction.
10. Closed, near-zero, short, SELL-only, and unquoted groups show no Sell.
11. CAD/native toggle does not change the prepared native price.
12. Privacy mode still prepares actual quantity despite masking its display.
13. Successful sale refreshes normally and respects closed-position settings.
14. Complete refresh failure removes unclicked Sell actions; recovery restores
    eligible actions.
15. Existing bulk delete, detail actions, sorting, dragging, expansion, and
    polling remain functional.

## Completion Gates

1. Detailed plan and roadmap item #18 `in progress`: complete after this edit.
2. User approves this plan before implementation.
3. Write failing tests first.
4. Implement production code.
5. Pass focused tests.
6. Pass full `python -m pytest`.
7. Obtain browser GUI approval.
8. Only then ask whether to commit and push.
9. Mark #18 shipped only in the approved commit, with PR number and date or a
   direct-main date.

## Definition Of Done

Every positively held and currently quoted ticker has one safe Quick Sell
action that prepares, but never submits, an exact full-position SELL in the
existing form. Closed, short, unavailable, and stale positions cannot offer the
action. Precision, ledger layout, mobile, accessibility, and existing actions
remain correct; all tests pass; and the user approves browser behavior.
