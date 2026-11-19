# tests/test_auth.py
# ===================
# Route-level auth contract: the before_request gate, the setup page, the
# login/logout forms, the People (user management) API, and password
# change. Single-user tests ride the `client` fixture — its seeded user is
# always id 1 ("tester"); fresh app.test_client() instances play the
# signed-out browser. NO network is ever touched: fake_market stands in
# for Yahoo wherever a route body would fetch quotes.

import logging
import sqlite3
import sys

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import app as app_module
from app import app, perform_password_reset, run_reset_password_command
import db
from conftest import (make_legacy_db, make_quote, seed_user, sign_in,
                      TESTER_PASSWORD)


def browser():
    """A signed-OUT Flask test client (a fresh browser's cookie jar)."""
    return app.test_client()


def login(web_client, username, password):
    """The real no-JS login flow: an HTML form POST."""
    return web_client.post("/auth/login", data={
        "username": username, "password": password})


# ── The gate ──────────────────────────────────────────────────────────

def test_signed_out_page_redirects_with_next(fresh_db):
    web_client = browser()
    for path in ("/", "/ledger", "/stock/AAPL"):
        response = web_client.get(path)
        assert response.status_code == 302, path
        assert response.headers["Location"].endswith(
            f"/auth/login?next={path}"), path


def test_signed_out_api_is_401_json(fresh_db):
    web_client = browser()
    response = web_client.get("/api/watchlist")
    assert response.status_code == 401
    assert response.get_json() == {"error": "authentication required"}
    assert web_client.post("/api/transactions",
                           json={"ticker": "AAPL"}).status_code == 401
    assert web_client.get("/api/portfolios").status_code == 401


