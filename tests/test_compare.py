"""Backend contracts for arbitrary chart comparison overlays."""

import pytest

import app as app_module
import db


def seed_transaction(ticker="AAPL", date="2026-08-28", price=100.0,
                     qty=10, tx_type="BUY", currency="CAD", fx_rate=1.0):
    """Insert a ledger fact through the public database layer."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


def test_parse_compare_symbols_basic():
    parse = app_module._parse_compare_symbols
    assert parse("") == []
    assert parse("spy") == ["SPY"]
    assert parse("SPY, spy ,QQQ") == ["SPY", "QQQ"]
    assert parse("SPY,,") == ["SPY"]
    assert parse("SPY,B,^IXIC") == ["SPY", "B", "^IXIC"]


def test_parse_compare_symbols_rejects_four():
    with pytest.raises(ValueError, match="3"):
        app_module._parse_compare_symbols("A,B,C,D")


@pytest.mark.parametrize(("closes", "expected"), [
    ({"d1": 100.0, "d3": 150.0}, [100.0, 100.0, 150.0]),
    ({"d2": 50.0, "d3": 100.0}, [None, 100.0, 200.0]),
    ({}, [None, None, None]),
    ({"d1": 200.0, "d2": 100.0}, [100.0, 50.0, 50.0]),
])
def test_rebase_series_forward_fills_and_anchors(closes, expected):
    assert app_module._rebase_series(["d1", "d2", "d3"], closes) == expected


def test_portfolio_history_no_benchmark_omits_key(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert "benchmarks" not in body


def test_portfolio_history_one_benchmark_rebased(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    fake_market.histories["SPY"] = {
        "2026-08-28": 400.0, "2026-08-31": 420.0,
    }

    body = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY"
    ).get_json()

    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 1100.0]
    assert body["index_values"] == pytest.approx([100.0, 110.0])
    assert body["benchmarks"] == [{
        "symbol": "SPY", "values": [100.0, 105.0], "error": None,
    }]


def test_portfolio_benchmark_starts_at_first_available_bar(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0,
        "2026-08-31": 100.0,
        "2026-09-01": 100.0,
    }
    fake_market.histories["SPY"] = {
        "2026-08-31": 500.0, "2026-09-01": 550.0,
    }

    body = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY"
    ).get_json()
    assert body["benchmarks"][0]["values"] == [None, 100.0, 110.0]


def test_portfolio_history_preserves_three_benchmark_order(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {"2026-08-28": 100.0,
                                         "2026-08-31": 100.0}
    for symbol, price in (("SPY", 400.0), ("QQQ", 300.0), ("XIC.TO", 30.0)):
        fake_market.histories[symbol] = {
            "2026-08-28": price, "2026-08-31": price * 1.1,
        }

    body = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY,QQQ,XIC.TO"
    ).get_json()
    assert [entry["symbol"] for entry in body["benchmarks"]] == [
        "SPY", "QQQ", "XIC.TO",
    ]


def test_portfolio_history_rejects_four_benchmarks(client, fake_market):
    response = client.get(
        "/api/portfolio/history?period=5D&benchmark=A,B,C,D"
    )
    assert response.status_code == 400
    assert "3" in response.get_json()["error"]


def test_portfolio_benchmark_failure_degrades_independently(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 100.0,
    }
    fake_market.histories["QQQ"] = {
        "2026-08-28": 300.0, "2026-08-31": 330.0,
    }

    response = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY,QQQ"
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["values"] == [1000.0, 1000.0]
    assert body["benchmarks"][0]["symbol"] == "SPY"
    assert body["benchmarks"][0]["values"] is None
    assert body["benchmarks"][0]["error"]
    assert body["benchmarks"][1]["values"] == [100.0, 110.0]


def test_portfolio_benchmark_can_reuse_held_symbol(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 125.0,
    }
    body = client.get(
        "/api/portfolio/history?period=5D&benchmark=AAPL"
    ).get_json()
    assert body["benchmarks"] == [{
        "symbol": "AAPL", "values": [100.0, 125.0], "error": None,
    }]


def test_portfolio_empty_ledger_with_benchmark_is_empty(client, fake_market):
    response = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY"
    )
    assert response.status_code == 200
    assert response.get_json()["labels"] == []


def test_portfolio_bad_period_wins_before_benchmark_fetch(client, fake_market):
    response = client.get(
        "/api/portfolio/history?period=NOPE&benchmark=SPY"
    )
    assert response.status_code == 400
    assert "period" in response.get_json()["error"]


def test_portfolio_benchmark_payload_has_no_nan(client, fake_market):
    seed_transaction()
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }
    fake_market.histories["SPY"] = {
        "2026-08-28": 400.0, "2026-08-31": 410.0,
    }
    response = client.get(
        "/api/portfolio/history?period=5D&benchmark=SPY"
    )
    assert b"NaN" not in response.data


def test_stock_history_without_benchmark_keeps_raw_shape(client, fake_market):
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 120.0,
    }
    body = client.get("/api/stock/AAPL/history?period=5D").get_json()
    assert body == {
        "labels": ["2026-08-28", "2026-08-31"],
        "values": [100.0, 120.0],
    }


def test_stock_history_comparison_normalizes_union_axis(client, fake_market):
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 120.0,
    }
    fake_market.histories["SPY"] = {
        "2026-08-28": 400.0, "2026-09-01": 440.0,
    }
    body = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=SPY"
    ).get_json()
    assert body["labels"] == [
        "2026-08-28", "2026-08-31", "2026-09-01",
    ]
    assert body["normalized"] is True
    assert body["values"] == [100.0, 120.0, 120.0]
    assert body["benchmarks"] == [{
        "symbol": "SPY", "values": [100.0, 100.0, 110.0], "error": None,
    }]


def test_stock_benchmark_failure_keeps_primary(client, fake_market):
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 120.0,
    }
    response = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=BAD"
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["normalized"] is True
    assert body["values"] == [100.0, 120.0]
    assert body["benchmarks"][0]["values"] is None
    assert body["benchmarks"][0]["error"]


def test_stock_primary_failure_remains_404_with_benchmark(client, fake_market):
    fake_market.histories["SPY"] = {"2026-08-28": 400.0}
    response = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=SPY"
    )
    assert response.status_code == 404


def test_stock_comparison_ignores_primary_symbol(client, fake_market):
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 120.0,
    }
    body = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=AAPL"
    ).get_json()
    assert body == {
        "labels": ["2026-08-28", "2026-08-31"],
        "values": [100.0, 120.0],
    }


def test_stock_history_supports_three_benchmarks(client, fake_market):
    fake_market.histories["AAPL"] = {"2026-08-28": 100.0}
    for symbol, price in (("SPY", 400.0), ("QQQ", 300.0), ("XIC.TO", 30.0)):
        fake_market.histories[symbol] = {"2026-08-28": price}
    body = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=SPY,QQQ,XIC.TO"
    ).get_json()
    assert [entry["symbol"] for entry in body["benchmarks"]] == [
        "SPY", "QQQ", "XIC.TO",
    ]


def test_stock_history_rejects_four_benchmarks(client, fake_market):
    response = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=A,B,C,D"
    )
    assert response.status_code == 400
    assert "3" in response.get_json()["error"]


def test_stock_empty_primary_keeps_valid_benchmark_axis(client, fake_market):
    fake_market.histories["AAPL"] = {}
    fake_market.histories["SPY"] = {
        "2026-08-28": 400.0, "2026-08-31": 420.0,
    }
    body = client.get(
        "/api/stock/AAPL/history?period=5D&benchmark=SPY"
    ).get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [None, None]
    assert body["benchmarks"][0]["values"] == [100.0, 105.0]
