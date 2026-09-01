# tests/test_routes.py
# =====================
# Route tests for app.py — HTTP behaviour without a browser or a server.
#
# THE CONCEPTS THIS FILE COMBINES:
#   - The Flask TEST CLIENT (fixture in conftest.py): client.get/post/put/
#     delete(...) run the REAL routes through real Flask machinery and hand
#     back real Response objects (.status_code, .get_json()) — no network.
#   - MOCKING (learned in test_market_data.py), applied with the golden
#     rule "patch where it's USED": app.py did `from market_data import
#     get_quote`, so the name routes actually look up is app.get_quote.
#     Patching market_data.get_quote instead would silently do nothing —
#     the #1 mocking mistake.
#   - The throwaway DB (fresh_db, via client): every route that writes
#     goes to a temp SQLite file, never instance/portfolio.db.
#
# WHAT'S WORTH TESTING AT THIS LAYER?
#   Not that Flask routes work (Flask's own tests cover that) — the
#   CONTRACTS we designed:
#   - status codes: 201 created, 204 silent success, 409 duplicate,
#     404 unknown, 400 bad input, 503 only when EVERY quote fails
#   - normalization: "aapl" in, "AAPL" stored and echoed
#   - the edit boundary: a "ticker" in a PUT body is IGNORED
#   - the facts-only rule: /api/transactions decorates rows with live
#     math per request; an unquotable ticker stays facts-only
#   - graceful degradation: one dead symbol never sinks the whole answer

from types import SimpleNamespace

import pytest

import db

# NAME-COLLISION SUBTLETY (worth knowing!): app.py contains a Flask
# INSTANCE also named `app`. So `from app import app` hands us the Flask
# object, NOT the module — and the route functions look up get_quote in
# the MODULE's namespace. To patch the names the routes actually use, we
# import the module itself under a different alias.
import app as app_module
from app import INDEX_SYMBOLS


# ── Helpers & fixtures ────────────────────────────────────────────────

def make_quote(symbol, price, previous_close, currency="USD"):
    """Build a quote dict in exactly the shape market_data.get_quote
    returns (raw floats + derived day-move numbers)."""
    return {
        "symbol": symbol,
        "price": price,
        "previous_close": previous_close,
        "currency": currency,
        "change": price - previous_close,
        "change_pct": (price - previous_close) / previous_close * 100,
    }


@pytest.fixture
def fake_market(monkeypatch):
    """Swap the three market-data names AS APP.PY USES THEM.

    Patching app.get_quote (not market_data.get_quote!) — see the banner.
    The patch is a dict lookup, so "unknown symbol" is simulated by the
    key simply being ABSENT: quotes["NOPE"] raises KeyError, every route
    catches it, and the resilience paths get exercised exactly as they
    would with a real Yahoo outage.
    """
    quotes, names, histories = {}, {}, {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_name", lambda symbol: names[symbol])
    monkeypatch.setattr(app_module, "get_history",
                        lambda symbol, period: histories[symbol])
    return SimpleNamespace(quotes=quotes, names=names, histories=histories)


def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD"):
    """Insert a ledger row through the db layer (never raw SQL) and
    return its auto-numbered id."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type)


# ── Watchlist ─────────────────────────────────────────────────────────

def test_add_to_watchlist_201_stores_normalized(client, fake_market):
    """Happy path: lowercase input → stored AND echoed as uppercase.
    The 201 body uses {"symbol": ...}; the truth is checked in the DB."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    res = client.post("/api/watchlist", json={"symbol": "aapl"})
    assert res.status_code == 201
    assert res.get_json() == {"symbol": "AAPL"}
    assert db.get_symbols() == ["AAPL"]


def test_add_duplicate_returns_409(client, fake_market):
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    assert client.post("/api/watchlist", json={"symbol": "AAPL"}).status_code == 201
    res = client.post("/api/watchlist", json={"symbol": "AAPL"})
    assert res.status_code == 409
    assert "already" in res.get_json()["error"]


def test_add_unknown_symbol_returns_404(client, fake_market):
    """No fake quote for TSLA → get_quote raises KeyError → 404 — and
    crucially, nothing was stored."""
    res = client.post("/api/watchlist", json={"symbol": "TSLA"})
    assert res.status_code == 404
    assert db.get_symbols() == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {},                                       # no JSON body at all
        {"json": ["AAPL"]},                       # JSON, but not a dict
        {"json": {"symbol": "   "}},              # whitespace-only symbol
    ],
    ids=["no body", "non-dict body", "blank symbol"],
)
def test_add_rejects_bad_bodies_with_400(client, kwargs):
    """Body-shape errors are caught BEFORE any Yahoo/DB work — all 400."""
    res = client.post("/api/watchlist", **kwargs)
    assert res.status_code == 400


