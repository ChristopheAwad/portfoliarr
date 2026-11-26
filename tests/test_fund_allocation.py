# tests/test_fund_allocation.py
# =============================
# Tests for the fund look-through behind the allocation donut (#62):
#   * market_data.get_profile's fund mixes (asset_mix/sector_mix) from
#     yfinance FundsData, with successes-only caching and a degraded flag
#   * GET /api/portfolio/allocation splitting a fund across its composition
#   * the n/a / Unknown wedges and the unclassified list
#
# Inherits the allocation route's contracts: one priced-long CAD base,
# long-only, CAD conversion, reported fund weights that are never scaled
# up, finite valid fractions summing to 1 or less, and an honest
# excluded[] for longs without a usable CAD value.

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


def _slice(body, key):
    matches = [s for s in body["slices"] if s["key"] == key]
    assert len(matches) <= 1, f"duplicate slice key {key!r}: {matches}"
    return matches[0] if matches else None


def _status(body, key):
    part = _slice(body, key)
    return None if part is None else part["status"]


def _value(body, key):
    part = _slice(body, key)
    return None if part is None else part["value"]


def _assert_coverage(coverage, priced_value, classified=0.0, unknown=0.0,
                     na=0.0):
    assert coverage["priced_value"] == pytest.approx(priced_value)
    if priced_value == 0:
        assert coverage["classified_weight"] is None
        assert coverage["unknown_weight"] is None
        assert coverage["not_applicable_weight"] is None
        return
    assert coverage["classified_weight"] == pytest.approx(
        classified / priced_value)
    assert coverage["unknown_weight"] == pytest.approx(unknown / priced_value)
    assert coverage["not_applicable_weight"] == pytest.approx(
        na / priced_value)


# ── Route: asset class look-through ──────────────────────────────────────

def test_fund_splits_across_asset_mix(client, fake_market):
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.4})

    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Stocks", "Bonds"}
    assert _status(body, "Stocks") == "classified"
    assert _status(body, "Bonds") == "classified"
    assert _weight(body, "Stocks") == pytest.approx(0.6)
    assert _weight(body, "Bonds") == pytest.approx(0.4)
    assert sum(s["weight"] for s in body["slices"]) == pytest.approx(1.0)
    assert body["unclassified"] == []
    assert body["excluded"] == []
    _assert_coverage(body["coverage"], 1000.0, classified=1000.0)


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
    assert all(s["status"] == "classified" for s in body["slices"])
    assert body["unclassified"] == []
    _assert_coverage(body["coverage"], 500.0, classified=500.0)


def test_fund_without_mix_is_unknown_asset_class(client, fake_market):
    seed("ETF.TO", 100.0, 1)
    fake_market.quotes["ETF.TO"] = make_quote("ETF.TO", 100.0, 99.0)
    fake_market.profiles["ETF.TO"] = make_profile(quote_type="ETF")
    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Unknown"}
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [
        {"ticker": "ETF.TO", "reason": "no asset-class data"}]
    _assert_coverage(body["coverage"], 100.0, unknown=100.0)


def test_partial_asset_mix_is_not_scaled_up(client, fake_market):
    """90% reported stays 90%; the missing 10% is a visible Unknown wedge."""
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.3})

    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _value(body, "Stocks") == pytest.approx(600.0)
    assert _value(body, "Bonds") == pytest.approx(300.0)
    assert _value(body, "Unknown") == pytest.approx(100.0)
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [
        {"ticker": "BAL", "reason": "incomplete asset-class data"}]
    _assert_coverage(body["coverage"], 1000.0, classified=900.0,
                     unknown=100.0)


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
    assert all(s["status"] == "classified" for s in body["slices"])
    assert body["unclassified"] == []
    _assert_coverage(body["coverage"], 100.0, classified=100.0)


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
    assert _status(body, "Technology") == "classified"
    assert _weight(body, "n/a") == pytest.approx(0.4)
    assert _status(body, "n/a") == "not_applicable"
    assert body["unclassified"] == [
        {"ticker": "BAL",
         "reason": "sector not applicable to non-equity holdings"}]
    _assert_coverage(body["coverage"], 1000.0, classified=600.0, na=400.0)


