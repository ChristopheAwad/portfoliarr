# tests/test_ledger_groups.py
# =================================
# Route tests for the GROUP aggregates GET /api/transactions decorates
# every row with — the per-ticker numbers the ledger's collapsed summary
# rows (and its sorter) display.
#
# WHY THESE LIVE ON EVERY ROW: the reply is a JSON array of transactions
# (the frontend's render contract), so each row carries its TICKER's
# group fields: group_value, group_cost_basis, group_total_gain,
# group_total_gain_pct, group_day_gain, group_day_gain_pct. Every row of
# one ticker carries the SAME values — the frontend reads them off the
# group's first row.
#
# THE CONTRACTS UNDER TEST HERE:
#   - the math mirrors /api/portfolio/summary exactly (one holdings
#     formula, two implementations is how drift bugs are born):
#       group_value      = net_qty × live price × value-rate
#       group_cost_basis = Σ ±(price_display × qty) — buys paid minus
#                          sells recouped, each at ITS display rate
#       group_total_gain = value − cost (realized + unrealized blended)
#       group_total_gain_pct = gain ÷ cost, NULL when cost ≤ 0
#       group_day_gain   = net_qty × quote.change × value-rate
#       group_day_gain_pct   = the ticker's daily move (price-level)
#   - SELLS NET OUT: the bug this feature fixes — group rows used to sum
#     BUY rows only, so logging a SELL changed nothing but Qty
#   - oversold positions (net qty < 0, incl. SELL-only groups) display
#     honestly negative — no clamping, consistent with the summary route
#   - the two-rate contract: value side at the LIVE USDCAD rate (CAD
#     mode), cost side at each row's own price_display (stored fx /
#     native); native mode pins native numbers
#   - resilience: an unquoted ticker's rows carry NO group_* keys at all
#     (facts only — the frontend's "—" path keys on their absence)

import pytest
from types import SimpleNamespace

import db


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
    """Swap get_quote AND the live-rate helper AS APP.PY USES THEM (patch
    where they're used — app.py did `from market_data import ...`, so the
    module-level names are what routes look up). An absent quotes key
    raises KeyError inside the route's wide except: the deterministic
    stand-in for a dead ticker. Seeding goes straight through db.add_
    transaction, so no historical-FX helper is needed here."""
    quotes = {}
    fx_rates = {}
    import app as app_module
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: fx_rates[f"{base}{target}"])
    return SimpleNamespace(quotes=quotes, fx_rates=fx_rates)


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="CAD", fx_rate=1.0):
    """Insert a ledger row through the db layer (never raw SQL). fx_rate
    is the stored currency fact: 1.0 for CAD rows, the USDCAD close on
    `date` for USD rows."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


def rows_of(client, ticker):
    """GET the ledger and return (buy_rows, sell_rows) for ONE ticker.
    Group fields must be identical across a ticker's rows, so tests fetch
    both kinds and assert on each."""
    rows = client.get("/api/transactions").get_json()
    mine = [r for r in rows if r["ticker"] == ticker]
    buys = [r for r in mine if r["transaction_type"] == "BUY"]
    sells = [r for r in mine if r["transaction_type"] == "SELL"]
    return buys, sells


def assert_group_fields(row, value, cost, gain, pct, day_gain, day_pct):
    """One assertion block for the six group fields on one row."""
    assert row["group_value"] == pytest.approx(value)
    assert row["group_cost_basis"] == pytest.approx(cost)
    assert row["group_total_gain"] == pytest.approx(gain)
    if pct is None:
        assert row["group_total_gain_pct"] is None
    else:
        assert row["group_total_gain_pct"] == pytest.approx(pct)
    assert row["group_day_gain"] == pytest.approx(day_gain)
    assert row["group_day_gain_pct"] == pytest.approx(day_pct)


# ── The math ──────────────────────────────────────────────────────────

def test_buy_only_group_aggregates_match_row_math(client, fake_market):
    """Baseline — one BUY, so the new aggregates must equal the old
    BUY-only sums exactly:
        value 10 × 105 = 1050, cost 10 × 100 = 1000,
        gain 50 (5%), day_gain 10 × (105 − 100) = 50 (5%)."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    buys, sells = rows_of(client, "AAPL")
    assert len(buys) == 1 and sells == []
    assert_group_fields(buys[0], value=1050.0, cost=1000.0, gain=50.0,
                        pct=5.0, day_gain=50.0, day_pct=5.0)


def test_partial_sell_nets_value_and_blends_realized_gain(client, fake_market):
    """THE bug fix, in one position (same numbers as the summary's
    locking test):
        BUY 10 @ 100 (paid 1000), SELL 4 @ 110 (recouped 440), live 105
      → net 6 held: value 630 — NOT the old 1050 (10 bought, 4 gone)
        cost 560, gain 70 = 40 realized + 30 unrealized (12.5%)
        day_gain 6 × 5 = 30."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", date="2026-08-02", price=110.0, qty=4,
                     tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    buys, sells = rows_of(client, "AAPL")
    assert len(buys) == 1 and len(sells) == 1
    # Both rows carry the SAME group fields — they describe the TICKER.
    for row in (buys[0], sells[0]):
        assert_group_fields(row, value=630.0, cost=560.0, gain=70.0,
                            pct=12.5, day_gain=30.0, day_pct=5.0)


def test_fully_sold_group_shows_realized_gain_null_pct(client, fake_market):
    """Sold everything: net qty 0 → value 0, day_gain 0 — but the gain is
    the REALIZED profit (recouped 1100 > paid 1000 → cost basis −100),
    and the % is null: a ≤ 0 cost basis is no honest denominator."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", date="2026-08-02", price=110.0, qty=10,
                     tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    buys, sells = rows_of(client, "AAPL")
    for row in (buys[0], sells[0]):
        assert_group_fields(row, value=0.0, cost=-100.0, gain=100.0,
                            pct=None, day_gain=0.0, day_pct=5.0)


