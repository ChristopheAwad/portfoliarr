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

import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest

import market_data


# ── Fixtures ──────────────────────────────────────────────────────────

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
        "search": None,   # tests assign a list of Yahoo search hits here
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)
            self.fast_info = dict(state["fast_info"])

        @property
        def info(self):
            return state["info"]

        def history(self, period=None, interval="1d", start=None, end=None):
            # Record the unpacked PERIOD_MAP values so tests can prove the
            # mapping reaches yfinance intact. The start/end form is the
            # date-window fetch (get_fx_rate_on); record it distinctly.
            if period is not None:
                calls.append((self.symbol, period, interval))
            else:
                calls.append(("range", self.symbol, start, end))
            return state["history"]

    class FakeSearch:
        """Stand-in for yf.Search: same constructor signature, same
        .quotes attribute the real library exposes after its fetch."""
        def __init__(self, query, max_results=8):
            calls.append(("search", query, max_results))
            self.quotes = state["search"]

    class FakeYf:
        Ticker = FakeTicker
        Search = FakeSearch

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
    point of the cache (Yahoo rate limits). Callers receive independent
    dicts so one route cannot mutate data seen by another."""
    first = market_data.get_quote("AAPL")
    second = market_data.get_quote("AAPL")
    assert fake_yf.calls == ["AAPL"]   # constructed once = one "network" call
    assert first == second
    assert first is not second


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


def test_quote_rejects_nan_price(fake_yf):
    """NaN is not a price — and the `not price` guard can't even SEE it:
    NaN is truthy in Python (only 0/None/"" are falsy), so it sails past
    `if not price`. Unchecked, a NaN lastPrice rides every payload that
    echoes a quote — and jsonify emits a bare `NaN` token, which is
    INVALID JSON for a browser (JSON.parse throws on it). One NaN quote
    would blank the ledger/watchlist/summary the same way a NaN close
    blanks a chart. Same named ValueError as the None case."""
    fake_yf.state["fast_info"]["lastPrice"] = float("nan")
    with pytest.raises(ValueError):
        market_data.get_quote("AAPL")


def test_quote_rejects_nan_previous_close(fake_yf):
    """The same NaN-truthiness hole, other input: change and change_pct
    are DERIVED from previous_close, so a NaN there poisons the derived
    fields even when the price itself is fine. Guarded identically."""
    fake_yf.state["fast_info"]["previousClose"] = float("nan")
    with pytest.raises(ValueError):
        market_data.get_quote("AAPL")


@pytest.mark.parametrize("field", ["lastPrice", "previousClose"])
@pytest.mark.parametrize("value", [float("inf"), float("-inf")])
def test_quote_rejects_infinite_values(fake_yf, field, value):
    fake_yf.state["fast_info"][field] = value
    with pytest.raises(ValueError):
        market_data.get_quote("AAPL")


def test_quote_cache_returns_defensive_copies(fake_yf):
    first = market_data.get_quote("AAPL")
    first["price"] = -1
    second = market_data.get_quote("AAPL")
    assert second["price"] == 150.0
    assert fake_yf.calls == ["AAPL"]


# ── Concurrency: one in-flight request per symbol ──────────────────────
#
# A cold dashboard starts summary + allocation + watchlist requests at the
# same time. Without coordination every route can miss the same cache entry
# and call Yahoo for the same symbol independently. These tests lock the
# fix: concurrent missers share ONE network fetch, different symbols still
# fetch concurrently, and a failed fetch wakes every waiter and stays
# retryable.

def test_concurrent_quote_cache_misses_share_one_yahoo_request(monkeypatch):
    calls = []
    entered = []                     # one entry per thread inside .fast_info
    gate = threading.Event()
    state = {
        "fast_info": {"lastPrice": 150.0, "previousClose": 145.0,
                      "currency": "USD"},
    }

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)     # one entry per Yahoo fetch

        @property
        def fast_info(self):
            entered.append(self.symbol)
            # Hold the "network" open so threads cannot complete before the
            # test proves how many reached it. A genuine cache miss shares
            # ONE fetch; a naive implementation fires one per caller.
            if not gate.wait(10):
                raise RuntimeError("gate never opened")
            return dict(state["fast_info"])

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)

    def fetch():
        answers.append(market_data.get_quote("AAPL"))

    answers = []
    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for t in threads:
        t.start()
    # Wait until the first caller is inside the fake network operation, then
    # give every other caller time to reach it too — the gate keeps the
    # cache cold, so a straggler can only arrive at a second fetch, not a
    # cache hit.
    deadline = time.monotonic() + 5
    while not entered and time.monotonic() < deadline:
        time.sleep(0.005)
    time.sleep(0.3)
    gate.set()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads), \
        "concurrent callers hung — the in-flight coordination deadlocked"

    assert calls == ["AAPL"], \
        f"concurrent missers must share ONE Yahoo fetch, got {calls}"
    assert len(answers) == 4
    for quote in answers:
        assert quote == answers[0]
        assert quote["price"] == 150.0
    assert len({id(a) for a in answers}) == 4, \
        "each caller must receive its own defensive dict"


def test_different_quote_symbols_can_fetch_concurrently(monkeypatch):
    barrier = threading.Barrier(2, timeout=5)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def fast_info(self):
            # Both symbols must be inside their network fetch AT THE SAME
            # TIME — a single global lock during Yahoo work would deadlock
            # this barrier into a BrokenBarrierError (test failure).
            barrier.wait()
            return {"lastPrice": 150.0, "previousClose": 145.0,
                    "currency": "USD"}

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)

    errors = []
    results = {}

    def fetch(symbol):
        try:
            results[symbol] = market_data.get_quote(symbol)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=fetch, args=("AAPL",)),
        threading.Thread(target=fetch, args=("MSFT",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads), \
        "different symbols must not serialize behind one lock"
    assert errors == []
    assert results["AAPL"]["symbol"] == "AAPL"
    assert results["MSFT"]["symbol"] == "MSFT"


def test_concurrent_quote_failure_wakes_waiters_and_stays_retryable(
        monkeypatch):
    calls = []
    entered = []                     # one entry per thread inside .fast_info
    gate = threading.Event()
    fail = True
    state = {
        "fast_info": {"lastPrice": 150.0, "previousClose": 145.0,
                      "currency": "USD"},
    }
    errors = []
    error_lock = threading.Lock()
    # All threads cross the same start gate right before calling get_quote,
    # so the four callers begin their lock-section race together (the main
    # thread then waits for the owner's slot below — no long sleeps that a
    # loaded machine could strap over).
    arrivals = 0
    arrival_lock = threading.Lock()
    start = threading.Barrier(4, timeout=10)

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)

        @property
        def fast_info(self):
            entered.append(self.symbol)
            # Hold the fetch open so every caller either joins the shared
            # future (fixed) or reaches its own fetch (naive) BEFORE the
            # first one raises — otherwise threads would serialize and the
            # test would never measure sharing.
            if not gate.wait(10):
                raise RuntimeError("gate never opened")
            if fail:
                raise RuntimeError("Yahoo is down")
            return dict(state["fast_info"])

    class FakeYf:
        Ticker = FakeTicker

    monkeypatch.setattr(market_data, "yf", FakeYf)

    def fetch():
        nonlocal arrivals
        with arrival_lock:
            arrivals += 1
        try:
            start.wait()
            market_data.get_quote("AAPL")
        except Exception as exc:  # noqa: BLE001 — every failure is collected
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for t in threads:
        t.start()
    # Wait until ALL four callers are about to run get_quote, then for the
    # owner's in-flight slot to be registered (it is, before the network
    # call). Opening the gate any later would let a straggler become a
    # SECOND owner after the first failure cleared its slot — the exact
    # duplicate-fetch race this whole PR removes.
    deadline = time.monotonic() + 5
    while arrivals < 4 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert arrivals == 4, "all four callers must reach the start gate"
    deadline = time.monotonic() + 5
    while market_data._inflight_quotes.get("AAPL") is None \
            and time.monotonic() < deadline:
        time.sleep(0.005)
    assert market_data._inflight_quotes.get("AAPL") is not None, \
        "the owner must register its in-flight slot before the network call"
    time.sleep(0.3)
    gate.set()
    for t in threads:
        t.join(10)
    assert not any(t.is_alive() for t in threads), \
        "concurrent callers hung on a shared failure"
    assert len(errors) == 4, "every waiter must receive the owner's failure"
    for exc in errors:
        assert isinstance(exc, RuntimeError)
    assert "AAPL" not in market_data._cache, \
        "a failed fetch must not be cached"
    assert "AAPL" not in market_data._inflight_quotes, \
        "a completed failure must not leave a stale in-flight entry"

    # Round 2: Yahoo recovers — the next call starts a fresh fetch.
    fail = False
    quote = market_data.get_quote("AAPL")
    assert quote["price"] == 150.0
    assert calls == ["AAPL", "AAPL"], \
        f"one failed round + one retry = two fetches, got {calls}"


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
    (1M is the daily-bars representative: 5D moved to 30-minute bars with
    'YYYY-MM-DD HH:MM' labels — see test_chart_speed.py.) Also asserts
    the PERIOD_MAP unpacking: '1M' → period='1mo', interval='1d'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )
    result = market_data.get_history("AAPL", "1M")
    assert result == {"2026-08-28": 100.0, "2026-08-31": 110.0}
    assert ("AAPL", "1mo", "1d") in fake_yf.calls


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


# ── get_history: NaN closes ───────────────────────────────────────────
# (Regression suite for the blank-chart outage of Sep 2026: Yahoo's
# current-day bar can ship Close = NaN, and a NaN that reached a chart
# payload left the whole chart blank — see the route-level tests in
# test_stock.py / test_routes.py for the end-to-end proof.)

def test_history_skips_nan_close_bars(fake_yf):
    """A NaN Close is NOT a price — it's "no bar printed yet" (Yahoo ships
    this for the in-progress current-day bar; observed live on META's
    2026-09-03 daily bar). Left in, it poisons every consumer: both chart
    routes would emit a bare `NaN` token, which browsers' JSON.parse
    rejects, so response.json() throws and the chart never paints. Skip
    the row — the chart's line just ends one bar earlier, exactly as if
    the bar had never arrived."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, float("nan"), 110.0]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31", "2026-09-01"]),
    )
    result = market_data.get_history("AAPL", "1M")
    assert result == {"2026-08-28": 100.0, "2026-09-01": 110.0}


