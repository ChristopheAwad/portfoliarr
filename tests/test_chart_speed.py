# tests/test_chart_speed.py
# =========================
# Tests for the chart-speed feature (Sep 2026): the dashboard's 5Y/MAX
# timeframes were slow because (a) get_history hit Yahoo on EVERY click —
# no cache, unlike quotes' 120s TTL dict — (b) /api/portfolio/history
# fetched its tickers SERIALLY (total time = sum of every Yahoo call),
# and (c) MAX fetched a daily bar since IPO (~25k points for ^GSPC).
#
# The feature:
#   1. PERIOD_MAP: 5Y → weekly bars ("1wk"), MAX → monthly bars ("1mo").
#   2. get_history + the portfolio route treat intraday-ness as a
#      PERIOD_MAP FLAG (now `intraday: True` on 1D only — it keyed on the
#      interval string "5m" at the time this file was written), so
#      1wk/1mo get date labels and daily-shaped ledger math.
#   3. A history cache in market_data.py: {(symbol, period_key): ...},
#      TTL 600s for settled bars (daily/weekly/monthly), 120s for the
#      "live" series that include today's still-moving bar. Successes
#      only — failures re-fetch.
#   4. Parallel per-ticker fetches in the portfolio route (ThreadPool),
#      same per-ticker resilience contract: one dead ticker never 503s
#      the chart, it just contributes 0.
#
# This file now also locks the follow-up: 5D serves 30-MINUTE bars
# ("30m") with "YYYY-MM-DD HH:MM" labels (its own five days must not
# collide in the {label: price} dict), the short live TTL, and daily-
# shaped ledger math over the finer bars.
#
# MOCKING (same golden rule as test_market_data.py): market_data uses the
# name `yf`, so THAT is what we replace — a fake whose history() counts
# "network" calls, because every cache assertion here is a call COUNT.
#
# WHICH TESTS FAIL BEFORE THE FEATURE EXISTS:
#   The cache tests (call counts), the interval tests (5y→"1wk",
#   max→"1mo" unpacking), and the parallel-fetch test (a threading
#   Barrier that only releases when two tickers are fetched at once).
#   Two tests are REGRESSION LOCKS that already pass (5Y daily-shape
#   end-to-end, parallel failure isolation) — they exist so the flip to
#   weekly/monthly bars and to a ThreadPool cannot silently break the
#   contracts the rest of the suite established.

import threading
from types import SimpleNamespace

import pandas as pd
import pytest

import app as app_module
import db
import market_data


# ── Fixtures ──────────────────────────────────────────────────────────

# (No cache-clearing fixture here: conftest.py's suite-wide autouse
# fresh_history_cache empties the history cache around EVERY test, so
# these cache assertions always start from an empty cache no matter
# which file ran before this one.)


@pytest.fixture
def fake_yf(monkeypatch):
    """Replace market_data's `yf` with a history-counting fake.

    calls — one entry per history() invocation, as (symbol, period,
            interval): the tuple IS the proof of which PERIOD_MAP values
            reached the "network".
    state["history"] — the DataFrame every call returns; tests assign it.
    state["fail"] — when True, history() raises (a Yahoo outage), for the
            never-cache-a-failure test.
    """
    calls = []
    state = {"history": None, "fail": False}

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period=None, interval="1d", start=None, end=None):
            calls.append((self.symbol, period, interval))
            if state["fail"]:
                raise ValueError("Yahoo is down (fake)")
            return state["history"]

    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    return SimpleNamespace(calls=calls, state=state)


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD", fx_rate=None):
    """Same ledger-seeding helper as test_routes.py: insert through the
    db layer, never raw SQL. (Copied, not imported — helpers live with
    the tests that use them.)"""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


# ── The history cache ─────────────────────────────────────────────────

