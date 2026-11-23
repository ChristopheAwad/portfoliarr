# tests/test_portfolio_history_availability.py
# ============================================
# The /api/portfolio/history AVAILABILITY contract.
#
# A 200 does not always mean the chart is complete: a held position whose
# price (or CAD conversion) is unavailable at a retained point still lets
# the route return the old payload, but the reply must SAY it is degraded.
# The additive `valuation_status` key is:
#   "partial"     — some relevant position priced, some did not
#   "unavailable" — nothing relevant priced at any retained point
#   absent        — complete, or a genuinely empty chart
# Degraded replies also carry Cache-Control: no-store; complete and
# genuine-empty replies keep their existing headers.

import math

import pytest

import app as app_module
import db


def seed_transaction(ticker="AAPL", date="2026-08-28", price=100.0,
                     qty=10, tx_type="BUY", currency="CAD", fx_rate=None):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate, portfolio_id=1)


def history(client, path="/api/portfolio/history?period=5D"):
    return client.get(path)


def assert_complete(res, body):
    """The old payload, no status key, and no degraded-cache header."""
    assert res.status_code == 200
    assert "valuation_status" not in body
    assert "Cache-Control" not in res.headers


def assert_degraded(res, body, status):
    """The old payload PLUS the additive status and no-store header."""
    assert res.status_code == 200
    assert body["valuation_status"] == status
    assert res.headers.get("Cache-Control") == "no-store"


# ── Empty charts: the triage that keeps "genuinely empty" distinct ────

def test_empty_ledger_is_genuine_empty(client, fake_market):
    """No ledger rows = ordinary empty, not a valuation failure."""
    res = history(client)
    body = res.get_json()
    assert body == {
        "labels": [], "values": [], "costs": [],
        "index_values": None, "twrr_pct": None,
    }
    assert_complete(res, body)


def test_future_only_ledger_with_healthy_bars_is_genuine_empty(
        client, fake_market):
    """Every transaction is in 2099: nothing has happened yet, so the
    empty chart is genuine even though the fetched bars are healthy."""
    seed_transaction(date="2099-01-01")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }

    res = history(client)
    body = res.get_json()
    assert body == {
        "labels": [], "values": [], "costs": [],
        "index_values": None, "twrr_pct": None,
    }
    assert_complete(res, body)


def test_future_only_ledger_with_missing_history_is_genuine_empty(
        client, fake_market):
    """No labels at all, but every transaction is future: still genuine."""
    seed_transaction(date="2099-01-01")
    # AAPL deliberately absent -> get_history raises (missing provider).

    res = history(client)
    body = res.get_json()
    assert body == {
        "labels": [], "values": [], "costs": [],
        "index_values": None, "twrr_pct": None,
    }
    assert_complete(res, body)


def test_trimmed_axis_with_missing_recent_history_is_unavailable(
        client, fake_market):
    """Healthy bars exist only BEFORE the first investment, so the trim
    leaves no labels. A second ticker has no history at all and a
    transaction on/before today: the empty reply is unavailable."""
    seed_transaction(ticker="AAPL", date="2026-08-21")
    seed_transaction(ticker="MISSING", date="2026-08-28", qty=5)
    fake_market.histories["AAPL"] = {"2026-08-20": 100.0}
    # MISSING deliberately absent -> get_history raises.

    res = history(client)
    body = res.get_json()
    assert body["labels"] == []
    assert body["values"] == []
    assert body["index_values"] is None
    assert body["twrr_pct"] is None
    assert_degraded(res, body, "unavailable")


# ── Complete portfolios ───────────────────────────────────────────────

