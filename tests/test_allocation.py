# tests/test_allocation.py
# ========================
# Tests for get_profile() in market_data.py and GET /api/portfolio/allocation.
#
# Two contracts under test:
#   1. THE DATA LAYER (market_data.get_profile): a cached Ticker.info call
#      that returns {sector, industry, country, quote_type, exchange,
#      market_cap} with process-lifetime caching — the name-cache pattern.
#   2. THE ALLOCATION ROUTE: multi-dimension donut data, slicing the same
#      portfolio value by sector / industry / country / type / exchange /
#      cap / currency. Inherits every rule the summary already follows:
#        - long-only wedges (a short is a bet against, not an allocation)
#        - priced-only slices (an unpriced ticker is in no slice and
#          excluded from the denominator — a weight over a phantom
#          denominator misstates every holding that DID price)
#        - CAD display: USD values convert at the live rate
#        - excludes + note for unclassified/unpriced tickers (never
#          fabricated into an "Unknown" category)

from types import SimpleNamespace

import pytest

import db
import market_data
import app as app_module
from app import app


# ── Helpers ──────────────────────────────────────────────────────────────

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


def make_profile(sector=None, industry=None, country=None,
                 quote_type=None, exchange=None, market_cap=None):
    """A profile dict in exactly market_data.get_profile's shape."""
    return {
        "sector": sector,
        "industry": industry,
        "country": country,
        "quote_type": quote_type,
        "exchange": exchange,
        "market_cap": market_cap,
    }


@pytest.fixture(autouse=True)
def clean_caches():
    """Empty market_data's module-level caches before EVERY test in this
    file — same isolation rule as test_market_data.py's clean_caches."""
    market_data._cache.clear()
    market_data._name_cache.clear()
    if hasattr(market_data, "_profile_cache"):
        market_data._profile_cache.clear()
    yield
    market_data._cache.clear()
    market_data._name_cache.clear()
    if hasattr(market_data, "_profile_cache"):
        market_data._profile_cache.clear()


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the db layer at a throwaway SQLite file for one test."""
    test_db_path = tmp_path / "test_portfolio.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    db.init()
    return test_db_path


@pytest.fixture
def client(fresh_db):
    """A Flask test client wired to the throwaway database."""
    return app.test_client()


def seed(ticker, price, qty, tx_type="BUY", currency="CAD", fx_rate=1.0,
         date="2026-08-01"):
    """Insert a ledger row through the db layer (never raw SQL)."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


# ── Market data: get_profile ────────────────────────────────────────────

@pytest.fixture
def fake_yf(monkeypatch):
    """Replace market_data's `yf` with a controllable fake — same pattern
    as test_market_data.py but extended for profile info."""
    calls = []
    state = {
        "fast_info": {"lastPrice": 150.0, "previousClose": 145.0,
                      "currency": "USD"},
        "info": {
            "shortName": "Apple Inc",
            "longName": None,
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "country": "United States",
            "quoteType": "EQUITY",
            "exchange": "NMS",
            "marketCap": 2500000000000,
        },
        "history": None,
        "search": None,
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)
            self.fast_info = dict(state["fast_info"])

        @property
        def info(self):
            return dict(state["info"])

        def history(self, period=None, interval="1d", start=None, end=None):
            if period is not None:
                calls.append((self.symbol, period, interval))
            else:
                calls.append(("range", self.symbol, start, end))
            return state["history"]

    class FakeSearch:
        def __init__(self, query, max_results=8):
            calls.append(("search", query, max_results))
            self.quotes = state["search"]

    class FakeYf:
        Ticker = FakeTicker
        Search = FakeSearch

    monkeypatch.setattr(market_data, "yf", FakeYf)
    return SimpleNamespace(calls=calls, state=state)


def test_get_profile_extracts_and_renames_fields(fake_yf):
    """One .info call returns all six snake_case keys with correct
    Yahoo→snake_case translations."""
    profile = market_data.get_profile("AAPL")
    assert profile["sector"] == "Technology"
    assert profile["industry"] == "Consumer Electronics"
    assert profile["country"] == "United States"
    assert profile["quote_type"] == "EQUITY"
    assert profile["exchange"] == "NMS"
    assert profile["market_cap"] == 2500000000000


