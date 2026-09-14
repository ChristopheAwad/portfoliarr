# tests/test_ui_redesign.py
# =========================
# Tests for the "Printed money" UI identity + dashboard completion feature.
# Two contracts are under test here:
#
#   1. THE IDENTITY (template string checks): the redesigned pages must
#      ship the new typefaces (Fraunces + Instrument Sans), the cost-basis
#      summary element, and the allocation donut canvas. These are rendered-
#      HTML checks through the Flask test client — they test what the
#      BROWSER receives, not what a template file happens to contain.
#
#   2. THE HOLDINGS BREAKDOWN (route math): /api/portfolio/summary gains
#      a `holdings` key — the per-ticker slice of the portfolio that the
#      dashboard's allocation donut plots. The math inherits every rule
#      the summary's totals already follow (they're computed in the same
#      pass, from the same quotes):
#        - CAD display: USD values convert at the LIVE rate
#        - priced-only slice: an unpriced ticker appears in NEITHER the
#          totals NOR holdings — a donut wedge for a dead ticker would
#          fake a weight that can't be sold
#        - netting: BUY adds shares, SELL subtracts (net qty drives value)
#        - weight = value ÷ total_value, so the wedges sum to exactly 1
#          (a donut that doesn't close is a lying donut)
#
# The timeframe-label lock (test 4) guards a sneaky regression class:
# main.js and stock.js read the timeframe buttons' textContent as keys
# into PERIOD_MAP. A restyle that renames or reorders those buttons
# breaks the chart silently — this test makes it break loudly instead.

import re
from types import SimpleNamespace

import pytest

import app as app_module
import db
from app import app


# ── The rendered-page contracts ───────────────────────────────────────

def test_dashboard_ships_redesigned_fonts(client):
    """The identity pass lives or dies on the typefaces actually reaching
    the browser. base.html loads them from Google Fonts' css2 endpoint —
    the URL must name BOTH families (Instrument+Sans is URL-encoded with
    a plus, since css2 rejects raw spaces)."""
    html = client.get("/").get_data(as_text=True)
    assert "Fraunces" in html, "Fraunces (display face) missing from base.html"
    assert "Instrument+Sans" in html, (
        "Instrument Sans (UI face) missing from base.html"
    )


def test_dashboard_has_cost_basis_element(client):
    """The brief's summary strip lists cost basis; the dashboard never
    showed it. main.js paints the number into this element from the
    summary reply's cost_basis field."""
    html = client.get("/").get_data(as_text=True)
    assert 'id="portfolio-cost-basis"' in html


def test_dashboard_has_allocation_donut(client):
    """The brief lists an allocation donut; it never existed. main.js
    paints a Chart.js doughnut onto this canvas from the summary reply's
    holdings slice."""
    html = client.get("/").get_data(as_text=True)
    assert 'id="allocationChart"' in html


def test_timeframe_labels_survive_the_restyle_on_dashboard(client):
    """The nine timeframe buttons, in order, EXACTLY. Their textContent
    is the PERIOD_MAP lookup key — a cosmetic rename here would 404 the
    chart data for that period. If you ever add a timeframe, update the
    expected list here AND PERIOD_MAP together."""
    html = client.get("/").get_data(as_text=True)
    found = re.findall(r">\s*(1D|5D|1M|3M|6M|YTD|1Y|5Y|MAX)\s*<", html)
    assert found == ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"]


