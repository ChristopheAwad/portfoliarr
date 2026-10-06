"""Focused contracts for performance measurement: perf.py, the perf
routes, the Server-Timing header, and the market-data cache recording."""

import json
import logging
import re
from types import SimpleNamespace

import pandas as pd
import pytest

import app as app_module
import market_data
import perf
from conftest import make_quote


def messages(caplog, event):
    """Return records whose stable key-value message starts with event."""
    prefix = f"event={event} "
    return [record for record in caplog.records
            if record.getMessage().startswith(prefix)]


# ---------------------------------------------------------------------------
# perf.py — the aggregator itself
# ---------------------------------------------------------------------------

def test_snapshot_percentiles_math():
    for value in range(1, 101):
        perf.record("unit.metric", value)
    (row,) = perf.snapshot()["metrics"]
    assert row["count"] == 100
    assert row["avg_ms"] == 50.5
    assert row["p50_ms"] == 50.0
    assert row["p95_ms"] == 95.0
    assert row["max_ms"] == 100.0
    assert row["total_ms"] == 5050.0


def test_tags_create_separate_rows_and_snapshot_is_json_safe():
    perf.record("m", 1.0, cache="hit")
    perf.record("m", 3.0, cache="miss")
    snapshot = perf.snapshot()
    json.dumps(snapshot)  # must not raise
    assert len(snapshot["metrics"]) == 2
    tags = {tuple(sorted(row["tags"].items())) for row in snapshot["metrics"]}
    assert tags == {(("cache", "hit"),), (("cache", "miss"),)}


def test_record_ignores_bad_values_and_clamps_negatives():
    perf.record("m", None)
    perf.record("m", "fast")
    assert perf.snapshot()["metrics"] == []
    perf.record("m", -5)
    (row,) = perf.snapshot()["metrics"]
    assert row["count"] == 1 and row["max_ms"] == 0.0


def test_request_completed_counts_and_reset_clears():
    assert perf.request_completed() == 1
    assert perf.request_completed() == 2
    assert perf.snapshot()["requests_total"] == 2
    perf.reset()
    assert perf.snapshot()["requests_total"] == 0
    assert perf.request_completed() == 1


# ---------------------------------------------------------------------------
# request boundary — Server-Timing, request_complete extras, aggregates
# ---------------------------------------------------------------------------

def test_every_non_static_response_carries_server_timing(client):
    response = client.get("/api/portfolios")
    assert response.status_code == 200
    assert re.fullmatch(r"app;dur=\d+(\.\d+)?",
                        response.headers["Server-Timing"])


def test_static_response_has_no_server_timing(client):
    response = client.get("/static/js/perf.js")
    assert response.status_code == 200
    assert "Server-Timing" not in response.headers


def test_request_complete_names_the_endpoint_and_size(
        client, monkeypatch, caplog):
    monkeypatch.setattr(app_module, "SLOW_REQUEST_MS", 10**9)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/portfolios")
    (record,) = messages(caplog, "request_complete")
    text = record.getMessage()
    assert "endpoint=portfolios_api" in text
    assert re.search(r"bytes=\d+", text)
    assert response.headers["X-Request-ID"] in text


def test_http_metrics_keep_working_after_two_symbols(client, fake_market):
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150, 145)
    fake_market.quotes["MSFT"] = make_quote("MSFT", 400, 398)
    fake_market.names["AAPL"] = "Apple Inc"
    fake_market.names["MSFT"] = "Microsoft"
    client.get("/api/stock/AAPL")
    client.get("/api/stock/MSFT")
    rows = [row for row in perf.snapshot()["metrics"]
            if row["name"] == "http.stock_quote"]
    assert len(rows) == 1
    assert rows[0]["count"] == 2


def test_db_connect_is_recorded(client):
    client.get("/api/portfolios")
    rows = [row for row in perf.snapshot()["metrics"]
            if row["name"] == "db.connect"]
    assert rows and rows[0]["count"] >= 1


# ---------------------------------------------------------------------------
# GET /api/perf
# ---------------------------------------------------------------------------

def test_api_perf_requires_a_session(fresh_db):
    anonymous = app_module.app.test_client()
    response = anonymous.get("/api/perf")
    assert response.status_code == 401


def test_api_perf_returns_metrics_after_a_request(client):
    client.get("/api/portfolios")
    response = client.get("/api/perf")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["requests_total"] >= 1
    names = {row["name"] for row in payload["metrics"]}
    assert "http.portfolios_api" in names


# ---------------------------------------------------------------------------
# perf_summary logging
# ---------------------------------------------------------------------------

