# tests/test_fund_allocation.py
# =============================
# Tests for the fund look-through behind the allocation donut (#62):
#   * market_data.get_profile's fund mixes (asset_mix/sector_mix) from
#     yfinance FundsData, with successes-only caching and a degraded flag
#   * GET /api/portfolio/allocation splitting a fund across its composition
#   * the n/a / Unknown wedges and the unclassified list
#
# Inherits the allocation route's contracts: long-only, priced-only, CAD
# conversion, weights over the summed wedges, honest excluded[].

from types import SimpleNamespace

import pytest

import db
import market_data
import app as app_module
from app import app


def make_quote(symbol, price, previous_close, currency="CAD"):
    return {
        "symbol": symbol, "price": price, "previous_close": previous_close,
        "currency": currency, "change": price - previous_close,
        "change_pct": (price - previous_close) / previous_close * 100,
    }


def make_profile(sector=None, country=None, quote_type=None, market_cap=None,
                 asset_mix=None, sector_mix=None, fund_degraded=False):
    return {
        "sector": sector, "country": country, "quote_type": quote_type,
        "market_cap": market_cap, "asset_mix": asset_mix,
        "sector_mix": sector_mix, "fund_degraded": fund_degraded,
    }


def seed(ticker, price, qty, tx_type="BUY", currency="CAD", fx_rate=1.0,
         date="2026-08-01"):
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate, portfolio_id=1)


@pytest.fixture
def fake_market(monkeypatch):
    quotes, profiles = {}, {}
    fx_rates = {}
    monkeypatch.setattr(app_module, "get_quote", lambda s: quotes[s])
    monkeypatch.setattr(app_module, "get_profile", lambda s: profiles[s])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda b, t: fx_rates[f"{b}{t}"])
    return SimpleNamespace(quotes=quotes, profiles=profiles, fx_rates=fx_rates)


def _keys(body):
    return {s["key"] for s in body["slices"]}


def _weight(body, key):
    for s in body["slices"]:
        if s["key"] == key:
            return s["weight"]
    return None


# ── Route: asset class look-through ──────────────────────────────────────

def test_fund_splits_across_asset_mix(client, fake_market):
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.4})

    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Stocks", "Bonds"}
    assert _weight(body, "Stocks") == pytest.approx(0.6)
    assert _weight(body, "Bonds") == pytest.approx(0.4)
    assert sum(s["weight"] for s in body["slices"]) == pytest.approx(1.0)
    assert body["unclassified"] == []


def test_asset_class_maps_non_funds(client, fake_market):
    seed("AAPL", 100.0, 1)
    seed("BTC-USD", 100.0, 1)
    seed("GOLD", 100.0, 1)
    seed("FX", 100.0, 1)
    seed("BOND", 100.0, 1)
    for sym in ("AAPL", "BTC-USD", "GOLD", "FX", "BOND"):
        fake_market.quotes[sym] = make_quote(sym, 100.0, 99.0)
    fake_market.profiles["AAPL"] = make_profile(quote_type="EQUITY")
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")
    fake_market.profiles["GOLD"] = make_profile(quote_type="FUTURE")
    fake_market.profiles["FX"] = make_profile(quote_type="CURRENCY")
    fake_market.profiles["BOND"] = make_profile(quote_type="BOND")

    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Stocks", "Crypto", "Commodities", "Cash", "Bonds"}


def test_fund_without_mix_is_unknown_asset_class(client, fake_market):
    seed("ETF.TO", 100.0, 1)
    fake_market.quotes["ETF.TO"] = make_quote("ETF.TO", 100.0, 99.0)
    fake_market.profiles["ETF.TO"] = make_profile(quote_type="ETF")
    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Unknown"}
    assert body["unclassified"] == [
        {"ticker": "ETF.TO", "reason": "no asset-class data"}]


# ── Route: sector look-through + sleeve ──────────────────────────────────

def test_equity_fund_sector_look_through(client, fake_market):
    seed("SPY", 100.0, 1)
    fake_market.quotes["SPY"] = make_quote("SPY", 100.0, 99.0)
    fake_market.profiles["SPY"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 1.0},
        sector_mix={"Technology": 0.7, "Healthcare": 0.3})

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"Technology", "Healthcare"}
    assert _weight(body, "Technology") == pytest.approx(0.7)
    assert body["unclassified"] == []


def test_mixed_fund_sector_sleeve_goes_to_na(client, fake_market):
    """A 60/40 fund's sector weights cover only the equity sleeve: 60% across
    sectors, 40% to the n/a (non-equity) wedge — never 100% on equities."""
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.4},
        sector_mix={"Technology": 1.0})

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _weight(body, "Technology") == pytest.approx(0.6)
    assert _weight(body, "n/a") == pytest.approx(0.4)
    assert body["unclassified"] == [
        {"ticker": "BAL",
         "reason": "sector not applicable to non-equity holdings"}]


