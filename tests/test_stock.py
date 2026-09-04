# tests/test_stock.py
# ===================
# Route tests for the stock detail page: GET /stock/<symbol> and its four
# JSON feeds (/api/search is covered in test_search.py).
#
# THE CONTRACT UNDER TEST — one symbol, one request, no graceful middle
# ground: the dashboard's multi-symbol endpoints degrade per symbol, but
# here the single symbol IS the whole answer, so an unquotable symbol is
# a plain 404 (same verdict as watchlist-add / transaction-log).
#
# Everything shares conftest.py's fake_market fixture — the same patched
# app.get_quote / get_name / get_history / get_stats dict-lookup fakes
# test_routes.py uses; a symbol absent from a dict = Yahoo can't serve it.

import pytest

import market_data
import pandas as pd
from conftest import make_quote
from types import SimpleNamespace


# ── Page route ────────────────────────────────────────────────────────

def test_stock_page_renders_shell_with_normalized_symbol(client):
    """The page route is a dumb shell renderer: no network, no DB — it
    just stamps the uppercased symbol into the HTML (stock.js reads it
    from <body data-symbol> and fills everything else)."""
    res = client.get("/stock/aapl")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'data-symbol="AAPL"' in html
    assert "AAPL" in html   # also in the <title>


# ── Quote endpoint (the polled one) ───────────────────────────────────

def test_stock_quote_returns_quote_plus_name(client, fake_market):
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    fake_market.names["AAPL"] = "Apple Inc"

    body = client.get("/api/stock/AAPL").get_json()
    assert body["price"] == 229.5
    assert body["previous_close"] == 225.0
    assert body["change"] == pytest.approx(4.5)
    assert body["name"] == "Apple Inc"


def test_stock_quote_normalizes_case(client, fake_market):
    """Lowercase URL → canonical lookup, same rule as every symbol route."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    assert client.get("/api/stock/aapl").status_code == 200


def test_stock_quote_name_failure_degrades_to_none(client, fake_market):
    """The heavy name endpoint flaking must not sink the quote: name is
    None and the header falls back to the bare symbol (watchlist rule)."""
    fake_market.quotes["MSFT"] = make_quote("MSFT", 500.0, 495.0)
    # names dict deliberately empty → get_name raises KeyError
    body = client.get("/api/stock/MSFT").get_json()
    assert body["price"] == 500.0
    assert body["name"] is None


def test_stock_quote_unquotable_symbol_returns_404(client, fake_market):
    """NOPE is absent from the quotes dict → get_quote raises → 404.
    One symbol IS the whole request, so there's nothing to degrade to."""
    res = client.get("/api/stock/NOPE")
    assert res.status_code == 404
    assert "NOPE" in res.get_json()["error"]


# ── Stats endpoint (the once-per-load one) ────────────────────────────

def test_stock_stats_returned_untouched(client, fake_market):
    """get_stats already returns the snake_case grid keys — the route is a
    pure pass-through (including None values for fields Yahoo lacks)."""
    fake_market.stats["AAPL"] = {
        "open": 148.0, "day_high": 152.0, "day_low": 147.5,
        "prev_close": 145.0, "volume": 55_000_000,
        "week52_low": 164.0, "week52_high": 237.25,
        "market_cap": None,   # e.g. an index — the frontend gap-fills "—"
    }
    res = client.get("/api/stock/AAPL/stats")
    assert res.status_code == 200
    assert res.get_json() == fake_market.stats["AAPL"]


def test_stock_stats_failure_returns_404(client, fake_market):
    res = client.get("/api/stock/NOPE/stats")
    assert res.status_code == 404


# ── History endpoint (the chart's data) ───────────────────────────────

def test_stock_history_sorts_labels_and_aligns_values(client, fake_market):
    """get_history returns {label: close} in fetch order; the chart needs
    parallel arrays sorted chronologically — ISO dates sort as strings."""
    fake_market.histories["AAPL"] = {
        "2026-08-31": 120.0,   # deliberately out of order
        "2026-08-27": 100.0,
        "2026-08-28": 110.0,
    }
    body = client.get("/api/stock/AAPL/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-27", "2026-08-28", "2026-08-31"]
    assert body["values"] == [100.0, 110.0, 120.0]   # same order as labels


def test_stock_history_rejects_unknown_period(client, fake_market):
    """A bad timeframe key is caught BEFORE any fetch, listing the valid
    options — identical validation to /api/portfolio/history."""
    res = client.get("/api/stock/AAPL/history?period=NOPE")
    assert res.status_code == 400
    assert "5D" in res.get_json()["error"]
    assert "MAX" in res.get_json()["error"]


def test_stock_history_empty_history_is_a_normal_200(client, fake_market):
    """An empty close dict (e.g. a brand-new listing) is an empty chart,
    not an error — the frontend just leaves the canvas blank."""
    fake_market.histories["AAPL"] = {}
    res = client.get("/api/stock/AAPL/history?period=1Y")
    assert res.status_code == 200
    assert res.get_json() == {"labels": [], "values": []}


def test_stock_history_failure_returns_404(client, fake_market):
    res = client.get("/api/stock/BAD/history?period=5D")
    assert res.status_code == 404
    assert "BAD" in res.get_json()["error"]


def test_stock_history_nan_last_bar_is_dropped_end_to_end(client, monkeypatch):
    """END-TO-END regression for the blank-chart outage (Sep 2026): Yahoo's
    current-day bar can ship Close = NaN (observed live on META). The NaN
    used to reach the JSON payload as a bare `NaN` token — invalid JSON
    for a browser — so response.json() threw in the catch block and the
    chart never painted, while sibling tickers with clean bars rendered
    fine ("works for some tickers, not others").

    Deliberately NOT fake_market: its dict-lookup fake REPLACES
    app.get_history, which would bypass the data layer this fix lives in.
    Instead market_data.yf is patched (where market_data uses it) and the
    REAL get_history runs — app.get_history IS that same function object,
    imported from market_data at import time.

    The raw-bytes assertion matters: res.get_json() parses NaN leniently
    and could NOT catch this bug — b"NaN" on the wire is what browsers
    choke on."""
    class FakeTicker:
        def __init__(self, symbol):
            pass

        def history(self, period=None, interval="1d"):
            return pd.DataFrame(
                {"Close": [578.02, 592.85, float("nan")]},
                index=pd.to_datetime(
                    ["2026-08-28", "2026-09-02", "2026-09-03"]),
            )

    monkeypatch.setattr(market_data, "yf",
                        SimpleNamespace(Ticker=FakeTicker))

    res = client.get("/api/stock/META/history?period=5D")
    assert res.status_code == 200
    assert b"NaN" not in res.data          # strict-JSON clean on the wire
    assert res.get_json() == {
        "labels": ["2026-08-28", "2026-09-02"],   # NaN bar's label is gone
        "values": [578.02, 592.85],
    }