def test_history_skips_nan_intraday_bars(fake_yf):
    """Same skip for intraday (1D, 5-minute) bars — a session in progress
    can carry NaN closes mid-series too."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [150.0, float("nan"), 151.5]},
        index=pd.to_datetime(
            ["2026-08-31 09:30", "2026-08-31 09:35", "2026-08-31 09:40"]),
    )
    result = market_data.get_history("AAPL", "1D")
    assert result == {"09:30": 150.0, "09:40": 151.5}


def test_history_all_nan_bars_yield_empty_dict(fake_yf):
    """When EVERY bar is NaN the result is {} — a normal empty history,
    not an exception (routes already serve an empty close dict as a blank
    chart, mirroring the empty-DataFrame behaviour)."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [float("nan"), float("nan")]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )
    assert market_data.get_history("AAPL", "5D") == {}


def test_history_skips_infinite_close_bars(fake_yf):
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, float("inf"), float("-inf"), 110.0]},
        index=pd.to_datetime([
            "2026-08-28", "2026-08-31", "2026-09-01", "2026-09-02",
        ]),
    )
    assert market_data.get_history("AAPL", "1M") == {
        "2026-08-28": 100.0, "2026-09-02": 110.0,
    }


def test_history_empty_dataframe_returns_empty_dict(fake_yf):
    """A truly empty DataFrame (zero rows from yfinance — a delisted
    ticker, a Yahoo hiccup, or a period with no data) returns {} without
    crashing. Distinct from the all-NaN test above: that one has rows
    that drop; this one has NO rows at all. yfinance always provides a
    Close column with a DatetimeIndex, even on empty DataFrames."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": pd.Series(dtype=float)},
        index=pd.DatetimeIndex([], name="Date"),
    )
    assert market_data.get_history("AAPL", "1M") == {}


# ── get_stats: the detail page's stats grid ───────────────────────────

def test_get_stats_extracts_and_renames_the_grid_fields(fake_yf):
    """Yahoo's camelCase profile → our snake_case grid keys, exactly the
    translation the route layer relies on. Covers the ORIGINAL 8 keys AND
    the 11 cheap additions (all read out of the same already-fetched
    profile — no extra network call). dividendYield passes through VERBATIM:
    Yahoo already ships it as a percent (verified live on CM.TO/RY.TO/AAPL/
    VZ), so expecting 0.33 → 0.33 pins the pass-through that prevents the
    double-scaling bug (CM.TO showed 263%)."""
    fake_yf.state["info"] = {
        "open": 148.0, "dayHigh": 152.0, "dayLow": 147.5,
        "regularMarketPreviousClose": 145.0, "volume": 55_000_000,
        "fiftyTwoWeekLow": 164.0, "fiftyTwoWeekHigh": 237.25,
        "marketCap": 3_500_000_000_000,
        "trailingPE": 28.5, "trailingEps": 6.10, "dividendYield": 0.33,
        "beta": 1.2, "fiftyDayAverage": 228.4, "twoHundredDayAverage": 210.15,
        "avgVolume10days": 42_000_000, "targetMeanPrice": 260.0,
        "recommendationKey": "buy", "sector": "Technology",
        "industry": "Consumer Electronics",
    }
    assert market_data.get_stats("AAPL") == {
        "open": 148.0, "day_high": 152.0, "day_low": 147.5,
        "prev_close": 145.0, "volume": 55_000_000,
        "week52_low": 164.0, "week52_high": 237.25,
        "market_cap": 3_500_000_000_000,
        "pe_ratio": 28.5, "eps": 6.10, "dividend_yield": 0.33,
        "beta": 1.2, "fifty_day_average": 228.4, "two_hundred_day_average": 210.15,
        "avg_volume": 42_000_000, "target_price": 260.0,
        "recommendation": "buy", "sector": "Technology",
        "industry": "Consumer Electronics",
    }


def test_get_stats_dividend_yield_is_a_percent_pass_through(fake_yf):
    """Yahoo's .info ships dividendYield ALREADY as a percent (verified
    live Sep 2026: CM.TO 2.63 → 2.63%, AAPL 0.33 → 0.33%, VZ 5.59 → 5.59%
    — each matching dividendRate/currentPrice). So get_stats must pass it
    through VERBATIM; multiplying by 100 is the double-scaling bug that
    once showed CM.TO at 263%. A non-payer has no key at all → None
    (gap-fills "—")."""
    fake_yf.state["info"] = {"dividendYield": 0.33}
    assert market_data.get_stats("AAPL")["dividend_yield"] == 0.33

    fake_yf.state["info"] = {"open": 150.0}
    assert market_data.get_stats("AAPL")["dividend_yield"] is None


def test_get_stats_missing_fields_become_none(fake_yf):
    """Different security types legitimately lack different figures (an
    index has no marketCap, an unprofitable company no P/E): absent fields
    come back None — data the frontend gap-fills with "—", never a crash."""
    fake_yf.state["info"] = {"open": 5000.0}
    stats = market_data.get_stats("^GSPC")
    assert stats["open"] == 5000.0
    # The ORIGINAL 8 keys...
    assert stats["market_cap"] is None
    assert stats["volume"] is None
    # ...and ALL 11 cheap additions, in one loop (same contract: absent →
    # None, an index legitimately lacks every valuation/fundamental figure).
    for key in ("pe_ratio", "eps", "dividend_yield", "beta",
                "fifty_day_average", "two_hundred_day_average", "avg_volume",
                "target_price", "recommendation", "sector", "industry"):
        assert stats[key] is None


@pytest.mark.parametrize(
    "provider_key,result_key",
    [
        ("open", "open"),
        ("regularMarketPreviousClose", "prev_close"),
        ("volume", "volume"),
        ("marketCap", "market_cap"),
        ("trailingPE", "pe_ratio"),
    ],
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_get_stats_non_finite_numbers_become_none(
        fake_yf, provider_key, result_key, value):
    fake_yf.state["info"] = {provider_key: value}
    assert market_data.get_stats("AAPL")[result_key] is None


def test_get_stats_prev_close_falls_back_to_alt_spelling(fake_yf):
    """regularMarketPreviousClose missing → previousClose is the same fact
    under Yahoo's alternate key (same `or` pattern as get_name)."""
    fake_yf.state["info"] = {"previousClose": 145.0}
    assert market_data.get_stats("AAPL")["prev_close"] == 145.0


