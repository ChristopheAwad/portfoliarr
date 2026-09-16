# Feature: Cost basis on the portfolio chart (hover tooltip + dashed line)

## Status
Implemented. FULL suite green (476 passed). NEXT STEP: user GUI check of
the dashboard chart (hover shows Value / Cost Basis / Gain in the tooltip
+ a faint dashed cost line that appears ONLY while hovering and vanishes
on mouse-out; the y-axis never reflows; stock page chart unchanged), then
commit gate on explicit yes.

NOTE (post-implementation refinement): the dashed cost line is a hover
DECORATION, not a Chart.js dataset — drawn by the `costLine` plugin in
`afterDatasetsDraw` only while the tooltip is active. A real dataset was
tried first but toggling its `hidden` recomputed the y-axis on every
mouse-in/out (the value line jumped under the cursor). The decoration
keeps the axis sized to the value line only.

## The idea
The dashboard's value chart hover currently shows only the portfolio value
at each bar. Add the cost basis (netted contributions) at that same point,
so the hover answers "what did I pay vs what is it worth — and by how
much?" — i.e. the portfolio's gain-to-date AT ANY HISTORICAL MOMENT.

Three user decisions (locked):
1. **Tooltip + faint dashed second line** — cost basis is also plotted
   (dashed, muted), not just tooltip text.
2. **Netted cost basis** — buys paid minus sells recouped, the SAME
   definition as `/api/portfolio/summary`'s `cost_basis` (app.py:544).
   Value − cost at any label = blended realized+unrealized gain to that
   date, so the tooltip reconciles with the summary strip's total return.
3. **Third tooltip line "Gain"** — value − cost, green/red by sign.

## Why it's cheap (the design insight)
`portfolio_history` (app.py:238) already walks the ledger forward label by
label maintaining `net_qty`. Cost basis is FROZEN LEDGER MATH —
`Σ ±(price × qty × fx_rate)`, no quotes, no network — so a second
accumulator (`net_cost`) folds into the SAME walk for free. No new
endpoint, no new caching, no PERIOD_MAP changes, no template changes,
no db changes.

## Test plan (FIRST — must fail until implemented)

### A. Update existing exact-shape assertions (portfolio history gains `costs`)
Every portfolio-history reply now carries THREE keys, so these exact-shape
asserts gain `"costs"`:
- `tests/test_routes.py:575` (empty ledger)
- `tests/test_routes.py:654`
- `tests/test_routes.py:831`
- `tests/test_chart_speed.py:319` (5D intraday-with-buys shape)
- `tests/test_chart_speed.py:382` (3M)
- `tests/test_chart_speed.py:425` (5Y)
NOT touched: `tests/test_stock.py:196` — the STOCK history endpoint keeps
`{labels, values}` (its page has no cost line; this stays the lock proving
the shared chart factory degrades cleanly).

### B. New file `tests/test_history_costs.py`
1. `test_history_costs_empty_ledger` — empty ledger →
   `{"labels": [], "values": [], "costs": []}`.
2. `test_costs_constant_between_buys` — CAD buy 10 @ 100; closes 100→110→120:
   `values` move, `costs` stays `[1000.0, 1000.0, 1000.0]` (cost is what
   was PAID, not what it's worth).
3. `test_sell_nets_cost_basis` — buy 10 @ 100 (cost 1000), sell 4 @ 120:
   from the sell's label on, cost = 1000 − 480 = **520** (sells subtract
   what they recouped — summary-strip parity).
4. `test_usd_cost_uses_stored_fx_not_live` — THE differentiator. USD row
   with stored `fx_rate=1.4`, live `USDCAD=1.5`:
   cost = 10 × 100 × **1.4 = 1400** (frozen fact), while the value side
   uses the LIVE rate (10 × close × 1.5). Locks that the two sides
   deliberately use different rates (value = live, cost = stored).
5. `test_null_fx_usd_row_falls_back_to_live_rate` — USD row with
   `fx_rate=None` (pre-feature row) → cost converts at the LIVE rate,
   the documented per-request fallback.
6. `test_null_fx_usd_row_live_rate_down_contributes_zero` — USD row with
   `fx_rate=None` AND no USDCAD answer → that row contributes 0 to cost
   (never a fake 1:1), same honesty rule as the value side.
