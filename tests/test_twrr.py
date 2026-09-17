# tests/test_twrr.py — locks for the TIME-WEIGHTED RETURN (TWR)
# feature: the dashboard's "Performance" chart view.
#
# The math (see feature.md): per-bar chaining over the value series with
# cash flows removed.  Portfoliarr has no separate cash account, so
# transactions ARE the cash movements — a BUY injects cash (a positive
# contribution), a SELL withdraws it (a negative one).  The flow is
# folded in the SAME walk that applies shares to net_qty, so flow timing
# and share timing always agree.
#
#   r_i    = (V_i − F_i − V_{i−1}) / V_{i−1}      (flows at bar close)
#   index  = 100 × Π(1 + r_i);  twrr_pct = chained − 1, as a %.
#
# The honesty rules under test:
#   * a deposit at an unchanged price adds ZERO return (its flow exactly
#     cancels the value it brought in);
#   * a deposit AFTER a gain does NOT dilute that gain — the money-
#     weighted cost-basis % would read +33% where TWR honestly says
#     +100%;
#   * a withdrawal (sell) does not fake a loss;
#   * flows follow the SAME absorption rule as shares (a Saturday buy
#     lands on Monday's bar; the first bar's flow is part of the base);
#   * flows are measured in the value series' OWN units — the flat LIVE
#     rate for USD.  A stored-fx flow would leave a phantom FX gain on
#     the buy's bar (the COST side keeps using stored fx; the two sides
#     diverge on purpose, just like the summary strip);
#   * a tx whose value cannot enter the series (dead ticker, missing FX)
#     has its flow excluded too — the MIRROR RULE;
#   * a net-short or emptied base ends the chaining (truncation) — the
#     index is reported WHILE the portfolio had a real, positive base;
#   * nothing computable → index_values null + twrr_pct null (never 0/0).

from datetime import date, timedelta

import pytest

import db
import app as app_module


# ── Local helper ──────────────────────────────────────────────────────

def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD", fx_rate=None):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


# ── The shape of the reply ────────────────────────────────────────────

def test_empty_ledger_shape(client, fake_market):
    """An empty ledger returns the new TWR keys as NULL — "nothing to
    measure" — alongside the empty arrays the frontend already knows."""
    res = client.get("/api/portfolio/history")
    assert res.status_code == 200
    assert res.get_json() == {
        "labels": [], "values": [], "costs": [],
        "index_values": None, "twrr_pct": None,
    }


# ── The motivating cases ──────────────────────────────────────────────

def test_buy_at_unchanged_price_is_zero_twr(client, fake_market):
    """THE user's example: hold $1k of AAPL, buy ANOTHER $1k at an
    unchanged price. A contribution must add ZERO return — its flow
    exactly cancels the value the series added — while a naive
    (last−first)/first would scream 100% (a fake gain).
        08-28: buy 10 @ 100        V = 1000
        08-31: buy 10 @ 100 (flat) V = 2000, F = +1000
        r = (2000 − 1000 − 1000) / 1000 = 0 → index [100, 100]"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["index_values"] == [100.0, 100.0]
    assert body["twrr_pct"] == 0.0


def test_deposit_after_gain_not_diluted(client, fake_market):
    """Deposits must NOT dilute a real run — the whole point of TWR.
    Buy $1k, watch it double, then inject $2k at the doubled price
    (flat thereafter). The money-weighted cost-basis % reads +33%
    (4000 value / 3000 cost); TWR honestly says +100%: the $2k never
    performed, but that must not drag the ORIGINAL gain down.
        08-28: buy 10 @ 100     V = 1000
        09-01: close 200        V = 2000, no flow  → r = +100%
        09-02: buy 10 @ 200     V = 4000, F = +2000 → r = 0
        09-03: flat 200         V = 4000            → r = 0
        index [100, 200, 200, 200], twrr = +100%"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-09-02", qty=10,
                     currency="CAD", price=200.0)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-09-01": 200.0,
        "2026-09-02": 200.0, "2026-09-03": 200.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["index_values"] == [100.0, 200.0, 200.0, 200.0]
    assert body["twrr_pct"] == 100.0


def test_withdrawal_doesnt_look_like_loss(client, fake_market):
    """A withdrawal (sell) must not fake a loss. Selling shares whose
    price has not moved recovers cash that exactly cancels the value it
    removed — the productive base shrinks but the return stays 0%.
        08-28: buy 10 @ 100        V = 1000
        08-31: sell 5 @ 100 (flat) V = 500, F = −500
        09-01: flat               V = 500
        r1 = (500 + 500 − 1000) / 1000 = 0 → index flat 100"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=5,
                     tx_type="SELL", currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0, "2026-09-01": 100.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["index_values"] == [100.0, 100.0, 100.0]
    assert body["twrr_pct"] == 0.0


# ── Flow timing = share timing (the absorption rules) ─────────────────

def test_first_bar_flow_absorbed_into_base(client, fake_market):
    """A flow absorbed at the FIRST bar is part of the base — the series
    starts at the first transaction date, so its value already carries
    the deposit. Removing it again would double-report the return.
        08-28: buy 10 @ 100 → closes 100→110 → V [1000, 1100]
        F_0 ignored → r = (1100 − 1000)/1000 = +10% → index [100, 110]"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["index_values"] == pytest.approx([100.0, 110.0])
    assert body["twrr_pct"] == pytest.approx(10.0)


