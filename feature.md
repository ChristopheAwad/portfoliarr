# Feature #1: Average Price on Ledger Ticker Rows

## Status

SHIPPED pending merge 2026-09-22 (PR #68). Roadmap item #1 shipped with this
PR. Tests were written first (focused red run: 21 failed with
`KeyError: group_avg_cost` / missing frontend wiring), then production code in
`app.py` and `static/js/ledger.js`. Focused tests, the neighboring ledger
suites, and the full `python -m pytest` run pass (782 passed). The user
approved the browser behavior before the PR was opened. One planned test file
note: the quick-sell meta-test's locked `groupSortKeys` destructure line was
updated to `const { netQty, avgCost } = groupSortKeys(txs);` because the plan
reads both values from that single call.

## Problem

The ledger groups transactions by ticker. Each collapsed ticker parent row
shows the net quantity, current value, gains, and actions, but its Price cell
always shows `—`.

The parent row must instead show the average acquisition price of the shares
that remain in that ticker's current position. This is a cost-pool average,
not net cash flow divided by shares.

Example:

1. BUY 10 shares at 100.
2. SELL 4 shares at 110.
3. The remaining 6 shares still have an average acquisition price of 100.
4. The parent Price cell must show `100.00`, not `(1000 - 440) / 6 = 93.33`.

## Goal

Show the current position's average acquisition price in the Price column of
each ledger ticker parent row.

The calculation must:

1. Replay stored transactions oldest-first.
2. Add opening or same-side quantities to a weighted cost pool.
3. Remove closing quantities at the pool's existing average price.
4. Keep the average unchanged after a partial close.
5. Start a new pool at the crossing transaction's price when a transaction
   crosses through flat from long to short or short to long.
6. Return no average for a flat position.
7. Follow the ledger's CAD/native display toggle and stored-FX rules.
8. Remain available when Yahoo cannot provide a live quote because average
   price uses stored ledger facts only.

## Locked Product Decisions

1. "Average price" means the average acquisition price of the CURRENT open
   position. Sale proceeds do not reduce the remaining shares' average.
2. Use an average-cost pool, not FIFO or LIFO.
3. Long positions are opened or increased by BUY transactions. Their average
   is weighted by BUY price and quantity.
4. SELL transactions first close an existing long at its current average.
   A partial close does not change that average.
5. Short positions are opened or increased by SELL transactions. Their
   average opening price is weighted by SELL price and quantity.
6. BUY transactions first cover an existing short at its current average.
   A partial cover does not change that average.
7. If one transaction crosses through flat, only its excess quantity opens
   the opposite-side pool, at that transaction's own price.
8. A position is flat when `abs(qty) <= 1e-9`, matching the repository's
   established position tolerance. Flat positions have `group_avg_cost =
   null` and display `—`.
9. In `currency=NATIVE` mode, calculate the pool from each transaction's
   native `price`.
10. In default CAD mode, calculate the pool from each transaction's existing
    `price_display`. This preserves the ledger's established cost-side rule:
    each USD transaction uses its stored historical FX rate when available,
    with the route's existing live-rate fallback for quoted legacy rows.
11. The displayed currency comes from the group's existing
    `display_currency`. Do not add a new currency field.
12. The average price is a stored-facts calculation. It does not depend on
    `price_now`, `group_value`, or any successful live quote.
13. A missing quote must not suppress `group_avg_cost` when the stored facts
    can still produce it.
14. If the existing row-decoration rules degrade a USD row to native display,
    calculate the group average from those native `price_display` values and
    label it with that existing native `display_currency`. Never fabricate an
    FX rate.
15. Backend responses contain raw floats or `null`. JavaScript owns decimal
    formatting and the currency suffix.
16. Keep Price non-sortable. This feature changes display only; it does not
    add parent-row price sorting.
17. Do not add columns. The ledger remains an 11-column table.
18. Do not change transaction storage, validation, realized gains, portfolio
    summary math, quick sell, import, polling, or Android code.

## Existing Contracts To Preserve

1. `GET /api/transactions` remains a JSON array of transaction rows.
2. Every transaction builder retains all 11 cell keys, and actions remain the
   last persisted column.
3. Backend group values are attached to every row for that ticker; the
   frontend reads the first row as the group's representative.
4. Unavailable live fields still render `—` and sort last.
5. Parent quantity remains fact-computed in `groupSortKeys` and is available
   during quote failure.
6. Individual transaction Price cells continue to show their own stored
   `price_display`; this feature changes only the ticker parent row.
7. Parent quick sell still uses exact native `price_now`, never the displayed
   average price.
8. The privacy toggle continues to mask Qty, Value, Total Gain, and Day Gain.
   Price is not newly masked.
9. Backend floats remain unformatted. Use the existing `formatNumber` helper
   in JavaScript.
10. The default display remains CAD, and `?currency=NATIVE` still affects only
    the ledger.
11. Missing or unsupported FX must degrade honestly rather than use 1:1.
12. Page polling continues through `setupAutoRefresh`; add no interval.

## Files

Production:

- `app.py` - calculate and attach `group_avg_cost` during ledger decoration.
- `static/js/ledger.js` - read and render the group average in the parent
  Price cell.

Tests:

- `tests/test_ledger_groups.py` - route-level average-cost replay contracts.
- `tests/test_ledger_average_price.py` - focused frontend source/meta-tests.

Planning:

- `feature.md`
- `roadmap.md`

No template, CSS, database, market-data, dependency, Docker, deployment, or
Android edit is expected.

## Test-First Plan

Write all tests in this section before changing `app.py` or
`static/js/ledger.js`. Run the focused tests and confirm that they fail for the
intended reason: `group_avg_cost` does not exist and the parent Price cell is
hard-coded to `—`.

### A. Backend Route Tests - `tests/test_ledger_groups.py`

Update the file's contract comments and helpers so `group_avg_cost` is one of
the documented group fields. Do not weaken any existing group aggregate
assertions.

Add these tests:

1. `test_group_avg_cost_for_one_buy`
   - Seed BUY 10 at 100 in CAD.
   - Return a valid quote.
   - Assert `group_avg_cost == 100.0`.

2. `test_group_avg_cost_weights_multiple_buys`
   - Seed BUY 10 at 100 and BUY 5 at 130.
   - Assert `(10 * 100 + 5 * 130) / 15 == 110.0`.
   - Assert every row in the ticker group carries the same value.

3. `test_partial_sell_preserves_long_average_cost`
   - Seed BUY 10 at 100 and SELL 4 at 110.
   - Assert the six remaining shares have `group_avg_cost == 100.0`.
   - This test must explicitly reject the old roadmap interpretation of
     `group_cost_basis / net_qty == 93.333...`.

4. `test_later_buy_reweights_remaining_long_pool`
   - Seed BUY 10 at 100, SELL 4 at 110, then BUY 4 at 120.
   - The pool before the final buy is 6 shares at 100.
   - Assert the final 10-share average is 108.

5. `test_fully_closed_group_has_null_average_cost`
   - Seed BUY 10 at 100 and SELL 10 at 110.
   - Assert `group_avg_cost is None` on both rows.

6. `test_long_to_short_crossing_starts_new_pool_at_sell_price`
   - Seed BUY 5 at 100 and SELL 8 at 120.
   - Five shares close the long; three shares open a short at 120.
   - Assert `group_avg_cost == 120.0`.

7. `test_short_sales_have_weighted_average_open_price`
   - Seed SELL 4 at 120 and SELL 2 at 90.
   - Assert the six-share short average is 110.

8. `test_partial_short_cover_preserves_average_open_price`
   - Seed SELL 4 at 120 and BUY 1 at 80.
   - Assert the remaining short average is 120.

9. `test_short_to_long_crossing_starts_new_pool_at_buy_price`
   - Seed SELL 3 at 120 and BUY 5 at 90.
   - Three shares close the short; two shares open a long at 90.
   - Assert `group_avg_cost == 90.0`.

10. `test_near_zero_position_has_null_average_cost`
    - Seed quantities whose mathematical remainder is within `1e-9`.
    - Assert `group_avg_cost is None`, locking the flat tolerance and
      preventing a huge average caused by division by floating-point dust.

11. `test_group_avg_cost_uses_stored_fx_in_cad_mode`
    - Seed USD BUY 10 at 100 with stored FX 1.40 and USD BUY 10 at 120 with
      stored FX 1.30.
    - Provide a different live FX rate to prove it does not replace valid
      historical rates on the cost side.
    - Assert the CAD average is
      `(10 * 100 * 1.40 + 10 * 120 * 1.30) / 20 == 148.0`.

12. `test_group_avg_cost_is_native_in_native_mode`
    - Use the same USD buys and request `?currency=NATIVE`.
    - Assert `group_avg_cost == 110.0` and `display_currency == "USD"`.

13. `test_partial_sell_preserves_cad_pool_average`
    - Seed a USD BUY with a stored FX rate, then a partial SELL with a
      different stored rate and price.
    - Assert the remaining average stays at the BUY's CAD acquisition cost;
      sale proceeds and the sale's FX rate do not reprice remaining shares.

14. `test_unquoted_group_still_has_average_cost`
    - Seed a CAD BUY and leave the fake quote absent.
    - Assert existing live `group_*` keys remain absent as currently required.
    - Assert `group_avg_cost == 100.0` is present because it needs no quote.

15. `test_unquoted_usd_group_uses_stored_fx_for_cad_average`
    - Seed a USD BUY with a valid stored FX rate and no quote.
    - Assert the row keeps the existing CAD `price_display` behavior and its
      `group_avg_cost` uses that stored rate.

16. `test_unquoted_usd_group_without_fx_degrades_to_native_average`
    - Seed a legacy USD BUY with `fx_rate=None` and no quote.
    - Assert the route does not invent CAD conversion.
    - Assert `display_currency == "USD"` and the native average is returned.

17. Extend `test_group_fields_are_per_ticker`
    - Give the two tickers different average prices.
    - Assert each ticker's rows contain only that ticker's average.

18. Extend the response-shape comments and the unquoted-group test so they
    distinguish fact-derived `group_avg_cost` from quote-derived group fields.

### B. Frontend Meta-Tests - `tests/test_ledger_average_price.py`

Follow the repository's existing JavaScript source/meta-test style. Add a
small function-block extractor local to the test file if needed; do not add a
production helper only to satisfy tests.

Add these tests:

1. `test_group_sort_keys_reads_backend_average_cost`
   - Assert `groupSortKeys` returns the first row's `group_avg_cost` as a
     nullable `avgCost` value.
   - This keeps one frontend reading point for group data.

2. `test_group_row_renders_average_cost_in_price_cell`
   - Inspect `buildGroupRow`.
   - Assert the Price cell uses the group average rather than hard-coding `—`.
   - Assert it formats through `formatNumber` and appends the group's existing
     display currency.

3. `test_group_row_uses_dash_when_average_cost_is_null`
   - Assert an explicit null/unavailable branch writes `—`.
   - Zero must not be treated as unavailable through a truthiness check; test
     for an explicit null condition.

4. `test_group_average_price_does_not_require_live_quote`
   - Assert Price rendering occurs independently of the `hasLive` branch.
   - This prevents a Yahoo failure from hiding a stored-facts average.

5. `test_group_average_price_does_not_replace_quick_sell_price`
   - Inspect `buildGroupRow` and assert quick sell still reads
     `txs[0].price_now` into `priceNow`.
   - Assert the sell form is not filled from `avgCost`.

6. Keep `tests/test_ledger_col_count.py` green to prove the parent and detail
   builders still have exactly 11 matching cell keys.

7. Keep privacy tests green to prove Price is not accidentally added to the
   masking set.

## Implementation Plan

Start only after the new tests fail for the intended missing behavior.

### 1. Calculate the Open Cost Pool in `app.py`

Modify the group-aggregate section of `list_transactions` after every row has
received `price_display` and `display_currency`.

For each ticker group:

1. Initialize `position_qty = 0.0` and `position_cost = 0.0`.
2. Replay `reversed(rows)` because `db.get_transactions()` returns rows
   newest-first and cost pools must be chronological.
3. For each row, read positive `qty`, `price_display`, and BUY/SELL type.
4. Convert type to a signed quantity: BUY positive, SELL negative.
5. If the pool is flat within `1e-9`, open a new pool with the transaction's
   signed quantity and `abs(signed_qty) * price_display` cost magnitude.
6. If the transaction has the same sign as the pool, add its quantity and
   cost to form a weighted average.
7. If it has the opposite sign, close up to the current absolute quantity at
   the current average:
   - Reduce pool cost in direct proportion to the quantity closed.
   - Do not use the closing transaction's price for the shares that close.
8. If the transaction exactly closes the pool within `1e-9`, set both pool
   quantity and cost to zero.
9. If the transaction crosses through flat, use the excess quantity to open
   the opposite-side pool at that transaction's `price_display`.
10. After replay, calculate `avg_cost = position_cost / abs(position_qty)` only
    when `abs(position_qty) > 1e-9`; otherwise use `None`.
11. Attach `group_avg_cost` to every row in the ticker group before any early
    `quote is None` continuation.
12. Keep the existing quote-derived aggregate calculations unchanged.

Use positive cost magnitude for both long and short pools. The quantity sign
identifies direction; the average itself remains a positive display price.

Do not call market data, do not store the result, and do not change
`group_cost_basis`. That field intentionally remains net cash flow for the
portfolio gain formula, while `group_avg_cost` is the open-position cost pool.
They answer different questions.

### 2. Render the Average in `static/js/ledger.js`

1. Update the parent-row comments to state that Price is the backend's open
   position average and that it survives quote failure.
2. Extend `groupSortKeys(txs)` with
   `avgCost: first.group_avg_cost ?? null`.
3. In `buildGroupRow`, read `avgCost` with `netQty` from `groupSortKeys(txs)`.
4. Build the Price cell before the live-only cells, as today.
5. If `avgCost === null`, set `priceCell.textContent = "—"`.
6. Otherwise, use the first row's existing display currency and render
   ```${formatNumber(avgCost)} ${currency}```.
7. Do not put this logic inside `if (hasLive)`. Average cost is historical and
   must render without `price_now`.
8. Keep `priceNow = txs[0].price_now` and every quick-sell eligibility and form
   assignment unchanged.
9. Keep the cells object and `ledgerColOrder` behavior unchanged.

### 3. Update Durable Comments

1. Update the `app.py` group aggregate comment to document
   `group_avg_cost` as a chronological open-position cost-pool average.
2. Explain briefly why `group_avg_cost` differs from `group_cost_basis /
   net_qty` after sales.
3. Update the `ledger.js` group comments to remove the obsolete statement
   that average cost is a future step.
4. Do not copy this entire plan into code comments. Document only the
   non-obvious distinction and quote-independent behavior.

## Focused Verification

After the intended red test run and implementation, run:

```bash
source .venv/bin/activate
python -m pytest tests/test_ledger_groups.py tests/test_ledger_average_price.py
python -m pytest tests/test_ledger_col_count.py tests/test_ledger_quick_sell.py tests/test_privacy_toggles.py
```

Then the lead agent must run the full suite:

```bash
source .venv/bin/activate
python -m pytest
```

No implementation is complete until the full suite passes.

## Browser GUI Approval Checklist

After pytest passes, stop and ask the user to inspect the browser before any
commit or push.

1. A ticker with one BUY shows that purchase price in the parent Price cell.
2. Multiple BUYs show the quantity-weighted average.
3. Expanding the group still shows each transaction's individual price.
4. A partial SELL leaves the remaining position's average unchanged.
5. A fully closed ticker shows `—` in the parent Price cell.
6. A short position shows its average opening sale price.
7. Default CAD mode shows the CAD average and `CAD` suffix.
8. “Show USD in USD” changes a USD ticker's parent average and suffix to its
   native USD values.
9. A ticker whose live quote fails still shows its parent average while live
   Value/Gain cells show `—`.
10. Quick Sell still fills today's exact native live price, not average cost.
11. Parent-row expansion, sorting, column order, privacy masking, editing,
    deletion, import, and polling still work.
12. Desktop and narrow mobile/card layouts remain aligned with 11 columns.

## Completion Gates

1. Plan in `feature.md` and roadmap item #1 marked `in progress`.
2. User approves this plan before implementation.
3. Write failing backend and frontend tests first.
4. Confirm focused tests fail for the intended missing behavior.
5. Implement the backend cost-pool replay.
6. Implement parent-row rendering.
7. Pass focused tests.
8. Pass full `python -m pytest`.
9. Obtain browser GUI approval.
10. Only then ask whether to commit and push.
11. Mark roadmap item #1 shipped only in the approved commit, with PR number
    and date, or date only for a direct-main commit.

## Definition Of Done

Each ledger ticker parent row shows the average acquisition price of its
current open long or short position in the selected ledger display currency.
Partial closes do not alter the average, crossings start a new opposite-side
pool at the crossing transaction's price, flat groups show `—`, and quote
failure does not hide the stored-facts average. All tests pass and the user
approves the browser behavior.
