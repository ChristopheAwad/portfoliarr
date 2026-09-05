# Feature: Responsive design for phones & tablets — v2

## Goal

Make the dashboard feel phone-app-like on a real phone (~375px): the
desktop-y 11-column ledger becomes stacked holding cards, and the page's
small-screen details are tightened. The stock detail page is already
fine per the user — untouched except the shared polish.

Round 1 (shipped) put a swipe-scroll wrapper on the ledger + touch fixes;
the user's real-device test showed it reflows but "still reads desktop".
v2 replaces the phone presentation, not the data path.

## Round-1 changes already in place (kept)

- `<div class="table-wrap">` around the ledger table + `min-width: 760px`
  (tablets/landscape phones 601–920px still use this swipe table).
- `@media (hover: none)`: edit/delete/remove buttons always visible on
  touch.
- Timeframe buttons wrap; ≤600px navbar/price/chart compactions.

## v2 changes

### 1. Ledger → holding cards on phones — main.js + style.css

**main.js (only JS change, ~15 lines, zero behavior change on desktop):**
- At boot, build `ledgerColLabels` (data-col → header text) from the
  thead — the SAME text the desktop table shows. Strip ▲/▼ defensively.
- In `buildTxRow` and `buildGroupRow`, the keyed-append stamps every cell:
  `cell.dataset.col = col` + `cell.dataset.label = ledgerColLabels[col]`.
  Invisible on desktop until CSS uses them; cell ORDER still comes from
  `ledgerColOrder` (drag-reorder safe — rows are rebuilt after a drop, so
  stamps stay truthful).
- `setLedgerMessage` untouched: its colSpan=11 cell becomes a full-width
  block in card mode (colSpan ignored in block display — harmless).

**style.css, entirely inside `@media (max-width: 600px)`:**
- thead hidden; `.ledger-table`, tbody/tr/td → display:block (classic
  responsive-table transform — SAME DOM, no second render path).
- Reset `min-width: 760px` → auto and `.table-wrap` overflow → visible
  (card mode doesn't swipe).
- Group rows (`.ledger-group`) = tinted cards: ticker link prominent,
  Value/Total Gain/Day Gain (+ pcts) as label:value lines, the caret +
  "N txns" (the date cell) as the meta line, delete-all button visible.
- Detail rows (`.ledger-row.tx-detail`) = labeled fact lines
  ("Date: …", "Price: … CAD", badge, etc.) under their card.
- Hide the meaningless cells on GROUP rows only: type (blank), price ("—").
- Actions cell: buttons inline; with the hover:none fix they're always
  visible.
- Pos/neg classes keep winning on gain lines (block display doesn't touch
  classes).

### 2. Phone polish (≤600px)

- Tighter chips; slimmer card padding; log form: inputs full-width rows,
  Log button full-width.
- Watchlist/summary unchanged beyond existing compaction.

### 3. Desktop invariant + known limits

- EVERYTHING v2 lives inside the ≤600px query — 601px+ renders exactly
  the round-1 desktop/tablet look.
- Phones: no column sorting (thead hidden) and no drag-reorder (desktop-
  only already); groups render in backend newest-first order.

## Test plan

Nothing server-rendered changes — no new pytest is meaningful (the stamps
are runtime JS; CSS isn't server-rendered). The gates:
1. Full suite stays green — the existing locks PROTECT this feature: the
   thead 11-column/data-col tests (test_routes.py) are the contract the
   CSS keys on; the wrapper test keeps the table findable.
2. GUI gate: user checks 375px (cards, expand, edit/delete, log form)
   AND desktop (~1200px) for zero visual drift.