def test_complete_cad_portfolio_has_no_status(client, fake_market):
    """Every held position prices at every retained label: no status."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    seed_transaction(ticker="RY.TO", date="2026-08-28", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    fake_market.histories["RY.TO"] = {
        "2026-08-28": 50.0, "2026-08-31": 52.0,
    }

    res = history(client)
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1500.0, 1620.0]
    assert_complete(res, body)


def test_holiday_forward_fill_stays_complete(client, fake_market):
    """A normal holiday/missing bar is forward-filled, not degraded."""
    seed_transaction(ticker="AAPL", date="2026-08-27", qty=1)
    seed_transaction(ticker="RY.TO", date="2026-08-27", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    fake_market.histories["RY.TO"] = {
        "2026-08-27": 50.0, "2026-08-31": 52.0,   # 08-28 holiday
    }

    res = history(client)
    body = res.get_json()
    assert body["values"] == [600.0, 610.0, 640.0]
    assert_complete(res, body)


# ── Partial: at least one relevant position still priced ──────────────

def test_one_missing_ticker_is_partial(client, fake_market):
    """One dead ticker still contributes 0, but the healthy ticker keeps
    the line alive: the chart is usable but incomplete."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    seed_transaction(ticker="BAD", date="2026-08-28", qty=5)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }   # "BAD" absent -> its history fetch fails

    res = history(client)
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 1100.0]
    assert set(body) == {
        "labels", "values", "costs", "index_values", "twrr_pct",
        "valuation_status",
    }
    assert_degraded(res, body, "partial")


def test_usd_without_fx_with_cad_companion_is_partial(client, fake_market):
    """A USD holding with no live rate is unpriced; the CAD companion
    carries the line, so the result is partial (not unavailable)."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    seed_transaction(ticker="RY.TO", date="2026-08-28", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    fake_market.histories["RY.TO"] = {
        "2026-08-28": 50.0, "2026-08-31": 52.0,
    }
    # fx_rates deliberately empty -> no live USDCAD rate.

    res = history(client)
    body = res.get_json()
    assert body["values"] == [500.0, 520.0]
    assert_degraded(res, body, "partial")


def test_unsupported_currency_is_partial_when_another_position_prices(
        client, fake_market):
    """EUR has no CAD conversion path, so it is unpriced; the CAD line
    keeps the chart usable -> partial."""
    seed_transaction(ticker="RY.TO", date="2026-08-28", qty=10)
    seed_transaction(ticker="EURGD", date="2026-08-28", qty=5,
                     currency="EUR")
    fake_market.histories["RY.TO"] = {
        "2026-08-28": 50.0, "2026-08-31": 52.0,
    }
    fake_market.histories["EURGD"] = {
        "2026-08-28": 10.0, "2026-08-31": 11.0,
    }

    res = history(client)
    body = res.get_json()
    assert body["values"] == [500.0, 520.0]
    assert_degraded(res, body, "partial")


def test_non_empty_history_that_never_resolves_while_held_is_partial(
        client, fake_market):
    """GAP has a non-empty history, but every bar predates the buy and is
    trimmed. It never resolves while held, so the response is partial."""
    seed_transaction(ticker="GAP", date="2026-08-28", qty=10)
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    fake_market.histories["GAP"] = {"2026-08-20": 10.0}   # before the buy
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }

    res = history(client)
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 1100.0]
    assert_degraded(res, body, "partial")


# ── Unavailable: nothing relevant prices at any retained point ────────

def test_usd_without_fx_is_unavailable(client, fake_market):
    """The only holding is USD with no rate: it never prices."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    # fx_rates deliberately empty.

    res = history(client)
    body = res.get_json()
    assert body["values"] == [0.0, 0.0]
    assert_degraded(res, body, "unavailable")


@pytest.mark.parametrize(
    "bad_rate",
    [0.0, float("inf"), float("-inf"), float("nan")],
)
def test_usd_with_unusable_live_rate_is_unavailable(
        client, fake_market, monkeypatch, bad_rate):
    """A zero or non-finite live rate cannot convert the only holding,
    so it must contribute 0 instead of a 0/NaN/Inf "CAD" value."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: bad_rate)

    res = history(client)
    body = res.get_json()
    assert res.status_code == 200
    assert body["values"] == [0.0, 0.0]
    assert all(math.isfinite(value) for value in body["values"])
    assert_degraded(res, body, "unavailable")


def test_all_relevant_positions_unpriced_is_unavailable(
        client, fake_market):
    """A retained axis exists, but the held positions are a data-gap CAD
    ticker and an unsupported EUR ticker: nothing prices."""
    seed_transaction(ticker="GAP", date="2026-08-28", qty=10)
    seed_transaction(ticker="EURGD", date="2026-08-28", qty=5,
                     currency="EUR")
    fake_market.histories["GAP"] = {"2026-08-20": 10.0}   # before the buy
    fake_market.histories["EURGD"] = {
        "2026-08-28": 10.0, "2026-08-31": 11.0,
    }

    res = history(client)
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [0.0, 0.0]
    assert_degraded(res, body, "unavailable")


@pytest.mark.parametrize("missing_mode", ["empty_result", "exception"])
def test_missing_market_axis_with_recent_tx_is_unavailable(
        client, fake_market, missing_mode):
    """No labels because every history fetch is empty (or raises), and a
    transaction is on/before today: without an axis we cannot judge the
    window, so the genuinely-shaped empty chart is unavailable."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    if missing_mode == "empty_result":
        fake_market.histories["AAPL"] = {}
    # exception mode leaves AAPL out -> get_history raises.

    res = history(client)
    body = res.get_json()
    assert body["labels"] == []
    assert body["values"] == []
    assert body["index_values"] is None
    assert body["twrr_pct"] is None
    assert_degraded(res, body, "unavailable")


