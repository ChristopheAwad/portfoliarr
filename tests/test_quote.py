# tests/test_quote.py
# ====================
# Route tests for GET /api/quote/<symbol> — the lightweight quote endpoint
# the ledger's Ticker field calls to prefill the Price input when a symbol
# is picked.
#
# WHY a separate endpoint from GET /api/stock/<symbol>: that route also
# fetches the display NAME via get_name (the heavy `Ticker.info` call). The
# form only needs the number, so the ledger's prefill must not pay the
# name's cost — this route is the fast_info-only slice of the same quote.
#
# Same contract as the other single-symbol endpoints: case-normalized, and
# an unquotable symbol is a plain 404 (there is no graceful middle ground
# when ONE symbol IS the whole answer). Shares conftest.py's fake_market.

import pytest
from conftest import make_quote


# ── The happy path ────────────────────────────────────────────────────

def test_quote_returns_price_payload(client, fake_market):
    """A quotable symbol returns exactly the get_quote dict — price,
    previous_close, currency, and the derived day-move numbers — and NO
    name key: the prefill form needs the number, not the company profile."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)

    body = client.get("/api/quote/AAPL").get_json()
    assert body["symbol"] == "AAPL"
    assert body["price"] == 229.5
    assert body["previous_close"] == 225.0
    assert body["currency"] == "USD"
    assert body["change"] == pytest.approx(4.5)
    assert body["change_pct"] == pytest.approx(2.0)
    assert "name" not in body, (
        "/api/quote must not carry the heavy name fetch's result — that is "
        "/api/stock/<symbol>'s job"
    )


def test_quote_normalizes_case(client, fake_market):
    """Lowercase URL → canonical lookup, the same rule as every symbol route
    ('aapl' and 'AAPL' must hit the same cache slot)."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    assert client.get("/api/quote/aapl").status_code == 200


def test_quote_does_not_touch_name(client, fake_market):
    """The route must never call get_name — proving it with the fakes: the
    fake's get_name raises KeyError for every symbol (names dict empty), so
    a 200 here means the request never reached the name path. A live
    endpoint that DID call get_name would degrade to 500 instead."""
    fake_market.quotes["MSFT"] = make_quote("MSFT", 500.0, 495.0)
    # names dict deliberately empty → app.get_name raises KeyError
    assert client.get("/api/quote/MSFT").status_code == 200


# ── The failure path ───────────────────────────────────────────────────

def test_quote_unquotable_symbol_returns_404(client, fake_market):
    """An absent symbol is a 404, exactly like the watchlist-add and
    transaction-log routes: the prefill silently leaves the price empty,
    and the user types it (the backend re-validates at submit anyway)."""
    assert client.get("/api/quote/NOPE").status_code == 404
