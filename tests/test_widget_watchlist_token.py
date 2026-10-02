# tests/test_widget_watchlist_token.py
# =====================================
# Contract tests for roadmap #59 (Android watchlist widget): the generalized
# widget-token scope (portfolio | watchlist) and the bearer-only
# /api/widget/watchlist route.
#
# The shape under test:
#   * widget_tokens gains `scope`; a watchlist token has scope='watchlist'
#     and portfolio_id NULL, and pre-scope rows migrate to 'portfolio';
#   * POST /api/widget/tokens with {"scope":"watchlist"} mints a watchlist
#     token; a portfolio token is unchanged apart from a scope label;
#   * GET /api/widget/watchlist accepts exactly one Authorization: Bearer
#     watchlist token and serves the token owner's watchlist, in the same
#     {symbols, quotes} shape as the session /api/watchlist route;
#   * each bearer route accepts only its own scope; revoking a token,
#     deleting its owner, or (for a portfolio token) deleting its portfolio
#     makes the route answer 401.

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import db
import app as app_module
from app import app
from conftest import (CLIENT_USER_ID, main_portfolio_id, make_quote,
                      seed_user)

ROOT = Path(__file__).resolve().parents[1]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_watchlist_token(client):
    return client.post("/api/widget/tokens", json={"scope": "watchlist"})


def create_portfolio_token(client, portfolio_id=None):
    if portfolio_id is None:
        portfolio_id = main_portfolio_id()
    return client.post("/api/widget/tokens", json={"portfolio_id": portfolio_id})


# ── Schema + migration ───────────────────────────────────────────────────

def test_init_columns_include_scope_and_nullable_portfolio(fresh_db):
    with sqlite3.connect(fresh_db) as conn:
        cols = {row[1]: row for row in conn.execute(
            "PRAGMA table_info(widget_tokens)")}
    assert "scope" in cols
    assert cols["portfolio_id"][3] == 0, "portfolio_id must be nullable"
    assert cols["scope"][3] == 1, "scope must be NOT NULL"


def test_old_table_migrates_to_portfolio_scope(fresh_db):
    seed_user("tester")  # creates user 1 + its Main portfolio, so the FK holds
    with sqlite3.connect(fresh_db) as conn:
        conn.execute("DROP TABLE widget_tokens")
        conn.execute("""CREATE TABLE widget_tokens (
            id           INTEGER PRIMARY KEY,
            user_id      INTEGER NOT NULL REFERENCES users(id),
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
            token_hash   TEXT NOT NULL UNIQUE,
            created_at   TEXT NOT NULL,
            last_used_at TEXT)""")
        conn.execute(
            "INSERT INTO widget_tokens (id, user_id, portfolio_id, token_hash,"
            " created_at) VALUES (1, 1, 1, 'legacyhash', '2026-01-01T00:00:00+00:00')")

    db.init()  # idempotent: must rebuild the pre-scope table in place

    with sqlite3.connect(fresh_db) as conn:
        cols = {row[1]: row for row in conn.execute(
            "PRAGMA table_info(widget_tokens)")}
        assert "scope" in cols
        assert cols["portfolio_id"][3] == 0
        row = conn.execute(
            "SELECT scope, portfolio_id, token_hash FROM widget_tokens"
        ).fetchone()
    assert row == ("portfolio", 1, "legacyhash")


# ── Token creation ───────────────────────────────────────────────────────

def test_create_watchlist_token_201(client):
    res = create_watchlist_token(client)
    assert res.status_code == 201
    body = res.get_json()
    assert body["scope"] == "watchlist"
    assert body["token"] and len(body["token"]) >= 20
    assert body["created_at"]
    assert "portfolio_id" not in body


def test_create_watchlist_token_stores_hash_and_null_portfolio(client, fresh_db):
    token = create_watchlist_token(client).get_json()["token"]
    with sqlite3.connect(fresh_db) as conn:
        row = conn.execute(
            "SELECT scope, portfolio_id, token_hash FROM widget_tokens").fetchone()
    assert row[0] == "watchlist"
    assert row[1] is None
    assert row[2] == token_hash(token)
    assert row[2] != token


def test_create_rejects_unknown_scope(client):
    assert client.post(
        "/api/widget/tokens", json={"scope": "nonsense"}).status_code == 400


def test_create_rejects_ambiguous_body(client):
    body = {"scope": "watchlist", "portfolio_id": main_portfolio_id()}
    assert client.post("/api/widget/tokens", json=body).status_code == 400


def test_portfolio_token_reply_has_scope(client):
    res = create_portfolio_token(client)
    assert res.status_code == 201
    body = res.get_json()
    assert body["scope"] == "portfolio"
    assert body["portfolio_name"] == "Main"


def test_create_accepts_explicit_portfolio_scope(client):
    body = {"scope": "portfolio", "portfolio_id": main_portfolio_id()}
    res = client.post("/api/widget/tokens", json=body)
    assert res.status_code == 201
    assert res.get_json()["scope"] == "portfolio"


