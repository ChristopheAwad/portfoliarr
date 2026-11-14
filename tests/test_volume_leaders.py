# tests/test_volume_leaders.py
# =============================
# Unit tests for the volume-leaders feature: market_data.get_volume_leaders()
# and the GET /api/market/volume-leaders route.
#
# WHAT'S WORTH TESTING HERE?
#   - get_volume_leaders picks top 1 per sector by volume
#   - final list is sorted by volume descending, capped at 10
#   - caching: second call within TTL returns cached result
#   - graceful failure: one sector fails, others still returned
#   - all sectors fail: raises ValueError; the route returns an empty list
#   - API route returns correct structure and never 500

from collections import Counter
from concurrent.futures import Future
import threading
from types import SimpleNamespace

import pytest

import market_data
import app as app_module
import perf


# ── Helpers ────────────────────────────────────────────────────────────

def _make_info(name, price, prev_close, volume, sector="Technology"):
    """Build a fake Ticker.info dict with the fields get_volume_leaders reads."""
    return {
        "shortName": name,
        "longName": None,
        "regularMarketPrice": price,
        "regularMarketPreviousClose": prev_close,
        "volume": volume,
        "sector": sector,
    }


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def fake_yf_for_volume(monkeypatch):
    """Replace yfinance with a fake that returns canned info per symbol.

    Returns a namespace with:
      info_data — dict mapping symbol → info dict (tests set this up)
      calls    — list of symbols that were constructed (to count network hits)
    """
    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            calls.append(symbol)

        @property
        def info(self):
            data = info_data.get(self.symbol)
            if data is None:
                raise ValueError(f"no info for {self.symbol}")
            return data

    class FakeYf:
        Ticker = FakeTicker

    info_data = {}
    monkeypatch.setattr(market_data, "yf", FakeYf)
    return SimpleNamespace(info_data=info_data, calls=calls)


# ── get_volume_leaders: sector selection ───────────────────────────────

def test_top_one_per_sector(fake_yf_for_volume):
    """Each sector's highest-volume ticker is picked, even when a lower-
    volume ticker appears first in the candidates list — and exactly ONE
    winner per sector (a bug emitting two would fail the equality)."""
    # Technology sector: NVDA (500M) beats AAPL (100M) and MSFT (30M)
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
        "MSFT": _make_info("Microsoft", 420.0, 415.0, 30_000_000),
    })
    leaders = market_data.get_volume_leaders()

    # Only Technology resolves with this data, so exactly 1 leader — NVDA.
    symbols = [l["symbol"] for l in leaders]
    assert symbols == ["NVDA"]


def test_sorted_by_volume_descending(fake_yf_for_volume):
    """The final list is sorted by volume, highest first. Needs THREE
    different sectors — same-sector tickers collapse to one winner, so a
    single-sector fill would make the order assertion vacuous (a list of
    one is always 'sorted')."""
    fake_yf_for_volume.info_data.update({
        # Technology's winner: NVDA 500M
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
        "MSFT": _make_info("Microsoft", 420.0, 415.0, 30_000_000),
        # Energy's winner: XOM 300M
        "XOM": _make_info("Exxon", 110.0, 108.0, 300_000_000),
        "CVX": _make_info("Chevron", 160.0, 158.0, 90_000_000),
        # Financials' winner: JPM 100M
        "JPM": _make_info("JPMorgan", 240.0, 238.0, 100_000_000),
        "BAC": _make_info("Bank of America", 45.0, 44.0, 80_000_000),
    })
    leaders = market_data.get_volume_leaders()
    # Exact order: 500M, then 300M, then 100M — not just "sorted-ish".
    assert [l["symbol"] for l in leaders] == ["NVDA", "XOM", "JPM"]


def test_capped_at_ten(fake_yf_for_volume):
    """The cap BITES, not just 'is not exceeded': all 11 sectors resolve,
    exactly 10 come back (an off-by-one [:9] or a missing cap would fail)."""
    for sector_tickers in market_data.SECTOR_LEADERS.values():
        for sym in sector_tickers:
            fake_yf_for_volume.info_data[sym] = _make_info(
                sym, 100.0, 99.0, 50_000_000
            )
    leaders = market_data.get_volume_leaders()
    assert len(leaders) == 10