def test_history_is_cached_within_ttl(fake_yf):
    """Two identical get_history calls = ONE network fetch, same data
    both times. This is the whole point: clicking 5Y → MAX → 5Y must not
    re-buy the same data from Yahoo three times. (5D carries 30-minute
    bars these days, so the fake data is intraday-shaped too.)"""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2026-09-01 09:30", "2026-09-01 10:00"]),
    )

    first = market_data.get_history("AAPL", "5D")
    second = market_data.get_history("AAPL", "5D")

    assert first == second == {
        "2026-09-01 09:30": 100.0, "2026-09-01 10:00": 110.0,
    }
    assert len(fake_yf.calls) == 1


def test_history_refetches_after_ttl_expires(fake_yf, monkeypatch):
    """The cache is YOUNG-enough-to-trust, not forever: after the 600s
    TTL a call re-fetches. 599s after the fetch the entry is still fresh
    (no second call); 601s after, it is stale (second call). time.time is
    faked so the test runs in microseconds, not minutes. (Uses 1M, a
    SETTLED series — the 5D button moved to the short live TTL when it
    went to 30-minute bars; see test_5d_history_uses_the_short_live_ttl.)"""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.to_datetime(["2026-08-28"]),
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(market_data, "time",
                        SimpleNamespace(time=lambda: clock["now"]))

    market_data.get_history("AAPL", "1M")      # fetch #1, stamped at t=1000
    clock["now"] += 599                        # still inside the 600s TTL
    market_data.get_history("AAPL", "1M")
    assert len(fake_yf.calls) == 1

    clock["now"] += 2                          # 601s after the fetch: stale
    market_data.get_history("AAPL", "1M")
    assert len(fake_yf.calls) == 2


def test_intraday_history_uses_the_short_ttl(fake_yf, monkeypatch):
    """1D is different: its last bar is TODAY, still moving all session —
    caching it for 600s would freeze the line mid-day. So intraday
    entries go stale at 120s (the quote cache's cadence): fresh at +60s,
    refetched at +121s."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [150.0, 151.0]},
        index=pd.to_datetime(["2026-08-31 09:30", "2026-08-31 09:35"]),
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(market_data, "time",
                        SimpleNamespace(time=lambda: clock["now"]))

    market_data.get_history("AAPL", "1D")      # fetch #1
    clock["now"] += 60                         # inside even the short TTL
    market_data.get_history("AAPL", "1D")
    assert len(fake_yf.calls) == 1

    clock["now"] += 61                         # 121s: stale under 120s TTL
    market_data.get_history("AAPL", "1D")
    assert len(fake_yf.calls) == 2


def test_5d_history_uses_the_short_live_ttl(fake_yf, monkeypatch):
    """5D joins 1D on the short 'live' TTL: its 30-minute bars include
    TODAY's still-moving bar, so caching it for 600s would freeze the
    last day of the line mid-session. Fresh at +60s, refetched at +121s —
    the mirror image of the 1D test above."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 101.0]},
        index=pd.to_datetime(["2026-09-01 09:30", "2026-09-01 10:00"]),
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr(market_data, "time",
                        SimpleNamespace(time=lambda: clock["now"]))

    market_data.get_history("AAPL", "5D")      # fetch #1
    clock["now"] += 60                         # inside even the short TTL
    market_data.get_history("AAPL", "5D")
    assert len(fake_yf.calls) == 1

    clock["now"] += 61                         # 121s: stale under 120s TTL
    market_data.get_history("AAPL", "5D")
    assert len(fake_yf.calls) == 2


