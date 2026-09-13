# Feature: Hide closed positions (Preferences-controlled)

## What
Fully-sold tickers (net qty 0) disappear from the transaction ledger's
group list by default, so a traded-out position stops crowding the
"what do I hold" view. A **"Show closed positions"** switch on
`/preferences` (in the existing **Ledger** card) brings them back.

## Decisions locked in the brainstorm
- **Never delete fully-sold transactions.** The Closed sales math is an
  average-cost replay of the WHOLE ledger — the BUY rows are the cost
  basis. Hiding is presentation; deleting would corrupt realized-gain
  history. (This feature is presentation-only: zero backend changes.)
- **Exact-zero hides; shorts stay.** netQty === 0 is "closed"; a
  negative netQty is an active short and stays visible.
- **The qty source is fact arithmetic** — the same `groupSortKeys`
  netQty the group row's Qty cell shows (Σ buys − sells over stored
  facts, no price involved). Works for unquoted/delisted tickers, whose
  live group fields are absent — precisely the rows that would crowd
  forever. No new backend field, no contract disturbance.
- **Per-render read, no event wiring.** `renderLedger` reads the
  localStorage key on EVERY render (it re-renders each 60s poll
  anyway), so flipping the switch in Preferences applies on /ledger
  within one poll cycle. Same eventual-freshness model as the privacy
  eyes' localStorage state.
- **Honest empty state.** If transactions exist but every group is
  closed and hidden, the table says "No open positions — enable 'Show
  closed positions' in Preferences." — never the misleading "No
  transactions yet".

## How it works
- `templates/preferences.html`: one new `pref-row` in the Ledger card —
  a `.fx-toggle` switch (the "Show USD in USD" styling, reused)
  wrapping `<input id="pref-show-closed">`, with a `pref-label` for the
  accessible name.
- `static/js/preferences.js`: a block mirroring the sort-pref one —
  sync the checkbox from `localStorage.getItem("showClosedPositions")`
  (`"true"` = on, anything else = off, the privacy-eye convention) and
  `setItem` on change.
- `static/js/ledger.js`: inside `renderLedger`, read the key, filter
  the sorted group list (`showClosed || netQty !== 0`), and render the
  honest empty state when nothing remains. Sorting, `expandedTickers`,
  the privacy eye, Closed sales, and edit/delete (reachable once the
  switch is on) are untouched.

## Verification
- **Implemented, tests green:** full suite **372 passed** (5 locks in
  `tests/test_show_closed_pref.py`, 15 in `tests/test_realized.py`
  including 2 review-driven regressions).
- **Review round 1 (pr-reviewer) — request-changes, all fixed:**
  1. BUY-covers-short gated the NATIVE pool shrink on `rated` — an
     unrated short's stale basis leaked into later rows' `avg_cost`
     (-160.0 instead of 90.0). Native now shrinks unconditionally;
     CAD stays gated. Locked by
     `test_covering_buy_shrinks_unrated_short_native_pool`.
  2. Exact-zero flat-wipe broke on fractional qtys (0.1+0.2−0.3 =
     5.55e-17): unrated ancestry stuck forever and the hide filter
     resurrected phantom "0.0000" rows. Wipe + filter now use a 1e-9
     tolerance. Locked by `test_fractional_positions_still_go_flat`
     + the updated string pin in `test_show_closed_pref.py`.
  3. "Zero network calls" wording corrected everywhere (app.py ×2,
     AGENTS.md, project-brief.md): the money math makes no quote/FX
     calls; the one network touch is `get_name` (process-lifetime
     cache, one .info per sold ticker after restart, retried per poll
     while Yahoo can't answer).
- Implementation notes: the keep-condition is the 1e-9 tolerance
  feeding a ternary filter (`showClosed ? all : filtered`) — the test
  pins that exact keep-condition, because a `> 0` variant would read
  the same to the eye while silently hiding shorts, and an exact
  `!== 0` would resurrect float-residue tickers.
- **GUI check pending:** user flips the switch on /preferences and
  confirms /ledger hides/shows sold-out tickers within a poll cycle,
  shorts stay, and the all-closed empty message points at Preferences.

## Rollback
Revert the commit. Touches `templates/preferences.html`,
`static/js/preferences.js`, `static/js/ledger.js`, the new test file,
`feature.md`. No backend, no schema, no data changes.

## Out of scope
- Dashboard holdings view (doesn't exist post-split; separate decision).
- Closed sales table (already the "what did I make" history; untouched).
- Summary strip / chart math (0-holding tickers already contribute 0;
  their realized gains stay in Total Return via cost basis — correct).
- Per-group "archive" sections or sort-to-bottom variants (rejected in
  brainstorm — the toggle achieves the same with less machinery).