def test_list_includes_scope_for_both(client):
    create_portfolio_token(client)
    create_watchlist_token(client)
    listed = client.get("/api/widget/tokens").get_json()
    assert len(listed) == 2
    by_scope = {item["scope"]: item for item in listed}
    assert set(by_scope) == {"portfolio", "watchlist"}
    assert by_scope["portfolio"]["portfolio_name"] == "Main"
    assert by_scope["watchlist"]["portfolio_name"] is None


# ── Bearer /api/widget/watchlist ─────────────────────────────────────────

def test_watchlist_bearer_returns_symbols_and_quotes(client, fake_market):
    db.add_symbol("AAPL", CLIENT_USER_ID)
    db.add_symbol("SHOP.TO", CLIENT_USER_ID)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0, "USD")
    fake_market.names["AAPL"] = "Apple Inc."
    fake_market.quotes["SHOP.TO"] = make_quote("SHOP.TO", 120.0, 118.0, "CAD")
    fake_market.names["SHOP.TO"] = "Shopify"

    token = create_watchlist_token(client).get_json()["token"]
    res = client.get("/api/widget/watchlist", headers=auth(token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["symbols"] == ["AAPL", "SHOP.TO"]
    quotes = {q["symbol"]: q for q in body["quotes"]}
    assert set(quotes) == {"AAPL", "SHOP.TO"}
    assert quotes["AAPL"]["price"] == 105.0
    assert quotes["AAPL"]["currency"] == "USD"
    assert quotes["AAPL"]["name"] == "Apple Inc."
    assert quotes["AAPL"]["change"] == pytest.approx(5.0)
    assert quotes["AAPL"]["change_pct"] == pytest.approx(5.0)


def test_watchlist_bearer_empty_is_200(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    res = client.get("/api/widget/watchlist", headers=auth(token))
    assert res.status_code == 200
    assert res.get_json() == {"symbols": [], "quotes": []}


def test_watchlist_bearer_omits_failed_symbols(client, fake_market):
    db.add_symbol("AAPL", CLIENT_USER_ID)
    db.add_symbol("DEAD", CLIENT_USER_ID)  # deliberately absent from fake market
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0, "USD")
    fake_market.names["AAPL"] = "Apple Inc."

    token = create_watchlist_token(client).get_json()["token"]
    body = client.get(
        "/api/widget/watchlist", headers=auth(token)).get_json()
    assert body["symbols"] == ["AAPL", "DEAD"]
    assert [q["symbol"] for q in body["quotes"]] == ["AAPL"]


def test_watchlist_bearer_rejects_portfolio_token(client, fake_market):
    token = create_portfolio_token(client).get_json()["token"]
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 401


def test_summary_rejects_watchlist_token(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    assert client.get(
        "/api/widget/summary", headers=auth(token)).status_code == 401


@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Basic abc"},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Bearer not-a-real-token"},
])
def test_watchlist_bearer_requires_valid_bearer(client, fake_market, headers):
    assert client.get("/api/widget/watchlist", headers=headers).status_code == 401


def test_watchlist_bearer_is_json_401_when_signed_out(fresh_db):
    res = app.test_client().get("/api/widget/watchlist")
    assert res.status_code == 401
    assert res.is_json


def test_watchlist_bearer_touches_last_used(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    listed = client.get("/api/widget/tokens").get_json()[0]
    assert listed["last_used_at"] is None
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 200
    after = client.get("/api/widget/tokens").get_json()[0]
    assert after["last_used_at"] is not None


def test_watchlist_bearer_401_after_revoke(client, fake_market):
    created = create_watchlist_token(client).get_json()
    token, token_id = created["token"], created["id"]
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 200
    assert client.delete(f"/api/widget/tokens/{token_id}").status_code == 204
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 401


def test_watchlist_token_cascades_on_user_delete(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    seed_user("bob")
    assert db.delete_user(CLIENT_USER_ID, "tester") == "deleted"
    assert db.get_widget_token(token_hash(token)) is None
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 401


def test_watchlist_token_survives_portfolio_delete(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    second = db.create_portfolio("Second", CLIENT_USER_ID)
    assert db.delete_portfolio(second, CLIENT_USER_ID, "Second") == "deleted"
    assert client.get(
        "/api/widget/watchlist", headers=auth(token)).status_code == 200


def test_watchlist_token_cannot_access_session_watchlist(client, fake_market):
    token = create_watchlist_token(client).get_json()["token"]
    anon = app.test_client()
    assert anon.get("/api/watchlist", headers=auth(token)).status_code == 401


# ── Preferences UI source pins ───────────────────────────────────────────

def test_preferences_card_copy_mentions_both_widgets():
    prefs = (ROOT / "templates/preferences.html").read_text()
    assert "widget-card" in prefs
    assert "Watchlist" in prefs


def test_preferences_js_labels_watchlist_scope():
    js = (ROOT / "static/js/preferences.js").read_text()
    segment = js.split("manageWidgetTokens", 1)[1]
    assert "scope" in segment
    assert "Watchlist" in segment
    assert "POST" not in segment
    assert "localStorage" not in segment