def test_partial_sector_mix_is_not_scaled_up(client, fake_market):
    """The ETF's 80% sector report covers 80% of its 60% stock sleeve:
    48% classified, 30% confirmed bonds n/a, and 22% Unknown (12% missing
    sector data inside the sleeve plus the 10% unreported NAV)."""
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.3},
        sector_mix={"Technology": 0.8})

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _value(body, "Technology") == pytest.approx(480.0)
    assert _status(body, "Technology") == "classified"
    assert _value(body, "n/a") == pytest.approx(300.0)
    assert _status(body, "n/a") == "not_applicable"
    assert _value(body, "Unknown") == pytest.approx(220.0)
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [{
        "ticker": "BAL",
        "reason": ("incomplete asset-class data; incomplete sector data; "
                   "sector not applicable to non-equity holdings"),
    }]
    _assert_coverage(body["coverage"], 1000.0, classified=480.0,
                     unknown=220.0, na=300.0)


def test_bond_only_fund_with_stray_sector_mix_is_na(client, fake_market):
    seed("BND", 100.0, 1)
    fake_market.quotes["BND"] = make_quote("BND", 100.0, 99.0)
    fake_market.profiles["BND"] = make_profile(
        quote_type="ETF", asset_mix={"Bonds": 1.0},
        sector_mix={"Technology": 1.0})
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"n/a"}
    assert _status(body, "n/a") == "not_applicable"
    _assert_coverage(body["coverage"], 100.0, na=100.0)


def test_fund_sector_without_asset_mix_is_all_unknown(client, fake_market):
    """No usable asset mix means no equity split: reported sectors are not
    allowed to claim the whole fund."""
    seed("ETF.TO", 100.0, 10)
    fake_market.quotes["ETF.TO"] = make_quote("ETF.TO", 100.0, 99.0)
    fake_market.profiles["ETF.TO"] = make_profile(
        quote_type="ETF", sector_mix={"Technology": 1.0})

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"Unknown"}
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [
        {"ticker": "ETF.TO", "reason": "no asset-class data"}]
    _assert_coverage(body["coverage"], 1000.0, unknown=1000.0)


def test_fund_sector_without_stock_sleeve_keeps_confirmed_nonstock_na(
        client, fake_market):
    """No Stocks split: confirmed Bonds are n/a, while Preferred/Other do
    not prove the sector concept is inapplicable, so they stay Unknown."""
    seed("BAL", 100.0, 10)
    fake_market.quotes["BAL"] = make_quote("BAL", 100.0, 99.0)
    fake_market.profiles["BAL"] = make_profile(
        quote_type="ETF", asset_mix={"Bonds": 0.3, "Other": 0.3},
        sector_mix={"Technology": 1.0})

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"n/a", "Unknown"}
    assert _value(body, "n/a") == pytest.approx(300.0)
    assert _status(body, "n/a") == "not_applicable"
    assert _value(body, "Unknown") == pytest.approx(700.0)
    assert _status(body, "Unknown") == "unknown"
    _assert_coverage(body["coverage"], 1000.0, unknown=700.0, na=300.0)


def test_only_confirmed_non_stock_mix_labels_are_na(client, fake_market):
    """Bonds, Cash, Convertible, Commodities and Crypto prove n/a; the
    Preferred / Real Estate / Other remainder does not."""
    seed("MIX", 100.0, 10)
    fake_market.quotes["MIX"] = make_quote("MIX", 100.0, 99.0)
    fake_market.profiles["MIX"] = make_profile(
        quote_type="ETF",
        asset_mix={
            "Stocks": 0.1, "Bonds": 0.1, "Cash": 0.1,
            "Convertible": 0.1, "Commodities": 0.1, "Crypto": 0.1,
            "Preferred": 0.1, "Real Estate": 0.1, "Other": 0.1,
        })

    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _value(body, "n/a") == pytest.approx(500.0)
    assert _status(body, "n/a") == "not_applicable"
    assert _value(body, "Unknown") == pytest.approx(500.0)
    assert _status(body, "Unknown") == "unknown"
    _assert_coverage(body["coverage"], 1000.0, unknown=500.0, na=500.0)


def test_crypto_sector_is_na(client, fake_market):
    seed("BTC-USD", 100.0, 1)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 100.0, 99.0)
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"n/a"}
    assert _status(body, "n/a") == "not_applicable"
    assert body["unclassified"] == [
        {"ticker": "BTC-USD", "reason": "sector not applicable"}]
    _assert_coverage(body["coverage"], 100.0, na=100.0)


