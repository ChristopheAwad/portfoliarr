# tests/test_widget_token.py
# ===========================
# Contract tests for feature #51 (Android home-screen widget): the scoped
# read-only token, its Preferences management endpoints, and the bearer-only
# /api/widget/summary route.
#
# The shape of the design under test:
#   * tokens are created by the phone (session-authenticated POST) and only
#     their SHA-256 hash is stored server-side;
#   * GET /api/widget/summary accepts exactly one Authorization: Bearer
#     token and nothing else — never the session cookie, never another route;
#   * a token names one portfolio, so no portfolio_id query can steer it;
#   * revoking a token, deleting its portfolio, or deleting its owner all
#     make the summary route answer 401;
#   * the payload is the small widget slice of the same math the dashboard
#     summary uses (no holdings, no cost basis).

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


def create_token(client, portfolio_id=None):
    if portfolio_id is None:
        portfolio_id = main_portfolio_id()
    return client.post("/api/widget/tokens", json={"portfolio_id": portfolio_id})


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ── Table + token lifecycle ──────────────────────────────────────────────

def test_init_creates_widget_tokens_table(fresh_db):
    with sqlite3.connect(fresh_db) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(widget_tokens)")
        }
    assert columns == {
        "id", "user_id", "portfolio_id", "token_hash", "created_at",
        "last_used_at",
    }


def test_create_stores_hash_not_plaintext(client, fresh_db):
    res = create_token(client)
    assert res.status_code == 201
    token = res.get_json()["token"]
    assert token and len(token) >= 20

    with sqlite3.connect(fresh_db) as conn:
        stored = conn.execute(
            "SELECT token_hash FROM widget_tokens").fetchone()[0]
    assert stored == token_hash(token)
    assert stored != token


@pytest.mark.parametrize("body", [
    {}, {"portfolio_id": "1"}, {"portfolio_id": True},
    {"portfolio_id": 0}, {"portfolio_id": -1}, {"portfolio_id": 1.5},
])
def test_create_rejects_bad_portfolio_id(client, body):
    assert client.post("/api/widget/tokens", json=body).status_code == 400


def test_create_rejects_non_object_body(client):
    assert client.post("/api/widget/tokens", json=[1]).status_code == 400


def test_create_rejects_other_users_portfolio(client):
    seed_user("bob")
    bob_portfolio = db.get_portfolios(2)[0]["id"]
    assert create_token(client, bob_portfolio).status_code == 404


def test_create_returns_token_once_and_list_never_returns_it(client):
    payload = create_token(client).get_json()
    assert payload["portfolio_name"] == "Main"
    assert payload["created_at"]

    listed = client.get("/api/widget/tokens").get_json()
    assert len(listed) == 1
    text = json.dumps(listed)
    assert payload["token"] not in text
    assert "token_hash" not in text
    assert "token" not in listed[0]


def test_list_shows_portfolio_name_created_and_last_used(client):
    create_token(client)
    item = client.get("/api/widget/tokens").get_json()[0]
    assert set(item) == {
        "id", "portfolio_id", "portfolio_name", "created_at", "last_used_at",
    }
    assert item["portfolio_name"] == "Main"
    assert item["created_at"]
    assert item["last_used_at"] is None


def test_last_used_at_set_after_successful_fetch(client, fake_market):
    token = create_token(client).get_json()["token"]
    assert client.get("/api/widget/tokens").get_json()[0]["last_used_at"] is None
    assert client.get("/api/widget/summary", headers=auth(token)).status_code == 200
    assert client.get("/api/widget/tokens").get_json()[0]["last_used_at"] is not None


def test_revoke_owned_returns_204_and_fetch_then_401(client, fake_market):
    created = create_token(client).get_json()
    token, token_id = created["token"], created["id"]
    assert client.get("/api/widget/summary", headers=auth(token)).status_code == 200
    assert client.delete(f"/api/widget/tokens/{token_id}").status_code == 204
    assert client.get("/api/widget/summary", headers=auth(token)).status_code == 401
    assert client.get("/api/widget/tokens").get_json() == []


