# tests/test_currency_display.py
# =================================
# The ledger's DISPLAY-currency contract: GET /api/transactions?currency=
# CAD|NATIVE — the one endpoint the dashboard's "Show USD in USD" toggle
# flips — plus the regression pinning the watchlist to native currency.
#
# THE TWO-RATE CONTRACT (feature.md): in CAD mode,
#   - price_display  = stored price × the row's STORED fx_rate — a past
#                      fact, frozen at the buy-date's USDCAD close;
#   - value / day_gain = live quote × the LIVE rate — today's CAD value
#                      of a potential sell;
#   - total_gain     = CAD value − CAD cost (so its % includes currency
#                      movement — the honest CAD return);
#   - the stored facts (price, currency, fx_rate, price_now) NEVER move:
#     the edit form prefills from them, and the frontend's group-% math
#     divides CAD value by CAD cost only because price_display converts
#     with the same stored rate.
# display_currency / price_display ride EVERY row (equal to the native
# facts in native mode) so the frontend never branches on the mode.
#
# Fixtures come from conftest.py: `client` (fresh_db + Flask test client)
# and `fake_market` (quotes/names/histories/stats + fx_rates/fx_on dicts,
# patched AS APP.PY USES THEM — the golden mocking rule).

import pytest

import db
import app as app_module
from conftest import make_quote


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD", fx_rate=1.40):
    """Insert a ledger row through the db layer. Defaults model the
    common USD case: bought @100 when USDCAD was 1.40."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


def seed_usd_market(fake_market, price=105.0, previous_close=100.0):
    """A quoted USD AAPL plus today's live USDCAD rate (1.35 — weaker
    than the stored 1.40, so FX drag shows in every number)."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=price,
                                            previous_close=previous_close,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.35


# ── CAD mode (the default) ────────────────────────────────────────────

def test_default_display_is_cad(client, fake_market):
    """No param = CAD. One row, bought @100 USD at 1.40, live 105 USD at
    1.35:
        price_display = 100 × 1.40 (stored)          = 140
        value         = 105 × 10 × 1.35 (live)       = 1417.50
        total_gain    = 1417.50 − 140 × 10           = 17.50  → 1.25% of CAD cost
        day_gain      = 5 × 10 × 1.35 (live)         = 67.50
    The native facts ride along untouched — the edit form's prefill and
    the delete confirmation read THOSE."""
    seed_transaction()
    seed_usd_market(fake_market)

    row = client.get("/api/transactions").get_json()[0]
    # CAD display numbers...
    assert row["display_currency"] == "CAD"
    assert row["price_display"] == pytest.approx(140.0)
    assert row["value"] == pytest.approx(1417.5)
    assert row["total_gain"] == pytest.approx(17.5)
    assert row["total_gain_pct"] == pytest.approx(17.5 / 1400.0 * 100)
    assert row["day_gain"] == pytest.approx(67.5)
    # ...and the untouched native facts.
    assert row["price"] == 100.0
    assert row["currency"] == "USD"
    assert row["fx_rate"] == 1.40
    assert row["price_now"] == 105.0
    # The day % is a price-level ratio — identical in every currency.
    assert row["day_gain_pct"] == pytest.approx(5.0)


def test_cad_rows_pass_through_unchanged(client, fake_market):
    """A CAD-quoted security needs no conversion: its display fields
    EQUAL its native facts (rate 1.0), and the live math is today's
    native math. One formula path, zero special cases."""
    seed_transaction(ticker="RY.TO", price=50.0, currency="CAD", fx_rate=1.0)
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", price=51.0,
                                             previous_close=50.0,
                                             currency="CAD")

    row = client.get("/api/transactions").get_json()[0]
    assert row["display_currency"] == "CAD"
    assert row["price_display"] == row["price"] == 50.0
    assert row["value"] == pytest.approx(510.0)
    assert row["total_gain"] == pytest.approx(10.0)
    assert row["day_gain"] == pytest.approx(10.0)


def test_legacy_null_fx_rate_uses_live_rate_everywhere(client, fake_market):
    """A pre-feature USD row (fx_rate NULL) has no stored fact to convert
    with — the live rate stands in for BOTH sides (cost and value), which
    keeps the % equal to the pure stock return. Editing the row backfills
    the real date-based fact."""
    seed_transaction(fx_rate=None)
    seed_usd_market(fake_market)

    row = client.get("/api/transactions").get_json()[0]
    assert row["display_currency"] == "CAD"
    assert row["price_display"] == pytest.approx(100.0 * 1.35)
    assert row["value"] == pytest.approx(105.0 * 10 * 1.35)
    assert row["total_gain"] == pytest.approx((105.0 - 100.0) * 10 * 1.35)
    assert row["total_gain_pct"] == pytest.approx(5.0)