def test_timeframe_labels_survive_the_restyle_on_stock_page(client):
    """Same lock as the dashboard, on the detail page — the two pages
    share the buttons' contract with PERIOD_MAP, so both are pinned."""
    html = client.get("/stock/AAPL").get_data(as_text=True)
    found = re.findall(r">\s*(1D|5D|1M|3M|6M|YTD|1Y|5Y|MAX)\s*<", html)
    assert found == ["1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "5Y", "MAX"]


# ── The holdings breakdown (donut data) ───────────────────────────────
#
# Fixture mirrors test_portfolio_summary.py's local fake_market: patch
# where app.py USES the names (app.get_quote, app.get_fx_rate...), keyed
# dicts, absent key = Yahoo couldn't answer.

def make_quote(symbol, price, previous_close, currency="CAD"):
    """A quote dict in exactly market_data.get_quote's shape."""
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
    """Patch where app.py USES the names (app.get_quote, app.get_fx_rate,
    app.get_fx_rate_on — not market_data's). Keyed dicts; an ABSENT key
    raises KeyError inside the route's wide except — exactly how a Yahoo
    outage (or an unavailable FX rate) behaves, deterministically.
    Mirrors test_portfolio_summary.py's local fixture of the same name."""
    quotes, fx_rates, fx_on = {}, {}, {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: fx_rates[f"{base}{target}"])
    monkeypatch.setattr(app_module, "get_fx_rate_on",
                        lambda base, target, date_iso:
                            fx_on[(f"{base}{target}", date_iso)])
    return SimpleNamespace(quotes=quotes, fx_rates=fx_rates, fx_on=fx_on)


def seed(ticker, price, qty, tx_type="BUY", currency="CAD", fx_rate=1.0,
         date="2026-08-01"):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


def test_holdings_empty_ledger(client, fake_market):
    """Empty ledger → no wedges. The donut card shows its own empty state;
    the endpoint's job is just to say so honestly."""
    body = client.get("/api/portfolio/summary").get_json()
    assert body["holdings"] == []


def test_holdings_single_holding_weight_one(client, fake_market):
    """One holding owns 100% of the donut. 10 RBC @ $150 (CAD) → value
    1500.0, weight exactly 1.0."""
    seed("RBC.TO", 150.0, 10)
    market.quotes["RBC.TO"] = make_quote("RBC.TO", 150.0, 148.0)
    body = client.get("/api/portfolio/summary").get_json()
    assert len(body["holdings"]) == 1
    entry = body["holdings"][0]
    assert entry["ticker"] == "RBC.TO"
    assert entry["value"] == pytest.approx(1500.0)
    assert entry["weight"] == pytest.approx(1.0)


def test_holdings_weights_sum_to_one_and_sort_by_value(client, fake_market):
    """Two holdings: values are net_qty × price, weights are
    value ÷ total_value, and the wedges close the circle — weights sum
    to 1 within 1e-9 (binary float residue, the same tolerance the
    realized-gain fold uses). The list is sorted by value DESCENDING so
    the donut's legend reads biggest-first without the frontend sorting
    again (main.js reads, never re-derives)."""
    seed("RY.TO", 100.0, 10)    # 10 × 200 = 2000 (price moved to 200)
    seed("TD.TO", 50.0, 10)     # 10 × 100 = 1000 (price moved to 100)
    market.quotes["RY.TO"] = make_quote("RY.TO", 200.0, 195.0)
    market.quotes["TD.TO"] = make_quote("TD.TO", 100.0, 99.0)
    body = client.get("/api/portfolio/summary").get_json()
    holdings = body["holdings"]
    assert [h["ticker"] for h in holdings] == ["RY.TO", "TD.TO"]
    assert holdings[0]["value"] == pytest.approx(2000.0)
    assert holdings[1]["value"] == pytest.approx(1000.0)
    assert holdings[0]["weight"] == pytest.approx(2000.0 / 3000.0)
    assert holdings[1]["weight"] == pytest.approx(1000.0 / 3000.0)
    assert sum(h["weight"] for h in holdings) == pytest.approx(1.0, abs=1e-9)


def test_holdings_usd_converts_at_live_rate(client, fake_market):
    """A USD holding enters the CAD donut at the LIVE rate — the same
    conversion rule the totals follow (current value = a potential sell).
    10 AAPL @ $180 USD × 1.35 = 2430 CAD; the seeded fx dict proves the
    rate was actually consulted (absent key would raise KeyError)."""
    seed("AAPL", 180.0, 10, currency="USD", fx_rate=1.30)
    market.quotes["AAPL"] = make_quote("AAPL", 180.0, 175.0, currency="USD")
    market.fx_rates["USDCAD"] = 1.35
    body = client.get("/api/portfolio/summary").get_json()
    assert body["holdings"][0]["value"] == pytest.approx(2430.0)
    assert body["holdings"][0]["weight"] == pytest.approx(1.0)


def test_holdings_excludes_unpriced_ticker(client, fake_market):
    """A dead ticker joins the totals' 'unpriced' list and appears in NO
    wedge: a donut slice for something you can't sell is a lie, and a
    weight computed over a phantom denominator would misstate every
    other wedge. RBC prices (weight 1.0, not 0.5 over a fake total)."""
    seed("RBC.TO", 150.0, 10)
    seed("DEAD.TO", 50.0, 10)
    market.quotes["RBC.TO"] = make_quote("RBC.TO", 150.0, 148.0)
    # DEAD.TO absent from the quotes dict = Yahoo couldn't answer.
    body = client.get("/api/portfolio/summary").get_json()
    assert body["unpriced"] == ["DEAD.TO"]
    assert [h["ticker"] for h in body["holdings"]] == ["RBC.TO"]
    assert body["holdings"][0]["weight"] == pytest.approx(1.0)


def test_holdings_sells_net_out(client, fake_market):
    """Buy 10, sell 4 → the wedge is the NET 6 shares, not the 10 once
    bought. Value 6 × 100 = 600. The same netting rule the totals use,
    applied per ticker."""
    seed("BN.TO", 100.0, 10)
    seed("BN.TO", 110.0, 4, tx_type="SELL", date="2026-08-05")
    fake_market.quotes["BN.TO"] = make_quote("BN.TO", 100.0, 98.0)
    body = client.get("/api/portfolio/summary").get_json()
    assert body["holdings"][0]["value"] == pytest.approx(600.0)
    assert body["holdings"][0]["weight"] == pytest.approx(1.0)


def test_holdings_fully_sold_portfolio_has_no_wedges(client, fake_market):
    """Buy 10, sell all 10 → net qty 0 → no wedge at all. A zero-value
    wedge would be invisible clutter at best and a 0/0 weight NaN at
    worst; 'no position, no wedge' is the honest shape."""
    seed("AAPL", 100.0, 10)
    seed("AAPL", 110.0, 10, tx_type="SELL", date="2026-08-05")
    market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0)
    body = client.get("/api/portfolio/summary").get_json()
    assert body["holdings"] == []