def test_failed_history_fetch_is_never_cached(fake_yf, monkeypatch):
    """A failure must not poison the cache. If the failed result (or the
    exception itself) were stored, the NEXT call would serve the poison —
    a transient Yahoo hiccup would look like a dead ticker for a whole
    TTL window. Instead: raise, store nothing, and the next call pays the
    network cost again."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.to_datetime(["2026-08-28"]),
    )

    fake_yf.state["fail"] = True
    with pytest.raises(ValueError):
        market_data.get_history("AAPL", "1M")

    fake_yf.state["fail"] = False
    result = market_data.get_history("AAPL", "1M")
    assert result == {"2026-08-28": 100.0}     # the retry really fetched
    assert len(fake_yf.calls) == 2

    market_data.get_history("AAPL", "1M")      # and the success IS cached
    assert len(fake_yf.calls) == 2


def test_cache_key_includes_the_period(fake_yf):
    """Same symbol, different timeframe = different data = different
    cache entry. A key of symbol alone would serve 5D bars to the MAX
    chart."""
    df = pd.DataFrame({"Close": [100.0, 110.0]},
                      index=pd.to_datetime(["2026-08-28", "2026-08-31"]))
    fake_yf.state["history"] = df

    market_data.get_history("AAPL", "5D")
    market_data.get_history("AAPL", "1M")

    assert len(fake_yf.calls) == 2


# ── Weekly / monthly bars still speak the date-label dialect ──────────

def test_5y_uses_weekly_bars_with_date_labels(fake_yf):
    """The 5Y button now fetches WEEKLY bars (5× fewer points than daily)
    — and weekly bars must still be labelled 'YYYY-MM-DD', not the HH:MM
    the old else-branch produced for any non-'1d' interval. Also asserts
    the PERIOD_MAP unpacking: '5Y' → period='5y', interval='1wk'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 110.0]},
        index=pd.to_datetime(["2026-08-21", "2026-08-28"]),
    )

    result = market_data.get_history("AAPL", "5Y")

    assert result == {"2026-08-21": 100.0, "2026-08-28": 110.0}
    assert ("AAPL", "5y", "1wk") in fake_yf.calls


def test_max_uses_monthly_bars_with_date_labels(fake_yf):
    """MAX now fetches MONTHLY bars — ^GSPC's ~25,000 daily points since
    1927 collapse to ~1,200 — with the same 'YYYY-MM-DD' labels. The
    unpacking assertion locks 'MAX' → period='max', interval='1mo'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [1.0, 5000.0]},
        index=pd.to_datetime(["1927-01-01", "2026-08-31"]),
    )

    result = market_data.get_history("^GSPC", "MAX")

    # Monthly bars are labelled with the bar's OWN date — no first-of-
    # month normalization (get_history just takes the timestamp's date
    # part, exactly as it does for daily bars).
    assert result == {"1927-01-01": 1.0, "2026-08-31": 5000.0}
    assert ("^GSPC", "max", "1mo") in fake_yf.calls


# ── 5D: 30-minute bars, datetime labels ───────────────────────────────

def test_5d_uses_30m_bars_with_datetime_labels(fake_yf):
    """The 5D button serves 30-MINUTE bars (~65 points, Google Finance's
    choice) — plain daily bars left it a 5-point zigzag, the odd one out
    once 5Y/MAX went coarse. Unpacking assertion locks '5D' →
    period='5d', interval='30m'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 101.0, 110.0, 111.0]},
        index=pd.to_datetime([
            "2026-09-01 09:30", "2026-09-01 15:30",
            "2026-09-02 09:30", "2026-09-02 15:30",
        ]),
    )

    result = market_data.get_history("AAPL", "5D")

    # Labels are "YYYY-MM-DD HH:MM" — and MUST be. get_history returns a
    # {label: price} dict, so a multi-day intraday series labelled with
    # bare "HH:MM" would collide ("09:30" occurs on all five days) and
    # silently drop four days of bars. Same timestamp on both days below
    # proves each day survives as its own key.
    assert result == {
        "2026-09-01 09:30": 100.0,
        "2026-09-01 15:30": 101.0,
        "2026-09-02 09:30": 110.0,
        "2026-09-02 15:30": 111.0,
    }
    assert ("AAPL", "5d", "30m") in fake_yf.calls


