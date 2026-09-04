# Feature: Delete a whole ticker (all its transactions) from the ledger

## What & why

The ledger groups transactions by ticker (one collapsible "group" row per
ticker). Today the only delete is per-transaction. This feature adds the
bulk verb: remove EVERY transaction of one ticker in one action, from the
group row itself — gated behind an explicit type-the-ticker confirmation,
because it destroys many immutable facts at once with no undo.

**Agreed decisions (user):**
- Confirmation = `prompt()` requiring the user to TYPE the exact ticker.
  Cancel or mismatch aborts. (Stronger than the single-row `confirm()`.)
- Scope: ledger only. The watchlist is a separate list and is NOT touched.
- Button lives in the group row's (currently blank) actions cell.
  NO template change, NO column-count change (the 11-column contract in
  AGENTS.md stays intact — the button lives INSIDE the existing cell).

## Files

| File | Role |
|---|---|
| `db.py` | New `delete_transactions_for_ticker(ticker)` — `DELETE FROM transactions WHERE ticker = ?` (parameterized like everything else), returns `cursor.rowcount` (0 = nothing matched). Exact match: `AAPL` never hits `AAPL.TO`. |
| `app.py` | New route `DELETE /api/transactions/ticker/<symbol>` — trim+uppercase (one canonical form), 404 when 0 rows, 204 otherwise; info log as audit trail (bulk destructive op, mirrors import_commit's receipt-in-the-log idea). No collision with `DELETE /api/transactions/<int:tx_id>`: "ticker" isn't an int, so Flask's int converter never matches it. |
| `static/js/main.js` | (1) `buildGroupRow`: append a `×` delete button (`ticker-delete-btn` class + `data-ticker` hook + tooltip) to the group actions cell. (2) Extend the existing delegated actions listener with a `.ticker-delete-btn` branch BEFORE the generic `.tx-action-btn.delete` branch — the generic one would otherwise swallow the click and no-op on its missing `data-id`. (3) The prompt: `Type AAPL to confirm deleting ALL 5 AAPL transactions.` — abort on cancel/mismatch. (4) On success: `expandedTickers.delete(ticker)`, exit edit mode if the form was editing one of that ticker's rows, refresh ledger + summary (existing pattern). (5) The group expand/collapse listener must stand down when a click starts on ANY action button (same guard it already uses for the ticker `<a>`), so deleting doesn't also toggle the group. |
| `tests/test_db.py` | Unit tests for the new db function. |
| `tests/test_routes.py` | Route tests via the test client. |

## Test plan (pytest — written FIRST, failing until implemented)

`tests/test_db.py`:

1. `test_delete_transactions_for_ticker_removes_only_that_ticker` —
   seed AAPL×2 + MSFT×1 → delete AAPL returns 2; get_transactions()
   holds only the MSFT row.
2. `test_delete_transactions_for_ticker_returns_zero_for_unknown` —
   returns 0, ledger unchanged.
3. `test_delete_transactions_for_ticker_is_exact_match` — `AAPL` delete
   leaves `AAPL.TO` rows alone (SQL `=` is exact; tickers are full
   identities, not prefixes).

`tests/test_routes.py` (new "DELETE ticker (bulk)" section after the
existing DELETE section):

4. `test_delete_ticker_transactions_bulk_204_keeps_other_tickers` —
   seed AAPL×2 + MSFT×1 → `DELETE /api/transactions/ticker/AAPL` → 204;
   GET /api/transactions shows only MSFT.
5. `test_delete_ticker_transactions_normalizes_case` — path
   `.../ticker/aapl` deletes the `AAPL` rows (same canonical-form rule as
   every symbol-bearing route).
6. `test_delete_ticker_transactions_unknown_ticker_404` — 404 + error
   JSON, for an unknown ticker AND for an empty ledger (0 rows = nothing
   to delete, not a silent success).
7. `test_delete_ticker_transactions_percent_encoded_symbol` — seed
   `^GSPC`, DELETE `.../ticker/%5EGSPC` → 204 (same percent-encoding rule
   as the watchlist path; Flask decodes it back).
8. `test_delete_ticker_leaves_single_tx_delete_working` — after a bulk
   delete, `DELETE /api/transactions/<id>` of a surviving row still
   works (guards the two DELETE routes' coexistence).
9. `test_delete_ticker_does_not_touch_watchlist` — AAPL on the watchlist
   + AAPL in the ledger → bulk delete → watchlist still lists AAPL.

## Implementation steps

1. Tests first: add both blocks, run them, CONFIRM they fail.
2. `db.py` → `app.py` → `static/js/main.js` (small, interdependent — no
   subagents; a beginner-readable teaching-comment style throughout).
3. Full `python -m pytest` green (new + all existing).

## Verification & gates

1. Full suite green.
2. GUI gate: user opens the dashboard, expands a group, clicks the group
   `×`, types the ticker (and mistypes once to see the abort), confirms
   the group vanishes and the summary/chart follow.
3. Commit gate: commit/push only after explicit user approval.
