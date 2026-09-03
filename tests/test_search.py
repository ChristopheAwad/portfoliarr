# tests/test_search.py
# ====================
# Route tests for GET /api/search — the navbar's suggestion endpoint.
#
# Same machinery as test_routes.py (test client, conftest's fixtures),
# with one new twist: the endpoint's dependency is `search_tickers`,
# which app.py imported from market_data — so per the golden mocking
# rule ("patch where it's USED") we patch app.search_tickers, NOT
# market_data.search_tickers.
#
# WHAT'S WORTH TESTING — the endpoint's own contract:
#   - 400 BEFORE any network work when q is missing or blank
#   - 200 passthrough: the query travels intact, results come back as-is
#   - empty results are a normal 200 (the dropdown shows "No matches")
#   - a dead Yahoo search is 503 ("it's me, not you") — search is an
#     entry point, so its failure degrades the dropdown, never the page

import pytest

import app as app_module


@pytest.fixture
def fake_search(monkeypatch):
    """Swap app.search_tickers for a controllable fake.

    state["results"]  — what the fake returns (tests set this)
    state["error"]    — when set, the fake raises it (Yahoo outage)
    state["queried"]  — the (query, limit) the route actually passed,
                        proving the request reached the data layer intact
    """
    state = {"results": [], "error": None, "queried": None}

    def fake_search_tickers(query, limit=8):
        if state["error"] is not None:
            raise state["error"]
        state["queried"] = (query, limit)
        return state["results"]

    monkeypatch.setattr(app_module, "search_tickers", fake_search_tickers)
    return state


# ── Input validation ──────────────────────────────────────────────────

def test_missing_query_returns_400_before_any_work(client, fake_search):
    """No ?q= at all → 400, and the fake was never called — validation
    happens BEFORE the (potentially slow) Yahoo round-trip."""
    res = client.get("/api/search")
    assert res.status_code == 400
    assert "q" in res.get_json()["error"]
    assert fake_search["queried"] is None


def test_blank_query_returns_400(client, fake_search):
    """Whitespace-only is as good as missing — strip() normalizes it to
    empty, same 400."""
    res = client.get("/api/search?q=%20%20%20")
    assert res.status_code == 400
    assert fake_search["queried"] is None


# ── Success paths ─────────────────────────────────────────────────────

def test_search_returns_results_passthrough(client, fake_search):
    """The route adds nothing and filters nothing — the data layer's
    normalized hits go straight to the browser (200)."""
    fake_search["results"] = [
        {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ",
         "type": "Equity"},
    ]
    res = client.get("/api/search?q=apple")
    assert res.status_code == 200
    assert res.get_json() == {"results": fake_search["results"]}
    assert fake_search["queried"] == ("apple", 8)  # query + default limit


def test_search_empty_results_are_a_normal_200(client, fake_search):
    """Gibberish finding nothing is not an error — an empty list the
    dropdown renders as 'No matches'."""
    res = client.get("/api/search?q=zzzznope")
    assert res.status_code == 200
    assert res.get_json() == {"results": []}


# ── Failure path ──────────────────────────────────────────────────────

def test_search_failure_returns_503(client, fake_search):
    """A raised exception (any yfinance failure) becomes 503 Service
    Unavailable — the same all-failed convention as the indices bar."""
    fake_search["error"] = ConnectionError("yahoo down")
    res = client.get("/api/search?q=apple")
    assert res.status_code == 503
    assert "unavailable" in res.get_json()["error"]