def test_watchlist_quotes_skip_failed_symbols(client, fake_market):
    """The symbols/quotes split: the DB list is the source of truth for
    WHICH rows exist; a failed quote just doesn't appear in quotes (the
    frontend gap-fills that row with "—")."""
    db.add_symbol("AAPL")
    db.add_symbol("BAD")
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    fake_market.names["AAPL"] = "Apple Inc"

    res = client.get("/api/watchlist")
    body = res.get_json()
    assert body["symbols"] == ["AAPL", "BAD"]   # both rows exist
    assert len(body["quotes"]) == 1             # only one is quotable
    assert body["quotes"][0]["name"] == "Apple Inc"


def test_watchlist_name_failure_degrades_to_none(client, fake_market):
    """A missing company name must NOT sink the row — name becomes None
    and the frontend falls back to showing the bare symbol."""
    db.add_symbol("MSFT")
    fake_market.quotes["MSFT"] = make_quote("MSFT", 500.0, 495.0)
    # names dict deliberately empty → get_name raises KeyError → name None

    res = client.get("/api/watchlist")
    assert res.get_json()["quotes"][0]["name"] is None


def test_watchlist_delete_204_then_404(client, fake_market):
    """DELETE is idempotent-honest: first remove = 204 No Content (and
    the URL's lowercase 'aapl' is normalized to match storage), repeat =
    404 because it's already gone."""
    db.add_symbol("AAPL")
    res = client.delete("/api/watchlist/aapl")
    assert res.status_code == 204
    assert res.data == b""                      # 204 means "nothing to say"
    assert client.delete("/api/watchlist/aapl").status_code == 404


# ── Indices bar ───────────────────────────────────────────────────────

def test_indices_partial_failure_returns_successes_only(client, fake_market):
    """Per-symbol resilience: two dead symbols must NOT blank the bar —
    the live two come back, the dead two are simply ABSENT (the frontend
    infers which chips show "—")."""
    for symbol in INDEX_SYMBOLS[:2]:
        fake_market.quotes[symbol] = make_quote(symbol, 100.0, 95.0)

    res = client.get("/api/indices")
    quotes = res.get_json()
    assert res.status_code == 200
    assert [q["symbol"] for q in quotes] == INDEX_SYMBOLS[:2]


def test_indices_all_fail_returns_503(client, fake_market):
    """ONLY when every symbol fails is the endpoint considered sick:
    503 = 'it's me, not you, try again later'."""
    res = client.get("/api/indices")
    assert res.status_code == 503


def test_indices_all_succeed_returns_full_list(client, fake_market):
    for symbol in INDEX_SYMBOLS:
        fake_market.quotes[symbol] = make_quote(symbol, 100.0, 95.0)
    res = client.get("/api/indices")
    assert res.status_code == 200
    assert len(res.get_json()) == len(INDEX_SYMBOLS)


# ── Transactions: POST (log) ──────────────────────────────────────────

def test_log_transaction_201_echoes_db_vocabulary(client, fake_market):
    """POST takes BROWSER keys (date/type) and answers with DB keys
    (transaction_date/transaction_type) — the route is the translator.
    Currency comes from the quote, never from the user."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    res = client.post("/api/transactions", json={
        "ticker": "aapl", "date": "2026-08-31",
        "price": 229.5, "qty": 10, "type": "buy",
    })
    body = res.get_json()
    assert res.status_code == 201
    assert body["ticker"] == "AAPL"
    assert body["transaction_date"] == "2026-08-31"
    assert body["transaction_type"] == "BUY"
    assert body["currency"] == "USD"
    assert isinstance(body["id"], int)
    # ...and the fact actually landed in the ledger.
    assert len(db.get_transactions()) == 1


def test_log_unknown_ticker_returns_404(client, fake_market):
    """No quote → the ticker isn't proven real → 404, nothing stored.
    (Currency comes FROM the quote, so no quote = no row is by design.)"""
    res = client.post("/api/transactions", json={
        "ticker": "NOPE", "date": "2026-08-31",
        "price": 10.0, "qty": 1, "type": "BUY",
    })
    assert res.status_code == 404
    assert db.get_transactions() == []


def test_log_inherits_shared_validator_rules(client, fake_market):
    """qty 0 must be rejected by POST too — proof that POST really uses
    the same validate_tx_fields as PUT (one set of rules, no drift)."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    res = client.post("/api/transactions", json={
        "ticker": "AAPL", "date": "2026-08-31",
        "price": 229.5, "qty": 0, "type": "BUY",
    })
    assert res.status_code == 400


def test_log_malformed_body_returns_400(client):
    res = client.post("/api/transactions")   # no JSON body
    assert res.status_code == 400


# ── Transactions: GET (ledger + live math) ────────────────────────────

