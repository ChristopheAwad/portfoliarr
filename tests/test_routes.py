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
#     the #1 mocking mistake. The `fake_market` fixture + `make_quote`
#     helper that do this live in conftest.py, because test_stock.py needs
#     the exact same machinery.
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

import pytest

import db
import market_data
import pandas as pd
import re
from types import SimpleNamespace
from urllib.parse import quote

# NAME-COLLISION SUBTLETY (worth knowing!): app.py contains a Flask
# INSTANCE also named `app`. So `from app import app` hands us the Flask
# object, NOT the module — and the route functions look up get_quote in
# the MODULE's namespace. To patch the names the routes actually use, we
# import the module itself under a different alias. (The patching itself
# happens inside conftest.py's fake_market fixture.)
import app as app_module
from app import INDEX_SYMBOLS

from conftest import make_quote


# ── Helpers ───────────────────────────────────────────────────────────
# (make_quote and the fake_market fixture live in conftest.py now — shared
# with test_stock.py. seed_transaction below is routes-file-only.)

def seed_transaction(ticker="AAPL", date="2026-08-01", price=100.0,
                     qty=10, tx_type="BUY", currency="USD", fx_rate=None):
    """Insert a ledger row through the db layer (never raw SQL) and
    return its auto-numbered id. fx_rate defaults to None ("pre-feature
    row, rate unknown") so tests that don't care about conversion don't
    have to pretend a rate; conversion tests pass it explicitly."""
    return db.add_transaction(ticker, date, price, qty, currency, tx_type,
                              fx_rate)


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


# ── Dashboard page (the indices chips) ────────────────────────────────

def dashboard_chip_tags(html):
    """Pull each chip's opening tag out of the rendered dashboard HTML,
    keyed by its data-symbol — the same hook main.js fills live quotes
    by. (The chips are static template HTML, so this is a pure string
    check: no fixtures, no fakes, no network.)"""
    tags = re.findall(r'<a class="chip"[^>]*>', html)
    return {re.search(r'data-symbol="([^"]+)"', tag).group(1): tag
            for tag in tags}


def test_dashboard_chips_are_links_to_detail_pages(client):
    """Every managed chip is a real <a> to the detail page, carrying BOTH
    hooks: data-symbol (main.js fills the live quote by it) and href (the
    browser navigates by it). Expected hrefs derive from the app's own
    INDEX_SYMBOLS — one source of truth — with ^ percent-encoded exactly
    as Flask's url_for emits it (^GSPC → /stock/%5EGSPC; the route
    decodes it back). A future chip added without a link fails here,
    keeping the AGENTS.md 'two edits per chip' contract honest."""
    expected = {s: f"/stock/{quote(s, safe='')}" for s in INDEX_SYMBOLS}
    chips = dashboard_chip_tags(client.get("/").get_data(as_text=True))
    assert set(chips) == set(expected)   # exactly the managed chips
    for symbol, href in expected.items():
        assert f'href="{href}"' in chips[symbol]


def test_encoded_index_symbol_url_round_trips(client):
    """The chip hrefs ship ^ percent-encoded (raw ^ is illegal in a URL
    path) — Flask must decode %5E back so the detail page's identity hook
    stamps the raw symbol, exactly how the search dropdown's
    encodeURIComponent links have always worked."""
    res = client.get("/stock/%5EGSPC")
    assert res.status_code == 200
    assert 'data-symbol="^GSPC"' in res.get_data(as_text=True)


# ── Transactions: POST (log) ──────────────────────────────────────────

def test_log_transaction_201_echoes_db_vocabulary(client, fake_market):
    """POST takes BROWSER keys (date/type) and answers with DB keys
    (transaction_date/transaction_type) — the route is the translator.
    Currency comes from the quote, never from the user — and so does the
    fx_rate, derived from the transaction's DATE (the USDCAD close that
    day): a past-fact conversion rate, stored once and never recomputed."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    fake_market.fx_on[("USDCAD", "2026-08-31")] = 1.4123
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
    assert body["fx_rate"] == 1.4123
    assert isinstance(body["id"], int)
    # ...and the fact actually landed in the ledger.
    assert db.get_transactions()[0]["fx_rate"] == 1.4123


def test_log_cad_ticker_stores_fx_1_without_any_fx_call(client, fake_market):
    """A CAD security needs no exchange rate — the rate IS 1.0. Proved by
    the fx dicts staying empty: any FX fetch would raise KeyError and
    fail the test."""
    fake_market.quotes["RY.TO"] = make_quote("RY.TO", 51.0, 50.0,
                                             currency="CAD")
    res = client.post("/api/transactions", json={
        "ticker": "RY.TO", "date": "2026-08-31",
        "price": 51.0, "qty": 10, "type": "BUY",
    })
    assert res.status_code == 201
    assert db.get_transactions()[0]["fx_rate"] == 1.0
    assert fake_market.fx_rates == {} and fake_market.fx_on == {}


def test_log_usd_ticker_falls_back_to_live_rate_when_history_fails(
        client, fake_market):
    """The date's close couldn't be fetched (Yahoo gap) but the LIVE rate
    could: the row stores the live rate rather than nothing. A visible
    approximation — the log line is the audit trail."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    fake_market.fx_rates["USDCAD"] = 1.38   # live works; fx_on stays empty

    res = client.post("/api/transactions", json={
        "ticker": "AAPL", "date": "2026-08-31",
        "price": 229.5, "qty": 10, "type": "BUY",
    })
    assert res.status_code == 201
    assert db.get_transactions()[0]["fx_rate"] == 1.38


