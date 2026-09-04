# Feature: Sortable Ledger Group Rows

## What (user story)

Click a column header on the ledger to reorder the **parent (group) ticker
rows** by that column. Individual transaction (detail) rows stay static —
newest transaction on top, oldest at bottom per group (the backend's
existing order). Default group order on load = current backend order (most
recently transacted ticker first). Sorting is **frontend-only** — no
API/DB changes, no Python test work.

## Decisions (from planning + user answers)

- Sort ONLY the groups (parent ticker rows). Detail rows inside a group are
  never sorted by the user; they keep the backend's newest-first order.
- Frontend-only sort on the already-fetched `lastTransactions` — instant,
  no refetch, survives the 60s poll because the sort state is a JS var.
- Sortable columns (exactly): Ticker, Qty, Value, Total Gain, Total Gain %,
  Day Gain, Day Gain %. All other headers (Date, Type, Price, blank actions)
  are non-clickable — a group has no single date/type/price.
- First click on a header sorts ascending; second click flips to descending;
  clicking the active header again toggles direction.
- Default (no sort clicked) = backend order = most recently transacted
  ticker on top.
- Groups whose sort key is unavailable ("—", e.g. SELL-only Total Gain %,
  or unquoted live cells) always sort LAST regardless of direction.

## Subtasks (in order — check off as done)

- [x] **1. `feature.md` plan written + user approved** (this file).
- [x] **2. `templates/index.html`** — add `data-col` attribute
      (`ticker`, `qty`, `value`, `total_gain`, `total_gain_pct`,
      `day_gain`, `day_gain_pct`) to the 7 sortable `<th>`s in the thead
      (lines ~182–195). Also make them focusable (`tabindex="0"`,
      `role="button"`, `aria-sort` for accessibility). NO new columns → the
      11-column contract is untouched.
- [x] **3. `static/js/main.js`**:
      - Extract the group aggregate math from `buildGroupRow` into a shared
        pure helper `groupSortKeys(txs)` returning `{netQty, value,
        totalGain, totalGainPct, dayGain, dayGainPct}`. `buildGroupRow`
        calls it too — one source of truth for the numbers that matter in
        both rendering and sorting.
      - Sort state: `ledgerSort` (null = default backend order). Ticker
        first-click ascends A→Z; numeric columns first-click descend
        (biggest first); same-column clicks flip direction.
      - In `renderLedger`, materialize groups into an array and sort by the
        active key (stable). Null/undefined/NaN (unavailable) keys sort
        last.
      - Delegated click + keydown listeners on the `<thead>` (finding the th
        by `data-col`) → update state and re-render from `lastTransactions`.
      - `renderSortIndicators()`: ▲/▼ on the active header, clear the
        others, set/clear `aria-sort` and the `.active` class.
- [x] **4. `static/style.css`** — sortable `<th>` hover/focus affordance
      (cursor:pointer, subtle accent), `.active` accent, `.sort-indicator`
      (▲/▼) styling.
- [x] **5. Verify** — `python -m pytest` fully green (146 passed, backend
      unchanged). Manual browser checklist pending the GUI gate.
- [x] **6. Docs** — added a permanent Design Rule to `project-brief.md`
      ("ledger sort is frontend-only; controls group rows; detail rows
      newest-first").
- [x] **7. GUI gate** — user checked in the browser (Sep 2026, alongside
      the NaN-chart bugfix verification).
- [x] **8. Commit gate** — user approved; committed and pushed.

## Group sort keys (how each column orders the parent rows)

- Ticker → `ticker.toLowerCase()` (A→Z / Z→A).
- Qty → net position `Σ BUY.qty − Σ SELL.qty`.
- Value → `Σ BUY.value`.
- Total Gain → `Σ BUY.total_gain`.
- Total Gain % → `Σ total_gain ÷ Σ(price_display×qty)` over BUYs; null
  (SELL-only) → sort last.
- Day Gain → `Σ BUY.day_gain`.
- Day Gain % → ticker's daily move `txs[0].day_gain_pct` (same for every
  row in the group).

## Test plan (manual browser checklist)

- Click each of the 7 sortable headers → groups reorder correctly (asc on
  first click, desc on second, back to asc on third).
- Ticker sorts alphabetically both directions.
- Qty/value/total-gain/day-gain sorts respect sign (losses sort below gains
  on descending correctly).
- Groups with "—" (SELL-only Total Gain %, or unquoted) always sort last in
  BOTH directions.
- Expand/collapse (and the ticker link) still work after sorting.
- Sort state survives a 60s poll (hold state in `ledgerSort`, not the DOM).
- Non-sortable headers (Date, Type, Price, blank) do nothing on click.
- Active header shows ▲/▼; others don't.
- No new columns → ledger visual width unchanged.

## Contracts that must NOT break (AGENTS.md)

- Ledger table column count stays 11 — no visible-column changes.
- Backend sends raw floats; formatting stays frontend-only.
- Grouping + expand/collapse (`expandedTickers`) behavior fully preserved.
- Detail rows keep newest-first order.
- No changes to `db.py`, `app.py`, or the API — so no Python tests, and the
  existing suite must stay green unchanged.
