# tests/test_market_data.py
# =========================
# Unit tests for market_data.py — with the network FAKED.
#
# THE NEW CONCEPT IN THIS FILE: MOCKING.
#   market_data.py's job is to call Yahoo Finance. Real tests must NOT:
#   they'd be slow (seconds per fetch), flaky (rate limits, weekends,
#   outages) and non-deterministic (prices change!). So we replace
#   yfinance with a FAKE — a hand-written stand-in object that returns
#   canned data and remembers how often it was used.
#
#   monkeypatch.setattr(market_data, "yf", FakeYf) swaps the `yf` name
#   inside market_data's own namespace. After the test, monkeypatch
#   restores the real yfinance — the fake can't leak into other tests.
#
# THE GOLDEN MOCKING RULE this file exercises:
#   "Patch where it's USED, not where it's defined."
#   market_data.py uses the name `yf`, so THAT is what we replace. (In
#   test_routes.py you'll see the same rule apply to `app.get_quote`.)
#
# WHAT'S WORTH TESTING HERE?
#   - the quote MATH (change = price - previous_close, and its %)
#   - the cache POLICY: one fetch per TTL window, refetch after expiry,
#     names cached for the process lifetime
#   - the error GUARD (incomplete data → named ValueError)
#   - get_history's label formatting (dates for daily bars, times for 1D)

from types import SimpleNamespace

import pandas as pd
import pytest

import market_data


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_caches():
    """Empty the module-level caches before EVERY test in this file.

    WHY: _cache and _name_cache are plain dicts that live as long as the
    process — including across tests! Without this, a quote cached by an
    earlier test would be served to a later one, and cache tests would
    depend on execution ORDER (the classic isolation bug). autouse=True
    means tests don't even have to ask for it.
    """
    market_data._cache.clear()
    market_data._name_cache.clear()
    yield  # the test runs here; nothing to clean up after


@pytest.fixture
def fake_yf(monkeypatch):
    """Replace market_data's `yf` with a controllable fake.

    Returns a namespace with:
      calls — every FakeTicker construction, as either the symbol string
              (quote/name paths) or a (symbol, period, interval) tuple
              (history path), so tests can count "network" hits and prove
              the PERIOD_MAP unpacking
      state — the canned data tests may edit per scenario (set lastPrice
              to None to simulate bad data, swap the DataFrame, ...)
    """
    calls = []
    state = {
        "fast_info": {"lastPrice": 150.0, "previousClose": 145.0,
                      "currency": "USD"},
        "info": {"shortName": "Apple Inc", "longName": None},
        "history": None,  # tests assign a DataFrame here
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)
            self.fast_info = dict(state["fast_info"])

        @property
        def info(self):
            return state["info"]

        def history(self, period, interval):
            # Record the unpacked PERIOD_MAP values so tests can prove the
            # mapping reaches yfinance intact.
            calls.append((self.symbol, period, interval))
            return state["history"]

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)
    return SimpleNamespace(calls=calls, state=state)


# ── get_quote: payload & math ─────────────────────────────────────────

def test_get_quote_builds_payload_with_correct_math(fake_yf):
    """The quote dict must carry raw floats AND the derived day-move
    numbers. 150 - 145 = 5.0; 5/145*100 = 3.448...% — assert with approx
    because floats."""
    quote = market_data.get_quote("AAPL")
    assert quote["symbol"] == "AAPL"
    assert quote["price"] == 150.0
    assert quote["previous_close"] == 145.0
    assert quote["currency"] == "USD"
    assert quote["change"] == pytest.approx(5.0)
    assert quote["change_pct"] == pytest.approx(5 / 145 * 100)


def test_quote_within_ttl_is_served_from_cache(fake_yf):
    """Second call inside the 120s window must NOT re-fetch — the whole
    point of the cache (Yahoo rate limits). Bonus proof: the cache serves
    the SAME dict object, which is exactly why the watchlist route copies
    it before decorating (see app.py's get_quote comment)."""
    first = market_data.get_quote("AAPL")
    second = market_data.get_quote("AAPL")
    assert fake_yf.calls == ["AAPL"]   # constructed once = one "network" call
    assert first is second


def test_quote_after_ttl_expires_refetches(fake_yf):
    """Backdate the cache entry past TTL_SECONDS, and the next call must
    pay the network cost again. No clock-mocking needed: we simply age the
    stored timestamp."""
    market_data.get_quote("AAPL")
    market_data._cache["AAPL"]["fetched_at"] -= market_data.TTL_SECONDS + 1
    market_data.get_quote("AAPL")
    assert fake_yf.calls == ["AAPL", "AAPL"]


def test_incomplete_quote_data_raises(fake_yf):
    """A quote without a price must raise ValueError — a DELIBERATE, named
    error instead of a ZeroDivisionError later (change/previous_close)."""
    fake_yf.state["fast_info"]["lastPrice"] = None
    with pytest.raises(ValueError):
        market_data.get_quote("AAPL")


# ── get_name: permanent cache ─────────────────────────────────────────

def test_get_name_is_cached_for_the_process_lifetime(fake_yf):
    """Names never change, so ONE fetch ever — a second call is a pure
    dict lookup (still exactly one FakeTicker construction)."""
    assert market_data.get_name("AAPL") == "Apple Inc"
    assert market_data.get_name("AAPL") == "Apple Inc"
    assert fake_yf.calls == ["AAPL"]


def test_get_name_falls_back_to_long_name(fake_yf):
    """shortName missing/empty → longName is equally fine to show."""
    fake_yf.state["info"] = {"shortName": "", "longName": "Apple Incorporated"}
    assert market_data.get_name("AAPL") == "Apple Incorporated"


def test_get_name_raises_when_no_name_exists(fake_yf):
    fake_yf.state["info"] = {}
    with pytest.raises(ValueError):
        market_data.get_name("AAPL")


# ── get_history: labels ───────────────────────────────────────────────

def test_history_daily_bars_use_date_labels(fake_yf):
    """Daily bar labels are plain 'YYYY-MM-DD' strings — exactly what the
    frontend's chart wants, no timezone objects leaked to the browser.
    Also asserts the PERIOD_MAP unpacking: '5D' → period='5d', interval='1d'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )
    result = market_data.get_history("AAPL", "5D")
    assert result == {"2026-08-28": 100.0, "2026-08-31": 110.0}
    assert ("AAPL", "5d", "1d") in fake_yf.calls


def test_history_intraday_bars_use_time_labels(fake_yf):
    """The 1D button maps to 5-minute bars — labels become 'HH:MM' so the
    x-axis stays readable."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [150.0, 151.0]},
        index=pd.to_datetime(["2026-08-31 09:30", "2026-08-31 09:35"]),
    )
    result = market_data.get_history("AAPL", "1D")
    assert result == {"09:30": 150.0, "09:35": 151.0}
    assert ("AAPL", "1d", "5m") in fake_yf.calls
