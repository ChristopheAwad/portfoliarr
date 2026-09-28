# tests/test_stock_position.py — roadmap #53 Ticker Page Position Card.
#
# The detail page shows the signed-in person's holding in NATIVE money:
# qty, mean cost, cost, live worth, profit $/%, day move. No FX math.
import pathlib

import pytest

import db
from conftest import make_quote, seed_user


def seed(ticker="AAPL", date="2026-08-01", price=100.0, qty=10,
         tx_type="BUY", currency="USD", fx_rate=1.37, fee=None):
    return db.add_transaction(ticker, date, price, qty, currency,
                              tx_type, fx_rate, fee,
                              portfolio_id=1)


def get(client, symbol_qs):
    return client.get(f"/api/portfolio/position{symbol_qs}")


def test_buy_only_native(client, fake_market):
    seed()
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    resp = get(client, "?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["held"] is True
    assert data["symbol"] == "AAPL"
    assert data["currency"] == "USD"
    assert data["qty"] == pytest.approx(10.0)
    assert data["avg_cost"] == pytest.approx(100.0)
    assert data["cost_basis"] == pytest.approx(1000.0)
    assert data["value"] == pytest.approx(1100.0)
    assert data["gain"] == pytest.approx(100.0)
    assert data["gain_pct"] == pytest.approx(10.0)
    assert data["day_gain"] == pytest.approx(20.0)
    assert data["day_gain_pct"] == pytest.approx(2.0 / 108.0 * 100)
    # Native card makes zero FX calls.
    assert fake_market.fx_rates == {}


def test_partial_sell_keeps_avg(client, fake_market):
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(price=150.0, qty=4, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is True
    assert data["qty"] == pytest.approx(6.0)
    assert data["avg_cost"] == pytest.approx(100.0)
    assert data["cost_basis"] == pytest.approx(400.0)
    assert data["value"] == pytest.approx(660.0)
    assert data["gain"] == pytest.approx(260.0)


def test_full_close_hides(client, fake_market):
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(price=120.0, qty=10, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 130.0, 128.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is False
    assert "qty" not in data


def test_sell_only_short(client, fake_market):
    seed(price=50.0, qty=5, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 45.0, 46.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is True
    assert data["qty"] == pytest.approx(-5.0)
    assert data["avg_cost"] == pytest.approx(50.0)
    assert data["cost_basis"] == pytest.approx(-250.0)
    # Short falls while the market rises: the dollar move and the
    # market % point opposite ways. Both must be served with their
    # own direction (the frontend signs each independently).
    assert data["day_gain"] == pytest.approx(-5.0 * (45.0 - 46.0))
    assert data["day_gain_pct"] == pytest.approx((45.0 - 46.0) / 46.0 * 100)


def test_sell_fee_reduces_cost_basis(client, fake_market):
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(price=150.0, qty=4, tx_type="SELL", fee=8.0)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is True
    assert data["qty"] == pytest.approx(6.0)
    # A sell fee comes off the proceeds: it lowers the cost basis
    # but leaves the remaining pool's average untouched.
    assert data["avg_cost"] == pytest.approx(100.0)
    assert data["cost_basis"] == pytest.approx(10 * 100.0 - 4 * 150.0 + 8.0)


def test_cross_flat_opens_short_at_sell(client, fake_market):
    seed(price=100.0, qty=5, tx_type="BUY")
    seed(price=120.0, qty=8, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 118.0, 119.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["qty"] == pytest.approx(-3.0)
    assert data["avg_cost"] == pytest.approx(120.0)


def test_fee_raises_avg(client, fake_market):
    seed(price=100.0, qty=10, tx_type="BUY", fee=10.0)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["avg_cost"] == pytest.approx(101.0)
    assert data["cost_basis"] == pytest.approx(1010.0)


def test_quote_fail_facts_only(client, fake_market):
    seed()
    # No quote key = Yahoo failure.
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is True
    assert data["qty"] == pytest.approx(10.0)
    assert data["avg_cost"] == pytest.approx(100.0)
    assert data["cost_basis"] == pytest.approx(1000.0)
    assert "price" not in data
    assert "value" not in data
    assert "gain" not in data


def test_missing_symbol_400(client, fake_market):
    assert get(client, "").status_code == 400
    assert get(client, "?symbol=").status_code == 400
    assert get(client, "?symbol=%20%20").status_code == 400


def test_lowercase_symbol_works(client, fake_market):
    seed()
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    data = get(client, "?symbol=aapl").get_json()
    assert data["held"] is True
    assert data["symbol"] == "AAPL"


def test_not_held_hides(client, fake_market):
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 108.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is False


def test_other_user_portfolio_404(client, fake_market):
    seed()
    other_id = seed_user("other-person")
    other_pid = db.get_portfolios(other_id)[0]["id"]
    resp = client.get(
        f"/api/portfolio/position?symbol=AAPL&portfolio_id={other_pid}")
    assert resp.status_code == 404


def test_signed_out_401(fresh_db, fake_market):
    from app import app
    anon = app.test_client()
    assert anon.get("/api/portfolio/position?symbol=AAPL").status_code == 401


def test_dust_is_flat(client, fake_market):
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(price=100.0, qty=10, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 100.0, 99.0, "USD")
    assert get(client, "?symbol=AAPL").get_json()["held"] is False


def test_gain_pct_null_when_cost_not_positive(client, fake_market):
    seed(price=50.0, qty=5, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 45.0, 46.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["gain_pct"] is None


def test_gain_pct_null_when_cost_fully_recovered(client, fake_market):
    # BUY 10@100, SELL 5@200: the sale returned the whole stake, so
    # cost is 0 — no base for a %. Money fields still show.
    seed(price=100.0, qty=10, tx_type="BUY")
    seed(price=200.0, qty=5, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 210.0, 208.0, "USD")
    data = get(client, "?symbol=AAPL").get_json()
    assert data["held"] is True
    assert data["qty"] == pytest.approx(5.0)
    assert data["cost_basis"] == pytest.approx(0.0)
    assert data["gain_pct"] is None
    assert data["gain"] == pytest.approx(5.0 * 210.0 - 0.0)
    assert data["value"] == pytest.approx(5.0 * 210.0)


def test_source_contracts():
    app_src = pathlib.Path("app.py").read_text()
    html = pathlib.Path("templates/stock.html").read_text()
    js = pathlib.Path("static/js/stock.js").read_text()
    assert "/api/portfolio/position" in app_src
    assert "position-card" in html
    assert "refreshPosition" in js
    assert "portfolio_id" in js
    assert "setInterval" not in js