def test_leader_payload_has_required_fields(fake_yf_for_volume):
    """Each leader dict carries the fields the frontend needs."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple Inc", 190.0, 188.0, 100_000_000),
    })
    leaders = market_data.get_volume_leaders()
    assert len(leaders) >= 1
    leader = leaders[0]
    assert "symbol" in leader
    assert "name" in leader
    assert "price" in leader
    assert "change" in leader
    assert "change_pct" in leader
    assert "volume" in leader


def test_leader_math(fake_yf_for_volume):
    """Price, change, and change_pct are computed correctly."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 180.0, 100_000_000),
    })
    leaders = market_data.get_volume_leaders()
    leader = leaders[0]
    assert leader["price"] == 190.0
    assert leader["change"] == pytest.approx(10.0)
    assert leader["change_pct"] == pytest.approx(10 / 180 * 100)


# ── get_volume_leaders: caching ────────────────────────────────────────

def test_second_call_within_ttl_returns_cached(fake_yf_for_volume):
    """Volume data is cached, but callers receive independent objects."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
    })
    first = market_data.get_volume_leaders()
    second = market_data.get_volume_leaders()
    assert first == second
    assert first is not second
    assert len(fake_yf_for_volume.calls) == sum(
        len(symbols) for symbols in market_data.SECTOR_LEADERS.values()
    )


def test_cache_expires_after_ttl(fake_yf_for_volume):
    """Backdate the cache entry past TTL, next call refetches."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
    })
    market_data.get_volume_leaders()
    # Age the cache entry past TTL
    market_data._volume_cache["data"]["fetched_at"] -= (
        market_data._VOLUME_TTL + 1
    )
    market_data.get_volume_leaders()
    # FakeTicker was constructed again (refetched)
    assert len(fake_yf_for_volume.calls) >= 2


# ── get_volume_leaders: failure handling ───────────────────────────────

def test_one_sector_fails_others_still_returned(fake_yf_for_volume):
    """Per-sector resilience: TWO sectors start alive, one dies mid-scan
    (its tickers raise) — the survivor's leader still comes back. Filling
    both then deleting one's data is what makes 'others still returned'
    real: with only one sector filled there'd be nothing to survive."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
        "XOM": _make_info("Exxon", 110.0, 108.0, 300_000_000),
    })
    del fake_yf_for_volume.info_data["XOM"]  # Energy just went dark
    leaders = market_data.get_volume_leaders()
    assert [l["symbol"] for l in leaders] == ["AAPL"]


def test_all_sectors_fail_raises_value_error(fake_yf_for_volume):
    """Total failure raises the named ValueError — it must NOT return an
    empty list, because an empty result would be cached for 5 minutes
    (the successes-only rule the history cache already lives by)."""
    # info_data is empty → every ticker raises inside _fetch → nothing resolves
    with pytest.raises(ValueError):
        market_data.get_volume_leaders()


def test_failed_fetch_is_not_cached(fake_yf_for_volume):
    """The regression lock for the successes-only rule: a total failure
    leaves NO cache entry behind, so Yahoo recovering is visible on the
    very next call (fresh constructions), not 5 minutes later."""
    # 1. Everything fails → raise, and the cache stays empty.
    with pytest.raises(ValueError):
        market_data.get_volume_leaders()
    assert market_data._volume_cache == {}

    # 2. Yahoo "recovers" — the next call fetches for real and succeeds.
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
    })
    leaders = market_data.get_volume_leaders()
    assert [l["symbol"] for l in leaders] == ["AAPL"]
    assert len(fake_yf_for_volume.calls) > 0  # a genuine fetch happened


def test_missing_volume_field_skips_ticker(fake_yf_for_volume):
    """A ticker whose info lacks `volume` is skipped — not a crash, and
    not a zero-volume winner. Its sector still resolves via a sibling."""
    fake_yf_for_volume.info_data.update({
        "AAPL": {
            "shortName": "Apple",
            "regularMarketPrice": 190.0,
            "regularMarketPreviousClose": 188.0,
            # volume key missing → skipped
        },
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
    })
    leaders = market_data.get_volume_leaders()
    assert [l["symbol"] for l in leaders] == ["NVDA"]


def test_unusable_high_volume_candidate_falls_back_to_sibling(
        fake_yf_for_volume):
    """Validate the complete candidate before selecting a sector winner."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", None, 188.0, 900_000_000),
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
    })
    leaders = market_data.get_volume_leaders()
    assert [leader["symbol"] for leader in leaders] == ["NVDA"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("volume", "many"),
        ("volume", float("inf")),
        ("regularMarketPrice", float("nan")),
        ("regularMarketPreviousClose", float("-inf")),
    ],
)
def test_malformed_candidate_does_not_abort_other_sectors(
        fake_yf_for_volume, field, value):
    bad = _make_info("Apple", 190.0, 188.0, 100_000_000)
    bad[field] = value
    fake_yf_for_volume.info_data.update({
        "AAPL": bad,
        "XOM": _make_info("Exxon", 110.0, 108.0, 300_000_000),
    })
    leaders = market_data.get_volume_leaders()
    assert [leader["symbol"] for leader in leaders] == ["XOM"]