def test_5d_portfolio_chart_is_daily_shaped_on_30m_bars(client, fake_yf):
    """End-to-end: the 5D chart keeps every daily-shape behaviour the
    suite relies on — the axis trims at the first logged investment (the
    pre-buy 08-31 bar is dropped), and a transaction applies at its
    day's FIRST 30-minute bar (a date-only ledger can't know the minute;
    lexicographic '2026-09-03' <= '2026-09-03 09:30' does the dating).
    The 09-03 buy must NOT leak into the 09-02 15:30 bar."""
    seed_transaction(ticker="AAPL", date="2026-09-01", qty=1,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-09-03", qty=2,
                     currency="CAD")
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [90.0, 100.0, 105.0, 110.0, 112.0, 120.0, 125.0, 130.0]},
        index=pd.to_datetime([
            "2026-08-31 15:30",   # pre-first-buy bar → trimmed
            "2026-09-01 09:30", "2026-09-01 15:30",
            "2026-09-02 09:30", "2026-09-02 15:30",
            "2026-09-03 09:30", "2026-09-03 15:30",
            "2026-09-04 09:30",
        ]),
    )

    body = client.get("/api/portfolio/history?period=5D").get_json()
    # 1 share from the 09-01 buy; 3 shares once the 09-03 buy lands at
    # that day's first bar (3 × 120 = 360).
    assert body == {
        "labels": [
            "2026-09-01 09:30", "2026-09-01 15:30",
            "2026-09-02 09:30", "2026-09-02 15:30",
            "2026-09-03 09:30", "2026-09-03 15:30",
            "2026-09-04 09:30",
        ],
        "values": [100.0, 105.0, 110.0, 112.0, 360.0, 375.0, 390.0],
    }


# ── 3M: daily bars, date labels ───────────────────────────────────────

def test_3m_uses_daily_bars_with_date_labels(fake_yf):
    """The 3M button serves DAILY bars (~63 closes) — the interval that
    keeps the whole ladder monotonically dense (1M 22 → 3M 63 → 6M 126 →
    1Y 252) instead of the old hourly 3M (~440) out-densifying every
    later timeframe. Unpacking assertion locks '3M' → period='3mo',
    interval='1d'."""
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 105.0, 110.0, 112.0]},
        index=pd.to_datetime([
            "2026-09-01", "2026-09-02",
            "2026-09-03", "2026-09-04",
        ]),
    )

    result = market_data.get_history("AAPL", "3M")

    # Date-only labels — one bar per day, so each date is its own key.
    assert result == {
        "2026-09-01": 100.0,
        "2026-09-02": 105.0,
        "2026-09-03": 110.0,
        "2026-09-04": 112.0,
    }
    assert ("AAPL", "3mo", "1d") in fake_yf.calls


def test_3m_portfolio_chart_is_daily_shaped(client, fake_yf):
    """End-to-end: the 3M chart is an ordinary daily-shaped series — the
    axis trims at the first logged investment (the pre-buy 08-31 bar is
    dropped) and a transaction applies at its date's bar. A NaN close on
    today's in-progress bar is still dropped by get_history. The 09-03
    buy must NOT leak into the 09-02 bar."""
    seed_transaction(ticker="AAPL", date="2026-09-01", qty=1,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-09-03", qty=2,
                     currency="CAD")
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [90.0, 100.0, 105.0, 110.0, 112.0,
                   float("nan")]},
        index=pd.to_datetime([
            "2026-08-31",   # pre-first-buy bar → trimmed
            "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
            "2026-09-05",   # NaN close = day in progress → dropped
        ]),
    )

    body = client.get("/api/portfolio/history?period=3M").get_json()
    # 1 share from the 09-01 buy; 3 shares once the 09-03 buy lands at
    # its date's bar (3 × 110 = 330). The NaN 09-05 bar ends the line at
    # 09-04.
    assert body == {
        "labels": ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
        "values": [100.0, 105.0, 330.0, 336.0],
    }


def test_intraday_and_live_flags_stay_exclusive():
    """REGRESSION LOCK (passes before AND after the 3M revert): across
    the WHOLE PERIOD_MAP, `intraday` is True ONLY for the single-day 1D
    view (clock-time labels + the route's first-bar ledger branch) and
    `live` is True ONLY for 1D and 5D (the 120s TTL — today's bar still
    moves). Every multi-day series — 5D's 30-minute bars and 3M's daily
    bars alike — must keep the daily-shaped ledger math and the settled
    600s TTL. A flip that accidentally set either flag on 3M would move
    it into the wrong ledger branch and cache tier; this test names that
    exact failure."""
    intraday_periods = [key for key, tf in market_data.PERIOD_MAP.items()
                        if tf["intraday"]]
    live_periods = [key for key, tf in market_data.PERIOD_MAP.items()
                    if tf["live"]]
    assert intraday_periods == ["1D"]
    assert live_periods == ["1D", "5D"]