def test_bond_only_fund_with_stray_sector_mix_is_na(client, fake_market):
    seed("BND", 100.0, 1)
    fake_market.quotes["BND"] = make_quote("BND", 100.0, 99.0)
    fake_market.profiles["BND"] = make_profile(
        quote_type="ETF", asset_mix={"Bonds": 1.0},
        sector_mix={"Technology": 1.0})
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"n/a"}


def test_crypto_sector_is_na(client, fake_market):
    seed("BTC-USD", 100.0, 1)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 100.0, 99.0)
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"n/a"}
    assert body["unclassified"] == [
        {"ticker": "BTC-USD", "reason": "sector not applicable"}]


def test_equity_without_sector_is_unknown(client, fake_market):
    seed("XYZ", 100.0, 1)
    fake_market.quotes["XYZ"] = make_quote("XYZ", 100.0, 99.0)
    fake_market.profiles["XYZ"] = make_profile(quote_type="EQUITY")
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"Unknown"}
    assert body["unclassified"] == [
        {"ticker": "XYZ", "reason": "no sector data"}]


# ── Route: country ───────────────────────────────────────────────────────

def test_country_matrix(client, fake_market):
    seed("AAPL", 100.0, 1)
    seed("NOCTRY", 100.0, 1)
    seed("VEQT", 100.0, 1)
    seed("GLD", 100.0, 1)
    seed("BTC-USD", 100.0, 1)
    for sym in ("AAPL", "NOCTRY", "VEQT", "GLD", "BTC-USD"):
        fake_market.quotes[sym] = make_quote(sym, 100.0, 99.0)
    fake_market.profiles["AAPL"] = make_profile(
        quote_type="EQUITY", country="United States")
    fake_market.profiles["NOCTRY"] = make_profile(quote_type="EQUITY")
    fake_market.profiles["VEQT"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 1.0})
    fake_market.profiles["GLD"] = make_profile(
        quote_type="ETF", asset_mix={"Commodities": 1.0})
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")

    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert _keys(body) == {"United States", "Unknown", "n/a"}
    reasons = {e["ticker"]: e["reason"] for e in body["unclassified"]}
    assert reasons["NOCTRY"] == "no country data"
    assert reasons["VEQT"] == "no country data"
    assert reasons["GLD"] == "country not applicable"
    assert reasons["BTC-USD"] == "country not applicable"
    assert "AAPL" not in reasons


def test_type_friendly_labels(client, fake_market):
    seed("AAPL", 100.0, 1)
    seed("BTC-USD", 100.0, 1)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 100.0, 99.0)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 100.0, 99.0)
    fake_market.profiles["AAPL"] = make_profile(quote_type="EQUITY")
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")
    body = client.get("/api/portfolio/allocation?by=type").get_json()
    assert _keys(body) == {"Stock", "Crypto"}
    assert body["unclassified"] == []


def test_cap_and_currency_never_unclassified(client, fake_market):
    seed("AAPL", 100.0, 1)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 100.0, 99.0)
    fake_market.profiles["AAPL"] = make_profile(
        quote_type="EQUITY", market_cap=25_000_000_000)
    for by in ("cap", "currency"):
        body = client.get(f"/api/portfolio/allocation?by={by}").get_json()
        assert body["unclassified"] == []


# ── Route: manual override precedence ────────────────────────────────────

def test_override_replaces_unknown_and_delete_reverts(client, fake_market):
    seed("VEQT", 100.0, 1)
    fake_market.quotes["VEQT"] = make_quote("VEQT", 100.0, 99.0)
    fake_market.profiles["VEQT"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 1.0})

    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert _keys(body) == {"Unknown"}

    db.set_classification_override(
        "VEQT", "country", {"Canada": 0.3, "United States": 0.7})
    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert _keys(body) == {"United States", "Canada"}
    assert _weight(body, "United States") == pytest.approx(0.7)
    assert body["unclassified"] == []

    db.delete_classification_override("VEQT", "country")
    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert _keys(body) == {"Unknown"}


def test_override_only_touches_its_dimension(client, fake_market):
    seed("VEQT", 100.0, 1)
    fake_market.quotes["VEQT"] = make_quote("VEQT", 100.0, 99.0)
    fake_market.profiles["VEQT"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 1.0},
        sector_mix={"Technology": 1.0})
    db.set_classification_override("VEQT", "country", {"Canada": 1.0})

    sector = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(sector) == {"Technology"}
    country = client.get("/api/portfolio/allocation?by=country").get_json()
    assert _keys(country) == {"Canada"}


# ── Route: edges and resilience ──────────────────────────────────────────

def test_empty_ledger_returns_three_empty_lists(client, fake_market):
    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert body["slices"] == []
    assert body["unclassified"] == []
    assert body["excluded"] == []


