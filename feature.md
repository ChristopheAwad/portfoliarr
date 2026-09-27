# Historical FX backfill (roadmap #39)

Status: in progress

A terminal maintenance command, NOT a Preferences button (the button would be a
one-time no-op). `python app.py backfill-fx <username|--all>` finds every USD
transaction whose stored `fx_rate` is NULL, re-derives the historical USDCAD
close on that row's own date, writes it back, and reports fixed/unresolved
counts. It NEVER guesses: it calls `get_fx_rate_on` (historical bar only) and
has NO live-rate fallback, so a date with no bar stays NULL.

Write every failing test named below FIRST, then implement, then run the FULL
`python -m pytest` suite. Never commit.

## Locked decisions (user-approved)
- Command name: `backfill-fx`. Flag: `--all`.
- Exit code `0` when the command ran, even if some rows stay unresolved
  (a Yahoo gap is honest, not a failure). `1` only for unknown user or bad
  usage.
- Historical only. Never reuse `_derive_fx_rate` (it falls back to the live
  rate).
- NULL-only. A row that already holds a rate is never rewritten.
- Scope: one user by name, or every user with `--all`. Each user's own
  portfolios only. Unclaimed (`user_id NULL`) portfolios are skipped.

## 1. db.py — two new functions (NO schema change)

Place near `set_password` / `update_transaction`.

1. `get_unrated_usd_transactions(portfolio_id)`:
   - Returns a list of plain dicts `{"id", "ticker", "transaction_date"}`.
   - SQL:
     ```sql
     SELECT id, ticker, transaction_date FROM transactions
     WHERE portfolio_id = ? AND currency = 'USD' AND fx_rate IS NULL
     ORDER BY transaction_date, id
     ```
   - Use `conn.row_factory = sqlite3.Row` + `dict(row)`, same as
     `get_transactions`.
2. `set_fx_rate(tx_id, fx_rate)`:
   - SQL `UPDATE transactions SET fx_rate = ? WHERE id = ?`.
   - Return `cursor.rowcount > 0` (dumb trusted writer, same shape as
     `set_password`). No portfolio check: the caller selected the id from a
     portfolio it already resolved.
   - Docstring must say this is ONLY for the maintenance backfill and that the
     normal write paths (`add_transaction` / `update_transaction`) still own
     fx_rate derivation.

## 2. app.py — CLI block next to the reset-password CLI (before `main`)

`get_fx_rate_on` is already imported at app.py line 51. Use `db`, `app.logger`.

### 2a. `perform_fx_backfill(user_id)`
Returns a summary dict:
```python
{"fixed": int, "unresolved": [{"ticker": str, "date": str, "reason": str}, ...]}
```
- `summary = {"fixed": 0, "unresolved": []}`.
- For each `p in db.get_portfolios(user_id)`:
  - For each `row in db.get_unrated_usd_transactions(p["id"])`:
    - `try: rate = get_fx_rate_on("USD", "CAD", row["transaction_date"])`.
    - Success → `db.set_fx_rate(row["id"], rate)`; `summary["fixed"] += 1`.
    - `except Exception as exc:` append
      `{"ticker": row["ticker"], "date": row["transaction_date"],
        "reason": str(exc)}`. Do NOT increment fixed.
      - NOTE: catch broadly, exactly like `_derive_fx_rate`, because Yahoo
        raises `KeyError`/network errors as well as `ValueError`.
- After the loops, log ONCE at INFO with NO amounts:
  ```python
  app.logger.info(
      "event=fx_backfill user_id=%d fixed=%d unresolved=%d",
      user_id, summary["fixed"], len(summary["unresolved"]),
  )
  ```
- Return `summary`.

### 2b. `run_backfill_fx_command(target)`
- Build the user list:
  - `target == "--all"` → `users = db.get_users()` (list of `{"id","username"}`).
  - Else → `user = db.get_user_by_username((target or "").strip())`; if `None`:
    `print("No account with that name on this server.", file=sys.stderr)`;
    return `1`. Else `users = [user]`.
- `total_fixed = 0`; `unresolved_lines = []`.
- For each user: `summary = perform_fx_backfill(user["id"])`;
  `total_fixed += summary["fixed"]`;
  print to stdout per user:
  `f"Fixed {summary['fixed']} rate(s) for {user['username']}; "
   f"{len(summary['unresolved'])} could not be resolved."`;
  for each unresolved `u`: append
  `f"Could not resolve: {u['ticker']} {u['date']} ({u['reason']})"`.
- Print each unresolved line to stdout after the per-user lines.
- Return `0`.

### 2c. `_dispatch(argv)` — extend only
Replace the body so it dispatches two commands:
```python
def _dispatch(argv):
    args = argv[1:]
    command = args[0] if args else ""
    if command == "reset-password" and len(args) == 2:
        return run_reset_password_command(args[1])
    if command == "backfill-fx" and len(args) == 2:
        return run_backfill_fx_command(args[1])
    print("usage: python app.py reset-password <username>", file=sys.stderr)
    print("usage: python app.py backfill-fx <username|--all>", file=sys.stderr)
    return 1
```
- `main(argv)` and the `__main__` guard are UNCHANGED.
- The existing `test_main_dispatch_reset_and_usage` still passes: its exact
  string is still printed on the bad-arity reset path.

### 2d. No Docker change
Docker runs `gunicorn app:app`, so the CLI block is unreachable in the
container. `tests/test_docker.py` must stay green untouched.