def test_equity_without_sector_is_unknown(client, fake_market):
    seed("XYZ", 100.0, 1)
    fake_market.quotes["XYZ"] = make_quote("XYZ", 100.0, 99.0)
    fake_market.profiles["XYZ"] = make_profile(quote_type="EQUITY")
    body = client.get("/api/portfolio/allocation?by=sector").get_json()
    assert _keys(body) == {"Unknown"}
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [
        {"ticker": "XYZ", "reason": "no sector data"}]
    _assert_coverage(body["coverage"], 100.0, unknown=100.0)


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
    assert _status(body, "United States") == "classified"
    assert _status(body, "Unknown") == "unknown"
    assert _status(body, "n/a") == "not_applicable"
    reasons = {e["ticker"]: e["reason"] for e in body["unclassified"]}
    assert reasons["NOCTRY"] == "no country data"
    assert reasons["VEQT"] == "no country data"
    assert reasons["GLD"] == "country not applicable"
    assert reasons["BTC-USD"] == "country not applicable"
    assert "AAPL" not in reasons
    _assert_coverage(body["coverage"], 500.0, classified=100.0,
                     unknown=200.0, na=200.0)


def test_etf_domicile_is_ignored_and_countryless_sleeves_are_na(
        client, fake_market):
    """A fund's own country is a domicile, never an issuer country. Only
    confirmed commodity/crypto sleeves are n/a; the rest stays Unknown."""
    seed("ETF.TO", 100.0, 10)
    fake_market.quotes["ETF.TO"] = make_quote("ETF.TO", 100.0, 99.0)
    fake_market.profiles["ETF.TO"] = make_profile(
        quote_type="ETF", country="Canada",
        asset_mix={"Commodities": 0.2, "Crypto": 0.1, "Bonds": 0.7})

    body = client.get("/api/portfolio/allocation?by=country").get_json()
    assert "Canada" not in _keys(body)
    assert _value(body, "n/a") == pytest.approx(300.0)
    assert _status(body, "n/a") == "not_applicable"
    assert _value(body, "Unknown") == pytest.approx(700.0)
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [{
        "ticker": "ETF.TO",
        "reason": "country not applicable; no country data",
    }]
    _assert_coverage(body["coverage"], 1000.0, unknown=700.0, na=300.0)


def test_type_friendly_labels(client, fake_market):
    seed("AAPL", 100.0, 1)
    seed("BTC-USD", 100.0, 1)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 100.0, 99.0)
    fake_market.quotes["BTC-USD"] = make_quote("BTC-USD", 100.0, 99.0)
    fake_market.profiles["AAPL"] = make_profile(quote_type="EQUITY")
    fake_market.profiles["BTC-USD"] = make_profile(quote_type="CRYPTOCURRENCY")
    body = client.get("/api/portfolio/allocation?by=type").get_json()
    assert _keys(body) == {"Stock", "Crypto"}
    assert all(s["status"] == "classified" for s in body["slices"])
    assert body["unclassified"] == []
    _assert_coverage(body["coverage"], 200.0, classified=200.0)


# ── Route: company size (cap) and currency ──────────────────────────────

def test_company_size_never_uses_etf_aum_or_crypto_market_cap(
        client, fake_market):
    """Known non-equities are n/a even when the provider sends a cap: an
    ETF's AUM and a crypto's market cap are not company sizes. An unknown
    type stays Unknown, and a direct equity keeps its CAD bucket."""
    seed("ETF.TO", 100.0, 10)
    seed("BTC-USD", 100.0, 10)
    seed("FUT", 100.0, 10)
    seed("ODD", 100.0, 10)
    seed("STOCK", 100.0, 10)
    for sym in ("ETF.TO", "BTC-USD", "FUT", "ODD", "STOCK"):
        fake_market.quotes[sym] = make_quote(sym, 100.0, 99.0)
    fake_market.profiles["ETF.TO"] = make_profile(
        quote_type="ETF", market_cap=999_000_000_000)
    fake_market.profiles["BTC-USD"] = make_profile(
        quote_type="CRYPTOCURRENCY", market_cap=999_000_000_000)
    fake_market.profiles["FUT"] = make_profile(
        quote_type="FUTURE", market_cap=999_000_000_000)
    fake_market.profiles["ODD"] = make_profile(
        quote_type="WEIRD", market_cap=999_000_000_000)
    fake_market.profiles["STOCK"] = make_profile(
        quote_type="EQUITY", market_cap=25_000_000_000)

    body = client.get("/api/portfolio/allocation?by=cap").get_json()
    assert _keys(body) == {"n/a", "Unknown", "Large"}
    assert _value(body, "n/a") == pytest.approx(3000.0)
    assert _status(body, "n/a") == "not_applicable"
    assert _value(body, "Unknown") == pytest.approx(1000.0)
    assert _status(body, "Unknown") == "unknown"
    assert _value(body, "Large") == pytest.approx(1000.0)
    assert _status(body, "Large") == "classified"
    reasons = {e["ticker"]: e["reason"] for e in body["unclassified"]}
    assert reasons == {
        "BTC-USD": "company size not applicable",
        "ETF.TO": "company size not applicable",
        "FUT": "company size not applicable",
        "ODD": "no company-size data",
    }
    _assert_coverage(body["coverage"], 5000.0, classified=1000.0,
                     unknown=1000.0, na=3000.0)


