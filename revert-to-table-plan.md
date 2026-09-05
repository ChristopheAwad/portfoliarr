# Revert plan: holding cards → swipe table (contingency)

**Status: NOT EXECUTED.** The shipped design keeps phone holding cards
(user approved them at the GUI gate). This file documents the escape
hatch: how to return the ledger's phone presentation to the round-1
horizontal-scroll table. Do not run it unless the user asks.

**Why it's cheap:** the cards are pure CSS *overrides* inside the
≤600px media query. The swipe table from round 1 still exists
underneath (`.table-wrap { overflow-x: auto }` + `.ledger-table
{ min-width: 760px }` in the base rules) — deleting the overrides
restores swipe behavior at ≤600px automatically. No template or
backend changes, no test changes.

## Step 1 — style.css: delete the card transform

Inside `@media (max-width: 600px)` (bottom of the file), delete the
ENTIRE "Ledger holding cards" subsection — from the comment block
starting `/* ── Ledger holding cards ──` through the `.ledger-table
td.empty-state` rule (the last rule before the query's closing brace).

Concretely, that removes: the `.table-wrap`/`.ledger-table` un-swipe
overrides, the `thead { display: none }`, the table/tr/td block rules,
the `td::before` caption rule, all `tr.ledger-group` card styling
(flex-wrap, title row, type/price hiding, actions), all `tr.tx-detail`
overrides, and the empty-state quiet-line rule.

**Keep** in the same query (these are separate polish, not card code):
navbar/logo/container/price/chart compactions, chip tightening, card
padding, full-width tx-form rows, Log button.

**Verify the delete boundary:** after removal, ≤600px must fall back to
the base `.table-wrap` swipe rules — grep the file to confirm
`overflow-x: auto` (base) is no longer shadowed by any `overflow:
visible` override.

## Step 2 — main.js: remove the cell stamping (recommended)

The stamps are invisible in table mode, so leaving them costs nothing —
but they'd be dead code that confuses a future reader. Clean removal:

1. Delete the `ledgerColLabels` map + its loop (comment block starting
   "Header TEXT per data-col", near `ledgerColOrder`).
2. Delete the `stampCell(col, cells)` helper (comment block "Stamp ONE
   ledger cell…", just above `buildTxRow`).
3. In BOTH `buildTxRow` and `buildGroupRow`, revert the keyed-append to
   the original shape:
   `row.append(...ledgerColOrder.map((col) => cells[col] ?? document.createElement("td")));`

The two builders MUST stay in lockstep — both or neither.

## Step 3 — verification

1. `python -m pytest` — full suite must be green (nothing in it keys on
   the card CSS; the locks protect the TABLE contract, which the revert
   restores).
2. GUI: 375px → ledger swipes sideways INSIDE the card again, edit/
   delete buttons visible without hover (the `hover: none` fix stays),
   full-width log form stays. Desktop (~1200px) unchanged: plain table.
3. Stock page untouched either way (it has no ledger).

## What survives the revert either way

Round-1 + polish: swipe wrapper, `@media (hover: none)` always-visible
touch buttons, wrapped timeframe buttons, ≤600px navbar/chips/form
compactions. Nothing in `tests/` references the card CSS or the JS
stamps — 199 tests are unaffected by this plan in either direction.

Estimated effort: ~15 minutes. Risk: low (pure deletions; the fallback
behavior already ships in the base stylesheet).