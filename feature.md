# Feature: Ledger group rows react to SELLs (backend group aggregates)

## What & why

The ledger groups transactions by ticker. The group row's Value / Total
Gain / Day Gain are computed in `groupSortKeys` (`static/js/main.js`) by
summing **BUY rows only** — a SELL changed nothing but the Qty column.
Root cause of the user-visible bug: log a SELL and the ticker row's total
value stays frozen (BUY 10 @ 100 + SELL 4 @ 110 @ price 105 shows value
1050 — every share ever bought — while you hold 6 worth 630). It also
silently disagrees with the portfolio summary strip, which nets sells
correctly (`portfolio_summary`), and with the ledger sorter, which reads
the same `groupSortKeys`.

**Agreed decisions (user):**
- Option B: the BACKEND computes per-ticker group aggregates (same math
  and semantics as `/api/portfolio/summary`); `main.js` renders them.
  Keeps the architecture rule "backend = numbers, frontend = formatting"
  and makes the math pytest-lockable.
- Oversold positions (net qty < 0, incl. SELL-only groups) display
  honestly negative — consistent with the summary route. No validation
  change.

## Files

| File | Role |
|---|---|
| `app.py` | `list_transactions`: after per-row decoration, per UNIQUE ticker compute group aggregates and attach them to EVERY row of that ticker (response stays a JSON array; additive fields only). Fields: `group_value`, `group_cost_basis`, `group_total_gain`, `group_total_gain_pct` (null when cost ≤ 0), `group_day_gain`, `group_day_gain_pct`. Absent when the ticker's quote failed (frontend "—" path unchanged). Value side at the LIVE rate (CAD mode), cost side at each row's `price_display` (stored-rate CAD / native) — the summary's two-rate contract. Realized + unrealized blend: `total = value − cost`. |
| `static/js/main.js` | `groupSortKeys` reads `txs[0].group_*` instead of summing BUY rows; `netQty` stays fact-computed (Qty cell works even unquoted). `buildGroupRow` / `sortGroupRows` follow automatically (they consume the same keys — sort-matches-display rule). "BUY rows only" comments rewritten to the backend-aggregate story. |
| `tests/test_ledger_groups.py` | NEW — pytest locks the math (below). |
| `AGENTS.md` | One contract line: group aggregates mirror summary math; fields live on every row of a ticker. |

## Test plan (pytest — written FIRST, failing until implemented)

`tests/test_ledger_groups.py` (fixtures `client`, `fake_market`,
`seed_transaction` mirroring test_portfolio_summary.py's helper):

1. `test_buy_only_group_aggregates_match_row_math` — BUY 10 @ 100, quote
   105/prev 100 → value 1050, cost 1000, gain 50, pct 5%, day_gain 50,
   day_pct 5. Baseline: aggregates == the old BUY-only sums.
2. `test_partial_sell_nets_value_and_blends_realized_gain` — BUY 10 @
   100 + SELL 4 @ 110, quote 105 → value 630, cost 560, gain 70
   (40 realized + 30 unrealized), pct 12.5%, day_gain 30.
3. `test_fully_sold_group_shows_realized_gain_null_pct` — BUY 10 @ 100 +
   SELL 10 @ 110, quote 105 → value 0, cost −100, gain +100, pct null
   (cost ≤ 0), day_gain 0.
4. `test_sell_only_group_is_negative` — SELL 4 @ 110, quote 105 →
   value −420, cost −440, gain +20, pct null.
5. `test_cad_conversion_two_rate_contract` — USD BUY 10 @ 100 (stored fx
   1.40), live fx 1.25, quote 105 → value 1312.5 (live rate), cost 1400
   (stored rate), gain −87.5 (currency movement included); with a SELL:
   cost nets at each row's OWN stored rate.
6. `test_native_mode_group_fields_are_native` — same seed, `?currency=
   NATIVE` → value 1050, cost 1000, gain 50 (no conversion).
7. `test_unquoted_ticker_has_no_group_fields` — quote fails → rows carry
   NO `group_*` keys (facts only, as today).
8. `test_group_fields_are_per_ticker` — two tickers seeded, each row's
   aggregates describe ITS ticker only.
9. `test_group_day_pct_is_ticker_move` — day_gain_pct equals
   quote.change_pct on every row regardless of type mix.

## Implementation steps

1. Tests first: write the file, run it, CONFIRM it fails
   (KeyError/assert on missing `group_*` fields).
2. `app.py` — group-aggregate pass in `list_transactions`.
3. `static/js/main.js` — groupSortKeys/buildGroupRow read the fields.
4. Full `python -m pytest` green (new + all existing).
5. AGENTS.md contract line.

## Verification & gates

1. Full suite green.
2. GUI gate: user logs a SELL against an existing BUY, confirms the
   group row's Qty AND Value (plus gains) move, and agrees with the
   summary strip; SELL-only/fully-sold groups show the documented
   shapes ("—" pct, negative value).
3. Commit gate: commit/push only after explicit user approval.