def test_asset_class_is_accepted(client, fake_market):
    res = client.get("/api/portfolio/allocation?by=asset_class")
    assert res.status_code == 200


def test_short_and_zero_positions_get_no_slice(client, fake_market):
    seed("LONG", 100.0, 10)
    seed("SHORT", 100.0, 4, tx_type="SELL")
    seed("FLAT", 100.0, 5)
    seed("FLAT", 100.0, 5, tx_type="SELL", date="2026-08-02")
    for sym in ("LONG", "SHORT", "FLAT"):
        fake_market.quotes[sym] = make_quote(sym, 100.0, 99.0)
        fake_market.profiles[sym] = make_profile(quote_type="EQUITY")
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    tickers = {e["ticker"] for e in body["unclassified"]}
    assert tickers == {"LONG"}
    excluded = {e["ticker"] for e in body["excluded"]}
    assert "SHORT" not in excluded and "FLAT" not in excluded


def test_override_cannot_resurrect_unpriced_holding(client, fake_market):
    seed("DEAD", 100.0, 1)
    # No quote → excluded, even with an override stored.
    db.set_classification_override("DEAD", "country", {"Canada": 1.0})
    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert body["slices"] == []
    assert {e["ticker"] for e in body["excluded"]} == {"DEAD"}


def test_no_nan_in_reply_with_sparse_fund(client, fake_market):
    seed("SPARSE", 100.0, 1)
    fake_market.quotes["SPARSE"] = make_quote("SPARSE", 100.0, 99.0)
    fake_market.profiles["SPARSE"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 1.0})
    res = client.get("/api/portfolio/allocation?by=asset_class")
    assert b"NaN" not in res.data


# ── Data layer: get_profile fund mixes ───────────────────────────────────

@pytest.fixture
def fake_yf(monkeypatch):
    state = {
        "info": {"quoteType": "ETF", "sector": None, "country": None,
                 "marketCap": None},
        "fund_error": False,
        "asset_classes": {"stockPosition": 0.6, "bondPosition": 0.4},
        "sector_weightings": {"technology": 0.7, "healthcare": 0.3},
        "category_name": "Balanced",
        "info_fetches": 0,
        "fund_fetches": 0,
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            state["info_fetches"] += 1
            return dict(state["info"])

        @property
        def funds_data(self):
            state["fund_fetches"] += 1
            if state["fund_error"]:
                raise RuntimeError("fund boom")
            return SimpleNamespace(
                asset_classes=state["asset_classes"],
                sector_weightings=state["sector_weightings"],
                fund_overview={"categoryName": state["category_name"]},
            )

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)
    return state


def test_get_profile_funds_fold_mixes(fake_yf):
    profile = market_data.get_profile("BAL")
    assert profile["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.4}
    assert profile["sector_mix"] == {"Technology": 0.7, "Healthcare": 0.3}
    assert profile["fund_degraded"] is False


def test_get_profile_fund_fetch_cached(fake_yf):
    market_data.get_profile("BAL")
    market_data.get_profile("BAL")
    assert fake_yf["fund_fetches"] == 1
    assert fake_yf["info_fetches"] == 1


def test_get_profile_fund_failure_degrades_and_retries(fake_yf):
    fake_yf["fund_error"] = True
    first = market_data.get_profile("BAL")
    assert first["asset_mix"] is None
    assert first["sector_mix"] is None
    assert first["fund_degraded"] is True

    # A failure is not cached: the next call retries and succeeds.
    fake_yf["fund_error"] = False
    second = market_data.get_profile("BAL")
    assert second["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.4}
    assert second["fund_degraded"] is False
    assert fake_yf["fund_fetches"] == 2


def test_get_profile_non_fund_never_touches_funds_data(fake_yf):
    fake_yf["info"] = {"quoteType": "EQUITY", "sector": "Technology",
                       "country": "United States", "marketCap": 100}
    profile = market_data.get_profile("AAPL")
    assert profile["asset_mix"] is None
    assert profile["sector_mix"] is None
    assert profile["fund_degraded"] is False
    assert fake_yf["fund_fetches"] == 0


def test_get_profile_sparse_fund_data_is_none(fake_yf):
    fake_yf["asset_classes"] = None
    fake_yf["sector_weightings"] = {}
    profile = market_data.get_profile("BAL")
    assert profile["asset_mix"] is None
    assert profile["sector_mix"] is None
    assert profile["fund_degraded"] is False


def test_get_profile_commodity_other_maps_by_category(fake_yf):
    fake_yf["asset_classes"] = {"otherPosition": 1.0}
    fake_yf["sector_weightings"] = {}
    fake_yf["category_name"] = "Commodities Focused"
    profile = market_data.get_profile("GLD")
    assert profile["asset_mix"] == {"Commodities": 1.0}
