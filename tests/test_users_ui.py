# tests/test_users_ui.py
# ======================
# Source pins for the auth UI (the same "meta-test" idea as
# test_portfolios_ui.py / test_web_refresh_wiring.py): the artifacts carry
# the hooks and helpers that make login/no-JS forms, the People card, and
# the signed-out 401 redirect work together. These cannot prove runtime
# behavior — that is the browser GUI gate's job (plus the route
# assertions in test_auth.py).

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text()


def test_base_carries_user_identity_and_logout():
    html = source("templates/base.html")
    assert "g.user.username" in html
    assert '<form method="post"' in html
    assert "url_for('auth_logout')" in html


def test_preferences_carries_people_section():
    prefs = source("templates/preferences.html")
    for hook in ("people-card", "people-create", "people-list",
                 "password-change", "data-current-uid"):
        assert hook in prefs
    assert "Each person owns only their own portfolios and watchlist" in prefs


def test_preferences_js_wires_people_and_password():
    js = source("static/js/preferences.js")
    for hook in ("/api/users", "/api/auth/password", "showPrompt",
                 "currentUid"):
        assert hook in js


def test_common_hooks_401_redirect():
    common = source("static/js/common.js")
    assert "status === 401" in common
    assert "/auth/" in common


def test_auth_pages_are_no_js_forms():
    for name, password_attr in (("login.html", "current-password"),
                                ("setup.html", "new-password")):
        page = source(f"templates/{name}")
        assert '<form method="post"' in page, name
        assert "<script" not in page, name
        assert password_attr in page, name
    # The two pages share their classes with the stylesheet:
    css = source("static/style.css")
    for style in (".auth-page", ".auth-card", ".auth-form"):
        assert style in css


def test_auth_pages_render_the_brand():
    head = source("templates/_auth_head.html")
    assert "logo-mark" in head
    # The brand card classes live on the shared skeleton's auth card... and
    # the pages select it through the block:
    assert 'class="card auth-card"' in head
    for name in ("login.html", "setup.html"):
        assert '{% extends "_auth_head.html" %}' in source(f"templates/{name}")


def test_changed_page_scripts_parse_in_javascript_engine():
    MiniRacer = pytest.importorskip("py_mini_racer").MiniRacer
    engine = MiniRacer()
    for path in ("static/js/common.js", "static/js/preferences.js"):
        engine.eval("new Function(" + json.dumps(source(path)) + ")")
