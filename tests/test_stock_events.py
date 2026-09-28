# tests/test_stock_events.py
# ===========================
# Locks for the stock-detail Events card (roadmap #55).
#
# The detail page shows an Events cluster: next earnings date,
# ex-dividend and dividend dates, recent dividend history with a
# trailing-12-month total — all from ONE data-layer call
# (market_data.get_events merges Yahoo's `Ticker.calendar` with
# `Ticker.dividends`) and ONE new route
# (GET /api/stock/<symbol>/events).
#
# Two contracts are under test here:
#
#   1. DATA LAYER (market_data.get_events). Returns the exact reply
#      shape {earnings_date, ex_dividend_date, dividend_date (ISO
#      YYYY-MM-DD strings or None), ttm_total (raw float or None),
#      recent ([{date, amount}] oldest-first, max 10, raw floats)}.
#      NO rounding, NO FX. Non-finite dividend cells are dropped.
#      Raises ValueError only when NOTHING is usable (all dates None
#      AND recent empty) — the route turns that into a 404 and the
#      frontend hides the card. Results ride a 24h process-memory
#      cache, successes only.
#
#   2. TEMPLATE. The events card ships HIDDEN with empty dd cells and
#      an empty tbody; stock.js builds every row from JSON. A renamed
#      id or a baked-in static date is a silent break, so pytest makes
#      it loud.
#
# market_data.yf is patched WHERE MARKET_DATA USES IT (the
# test_stock_financials.py pattern) so the REAL get_events runs —
# fake_market would replace app.get_events with a dict lookup and
# bypass the data layer this file mostly exists to lock.
#
# fake_market convention (conftest.py): `events` dict keyed by symbol;
# `fake_market.events["AAPL"] = {...}` makes the route return it, an
# absent key raises KeyError so the route answers 404.

import re
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

import market_data


class FakeTicker:
    def __init__(self, calendar, dividends):
        self.calendar = calendar
        self.dividends = dividends


def patch_ticker(monkeypatch, calendar, dividends):
    """Point market_data.yf at a Ticker with the given calendar/dividends."""
    monkeypatch.setattr(
        market_data, "yf",
        SimpleNamespace(
            Ticker=lambda symbol: FakeTicker(calendar, dividends)
        ),
    )


def monthly_dividends(n, amount=1.0, end="2026-08-01", freq_days=30):
    """n monthly-ish payouts ending at `end`, oldest first in the Series."""
    end_ts = pd.Timestamp(end)
    dates = [end_ts - timedelta(days=freq_days * i)
             for i in reversed(range(n))]
    return pd.Series([amount] * n, index=pd.DatetimeIndex(dates))


def full_calendar():
    """Dict-shape calendar with all three dates (newer yfinance shape)."""
    return {
        "Earnings Date": [pd.Timestamp("2026-10-30 00:00:00")],
        "Ex-Dividend Date": pd.Timestamp("2026-08-08 00:00:00"),
        "Dividend Date": pd.Timestamp("2026-08-14 00:00:00"),
    }


# ── Data layer ───────────────────────────────────────────────────────


def test_get_events_full_reply(monkeypatch):
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(12, amount=2.0))
    events = market_data.get_events("AAPL")
    assert events["earnings_date"] == "2026-10-30"
    assert events["ex_dividend_date"] == "2026-08-08"
    assert events["dividend_date"] == "2026-08-14"
    # 12 monthly payouts of 2.0, all within a year of the latest one.
    assert events["ttm_total"] == pytest.approx(24.0)
    # Recent caps at the last 10, oldest first.
    assert len(events["recent"]) == 10
    assert events["recent"][0]["date"] < events["recent"][-1]["date"]
    assert all(entry["amount"] == pytest.approx(2.0)
               for entry in events["recent"])
    assert set(events) == {
        "earnings_date", "ex_dividend_date", "dividend_date",
        "ttm_total", "recent",
    }