def test_equity_without_cap_is_unknown(client, fake_market):
    seed("NOCAP", 100.0, 10)
    fake_market.quotes["NOCAP"] = make_quote("NOCAP", 100.0, 99.0)
    fake_market.profiles["NOCAP"] = make_profile(
        quote_type="EQUITY", market_cap=None)

    body = client.get("/api/portfolio/allocation?by=cap").get_json()
    assert _keys(body) == {"Unknown"}
    assert _status(body, "Unknown") == "unknown"
    assert body["unclassified"] == [
        {"ticker": "NOCAP", "reason": "no market-cap data"}]
    assert body["excluded"] == []
    _assert_coverage(body["coverage"], 1000.0, unknown=1000.0)


def test_currency_never_has_unclassified(client, fake_market):
    seed("AAPL", 100.0, 10, currency="USD", fx_rate=1.30)
    seed("RY.TO", 100.0, 10)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 145.0,
                                            currency="USD")
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", 100.0, 98.0)
    fake_market.fx_rates["USDCAD"] = 1.30

    body = client.get("/api/portfolio/allocation?by=currency").get_json()
    assert _keys(body) == {"USD", "CAD"}
    assert all(s["status"] == "classified" for s in body["slices"])
    assert body["unclassified"] == []
    assert body["excluded"] == []
    assert fake_market.profiles == {}
    _assert_coverage(body["coverage"], 2950.0, classified=2950.0)


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
    assert all(s["status"] == "classified" for s in body["slices"])
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


def test_override_replaces_partial_fund_asset_mix(client, fake_market):
    """The owner override replaces the whole mix, so the partial fund's
    Unknown residual disappears until the override is deleted."""
    seed("VEQT", 100.0, 10)
    fake_market.quotes["VEQT"] = make_quote("VEQT", 100.0, 99.0)
    fake_market.profiles["VEQT"] = make_profile(
        quote_type="ETF", asset_mix={"Stocks": 0.6, "Bonds": 0.3})

    partial = client.get(
        "/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(partial) == {"Stocks", "Bonds", "Unknown"}

    db.set_classification_override(
        "VEQT", "asset", {"Stocks": 0.8, "Bonds": 0.2})
    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(body) == {"Stocks", "Bonds"}
    assert _value(body, "Stocks") == pytest.approx(800.0)
    assert _value(body, "Bonds") == pytest.approx(200.0)
    assert all(s["status"] == "classified" for s in body["slices"])
    assert body["unclassified"] == []
    _assert_coverage(body["coverage"], 1000.0, classified=1000.0)

    db.delete_classification_override("VEQT", "asset")
    restored = client.get(
        "/api/portfolio/allocation?by=asset_class").get_json()
    assert _keys(restored) == {"Stocks", "Bonds", "Unknown"}


# ── Route: edges and resilience ──────────────────────────────────────────

def test_empty_ledger_returns_three_empty_lists(client, fake_market):
    body = client.get("/api/portfolio/allocation?by=asset_class").get_json()
    assert body["slices"] == []
    assert body["unclassified"] == []
    assert body["excluded"] == []
    _assert_coverage(body["coverage"], 0.0)


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


# ── Data layer: raw provider fraction folding ───────────────────────────

def test_fold_asset_classes_keeps_complete_mix():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "bondPosition": 0.4}, "Balanced") == {
            "Stocks": 0.6, "Bonds": 0.4}