def test_weekend_buy_flow_lands_next_bar(client, fake_market):
    """A Saturday buy lands on MONDAY's bar for its flow AND its shares
    (the same pointer rule the qty fold uses) — a weekend contribution
    cannot leak into Friday's return.
        08-27 buy 5 @ 100; 08-29 (Sat) buy 5 @ 100
        labels 08-28, 08-31; V [500, 1000]; F_31 = +500
        r = (1000 − 500 − 500)/500 = 0 → flat index"""
    seed_transaction(ticker="AAPL", date="2026-08-27", qty=5,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-29", qty=5,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["index_values"] == [100.0, 100.0]
    assert body["twrr_pct"] == 0.0


# ── The FX divergence (flows vs costs, live vs stored) ─────────────────

def test_usd_flow_uses_live_rate_not_stored_fx(client, fake_market):
    """THE differentiator: flows are measured in the value series' OWN
    units — the flat LIVE rate — so removing a USD buy's principal
    exactly cancels what the series added. The COST side keeps its
    stored frozen rate. Both are correct; they answer different
    questions, and the divergence is under test.
        stored fx = 1.4 (the frozen fact, for COSTS), live USDCAD = 1.5
        08-28 buy 10 @ 100: value 10×100×1.5 = 1500, cost 10×100×1.4 = 1400
        08-31 buy 10 @ 100: value 20×100×1.5 = 3000, cost 2800,
                            F = +10×100×1.5 = 1500 (LIVE)
        r = (3000 − 1500 − 1500)/1500 = 0 → flat index, twrr = 0
        (a stored-fx flow of 1400 would compute r = +6.7% — the phantom
        FX gain this test exists to forbid.)"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0,
    }
    fake_market.fx_rates["USDCAD"] = 1.5

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [1500.0, 3000.0]   # live rate
    assert body["costs"] == [1400.0, 2800.0]    # stored rate
    assert body["index_values"] == [100.0, 100.0]
    assert body["twrr_pct"] == 0.0


# ── The mirror rule (no value in the series → no flow out) ─────────────

def test_usd_flow_excluded_when_no_live_rate(client, fake_market):
    """No live USDCAD answer → the USD ticker's value cannot enter the
    series, so its flow must NOT be removed either (removing a principal
    that never entered would fake a loss). All-zero values → no positive
    base → null index, null pct. Never 0/0. (Costs still count the
    stored fact — that side is unaffected by FX availability.)"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    # No fx_rates["USDCAD"] → live_rate unavailable

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [0.0, 0.0]          # value side: 0
    assert body["costs"] == [1400.0, 1400.0]     # cost side: frozen fact
    assert body["index_values"] is None
    assert body["twrr_pct"] is None


def test_dead_ticker_flow_excluded_mirror_rule(client, monkeypatch):
    """The mirror rule against a dead ticker: BAD's history fetch raises
    → it contributes 0 to values AND its buy contributes 0 to flows.
    Removing a flow for value that never entered the series would fake a
    loss. TWR therefore computes over AAPL alone.
        AAPL: values [1100, 1200]; BAD: value 0 AND flow 0
        r = (1200 − 1100)/1100 ≈ 9.09% → index ≈ [100, 109.09]"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="BAD", date="2026-08-28", qty=10,
                     currency="CAD")

    def fake_get_history(symbol, period):
        if symbol == "BAD":
            raise ValueError("delisted (fake)")
        return {"2026-08-28": 110.0, "2026-08-31": 120.0}

    monkeypatch.setattr(app_module, "get_history", fake_get_history)

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [1100.0, 1200.0]
    assert body["costs"] == [2000.0, 2000.0]     # cost keeps BAD — a fact
    assert body["index_values"] == pytest.approx(
        [100.0, 100.0 + 100.0 / 11.0])
    assert body["twrr_pct"] == pytest.approx(100.0 / 11.0)


def test_delisted_before_window_flow_excluded(client, fake_market):
    """The mirror rule, second hole: a ticker whose history is NON-EMPTY
    but entirely BEFORE the label window (delisted before the chart
    starts; another holding anchors the labels). Its bars are all trimmed
    away, so it contributes 0 to values — its buy must contribute 0 to
    flows too, or the "returned" money fakes a loss (measured −40% on a
    true +10% portfolio against the buggy build).
        AAPL: buy 10 @ 100 on 09-01, price 100 → 110
        DEAD: buy 10 @ 50  on 09-03, delisted 08-26 (pre-window history)
        buggy: r_09-03 = (1100 − 500 − 1100)/1100 → index dips to 60
        fixed: DEAD never flowable → index [100, 110, 110, 110] = +10%"""
    seed_transaction(ticker="AAPL", date="2026-09-01", qty=10,
                     currency="CAD")
    seed_transaction(ticker="DEAD", date="2026-09-03", price=50.0, qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-09-01": 100.0, "2026-09-02": 110.0,
        "2026-09-03": 110.0, "2026-09-04": 110.0,
    }
    # Non-empty history — but every bar predates the window's first
    # label (09-01, the first transaction's date).
    fake_market.histories["DEAD"] = {
        "2026-08-25": 60.0, "2026-08-26": 60.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-09-01", "2026-09-02",
                              "2026-09-03", "2026-09-04"]
    assert body["values"] == [1000.0, 1100.0, 1100.0, 1100.0]
    assert body["costs"] == [1000.0, 1000.0, 1500.0, 1500.0]  # paid = fact
    assert body["index_values"] == pytest.approx(
        [100.0, 110.0, 110.0, 110.0])
    assert body["twrr_pct"] == pytest.approx(10.0)


# ── Truncation (honest degradation) ───────────────────────────────────

def test_short_truncates_index(client, fake_market):
    """An oversell opens a short (negative net qty) → the series turns
    negative → chaining STOPS at the first non-positive base, leaving a
    TRUNCATED index (shorter than labels). Performance is reported WHILE
    the portfolio had a real, positive base — never a sign-flipped fake.
        08-28 buy  5 @ 100          V = 500
        09-01 sell 10 @ 100         V = −500, F = −1000
        r_09-01 = (−500 + 1000 − 500)/500 = 0  (base still 500 > 0)
        next base −500 ≤ 0 → STOP. index [100, 100, 100] over 4 labels."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=5,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-09-01", qty=10,
                     tx_type="SELL", currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0,
        "2026-09-01": 100.0, "2026-09-02": 100.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31",
                              "2026-09-01", "2026-09-02"]
    assert body["index_values"] == [100.0, 100.0, 100.0]  # truncated
    assert len(body["index_values"]) < len(body["labels"])
    assert body["twrr_pct"] == 0.0