def test_unquoted_row_with_stored_fx_still_shows_cad_price(client, fake_market):
    """The quote died but the facts stand: the stored fx_rate alone is
    enough to convert the PRICE (a past fact needs no live data), so the
    row keeps its CAD cost while the live cells degrade to "—" frontend-
    side (no value/total_gain keys)."""
    seed_transaction()
    # "AAPL" deliberately absent from the fake market → no quote

    row = client.get("/api/transactions").get_json()[0]
    assert row["display_currency"] == "CAD"
    assert row["price_display"] == pytest.approx(140.0)
    assert "price_now" not in row
    assert "value" not in row


def test_unquoted_legacy_row_stays_native(client, fake_market):
    """No quote AND no stored rate: nothing can convert honestly, so the
    row displays native facts (display_currency echoes the stored code)
    rather than pretending 1 USD = 1 CAD."""
    seed_transaction(fx_rate=None)
    # no quote, no fx

    row = client.get("/api/transactions").get_json()[0]
    assert row["display_currency"] == "USD"
    assert row["price_display"] == row["price"] == 100.0


def test_fx_failure_degrades_usd_rows_to_native(client, fake_market):
    """The quote lives but the FX rate doesn't: USD rows fall back to
    native display (never a 500, never a fake 1:1 rate) while CAD rows —
    whose native display IS CAD — carry on as if nothing happened."""
    seed_transaction()
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    seed_transaction(ticker="RY.TO", date="2026-08-02", currency="CAD",
                     fx_rate=1.0)
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", price=51.0,
                                             previous_close=50.0,
                                             currency="CAD")
    # fx_rates deliberately empty → the live rate is unavailable

    rows = client.get("/api/transactions").get_json()
    by_ticker = {row["ticker"]: row for row in rows}
    usd_row = by_ticker["AAPL"]
    assert usd_row["display_currency"] == "USD"
    assert usd_row["price_display"] == 100.0
    assert usd_row["value"] == pytest.approx(1050.0)     # native math
    cad_row = by_ticker["RY.TO"]
    assert cad_row["display_currency"] == "CAD"
    assert cad_row["value"] == pytest.approx(510.0)


# ── NATIVE mode (what the toggle flips to) ────────────────────────────

def test_native_param_pins_todays_shape(client, fake_market, monkeypatch):
    """?currency=native is the pre-FX behavior exactly: display fields
    equal the native facts and every live number is native. This is what
    the dashboard toggle requests — USD securities 'back to USD value'.
    Native mode never asks for an FX rate: the exploding patch proves a
    call would fail the test, not just go unseeded."""
    seed_transaction()
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")

    def explode(base, target):
        raise AssertionError("native mode must not fetch an FX rate")

    monkeypatch.setattr(app_module, "get_fx_rate", explode)

    row = client.get("/api/transactions?currency=native").get_json()[0]
    assert row["display_currency"] == "USD"
    assert row["price_display"] == row["price"] == 100.0
    assert row["value"] == pytest.approx(1050.0)
    assert row["total_gain"] == pytest.approx(50.0)
    assert row["total_gain_pct"] == pytest.approx(5.0)
    assert row["day_gain"] == pytest.approx(50.0)


def test_cad_param_explicit_matches_default(client, fake_market):
    """The toggle OFF sends ?currency=CAD explicitly; it must land in the
    exact same place as omitting the param."""
    seed_transaction()
    seed_usd_market(fake_market)

    explicit = client.get("/api/transactions?currency=CAD").get_json()[0]
    omitted = client.get("/api/transactions").get_json()[0]
    assert explicit == omitted
    assert explicit["display_currency"] == "CAD"


def test_invalid_currency_param_is_400(client, fake_market):
    """A nonsense display currency is rejected BEFORE any work, with the
    valid options named — the same contract as the chart's ?period=."""
    seed_transaction()
    res = client.get("/api/transactions?currency=GBP")
    assert res.status_code == 400
    assert "CAD" in res.get_json()["error"]
    assert "NATIVE" in res.get_json()["error"]


# ── Scope pins: what must NOT convert ─────────────────────────────────

def test_watchlist_quotes_stay_native(client, fake_market):
    """THE scope decision: the watchlist is market data, not portfolio
    value — its USD quotes display natively no matter what the dashboard
    toggle or the ledger do. No ?currency= exists on this endpoint."""
    db.add_symbol("AAPL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=229.5,
                                            previous_close=225.0,
                                            currency="USD")
    fake_market.names["AAPL"] = "Apple Inc"

    quote = client.get("/api/watchlist").get_json()["quotes"][0]
    assert quote["price"] == 229.5          # native, NOT × any FX rate
    assert quote["currency"] == "USD"
    assert fake_market.fx_rates == {}       # never even asked
