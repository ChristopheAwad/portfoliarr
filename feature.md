# Feature: TWR Flow-Timing Alignment (Roadmap #14)

## Status
IMPLEMENTED — tests A/B/C written first (A and B failed on the buggy build),
then the per-bar flow fix. Focused suites and the full 585-test suite pass.
Browser GUI approved by the user; ready for the approved PR workflow.

## Goal
Fix the one correctness bug in the TWR "Performance" chart view. A cash flow
must be removed on the same bar where its symbol's value enters the series,
not on the transaction's absorption label. Today a ticker whose first in-window
price bar comes AFTER its buy's absorption label has its flow removed while it
still contributes 0 to the value line. That fakes a one-bar loss. In the extreme
(flow is large compared with the rest of the portfolio) it trips the truncation
guard and makes the whole index `null` or permanently short.

This is the bug the audit found as finding #1 and that roadmap #14 already
describes. No other audit finding is in scope.

## Root cause (verified in code)
- `flowable_symbols` (`app.py:558-565`) gates flow removal per SYMBOL. It only
  requires `max(history) >= labels[0]`.
- The transaction walk removes the flow at the transaction's ABSORPTION LABEL:
  - intraday branch: `app.py:622-624`
  - daily branch: `app.py:640-642`
- The value walk (`app.py:665-671`) contributes 0 when the symbol has no bar at
  that label and no carried-forward close.
- So a symbol can pass the per-symbol gate but have no measured price at the
  absorption label. The flow is subtracted anyway:
  `r_i = (0 − F_i − V_{i−1}) / V_{i−1}`. If `F_i >= V_{i−1}`, then
  `post_flow_value = V_i − F_i = −F_i <= 0`, and `_time_weighted_return`
  (`app.py:281-283`) breaks the chain. Result: `index_values` is `null` (one
  bar removed) or a permanently short index.

## The contract after the fix (do not deviate)
1. A flow is removed on the FIRST label where its symbol has a MEASURED price.
   "Measured price" = a bar at that label, or a carried-forward last close —
   the exact same marker the value walk uses (`last_closes`).
2. A symbol that never prices inside the window keeps its flows pending
   forever, so they are never removed. This preserves the existing mirror rule
   (no value in the series, no flow out).
3. Currency eligibility is unchanged: CAD always, USD only when a live rate
   exists. Unsupported currencies and USD-without-rate still contribute 0 flow.
4. The normal case is unchanged: a symbol that prices at its absorption label
   flushes the flow there, exactly as today. All existing TWR tests must keep
   passing without edits.
5. Sell-to-zero is preserved: the sell's negative flow is removed on the
   zeroing bar (the symbol already has a `last_closes` entry), so a full
   withdrawal still reads 0% and truncates at the empty base.

## Test plan (write these FIRST; they must fail on the current build)

Add the following three tests to `tests/test_twrr.py`. Use the file's existing
`seed_transaction` helper and the `client` / `fake_market` fixtures. Append them
after `test_delisted_before_window_flow_excluded` (after line 283), under the
existing mirror-rule section.

### Test A — the core regression (fails on the current build)
Name: `test_flow_deferred_until_symbol_first_prices`

Scenario:
- 2026-08-28 buy AAPL 10 @ 100 (CAD)
- 2026-08-31 buy MSFT 10 @ 100 (CAD)
- AAPL history: `{"2026-08-28": 100.0, "2026-08-31": 100.0, "2026-09-01": 100.0}`
- MSFT history: `{"2026-09-01": 100.0}` (deliberate data gap on 08-31)

Why it fails now: MSFT's first bar is 09-01, after its absorption label 08-31.
On 08-31 MSFT contributes 0 but its +1000 flow is removed, so
`post_flow_value = 1000 − 1000 = 0` breaks the chain and the route returns
`index_values: None`. The fixed build holds the flow pending until 09-01.

Exact assertions:
```python
def test_flow_deferred_until_symbol_first_prices(client, fake_market):
    """Roadmap #14: MSFT's first in-window bar (09-01) lands AFTER its
    buy's absorption label (08-31). Its flow must NOT be removed on
    08-31 while MSFT still contributes 0 — that removal would drive r to
    −100% and truncate the whole index (the buggy build returns None).
    The pending flow flushes on 09-01, the first bar MSFT prices.

        08-28 buy AAPL 10 @ 100 (CAD)  AAPL closes 100
        08-31 buy MSFT 10 @ 100 (CAD)  AAPL 100; MSFT has no bar → 0
        09-01                          AAPL 100 + MSFT 100 = 2000
        values [1000, 1000, 2000]; flows [1000, 0, 1000]
        r1 = (1000 − 0 − 1000)/1000 = 0
        r2 = (2000 − 1000 − 1000)/1000 = 0 → index [100, 100, 100]"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="MSFT", date="2026-08-31", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0, "2026-09-01": 100.0,
    }
    fake_market.histories["MSFT"] = {"2026-09-01": 100.0}

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31", "2026-09-01"]
    assert body["values"] == [1000.0, 1000.0, 2000.0]
    assert body["costs"] == [1000.0, 2000.0, 2000.0]
    assert body["index_values"] == [100.0, 100.0, 100.0]
    assert body["twrr_pct"] == 0.0
```