def test_revoke_other_users_token_is_404(client):
    seed_user("bob")
    bob_portfolio = db.get_portfolios(2)[0]["id"]
    token_id = db.create_widget_token(
        2, bob_portfolio, "deadbeef", "2026-01-01T00:00:00+00:00")
    assert client.delete(f"/api/widget/tokens/{token_id}").status_code == 404
    assert db.get_widget_token("deadbeef") is not None


def test_revoke_unknown_token_is_404(client):
    assert client.delete("/api/widget/tokens/9999").status_code == 404


def test_delete_portfolio_cascades_tokens(client, fake_market):
    created = create_token(client).get_json()
    token = created["token"]
    main_pid = main_portfolio_id()
    db.create_portfolio("Second", CLIENT_USER_ID)

    assert db.delete_portfolio(main_pid, CLIENT_USER_ID, "Main") == "deleted"
    assert db.get_widget_token(token_hash(token)) is None
    assert client.get("/api/widget/summary", headers=auth(token)).status_code == 401


def test_delete_user_cascades_tokens(client, fake_market):
    token = create_token(client).get_json()["token"]
    seed_user("bob")
    assert db.delete_user(CLIENT_USER_ID, "tester") == "deleted"
    assert db.get_widget_token(token_hash(token)) is None


# ── /api/widget/summary auth surface ─────────────────────────────────────

@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Basic abc"},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Bearer not-a-real-token"},
])
def test_widget_summary_requires_a_valid_bearer(client, headers):
    assert client.get("/api/widget/summary", headers=headers).status_code == 401


def test_widget_summary_is_json_401_when_signed_out(fresh_db):
    res = app.test_client().get("/api/widget/summary")
    assert res.status_code == 401
    assert res.is_json


def test_signed_in_client_without_bearer_gets_401(client):
    assert client.get("/api/widget/summary").status_code == 401


def test_widget_token_cannot_access_other_endpoints(fresh_db):
    seed_user("tester")
    token = "widget-token-abcdefghijklmnopqrstuvwxyz"
    db.create_widget_token(
        CLIENT_USER_ID, main_portfolio_id(), token_hash(token),
        "2026-01-01T00:00:00+00:00")
    anon = app.test_client()
    for path in ("/api/portfolios", "/api/transactions",
                 "/api/portfolio/summary", "/api/watchlist"):
        assert anon.get(path, headers=auth(token)).status_code == 401


# ── /api/widget/summary payload ──────────────────────────────────────────

def test_widget_summary_empty_ledger(client, fake_market):
    token = create_token(client).get_json()["token"]
    res = client.get("/api/widget/summary", headers=auth(token))
    assert res.status_code == 200
    assert res.get_json() == {
        "portfolio_name": "Main",
        "currency": "CAD",
        "total_value": 0.0,
        "day_gain": 0.0,
        "day_gain_pct": None,
        "total_gain": 0.0,
        "total_gain_pct": None,
        "unpriced": [],
    }


def test_widget_summary_returns_cad_numbers(client, fake_market):
    pid = main_portfolio_id()
    db.add_transaction("AAPL", "2026-01-02", 100.0, 2.0, "USD", "BUY",
                       1.3, portfolio_id=pid)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0, "USD")
    fake_market.fx_rates["USDCAD"] = 1.4

    token = create_token(client).get_json()["token"]
    body = client.get("/api/widget/summary", headers=auth(token)).get_json()
    assert body["portfolio_name"] == "Main"
    assert body["currency"] == "CAD"
    assert body["total_value"] == pytest.approx(2 * 105 * 1.4)
    assert body["day_gain"] == pytest.approx(2 * 5 * 1.4)
    assert body["day_gain_pct"] == pytest.approx(5.0)
    assert body["total_gain"] == pytest.approx(294.0 - 260.0)
    assert body["total_gain_pct"] == pytest.approx(34.0 / 260.0 * 100)


