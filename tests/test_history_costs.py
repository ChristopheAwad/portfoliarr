# tests/test_history_costs.py — locks for the cost-basis / gain tooltip
# on the portfolio history chart.
#
# The cost basis is netted contributions: buys PAID minus sells
# RECOUPED — the same definition as /api/portfolio/summary's cost_basis.
# The value side of the chart uses live FX rates; the cost side uses each
# transaction's STORED fx_rate (a frozen fact).  This deliberate
# divergence mirrors the summary strip and is tested explicitly.

from datetime import date, timedelta

import pytest

import db
import app as app_module
from app import app


# ── Local helper ──────────────────────────────────────────────────────

def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD", fx_rate=None):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate, portfolio_id=1)


# ── Empty / shape tests ───────────────────────────────────────────────

def test_history_costs_empty_ledger(client, fake_market):
    """An empty ledger returns costs alongside labels and values —
    the frontend needs all three arrays to have the same length."""
    res = client.get("/api/portfolio/history")
    assert res.status_code == 200
    assert res.get_json() == {
        "labels": [], "values": [], "costs": [],
        # TWR keys: null here — nothing to measure (never 0/0).
        "index_values": None, "twrr_pct": None,
    }


def test_costs_length_matches_labels(client, fake_market):
    """The costs array must be the same length as labels for every
    period — the frontend indexes into them by position."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert len(body["costs"]) == len(body["labels"])


# ── Cost constant between buys ────────────────────────────────────────

def test_costs_constant_between_buys(client, fake_market):
    """Cost is what was PAID, not what it's worth — the cost line stays
    flat between transactions even as the value line moves with prices.
        08-28: buy 10 @ 100 → cost 1000, value 10 × 110 = 1100
        08-31: still same buys → cost 1000, value 10 × 120 = 1200
    (CAD row — no FX work needed.)"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["costs"] == [1000.0, 1000.0]


# ── Sell netting ──────────────────────────────────────────────────────

def test_sell_nets_cost_basis(client, fake_market):
    """Sells subtract what they RECOUPED from the cost basis — the same
    netting the summary strip uses.  After the sell the cost drops:
        08-28: buy 10 @ 100          → cost 1000
        08-31: sell 4 @ 120 (CAD)   → cost 1000 − 480 = 520"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=4,
                     tx_type="SELL", currency="CAD", price=120.0)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["costs"] == [1000.0, 520.0]


# ── USD stored-fx vs live-fx (the differentiator) ────────────────────

def test_usd_cost_uses_stored_fx_not_live(client, fake_market):
    """THE key divergence: the value side uses the FLAT LIVE rate; the
    cost side uses the transaction's STORED fx_rate.  Both are correct
    but different — this is the test that locks the distinction.
        stored fx_rate = 1.4, live USDCAD = 1.5
        cost  = 10 × 100 × 1.4 = 1400 (frozen fact)
        value = 10 × 110 × 1.5 = 1650 (live rate)"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    fake_market.fx_rates["USDCAD"] = 1.5

    body = client.get("/api/portfolio/history?period=5D").get_json()
    # Cost: 10 × 100 × 1.4 = 1400 (stored), constant across both bars
    assert body["costs"] == [1400.0, 1400.0]
    # Value: 10 × 110 × 1.5 = 1650, 10 × 120 × 1.5 = 1800 (live)
    assert body["values"] == [1650.0, 1800.0]


# ── NULL-fx fallback (pre-feature rows) ───────────────────────────────

def test_null_fx_usd_row_falls_back_to_live_rate(client, fake_market):
    """Pre-feature USD rows carry fx_rate = None — their rate is genuinely
    unknown.  The cost side falls back to the live rate (the same
    per-request fallback the summary strip uses).  With live USDCAD = 1.6:
        cost = 10 × 100 × 1.6 = 1600"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=None)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    fake_market.fx_rates["USDCAD"] = 1.6

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["costs"] == [1600.0, 1600.0]


def test_null_fx_usd_row_live_rate_down_contributes_zero_cost(
        client, fake_market):
    """When fx_rate is None AND no USDCAD answer is available, that
    unrated row contributes 0 to cost — never a fake 1:1 rate.  This
    matches the value side's own zero-contribution rule."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=None)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    # No fx_rates["USDCAD"] set → live_rate unavailable → 0 contribution

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["costs"] == [0.0, 0.0]


# ── Negative cost from oversell (short) ───────────────────────────────

def test_oversell_negative_cost_is_honest(client, fake_market):
    """A short position's netted cost goes negative — the sell recoups
    MORE than was ever paid.  This matches test_portfolio_summary's
    negative-cost-basis semantics (no clamping).
        08-28: buy  5 @ 100          → cost 500
        08-31: sell 10 @ 120 (CAD)   → cost 500 − 1200 = −700"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=5,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=10,
                     tx_type="SELL", currency="CAD", price=120.0)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["costs"] == [500.0, -700.0]


# ── Intraday: walked-in cost applies at first bar ─────────────────────

def test_intraday_1d_walked_in_cost_applies_at_first_bar(client, fake_market):
    """The intraday (1D) branch: both a PAST buy and today's buy fold
    into the cost at today's FIRST bar (the same first-bar application
    as net_qty).  Cost then stays flat across the remaining bars.
        past buy  10 @ 100    (CAD)
        today buy  2 @ 120    (CAD)
        cost = 1000 + 240 = 1240 at every bar"""
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    seed_transaction(ticker="AAPL", date=yesterday, qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date=today, qty=2,
                     currency="CAD", price=120.0)
    fake_market.histories["AAPL"] = {"09:30": 150.0, "09:35": 151.0}

    body = client.get("/api/portfolio/history?period=1D").get_json()
    # Cost = 10 × 100 (past) + 2 × 120 (today) = 1240, flat
    assert body["costs"] == [1240.0, 1240.0]


# ── Saturday buy lands next trading bar ───────────────────────────────

def test_saturday_buy_applies_cost_next_trading_label(client, fake_market):
    """A buy dated a non-trading day folds its cost at the NEXT trading
    bar — the same transaction-pointer rule the net_qty fold uses.  The
    Saturday buy is invisible on Friday's bar but lands on Monday.
        08-27: buy 5 @ 100          → cost 500 at 08-28
        08-29 (Saturday): buy 5 @ 100 → lands at 08-31 → cost 1000
    (An earlier 08-27 buy keeps the 08-28 bar alive — the axis trims
    everything BEFORE the first logged investment, so a Saturday FIRST
    buy would have no "before" bar to assert on.)"""
    seed_transaction(ticker="AAPL", date="2026-08-27", qty=5,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-29", qty=5,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    body = client.get("/api/portfolio/history?period=5D").get_json()
    # Friday 08-28: only the 08-27 buy (5 × 100) → cost 500
    # Monday 08-31: Saturday buy lands (5 × 100) → 500 + 500 = 1000
    assert body["costs"] == [500.0, 1000.0]