def test_calendar_dataframe_shape(monkeypatch):
    """Older yfinance returns calendar as a DataFrame — same verdict."""
    frame = pd.DataFrame(
        {"Value": [pd.Timestamp("2026-10-30 00:00:00")]},
        index=["Earnings Date"],
    )
    patch_ticker(monkeypatch, frame, monthly_dividends(2, amount=1.5))
    events = market_data.get_events("AAPL")
    assert events["earnings_date"] == "2026-10-30"
    assert events["ex_dividend_date"] is None
    assert events["dividend_date"] is None
    assert events["ttm_total"] == pytest.approx(3.0)
    assert len(events["recent"]) == 2


def test_dividends_only_no_calendar(monkeypatch):
    patch_ticker(monkeypatch, None, monthly_dividends(3, amount=1.0))
    events = market_data.get_events("AAPL")
    assert events["earnings_date"] is None
    assert events["ex_dividend_date"] is None
    assert events["dividend_date"] is None
    assert events["ttm_total"] == pytest.approx(3.0)
    assert len(events["recent"]) == 3


def test_calendar_only_no_dividends(monkeypatch):
    patch_ticker(monkeypatch, full_calendar(), pd.Series(dtype=float))
    events = market_data.get_events("AAPL")
    assert events["earnings_date"] == "2026-10-30"
    assert events["ex_dividend_date"] == "2026-08-08"
    assert events["dividend_date"] == "2026-08-14"
    assert events["recent"] == []
    assert events["ttm_total"] is None


def test_nothing_usable_raises(monkeypatch):
    patch_ticker(monkeypatch, None, pd.Series(dtype=float))
    with pytest.raises(ValueError):
        market_data.get_events("NOPE")


def test_non_finite_dividends_dropped(monkeypatch):
    series = monthly_dividends(4, amount=1.0)
    series.iloc[1] = float("nan")
    series.iloc[2] = float("inf")
    patch_ticker(monkeypatch, None, series)
    events = market_data.get_events("AAPL")
    assert len(events["recent"]) == 2
    assert events["ttm_total"] == pytest.approx(2.0)


def test_ttm_window(monkeypatch):
    # 24 monthly payouts of 1.0: only the last ~12 fall within 365 days
    # of the latest payout; recent still caps at the last 10.
    series = monthly_dividends(24, amount=1.0, freq_days=30)
    patch_ticker(monkeypatch, None, series)
    events = market_data.get_events("AAPL")
    latest = series.index.max()
    expected = float(series[series.index >= latest - timedelta(days=365)]
                     .sum())
    assert events["ttm_total"] == pytest.approx(expected)
    assert len(events["recent"]) == 10
    # Recent holds the last 10 by date, oldest first.
    assert events["recent"][-1]["date"] == latest.strftime("%Y-%m-%d")


def test_cache_serves_second_call(monkeypatch):
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(2, amount=1.0))
    first = market_data.get_events("AAPL")
    # Different data must NOT leak through (autouse fresh_market_caches
    # isolates us from other tests).
    patch_ticker(monkeypatch, None, monthly_dividends(2, amount=9.0))
    second = market_data.get_events("AAPL")
    assert first == second
    assert second["ttm_total"] == pytest.approx(2.0)


def test_cache_returns_copy(monkeypatch):
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(2, amount=1.0))
    first = market_data.get_events("AAPL")
    first["recent"].append({"date": "2000-01-01", "amount": 0.0})
    second = market_data.get_events("AAPL")
    assert len(second["recent"]) == 2


def test_failure_leaves_nothing_cached(monkeypatch):
    # Successes only: a Yahoo failure must stay retryable next visit,
    # never pose as "no events" for a TTL window.
    patch_ticker(monkeypatch, None, pd.Series(dtype=float))
    with pytest.raises(ValueError):
        market_data.get_events("AAPL")
    assert "AAPL" not in market_data._events_cache
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(2, amount=1.0))
    events = market_data.get_events("AAPL")
    assert events["earnings_date"] == "2026-10-30"