def test_volume_cache_returns_defensive_copies(fake_yf_for_volume):
    fake_yf_for_volume.info_data["AAPL"] = _make_info(
        "Apple", 190.0, 188.0, 100_000_000
    )
    first = market_data.get_volume_leaders()
    first[0]["price"] = -1
    second = market_data.get_volume_leaders()
    assert second[0]["price"] == 190.0


# ── Route tests ────────────────────────────────────────────────────────

def test_volume_leaders_route_returns_200(client, fake_market, monkeypatch):
    """The API endpoint returns 200 with a leaders list."""
    # Patch get_volume_leaders on the module where it's used (app.py —
    # the same "patch where it's USED" rule as the fake_market fixture).
    monkeypatch.setattr(
        app_module, "get_volume_leaders",
        lambda: [
            {
                "symbol": "AAPL", "name": "Apple Inc",
                "price": 190.0, "change": 2.0, "change_pct": 1.05,
                "volume": 100_000_000,
            }
        ],
    )
    res = client.get("/api/market/volume-leaders")
    assert res.status_code == 200
    body = res.get_json()
    assert "leaders" in body
    assert len(body["leaders"]) == 1
    assert body["leaders"][0]["symbol"] == "AAPL"


def test_volume_leaders_route_empty_list(client, fake_market, monkeypatch):
    """Route passthrough: whatever the data layer hands back is echoed
    verbatim, so an empty list is 200 + {"leaders": []}. (The real data
    layer raises instead of returning [] on total failure — this patched
    shape is defense-in-depth for the route's own contract.)"""
    monkeypatch.setattr(app_module, "get_volume_leaders", lambda: [])
    res = client.get("/api/market/volume-leaders")
    assert res.status_code == 200
    assert res.get_json()["leaders"] == []


def test_volume_leaders_route_exception_returns_200(
        client, fake_market, monkeypatch):
    """If get_volume_leaders raises (e.g. the total-failure ValueError),
    the route catches and returns 200 with empty leaders — never a 500."""
    def _raise():
        raise ValueError("no volume leaders resolved from any sector")

    monkeypatch.setattr(app_module, "get_volume_leaders", _raise)
    res = client.get("/api/market/volume-leaders")
    assert res.status_code == 200
    assert res.get_json()["leaders"] == []


# ── Concurrent composite cache refreshes ──────────────────────────────

@pytest.fixture
def joined_volume_waiters(monkeypatch):
    """Observe waiters before releasing a blocked provider, without sleeps."""
    condition = threading.Condition()
    joined = []

    class TrackedFuture(Future):
        def result(self, timeout=None):
            with condition:
                joined.append(self)
                condition.notify_all()
            return super().result(timeout=timeout)

    monkeypatch.setattr(market_data, "Future", TrackedFuture)

    def wait_for(count):
        with condition:
            return condition.wait_for(lambda: len(joined) >= count, timeout=2)

    return wait_for


def _start_call(function=market_data.get_volume_leaders):
    outcome = []

    def call():
        try:
            outcome.append(("ok", function()))
        except BaseException as exc:
            outcome.append(("error", exc))

    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    return thread, outcome