## 3. NEW tests/tests_fx_backfill.py (write first, all must fail)

Imports:
```python
import logging
import db
import app as app_module
from app import perform_fx_backfill, run_backfill_fx_command
from conftest import seed_user, main_portfolio_id
```
Helpers to define in the file:
- `def add(pid, ticker="AAPL", date="2026-01-02", currency="USD",
   fx_rate=None):` → `db.add_transaction(ticker, date, 10.0, 2.0, currency,
   "BUY", fx_rate, portfolio_id=pid)`; return the new id.
   `db.add_transaction` signature is `(ticker, transaction_date, price, qty,
   currency, transaction_type, fx_rate, fee=None, *, portfolio_id)`; it
   returns `cursor.lastrowid`.

Tests (use `fake_market` for `fx_on`):
`fake_market.fx_on[("USDCAD", date)] = rate` supplies a bar; an ABSENT key
raises (models a Yahoo gap). `fake_market.fx_rates["USDCAD"]` is the live rate.

1. `test_backfill_fills_null_usd_row(fresh_db, fake_market)`:
   - `uid = seed_user("tester")`; `pid = main_portfolio_id(uid)`.
   - `tx_id = add(pid)`; `fake_market.fx_on[("USDCAD","2026-01-02")] = 1.31`.
   - `s = perform_fx_backfill(uid)`.
   - Assert `s["fixed"] == 1`, `s["unresolved"] == []`.
   - Assert `db.get_transaction(tx_id, pid)["fx_rate"] == 1.31`.
2. `test_backfill_ignores_cad_and_rated_rows(fresh_db, fake_market)`:
   - CAD row (`currency="CAD"`, `fx_rate=None`) and USD row with
     `fx_rate=1.25`; plus one NULL USD row with a bar.
   - Assert `s["fixed"] == 1`; CAD row's stored fx_rate is `None` (backfill
     does not invent 1.0 — `db.init`'s migration is a different path);
     rated USD row still `1.25`.
3. `test_backfill_unresolved_stays_null(fresh_db, fake_market)`:
   - One NULL USD row, NO `fx_on` key.
   - Assert `s["fixed"] == 0`, `len(s["unresolved"]) == 1`,
     `s["unresolved"][0]["date"] == "2026-01-02"`; stored rate still `None`.
4. `test_backfill_never_uses_live_rate(fresh_db, fake_market)`:
   - One NULL USD row, NO historical key, but set
     `fake_market.fx_rates["USDCAD"] = 1.40`.
   - Assert `s["fixed"] == 0` and stored rate still `None` (no live fallback).
5. `test_backfill_covers_all_user_portfolios(fresh_db, fake_market)`:
   - `uid`; `pid = main_portfolio_id(uid)`;
     `second = db.create_portfolio("Second", uid)` (returns the new int id).
   - Add a NULL row in each; both bars present. Assert `s["fixed"] == 2`.
6. `test_backfill_scoped_to_one_user(fresh_db, fake_market)`:
   - `a = seed_user("alpha")`, `b = seed_user("bravo")`; row each; bars.
   - `perform_fx_backfill(a)` fixes alpha's; bravo's row still `None`.
7. `test_backfill_all_flag_covers_every_user(fresh_db, fake_market)`:
   - two users with rows, bars present.
   - `run_backfill_fx_command("--all") == 0`; both rows fixed.
8. `test_run_backfill_unknown_user(fresh_db, capsys)`:
   - `run_backfill_fx_command("ghost") == 1`;
     `"No account"` in `capsys.readouterr().err`.
9. `test_run_backfill_prints_counts(fresh_db, fake_market, capsys)`:
   - `seed_user("tester")`; one fixed, one unresolved.
   - return `0`; out contains `"Fixed 1 rate(s) for tester"` and the
     unresolved date string.
10. `test_run_backfill_noop_when_nothing_missing(fresh_db, capsys)`:
    - `seed_user("tester")`; no NULL rows. return `0`; out contains
      `"Fixed 0 rate(s) for tester"`.
11. `test_dispatch_backfill_and_usage(fresh_db, fake_market, capsys)`:
    - `seed_user("tester")`.
    - `app_module.main(["app.py", "backfill-fx", "tester"]) == 0`.
    - `app_module.main(["app.py", "backfill-fx"]) == 1`; stderr contains
      `"usage: python app.py backfill-fx <username|--all>"`.
    - `app_module.main(["app.py", "backfill-fx", "tester", "extra"]) == 1`.
12. `test_backfill_logs_summary_without_amounts(fresh_db, fake_market, caplog)`:
    - one fix; `with caplog.at_level(logging.INFO): perform_fx_backfill(uid)`.
    - some record line contains `"event=fx_backfill"` and `"fixed=1"`;
      `"10.0"` (a price) does NOT appear in `caplog.text`.

If any assertion about a helper's return shape turns out wrong (e.g.
`create_portfolio`), read `db.py` and adjust the TEST, never the contract.

## 4. Order
1. Write ALL failing tests → run `python -m pytest tests/test_fx_backfill.py`
   (expect failures / collection).
2. Implement db.py helpers.
3. Implement app.py `perform_fx_backfill`, `run_backfill_fx_command`,
   `_dispatch`.
4. Run `python -m pytest tests/test_fx_backfill.py` to green.
5. Run the FULL `python -m pytest` (Docker test must stay green).
6. Report; await user commit approval.