def test_static_bypasses_the_gate_and_login_renders_with_users(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    web_client = browser()
    assert web_client.get("/static/style.css").status_code == 200
    # Signed OUT, users exist: the login page is a normal 200 form page.
    assert web_client.get("/auth/login").status_code == 200


def test_unknown_url_redirects_signed_out_and_404s_signed_in(client):
    assert browser().get("/definitely-not-a-route").status_code == 302
    assert client.get("/definitely-not-a-route").status_code == 404


def test_deleted_user_session_is_rejected_not_leaked(client):
    """A signed-in user vanishes mid-session (deleted by someone else):
    the next request must answer like any signed-out request, never a
    500 and never their data."""
    third_id = seed_user("third")
    third_browser = app.test_client()
    sign_in(third_browser, third_id)
    assert third_browser.get("/api/watchlist").status_code == 200
    assert client.delete(f"/api/users/{third_id}",
                         json={"username": "third"}).status_code == 204
    after = third_browser.get("/api/watchlist")
    assert after.status_code == 401
    assert after.get_json() == {"error": "authentication required"}


# ── Setup (first run) ────────────────────────────────────────────────

def test_setup_redirects_to_login_and_post_is_rejected(client):
    response = client.get("/auth/setup")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    rejection = client.post("/auth/setup", data={
        "username": "owner", "password": "owner-pass-1",
        "confirm_password": "owner-pass-1"})
    assert rejection.status_code == 409
    assert rejection.get_json() == {"error": "setup already complete"}


def test_setup_redirects_to_login_when_zero_users(fresh_db):
    web_client = browser()
    assert web_client.get("/auth/login").headers[
        "Location"].endswith("/auth/setup")
    response = web_client.post("/auth/login", data={"username": "a",
                                                    "password": "b"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/setup")


def test_setup_adopts_legacy_data_and_signs_in(tmp_path, monkeypatch,
                                               fake_market):
    path = tmp_path / "old.db"
    make_legacy_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    web_client = browser()
    fake_market.quotes["AAPL"] = make_quote("AAPL", 10, 9)
    response = web_client.post("/auth/setup", data={
        "username": "owner", "password": "owner-pass-1",
        "confirm_password": "owner-pass-1"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert [p["name"]
            for p in web_client.get("/api/portfolios").get_json()] == ["Main"]
    watchlist = web_client.get("/api/watchlist").get_json()
    assert watchlist["symbols"] == ["AAPL"]
    assert db.count_users() == 1


def test_setup_validation_errors_re_render_400(fresh_db):
    web_client = browser()
    cases = [
        ({"username": "", "password": "owner-pass-1",
          "confirm_password": "owner-pass-1"},
         "Usernames are 1 to 30 characters."),
        ({"username": "x" * 31, "password": "owner-pass-1",
          "confirm_password": "owner-pass-1"},
         "Usernames are 1 to 30 characters."),
        ({"username": "kid", "password": "abc",
          "confirm_password": "abc"},
         "Passwords are 8 to 128 characters."),
        ({"username": "kid", "password": "y" * 129,
          "confirm_password": "y" * 129},
         "Passwords are 8 to 128 characters."),
        ({"username": "kid", "password": "secret-1",
          "confirm_password": "secret-2"},
         "Passwords do not match."),
    ]
    for form, message in cases:
        response = web_client.post("/auth/setup", data=form)
        assert response.status_code == 400, form
        assert message in response.get_data(as_text=True), form
        assert db.count_users() == 0, form


# ── Login / logout ────────────────────────────────────────────────────

def test_login_success_redirects_and_cookie_works(client):
    web_client = browser()
    response = login(web_client, "tester", TESTER_PASSWORD)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert web_client.get("/api/watchlist").status_code == 200


def test_login_honors_safe_next(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    web_client = browser()
    response = web_client.post("/auth/login?next=%2Fledger", data={
        "username": "tester", "password": TESTER_PASSWORD})
    assert response.headers["Location"].endswith("/ledger")


@pytest.mark.parametrize("next_value", ["//evil.com", "", "http://evil.com"])
def test_login_next_falls_back_to_home_for_unsafe_values(client, next_value):
    web_client = browser()
    response = web_client.post(f"/auth/login?next={next_value}", data={
        "username": "tester", "password": TESTER_PASSWORD})
    assert response.headers["Location"].endswith("/")


def test_login_failures_are_uniform(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    web_client = browser()
    for form in ({"username": "ghost", "password": "x"},
                 {"username": "tester", "password": "wrong-key"}):
        response = web_client.post("/auth/login", data=form)
        assert response.status_code == 400
        assert "Wrong username or password." in response.get_data(as_text=True)
        assert web_client.get("/api/watchlist").status_code == 401


def test_login_redirects_signed_in_users_home(client):
    response = client.get("/auth/login")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_logout_clears_session(client):
    response = client.post("/auth/logout")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    assert client.get("/api/watchlist").status_code == 401


# ── People management API ─────────────────────────────────────────────

def test_list_users_returns_id_and_username_only(client):
    seed_user("second")
    users = client.get("/api/users").get_json()
    assert [user["username"] for user in users] == ["tester", "second"]
    assert all(set(user) == {"id", "username"} for user in users)


def test_create_user_via_api_validates_fields_and_taken_names(client):
    response = client.post("/api/users",
                           json={"username": "kid", "password": "kid-key-1"})
    assert response.status_code == 201
    assert response.get_json() == {"id": 2, "username": "kid"}
    assert [p["name"] for p in db.get_portfolios(2)] == ["Main"]

    bad_bodies = [
        (None, "expected JSON body with username and password"),
        ({"password": "kid-key-1"},
         "expected JSON body with username and password"),
        ({"username": "", "password": "kid-key-1"},
         "username must contain 1 to 30 characters"),
        ({"username": "x" * 31, "password": "kid-key-1"},
         "username must contain 1 to 30 characters"),
        ({"username": "kid", "password": "abc"},
         "password must contain 8 to 128 characters"),
        ({"username": "kid", "password": "y" * 129},
         "password must contain 8 to 128 characters"),
    ]
    for body, message in bad_bodies:
        response = client.post("/api/users", json=body)
        assert response.status_code == 400, body
        assert message in response.get_data(as_text=True), body

    taken = client.post("/api/users",
                        json={"username": "TESTER", "password": "kid-key-1"})
    assert taken.status_code == 409
    assert "already taken" in taken.get_data(as_text=True)


def test_delete_user_rules(client):
    text = lambda response: response.get_data(as_text=True)
    own = client.delete("/api/users/1", json={"username": "tester"})
    assert own.status_code == 400
    assert "signed in as" in text(own)
    assert client.delete("/api/users/999",
                         json={"username": "ghost"}).status_code == 404
    no_body = client.delete("/api/users/2")
    assert no_body.status_code == 400
    assert "type the username to confirm" in text(no_body)

    kid_id = seed_user("kid")
    mismatch = client.delete(f"/api/users/{kid_id}", json={"username": "KID"})
    assert mismatch.status_code == 409
    assert "typed username does not match" in text(mismatch)
    assert kid_id in {user["id"] for user in client.get("/api/users").json}

    assert client.delete(f"/api/users/{kid_id}",
                         json={"username": "kid"}).status_code == 204
    assert db.get_portfolios(kid_id) == []
    assert [user["username"] for user in client.get("/api/users").json] == [
        "tester"]


def test_delete_user_cascade_via_api_isolates_the_rest(client, fake_market):
    kid_id = seed_user("kid")
    kid_main = db.get_portfolios(kid_id)[0]["id"]
    db.add_transaction("AAPL", "2026-01-01", 10, 2, "CAD", "BUY", 1,
                       portfolio_id=kid_main)
    db.add_symbol("MSFT", kid_id)
    db.add_symbol("AAPL", 1)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 10, 9)

    assert client.delete(f"/api/users/{kid_id}",
                         json={"username": "kid"}).status_code == 204
    assert db.get_transaction(1, kid_main) is None
    assert db.get_symbols(kid_id) == []
    assert [user["username"] for user in client.get("/api/users").json] == [
        "tester"]
    assert client.get(
        "/api/watchlist").get_json()["symbols"] == ["AAPL"]
    assert len(db.get_portfolios(1)) == 1


def test_change_own_password_via_api(client):
    response = client.post("/api/auth/password", json={
        "current_password": TESTER_PASSWORD, "new_password": "new-key-9"})
    assert response.status_code == 204

    web_client = browser()
    assert login(web_client, "tester", TESTER_PASSWORD).status_code == 400
    assert login(web_client, "tester", "new-key-9").status_code == 302

    wrong_current = client.post("/api/auth/password", json={
        "current_password": "nope-case", "new_password": "another-key-7"})
    assert wrong_current.status_code == 400
    assert wrong_current.get_json()["error"] == "current password does not match"

    bad_new = client.post("/api/auth/password", json={
        "current_password": "new-key-9", "new_password": "ab"})
    assert bad_new.status_code == 400
    assert bad_new.get_json()["error"] == (
        "password must contain 8 to 128 characters")

    shape = client.post("/api/auth/password", json={
        "current_password": "new-key-9"})
    assert shape.status_code == 400
    assert shape.get_json()["error"] == (
        "expected JSON body with current_password and new_password")


# ── Log events ────────────────────────────────────────────────────────

def test_auth_events_are_logged_without_secrets(client, caplog):
    web_client = browser()
    with caplog.at_level(logging.INFO):
        web_client.post("/auth/login",
                        data={"username": "tester", "password": "bad-pass"})
        login(web_client, "tester", TESTER_PASSWORD)
        kid_id = client.post("/api/users", json={
            "username": "kid", "password": "kid-key-1"}).json["id"]
        client.delete(f"/api/users/{kid_id}", json={"username": "kid"})
        client.post("/api/auth/password", json={
            "current_password": TESTER_PASSWORD, "new_password": "new-key-9"})

    records = [record.getMessage() for record in caplog.records]
    text = "".join(records)
    assert any("event=login_failed " in line and "username='tester'" in line
               for line in records)
    assert any("event=login_success " in line and "username='tester'" in line
               for line in records)
    assert any("event=user_created " in line and "username='kid'" in line
               for line in records)
    assert any("event=user_deleted " in line and "username='kid'" in line
               for line in records)
    assert any("event=password_changed " in line for line in records)
    # No password, guessed or real, ever reached the log:
    for password in ("bad-pass", "kid-key-1", "new-key-9", TESTER_PASSWORD):
        assert password not in text


# ── CLI password reset (roadmap #27, part 1) ──────────────────────────

def test_perform_password_reset_unknown_username(fresh_db):
    ok, message = perform_password_reset("ghost", "brand-new-key-7")
    assert ok is False
    assert "No account" in message


def test_perform_password_reset_trimmed_casing_lookup(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    ok, _ = perform_password_reset("  TestEr ", "brand-new-key-7")
    assert ok is True


def test_perform_password_reset_rejects_out_of_range(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    for password in ("abc", "y" * 129):
        ok, message = perform_password_reset("tester", password)
        assert ok is False, password
        assert message == "Passwords are 8 to 128 characters.", password


def test_perform_password_reset_round_trip(fresh_db):
    uid = seed_user("tester", TESTER_PASSWORD)
    ok, message = perform_password_reset("tester", "brand-new-key-7")
    assert ok is True
    hash_now = db.get_user(uid)["password_hash"]
    assert check_password_hash(hash_now, "brand-new-key-7")
    assert not check_password_hash(hash_now, TESTER_PASSWORD)
    assert "Password updated" in message


def test_perform_password_reset_event_has_no_password(fresh_db, caplog):
    seed_user("tester", TESTER_PASSWORD)
    with caplog.at_level(logging.INFO):
        perform_password_reset("tester", "brand-new-key-7")
    lines = [record.getMessage() for record in caplog.records]
    assert any("event=password_reset " in line for line in lines)
    assert "brand-new-key-7" not in "".join(lines)


def test_run_reset_password_command_mismatch(fresh_db, monkeypatch, capsys):
    seed_user("tester", TESTER_PASSWORD)
    typed = iter(["pw-one-11", "pw-two-99"])
    monkeypatch.setattr(app_module.getpass, "getpass",
                        lambda prompt="": next(typed))
    assert run_reset_password_command("tester") == 1
    assert "Passwords do not match." in capsys.readouterr().err


def test_run_reset_password_command_success(fresh_db, monkeypatch, capsys):
    uid = seed_user("tester", TESTER_PASSWORD)
    monkeypatch.setattr(app_module.getpass, "getpass",
                        lambda prompt="": "brand-new-key-9")
    assert run_reset_password_command("tester") == 0
    assert "Password updated" in capsys.readouterr().out
    assert check_password_hash(
        db.get_user(uid)["password_hash"], "brand-new-key-9")


def test_main_dispatch_reset_and_usage(fresh_db, monkeypatch, capsys):
    seed_user("tester", TESTER_PASSWORD)
    monkeypatch.setattr(app_module.getpass, "getpass",
                        lambda prompt="": "brand-new-key-9")
    assert app_module.main(["app.py", "reset-password", "tester"]) == 0
    assert app_module.main(["app.py", "reset-password"]) == 1
    assert "usage: python app.py reset-password <username>" in (
        capsys.readouterr().err)


def test_main_no_arguments_means_the_dev_server(monkeypatch):
    booted = []
    monkeypatch.delenv("PORTFOLIARR_DEBUG", raising=False)
    monkeypatch.setattr(sys, "argv", ["app.py"])
    monkeypatch.setattr(app_module.app, "run",
                        lambda **options: booted.append(options))
    assert app_module.main(None) == 0
    assert len(booted) == 1 and booted[0]["host"] == "127.0.0.1"
    assert booted[0]["debug"] is False
    # A LIST argument never boots the server: tests exercise main() freely.
    assert app_module.main(["app.py"]) == 0
    assert len(booted) == 1


# ── Open sign-up, owner-controlled (roadmap #27, part 2) ──────────────

def test_signup_toggle_defaults_off(client):
    assert client.get("/api/auth/signup-toggle").get_json() == {"allow": False}


def test_signup_toggle_requires_session(fresh_db):
    seed_user("tester", TESTER_PASSWORD)
    web_client = browser()
    assert web_client.get("/api/auth/signup-toggle").status_code == 401
    assert web_client.post("/api/auth/signup-toggle",
                           json={"allow": True}).status_code == 401


def test_signup_toggle_round_trip_and_persistence(client):
    assert client.post("/api/auth/signup-toggle",
                       json={"allow": True}).status_code == 204
    assert client.get("/api/auth/signup-toggle").get_json() == {"allow": True}
    # The setting lives in app_settings (SQLite): a fresh browser sees it.
    assert db.get_setting("allow_signup") == "true"
    web_client = browser()
    assert web_client.get("/auth/signup").status_code == 200
    assert client.post("/api/auth/signup-toggle",
                       json={"allow": False}).status_code == 204
    assert client.get("/api/auth/signup-toggle").get_json() == {"allow": False}


def test_signup_toggle_rejects_bad_bodies(client):
    bad = [None, [1], {"allow": 1}, {"allow": "yes"}, {}]
    for body in bad:
        response = client.post("/api/auth/signup-toggle", json=body)
        assert response.status_code == 400, body
        assert "boolean" in response.get_data(as_text=True), body


def test_signup_page_locked_by_default(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    web_client = browser()
    response = web_client.get("/auth/signup")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")
    assert "Create an account" not in web_client.get(
        "/auth/login").get_data(as_text=True)


def test_signup_page_unlocked(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    db.set_setting("allow_signup", "true")
    web_client = browser()
    page = web_client.get("/auth/signup")
    assert page.status_code == 200
    assert 'name="username"' in page.get_data(as_text=True)
    login_page = web_client.get("/auth/login").get_data(as_text=True)
    assert 'href="/auth/signup"' in login_page
    assert "Create an account" in login_page


def test_signup_success_creates_main_and_signs_in(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    db.set_setting("allow_signup", "true")
    web_client = browser()
    response = web_client.post("/auth/signup", data={
        "username": "neu", "password": "pw-key-9", "confirm_password":
        "pw-key-9"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert db.count_users() == 2
    portfolios = web_client.get("/api/portfolios").get_json()
    assert [p["name"] for p in portfolios] == ["Main"]


def test_signup_validation_ladder(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    db.set_setting("allow_signup", "true")
    web_client = browser()
    cases = [
        ({"username": "x" * 31, "password": "pw-key-9", "confirm_password":
          "pw-key-9"}, "Usernames are 1 to 30 characters."),
        ({"username": "kid", "password": "abc", "confirm_password": "abc"},
         "Passwords are 8 to 128 characters."),
        ({"username": "kid", "password": "secret-1", "confirm_password":
          "secret-2"}, "Passwords do not match."),
        ({"username": "TESTER", "password": "pw-key-9", "confirm_password":
          "pw-key-9"}, "That username is taken."),
    ]
    for form, message in cases:
        response = web_client.post("/auth/signup", data=form)
        assert response.status_code == 400, form
        assert message in response.get_data(as_text=True), form
    assert db.count_users() == 1


def test_signup_refused_when_disabled(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    web_client = browser()
    assert web_client.post("/auth/signup", data={
        "username": "neu", "password": "pw-key-9",
        "confirm_password": "pw-key-9"}).status_code == 409
    assert db.count_users() == 1


def test_signup_setup_mode_redirects_to_setup(fresh_db):
    assert browser().get("/auth/signup").headers[
        "Location"].endswith("/auth/setup")


def test_signed_in_visitor_redirected_from_signup(client):
    response = client.get("/auth/signup")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_signup_events_logged_without_secrets(fresh_db, caplog):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    db.set_setting("allow_signup", "true")
    web_client = browser()
    with caplog.at_level(logging.INFO):
        output = web_client.post("/auth/signup", data={
            "username": "neu", "password": "pw-key-9",
            "confirm_password": "pw-key-9"})
    assert output.status_code == 302
    lines = [record.getMessage() for record in caplog.records]
    assert any("event=user_created " in line and "username='neu'" in line
               and "source=signup" in line for line in lines)
    assert "pw-key-9" not in "".join(lines)


# ── Owner-only management surface ─────────────────────────────────────

def regular_browser(username="kid"):
    uid = seed_user(username, TESTER_PASSWORD)
    web_client = browser()
    sign_in(web_client, uid)
    return web_client, uid


def test_owner_only_endpoints_reject_regular_users_before_body(client):
    regular, regular_id = regular_browser()
    owner_id = db.get_user_by_username("tester")["id"]
    calls = [
        ("get", "/api/users", None),
        ("head", "/api/users", None),
        ("post", "/api/users", {"username": "x", "password": "y"}),
        ("delete", f"/api/users/{owner_id}", {"username": "tester"}),
        ("post", "/api/auth/signup-toggle", {"allow": True}),
        ("put", "/api/fund-classification/VEQT.TO",
         {"dimension": "country", "weights": {"Canada": 1}}),
        ("delete", "/api/fund-classification/VEQT.TO", None),
    ]
    for method, url, body in calls:
        response = (getattr(regular, method)(url) if body is None
                    else getattr(regular, method)(url, json=body))
        assert response.status_code == 403, (method, url)
        if method != "head":
            assert response.get_json()["error"] == "owner access required"

    # Shared reads and the account's own private data stay available.
    assert regular.get("/api/auth/signup-toggle").get_json() == {"allow": False}
    assert regular.get("/api/fund-classification/VEQT.TO").status_code == 200
    assert regular.get("/api/portfolios").status_code == 200
    assert regular.get("/api/watchlist").status_code == 200
    assert regular.post("/api/auth/password", json={
        "current_password": TESTER_PASSWORD,
        "new_password": "regular-own-key-1"}).status_code == 204


def test_owner_can_still_manage_people_and_policy(client):
    assert client.get("/api/users").status_code == 200
    assert client.post("/api/auth/signup-toggle",
                       json={"allow": True}).status_code == 204
    kid = client.post("/api/users", json={
        "username": "kid", "password": "kid-key-1"})
    assert kid.status_code == 201
    assert client.delete(f"/api/users/{kid.json['id']}",
                         json={"username": "kid"}).status_code == 204


def test_owner_account_cannot_be_deleted_via_api(client):
    kid, _ = regular_browser()
    owner_id = db.get_user_by_username("tester")["id"]
    response = kid.delete(f"/api/users/{owner_id}", json={"username": "tester"})
    assert response.status_code == 403


def test_signed_out_owner_endpoints_are_401_not_403(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    anon = browser()
    assert anon.get("/api/users").status_code == 401
    assert anon.post("/api/users", json={}).status_code == 401
    assert anon.post("/api/auth/signup-toggle",
                     json={"allow": True}).status_code == 401
    assert anon.put("/api/fund-classification/VEQT.TO",
                    json={}).status_code == 401


# ── Session version and role authority ────────────────────────────────

def _owner_id():
    return db.get_user_by_username("tester")["id"]


def test_missing_pv_session_is_rejected_and_cleared(client):
    web_client = browser()
    with web_client.session_transaction() as session:
        session["user_id"] = _owner_id()
    assert web_client.get("/api/watchlist").status_code == 401
    with web_client.session_transaction() as session:
        assert "user_id" not in session
        assert "pv" not in session


def test_non_integer_session_values_are_rejected(client):
    for user_id, pv in (("1", 1), (1, "1"), (True, 1), (1, True)):
        web_client = browser()
        with web_client.session_transaction() as session:
            session["user_id"] = user_id
            session["pv"] = pv
        assert web_client.get("/api/watchlist").status_code == 401, (
            user_id, pv)


def test_stale_pv_is_rejected_and_cleared(client):
    web_client = browser()
    with web_client.session_transaction() as session:
        session["user_id"] = _owner_id()
        session["pv"] = 999
    assert web_client.get("/api/watchlist").status_code == 401
    with web_client.session_transaction() as session:
        assert "user_id" not in session


def test_cookie_role_cannot_escalate(client):
    regular, _ = regular_browser()
    with regular.session_transaction() as session:
        session["role"] = "owner"
    assert regular.get("/api/users").status_code == 403


def test_login_stamps_the_verified_rows_pv(fresh_db):
    db.create_first_user("tester", generate_password_hash(TESTER_PASSWORD))
    web_client = browser()
    assert login(web_client, "tester", TESTER_PASSWORD).status_code == 302
    with web_client.session_transaction() as session:
        assert session["pv"] == db.get_user_by_username(
            "tester")["password_version"]


# ── Setup transaction and failure paths ───────────────────────────────

def test_setup_concurrent_race_answers_409(fresh_db, monkeypatch):
    monkeypatch.setattr(db, "create_first_user",
                        lambda username, password_hash: None)
    response = browser().post("/auth/setup", data={
        "username": "owner", "password": "owner-pass-1",
        "confirm_password": "owner-pass-1"})
    assert response.status_code == 409
    assert response.get_json() == {"error": "setup already complete"}
    assert db.count_users() == 0


def test_setup_persistence_failure_is_generic_500_and_rolls_back(
        fresh_db, monkeypatch):
    def explode(username, password_hash):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(db, "create_first_user", explode)
    response = browser().post("/auth/setup", data={
        "username": "owner", "password": "owner-pass-1",
        "confirm_password": "owner-pass-1"})
    assert response.status_code == 500
    assert response.get_json() == {"error": "internal server error"}
    assert db.count_users() == 0


# ── Local recovery commands ───────────────────────────────────────────

def test_assign_owner_cli_contract(fresh_db, capsys):
    kid = seed_user("kid", TESTER_PASSWORD)
    assert app_module.main(["app.py", "assign-owner", "ghost"]) == 1
    assert "No account" in capsys.readouterr().err
    assert app_module.main(["app.py", "assign-owner", "  KID "]) == 0
    assert "Owner assigned to" in capsys.readouterr().out
    assert db.get_user(kid)["role"] == "owner"
    assert db.signup_enabled() is False

    seed_user("later", TESTER_PASSWORD)
    assert app_module.main(["app.py", "assign-owner", "later"]) == 1
    assert "already has an owner" in capsys.readouterr().err
    assert app_module.main(["app.py", "assign-owner"]) == 2
    assert "usage:" in capsys.readouterr().err.lower()
    assert app_module.main(["app.py", "assign-owner", "   "]) == 2
    assert "usage:" in capsys.readouterr().err.lower()


def test_rotate_session_secret_cli_requires_restart_message(
        fresh_db, capsys):
    before = db.get_setting("secret_key")
    assert app_module.main(["app.py", "rotate-session-secret"]) == 0
    after = db.get_setting("secret_key")
    assert after and after != before
    output = capsys.readouterr().out
    assert "Restart the server" in output
    assert after not in output
    assert app_module.main(
        ["app.py", "rotate-session-secret", "extra"]) == 2


def test_dev_server_host_and_debug_follow_the_environment(monkeypatch):
    booted = []
    monkeypatch.setattr(sys, "argv", ["app.py"])
    monkeypatch.setattr(app_module.app, "run",
                        lambda **options: booted.append(options))
    monkeypatch.setenv("PORTFOLIARR_DEBUG", "1")
    assert app_module.main(None) == 0
    assert booted[-1] == {"debug": True, "host": "127.0.0.1"}

    for value in ("true", "TRUE", "yes", "0", ""):
        monkeypatch.setenv("PORTFOLIARR_DEBUG", value)
        assert app_module.main(None) == 0
        assert booted[-1] == {"debug": False, "host": "127.0.0.1"}


def test_password_change_stale_cas_answers_401(client, monkeypatch):
    monkeypatch.setattr(db, "set_password_and_bump",
                        lambda *args, **kwargs: "stale")
    response = client.post("/api/auth/password", json={
        "current_password": TESTER_PASSWORD,
        "new_password": "brand-new-key-1"})
    assert response.status_code == 401
    assert response.get_json() == {"error": "session expired"}
    assert client.get("/api/watchlist").status_code == 401


def test_setup_stamps_the_committed_tuple(fresh_db, monkeypatch):
    monkeypatch.setattr(db, "create_first_user",
                        lambda username, password_hash: (42, 7))
    web_client = browser()
    assert web_client.post("/auth/setup", data={
        "username": "owner", "password": "owner-pass-1",
        "confirm_password": "owner-pass-1"}).status_code == 302
    with web_client.session_transaction() as session:
        assert (session["user_id"], session["pv"]) == (42, 7)


def test_signup_stamps_the_committed_tuple(fresh_db, monkeypatch):
    db.create_first_user("owner", generate_password_hash(TESTER_PASSWORD))
    db.set_setting("allow_signup", "true")
    monkeypatch.setattr(db, "create_signup_user_if_allowed",
                        lambda username, password_hash: (42, 7))
    web_client = browser()
    assert web_client.post("/auth/signup", data={
        "username": "neu", "password": "pw-key-9",
        "confirm_password": "pw-key-9"}).status_code == 302
    with web_client.session_transaction() as session:
        assert (session["user_id"], session["pv"]) == (42, 7)