def _join_calls(calls):
    for thread, _ in calls:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread, _ in calls), \
        "a market-data caller did not wake up"
    assert all(len(outcome) == 1 for _, outcome in calls)
    return [outcome[0] for _, outcome in calls]


def _volume_metrics():
    return {
        row["tags"]["cache"]: row["count"]
        for row in perf.snapshot()["metrics"]
        if row["name"] == "market.get_volume_leaders"
    }


class _BlockedInfoProvider:
    """Track active .info reads while holding all provider calls on a gate."""

    def __init__(self, info_by_symbol):
        self.info_by_symbol = info_by_symbol
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.eight_entered = threading.Event()
        self.calls = []
        self.active = 0
        self.peak = 0

    def Ticker(self, symbol):
        provider = self

        class FakeTicker:
            @property
            def info(self):
                with provider.lock:
                    provider.calls.append(symbol)
                    provider.active += 1
                    provider.peak = max(provider.peak, provider.active)
                    if provider.active >= 8:
                        provider.eight_entered.set()
                try:
                    if not provider.release.wait(timeout=10):
                        raise RuntimeError("provider gate did not open")
                    value = provider.info_by_symbol.get(symbol)
                    if isinstance(value, BaseException):
                        raise value
                    return value
                finally:
                    with provider.lock:
                        provider.active -= 1

            @property
            def fast_info(self):
                return {"lastPrice": 25.0, "previousClose": 20.0,
                        "currency": "USD"}

        return FakeTicker()


def _full_volume_fixture(partial=False):
    """Use distinct sector winners, including a final-list volume tie."""
    info = {}
    expected = []
    for sector_index, tickers in enumerate(market_data.SECTOR_LEADERS.values()):
        for ticker_index, symbol in enumerate(tickers):
            volume = (sector_index + 1) * 100 + ticker_index
            # The last two sectors have equal winning volume; their final
            # order must use symbol rather than completion order.
            if sector_index == 10:
                volume = 1000 + ticker_index
            info[symbol] = _make_info(symbol, 110.0, 100.0, volume)
        expected.append(tickers[-1])

    if partial:
        # Both an exception and an invalid high-volume candidate must be
        # skipped, leaving the third candidate as Technology's winner.
        info["MSFT"] = RuntimeError("fake provider failure")
        info["NVDA"]["regularMarketPrice"] = None
        expected[0] = "AAPL"
        # An entirely unavailable sector must be absent from every reply.
        for symbol in ("LIN", "APD", "SHW"):
            info[symbol] = RuntimeError("fake sector outage")
        expected.remove("SHW")

    expected.sort(key=lambda symbol: (-info[symbol]["volume"], symbol))
    return info, expected[:10]


@pytest.mark.parametrize(
    "callers,expired,partial",
    [(2, False, False), (8, False, True), (8, True, False)],
)
def test_concurrent_volume_misses_share_one_scan_and_return_copies(
        monkeypatch, joined_volume_waiters, callers, expired, partial):
    info, expected = _full_volume_fixture(partial=partial)
    provider = _BlockedInfoProvider(info)
    monkeypatch.setattr(market_data, "yf", provider)
    if expired:
        market_data._volume_cache["data"] = {
            "leaders": [{"symbol": "STALE"}],
            "fetched_at": market_data.time.time() - market_data._VOLUME_TTL - 1,
        }

    calls = [_start_call()]
    try:
        entered = provider.eight_entered.wait(timeout=5)
        calls.extend(_start_call() for _ in range(callers - 1))
        joined = joined_volume_waiters(callers - 1)
    finally:
        provider.release.set()
        outcomes = _join_calls(calls)

    candidates = [symbol for tickers in market_data.SECTOR_LEADERS.values()
                  for symbol in tickers]
    assert entered, "the original eight provider workers must run concurrently"
    assert len(candidates) == 33
    assert Counter(provider.calls) == Counter(candidates), \
        "concurrent consumers must share one 33-candidate scan"
    assert joined, "all remaining callers must join the pending scan"
    assert provider.peak == 8
    assert all(status == "ok" for status, _ in outcomes)
    replies = [value for _, value in outcomes]
    assert all([row["symbol"] for row in reply] == expected for reply in replies)
    assert all(len(reply) == 10 for reply in replies)
    assert all(set(row) == {"symbol", "name", "price", "change", "change_pct",
                            "volume"} for row in replies[0])
    assert len({id(reply) for reply in replies}) == callers
    assert len({id(reply[0]) for reply in replies}) == callers
    assert replies[0][0]["price"] == 110.0
    assert replies[0][0]["change"] == 10.0
    assert replies[0][0]["change_pct"] == 10.0

    replies[0][0]["price"] = -1
    replies[0].pop()
    assert replies[1][0]["price"] == 110.0
    replies[1][0]["symbol"] = "CHANGED"
    warm = market_data.get_volume_leaders()
    assert [row["symbol"] for row in warm] == expected
    assert warm[0]["price"] == 110.0
    assert len(provider.calls) == 33
    assert _volume_metrics() == {"hit": 1, "miss": 1, "wait": callers - 1}