def test_get_profile_missing_fields_become_none(fake_yf):
    """Absent fields become None — not errors. Different security types
    legitimately lack different fields."""
    fake_yf.state["info"] = {"shortName": "Bitcoin"}
    profile = market_data.get_profile("BTC-USD")
    assert profile["sector"] is None
    assert profile["industry"] is None
    assert profile["country"] is None
    assert profile["quote_type"] is None
    assert profile["exchange"] is None
    assert profile["market_cap"] is None


def test_get_profile_is_cached_for_process_lifetime(fake_yf):
    """Two calls for the same symbol → ONE .info call. Process-lifetime
    cache means the network is never hit again after the first success."""
    market_data.get_profile("AAPL")
    market_data.get_profile("AAPL")
    # FakeTicker appends the symbol to calls on construction, and .info
    # is a property that returns from state. The call list records the
    # symbol string (not the property access), so two .info accesses
    # still produce ONE call entry.
    assert fake_yf.calls.count("AAPL") == 1


def test_get_profile_empty_profile_raises(fake_yf):
    """An empty info dict means Yahoo knows nothing — fail loudly with a
    named error instead of returning Nones that masquerade as facts."""
    fake_yf.state["info"] = {}
    with pytest.raises(ValueError, match="no profile data"):
        market_data.get_profile("DEAD")


# ── Allocation route: validation ────────────────────────────────────────

@pytest.fixture
def fake_market(monkeypatch):
    """Patch where app.py USES the names — same pattern as
    test_portfolio_summary.py, extended with get_profile."""
    quotes, names, stats = {}, {}, {}
    profiles = {}
    fx_rates, fx_on = {}, {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_name", lambda symbol: names[symbol])
    monkeypatch.setattr(app_module, "get_stats", lambda symbol: stats[symbol])
    monkeypatch.setattr(app_module, "get_profile",
                        lambda symbol: profiles[symbol])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: fx_rates[f"{base}{target}"])
    monkeypatch.setattr(app_module, "get_fx_rate_on",
                        lambda base, target, date_iso:
                            fx_on[(f"{base}{target}", date_iso)])
    return SimpleNamespace(quotes=quotes, names=names, stats=stats,
                           profiles=profiles, fx_rates=fx_rates, fx_on=fx_on)


def test_bad_dimension_returns_400_with_options(client, fake_market):
    """A by= value not in the whitelist must 400 with the valid options."""
    res = client.get("/api/portfolio/allocation?by=nonsense")
    assert res.status_code == 400
    body = res.get_json()
    assert "error" in body
    assert "sector" in body["error"]
    assert "currency" in body["error"]


def test_ticker_is_not_a_valid_by(client, fake_market):
    """The ticker view is served by the summary's holdings slice; the
    allocation endpoint rejects 'ticker' as a by key to prevent drift."""
    res = client.get("/api/portfolio/allocation?by=ticker")
    assert res.status_code == 400


def test_empty_ledger_returns_empty_slices(client, fake_market):
    """An empty ledger → no slices, no excluded. The donut shows its own
    empty state; the endpoint's job is to say so honestly."""
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"] == []
    assert body["excluded"] == []


# ── Allocation route: grouping math ─────────────────────────────────────

def test_sector_grouping_sums_and_sorts(client, fake_market):
    """Two tickers in one sector + one in another: the grouped sector's
    value is the sum of its holdings, weights divide by the total of
    classified slices, and the list is sorted value-descending."""
    seed("AAPL", 100.0, 10, currency="USD", fx_rate=1.30)
    seed("MSFT", 100.0, 5, currency="USD", fx_rate=1.30)
    seed("RY.TO", 100.0, 10)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 145.0, currency="USD")
    fake_market.quotes["MSFT"] = make_quote("MSFT", 100.0, 99.0, currency="USD")
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", 100.0, 98.0)
    fake_market.fx_rates["USDCAD"] = 1.30
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")
    fake_market.profiles["MSFT"] = make_profile(sector="Technology")
    fake_market.profiles["RY.TO"] = make_profile(sector="Financials")

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    slices = body["slices"]
    assert len(slices) == 2
    # Technology: 10×150×1.30 = 1950 + 5×100×1.30 = 650 → 2600
    # Financials: 10×100 = 1000
    assert slices[0]["key"] == "Technology"
    assert slices[0]["value"] == pytest.approx(2600.0)
    assert slices[0]["weight"] == pytest.approx(2600.0 / 3600.0)
    assert slices[1]["key"] == "Financials"
    assert slices[1]["value"] == pytest.approx(1000.0)
    assert slices[1]["weight"] == pytest.approx(1000.0 / 3600.0)
    assert sum(s["weight"] for s in slices) == pytest.approx(1.0, abs=1e-9)


