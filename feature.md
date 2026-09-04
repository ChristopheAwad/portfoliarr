# Feature: Reorderable ledger columns (drag + persist)

## What & why

The ledger table's 11 columns are fixed in place. This feature lets the user
drag a column header to a new position — e.g. pull `Ticker` next to `Date` —
and have that order stick: across the 60-second poll rebuilds, across page
reloads (localStorage), until they drag it back.

**Design decisions (already agreed):**

- **Whole header draggable** — no dedicated ⠿ handle. HTML5 drag only starts
  after the mouse *moves* while held, so a plain click (down + up) still
  triggers the existing column sort. Drag and sort coexist for free.
- **Drag + persist** — order saved to `localStorage`, restored on load.
- **Actions column pinned last** — edit/delete stay at the right edge; it
  can't be dragged and drops onto it are rejected.
- **Pure frontend** — no route, DB, or market_data changes. `colSpan = 11`
  in `setLedgerMessage` is unaffected (column *count* never changes, only
  order).

## The key refactor: one source of truth for column order

Today the column order is hardcoded in three places that must agree:

1. the static `<th>` row (`templates/index.html` ~lines 197-226),
2. `buildTxRow`'s `row.append(dateCell, typeCell, ...)` (`main.js` ~552),
3. `buildGroupRow`'s `row.append(...)` (`main.js` ~730).

The refactor collapses 2 and 3 into 1:

- Every `<th>` gets a `data-col` attribute (the 7 sortable ones already
  have it; we add `date`, `type`, `price`, `actions`). The HTML `<th>` row
  becomes the SINGLE declaration of the columns.
- On boot, `main.js` reads the live `<th>`s and derives the current order
  from their `data-col`s.
- Both row builders assemble their cells into a `{key: cell}` map, then
  append by iterating that order. Reordering never touches the builders.

Why derive from the DOM instead of a JS array constant: pytest can only see
server-rendered HTML. Keeping the header static means the tests below can
lock the default order and the sortable-column contract. It also means a
future column addition edits ONE place (the `<th>` row), dissolving the
"column count lives in four places" contract in AGENTS.md (only
`setLedgerMessage`'s colSpan stays a hand-maintained 11 — count, not order).

## Test plan (pytest — server-rendered HTML only)

New tests in `tests/test_routes.py`, next to the dashboard chip tests
(same style: fetch `/` with the `client` fixture, regex the HTML — no
fixtures beyond `client`, no fakes, no network).

> Honest limit: pytest cannot execute JavaScript, so drag behavior,
> persistence, and drop rejection are proven at the **GUI gate**, not here.
> These tests lock what the server renders — the contract the JS builds on.

1. **`test_ledger_header_renders_expected_columns_in_default_order`**
   The ledger table's `<thead>` contains exactly 11 `<th>`s whose
   `data-col` values, in order, are:
   `date, type, ticker, qty, price, value, total_gain, total_gain_pct,
   day_gain, day_gain_pct, actions`.
   Guards: the count-11 contract (colSpan), the default order the JS
   derives at boot, uniqueness of every `data-col` key (builders and the
   reorder logic key cells by it — a duplicate would silently misplace
   cells). **Fails first**: 4 of the 11 `<th>`s don't carry `data-col` yet.

2. **`test_ledger_sortable_headers_match_sort_vocabulary`**
   Exactly 7 `<th>`s carry `class="sortable"`, and their `data-col` set is
   `{ticker, qty, value, total_gain, total_gain_pct, day_gain, day_gain_pct}`;
   `date`, `type`, `price`, `actions` are NOT sortable.
   Guards: the HTML↔JS contract — `SORT_COLS` in `main.js` maps exactly
   these 7 keys, and `renderSortIndicators` finds sortable headers by
   class. Passes already (regression guard for the template edits).

## Implementation steps

**1. `templates/index.html`** — add `data-col` to the 4 remaining `<th>`s
(`date`, `type`, `price`, `actions`); update the explanatory comment above
the row to describe the new drag behavior.

**2. `static/js/main.js`** — all the logic:

- **Boot (module scope):** read `document.querySelectorAll("thead th")` →
  default order. Read `localStorage("ledgerColOrder")`; validate it's a
  permutation of the live `data-col` set (same keys, count 11) with
  `actions` last — anything invalid is ignored (protects against corruption
  AND future column additions). Apply the saved order by re-appending the
  actual `<th>` elements to their row (moving DOM nodes preserves their
  listeners and `data-col`, so sort clicks and indicators keep working).
- **`ledgerColOrder`** (module-level, like `ledgerSort`): the current key
  order. Poll rebuilds re-render the tbody every 60s, so the order must
  live outside the DOM — the same pattern as `expandedTickers`.
- **Builders:** `buildTxRow` and `buildGroupRow` build a
  `{dataColKey: cell}` map, then `append` in `ledgerColOrder` order.
  Everything inside the cells (caret, badges, pos/neg classes, buttons)
  travels with its cell automatically.
- **Drag wiring** on the `<th>`s (set `draggable = true` on all but
  `actions`): `dragstart` remembers the source key; `dragover` shows a
  drop-indicator class (suppressed over `actions` — no
  `preventDefault` there means no drop fires); `drop` computes the new
  order, updates `ledgerColOrder`, re-orders the `<th>`s, saves to
  localStorage, and re-renders the ledger immediately (don't wait up to
  60s for the next poll).

**3. `static/style.css`** — drop-indicator and dragging styles (e.g. a
`.drop-target` edge highlight and dimmed `.dragging` header), next to the
existing ledger table styles.

## Data flow

```
drag th ──drop──▶ new key order ──▶ ledgerColOrder (memory)
                                      ├─▶ localStorage (survives reload)
                                      ├─▶ reorder <th> elements in place
                                      └─▶ renderLedger() → builders append
                                            cells in ledgerColOrder order
boot:  localStorage ──validate──▶ ledgerColOrder ──▶ reorder <th>s
```

## Verification

1. `python -m pytest` — full suite green (the two new tests + all existing).
2. **GUI gate:** drag a column → order changes instantly; reload → order
   persists; click headers → sort still works; expand/collapse and
   edit/delete still work; drops on Actions do nothing; empty-ledger
   message still spans the full table.
3. Commit gate only after GUI approval.