def test_volume_cache_exact_ttl_boundary(fake_yf_for_volume, monkeypatch):
    fake_yf_for_volume.info_data["AAPL"] = _make_info("Apple", 110, 100, 10)
    clock = {"now": 10_000.0}
    monkeypatch.setattr(market_data.time, "time", lambda: clock["now"])

    assert market_data.get_volume_leaders()[0]["symbol"] == "AAPL"
    clock["now"] += market_data._VOLUME_TTL - 0.001
    assert market_data.get_volume_leaders()[0]["symbol"] == "AAPL"
    assert len(fake_yf_for_volume.calls) == 33
    clock["now"] += 0.001
    assert market_data.get_volume_leaders()[0]["symbol"] == "AAPL"
    assert len(fake_yf_for_volume.calls) == 66
    assert _volume_metrics() == {"hit": 1, "miss": 2}


def test_expired_volume_cache_is_not_served_or_refreshed_on_failure(
        fake_yf_for_volume, monkeypatch):
    clock = 10_000.0
    monkeypatch.setattr(market_data.time, "time", lambda: clock)
    stale = {"leaders": [{"symbol": "STALE"}],
             "fetched_at": clock - market_data._VOLUME_TTL}
    market_data._volume_cache["data"] = stale

    with pytest.raises(ValueError, match="no volume leaders resolved"):
        market_data.get_volume_leaders()
    assert market_data._volume_cache["data"] == stale
    assert len(fake_yf_for_volume.calls) == 33

    fake_yf_for_volume.info_data["AAPL"] = _make_info("Apple", 110, 100, 10)
    assert market_data.get_volume_leaders()[0]["symbol"] == "AAPL"
    assert len(fake_yf_for_volume.calls) == 66
    assert market_data._volume_cache["data"]["fetched_at"] == clock


def test_equal_volume_sector_keeps_the_first_completed_candidate(monkeypatch):
    import concurrent.futures

    monkeypatch.setattr(
        market_data, "SECTOR_LEADERS", {"Technology": ["ZZZ", "AAA"]}
    )
    first_processed = threading.Event()
    second_returned = threading.Event()
    original_as_completed = concurrent.futures.as_completed

    def observe_completion(futures):
        for future in original_as_completed(futures):
            yield future
            if futures[future][1] == "ZZZ":
                first_processed.set()

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            if self.symbol == "AAA":
                if not first_processed.wait(timeout=5):
                    raise RuntimeError("first candidate was not processed")
                second_returned.set()
            return _make_info(self.symbol, 110, 100, 1000)

    monkeypatch.setattr(concurrent.futures, "as_completed", observe_completion)
    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    assert [row["symbol"] for row in market_data.get_volume_leaders()] == ["ZZZ"]
    assert second_returned.is_set()


class _ProviderAbort(BaseException):
    pass