def test_list_decorates_rows_with_live_math(client, fake_market):
    """THE facts-only rule in action: stored facts + numbers computed
    FRESH per request from the live quote. Bought 10 @ 100 on 08-01;
    now 150 (prev close 140):
        value        = 150 × 10            = 1500
        total_gain   = (150 − 100) × 10    = 500
        total_gain_% = 50 / 100 × 100      = 50
        day_gain     = (150 − 140) × 10    = 100
        day_gain_%   = 10 / 140 × 100      = 7.1428...
    """
    seed_transaction()
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 140.0)

    row = client.get("/api/transactions").get_json()[0]
    assert row["price"] == 100.0            # the stored fact, untouched
    assert row["price_now"] == 150.0
    assert row["value"] == pytest.approx(1500.0)
    assert row["total_gain"] == pytest.approx(500.0)
    assert row["total_gain_pct"] == pytest.approx(50.0)
    assert row["day_gain"] == pytest.approx(100.0)
    assert row["day_gain_pct"] == pytest.approx(10 / 140 * 100)


def test_list_unquotable_ticker_stays_facts_only(client, fake_market):
    """A dead ticker must not sink the response — its rows simply lack
    the live decoration (no price_now key) and the frontend gap-fills."""
    seed_transaction(ticker="BAD")
    row = client.get("/api/transactions").get_json()[0]
    assert row["ticker"] == "BAD"
    assert "price_now" not in row
    assert row["price"] == 100.0            # facts still intact


# ── Transactions: PUT (edit) ──────────────────────────────────────────

def test_edit_404_comes_before_validation(client):
    """Wrong id + garbage body → 404, NOT 400. The route checks existence
    FIRST because 'no such row' is the more useful answer."""
    res = client.put("/api/transactions/999", json={"date": "garbage"})
    assert res.status_code == 404


def test_edit_updates_four_fields_and_ignores_ticker(client, fake_market):
    """THE edit boundary (AGENTS.md): a PUT may rewrite date/price/qty/
    type — and a 'ticker' in the body is IGNORED outright. The response is
    re-read from the DB, so it shows the truth on disk, including the
    untouched ticker/currency."""
    tx_id = seed_transaction(ticker="AAPL", currency="USD")
    res = client.put(f"/api/transactions/{tx_id}", json={
        "date": "2026-08-02", "price": 110.0, "qty": 7,
        "type": "sell",
        "ticker": "MSFT",                   # smuggled in — must be ignored
    })
    body = res.get_json()
    assert res.status_code == 200
    assert body["transaction_date"] == "2026-08-02"
    assert body["price"] == 110.0
    assert body["qty"] == 7
    assert body["transaction_type"] == "SELL"
    assert body["ticker"] == "AAPL"         # identity survives
    assert body["currency"] == "USD"        # yfinance fact survives


# ── Transactions: DELETE ──────────────────────────────────────────────

def test_delete_204_then_404(client):
    tx_id = seed_transaction()
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 204
    assert client.delete(f"/api/transactions/{tx_id}").status_code == 404


def test_delete_unknown_id_returns_404(client):
    assert client.delete("/api/transactions/999").status_code == 404


# ── Portfolio history chart ───────────────────────────────────────────

def test_history_rejects_unknown_period(client, fake_market):
    """A bad timeframe key is caught BEFORE any fetch, with the valid
    options listed (both come from PERIOD_MAP — one source of truth)."""
    res = client.get("/api/portfolio/history?period=NOPE")
    assert res.status_code == 400
    assert "5D" in res.get_json()["error"]
    assert "MAX" in res.get_json()["error"]


def test_history_empty_ledger_is_not_an_error(client, fake_market):
    """An empty ledger is a normal state: empty chart data, 200."""
    res = client.get("/api/portfolio/history")
    assert res.status_code == 200
    assert res.get_json() == {"labels": [], "values": []}


def test_history_buy_applies_from_its_date_onward(client, fake_market):
    """The chart's heart: before the buy the line is 0; from the buy's
    date on, the line is qty × that day's close.
        08-27: nothing held            → 0
        08-28: buy 10 AAPL @ close 110 → 1100
        08-31: still 10 @ close 120    → 1200
    """
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10)
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-27", "2026-08-28", "2026-08-31"]
    assert body["values"] == [0.0, 1100.0, 1200.0]


def test_history_sell_reduces_value_and_unpriced_ticker_contributes_zero(
        client, fake_market):
    """Two rules in one chart:
        1. A SELL pulls the line DOWN from its date: 10 − 4 = 6 held.
        2. An unpriced ticker (no history available) contributes 0 —
           its holdings exist but are valued at zero, never a crash.
        08-28: 10×100 (AAPL) + 5×0 (BAD) = 1000
        08-31:  6×110 (AAPL) + 5×0 (BAD) =  660
    """
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10, tx_type="BUY")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=4, tx_type="SELL")
    seed_transaction(ticker="BAD", date="2026-08-28", qty=5, tx_type="BUY")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }   # "BAD" deliberately absent → get_history raises → valued at 0

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 660.0]