def test_expired_entry_refetches(monkeypatch):
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(2, amount=1.0))
    market_data.get_events("AAPL")
    # Backdate past the 24h TTL: the next call refetches instead of
    # serving the stale entry.
    market_data._events_cache["AAPL"]["fetched_at"] -= (
        market_data._EVENTS_TTL + 1)
    patch_ticker(monkeypatch, full_calendar(),
                 monthly_dividends(2, amount=9.0))
    events = market_data.get_events("AAPL")
    assert events["ttm_total"] == pytest.approx(18.0)


# ── Route ────────────────────────────────────────────────────────────


def test_events_route_passthrough(client, fake_market):
    reply = {
        "earnings_date": "2026-10-30",
        "ex_dividend_date": "2026-08-08",
        "dividend_date": "2026-08-14",
        "ttm_total": 4.0,
        "recent": [
            {"date": "2026-05-14", "amount": 1.0},
            {"date": "2026-08-14", "amount": 1.0},
        ],
    }
    fake_market.events["AAPL"] = reply
    response = client.get("/api/stock/AAPL/events")
    assert response.status_code == 200
    assert response.get_json() == reply


def test_events_route_404_when_empty(client, fake_market):
    # Key absent = Yahoo failure (the fake_market KeyError convention).
    response = client.get("/api/stock/NOPE/events")
    assert response.status_code == 404
    assert "error" in response.get_json()


# ── Template ─────────────────────────────────────────────────────────


def _stock_html(client):
    return client.get("/stock/AAPL").get_data(as_text=True)


def test_stock_page_has_events_ids(client):
    html = _stock_html(client)
    for element_id in ("events-card", "events-toggle", "events-body",
                       "event-earnings", "event-ex-div",
                       "event-div-date", "event-ttm", "events-table",
                       "events-tbody"):
        assert f'id="{element_id}"' in html


def test_events_card_ships_hidden(client):
    html = _stock_html(client)
    assert re.search(
        r'<div class="card events-card" id="events-card" hidden>',
        html,
    )


def test_events_tbody_ships_empty(client):
    html = _stock_html(client)
    assert re.search(r'<tbody id="events-tbody"></tbody>', html)


def test_events_body_ships_collapsed(client):
    # The body ships hidden behind the header toggle: dates are a
    # glance-able extra, so the card opens collapsed.
    html = _stock_html(client)
    assert re.search(r'<div id="events-body" hidden>', html)
    assert re.search(
        r'<button class="card-toggle" id="events-toggle"[^>]*'
        r'aria-expanded="false"[^>]*aria-controls="events-body"',
        html,
    )


def test_events_toggle_flips_body():
    # Meta-test: the toggle listener flips the body's hidden state and
    # the paint path resets it to collapsed on every fresh reply.
    with open("static/js/stock.js") as handle:
        source = handle.read()
    assert 'getElementById("events-toggle").addEventListener("click"' \
        in source
    assert 'getElementById("events-body").hidden = true' in source
    assert 'setAttribute("aria-expanded", "false")' in source


def test_events_css_alignment():
    # Meta-test: the toggle header matches .card h3's 16px voice (not
    # the browser's 1.17em default), amounts read right like the
    # financials table, and the dividends label carries cluster air.
    with open("static/style.css") as handle:
        css = handle.read()
    assert ".card-toggle" in css
    assert "font-size: 16px" in css
    assert ".events-card .events-table td:last-child" in css
    assert "text-align: right" in css
    assert ".events-card .stats-cluster-label" in css
    assert "max-width: 520px" in css
    assert "border-bottom: 1px solid var(--border-subtle)" in css


def test_no_setinterval_in_stock_js():
    with open("static/js/stock.js") as handle:
        assert "setInterval" not in handle.read()