def test_usd_converts_at_live_rate(client, fake_market):
    """A USD holding's slice is valued in CAD at the live rate."""
    seed("AAPL", 100.0, 10, currency="USD", fx_rate=1.30)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 145.0, currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.35
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"][0]["value"] == pytest.approx(10 * 150 * 1.35)


def test_currency_dimension_groups_by_quote_currency(client, fake_market):
    """Currency dimension classifies off quote currency — zero extra
    network, never calls get_profile."""
    seed("AAPL", 100.0, 10, currency="USD", fx_rate=1.30)
    seed("RY.TO", 100.0, 10)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 145.0, currency="USD")
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", 100.0, 98.0)
    fake_market.fx_rates["USDCAD"] = 1.30

    body = client.get("/api/portfolio/allocation?by=currency").get_json()
    slices = body["slices"]
    assert len(slices) == 2
    keys = {s["key"] for s in slices}
    assert keys == {"USD", "CAD"}
    # No profiles were needed for currency
    assert fake_market.profiles == {}


# ── Allocation route: resilience ─────────────────────────────────────────

def test_short_position_gets_no_wedge(client, fake_market):
    """A short (net qty < 0) is a bet against, not an allocation — it
    counts in the headline total but gets no wedge."""
    seed("RBC.TO", 150.0, 10)
    seed("SHORT.TO", 50.0, 4, tx_type="SELL", date="2026-08-01")
    fake_market.quotes["RBC.TO"] = make_quote("RBC.TO", 150.0, 148.0)
    fake_market.quotes["SHORT.TO"] = make_quote("SHORT.TO", 50.0, 49.0)
    fake_market.profiles["RBC.TO"] = make_profile(sector="Financials")
    fake_market.profiles["SHORT.TO"] = make_profile(sector="Technology")

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    # SHORT.TO gets no slice (net qty = -4), RBC.TO is the only wedge
    assert len(body["slices"]) == 1
    assert body["slices"][0]["key"] == "Financials"


def test_fully_sold_portfolio_has_no_slices(client, fake_market):
    """Buy 10, sell all 10 → net qty 0 → no slices at all."""
    seed("AAPL", 100.0, 10)
    seed("AAPL", 110.0, 10, tx_type="SELL", date="2026-08-05")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0)
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"] == []
    assert body["excluded"] == []


def test_unpriced_ticker_appears_in_excluded_with_reason(client, fake_market):
    """A dead ticker (quote failed) is excluded from slices and appears
    in the excluded list with a reason."""
    seed("AAPL", 100.0, 10)
    seed("DEAD.TO", 50.0, 10)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0)
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")
    # DEAD.TO absent from the quotes dict → get_quote raises → excluded

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert len(body["slices"]) == 1
    assert body["slices"][0]["key"] == "Technology"
    excluded_tickers = {e["ticker"] for e in body["excluded"]}
    assert "DEAD.TO" in excluded_tickers


def test_missing_sector_appears_in_excluded_with_reason(client, fake_market):
    """Profile fetched but sector field is None (e.g. crypto) → excluded
    from the sector view with a reason."""
    seed("BTC-USD", 50000.0, 0.1, currency="USD", fx_rate=1.30)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 50000.0, 49000.0,
                                                currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.30
    fake_market.profiles["BTC-USD"] = make_profile(sector=None)

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"] == []
    excluded_tickers = {e["ticker"] for e in body["excluded"]}
    assert "BTC-USD" in excluded_tickers


def test_profile_fetch_failure_excluded_with_reason(client, fake_market):
    """get_profile raises for one ticker → that ticker is excluded, the
    rest still slice normally."""
    seed("AAPL", 100.0, 10)
    seed("DEAD.TO", 50.0, 10)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0)
    fake_market.quotes["DEAD.TO"] = make_quote("DEAD.TO", 50.0, 49.0)
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")
    # DEAD.TO absent from profiles → get_profile raises

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert len(body["slices"]) == 1
    assert body["slices"][0]["key"] == "Technology"
    excluded_tickers = {e["ticker"] for e in body["excluded"]}
    assert "DEAD.TO" in excluded_tickers


