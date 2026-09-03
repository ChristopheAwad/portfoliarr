# tests/test_portfolio_summary.py
# =================================
# Route tests for GET /api/portfolio/summary — the portfolio header's
# three live numbers (total value, day change, total return).
#
# Same concepts as test_routes.py (read its banner first):
#   - the Flask TEST CLIENT (conftest.py) — real routes, no network
#   - MOCKING with the golden rule "patch where it's USED": app.py did
#     `from market_data import get_quote`, so we patch app.get_quote.
#     The patch is a dict lookup — a ticker missing from the dict raises
#     KeyError, which is exactly how an unquotable/dead ticker behaves.
#   - the throwaway DB (fresh_db, via client) — seeded through the db
#     layer's add_transaction, never raw SQL.
#
# THE CONTRACTS UNDER TEST HERE:
#   - the math: value / day gain / cost basis / their percentages
#   - netting: a SELL subtracts proceeds from cost basis, which is how
#     realized gains blend with unrealized ones in total_gain
#   - resilience: an unpriced ticker is excluded from EVERY sum and
#     reported in "unpriced" — never a 500, never a half-priced mix
#   - normal states: empty ledger and fully-sold portfolios return
#     zeros with null percentages, not errors
#   - the documented temporary decision: currencies sum as-is (no FX)

import pytest

import db

# NAME-COLLISION SUBTLETY (see test_routes.py banner): `from app import
# app` binds the Flask object; the routes look up get_quote in the
# MODULE's namespace, so that's the name we must patch.
import app as app_module


# ── Helpers & fixtures ────────────────────────────────────────────────

def make_quote(symbol, price, previous_close, currency="USD"):
    """Build a quote dict in exactly the shape market_data.get_quote
    returns (raw floats + derived day-move numbers)."""
    return {
        "symbol": symbol,
        "price": price,
        "previous_close": previous_close,
        "currency": currency,
        "change": price - previous_close,
        "change_pct": (price - previous_close) / previous_close * 100,
    }