# ── Things that must NOT degrade the valuation ────────────────────────

def test_unrelated_fx_failure_does_not_degrade_cad_only(
        client, fake_market):
    """A closed USD position makes the route attempt the live FX lookup,
    but no relevant position needs it. Its failure must not mark the
    complete CAD chart as degraded."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    seed_transaction(ticker="OLD", date="2026-08-20", qty=10,
                     currency="USD", fx_rate=1.4)
    seed_transaction(ticker="OLD", date="2026-08-21", qty=10,
                     tx_type="SELL", currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    # OLD has no history and fx_rates is empty -> both lookups fail.

    res = history(client)
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 1100.0]
    assert_complete(res, body)


def test_closed_position_outside_the_window_does_not_degrade(
        client, fake_market):
    """A position bought and sold before the retained window is not
    relevant, even when its history is missing."""
    seed_transaction(ticker="CLOSED", date="2026-08-01", qty=5)
    seed_transaction(ticker="CLOSED", date="2026-08-02", qty=5,
                     tx_type="SELL")
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    # CLOSED deliberately absent -> missing, but quantity is 0 everywhere.

    res = history(client)
    body = res.get_json()
    assert body["values"] == [1000.0, 1100.0]
    assert_complete(res, body)


def test_benchmark_error_does_not_degrade_the_portfolio(
        client, fake_market):
    """A benchmark's missing history is its own error field; the complete
    portfolio line keeps its normal shape and headers."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    # SPY is absent -> benchmark-only failure.

    res = client.get("/api/portfolio/history?period=5D&benchmark=SPY")
    body = res.get_json()
    assert body["benchmarks"][0]["symbol"] == "SPY"
    assert body["benchmarks"][0]["error"] is not None
    assert body["values"] == [1000.0, 1100.0]
    assert_complete(res, body)


# ── The same-day new-position deferral exception ──────────────────────

def test_same_day_new_position_deferral_is_not_degraded(
        client, fake_market):
    """NEW is bought on the same date as the first retained intraday bar,
    but its first bar is the later bar on THAT SAME date. That is the
    walk's intentional deferral, not a degraded valuation."""
    seed_transaction(ticker="OLD", date="2026-08-27", qty=1)
    seed_transaction(ticker="NEW", date="2026-08-28", qty=2)
    fake_market.histories["OLD"] = {
        "2026-08-28 09:30": 100.0, "2026-08-28 09:35": 101.0,
    }
    fake_market.histories["NEW"] = {"2026-08-28 09:35": 50.0}

    res = history(client, "/api/portfolio/history?period=1D")
    body = res.get_json()
    assert body["labels"] == ["2026-08-28 09:30", "2026-08-28 09:35"]
    assert body["values"] == [100.0, 1 * 101.0 + 2 * 50.0]
    assert_complete(res, body)


def test_same_day_new_position_without_a_same_day_bar_is_partial(
        client, fake_market):
    """The deferral exception is narrow: NEW's first bar is the NEXT
    trading day, so the first retained bar genuinely cannot price it."""
    seed_transaction(ticker="OLD", date="2026-08-27", qty=1)
    seed_transaction(ticker="NEW", date="2026-08-28", qty=2)
    fake_market.histories["OLD"] = {"2026-08-28 09:30": 100.0}
    fake_market.histories["NEW"] = {"2026-08-31 09:30": 50.0}

    res = history(client, "/api/portfolio/history?period=1D")
    body = res.get_json()
    assert body["labels"] == ["2026-08-28 09:30", "2026-08-31 09:30"]
    assert_degraded(res, body, "partial")