### Test B — the flow flushes once and the return is true (fails now)

Exact assertions:
```python
def test_deferred_flow_flushed_once_on_first_price(client, fake_market):
    """The pending flow must be removed exactly once, at the first measured
    price, and must not leave a permanent phantom. Non-zero return so a
    missing flush or a double flush both change the answer.

        08-28 buy AAPL 10 @ 100 (CAD); AAPL 100
        08-31 buy MSFT 10 @ 100 (CAD); AAPL 110; MSFT no bar → 0
        09-01 AAPL 121 + MSFT 110 = 2310; MSFT's +1000 flow flushes
        r1 = (1100 − 0 − 1000)/1000       = 0.10   → index 110
        r2 = (2310 − 1000 − 1100)/1100    = 0.1909 → index 131 = +31%"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="MSFT", date="2026-08-31", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0, "2026-09-01": 121.0,
    }
    fake_market.histories["MSFT"] = {"2026-09-01": 110.0}

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [1000.0, 1100.0, 2310.0]
    assert body["index_values"] == pytest.approx([100.0, 110.0, 131.0])
    assert body["twrr_pct"] == pytest.approx(31.0)
```

Buggy result for comparison: `index_values` is `[100, 10, 21]`,
`twrr_pct = −79`.

### Test C — sell-to-zero regression lock (passes before AND after)
This test guards against the pending mechanism accidentally dropping a sell
flow when the position goes to zero.

Exact assertions:
```python
def test_sell_to_zero_flow_removed_on_zero_bar(client, fake_market):
    """REGRESSION LOCK (passes before and after #14): when a sell takes the
    position to 0, the symbol contributes no value that bar but DOES have a
    carried-forward close, so its negative flow must still be removed — a
    full withdrawal reads 0%, then the empty base truncates the chain.

        08-28 buy 10 @ 100        V = 1000
        08-31 sell 10 @ 100       V = 0, F = −1000
        r1 = (0 + 1000 − 1000)/1000 = 0 → index [100, 100], then V=0 stops."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=10,
                     tx_type="SELL", currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0, "2026-09-01": 100.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [1000.0, 0.0, 0.0]
    assert body["index_values"] == [100.0, 100.0]
    assert len(body["index_values"]) < len(body["labels"])
    assert body["twrr_pct"] == 0.0
```

### Existing tests that must keep passing unchanged
- `tests/test_twrr.py` (all 13 tests) — especially
  `test_delisted_before_window_flow_excluded`,
  `test_dead_ticker_flow_excluded_mirror_rule`,
  `test_usd_flow_excluded_when_no_live_rate`,
  `test_usd_flow_uses_live_rate_not_stored_fx`,
  `test_weekend_buy_flow_lands_next_bar`,
  `test_short_truncates_index`.
- `tests/test_chart_speed.py` TWR assertions (`index_values` / `twrr_pct`).
- `tests/test_history_costs.py`, `tests/test_routes.py` TWR key shapes.

## Implementation (only after tests A and B fail)

All changes are in `app.py`, inside `portfolio_history`.

### Step 1 — replace the flow gate block (`app.py:542-565`)
Replace the whole comment + `flowable_symbols` block with this. The eligibility
set drops the `max(history) >= labels[0]` condition; timing is now handled by
the pending walk.

```python
    # THE MIRROR RULE: a transaction's flow is removed ONLY at a bar where
    # its symbol's value is actually measured. A dead ticker (get_history
    # raised → empty dict) contributes 0 to values, so removing its buy
    # would "return" money that never arrived — that would fake a LOSS.
    # Same for a USD row with no live rate, or an unsupported currency.
    #
    # The mirror is PER-BAR, not per-symbol (roadmap #14). A ticker's
    # first bar inside the window can land AFTER its transaction's
    # absorption label (a Yahoo data gap, or a MAX window whose history
    # starts later than a logged buy). On those gap bars the ticker still
    # contributes 0: removing its flow anyway would fake a one-bar loss
    # (and, when the flow is large, truncate the whole index). So each
    # symbol's flows wait in `pending_flows` and flush at the FIRST label
    # where that symbol has a measured price — the exact bar its value
    # enters the series. A symbol that never prices in the window keeps
    # its flows pending forever, so they are never removed (no value, no
    # flow). The set below gates CURRENCY only; the pending/flush walk
    # gates timing.
    flow_eligible_symbols = {
        symbol for symbol, currency in currency_by_symbol.items()
        if currency == "CAD"
        or (currency == "USD" and live_rate is not None)
    }
```

