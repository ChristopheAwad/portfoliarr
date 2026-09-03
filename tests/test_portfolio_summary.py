# tests/test_portfolio_summary.py
# =================================
# Route tests for GET /api/portfolio/summary — the portfolio header's
# live numbers (total value, day change, total return).
#
# Same concepts as test_routes.py (read its banner first):
#   - the Flask TEST CLIENT (conftest.py) — real routes, no network
#   - MOCKING with the golden rule "patch where it's USED": app.py did
#     `from market_data import get_quote`, so we patch app.get_quote.
#     The patch is a dict lookup — a ticker missing from the dict raises
#     KeyError, which is exactly how an unquotable/dead ticker behaves.
#     The FX helpers (get_fx_rate / get_fx_rate_on) get the same
#     treatment via the fixture's fx_rates / fx_on dicts.
#   - the throwaway DB (fresh_db, via client) — seeded through the db
#     layer's add_transaction, never raw SQL.
#
# THE CONTRACTS UNDER TEST HERE:
#   - the math: value / day gain / cost basis / their percentages
#   - THE DISPLAY CURRENCY: the summary is ALWAYS CAD. USD amounts
#     convert at the LIVE rate for current values (a potential sell)
#     and at each transaction's STORED fx_rate for the cost basis (a
#     past fact). The old "sum native currencies as-is" decision is
#     retired — its locking test was rewritten to lock the conversion.
#   - netting: a SELL subtracts proceeds from cost basis, which is how
#     realized gains blend with unrealized ones in total_gain
#   - resilience: an unpriced ticker is excluded from EVERY sum and
#     reported in "unpriced" — never a 500, never a half-priced mix
#   - normal states: empty ledger and fully-sold portfolios return
#     zeros with null percentages, not errors

import pytest
from types import SimpleNamespace

import db

# NAME-COLLISION SUBTLETY (see test_routes.py banner): `from app import
# app` binds the Flask object; the routes look up get_quote in the
# MODULE's namespace, so that's the name we must patch.
import app as app_module


# ── Helpers & fixtures ────────────────────────────────────────────────

def make_quote(symbol, price, previous_close, currency="CAD"):
    """Build a quote dict in exactly the shape market_data.get_quote
    returns (raw floats + derived day-move numbers). Defaults to CAD so
    the pure-math tests need no FX scaffolding; USD tests pass it
    explicitly."""
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
    """Swap get_quote AND the FX helpers AS APP.PY USES THEM (patch where
    they're used). Returns the dicts themselves, so a test seeds directly:
    fake_market["AAPL"] = make_quote(...), fake_market.fx_rates["USDCAD"]
    = 1.35. An absent key raises KeyError inside the route's wide except —
    the same path a Yahoo outage (or an unavailable FX rate) would take,
    deterministically."""
    quotes = {}
    fx_rates, fx_on = {}, {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: fx_rates[f"{base}{target}"])
    monkeypatch.setattr(app_module, "get_fx_rate_on",
                        lambda base, target, date_iso:
                            fx_on[(f"{base}{target}", date_iso)])
    return SimpleNamespace(quotes=quotes, fx_rates=fx_rates, fx_on=fx_on)


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="CAD", fx_rate=1.0):
    """Insert a ledger row through the db layer (never raw SQL). fx_rate
    is the stored currency fact: 1.0 for CAD rows, the USDCAD close on
    `date` for USD rows (None = pre-feature row, rate unknown)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


# ── Normal states ─────────────────────────────────────────────────────

def test_empty_ledger_returns_zeros_and_null_pcts(client, fake_market):
    """An empty ledger is a normal state, not an error: all-zero sums,
    null percentages (no base to divide by), nothing unpriced. The reply
    declares its display currency — always CAD."""
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
        "currency": "CAD",
    }


def test_fully_sold_portfolio_zeros_with_null_pcts(client, fake_market):
    """Buy 10, sell all 10: net qty is 0, so value and day move are 0 —
    and the percentages correctly degrade to null instead of dividing by
    a meaningless base. The realized gain (bought @100, sold @110) still
    shows in total_gain via the netted cost basis: 0 − (1000 − 1100)."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", price=110.0, qty=10, tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 0.0
    assert body["day_gain"] == 0.0
    assert body["day_gain_pct"] is None
    assert body["cost_basis"] == -100.0
    assert body["total_gain"] == 100.0
    assert body["total_gain_pct"] is None
    assert body["unpriced"] == []


def test_cad_only_portfolio_never_touches_fx(client, fake_market):
    """A portfolio with no USD exposure needs no exchange rate — proved
    by the fx dict staying EMPTY (any FX call would raise KeyError and
    fail the test). The display currency is still declared CAD."""
    seed_transaction(ticker="RY.TO", price=50.0, qty=10)
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", price=51.0,
                                             previous_close=50.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 510.0
    assert body["cost_basis"] == 500.0
    assert body["currency"] == "CAD"
    assert fake_market.fx_rates == {} and fake_market.fx_on == {}


# ── The math ──────────────────────────────────────────────────────────

def test_buy_only_totals_match_quote_math(client, fake_market):
    """One BUY, priced: every number is a straight multiply.
        value      = 10 × 105 = 1050
        day_gain   = 10 × (105 − 100) = 50, ÷ yesterday's 1000 → 5%
        cost_basis = 10 × 100 = 1000
        total_gain = 1050 − 1000 = 50, ÷ 1000 → 5%
    """
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

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
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 630.0
    assert body["day_gain"] == 30.0
    assert body["day_gain_pct"] == pytest.approx(5.0)
    assert body["cost_basis"] == 560.0
    assert body["total_gain"] == 70.0
    assert body["total_gain_pct"] == pytest.approx(70.0 / 560.0 * 100)