def test_log_usd_ticker_with_no_fx_at_all_stores_null(client, fake_market):
    """Neither the date's close nor the live rate answered: the ledger
    fact is still stored, with fx_rate NULL ("rate unknown") — display
    falls back to the live rate per request, and the row can be edited
    later to backfill the real fact. Never a 500 for a missing rate."""
    fake_market.quotes["AAPL"] = make_quote("AAPL", 229.5, 225.0)
    # both fx dicts deliberately empty

    res = client.post("/api/transactions", json={
        "ticker": "AAPL", "date": "2026-08-31",
        "price": 229.5, "qty": 10, "type": "BUY",
    })
    assert res.status_code == 201
    assert db.get_transactions()[0]["fx_rate"] is None


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
    ?currency=native pins the NATIVE display math (the CAD-conversion
    contract lives in test_currency_display.py) — and the empty fx dicts
    prove native mode never asks for a rate.
    """
    seed_transaction(fx_rate=1.40)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 150.0, 140.0)

    row = client.get("/api/transactions?currency=native").get_json()[0]
    assert fake_market.fx_rates == {} and fake_market.fx_on == {}
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


def test_edit_updates_four_fields_ignores_ticker_rederives_fx(
        client, fake_market):
    """THE edit boundary (AGENTS.md), evolved: a PUT may rewrite date/
    price/qty/type — and a 'ticker' in the body is IGNORED outright. The
    date-derived fx_rate is re-derived from the NEW date (a stale rate
    would be a wrong fact after a date correction); currency still never
    moves. The response is re-read from the DB, so it shows the truth on
    disk."""
    tx_id = seed_transaction(ticker="AAPL", currency="USD", fx_rate=1.40)
    fake_market.fx_on[("USDCAD", "2026-08-02")] = 1.3777
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
    assert body["fx_rate"] == 1.3777        # ...re-derived from the new date


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
    (Seeded CAD — the chart's display currency IS CAD, so a CAD holding
    needs no FX work; the empty fx dict proves none was fetched.)
    """
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-27", "2026-08-28", "2026-08-31"]
    assert body["values"] == [0.0, 1100.0, 1200.0]
    assert fake_market.fx_rates == {} and fake_market.fx_on == {}


def test_history_usd_holdings_convert_at_the_live_rate(client, fake_market):
    """The chart is ALWAYS CAD (the ledger toggle never touches it — it
    plots the portfolio total). A USD holding's whole line scales by the
    flat LIVE rate: history is context, not a sell price, so a per-point
    historical rate was deliberately skipped.
        08-28: 10 × 110 × 1.5 = 1650
        08-31: 10 × 120 × 1.5 = 1800
    """
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    fake_market.fx_rates["USDCAD"] = 1.5

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [0.0, 1650.0, 1800.0]


