# tests/test_security_audit.py — home-LAN hardening contract.
import time

import app as app_module
from app import app
import db
from conftest import seed_user, TESTER_PASSWORD


def browser():
    return app.test_client()


def login(web_client, username, password):
    return web_client.post("/auth/login", data={
        "username": username, "password": password})


# T1 password length 8
def test_setup_rejects_7_char_password(fresh_db):
    r = browser().post("/auth/setup", data={
        "username": "amy", "password": "Abc1234",
        "confirm_password": "Abc1234"})
    assert r.status_code == 400
    assert "8 to 128" in r.get_data(as_text=True)


def test_setup_accepts_8_char_password(fresh_db):
    r = browser().post("/auth/setup", data={
        "username": "amy", "password": "Abc12345",
        "confirm_password": "Abc12345"})
    assert r.status_code == 302


def test_create_user_api_rejects_short(client):
    r = client.post("/api/users", json={
        "username": "bob", "password": "short77"})
    assert r.status_code == 400


def test_change_password_rejects_short(client):
    r = client.post("/api/auth/password", json={
        "current_password": TESTER_PASSWORD, "new_password": "short77"})
    assert r.status_code == 400


def test_password_reset_rejects_short(fresh_db):
    seed_user("amy", "long-password-1234")
    ok, msg = app_module.perform_password_reset("amy", "short77")
    assert ok is False
    assert "8 to 128" in msg


# T2 throttle
def test_login_throttle_after_10_fails(fresh_db, monkeypatch):
    monkeypatch.setattr(app_module, "_LOGIN_WINDOW_S", 60)
    app_module._LOGIN_FAILS.clear()
    seed_user("amy", "long-password-1234")
    web = browser()
    for _ in range(10):
        r = web.post("/auth/login", data={
            "username": "amy", "password": "wrong-password"},
            environ_overrides={"REMOTE_ADDR": "10.0.0.9"})
        assert r.status_code == 400
    r = web.post("/auth/login", data={
        "username": "amy", "password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "10.0.0.9"})
    assert r.status_code == 429
    # other IP not blocked
    r2 = web.post("/auth/login", data={
        "username": "amy", "password": "wrong-password"},
        environ_overrides={"REMOTE_ADDR": "10.0.0.10"})
    assert r2.status_code == 400


# T3 session invalidate
def test_password_change_invalidates_other_session(client):
    seed_user("second", "second-password-1234")
    second = app.test_client()
    assert login(second, "second", "second-password-1234").status_code == 302
    # second client works
    assert second.get("/api/portfolios").status_code == 200
    # tester changes own password; second session must keep working
    # (only own other sessions die). Now test tester second session:
    tester_b = app.test_client()
    assert login(tester_b, "tester", TESTER_PASSWORD).status_code == 302
    assert tester_b.get("/api/portfolios").status_code == 200
    r = client.post("/api/auth/password", json={
        "current_password": TESTER_PASSWORD,
        "new_password": "brand-new-password-1234"})
    assert r.status_code == 204
    # first client stays alive
    assert client.get("/api/portfolios").status_code == 200
    # second tester session is dead
    after = tester_b.get("/api/portfolios")
    assert after.status_code in (302, 401)


# T4/T5 meta-tests
def test_stock_js_allowlists_website_scheme():
    text = open("static/js/stock.js").read()
    assert 'startsWith("http://")' in text
    assert 'startsWith("https://")' in text


def test_main_js_uses_css_escape():
    text = open("static/js/main.js").read()
    assert "CSS.escape(" in text


# T6 headers
def test_security_headers_present(client):
    r = client.get("/api/portfolios")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    assert "X-Request-ID" in r.headers


# T7 IDOR regression
def test_other_user_portfolio_is_404(client, fake_market):
    from conftest import CLIENT_USER_ID
    pid = db.get_portfolios(CLIENT_USER_ID)[0]["id"]
    seed_user("bob", "bob-password-1234")
    bob = app.test_client()
    assert login(bob, "bob", "bob-password-1234").status_code == 302
    assert bob.get(
        f"/api/portfolio/summary?portfolio_id={pid}").status_code == 404
    assert bob.get(
        f"/api/transactions?portfolio_id={pid}").status_code == 404


# T8 docker
def test_dockerfile_has_healthcheck():
    text = open("Dockerfile").read()
    assert "HEALTHCHECK" in text


# T9 android static checks
def test_android_hardening():
    # Cleartext stays globally permitted by the manifest (plain-HTTP LAN
    # server); scoping happens in-app via URL validation, because
    # <domain> entries cannot express IP ranges.
    manifest = open(
        "android/app/src/main/AndroidManifest.xml").read()
    assert 'usesCleartextTraffic="true"' in manifest
    main = open(
        "android/app/src/main/java/com/portfoliarr/app/MainActivity.kt"
    ).read()
    assert "allowFileAccess = false" in main
    assert "allowContentAccess = false" in main
    assert "isAllowedUrl" in main
    settings = open(
        "android/app/src/main/java/com/portfoliarr/app/SettingsActivity.kt"
    ).read()
    assert "http://" in settings
    assert "javascript:" in settings.lower()