def test_perf_summary_fires_at_the_interval(client, monkeypatch, caplog):
    monkeypatch.setattr(app_module, "PERF_SUMMARY_EVERY", 1)
    app_module._perf_last_summary_total = 0
    with caplog.at_level(logging.INFO):
        client.get("/api/portfolios")
    records = messages(caplog, "perf_summary")
    assert any("requests=" in record.getMessage() for record in records)
    assert any("endpoint=portfolios_api" in record.getMessage()
               for record in records)


def test_perf_summary_reports_cache_rates_without_paths(caplog):
    perf.record("market.get_quote", 5.0, cache="hit")
    perf.record("market.get_quote", 50.0, cache="miss")
    perf.record("market.get_quote", 30.0, cache="wait")
    with caplog.at_level(logging.INFO):
        app_module._log_perf_summary(3)
    cache_records = [record for record in messages(caplog, "perf_summary")
                     if "cache=" in record.getMessage()]
    (record,) = cache_records
    text = record.getMessage()
    assert "cache=market.get_quote" in text
    assert "hit=1 miss=1 wait=1" in text
    assert "hit_rate=0.33" in text
    assert "miss_p95_ms=50.0" in text


# ---------------------------------------------------------------------------
# market_data records cache outcomes (patch where yf is used)
# ---------------------------------------------------------------------------

def _fake_yf(state):
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.fast_info = dict(state["fast_info"])

        @property
        def info(self):
            return state["info"]

        def history(self, period=None, interval="1d", start=None, end=None):
            return state["history"]

    return SimpleNamespace(Ticker=FakeTicker)


def test_quote_records_miss_then_hit(monkeypatch):
    state = {"fast_info": {"lastPrice": 150.0, "previousClose": 145.0,
                           "currency": "USD"},
             "info": {}, "history": None}
    monkeypatch.setattr(market_data, "yf", _fake_yf(state))
    market_data.get_quote("AAPL")
    market_data.get_quote("AAPL")
    rows = {(row["name"], row["tags"].get("cache")): row
            for row in perf.snapshot()["metrics"]}
    assert rows[("market.get_quote", "miss")]["count"] == 1
    assert rows[("market.get_quote", "hit")]["count"] == 1


def test_history_records_period_tag_on_miss_and_hit(monkeypatch):
    frame = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    state = {"fast_info": {}, "info": {},
             "history": frame}
    monkeypatch.setattr(market_data, "yf", _fake_yf(state))
    market_data.get_history("AAPL", "1M")
    market_data.get_history("AAPL", "1M")
    rows = {(row["name"], row["tags"].get("cache"),
             row["tags"].get("period")): row
            for row in perf.snapshot()["metrics"]}
    assert rows[("market.get_history", "miss", "1M")]["count"] == 1
    assert rows[("market.get_history", "hit", "1M")]["count"] == 1


def test_name_records_hit_and_miss(monkeypatch):
    state = {"fast_info": {}, "info": {"shortName": "Apple Inc"},
             "history": None}
    monkeypatch.setattr(market_data, "yf", _fake_yf(state))
    market_data.get_name("AAPL")
    market_data.get_name("AAPL")
    rows = {(row["name"], row["tags"].get("cache")): row
            for row in perf.snapshot()["metrics"]}
    assert rows[("market.get_name", "miss")]["count"] == 1
    assert rows[("market.get_name", "hit")]["count"] == 1


def test_failed_fetch_still_records_a_miss(monkeypatch):
    state = {"fast_info": {}, "info": {}, "history": None}
    monkeypatch.setattr(market_data, "yf", _fake_yf(state))
    with pytest.raises(ValueError):
        market_data.get_name("AAPL")
    rows = {(row["name"], row["tags"].get("cache")): row
            for row in perf.snapshot()["metrics"]}
    assert rows[("market.get_name", "miss")]["count"] == 1


# ---------------------------------------------------------------------------
# POST /api/perf/client — the browser beacon
# ---------------------------------------------------------------------------

VALID_BEACON = {
    "page": "dashboard",
    "ttfb_ms": 12.3,
    "dom_ms": 100.0,
    "load_ms": 250.5,
    "lcp_ms": 180.0,
    "fetches": [
        {"endpoint": "/api/portfolio/summary", "ms": 120.0,
         "server_ms": 80.0, "bytes": 500},
        {"endpoint": "/api/stock/:symbol", "ms": 90.0},
    ],
}


def test_beacon_records_and_logs_without_paths(client, caplog):
    with caplog.at_level(logging.INFO):
        response = client.post("/api/perf/client", json=VALID_BEACON)
    assert response.status_code == 204
    (record,) = messages(caplog, "client_perf")
    text = record.getMessage()
    assert "page=dashboard" in text
    assert "ttfb_ms=12.3" in text
    assert "lcp_ms=180.0" in text
    assert "fetches=2" in text
    assert "request_id=" in text
    rows = {(row["name"], tuple(sorted(row["tags"].items()))): row
            for row in perf.snapshot()["metrics"]}
    assert rows[("client.page_load", (("page", "dashboard"),))]["count"] == 1
    assert rows[("client.fetch",
                 (("endpoint", "/api/portfolio/summary"),))]["count"] == 1
    assert rows[("client.server",
                 (("endpoint", "/api/portfolio/summary"),))]["count"] == 1


