# Feature: Stock-page watchlist button reflects + toggles watch state

## Problem
The stock detail page's "Add to Watchlist" button never shows that the symbol
is ALREADY watched (only learns it from a click's 201/409 response), and the
done-state is `disabled`, so a watched symbol can't be unwatched from this page.

## Goal
- Button paints its true state AT LOAD (check mark if already watched).
- Clicking while watched asks "Remove from watchlist?" (showConfirm) and
  DELETEs on confirm; 404 = removed elsewhere → sync to unwatched.

## Subtasks
1. `db.py` — `is_watched(symbol)` helper (bool SELECT next to add/remove).
2. `app.py` — `stock_page` passes `watched=db.is_watched(...)` to the template
   (DB read only; rendering still never touches the network).
3. `templates/stock.html` — button ships `data-watched="true|false"`.
4. `static/js/stock.js` — `paintWatchBtn(watched)` paints both states from
   icon("plus")/icon("check"); boot reads data-watched (no fetch, no flicker);
   click branches watched → confirm+DELETE / not-watched → POST; 404 on
   DELETE treated as "already removed" → paint unwatched.
5. `static/style.css` — new `.btn-action.watched` (green palette, clickable —
   the old disabled done-state is gone); hover keeps green.

## Contracts that are easy to break (touched here)
- Layering: db knows nothing about Flask/yfinance; routes decide; JS renders.
- stock_page's shell rule: template ships state, JS fills data — no network
  at render time.
- PUT/POST vocabularies untouched; DELETE /api/watchlist/<symbol> already
  exists (204 / 404) — no new endpoints.
- `.btn-action:disabled` is the shared done-state rule; we ADD a sibling
  class, never repurpose the disabled rule.
- showConfirm contract: resolves true/false; danger=true for destructive.

## Test plan (written first — must fail before implementation)
- tests/test_db.py:
  - is_watched False on empty DB; True after add; False after remove.
  - is_watched is case-sensitive exact match (routes normalize before calling).
- tests/test_stock.py:
  - GET /stock/aapl renders data-watched="false" when unwatched.
  - After POST /api/watchlist {"symbol": "aapl"}, GET /stock/aapl renders
    data-watched="true" (normalization: stored AAPL matches URL aapl).

JS confirm/unwatch flow has no JS test infra — verified at the GUI gate.

## Status
- [x] Plan approved by user (2026-09-05)
- [x] Tests written + failing (4 new: 2 db, 2 route)
- [x] Implemented, full `python -m pytest` green (213 passed)
- [x] GUI gate (user checked the browser, 2026-09-05)
- [x] Commit gate (review nits addressed, squash-merging into main)
