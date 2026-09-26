# tests/test_multiuser_scoping.py
# =================================
# The ownership wall: two signed-in people on one server must be unable
# to reach each other's portfolios, transactions, or watchlist. Every
# portfolio-identifying route answers 404 for a foreign ID (no fallback,
# no info leak); omitted IDs resolve WITHIN the caller's own portfolios.
#
# Identity here: `client` = tester (user id 1, Main = portfolio 1); the
# helper forge session makes user id 2 ("bert", Main = portfolio 2) a
# second browser. The portfolio-resolution hook rejects foreign ids
# BEFORE any route body runs, so most tests need no fake market.

from app import app
import db
from conftest import make_quote, seed_user


def second_browser(username="bert"):
    """Another person's browser, signed in as their own account."""
    web_client = app.test_client()
    uid = seed_user(username)
    with web_client.session_transaction() as session:
        session["user_id"] = uid
    return web_client, uid


# (method, url, json-body-or-None) — portfolio 2 is bert's Main, foreign
# to tester. PUT/DELETE need the transaction row id 1 to exist (seeded
# below); PATCH/DELETE portfolios need bert's portfolio to exist.
FOREIGN_ROUTES = [
    ("get", "/api/portfolio/summary?portfolio_id=2", None),
    ("get", "/api/portfolio/history?portfolio_id=2", None),
    ("get", "/api/portfolio/allocation?portfolio_id=2", None),
    ("get", "/api/portfolio/realized?portfolio_id=2", None),
    ("get", "/api/transactions?portfolio_id=2", None),
    ("post", "/api/transactions?portfolio_id=2",
     {"ticker": "AAPL", "date": "2026-01-01", "price": 1, "qty": 1,
      "type": "BUY"}),
    ("put", "/api/transactions/1?portfolio_id=2",
     {"date": "2026-01-02", "price": 11, "qty": 2, "type": "SELL"}),
    ("delete", "/api/transactions/1?portfolio_id=2", None),
    ("delete", "/api/transactions/ticker/AAPL?portfolio_id=2", None),
    ("post", "/api/transactions/import/preview?portfolio_id=2",
     {"text": "AAPL\t16 Mar 2026\t10\t1"}),
    ("post", "/api/transactions/import/commit?portfolio_id=2",
     {"text": "AAPL\t16 Mar 2026\t10\t1"}),
    ("patch", "/api/portfolios/2", {"name": "Renamed"}),
    ("delete", "/api/portfolios/2", {"name": "Main"}),
    ("patch", "/api/portfolios/2/move", {"direction": "up"}),
]


def test_every_portfolio_scoped_route_404s_on_a_foreign_id(client):
    # bert (user 2, whose Main is portfolio 2) must EXIST first: the
    # seeded transaction needs an owner to reference (FK).
    seed_user("bert")
    db.add_transaction("AAPL", "2026-01-01", 10, 2, "CAD", "BUY", 1,
                       portfolio_id=2)

    before_b_name = db.get_portfolio(2, 2)["name"]
    for method, url, body in FOREIGN_ROUTES:
        if body is None:
            response = getattr(client, method)(url)
        else:
            response = getattr(client, method)(url, json=body)
        assert response.status_code == 404, url
        assert response.get_json()["error"] == "portfolio not found", url

    # Bert's facts are untouched: the row survived, and the name/membership
    # were not rewritten ("portfolio not found" never means "deleted").
    assert db.get_transaction(1, 2)["ticker"] == "AAPL"
    assert db.get_portfolio(2, 2)["name"] == before_b_name == "Main"
    assert len(db.get_transactions(2)) == 1