def test_fold_asset_classes_keeps_partial_mix_unscaled():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "bondPosition": 0.3}, "Balanced") == {
            "Stocks": 0.6, "Bonds": 0.3}


def test_fold_asset_classes_skips_missing_and_zero_cells():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "bondPosition": None, "cashPosition": 0.0},
        None) == {"Stocks": 0.6}


def test_fold_asset_classes_rejects_negative_cells():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "bondPosition": -0.1}, None) is None
    # An unmapped negative cell invalidates the mix too.
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "mysteryPosition": -0.1}, None) is None


@pytest.mark.parametrize("bad", [
    float("nan"), float("inf"), float("-inf"), "0.6", True, object(),
])
def test_fold_asset_classes_rejects_malformed_cells(bad):
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.6, "bondPosition": bad}, None) is None


def test_fold_asset_classes_rejects_material_overage():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.7, "bondPosition": 0.4}, None) is None


@pytest.mark.parametrize("raw", [
    {"stockPosition": 0.5005, "bondPosition": 0.5004},
    {"stockPosition": 0.5005, "bondPosition": 0.5005},
])
def test_fold_asset_classes_shaves_tiny_rounding_overage(raw):
    folded = market_data._fold_asset_classes(raw, None)
    assert folded is not None
    assert sum(folded.values()) == pytest.approx(1.0)


def test_fold_asset_classes_rejects_overage_above_ceiling():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.5006, "bondPosition": 0.5005}, None) is None


def test_fold_asset_classes_counts_unmapped_weights_but_omits_them():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.5, "mysteryPosition": 0.2}, None) == {
            "Stocks": 0.5}
    # All positive weight is unmapped: no usable asset mix.
    assert market_data._fold_asset_classes(
        {"mysteryPosition": 0.2}, None) is None
    # Known + unmapped total above the ceiling still invalidates.
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.9, "mysteryPosition": 0.2}, None) is None


def test_fold_asset_classes_preserves_other_and_category_refinements():
    assert market_data._fold_asset_classes(
        {"stockPosition": 0.7, "otherPosition": 0.2}, "Balanced") == {
            "Stocks": 0.7, "Other": 0.2}
    assert market_data._fold_asset_classes(
        {"otherPosition": 0.2}, "Commodities Focused") == {
            "Commodities": 0.2}
    assert market_data._fold_asset_classes(
        {"otherPosition": 0.2}, "Digital Assets") == {"Crypto": 0.2}
    assert market_data._fold_asset_classes(
        {"otherPosition": 0.2}, "Real Estate Focused") == {
            "Real Estate": 0.2}


def test_fold_sector_weightings_keeps_partial_mix_unscaled():
    assert market_data._fold_sector_weightings(
        {"technology": 0.4, "healthcare": 0.3}) == {
            "Technology": 0.4, "Healthcare": 0.3}


def test_fold_sector_weightings_skips_missing_and_zero_cells():
    assert market_data._fold_sector_weightings(
        {"technology": 0.4, "healthcare": None, "energy": 0.0}) == {
            "Technology": 0.4}


@pytest.mark.parametrize("bad", [
    -0.1, float("nan"), float("inf"), "0.4", True,
])
def test_fold_sector_weightings_rejects_bad_cells(bad):
    assert market_data._fold_sector_weightings(
        {"technology": 0.4, "healthcare": bad}) is None


def test_fold_sector_weightings_uses_raw_total_for_validation():
    assert market_data._fold_sector_weightings(
        {"technology": 0.5, "mystery": 0.2}) == {"Technology": 0.5}
    assert market_data._fold_sector_weightings(
        {"technology": 0.5, "mystery": 0.6}) is None
    assert market_data._fold_sector_weightings({"mystery": 0.2}) is None


def test_fold_sector_weightings_shaves_tiny_rounding_overage():
    folded = market_data._fold_sector_weightings(
        {"technology": 0.5005, "healthcare": 0.5004})
    assert folded is not None
    assert sum(folded.values()) == pytest.approx(1.0)


# ── Data layer: get_profile fund mixes ───────────────────────────────────

