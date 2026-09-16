# Feature: Time-Weighted Return (TWR) — "Performance" chart view

## Status
PLANNED — implementation PAUSED at the user's request. The plan below is
approved in direction (user picked the secondary-chart design); do NOT
write code until the user says go. Next step when resumed: write
`tests/test_twrr.py` + the shape updates in section A (they must FAIL),
then implement, then FULL `python -m pytest`, then GUI gate, then commit
gate. Roadmap entry: #13 (`Status: in progress`).

## The idea
The dashboard's value chart is MONEY-WEIGHTED: `total_gain / cost_basis`
counts every injected dollar in the denominator, so a deposit after a
good run drags the measured return down (buy $1k, double to $2k, inject
$2k → money-weighted says +33% while the picks actually did +100%).
That number stays (it honestly answers "all money in vs worth now").

Add a SECOND chart view the user can flip to: the TIME-WEIGHTED return,
drawn as a growth-of-$100 index — the fund-industry standard. Each bar
multiplies by that bar's FLOW-ADJUSTED return, so deposits stop causing
vertical jumps: the line only moves with market performance. Two views,
two honest stories: "what am I worth" (Value) vs "how did the picks do"
(Performance).

### User decisions (locked)
1. **Secondary chart, not a pill** — a toggle on the chart card flips
   between Value (current) and Performance (TWR index) views. Shared
   1D–MAX timeframe buttons; toggle persisted in localStorage (same
   pattern as the allocation donut's last-view).
2. **Summary strip untouched** — the money-weighted "Total" stays.
3. **Flows priced at the flat live rate** — the same rate the value
   series already uses, so a USD buy removes exactly what the series
   added (no phantom FX gain on buy day). The frozen "flat rate" chart
   decision (project-brief.md) is untouched.

## The math (conventions — implement EXACTLY this)
Per-bar chaining (the standard "daily valuation" method), flow-at-close:

    r_i    = (V_i − F_i − V_{i−1}) / V_{i−1}     for bars i ≥ 1
    index  = 100; then index_i = index_{i−1} × (1 + r_i)
    twrr_pct = (Π(1 + r_i) − 1) × 100 over the defined span

- **V** = the existing `values` series (CAD, flat live FX for USD).
- **F_i** = net CAD CONTRIBUTION absorbed at label i = Σ over the txs
  newly applied at that label of `sign × price × qty × rate`, where
  sign is +1 BUY / −1 SELL, and rate mirrors the value side:
  CAD → 1.0; USD → `live_rate`; USD with no live rate / other currency /
  dead ticker → the tx's flow is **0** (see Mirror rule).
- **F_0 is ignored** — txs absorbed at the first bar are part of the
  base (V_0 already includes them; the series starts at the first tx
  date, so every first-ever buy lands at bar 0).
- **Flow timing = qty timing.** Flows are recorded INSIDE the existing
  transaction-absorption walk (app.py:437-465) — the daily `while
  tx_index` loop AND the intraday `today_applied` first-bar block — so
  a Saturday buy lands on Monday's bar for both its shares and its
  flow. Guaranteed same-label, by construction.
- **THE MIRROR RULE (critical):** a tx's flow enters TWR only if that
  tx's VALUE enters the series — i.e. its ticker has a usable history
  (`histories[symbol]` non-empty) AND its currency is supported (CAD,
  or USD with a live rate). A dead ticker contributes 0 to `values`
  (test_chart_speed.py:498 locks this); a phantom flow for it would
  fake a loss. Flow removal is the exact mirror of the value walk.
- **Divergence from the cost line (deliberate, document in code):** the
  cost-basis dataset uses each tx's STORED fx_rate (frozen facts), but
  flows use the flat LIVE rate — because a flow must be measured in the
  SAME units as the series it's removed from, or removal leaves a
  phantom FX gain/loss on the tx's bar.
- **Truncation (honest degradation):** chain while `V_{i−1} > 0`; stop
  before the first bar whose base is ≤ 0 (net-short slice via the
  oversell fold, or a fully-withdrawn portfolio, or nothing priced).
  `index_values` is then SHORTER than `labels` (frontend slices); if no
  bar pair is computable (fewer than 2 bars, or V_0 ≤ 0 — e.g. the only
  ticker's history fetch failed → all-zero series), `index_values` is
  **null** and `twrr_pct` is null. Never a fake number.
- **1D degenerates for free:** intraday applies every tx at today's
  first bar → all flows land at bar 0 → ignored → TWR = the simple
  rebased return. No special case.

## Why it's cheap (the design insight)
`portfolio_history` already walks the ledger forward label by label
maintaining `net_qty` and has already absorbed every tx at exactly the
right label (the Saturday-pointer problem is solved there). Flows are a
second accumulator folded in the SAME two branches; the index is a
chaining pass over `values` + `flows` afterwards. No new endpoint, no
new caching, no PERIOD_MAP changes, no db changes, no new fetches — the
Performance view swaps datasets from the SAME payload, client-side.

## Test plan (FIRST — must fail until implemented)

### A. Update existing exact-shape assertions (the reply gains 2 keys)
Every portfolio-history reply now carries `index_values` + `twrr_pct`:
- `tests/test_routes.py:575`, `:654`, `:831` — early-return shapes gain
  `"index_values": None, "twrr_pct": None`.
- `tests/test_history_costs.py:35` — same empty-ledger shape.
- `tests/test_chart_speed.py:327`, `:389`, `:433`, `:498-505` — full
  shapes gain the keys; `:498` also becomes the dead-ticker mirror-rule
  lock (BAD's flow excluded → index over AAPL only).
NOT touched: `tests/test_stock.py:196` — the STOCK history endpoint
keeps `{labels, values}` (its page has no TWR view; stays the lock
proving the shared chart factory degrades cleanly).

### B. New file `tests/test_twrr.py`
(Use existing patterns: `client`, `fake_market`, `seed_transaction`,
monkeypatch `app_module.get_history`; floats via `pytest.approx`.)
1. `test_buy_at_unchanged_price_is_zero_twr` — THE user example. Buy
   10@100 (bar0), buy 10@100 (bar1), price flat: values [1000, 2000],
   F_1 = +1000 → r = 0. index [100, 100], twrr_pct 0.0. (Money-weighted
   would also be 0 here — the contrast case is #2.)
2. `test_deposit_after_gain_not_diluted` — THE motivating case. Buy
   10@100 d0; close doubles to 200 d1; buy 10@200 d2; flat d3. values
   [1000, 2000, 4000, 4000], F_2 = +2000. index [100, 200, 200, 200],
   twrr_pct **100.0** (money-weighted says +33% — docstring spells out
   the contrast).
3. `test_withdrawal_doesnt_look_like_loss` — sell recouping 500 at an
   unchanged price → r = 0 that bar; index stays 100.
4. `test_first_bar_flow_absorbed_into_base` — one buy, price +10%
   after: index [100, 110], twrr 10.0. Locks that F_0 is NOT removed
   (double-removal would show 10% twice).
5. `test_weekend_buy_flow_lands_next_bar` — tx dated a non-trading day
   folds its flow at the NEXT trading bar (same pointer rule as the qty
   fold — parity lock). Price flat → r = 0.
6. `test_usd_flow_uses_live_rate_not_stored_fx` — THE differentiator.
   USD ticker, stored `fx_rate=1.4`, live USDCAD 1.5. Mid-series buy:
   r on the buy bar must be **0** (flow = price×qty×**1.5**, the rate
   the series used). Using the stored 1.4 would leave a phantom +6.7%
   FX gain. ALSO asserts `costs` uses the stored 1.4 — both sides of
   the documented divergence in one lock.
7. `test_usd_flow_excluded_when_no_live_rate` — live USDCAD absent →
   the USD ticker contributes 0 to values AND its flow is excluded;
   all-zero series → index null, twrr null.
8. `test_dead_ticker_flow_excluded_mirror_rule` — extends
   test_chart_speed.py:498's scenario: AAPL priced + BAD raises →
   index computed over AAPL only (BAD's buy flow NOT removed); assert
   exact index + twrr.
9. `test_short_truncates_index` — buy 5@100, then sell 10@100 (oversell
   fold opens a short; V goes −500): the bar with a positive base
   computes, chaining STOPS at the first ≤0 base. len(index_values) ==
   2 while len(labels) == 4; twrr_pct over the defined span (0.0).
10. `test_all_unpriced_nulls_index` — only ticker's get_history raises
    → values all 0, V_0 = 0 → index null, twrr null (never 0/0 NaN).
11. `test_empty_ledger_shape` — `{"labels": [], "values": [],
    "costs": [], "index_values": None, "twrr_pct": None}`.
12. `test_1d_degenerates_to_simple_return` — intraday closes 100→110,
    today-dated buy: flows all absorb at bar 0 → index [100, 110],
    twrr 10.0. Locks the no-special-case claim.
13. `test_values_and_costs_unchanged` — regression: `values` and
    `costs` arrays byte-identical to their pre-TWR assertions in a
    multi-ticker scenario (the TWR work must not disturb the shipped
    math).

No pytest for the JS half (house rule: JS is GUI-gated).

## Implementation (after tests exist and fail)

### 1. `app.py` — `portfolio_history` + pure helper (~45 LOC)
- Module-level pure helper `_time_weighted_return(values, flows)` →
  `(index_list_or_None, pct_or_None)` implementing the math section
  verbatim (chaining pass, truncation, null rules). Pure, no
  Flask/network — directly unit-testable, same pattern as the realized
  replay helpers.
- In the walk: a `flows_by_label` accumulator (dict label → net CAD
  contribution) folded in BOTH tx-absorption branches, gated by the
  Mirror rule (symbol priced + currency supported + FX available when
  USD). Rate = 1.0 CAD / `live_rate` USD — the series' own units.
- After the walk: build the flow list in label order (bar 0's entry
  ignored by the helper), call the helper, append `"index_values"` +
  `"twrr_pct"` to the reply. The three early-return `jsonify`s (empty
  ledger, intraday-future tx, all-trimmed) gain `"index_values": None,
  "twrr_pct": None`.
- Code comment (permanent rationale): flows use the flat live rate, NOT
  the stored fx_rate the cost side uses — a flow must be measured in
  the series' own units or removal leaves a phantom FX gain (Mirror
  rule + divergence documented).

### 2. `static/js/common.js` — `setupTimeframeChart` (~40 LOC)
- Optional config `performance: { key: "index_values" }`. When present,
  the factory renders a "Value | Performance" segment toggle in the
  chart card and holds the last payload per refresh; toggling swaps
  dataset[0].data between `values` and `index_values` (NO refetch —
  same payload, client-side), updates the dataset label to "Growth of
  $100 (TWR)", and hides the cost dataset + "Gain" tooltip footer
  (CAD amounts are meaningless on a unitless index axis).
- `index_values` may be SHORTER than `labels` (truncation) → slice
  labels for the performance dataset. `null` → Performance view shows
  its empty/unavailable state (same ethos as the unpriced gap-fill).
- Persist last view in localStorage (donut-carousel precedent); both
  views share the timeframe buttons and refresh cycle untouched.
- Price-diff measuring stays pinned to dataset[0] — a freebie: on the
  index line that diff IS the TWR from window start.
- Stock page passes no `performance` config → no toggle rendered,
  datasets untouched, pixel-identical (test_stock.py:196 stays green).

### 3. `templates/index.html` + `static/js/main.js` (~15 LOC)
- Toggle markup in the dashboard chart card (stock page gets none).
- `setupTimeframeChart({... performance: { key: "index_values" }})`.

## Notes
- Ledger column counts, PERIOD_MAP, importer, realized replay, summary
  strip: untouched. Privacy masking: chart data is unmasked today; the
  Performance view adds no new category of exposure.
- Backend sends raw floats; formatting/pos-neg coloring stays
  frontend-only (existing contract).
- Roadmap synergy: the rebase-to-100 + multi-dataset machinery here is
  exactly what #7 (Benchmark Comparison Line) needs — building #13
  first makes #7 mostly a data-plumbing task.
- Gates after implementation: FULL `python -m pytest` green → user GUI
  check (toggle flips views; deposits don't jump the Performance line;
  stock page unchanged) → commit only on explicit yes.
