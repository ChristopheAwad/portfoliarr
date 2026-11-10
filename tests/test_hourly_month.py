"""Hourly 1M data through both chart routes, with no network calls."""

from types import SimpleNamespace

import pandas as pd
import pytest

import db
import market_data


@pytest.fixture
def hourly_yahoo(monkeypatch):
    state = {"fail": False}
    calls = []
    frames = {
        "AAPL": pd.DataFrame(
            {"Close": [90, 100, 110, float("nan"), float("inf"), 120, 130]},
            index=pd.to_datetime([
                "2026-09-03 15:30", "2026-09-04 09:30", "2026-09-04 10:30",
                "2026-09-04 11:30", "2026-09-04 12:30",
                "2026-09-07 09:30", "2026-09-07 10:30",
            ]),
        ),
    }

    class Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, **kwargs):
            calls.append((self.symbol, kwargs))
            if state["fail"]:
                raise ValueError("Yahoo unavailable")
            return frames[self.symbol]

    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=Ticker))
    return SimpleNamespace(frames=frames, calls=calls, state=state)


def test_month_stock_preserves_hours_and_dates(client, hourly_yahoo):
    response = client.get("/api/stock/AAPL/history?period=1M")
    assert response.status_code == 200
    assert response.get_json() == {
        "labels": ["2026-09-03 15:30", "2026-09-04 09:30", "2026-09-04 10:30",
                   "2026-09-07 09:30", "2026-09-07 10:30"],
        "values": [90, 100, 110, 120, 130],
    }
    assert hourly_yahoo.calls == [
        ("AAPL", {"period": "1mo", "interval": "1h", "auto_adjust": False}),
    ]


@pytest.mark.parametrize("prices", [[], [float("nan"), float("nan")]])
def test_month_empty_or_invalid_prices(hourly_yahoo, prices):
    hourly_yahoo.frames["AAPL"] = pd.DataFrame(
        {"Close": prices}, index=pd.date_range("2026-09-01", periods=len(prices), freq="h"),
    )
    assert market_data.get_history("AAPL", "1M") == {}


def test_month_failed_fetch_retries(hourly_yahoo):
    hourly_yahoo.state["fail"] = True
    with pytest.raises(ValueError, match="unavailable"):
        market_data.get_history("AAPL", "1M")
    hourly_yahoo.state["fail"] = False
    assert len(market_data.get_history("AAPL", "1M")) == 5
    assert len(hourly_yahoo.calls) == 2


@pytest.mark.parametrize("with_monday", [False, True])
def test_month_weekend_trade_waits_for_next_session(client, hourly_yahoo, with_monday):
    db.add_transaction("AAPL", "2026-09-04", 100, 1, "CAD", "BUY", 1, portfolio_id=1)
    db.add_transaction("AAPL", "2026-09-05", 100, 2, "CAD", "BUY", 1, portfolio_id=1)
    if not with_monday:
        hourly_yahoo.frames["AAPL"] = hourly_yahoo.frames["AAPL"].iloc[:5]
    response = client.get("/api/portfolio/history?period=1M")
    assert response.status_code == 200
    body = response.get_json()
    assert body["labels"] == ["2026-09-04 09:30", "2026-09-04 10:30"] + (
        ["2026-09-07 09:30", "2026-09-07 10:30"] if with_monday else []
    )
    assert body["values"] == ([100, 110, 360, 390] if with_monday else [100, 110])
    assert body["costs"] == ([100, 100, 300, 300] if with_monday else [100, 100])
    assert body["index_values"] == pytest.approx(
        [100, 110, 160, 520 / 3] if with_monday else [100, 110]
    )
    assert body["twrr_pct"] == pytest.approx(220 / 3 if with_monday else 10)