def test_get_stats_empty_profile_raises(fake_yf):
    """Yahoo returning NOTHING about the symbol is a total failure, not
    eight quiet Nones — raise the named ValueError the route layer
    translates into a 404."""
    fake_yf.state["info"] = {}
    with pytest.raises(ValueError):
        market_data.get_stats("NOPE")


# ── FX helpers: the CAD display layer's exchange rates ───────────────

def test_fx_rate_same_currency_shortcuts_to_one_without_network(
        fake_yf, monkeypatch):
    """CAD→CAD is 1.0 by definition — no Yahoo call may happen (proved by
    an attribute access on the fake RAISING if the code ever touched yf)."""
    class Exploding:
        def __getattr__(self, name):
            raise AssertionError("network touched for a same-currency rate")

    monkeypatch.setattr(market_data, "yf", Exploding)
    assert market_data.get_fx_rate("CAD", "CAD") == 1.0


def test_fx_rate_quotes_the_pair_symbol(fake_yf):
    """USD→CAD is Yahoo's 'USDCAD=X' pair: the live rate IS its last
    price. The fake's canned fast_info price is what comes back, and the
    construction log proves the pair symbol was used verbatim."""
    fake_yf.state["fast_info"] = {"lastPrice": 1.3821,
                                  "previousClose": 1.38,
                                  "currency": "CAD"}
    assert market_data.get_fx_rate("USD", "CAD") == 1.3821
    assert "USDCAD=X" in fake_yf.calls