def test_omitted_portfolio_id_resolves_within_the_caller(client, fake_market):
    """The 'older API clients' contract survives multi-user: no id means
    the CALLER's first portfolio — never another user's, even one with
    the lower id (bert is created first here)."""
    bert, bert_id = second_browser()
    first_bert = db.get_portfolios(bert_id)[0]["id"]      # alive, id 2
    assert first_bert == 2

    db.add_transaction("AAPL", "2026-01-01", 10, 2, "CAD", "BUY", 1,
                       portfolio_id=1)
    bert_tx = db.add_transaction("MSFT", "2026-01-01", 5, 1, "CAD", "BUY",
                                 1, portfolio_id=2)
    assert [tx["ticker"] for tx in client.get("/api/transactions").json] == [
        "AAPL"]
    assert [tx["ticker"] for tx in bert.get("/api/transactions").json] == [
        "MSFT"]

    # Writes without an id also land in the caller's own portfolio:
    fake_market.quotes["TSLA"] = make_quote("TSLA", 100, 90)
    created = client.post("/api/transactions", json={
        "ticker": "TSLA", "date": "2026-01-02", "price": 100, "qty": 1,
        "type": "BUY"})
    row = db.get_transaction(created.json["id"], 1)
    assert row["portfolio_id"] == 1
    assert db.get_transaction(created.json["id"], 2) is None
    assert [tx["id"] for tx in bert.get("/api/transactions").json] == [
        bert_tx]


def test_watchlist_is_per_user(client, fake_market):
    bert, __ = None, None
    bert_browser = app.test_client()
    bert_id = seed_user("bert")
    with bert_browser.session_transaction() as session:
        session["user_id"] = bert_id

    fake_market.quotes["AAPL"] = make_quote("AAPL", 10, 9)
    fake_market.names["AAPL"] = "Apple"
    fake_market.quotes["MSFT"] = make_quote("MSFT", 20, 19)
    fake_market.names["MSFT"] = "Microsoft"

    assert client.post("/api/watchlist",
                       json={"symbol": "AAPL"}).status_code == 201
    # Same symbol from the other person: allowed (ownership is per user).
    assert bert_browser.post("/api/watchlist",
                             json={"symbol": "AAPL"}).status_code == 201
    assert bert_browser.post("/api/watchlist",
                             json={"symbol": "MSFT"}).status_code == 201

    assert client.get("/api/watchlist").get_json()["symbols"] == ["AAPL"]
    assert bert_browser.get(
        "/api/watchlist").get_json()["symbols"] == ["AAPL", "MSFT"]

    # Deleting a shared symbol removes ONE person's row only:
    assert bert_browser.delete("/api/watchlist/AAPL").status_code == 204
    assert client.get("/api/watchlist").get_json()["symbols"] == ["AAPL"]
    # Removing a symbol only the OTHER person watches is a 404, and A
    # keeps it:
    assert client.delete("/api/watchlist/MSFT").status_code == 404
    assert client.get("/api/watchlist").get_json()["symbols"] == ["AAPL"]
    # Bert deleted AAPL above, removed MSFT below, and A's row is
    # untouched by both deletions:
    assert bert_browser.delete("/api/watchlist/MSFT").status_code == 204
    assert bert_browser.get("/api/watchlist").get_json()["symbols"] == []


def test_stock_page_watched_stamp_follows_the_session(client):
    bert_browser = app.test_client()
    bert_id = seed_user("bert")
    with bert_browser.session_transaction() as session:
        session["user_id"] = bert_id
    db.add_symbol("AAPL", 1)

    watched = client.get("/stock/AAPL").get_data(as_text=True)
    assert 'data-watched="true"' in watched
    plain = bert_browser.get("/stock/AAPL").get_data(as_text=True)
    assert 'data-watched="false"' in plain


def test_portfolios_names_and_defaults_are_per_user(client):
    bert, bert_id = second_browser()
    holiday_for_a = client.post("/api/portfolios",
                                json={"name": "Holiday"}).json["id"]
    # The same name is fine for the other person (uniqueness is per user):
    holiday_for_b = bert.post("/api/portfolios",
                              json={"name": "Holiday"}).json["id"]
    assert holiday_for_a != holiday_for_b
    a_ids = {p["id"] for p in client.get("/api/portfolios").json}
    b_ids = {p["id"] for p in bert.get("/api/portfolios").json}
    assert a_ids == {1, holiday_for_a}
    assert b_ids == {2, holiday_for_b}
    # And creating a THIRD user with yet another Main works:
    third, third_id = second_browser("cara")
    third_pids = [p["id"] for p in third.get("/api/portfolios").json]
    assert [p["name"] for p in third.get("/api/portfolios").json] == ["Main"]
    assert db.default_portfolio_id(third_id) == third_pids[0]
    assert len(third_pids) == 1