def test_widget_summary_matches_portfolio_summary(client, fake_market):
    pid = main_portfolio_id()
    db.add_transaction("AAPL", "2026-01-02", 100.0, 2.0, "USD", "BUY",
                       1.3, portfolio_id=pid)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 105.0, 100.0, "USD")
    fake_market.fx_rates["USDCAD"] = 1.4

    token = create_token(client).get_json()["token"]
    widget = client.get("/api/widget/summary", headers=auth(token)).get_json()
    dashboard = client.get(
        f"/api/portfolio/summary?portfolio_id={pid}").get_json()
    for key in ("currency", "total_value", "day_gain", "day_gain_pct",
                "total_gain", "total_gain_pct", "unpriced"):
        assert widget[key] == dashboard[key], key


def test_widget_summary_has_no_holdings_or_cost_basis(client, fake_market):
    pid = main_portfolio_id()
    db.add_transaction("AAPL", "2026-01-02", 100.0, 1.0, "CAD", "BUY",
                       1.0, portfolio_id=pid)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 100.0, "CAD")
    token = create_token(client).get_json()["token"]
    body = client.get("/api/widget/summary", headers=auth(token)).get_json()
    assert "holdings" not in body
    assert "cost_basis" not in body


def test_widget_summary_scoped_to_token_portfolio(client, fake_market):
    main_pid = main_portfolio_id()
    db.add_transaction("AAPL", "2026-01-02", 100.0, 1.0, "CAD", "BUY",
                       1.0, portfolio_id=main_pid)
    second = db.create_portfolio("Second", CLIENT_USER_ID)
    db.add_transaction("MSFT", "2026-01-02", 50.0, 10.0, "CAD", "BUY",
                       1.0, portfolio_id=second)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 110.0, 100.0, "CAD")
    fake_market.quotes["MSFT"] = make_quote("MSFT", 60.0, 50.0, "CAD")

    token = create_token(client, second).get_json()["token"]
    body = client.get("/api/widget/summary", headers=auth(token)).get_json()
    assert body["portfolio_name"] == "Second"
    assert body["total_value"] == pytest.approx(600.0)


def test_widget_summary_ignores_query_portfolio_id(client, fake_market):
    second = db.create_portfolio("Second", CLIENT_USER_ID)
    token = create_token(client).get_json()["token"]
    body = client.get(
        f"/api/widget/summary?portfolio_id={second}",
        headers=auth(token)).get_json()
    assert body["portfolio_name"] == "Main"
    assert body["total_value"] == 0.0


def test_widget_summary_all_quotes_fail(client, fake_market):
    pid = main_portfolio_id()
    db.add_transaction("CM", "2026-01-02", 100.0, 1.0, "USD", "BUY",
                       1.2, portfolio_id=pid)
    # "CM" deliberately absent from the fake market.
    token = create_token(client).get_json()["token"]
    res = client.get("/api/widget/summary", headers=auth(token))
    assert res.status_code == 200
    body = res.get_json()
    assert body["unpriced"] == ["CM"]
    assert body["total_value"] == 0.0
    assert body["day_gain"] == 0.0
    assert body["day_gain_pct"] is None
    assert body["total_gain_pct"] is None


# ── Preferences UI source pins (creation is native; web lists/revokes) ───

def test_preferences_has_widget_card():
    prefs = (ROOT / "templates/preferences.html").read_text()
    for hook in ("widget-card", "widget-list", "widget-error"):
        assert hook in prefs, f"preferences.html is missing {hook}"


def test_preferences_js_lists_and_revokes_only():
    js = (ROOT / "static/js/preferences.js").read_text()
    assert "manageWidgetTokens" in js
    segment = js.split("manageWidgetTokens", 1)[1]
    assert "/api/widget/tokens" in segment
    assert "DELETE" in segment
    assert "POST" not in segment, "the web UI must not create widget tokens"
    assert "localStorage" not in segment, "tokens never touch localStorage"