@pytest.fixture
def fake_market(monkeypatch):
    """Swap get_quote AS APP.PY USES IT (patch where it's used).

    Returns the quotes dict itself, so a test seeds it directly:
    fake_market["AAPL"] = make_quote(...). A symbol absent from the
    dict is "unquotable": quotes[symbol] raises KeyError inside the
    route's wide except — the same path a Yahoo outage or a delisted
    ticker would take, deterministically.
    """
    quotes = {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    return quotes


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD"):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type)


# ── Normal states ─────────────────────────────────────────────────────

def test_empty_ledger_returns_zeros_and_null_pcts(client, fake_market):
    """An empty ledger is a normal state, not an error: all-zero sums,
    null percentages (no base to divide by), nothing unpriced."""
    res = client.get("/api/portfolio/summary")
    assert res.status_code == 200
    assert res.get_json() == {
        "total_value": 0.0,
        "day_gain": 0.0,
        "day_gain_pct": None,
        "total_gain": 0.0,
        "total_gain_pct": None,
        "cost_basis": 0.0,
        "unpriced": [],
    }


def test_fully_sold_portfolio_zeros_with_null_pcts(client, fake_market):
    """Buy 10, sell all 10: net qty is 0, so value and day move are 0 —
    and the percentages correctly degrade to null instead of dividing by
    a meaningless base. The realized gain (bought @100, sold @110) still
    shows in total_gain via the netted cost basis: 0 − (1000 − 1100)."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", price=110.0, qty=10, tx_type="SELL")
    fake_market["AAPL"] = make_quote("AAPL", price=105.0, previous_close=100.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 0.0
    assert body["day_gain"] == 0.0
    assert body["day_gain_pct"] is None
    assert body["cost_basis"] == -100.0
    assert body["total_gain"] == 100.0
    assert body["total_gain_pct"] is None
    assert body["unpriced"] == []


# ── The math ──────────────────────────────────────────────────────────

def test_buy_only_totals_match_quote_math(client, fake_market):
    """One BUY, priced: every number is a straight multiply.
        value      = 10 × 105 = 1050
        day_gain   = 10 × (105 − 100) = 50, ÷ yesterday's 1000 → 5%
        cost_basis = 10 × 100 = 1000
        total_gain = 1050 − 1000 = 50, ÷ 1000 → 5%
    """
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    fake_market["AAPL"] = make_quote("AAPL", price=105.0, previous_close=100.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 1050.0
    assert body["day_gain"] == 50.0
    assert body["day_gain_pct"] == pytest.approx(5.0)
    assert body["cost_basis"] == 1000.0
    assert body["total_gain"] == 50.0
    assert body["total_gain_pct"] == pytest.approx(5.0)
    assert body["unpriced"] == []


def test_sell_nets_cost_basis_and_blends_realized_gain(client, fake_market):
    """The trickiest math in the feature, in one position:
        BUY 10 @ 100 (paid 1000), SELL 4 @ 110 (recouped 440)
      → cost basis 560, net qty 6, live price 105.
        value      = 6 × 105 = 630
        total_gain = 630 − 560 = 70
          = 40 realized on the sale (4 × (110 − 100))
          + 30 unrealized on what's held (6 × (105 − 100))
        One formula, no separate realized/unrealized bookkeeping.
        day_gain   = 6 × (105 − 100) = 30, ÷ yesterday's 600 → 5%
    """
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", price=110.0, qty=4, tx_type="SELL")
    fake_market["AAPL"] = make_quote("AAPL", price=105.0, previous_close=100.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 630.0
    assert body["day_gain"] == 30.0
    assert body["day_gain_pct"] == pytest.approx(5.0)
    assert body["cost_basis"] == 560.0
    assert body["total_gain"] == 70.0
    assert body["total_gain_pct"] == pytest.approx(70.0 / 560.0 * 100)


# ── Resilience ────────────────────────────────────────────────────────

def test_unpriced_ticker_excluded_from_every_sum(client, fake_market):
    """A dead ticker contributes to NOTHING — not value, not day move,
    and crucially not cost basis. Adding its cost without its value
    would fake a loss that never happened; excluding it everywhere keeps
    every number describing the same priced-only slice. Its NAME is the
    only trace: the "unpriced" list the frontend tooltip surfaces."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="CM", date="2026-08-02", price=75.0, qty=1,
                     currency="USD")
    fake_market["AAPL"] = make_quote("AAPL", price=105.0, previous_close=100.0)
    # "CM" deliberately absent → get_quote raises → excluded everywhere

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 1050.0
    assert body["day_gain"] == 50.0
    assert body["cost_basis"] == 1000.0
    assert body["total_gain"] == 50.0
    assert body["unpriced"] == ["CM"]


def test_all_unpriced_yields_the_frontend_degraded_shape(client, fake_market):
    """When EVERY ticker is unquotable, all sums are zero while
    "unpriced" is non-empty — exactly the shape the frontend checks to
    degrade the whole header to "—" instead of painting a hollow 0.00.
    Still a 200: the ledger facts stand; the quotes are what failed."""
    seed_transaction(ticker="CM", price=75.0, qty=1, currency="USD")
    # "CM" absent from the fake market

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 0.0
    assert body["day_gain"] == 0.0
    assert body["total_gain"] == 0.0
    assert body["day_gain_pct"] is None
    assert body["total_gain_pct"] is None
    assert body["unpriced"] == ["CM"]


# ── Documented temporary decision ─────────────────────────────────────

def test_mixed_currencies_sum_as_is(client, fake_market):
    """The temporary decision (project-brief.md): each holding counts in
    its own native currency and the totals add them as-is — no FX.
        CM    (USD): 1 × 76 = 76
        CM.TO (CAD): 1 × 51 = 51
        "total" 127 mixes the two — exact for one-currency portfolios,
        a documented approximation otherwise. This test LOCKS the
        decision: if someone adds FX conversion later, it is meant to
        fail and force updating the docs."""
    seed_transaction(ticker="CM", price=75.0, qty=1, currency="USD")
    seed_transaction(ticker="CM.TO", date="2026-08-02", price=50.0, qty=1,
                     currency="CAD")
    fake_market["CM"] = make_quote("CM", price=76.0, previous_close=75.0,
                                   currency="USD")
    fake_market["CM.TO"] = make_quote("CM.TO", price=51.0, previous_close=50.0,
                                      currency="CAD")

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 127.0  # 76 USD + 51 CAD, summed as-is
    assert body["day_gain"] == 2.0       # 1 USD + 1 CAD
    assert body["cost_basis"] == 125.0
    assert body["unpriced"] == []