7. `test_oversell_negative_cost_is_honest` — buy 5 @ 100 (500), sell
   10 @ 120: netted cost goes **−700** from the sell on. A short's
   "contributions" are negative by the netted definition (matches
   test_portfolio_summary's negative-cost-basis semantics); no clamping.
8. `test_intraday_1d_walked_in_cost_applies_at_first_bar` — 1D period:
   a buy from a PAST day + today's buy both fold into `costs` at today's
   FIRST bar, then cost stays flat for the rest of the day (mirrors the
   value branch's `today_applied` semantics).
9. `test_saturday_buy_applies_cost_next_trading_label` — a buy dated a
   non-trading day folds its cost at the NEXT trading bar (same
   transaction-pointer rule the qty fold uses — parity lock).

No pytest for the JS half (house rule: JS is GUI-gated).

## Implementation (after tests exist and fail)

### 1. `app.py` — `portfolio_history` (~30 LOC)
- New `net_cost` dict alongside `net_qty`, folded in BOTH transaction
  branches (daily `while tx_index` loop AND the intraday
  `today_applied` first-bar block):
  `sign × price × qty × rate`, where rate =
  - USD + stored `fx_rate` → that stored rate (frozen fact)
  - USD + `fx_rate is None` → `live_rate` (already fetched when any USD
    ticker exists); if `live_rate is None` → 0
  - CAD → 1.0 (rows store exactly that)
  - any other currency → skip (0), same rule as the value side
- Per label: `costs.append(sum(net_cost.values()))` — same length as
  `values` by construction (flat between trades, steps at each tx).
- The three early-return `jsonify`s (empty ledger, intraday-future tx,
  all-labels-trimmed) gain `"costs": []`; final return gains `"costs"`.
- Comment to leave in code (permanent rationale): the cost side uses each
  transaction's STORED fx_rate while the value side uses the flat live
  rate — deliberate, mirroring the summary strip (value = a potential
  sell at today's rate; past costs = frozen facts). Dead tickers: value
  freezes at last close / contributes 0, cost stays a ledger fact —
  consistent with the route's "the ledger is the truth" stance.

### 2. `static/js/common.js` — `setupTimeframeChart` (~35 LOC)
- Second dataset at chart creation: `data: []`, `label: "Cost Basis (CAD)"`,
  `borderColor` scriptable (reads `--text-secondary` CSS var per draw so
  theme flips stay correct), `borderDash: [5, 3]`, `borderWidth: 1`,
  `fill: false`, `pointRadius: 0`.
- `let lastCosts = null;` — set in `refresh()`:
  `lastCosts = Array.isArray(data.costs) ? data.costs : null;`
  `chart.data.datasets[1].data = lastCosts ?? [];` → the STOCK page's
  endpoint sends no `costs`, so its second dataset stays empty: nothing
  drawn, no scale effect, no tooltip item (mode "index" only emits items
  for datasets with data at that index) → stock page pixel-identical.
- Tooltip rework (shared factory, both pages):
  - `label(item)` → `` `${item.dataset.label}: ${formatPrice(item.parsed.y)}` ``
    — dataset label already differs per page ("Portfolio Value (CAD)" vs
    the stock page's own label), so no new config key.
  - `footer(items)` → when `lastCosts` exists at `items[0].dataIndex`:
    `Gain: $X` where X = value − cost; `footerColor` scriptable by sign
    (green/red). Returns nothing on the stock page.
- Price-diff measuring stays pinned to `datasets[0]` (the VALUE line) —
  add a comment; measurement semantics deliberately unchanged.
- `displayColors: false` stays; text prefixes distinguish the lines.

## Notes
- Ledger column counts, PERIOD_MAP, importer, realized replay: untouched.
- Privacy: chart tooltips already show raw numbers by design; the cost
  line adds no new category of exposure. No masking work.
- Backend sends raw floats; formatting/pos-neg coloring stays
  frontend-only (existing contract).
- Gates after implementation: FULL `python -m pytest` green → user GUI
  check (dashboard hover shows 3 lines + dashed line renders; stock page
  unchanged) → commit only on explicit yes.
