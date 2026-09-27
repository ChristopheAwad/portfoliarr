# tests/test_fx_backfill.py
# =========================
# The `python app.py backfill-fx <username|--all>` maintenance command:
# it finds USD transactions whose STORED fx_rate is NULL, re-derives the
# historical USDCAD close on each row's own date, writes it back, and
# reports fixed/unresolved counts. It is HISTORICAL-ONLY: no live-rate
# fallback, so a date with no bar stays NULL. No network is touched —
# fake_market stands in for Yahoo.

import logging

import db
import app as app_module
from app import perform_fx_backfill, run_backfill_fx_command
from conftest import seed_user, main_portfolio_id


def add(pid, ticker="AAPL", date="2026-01-02", currency="USD", fx_rate=None):
    """Insert one BUY row with the given stored rate (None = unrated)."""
    return db.add_transaction(
        ticker, date, 10.0, 2.0, currency, "BUY", fx_rate,
        portfolio_id=pid,
    )


def test_backfill_fills_null_usd_row(fresh_db, fake_market):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    tx_id = add(pid)
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    summary = perform_fx_backfill(uid)

    assert summary["fixed"] == 1
    assert summary["unresolved"] == []
    assert db.get_transaction(tx_id, pid)["fx_rate"] == 1.31


def test_backfill_ignores_cad_and_rated_rows(fresh_db, fake_market):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    cad_id = add(pid, ticker="SHOP", currency="CAD", fx_rate=None)
    rated_id = add(pid, ticker="MSFT", fx_rate=1.25)
    null_id = add(pid, ticker="AAPL")
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    summary = perform_fx_backfill(uid)

    assert summary["fixed"] == 1
    assert db.get_transaction(cad_id, pid)["fx_rate"] is None
    assert db.get_transaction(rated_id, pid)["fx_rate"] == 1.25
    assert db.get_transaction(null_id, pid)["fx_rate"] == 1.31


def test_backfill_unresolved_stays_null(fresh_db, fake_market):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    tx_id = add(pid)

    summary = perform_fx_backfill(uid)

    assert summary["fixed"] == 0
    assert len(summary["unresolved"]) == 1
    assert summary["unresolved"][0]["date"] == "2026-01-02"
    assert db.get_transaction(tx_id, pid)["fx_rate"] is None


def test_backfill_never_uses_live_rate(fresh_db, fake_market):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    tx_id = add(pid)
    fake_market.fx_rates["USDCAD"] = 1.40

    summary = perform_fx_backfill(uid)

    assert summary["fixed"] == 0
    assert db.get_transaction(tx_id, pid)["fx_rate"] is None


def test_backfill_covers_all_user_portfolios(fresh_db, fake_market):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    second = db.create_portfolio("Second", uid)
    add(pid, ticker="AAPL")
    add(second, ticker="MSFT")
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    summary = perform_fx_backfill(uid)

    assert summary["fixed"] == 2


def test_backfill_scoped_to_one_user(fresh_db, fake_market):
    alpha = seed_user("alpha")
    bravo = seed_user("bravo")
    alpha_pid = main_portfolio_id(alpha)
    bravo_pid = main_portfolio_id(bravo)
    alpha_tx = add(alpha_pid)
    bravo_tx = add(bravo_pid)
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    summary = perform_fx_backfill(alpha)

    assert summary["fixed"] == 1
    assert db.get_transaction(alpha_tx, alpha_pid)["fx_rate"] == 1.31
    assert db.get_transaction(bravo_tx, bravo_pid)["fx_rate"] is None


def test_backfill_all_flag_covers_every_user(fresh_db, fake_market):
    alpha = seed_user("alpha")
    bravo = seed_user("bravo")
    alpha_tx = add(main_portfolio_id(alpha))
    bravo_tx = add(main_portfolio_id(bravo))
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    assert run_backfill_fx_command("--all") == 0

    assert db.get_transaction(alpha_tx, main_portfolio_id(alpha))["fx_rate"] == 1.31
    assert db.get_transaction(bravo_tx, main_portfolio_id(bravo))["fx_rate"] == 1.31


def test_run_backfill_unknown_user(fresh_db, capsys):
    assert run_backfill_fx_command("ghost") == 1
    assert "No account" in capsys.readouterr().err


def test_run_backfill_prints_counts(fresh_db, fake_market, capsys):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    add(pid, ticker="AAPL")
    add(pid, ticker="MSFT", date="2026-03-04")
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    assert run_backfill_fx_command("tester") == 0

    out = capsys.readouterr().out
    assert "Fixed 1 rate(s) for tester" in out
    assert "2026-03-04" in out


def test_run_backfill_noop_when_nothing_missing(fresh_db, capsys):
    seed_user("tester")

    assert run_backfill_fx_command("tester") == 0

    assert "Fixed 0 rate(s) for tester" in capsys.readouterr().out


def test_dispatch_backfill_and_usage(fresh_db, fake_market, capsys):
    seed_user("tester")

    assert app_module.main(["app.py", "backfill-fx", "tester"]) == 0
    assert app_module.main(["app.py", "backfill-fx"]) == 1
    assert ("usage: python app.py backfill-fx <username|--all>"
            in capsys.readouterr().err)
    assert app_module.main(["app.py", "backfill-fx", "tester", "extra"]) == 1


def test_backfill_logs_summary_without_amounts(fresh_db, fake_market, caplog):
    uid = seed_user("tester")
    pid = main_portfolio_id(uid)
    add(pid)
    fake_market.fx_on[("USDCAD", "2026-01-02")] = 1.31

    with caplog.at_level(logging.INFO):
        perform_fx_backfill(uid)

    assert any("event=fx_backfill" in record.getMessage()
               and "fixed=1" in record.getMessage()
               for record in caplog.records)
    assert "10.0" not in caplog.text