@pytest.mark.parametrize("failure", ["total", "abort"])
def test_concurrent_volume_failure_wakes_waiters_and_can_retry(
        monkeypatch, joined_volume_waiters, failure):
    info, _ = _full_volume_fixture()
    candidates = list(info)
    exception = (RuntimeError("fake Yahoo failure") if failure == "total"
                 else _ProviderAbort("fake scan abort"))
    provider = _BlockedInfoProvider({symbol: exception for symbol in candidates})
    monkeypatch.setattr(market_data, "yf", provider)
    calls = [_start_call()]
    try:
        entered = provider.eight_entered.wait(timeout=5)
        calls.extend(_start_call() for _ in range(3))
        joined = joined_volume_waiters(3)
    finally:
        provider.release.set()
        outcomes = _join_calls(calls)

    assert entered
    assert Counter(provider.calls) == Counter(candidates)
    assert joined
    error_type = ValueError if failure == "total" else _ProviderAbort
    assert all(status == "error" and isinstance(value, error_type)
               for status, value in outcomes)
    if failure == "total":
        assert all(str(value) == "no volume leaders resolved from any sector"
                   for _, value in outcomes)
    assert market_data._volume_cache == {}
    assert _volume_metrics() == {"miss": 1}

    provider.info_by_symbol = info
    assert market_data.get_volume_leaders()
    assert Counter(provider.calls) == Counter(candidates * 2)
    assert _volume_metrics() == {"miss": 2}


def test_executor_failure_wakes_volume_waiters_and_allows_retry(
        monkeypatch, joined_volume_waiters):
    import concurrent.futures

    original_executor = concurrent.futures.ThreadPoolExecutor
    entered = threading.Event()
    release = threading.Event()

    class FailingExecutor:
        def __init__(self, **kwargs):
            entered.set()
            if not release.wait(timeout=10):
                raise RuntimeError("executor gate did not open")
            raise RuntimeError("executor unavailable")

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", FailingExecutor)
    calls = [_start_call()]
    try:
        assert entered.wait(timeout=5)
        calls.extend(_start_call() for _ in range(3))
        assert joined_volume_waiters(3)
    finally:
        release.set()
        outcomes = _join_calls(calls)

    assert all(status == "error" and isinstance(value, RuntimeError)
               and str(value) == "executor unavailable"
               for status, value in outcomes)
    assert market_data._volume_cache == {}
    assert _volume_metrics() == {"miss": 1}

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", original_executor)
    info, expected = _full_volume_fixture()
    provider = _BlockedInfoProvider(info)
    provider.release.set()
    monkeypatch.setattr(market_data, "yf", provider)
    assert [row["symbol"] for row in market_data.get_volume_leaders()] == expected
    assert len(provider.calls) == 33


def test_volume_waiter_can_retry_before_failed_owner_finishes(monkeypatch):
    monkeypatch.setattr(market_data, "SECTOR_LEADERS", {"Technology": ["AAPL"]})
    provider_entered = threading.Event()
    provider_release = threading.Event()
    waiter_joined = threading.Event()
    failure_published = threading.Event()
    owner_release = threading.Event()
    lock = threading.Lock()
    provider_calls = []

    class PausedFuture(Future):
        def result(self, timeout=None):
            waiter_joined.set()
            return super().result(timeout=timeout)

        def set_exception(self, exception):
            super().set_exception(exception)
            failure_published.set()
            if not owner_release.wait(timeout=10):
                raise RuntimeError("owner gate did not open")

    class FakeTicker:
        def __init__(self, symbol):
            with lock:
                self.number = len(provider_calls)
                provider_calls.append(symbol)

        @property
        def info(self):
            if self.number == 0:
                provider_entered.set()
                if not provider_release.wait(timeout=10):
                    raise RuntimeError("provider gate did not open")
                raise RuntimeError("first provider call failed")
            return _make_info("Apple", 110, 100, 1000)

    monkeypatch.setattr(market_data, "Future", PausedFuture)
    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    calls = [_start_call()]
    try:
        assert provider_entered.wait(timeout=5)
        calls.append(_start_call())
        assert waiter_joined.wait(timeout=5)
        provider_release.set()
        assert failure_published.wait(timeout=5)
        waiter_outcome = _join_calls(calls[1:])[0]
        assert waiter_outcome[0] == "error"
        assert isinstance(waiter_outcome[1], ValueError)
        # The failed owner is still completing its Future. A new request
        # must start a retry rather than rejoin that completed failure.
        retry = market_data.get_volume_leaders()
    finally:
        provider_release.set()
        owner_release.set()
        outcomes = _join_calls(calls)

    assert outcomes[0][0] == "error"
    assert retry[0]["price"] == 110
    assert provider_calls == ["AAPL", "AAPL"]
    assert market_data.get_volume_leaders()[0]["price"] == 110