@pytest.fixture
def fake_yf(monkeypatch):
    state = {
        "info": {"quoteType": "ETF", "sector": None, "country": None,
                 "marketCap": None},
        "fund_error": False,
        "overview_error": False,
        "asset_error": False,
        "sector_error": False,
        "asset_classes": {"stockPosition": 0.6, "bondPosition": 0.4},
        "sector_weightings": {"technology": 0.7, "healthcare": 0.3},
        "category_name": "Balanced",
        "info_fetches": 0,
        "fund_fetches": 0,
    }

    class FakeFundsData:
        @property
        def fund_overview(self):
            if state["overview_error"]:
                raise RuntimeError("overview boom")
            return {"categoryName": state["category_name"]}

        @property
        def asset_classes(self):
            if state["asset_error"]:
                raise RuntimeError("asset boom")
            return state["asset_classes"]

        @property
        def sector_weightings(self):
            if state["sector_error"]:
                raise RuntimeError("sector boom")
            return state["sector_weightings"]

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
            return FakeFundsData()

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)
    return state


def test_get_profile_funds_fold_mixes(fake_yf):
    profile = market_data.get_profile("BAL")
    assert profile["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.4}
    assert profile["sector_mix"] == {"Technology": 0.7, "Healthcare": 0.3}
    assert profile["fund_degraded"] is False


def test_get_profile_partial_fund_mixes_are_not_scaled(fake_yf):
    fake_yf["asset_classes"] = {"stockPosition": 0.6, "bondPosition": 0.3}
    fake_yf["sector_weightings"] = {"technology": 0.4, "healthcare": 0.3}
    profile = market_data.get_profile("BAL")
    assert profile["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.3}
    assert profile["sector_mix"] == {"Technology": 0.4, "Healthcare": 0.3}
    assert profile["fund_degraded"] is False


def test_get_profile_rejects_invalid_fund_mix(fake_yf):
    fake_yf["asset_classes"] = {"stockPosition": 0.6,
                                "bondPosition": -0.1}
    fake_yf["sector_weightings"] = {"technology": float("nan")}
    profile = market_data.get_profile("BAL")
    assert profile["asset_mix"] is None
    assert profile["sector_mix"] is None
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


@pytest.mark.parametrize("field, working_key, working_value", [
    ("asset_error", "sector_mix",
     {"Technology": 0.7, "Healthcare": 0.3}),
    ("sector_error", "asset_mix", {"Stocks": 0.6, "Bonds": 0.4}),
])
def test_get_profile_one_field_exception_keeps_other_and_retries(
        fake_yf, field, working_key, working_value):
    fake_yf[field] = True
    first = market_data.get_profile("BAL")
    assert first["fund_degraded"] is True
    assert first[working_key] == working_value
    assert first["asset_mix" if field == "asset_error" else "sector_mix"] is None
    assert "BAL" not in market_data._fund_cache

    fake_yf[field] = False
    second = market_data.get_profile("BAL")
    assert second["fund_degraded"] is False
    assert second["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.4}
    assert second["sector_mix"] == {"Technology": 0.7, "Healthcare": 0.3}
    assert fake_yf["fund_fetches"] == 2


def test_get_profile_overview_exception_degrades_and_retries(fake_yf):
    fake_yf["overview_error"] = True
    first = market_data.get_profile("BAL")
    assert first["fund_degraded"] is True
    assert first["asset_mix"] == {"Stocks": 0.6, "Bonds": 0.4}
    assert first["sector_mix"] == {"Technology": 0.7, "Healthcare": 0.3}

    fake_yf["overview_error"] = False
    second = market_data.get_profile("BAL")
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


def test_get_profile_sparse_fund_data_is_none_and_caches(fake_yf):
    fake_yf["asset_classes"] = None
    fake_yf["sector_weightings"] = {}
    first = market_data.get_profile("BAL")
    second = market_data.get_profile("BAL")
    assert first["asset_mix"] is None
    assert first["sector_mix"] is None
    assert first["fund_degraded"] is False
    assert second["asset_mix"] is None
    assert second["fund_degraded"] is False
    # Successfully returned None/empty is a complete answer: it caches.
    assert fake_yf["fund_fetches"] == 1


def test_get_profile_commodity_other_maps_by_category(fake_yf):
    fake_yf["asset_classes"] = {"otherPosition": 1.0}
    fake_yf["sector_weightings"] = {}
    fake_yf["category_name"] = "Commodities Focused"
    profile = market_data.get_profile("GLD")
    assert profile["asset_mix"] == {"Commodities": 1.0}