def test_beacon_is_available_signed_out(fresh_db):
    from conftest import seed_user
    seed_user("someone")
    anonymous = app_module.app.test_client()
    response = anonymous.post("/api/perf/client", json={"page": "other"})
    assert response.status_code == 204


def test_beacon_rejects_invalid_json_and_oversize(client):
    bad = client.post("/api/perf/client", data=b"{not json",
                      content_type="application/json")
    assert bad.status_code == 400
    non_object = client.post("/api/perf/client", data=b"[1, 2]",
                             content_type="application/json")
    assert non_object.status_code == 400
    oversize = client.post(
        "/api/perf/client",
        data=json.dumps({"page": "dashboard",
                         "fetches": [{"endpoint": "/x", "ms": 1}] * 500}
                        ).encode(),
        content_type="application/json")
    assert oversize.status_code == 413


def test_beacon_drops_invalid_items_and_unknown_pages(client, caplog):
    payload = {
        "page": "admin-panel",
        "load_ms": "NaN",
        "fetches": [
            {"endpoint": 42, "ms": 10},
            {"endpoint": "/api/ok", "ms": 10},
            {"endpoint": "/api/search", "ms": "fast"},
            {"endpoint": "/api/search", "ms": 15},
            {"endpoint": "/api/search", "ms": 20, "server_ms": float("nan")},
        ],
    }
    with caplog.at_level(logging.INFO):
        response = client.post("/api/perf/client", json=payload)
    assert response.status_code == 204
    (record,) = messages(caplog, "client_perf")
    text = record.getMessage()
    assert "page=other" in text
    assert "load_ms=-" in text
    assert "fetches=2" in text
    rows = [row for row in perf.snapshot()["metrics"]
            if row["name"] == "client.fetch"]
    assert len(rows) == 1
    assert rows[0]["tags"] == {"endpoint": "/api/search"}
    assert rows[0]["count"] == 2


def test_beacon_normalizes_symbol_paths_and_drops_unknown(client):
    payload = {
        "page": "stock",
        "fetches": [
            {"endpoint": "/api/stock/AAPL?secret=private", "ms": 10},
            {"endpoint": "/api/stock/AAPL/stats", "ms": 10},
            {"endpoint": "/api/stock/AAPL/history", "ms": 10},
            {"endpoint": "/api/stock/AAPL/financials", "ms": 10},
            {"endpoint": "/api/stock/AAPL/events", "ms": 10},
            {"endpoint": "/api/quote/MSFT", "ms": 10},
            {"endpoint": "/api/transactions/12", "ms": 10},
            {"endpoint": "/api/watchlist/TSLA", "ms": 10},
            {"endpoint": "/api/ok", "ms": 10},
        ],
    }
    response = client.post("/api/perf/client", json=payload)
    assert response.status_code == 204
    rows = [row for row in perf.snapshot()["metrics"]
            if row["name"] == "client.fetch"]
    endpoints = sorted(row["tags"]["endpoint"] for row in rows)
    assert endpoints == [
        "/api/quote/:symbol", "/api/stock/:symbol",
        "/api/stock/:symbol/events", "/api/stock/:symbol/financials",
        "/api/stock/:symbol/history", "/api/stock/:symbol/stats",
        "/api/transactions/:id", "/api/watchlist/:symbol",
    ]
    dumped = json.dumps(perf.snapshot())
    for leaked in ("AAPL", "MSFT", "TSLA", "secret", "private"):
        assert leaked not in dumped


def test_perf_summary_merges_methods_and_reports_true_miss_p95(caplog):
    perf.record("http.example", 10.0, method="GET", status=200)
    perf.record("http.example", 50.0, method="POST", status=400)
    perf.record("market.get_history", 5.0, cache="miss", period="1M")
    perf.record("market.get_history", 90.0, cache="miss", period="1Y")
    with caplog.at_level(logging.INFO):
        app_module._log_perf_summary(3)
    endpoint_records = [record for record in messages(caplog, "perf_summary")
                        if "endpoint=" in record.getMessage()]
    (endpoint_record,) = endpoint_records
    assert "endpoint=example count=2" in endpoint_record.getMessage()
    cache_records = [record for record in messages(caplog, "perf_summary")
                     if "cache=" in record.getMessage()]
    (cache_record,) = cache_records
    assert "miss_p95_ms=90.0" in cache_record.getMessage()