# ── CAD conversion: the display-currency contract ─────────────────────

def test_mixed_currencies_convert_to_cad(client, fake_market):
    """THE display-currency decision (retired the old 'sum as-is' rule):
    USD holdings convert at the live USDCAD rate, CAD holdings pass
    through — one coherent CAD total.
        CM    (USD): 1 × 76 × 1.25 = 95
        CM.TO (CAD): 1 × 51        = 51
        total 146; day gain 1 × 1.25 + 1 = 2.25; cost 75 × 1.25 + 50.
    This test LOCKS the conversion: if someone reverts to mixed sums,
    it is meant to fail and force updating the docs."""
    seed_transaction(ticker="CM", price=75.0, qty=1, currency="USD",
                     fx_rate=1.25)
    seed_transaction(ticker="CM.TO", date="2026-08-02", price=50.0, qty=1,
                     currency="CAD")
    fake_market.quotes["CM"] = make_quote("CM", price=76.0, previous_close=75.0,
                                          currency="USD")
    fake_market.quotes["CM.TO"] = make_quote("CM.TO", price=51.0,
                                             previous_close=50.0,
                                             currency="CAD")
    fake_market.fx_rates["USDCAD"] = 1.25

    body = client.get("/api/portfolio/summary").get_json()
    assert body["currency"] == "CAD"
    assert body["total_value"] == pytest.approx(146.0)   # 95 + 51, in CAD
    assert body["day_gain"] == pytest.approx(2.25)
    assert body["cost_basis"] == pytest.approx(143.75)
    assert body["unpriced"] == []


def test_usd_value_uses_live_rate_cost_uses_stored_rate(client, fake_market):
    """THE two-rate contract in one position. Bought 10 @ 100 USD when
    USDCAD was 1.40 (stored fact); today's rate is 1.35:
        value      = 10 × 105 × 1.35 (live)  = 1417.50  — today's CAD value
        cost_basis = 10 × 100 × 1.40 (stored) = 1400.00  — what it cost then
        total_gain = 17.50: the stock rose 5% but the CAD strengthened,
                     so the CAD return is only 1.25% — currency IS part
                     of the picture a Canadian investor sees.
        day_gain   = 10 × 5 × 1.35 = 67.50 (both prices are TODAY's, so
                     today's rate applies to the whole day move).
    """
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=1.40)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.35

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == pytest.approx(1417.5)
    assert body["cost_basis"] == pytest.approx(1400.0)
    assert body["total_gain"] == pytest.approx(17.5)
    assert body["total_gain_pct"] == pytest.approx(1.25)
    assert body["day_gain"] == pytest.approx(67.5)
    # The day % divides by YESTERDAY'S CAD value (10 × 100 × 1.35 = 1350):
    # the stock rose 5% today and the currency didn't move within a day,
    # so the CAD day-% equals the native one.
    assert body["day_gain_pct"] == pytest.approx(5.0)


def test_each_transaction_converts_at_its_own_stored_rate(client, fake_market):
    """Cost basis is built from PER-TRANSACTION facts, not one portfolio-
    wide rate: the same USD stock bought on two dates at two rates sums
    both purchases at the rate of ITS day (1.40 + 1.30 → 270 CAD per
    share average). Value uses today's live rate only."""
    seed_transaction(ticker="AAPL", date="2026-07-01", price=100.0, qty=10,
                     currency="USD", fx_rate=1.40)
    seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0, qty=10,
                     currency="USD", fx_rate=1.30)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.35

    body = client.get("/api/portfolio/summary").get_json()
    assert body["cost_basis"] == pytest.approx(2700.0)  # 1400 + 1300
    assert body["total_value"] == pytest.approx(20 * 105 * 1.35)
    assert body["total_gain"] == pytest.approx(2835.0 - 2700.0)


def test_legacy_null_fx_rate_falls_back_to_live_rate(client, fake_market):
    """Pre-feature USD rows carry fx_rate NULL — 'rate unknown'. The cost
    basis then uses the LIVE rate for that row (a documented, per-request
    approximation; editing the row backfills the real stored fact)."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=None)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.35

    body = client.get("/api/portfolio/summary").get_json()
    assert body["cost_basis"] == pytest.approx(1350.0)  # live-rate fallback
    assert body["total_value"] == pytest.approx(1417.5)
    # Same rate on both sides → the pct collapses to the pure stock return.
    assert body["total_gain_pct"] == pytest.approx(5.0)


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
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)
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
    seed_transaction(ticker="CM", price=75.0, qty=1, currency="USD",
                     fx_rate=None)
    # "CM" absent from the fake market

    body = client.get("/api/portfolio/summary").get_json()
    assert body["total_value"] == 0.0
    assert body["day_gain"] == 0.0
    assert body["total_gain"] == 0.0
    assert body["day_gain_pct"] is None
    assert body["total_gain_pct"] is None
    assert body["unpriced"] == ["CM"]


def test_fx_failure_puts_usd_holdings_in_unpriced(client, fake_market):
    """Quotes can succeed and the summary STILL can't price a USD holding:
    without a live USDCAD rate there is no honest CAD number. The holding
    joins "unpriced" and is excluded from EVERY sum (same priced-only-
    slice rule as a dead ticker) while CAD holdings carry on untouched."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=1.40)
    seed_transaction(ticker="RY.TO", date="2026-08-02", price=50.0, qty=10,
                     currency="CAD")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", price=51.0,
                                             previous_close=50.0,
                                             currency="CAD")
    # fx_rates deliberately empty → get_fx_rate raises → USD excluded

    body = client.get("/api/portfolio/summary").get_json()
    assert body["unpriced"] == ["AAPL"]
    assert body["total_value"] == pytest.approx(510.0)   # RY.TO only
    assert body["cost_basis"] == pytest.approx(500.0)
