"""Locks for raw (unadjusted) price reads.

The ledger stores raw facts: the price actually paid and the shares
actually bought. The chart multiplies those by historical closes, so the
closes must be RAW too. yfinance 1.7.0 defaults to auto_adjust=True, so
every .history() call must pass auto_adjust=False explicitly — otherwise
dividend/split-adjusted closes get mixed with raw quantities and costs
(fake losses on dividend payers, a scale break across splits).
"""

from types import SimpleNamespace

import pandas as pd

import market_data


class _RecordingTicker:
    def __init__(self, calls, frame):
        self.calls = calls
        self.frame = frame

    def history(self, **kwargs):
        self.calls.append(kwargs)
        return self.frame


def _install(monkeypatch, frame):
    calls = []
    monkeypatch.setattr(
        market_data, "yf",
        SimpleNamespace(Ticker=lambda symbol: _RecordingTicker(calls, frame)),
    )
    return calls


def test_all_history_calls_request_raw_closes(monkeypatch):
    frame = pd.DataFrame(
        {"Close": [100.0], "Adj Close": [90.0]},
        index=pd.to_datetime(["2026-08-28"]),
    )
    calls = _install(monkeypatch, frame)

    market_data.get_history("AAPL", "1M")
    market_data.get_price_on("AAPL", "2026-08-28")
    market_data.get_fx_rate_on("USD", "CAD", "2026-08-28")

    assert len(calls) == 3
    assert all(call["auto_adjust"] is False for call in calls)


def test_get_history_uses_close_not_adjusted_close(monkeypatch):
    frame = pd.DataFrame(
        {"Close": [100.0, 101.0], "Adj Close": [90.0, 91.0]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )
    _install(monkeypatch, frame)

    assert market_data.get_history("AAPL", "3M") == {
        "2026-08-28": 100.0, "2026-08-31": 101.0,
    }