def test_all_unpriced_nulls_index(client, monkeypatch):
    """The ONLY ticker's history fetch fails → the label union is empty,
    so the route returns EMPTY arrays (same shape as an empty ledger) and
    the TWR keys are null — nothing to measure, never a 0/0 NaN."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")

    def fake_get_history(symbol, period):
        raise ValueError("delisted (fake)")

    monkeypatch.setattr(app_module, "get_history", fake_get_history)

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == []
    assert body["costs"] == []
    assert body["index_values"] is None
    assert body["twrr_pct"] is None


def test_all_unpriced_intraday_returns_empty_shape(client, monkeypatch):
    """The 1D path must handle an empty label union just like daily paths."""
    seed_transaction(ticker="AAPL", date=date.today().isoformat(), qty=10,
                     currency="CAD")

    def fake_get_history(symbol, period):
        raise ValueError("delisted (fake)")

    monkeypatch.setattr(app_module, "get_history", fake_get_history)
    res = client.get("/api/portfolio/history?period=1D")
    assert res.status_code == 200
    assert res.get_json() == {
        "labels": [], "values": [], "costs": [],
        "index_values": None, "twrr_pct": None,
    }


# ── Intraday (1D) degenerates naturally ───────────────────────────────

def test_1d_degenerates_to_simple_return(client, fake_market):
    """Intraday (1D): every transaction applies at today's FIRST bar, so
    all flows land on bar 0 and are absorbed into the base — TWR
    degenerates to the simple rebased return with ZERO special-casing.
        10 @ 100 today; intraday closes 100→110 → index [100, 110]"""
    today = date.today().isoformat()
    seed_transaction(ticker="AAPL", date=today, qty=10, currency="CAD")
    fake_market.histories["AAPL"] = {"09:30": 100.0, "09:35": 110.0}

    body = client.get("/api/portfolio/history?period=1D").get_json()
    assert body["index_values"] == pytest.approx([100.0, 110.0])
    assert body["twrr_pct"] == pytest.approx(10.0)


# ── Regression: the shipped value/cost math is undisturbed ────────────

def test_values_and_costs_unchanged(client, fake_market):
    """The TWR work must NOT disturb the shipped value and cost
    arithmetic — two tickers, exact floats, as a multi-ticker base the
    index chains over.
        AAPL 10 @ 100, MSFT 5 @ 200 (both 08-28, absorbed into bar 0)
        values [2000, 2150]; costs [2000, 2000]
        r = (2150 − 2000)/2000 = +7.5% → index [100, 107.5]"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="MSFT", date="2026-08-28", qty=5,
                     currency="CAD", price=200.0)
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    fake_market.histories["MSFT"] = {
        "2026-08-28": 200.0, "2026-08-31": 210.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [2000.0, 2150.0]
    assert body["costs"] == [2000.0, 2000.0]
    assert body["index_values"] == [100.0, 107.5]
    assert body["twrr_pct"] == pytest.approx(7.5)