def test_fx_rate_is_cached_like_any_quote(fake_yf):
    """The rate rides the existing quote cache (TTL 120s): a second call
    within the window is a pure dict hit — one construction only."""
    fake_yf.state["fast_info"] = {"lastPrice": 1.3821,
                                  "previousClose": 1.38,
                                  "currency": "CAD"}
    market_data.get_fx_rate("USD", "CAD")
    market_data.get_fx_rate("USD", "CAD")
    assert fake_yf.calls == ["USDCAD=X"]


def test_fx_rate_failure_propagates(fake_yf):
    """Boundary rule: this layer RAISES; the route layer decides what a
    dead FX pair means (degrade to native, exclude, fall back)."""
    fake_yf.state["fast_info"] = {"lastPrice": None,
                                  "previousClose": 1.38,
                                  "currency": "CAD"}
    with pytest.raises(ValueError):
        market_data.get_fx_rate("USD", "CAD")


def test_fx_rate_on_returns_the_close_on_the_date(fake_yf):
    """The historical FACT a ledger row stores: the pair's daily close on
    the transaction's date (last bar on-or-before it)."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [1.402, 1.411, 1.398]},
        index=pd.to_datetime(["2026-08-27", "2026-08-28", "2026-08-31"]),
    )
    assert market_data.get_fx_rate_on("USD", "CAD", "2026-08-31") == 1.398
    # The date-window fetch reached yfinance (start = date − 10d grace
    # window, end = date + 1d so the date itself is included).
    assert ("range", "USDCAD=X", "2026-08-21", "2026-09-01") in fake_yf.calls


def test_fx_rate_on_weekend_falls_back_to_prior_close(fake_yf):
    """A Saturday buy has no bar — the last close ON OR BEFORE it (Friday)
    is the rate 'at the time of buying'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [1.411, 1.398]},
        index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
    )
    assert market_data.get_fx_rate_on("USD", "CAD", "2026-08-29") == 1.411


