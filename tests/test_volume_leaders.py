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
#   - all sectors fail: returns empty list
#   - API route returns correct structure and never 500

from types import SimpleNamespace

import pytest

import market_data
import app as app_module


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

@pytest.fixture(autouse=True)
def clean_volume_cache():
    """Empty the volume cache before EVERY test."""
    market_data._volume_cache.clear()
    yield


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
    volume ticker appears first in the candidates list."""
    # Technology sector: NVDA (500M) beats AAPL (100M)
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
        "MSFT": _make_info("Microsoft", 420.0, 415.0, 30_000_000),
    })
    leaders = market_data.get_volume_leaders()

    # Only Technology is defined in SECTOR_LEADERS with these tickers,
    # so we should get exactly 1 leader from that sector.
    symbols = [l["symbol"] for l in leaders]
    assert "NVDA" in symbols
    assert "AAPL" not in symbols  # lower volume in same sector


def test_sorted_by_volume_descending(fake_yf_for_volume):
    """The final list is sorted by volume, highest first."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
        "NVDA": _make_info("NVIDIA", 120.0, 118.0, 500_000_000),
        "MSFT": _make_info("Microsoft", 420.0, 415.0, 300_000_000),
    })
    leaders = market_data.get_volume_leaders()
    volumes = [l["volume"] for l in leaders]
    assert volumes == sorted(volumes, reverse=True)


def test_capped_at_ten(fake_yf_for_volume):
    """At most 10 leaders returned, even if more sectors resolve."""
    # Fill ALL sector leaders with valid data to get more than 10 sectors
    # The SECTOR_LEADERS dict has ~11 sectors, so we fill them all
    for sector_tickers in market_data.SECTOR_LEADERS.values():
        for sym in sector_tickers:
            fake_yf_for_volume.info_data[sym] = _make_info(
                sym, 100.0, 99.0, 50_000_000
            )
    leaders = market_data.get_volume_leaders()
    assert len(leaders) <= 10


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
    """Volume data changes slowly — second call must NOT re-fetch."""
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
    })
    first = market_data.get_volume_leaders()
    second = market_data.get_volume_leaders()
    assert first is second  # same object = served from cache


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
    """If one sector's tickers all fail, other sectors still appear."""
    # Only provide AAPL (Technology) — other sectors will fail
    fake_yf_for_volume.info_data.update({
        "AAPL": _make_info("Apple", 190.0, 188.0, 100_000_000),
    })
    leaders = market_data.get_volume_leaders()
    # Should still get Technology's leader
    assert any(l["symbol"] == "AAPL" for l in leaders)


def test_all_sectors_fail_returns_empty_list(fake_yf_for_volume):
    """When every ticker fails, return empty — no crash, no 500."""
    # info_data is empty → all tickers raise ValueError
    leaders = market_data.get_volume_leaders()
    assert leaders == []


def test_missing_volume_field_skips_ticker(fake_yf_for_volume):
    """A ticker with no volume data is skipped (not a crash)."""
    fake_yf_for_volume.info_data.update({
        "AAPL": {
            "shortName": "Apple",
            "regularMarketPrice": 190.0,
            "regularMarketPreviousClose": 188.0,
            # volume key missing
        },
    })
    leaders = market_data.get_volume_leaders()
    # AAPL should be skipped, no leaders returned
    assert leaders == []


# ── Route tests ────────────────────────────────────────────────────────

def test_volume_leaders_route_returns_200(client, fake_market):
    """The API endpoint returns 200 with a leaders list."""
    # Patch get_volume_leaders on the module where it's used (app.py)
    monkeypatch = pytest.MonkeyPatch()
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
    try:
        res = client.get("/api/market/volume-leaders")
        assert res.status_code == 200
        body = res.get_json()
        assert "leaders" in body
        assert len(body["leaders"]) == 1
        assert body["leaders"][0]["symbol"] == "AAPL"
    finally:
        monkeypatch.undo()


def test_volume_leaders_route_empty_list(client, fake_market):
    """Even an empty leaders list returns 200 (graceful degradation)."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_module, "get_volume_leaders", lambda: [])
    try:
        res = client.get("/api/market/volume-leaders")
        assert res.status_code == 200
        assert res.get_json()["leaders"] == []
    finally:
        monkeypatch.undo()


def test_volume_leaders_route_exception_returns_200(client, fake_market):
    """If get_volume_leaders raises, the route catches and returns 200
    with empty leaders — never a 500."""
    def _raise():
        raise ConnectionError("yahoo down")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(app_module, "get_volume_leaders", _raise)
    try:
        res = client.get("/api/market/volume-leaders")
        assert res.status_code == 200
        assert res.get_json()["leaders"] == []
    finally:
        monkeypatch.undo()