def test_history_mixed_currencies_sum_in_cad(client, fake_market):
    """One chart, two currencies, one CAD line: the USD ticker's points
    scale by the live rate, the CAD ticker passes through."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=1,
                     currency="USD", fx_rate=1.4)
    seed_transaction(ticker="RY.TO", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {"2026-08-28": 100.0, "2026-08-31": 110.0}
    fake_market.histories["RY.TO"] = {"2026-08-28": 50.0, "2026-08-31": 52.0}
    fake_market.fx_rates["USDCAD"] = 1.5

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [
        pytest.approx(1 * 100 * 1.5 + 10 * 50.0),   # 650.0
        pytest.approx(1 * 110 * 1.5 + 10 * 52.0),   # 685.0
    ]


def test_history_sell_reduces_value_and_unpriced_ticker_contributes_zero(
        client, fake_market):
    """Two rules in one chart:
        1. A SELL pulls the line DOWN from its date: 10 − 4 = 6 held.
        2. An unpriced ticker (no history available) contributes 0 —
           its holdings exist but are valued at zero, never a crash.
        08-28: 10×100 (AAPL) + 5×0 (BAD) = 1000
        08-31:  6×110 (AAPL) + 5×0 (BAD) =  660
    (Seeded CAD — the dead-ticker rule is orthogonal to currency.)
    """
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10, tx_type="BUY",
                     currency="CAD")
    seed_transaction(ticker="AAPL", date="2026-08-31", qty=4, tx_type="SELL",
                     currency="CAD")
    seed_transaction(ticker="BAD", date="2026-08-28", qty=5, tx_type="BUY",
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-28": 100.0, "2026-08-31": 110.0,
    }   # "BAD" deliberately absent → get_history raises → valued at 0

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    assert body["values"] == [1000.0, 660.0]


def test_history_fx_failure_makes_usd_holdings_contribute_zero(
        client, fake_market):
    """Same per-ticker resilience rule, new trigger: without a live USDCAD
    rate a USD holding has no honest CAD value, so its line contributes 0
    while the CAD holding carries the chart. Never a 500."""
    seed_transaction(ticker="AAPL", date="2026-08-28", qty=10,
                     currency="USD", fx_rate=1.4)
    seed_transaction(ticker="RY.TO", date="2026-08-28", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {"2026-08-28": 100.0}
    fake_market.histories["RY.TO"] = {"2026-08-28": 50.0}
    # fx_rates deliberately empty → no live rate → AAPL contributes 0

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["values"] == [500.0]   # RY.TO only


def test_history_nan_close_carries_forward_and_stays_strict_json(
        client, monkeypatch):
    """END-TO-END regression for the blank-chart outage (Sep 2026), the
    dashboard's chart: one held ticker's current-day bar shipping
    Close = NaN (Yahoo's in-progress bar) used to poison that day's total
    — the bare `NaN` token made the WHOLE payload invalid JSON, the
    browser's response.json() threw, and the portfolio chart never
    painted even though every other ticker was healthy. The NaN bar is
    now dropped at the data layer, and the missing-bar rule below prices
    the still-held position at its LAST KNOWN close instead of 0 — no
    end-of-chart cliff while Yahoo hasn't printed a fresh close yet.

    Deliberately NOT fake_market: its dict-lookup fake REPLACES
    app.get_history and would bypass the data layer where the fix lives.
    market_data.yf is patched instead (where market_data uses it), so the
    REAL get_history runs and the route sees exactly what production
    would: clean closes only. Both tickers are seeded CAD, so no FX call
    is involved."""
    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, period=None, interval="1d"):
            return {
                "META": pd.DataFrame(
                    {"Close": [100.0, float("nan")]},
                    index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
                ),
                "FETH.TO": pd.DataFrame(
                    {"Close": [50.0, 46.0]},
                    index=pd.to_datetime(["2026-08-28", "2026-08-31"]),
                ),
            }[self.symbol]

    monkeypatch.setattr(market_data, "yf",
                        SimpleNamespace(Ticker=FakeTicker))
    seed_transaction(ticker="META", date="2026-08-28", qty=10,
                     currency="CAD")
    seed_transaction(ticker="FETH.TO", date="2026-08-28", qty=5,
                     currency="CAD")

    res = client.get("/api/portfolio/history?period=5D")
    assert res.status_code == 200
    assert b"NaN" not in res.data       # strict-JSON clean on the wire
    body = res.get_json()
    assert body["labels"] == ["2026-08-28", "2026-08-31"]
    # 08-28: 10×100 (META) + 5×50 (FETH.TO) = 1250.  08-31: META printed
    # no bar (its NaN one was dropped at the data layer) → carried at
    # 100.0, the last known close → 10×100 + 5×46 = 1230. Forward-fill
    # keeps the line honest: a holding doesn't evaporate just because
    # Yahoo hasn't finalized a fresh close yet.
    assert body["values"] == [1250.0, 1230.0]


def test_history_missing_bar_carries_last_known_close(client, fake_market):
    """The forward-fill rule, mid-series: a day where a held ticker
    printed no bar (a holiday on ITS market, an unfinalized current-day
    bar...) prices the position at its LAST KNOWN close — never at 0,
    which painted a cliff implying the holding lost its whole value.
    AAPL prints on every label; RY.TO skips the middle one and is carried
    at 50.0 across the gap until its next close. (The old 0-fill would
    have dipped 08-28 to 1×110 + 10×0 = 510. A ticker with NO bars at all
    — nothing to carry — still contributes 0, locked by the dead-ticker
    test above.)"""
    seed_transaction(ticker="AAPL", date="2026-08-27", qty=1,
                     currency="CAD")
    seed_transaction(ticker="RY.TO", date="2026-08-27", qty=10,
                     currency="CAD")
    fake_market.histories["AAPL"] = {
        "2026-08-27": 100.0, "2026-08-28": 110.0, "2026-08-31": 120.0,
    }
    fake_market.histories["RY.TO"] = {
        "2026-08-27": 50.0, "2026-08-31": 52.0,   # 08-28 deliberately absent
    }

    body = client.get("/api/portfolio/history?period=5D").get_json()
    assert body["labels"] == ["2026-08-27", "2026-08-28", "2026-08-31"]
    # 08-27: 1×100 + 10×50 = 600.  08-28: 1×110 + 10×50 carried = 610.
    # 08-31: 1×120 + 10×52 = 640.
    assert body["values"] == [600.0, 610.0, 640.0]
