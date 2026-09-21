# Feature #19: Date-Aware Ledger Price Auto-Fill

## Status

SHIPPED 2026-09-21 (PR #67). Tests written first, production code in
`market_data.py`, `app.py`, and `static/js/ledger.js`, and the full
`python -m pytest` suite passes (762 passed). The user approved the browser
behavior before the PR was opened.

## Problem

When the user picks a ticker in the ledger transaction form, the Price field
fills with the **live** quote (`prefillPriceForTicker` in `static/js/ledger.js`,
which calls `GET /api/quote/<symbol>`). The Date field is ignored. If the user
logs a past transaction (for example, a buy from last month), the field still
shows today's price. The user must look up the historical close by hand.

The Date field and the Price field are two facts about the same event. They must
agree.

## Goal

Make the Price auto-fill depend on the selected Date:

1. Picking a ticker fills Price with the latest recorded close **on or before**
   the selected date.
2. Changing the date refreshes Price for the new date.
3. A date equal to today (or an empty date) uses the existing live quote.
4. A manually typed price is never overwritten by a date change.
5. Edit mode never re-fetches; the stored price stays the immutable fact.

## Locked Product Decisions

1. Historical price means the last daily `Close` on or before the selected
   date. Weekends and holidays fall back to the prior trading day's close.
   This matches the existing `get_fx_rate_on` rule in `market_data.py`.
2. Date equal to the browser's local today, or an empty date, uses the live
   `/api/quote/<symbol>` quote (today has no settled close).
3. A future date is treated as "not today": it returns the latest available
   close. (The transaction validator already allows future dates.)
4. A date change re-fetches only when all three are true: not in edit mode, the
   price is an untouched auto-fill (`priceEdited === false`), and a ticker is
   present. A user-typed price always wins.
5. Edit mode (`editingTxId !== null`) never re-fetches on a date change. The
   stored price is the recorded fact.
6. A failed historical lookup leaves the Price field empty. This is the current
   honest failure behavior. The user types the price, and the backend
   re-validates at submit.
7. Do not cache the historical price. `get_fx_rate_on` is also uncached, and
   date changes are user-driven and rare.
8. No database, response-shape, Android, dependency, or deployment change.

## Existing Contracts To Preserve

1. `GET /api/quote/<symbol>` with no `date` query keeps its exact current reply
   shape (`symbol, price, previous_close, currency, change, change_pct`) and
   never calls `get_name`.
2. The Price field shows 2 decimals, but `autofillPrice` keeps the full
   precision and the submit uses it when untouched
   (`priceEdited ? Number(fields.price) : (autofillPrice ?? Number(fields.price))`).
3. `prefillPriceForTicker` still clears the field first, and still backs the
   fill with `autofillPrice` plus `priceEdited = false`.
4. The stale-guard still stops an older reply from overwriting a newer pick.
   It must now also compare the requested date.
5. `exitEditMode`, `enterEditMode`, `prepareFullSale`, and the submit handler
   keep their current behavior. Programmatic `.value` sets on the date input
   fire no `change` event, so they cannot loop back into the new listener.
6. The ledger keeps 11 columns. No template change.
7. `todayLocalISO()` stays the single source for the browser's local today.
8. Backend floats stay raw; formatting stays in JavaScript.
9. Polling continues through `setupAutoRefresh`; add no interval.

## Files

Production:

- `market_data.py` — new `get_price_on(symbol, date_iso)`
- `app.py` — import it; extend `GET /api/quote/<symbol>` with optional `?date=`
- `static/js/ledger.js` — date-aware URL helper and the date listener

Tests:

- `tests/test_market_data.py` — unit tests for `get_price_on`
- `tests/test_quote.py` — route tests for `?date=`
- `tests/test_price_autofill.py` — frontend meta-tests
- `conftest.py` — add `get_price_on` to `fake_market`

Planning:

- `feature.md`
- `roadmap.md`

No template, database, Android, dependency, or deployment edit.

## Test-First Plan

Write the tests below BEFORE the production edits. Run them and confirm they
fail for the intended missing behavior. Pytest does not run browser JavaScript,
so frontend tests use the repository's string-lock source/meta-test style.

### A. `market_data.get_price_on` — `tests/test_market_data.py`

Add these next to the existing `get_fx_rate_on` tests (around line 650). Use the
existing `fake_yf` fixture. `fake_yf.state["history"]` takes a DataFrame. The
`FakeTicker.history` records a date-window fetch as
`("range", symbol, start, end)`.

1. `test_price_on_returns_the_close_on_the_date`: a DataFrame with closes for
   `2026-08-27`, `2026-08-28`, `2026-08-31` returns the `2026-08-31` close when
   asked for `2026-08-31`. Assert the call
   `("range", "AAPL", "2026-08-21", "2026-09-01")` is in `fake_yf.calls`, proving
   the window is `date − 10 days` to `date + 1 day` (exclusive end).
2. `test_price_on_weekend_falls_back_to_prior_close`: bars on `2026-08-28` and
   `2026-08-31`; ask for `2026-08-29` (Saturday) and get Friday's close.
   (Use the actual weekday of those dates or pick clearly-known dates; the
   point is "no bar exactly on the date".)
3. `test_price_on_ignores_bars_after_the_date`: bars on `2026-08-31` and
   `2026-09-02`; ask for `2026-08-31` and get only the `2026-08-31` close, never
   the later bar.
4. `test_price_on_raises_when_no_bar_covers_the_date`: only a bar strictly
   after the date → `pytest.raises(ValueError)`.
5. `test_price_on_rejects_invalid_prices`: parametrize `float("nan")`,
   `float("inf")`, `float("-inf")`, `0.0`, `-1.0` → each raises `ValueError`.
6. `test_price_on_empty_dataframe_raises`: an empty DataFrame → `ValueError`.

### B. `GET /api/quote/<symbol>?date=` — `tests/test_quote.py`

Extend the file. `fake_market` must gain a `prices_on` dict keyed
`(symbol, "YYYY-MM-DD")`. An absent key simulates "no bar covers the date". Add:

1. `test_quote_with_date_returns_historical_price`: put
   `fake_market.prices_on[("AAPL", "2026-08-31")] = 123.45`; call
   `GET /api/quote/AAPL?date=2026-08-31`; assert 200 and
   `body["price"] == 123.45` and `body["symbol"] == "AAPL"`.
2. `test_quote_with_date_does_not_touch_live_quote`: leave
   `fake_market.quotes` empty; the dated call must still return 200, proving
   `get_quote` was not used on the dated path.
3. `test_quote_with_bad_date_returns_400`: `?date=not-a-date` and
   `?date=2026-02-30` both return 400.
4. `test_quote_with_uncovered_date_returns_404`: a valid date with no
   `prices_on` entry returns 404.
5. Keep every existing test unchanged and green: the no-date path still returns
   the live dict with no `name` key.

### C. Frontend meta-tests — `tests/test_price_autofill.py`

Keep all existing tests. Add:

1. `test_price_prefill_builds_dated_url_for_past_date`: assert the source
   contains a helper (suggested name `priceQuoteUrl`) that returns
   `` `/api/quote/${encodeURIComponent(symbol)}?date=${encodeURIComponent(...)}` ``.
   Lock the `?date=` substring and the `encodeURIComponent` call.
2. `test_price_prefill_uses_today_helper_for_live_path`: assert the helper
   compares the date input against `todayLocalISO()` and falls back to the plain
   `/api/quote/<symbol>` URL for today or an empty date.
3. `test_prefill_reads_date_input`: assert `prefillPriceForTicker` (or the
   helper) reads `txDateInput.value`.
4. `test_prefill_stale_guard_checks_date`: assert the reply handler compares
   the current date input to the requested date before filling.
5. `test_date_change_listener_calls_prefill`: assert a
   `txDateInput.addEventListener("change", ...)` block calls
   `prefillPriceForTicker()`.
6. `test_date_change_listener_guards`: assert the listener returns early for
   `editingTxId !== null`, for `priceEdited`, and for an empty ticker. Lock the
   three guard expressions, not their comments.

### D. `conftest.py` — `fake_market`

Add `prices_on = {}` to the fixture and add:

```python
monkeypatch.setattr(app_module, "get_price_on",
                    lambda symbol, date_iso: prices_on[(symbol, date_iso)])
```

Return `prices_on` on the `SimpleNamespace` too. Patch at `app_module`, because
`app.py` imports the name (`from market_data import ...`) — patch where it is
used.

## Implementation Plan

Start only after the tests above fail for the right reason.

### 1. Add `get_price_on` to `market_data.py`

Place it directly after `get_fx_rate_on` (around line 626). Copy that function's
shape:

1. Parse with `date.fromisoformat(date_iso)`.
2. Fetch `yf.Ticker(symbol).history(start=(d - timedelta(days=10)).isoformat(),
   end=(d + timedelta(days=1)).isoformat(), interval="1d")`.
3. Walk `df.iterrows()` in ascending order. For each row whose timestamp date is
   on or before `d`, keep the last `_positive_finite_number(row["Close"])` that
   is not `None`. Break when a row's date is after `d`.
4. If no valid close was kept, `raise ValueError(f"no price for {symbol} on or
   before {date_iso}")`.
5. Return the kept float. Do not cache. Add a short teaching comment that
   explains "why on-or-before" (weekends/holidays) and "why uncached"
   (user-driven, one lookup per date change; same as `get_fx_rate_on`).

### 2. Extend the quote route in `app.py`

1. Add `get_price_on` to the `from market_data import (...)` list at line 31.
2. In `quote(symbol)` (line 2751), after the `symbol = symbol.strip().upper()`
   line, read `date_arg = request.args.get("date")`.
3. When `date_arg is not None`:
   - Normalize with `date.fromisoformat(date_arg).isoformat()`. On `ValueError`
     return `jsonify({"error": "date must be YYYY-MM-DD (a real calendar
     date)"}), 400`.
   - Call `get_price_on(symbol, date_iso)`. On any `Exception`, log at INFO
     (same rule as the live 404) and return
     `jsonify({"error": f"no price for {symbol} on {date_iso}"}), 404`.
   - Return `jsonify({"symbol": symbol, "price": price, "date": date_iso})`.
4. When `date_arg is None`, keep the current live code path byte-for-byte.
5. Update the route docstring to describe the optional `date` query.

### 3. Make the prefill date-aware in `static/js/ledger.js`

1. Add a small helper above `prefillPriceForTicker`:

   ```js
   function priceQuoteUrl(symbol) {
       const date = txDateInput.value;
       return (date && date !== todayLocalISO())
           ? `/api/quote/${encodeURIComponent(symbol)}?date=${encodeURIComponent(date)}`
           : `/api/quote/${encodeURIComponent(symbol)}`;
   }
   ```

   Explain in one comment: today (or empty) means the live quote; any other
   date means the recorded close on or before it.

2. In `prefillPriceForTicker`:
   - After computing `symbol`, capture `const requestedDate = txDateInput.value;`.
   - Keep clearing the field first.
   - Replace the fetch URL with `priceQuoteUrl(symbol)`.
   - In the reply handler, add the date to the stale-guard:
     `if (txForm.elements.ticker.value.trim().toUpperCase() !== symbol ||
      txDateInput.value !== requestedDate) return;`
   - Keep the exact `autofillPrice = quote.price` and
     `txForm.elements.price.value = quote.price.toFixed(2)` lines.
3. Add a date listener after the existing `txDateInput.value = todayLocalISO()`
   load line (around line 1467):

   ```js
   txDateInput.addEventListener("change", () => {
       if (editingTxId !== null) return;                  // edit mode: fact wins
       if (priceEdited) return;                           // manual price wins
       if (!txForm.elements.ticker.value.trim()) return;  // nothing to price
       prefillPriceForTicker();
   });
   ```

   Comment the three guards and the edit-mode rule.

### 4. Update comments

Keep the repository's teaching-comment style. Document only the non-obvious
rules: on-or-before close, today = live, manual price protection, and edit mode
exempt.

## Verification

Run focused tests:

```bash
source .venv/bin/activate
python -m pytest tests/test_market_data.py tests/test_quote.py
python -m pytest tests/test_price_autofill.py
```

Then the lead agent runs the full suite:

```bash
source .venv/bin/activate
python -m pytest
```

No implementation is complete until the full suite passes.

## Browser GUI Approval Checklist

After pytest passes, stop for user inspection before any commit or push.

1. Pick a ticker with Date = today → Price shows the live quote.
2. Change Date to a past trading day → Price refreshes to that day's close.
3. Change Date to a weekend or holiday → Price shows the prior trading day's
   close.
4. Type a price, then change the Date → the typed price is kept.
5. Change the Date with no ticker → nothing happens.
6. Enter edit mode on an old transaction, then change the Date → the stored
   price is kept.
7. Pick a ticker whose date has no history (for example, a date before the
   ticker existed) → the Price field is left empty with no error toast.
8. The form still submits the exact auto-filled precision when untouched, and
   the typed value when edited.
9. Quick Sell still fills ticker, full quantity, today's live price, local
   date, and SELL.
10. Existing ledger grouping, sorting, expansion, import, and polling still
    work.

## Completion Gates

1. This plan and roadmap item #19 `in progress`: complete after this edit.
2. User approves this plan before implementation.
3. Write failing tests first.
4. Implement production code.
5. Pass focused tests.
6. Pass full `python -m pytest`.
7. Obtain browser GUI approval.
8. Only then ask whether to commit and push.
9. Mark #19 shipped only in the approved commit, with PR number and date or a
   direct-main date.

## Definition Of Done

Picking a ticker or changing the date fills Price with the latest recorded close
on or before the selected date, except today, which uses the live quote. A
manually typed price and edit mode are never overwritten. The live endpoint's
reply shape is unchanged. All tests pass, and the user approves the browser
behavior.