def test_sell_only_group_is_negative(client, fake_market):
    """A SELL with no BUY (importer forces BUYs, the form doesn't):
    net qty −4 → value −420, cost −440, gain +20 (bought-back-cheaper
    math), pct null. Honest negatives, matching the summary route —
    never clamped to zero."""
    seed_transaction(ticker="AAPL", date="2026-08-01", price=110.0, qty=4,
                     tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)

    buys, sells = rows_of(client, "AAPL")
    assert buys == [] and len(sells) == 1
    assert_group_fields(sells[0], value=-420.0, cost=-440.0, gain=20.0,
                        pct=None, day_gain=-20.0, day_pct=5.0)


# ── CAD conversion: the two-rate contract ─────────────────────────────

def test_cad_conversion_value_live_cost_stored(client, fake_market):
    """USD group in CAD mode — the summary's two-rate contract per group:
        value side at the LIVE rate: 10 × 105 × 1.25 = 1312.5
        cost side at the STORED fx:  10 × 100 × 1.40 = 1400
        gain −87.5 — currency movement included, the honest CAD picture."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=1.40)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.25

    buys, _ = rows_of(client, "AAPL")
    assert_group_fields(buys[0], value=1312.5, cost=1400.0, gain=-87.5,
                        pct=-6.25, day_gain=62.5, day_pct=5.0)


def test_cad_cost_nets_each_rows_own_stored_rate(client, fake_market):
    """The cost basis is Σ ±(price × THAT row's stored fx × qty): the
    SELL recoups at ITS day's rate (1.30), not the BUY's (1.40).
        value 6 × 105 × 1.25 = 787.5
        cost 1400 − 4 × 110 × 1.30 = 828
        gain −40.5."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=1.40)
    seed_transaction(ticker="AAPL", date="2026-08-02", price=110.0, qty=4,
                     tx_type="SELL", currency="USD", fx_rate=1.30)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.25

    buys, sells = rows_of(client, "AAPL")
    for row in (buys[0], sells[0]):
        assert_group_fields(row, value=787.5, cost=828.0, gain=-40.5,
                            pct=-40.5 / 828.0 * 100, day_gain=37.5,
                            day_pct=5.0)


def test_native_mode_group_fields_are_native(client, fake_market):
    """?currency=NATIVE pins the group fields to the native currency —
    the same USD position as the CAD test, but NO conversion anywhere:
    value 1050 (not 1312.5), cost 1000 (not 1400). The toggle moves the
    ledger's display, never the CAD header's math."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, currency="USD",
                     fx_rate=1.40)
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0,
                                            currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.25

    res = client.get("/api/transactions?currency=NATIVE")
    assert res.status_code == 200
    row = res.get_json()[0]
    assert row["display_currency"] == "USD"
    assert_group_fields(row, value=1050.0, cost=1000.0, gain=50.0,
                        pct=5.0, day_gain=50.0, day_pct=5.0)


# ── Resilience & scoping ──────────────────────────────────────────────

def test_unquoted_ticker_has_no_group_fields(client, fake_market):
    """A dead ticker's rows stay FACTS ONLY — no group_* keys at all (the
    frontend's hasLive / "—" gap-fill keys on their absence), exactly
    like the per-row live fields today."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    # fake_market.quotes stays empty → get_quote("AAPL") raises KeyError.

    res = client.get("/api/transactions")
    assert res.status_code == 200
    row = res.get_json()[0]
    assert "group_value" not in row
    assert "group_cost_basis" not in row
    assert "group_total_gain" not in row
    assert "group_total_gain_pct" not in row
    assert "group_day_gain" not in row
    assert "group_day_gain_pct" not in row
    # Facts survive untouched.
    assert row["price"] == 100.0 and row["qty"] == 10


def test_group_fields_are_per_ticker(client, fake_market):
    """Two tickers, two independent aggregates: each row's group fields
    describe ITS ticker only — AAPL's numbers must never leak into
    MSFT's rows."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="MSFT", date="2026-08-02", price=200.0, qty=2,
                     tx_type="BUY")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=105.0,
                                            previous_close=100.0)
    fake_market.quotes["MSFT"] = make_quote("MSFT", price=210.0,
                                            previous_close=200.0)

    buys, _ = rows_of(client, "AAPL")
    assert_group_fields(buys[0], value=1050.0, cost=1000.0, gain=50.0,
                        pct=5.0, day_gain=50.0, day_pct=5.0)
    msft_rows, _ = rows_of(client, "MSFT")
    assert_group_fields(msft_rows[0], value=420.0, cost=400.0, gain=20.0,
                        pct=5.0, day_gain=20.0, day_pct=5.0)


def test_group_day_pct_is_ticker_move(client, fake_market):
    """group_day_gain_pct is the PRICE's daily move — identical on every
    row of the group (a % is position- and currency-independent), same
    rule as the per-row day_gain_pct."""
    seed_transaction(ticker="AAPL", price=100.0, qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", date="2026-08-02", price=110.0, qty=4,
                     tx_type="SELL")
    fake_market.quotes["AAPL"] = make_quote("AAPL", price=102.0,
                                            previous_close=100.0)

    buys, sells = rows_of(client, "AAPL")
    for row in (buys[0], sells[0]):
        assert row["group_day_gain_pct"] == pytest.approx(2.0)
        assert row["day_gain_pct"] == pytest.approx(2.0)