def test_all_unclassified_returns_empty_slices_and_full_excluded_list(
        client, fake_market):
    """When EVERY ticker has no sector data, slices are empty and
    excluded lists everything."""
    seed("BTC-USD", 50000.0, 0.1, currency="USD", fx_rate=1.30)
    seed("ETH-USD", 3000.0, 1.0, currency="USD", fx_rate=1.30)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 50000.0, 49000.0,
                                                currency="USD")
    fake_market.quotes["ETH-USD"] = make_quote("ETH-USD", 3000.0, 2900.0,
                                                currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.30
    fake_market.profiles["BTC-USD"] = make_profile(sector=None)
    fake_market.profiles["ETH-USD"] = make_profile(sector=None)

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"] == []
    assert len(body["excluded"]) == 2


# ── Allocation route: cap buckets ───────────────────────────────────────

def test_cap_buckets_respect_thresholds(client, fake_market):
    """Holdings bucket by CAD-converted market cap: Large ≥ 10B, Mid
    2–10B, Small < 2B. Missing marketCap → excluded."""
    # Large: marketCap 25000B native → 25000 CAD (USD × live rate)
    seed("LARGE", 100.0, 10, currency="USD", fx_rate=1.30)
    # Mid: marketCap 5B
    seed("MID", 50.0, 10, currency="USD", fx_rate=1.30)
    # Small: marketCap 500M
    seed("SMALL", 20.0, 10, currency="USD", fx_rate=1.30)
    # No cap: excluded
    seed("NOCAP", 30.0, 10, currency="USD", fx_rate=1.30)

    fake_market.quotes["LARGE"] = make_quote("LARGE", 100.0, 99.0, currency="USD")
    fake_market.quotes["MID"] = make_quote("MID", 50.0, 49.0, currency="USD")
    fake_market.quotes["SMALL"] = make_quote("SMALL", 20.0, 19.0, currency="USD")
    fake_market.quotes["NOCAP"] = make_quote("NOCAP", 30.0, 29.0, currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.0  # 1:1 for easy threshold math

    fake_market.profiles["LARGE"] = make_profile(market_cap=25_000_000_000)
    fake_market.profiles["MID"] = make_profile(market_cap=5_000_000_000)
    fake_market.profiles["SMALL"] = make_profile(market_cap=500_000_000)
    fake_market.profiles["NOCAP"] = make_profile(market_cap=None)

    body = client.get("/api/portfolio/allocation?by=cap").get_json()
    keys = {s["key"] for s in body["slices"]}
    assert "Large" in keys
    assert "Mid" in keys
    assert "Small" in keys
    assert len(body["slices"]) == 3
    excluded_tickers = {e["ticker"] for e in body["excluded"]}
    assert "NOCAP" in excluded_tickers


def test_cap_missing_market_cap_excluded(client, fake_market):
    """A ticker with missing market_cap is excluded from the cap view
    with a reason."""
    seed("ETF.TO", 100.0, 10)
    fake_market.quotes["ETF.TO"] = make_quote("ETF.TO", 100.0, 98.0)
    fake_market.profiles["ETF.TO"] = make_profile(market_cap=None)

    body = client.get("/api/portfolio/allocation?by=cap").get_json()
    assert body["slices"] == []
    excluded_tickers = {e["ticker"] for e in body["excluded"]}
    assert "ETF.TO" in excluded_tickers


def test_weights_sum_to_one_over_classified_slices_only(client, fake_market):
    """An excluded ticker's value does NOT enter the denominator — weights
    divide by the sum of CLASSIFIED slices only."""
    seed("AAPL", 100.0, 10)
    seed("BTC-USD", 50000.0, 0.1, currency="USD", fx_rate=1.30)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 50000.0, 49000.0,
                                                currency="USD")
    fake_market.fx_rates["USDCAD"] = 1.30
    fake_market.profiles["AAPL"] = make_profile(sector="Technology")
    fake_market.profiles["BTC-USD"] = make_profile(sector=None)

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert len(body["slices"]) == 1
    assert body["slices"][0]["weight"] == pytest.approx(1.0)


def test_slice_values_descending(client, fake_market):
    """Slices are sorted value-descending so the donut legend reads
    biggest-first."""
    seed("BIG", 100.0, 20)
    seed("SMALL", 100.0, 5)
    fake_market.quotes["BIG"] = make_quote("BIG", 100.0, 98.0)
    fake_market.quotes["SMALL"] = make_quote("SMALL", 100.0, 99.0)
    fake_market.profiles["BIG"] = make_profile(sector="Financials")
    fake_market.profiles["SMALL"] = make_profile(sector="Technology")

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert body["slices"][0]["key"] == "Financials"
    assert body["slices"][0]["value"] > body["slices"][1]["value"]