def test_month_leading_cross_market_holiday_starts_fully_priced(
        client, hourly_yahoo):
    """A 1M window can open on a date only ONE held market trades (for
    example Canadian Thanksgiving, when the TSX is closed and the US market
    is open). Forward-fill has no earlier close to carry at the window's
    leading edge, so the closed market's position priced at 0 and the line
    jumped up on the next session — the visible leading drop and the fake
    TWR headline. The axis must start on the first bar that prices EVERY
    held position, never on a partial total.

        held: 10 AAPL (US) + 100 RY.TO (TSX), both bought before the window
        AAPL: Oct 12 and Oct 13 hourly bars
        RY.TO: first bar Oct 13 (TSX closed Oct 12)
        Oct 12 cannot price RY.TO → trimmed.
        Oct 13 09:30: 10×102 + 100×50 = 6020
        Oct 13 10:30: 10×103 + 100×51 = 6130 → TWR +110/6020
    """
    db.add_transaction("AAPL", "2026-09-01", 100, 10, "CAD", "BUY", 1,
                       portfolio_id=1)
    db.add_transaction("RY.TO", "2026-09-01", 50, 100, "CAD", "BUY", 1,
                       portfolio_id=1)
    hourly_yahoo.frames["AAPL"] = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0, 103.0]},
        index=pd.to_datetime([
            "2026-10-12 09:30", "2026-10-12 10:30",
            "2026-10-13 09:30", "2026-10-13 10:30",
        ]),
    )
    hourly_yahoo.frames["RY.TO"] = pd.DataFrame(
        {"Close": [50.0, 51.0]},
        index=pd.to_datetime(["2026-10-13 09:30", "2026-10-13 10:30"]),
    )

    body = client.get("/api/portfolio/history?period=1M").get_json()
    assert body["labels"] == ["2026-10-13 09:30", "2026-10-13 10:30"]
    assert body["values"] == pytest.approx([6020.0, 6130.0])
    assert body["costs"] == pytest.approx([6000.0, 6000.0])
    assert body["index_values"] == pytest.approx([100.0, 6130 / 6020 * 100])
    assert body["twrr_pct"] == pytest.approx(110 / 6020 * 100)

    # A comparison line is rebased over the SAME trimmed axis: it starts at
    # 100 on the first fully-priced label, never on the dropped partial bar.
    hourly_yahoo.frames["SPY"] = pd.DataFrame(
        {"Close": [200.0, 210.0]},
        index=pd.to_datetime(["2026-10-13 09:30", "2026-10-13 10:30"]),
    )
    body = client.get(
        "/api/portfolio/history?period=1M&benchmark=SPY"
    ).get_json()
    assert body["labels"] == ["2026-10-13 09:30", "2026-10-13 10:30"]
    assert body["benchmarks"][0]["symbol"] == "SPY"
    assert body["benchmarks"][0]["values"] == pytest.approx([100.0, 105.0])
    assert body["benchmarks"][0]["error"] is None


@pytest.mark.parametrize("endpoint", ["/api/stock/AAPL/history", "/api/portfolio/history"])
def test_month_comparisons_and_price_gaps(client, hourly_yahoo, endpoint):
    db.add_transaction("AAPL", "2026-09-03", 90, 1, "CAD", "BUY", 1, portfolio_id=1)
    labels = ["2026-09-03 15:30", "2026-09-04 09:30", "2026-09-04 10:30",
              "2026-09-07 09:30", "2026-09-07 10:30"]
    hourly_yahoo.frames["SPY"] = pd.DataFrame(
        {"Close": [200, 220]}, index=pd.to_datetime([labels[1], labels[3]]),
    )
    body = client.get(f"{endpoint}?period=1M&benchmark=SPY").get_json()
    assert body["labels"] == labels
    assert body["benchmarks"][0]["values"] == pytest.approx([None, 100, 100, 110, 110])
    if endpoint == "/api/portfolio/history":
        # A second held ticker has gaps at otherwise valid hourly labels.
        db.add_transaction("SPY", "2026-09-03", 200, 1, "CAD", "BUY", 1, portfolio_id=1)
        body = client.get(f"{endpoint}?period=1M").get_json()
        assert body["values"] == [90, 300, 310, 340, 350]