### Step 2 — retarget `tx_flow`'s gate (`app.py:576`)
Change:
```python
        if tx["ticker"] not in flowable_symbols:
```
to:
```python
        if tx["ticker"] not in flow_eligible_symbols:
```
Leave the rest of `tx_flow` unchanged.

### Step 3 — add the pending accumulator (`app.py:597`)
After:
```python
    flows_by_label = {}  # label → net CAD cash contribution absorbed there
```
add:
```python
    pending_flows = {}   # symbol → flows absorbed BEFORE it first prices
```

### Step 4 — accumulate, do not remove, in the intraday branch (`app.py:622-624`)
Replace:
```python
                        flows_by_label[label] = (
                            flows_by_label.get(label, 0.0) + tx_flow(tx)
                        )
```
with:
```python
                        pending_flows[tx["ticker"]] = (
                            pending_flows.get(tx["ticker"], 0.0) + tx_flow(tx)
                        )
```
This block is the one indented 24 spaces (inside `if tx["transaction_date"] <= label_date_today:`).

### Step 5 — accumulate, do not remove, in the daily branch (`app.py:640-642`)
Replace:
```python
                flows_by_label[label] = (
                    flows_by_label.get(label, 0.0) + tx_flow(tx)
                )
```
with:
```python
                pending_flows[tx["ticker"]] = (
                    pending_flows.get(tx["ticker"], 0.0) + tx_flow(tx)
                )
```
This block is the one indented 16 spaces (inside the `while`).

### Step 6 — flush after the value/cost append (`app.py`, after line 687)
Insert after `costs.append(sum(net_cost.values()))` and before the closing of the
`for label in labels:` loop:

```python
        # Flush every held symbol's pending flows at the first label where
        # that symbol has a measured price (a bar now, or a carried-forward
        # last close). `last_closes` is the same "this symbol's value is
        # real at this label" marker the value walk used just above, so a
        # flow is removed on exactly the bar its value enters — no earlier.
        # A symbol that never prices here stays in `pending_flows` forever,
        # so its flows are never removed (the mirror rule, now per-bar).
        for symbol in [s for s in pending_flows if s in last_closes]:
            flow = pending_flows.pop(symbol)
            if flow:
                flows_by_label[label] = (
                    flows_by_label.get(label, 0.0) + flow
                )
```

Order matters: `last_closes` is updated inside the value loop, which runs
before this flush, so the current label's price is visible. Do NOT move the
flush above the value loop.

### Why Step 6 also covers sell-to-zero
The value loop skips `held == 0`, so on the zeroing bar it does not re-add the
symbol to `last_closes`; but `last_closes` keeps the entry from earlier bars.
The condition `s in last_closes` is therefore true, and the sell flow flushes.
A symbol that never priced at all is never in `last_closes`, so its flows stay
pending forever.

## Files touched
- `app.py` — the six edits above (comment block, set rename, pending
  accumulator, two accumulation sites, flush).
- `tests/test_twrr.py` — three new tests (A, B, C).
- `roadmap.md` — `**Status:** in progress` under item #14.

No frontend change. The reply shape (`index_values`, `twrr_pct`) is unchanged.
No `db.py`, `market_data.py`, template, or JS change.

## Verification and gates
1. Write tests A, B, C into `tests/test_twrr.py`.
2. Run `python -m pytest tests/test_twrr.py -q` and confirm A and B FAIL on the
   current build while C passes. If A or B passes, the test does not reproduce
   the bug — stop and fix the test before touching `app.py`.
3. Apply the six `app.py` edits.
4. Run `python -m pytest tests/test_twrr.py -q` — all must pass.
5. Run `python -m pytest tests/test_chart_speed.py tests/test_history_costs.py
   tests/test_routes.py -q`.
6. Run the full suite `python -m pytest` (lead agent owns the final verdict).
7. Wait for the user's browser GUI approval: open the dashboard, switch to the
   Performance view, and confirm the index line is not truncated and the
   Performance view still toggles correctly. A data gap is hard to create by
   hand; the GUI gate confirms no visible regression, and the tests prove the
   gap case.
8. Ask before any commit or push; mark roadmap #14 shipped only in that commit.
