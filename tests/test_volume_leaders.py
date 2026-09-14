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
    """Even an empty leaders list returns 200 (graceful degradation) —
    e.g. the data layer answered but every row lacked a usable price."""
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