def test_empty_candidate_set_still_raises_and_can_retry(monkeypatch):
    monkeypatch.setattr(market_data, "SECTOR_LEADERS", {})
    with pytest.raises(ValueError, match="max_workers"):
        market_data.get_volume_leaders()
    assert market_data._volume_cache == {}

    monkeypatch.setattr(market_data, "SECTOR_LEADERS", {"Technology": ["AAPL"]})
    provider = _BlockedInfoProvider({"AAPL": _make_info("Apple", 10, 9, 100)})
    provider.release.set()
    monkeypatch.setattr(market_data, "yf", provider)
    assert market_data.get_volume_leaders()[0]["symbol"] == "AAPL"
    assert provider.calls == ["AAPL"]


@pytest.mark.parametrize("old_finishes_first", [True, False])
@pytest.mark.parametrize("old_fails", [False, True])
def test_clear_during_volume_scan_preserves_new_owner_and_cache(
        monkeypatch, joined_volume_waiters, old_finishes_first, old_fails):
    monkeypatch.setattr(market_data, "SECTOR_LEADERS", {"Technology": ["AAPL"]})
    gates = [threading.Event(), threading.Event()]
    entered = [threading.Event(), threading.Event()]
    lock = threading.Lock()
    provider_calls = []

    class FakeTicker:
        def __init__(self, symbol):
            with lock:
                self.number = len(provider_calls)
                provider_calls.append(symbol)

        @property
        def info(self):
            if self.number >= 2:
                raise RuntimeError("a third scan must not start")
            entered[self.number].set()
            if not gates[self.number].wait(timeout=10):
                raise RuntimeError("provider gate did not open")
            if self.number == 0 and old_fails:
                raise RuntimeError("old provider failed")
            price = 100 if self.number == 0 else 200
            return _make_info("Apple", price, 90, 1000)

    monkeypatch.setattr(market_data, "yf", SimpleNamespace(Ticker=FakeTicker))
    calls = [_start_call()]
    try:
        assert entered[0].wait(timeout=5)
        calls.append(_start_call())
        assert joined_volume_waiters(1)
        market_data.clear_market_caches()
        calls.append(_start_call())
        assert entered[1].wait(timeout=5)
        calls.append(_start_call())
        assert joined_volume_waiters(2)

        if old_finishes_first:
            gates[0].set()
            old_outcomes = _join_calls(calls[:2])
            assert market_data._volume_cache == {}
            calls.append(_start_call())
            assert joined_volume_waiters(3)
            gates[1].set()
            new_outcomes = _join_calls(calls[2:])
        else:
            gates[1].set()
            new_outcomes = _join_calls(calls[2:])
            assert market_data.get_volume_leaders()[0]["price"] == 200
            gates[0].set()
            old_outcomes = _join_calls(calls[:2])
    finally:
        for gate in gates:
            gate.set()
        _join_calls(calls)

    assert provider_calls == ["AAPL", "AAPL"]
    if old_fails:
        assert all(status == "error" and isinstance(value, ValueError)
                   for status, value in old_outcomes)
    else:
        assert all(status == "ok" and value[0]["price"] == 100
                   for status, value in old_outcomes)
    assert all(status == "ok" and value[0]["price"] == 200
               for status, value in new_outcomes)
    assert market_data.get_volume_leaders()[0]["price"] == 200
    assert provider_calls == ["AAPL", "AAPL"]


def test_blocked_volume_scan_does_not_hold_quote_lock(monkeypatch):
    info, _ = _full_volume_fixture()
    provider = _BlockedInfoProvider(info)
    monkeypatch.setattr(market_data, "yf", provider)
    calls = [_start_call()]
    quote_done = threading.Event()

    def quote():
        try:
            return market_data.get_quote("AAPL")
        finally:
            quote_done.set()

    try:
        assert provider.eight_entered.wait(timeout=5)
        calls.append(_start_call(quote))
        completed_before_release = quote_done.wait(timeout=5)
    finally:
        provider.release.set()
        outcomes = _join_calls(calls)

    assert completed_before_release
    assert outcomes[1][0] == "ok"
    assert outcomes[1][1]["price"] == 25.0