# ── The portfolio route with the new intervals ────────────────────────

def test_5y_portfolio_chart_stays_daily_shaped(client, fake_yf):
    """REGRESSION LOCK (passes before AND after the feature): end-to-end,
    the 5Y chart must keep every daily-shape behaviour the suite relies
    on — weekly bars are labelled as DATES, and the axis starts at the
    first logged investment (the pre-buy 08-21 bar is trimmed). This is
    the test that catches the lazy version of the fix, where flipping
    5Y to '1wk' would leave get_history or the route treating any
    non-'1d' interval as intraday (time labels, no axis trimming)."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=1,
                     currency="CAD")
    fake_yf.state["history"] = pd.DataFrame(
        {"Close": [100.0, 110.0, 120.0]},
        index=pd.to_datetime(
            ["2026-08-21", "2026-08-28", "2026-09-04"]),  # weekly bars
    )

    body = client.get("/api/portfolio/history?period=5Y").get_json()
    assert body == {
        "labels": ["2026-08-28", "2026-09-04"],
        "values": [110.0, 120.0],
    }


# ── Parallel fetching in /api/portfolio/history ───────────────────────

def test_portfolio_history_fetches_tickers_in_parallel(client, monkeypatch):
    """The serial-loop killer: a threading.Barrier that only releases
    when TWO tickers are being fetched at the same time. Parallel code
    sails through; the old serial loop deadlocks the first waiter until
    the barrier's timeout, both tickers end up failed-and-zero, and the
    assertions below fail. (Each ticker has TWO transactions to also
    prove the per-symbol dedupe survives the rewrite: one fetch per
    symbol, not per transaction.)"""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=5,
                     currency="CAD")
    seed_transaction(ticker="MSFT", date="2026-08-28", qty=2,
                     currency="CAD")
    seed_transaction(ticker="MSFT", date="2026-08-31", qty=3,
                     currency="CAD")

    calls = []
    barrier = threading.Barrier(2)

    def fake_get_history(symbol, period):
        calls.append(symbol)
        barrier.wait(timeout=10)   # serial code stalls here, then breaks
        return {"2026-08-28": 110.0, "2026-08-31": 120.0}

    monkeypatch.setattr(app_module, "get_history", fake_get_history)

    res = client.get("/api/portfolio/history?period=5D")
    assert res.status_code == 200
    body = res.get_json()
    # First bar (08-28): only the 08-28 buys have applied — 10 AAPL +
    # 2 MSFT = 12 shares × 110 = 1320. Second bar (08-31): the 08-31
    # buys land there (a tx applies at the first bar ON-OR-AFTER its
    # date), so all 20 shares × 120 = 2400.
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1320.0, 2400.0]
    # dedupe: one fetch per UNIQUE symbol, even with two txs each
    assert sorted(calls) == ["AAPL", "MSFT"]


def test_parallel_fetch_failure_isolation(client, monkeypatch):
    """REGRESSION LOCK for the resilience contract under the new parallel
    code: one dead ticker must not break the chart — it contributes 0
    while the healthy ticker still draws (the same per-ticker try/except
    contract, now inside the worker)."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="BAD", date="2026-08-28", qty=10,
                     currency="CAD")

    def fake_get_history(symbol, period):
        if symbol == "BAD":
            raise ValueError("delisted (fake)")
        return {"2026-08-28": 110.0, "2026-08-31": 120.0}

    monkeypatch.setattr(app_module, "get_history", fake_get_history)

    res = client.get("/api/portfolio/history?period=5D")
    assert res.status_code == 200
    assert res.get_json() == {
        "labels": ["2026-08-28", "2026-08-31"],
        "values": [1100.0, 1200.0],   # AAPL only; BAD contributes 0
    }