def test_fx_rate_on_same_currency_shortcuts(fake_yf, monkeypatch):
    class Exploding:
        def __getattr__(self, name):
            raise AssertionError("network touched for a same-currency rate")

    monkeypatch.setattr(market_data, "yf", Exploding)
    assert market_data.get_fx_rate_on("CAD", "CAD", "2026-08-31") == 1.0


def test_fx_rate_on_raises_when_no_bar_covers_the_date(fake_yf):
    """No close on-or-before the date (Yahoo gap, brand-new pair) is a
    named ValueError — the route's cue to fall back to the live rate."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [1.398]},
        index=pd.to_datetime(["2026-09-08"]),   # strictly AFTER the date
    )
    with pytest.raises(ValueError):
        market_data.get_fx_rate_on("USD", "CAD", "2026-08-31")


@pytest.mark.parametrize(
    "rate", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0]
)
def test_fx_rate_on_rejects_invalid_rates(fake_yf, rate):
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [rate]}, index=pd.to_datetime(["2026-08-31"]),
    )
    with pytest.raises(ValueError):
        market_data.get_fx_rate_on("USD", "CAD", "2026-08-31")


# ── search_tickers: the navbar's suggestions ──────────────────────────

def test_search_normalizes_yahoo_hits_in_ranked_order(fake_yf):
    """Hits come back best-first (Yahoo ranks them) with display-friendly
    fields: shortname→longname and exchDisp→exchange fallbacks applied."""
    fake_yf.state["search"] = [
        {"symbol": "AAPL", "shortname": "Apple Inc.", "longname": None,
         "exchDisp": "NASDAQ", "typeDisp": "Equity"},
        {"symbol": "APLE", "shortname": None,
         "longname": "Apple Hospitality REIT, Inc.",
         "exchange": "NYQ", "typeDisp": "Equity"},
    ]
    results = market_data.search_tickers("apple")
    assert results == [
        {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ",
         "type": "Equity"},
        {"symbol": "APLE", "name": "Apple Hospitality REIT, Inc.",
         "exchange": "NYQ", "type": "Equity"},
    ]
    # The query AND the limit both reached yfinance intact.
    assert ("search", "apple", 8) in fake_yf.calls


def test_search_empty_results_are_a_normal_state(fake_yf):
    """Gibberish finding nothing is normal — [] , not an error."""
    fake_yf.state["search"] = []
    assert market_data.search_tickers("zzzz") == []


def test_search_skips_hits_without_a_symbol(fake_yf):
    """A symbol-less hit can't be navigated to — dropped rather than let
    the dropdown offer a link to /stock/None."""
    fake_yf.state["search"] = [
        {"shortname": "mystery hit with no symbol"},
        {"symbol": "AAPL", "shortname": "Apple Inc."},
    ]
    results = market_data.search_tickers("apple")
    assert [r["symbol"] for r in results] == ["AAPL"]


def test_search_failure_propagates(monkeypatch):
    """Boundary rule: this layer RAISES, the route layer translates into
    HTTP (503 here). Verified with its own exploding fake."""
    class ExplodingSearch:
        def __init__(self, query, max_results=8):
            raise ConnectionError("yahoo down")

    class ExplodingYf:
        Search = ExplodingSearch

    monkeypatch.setattr(market_data, "yf", ExplodingYf)
    with pytest.raises(ConnectionError):
        market_data.search_tickers("apple")
