# tests/test_users_ui.py
# ======================
# Source and render pins for the auth UI (the same "meta-test" idea as
# test_portfolios_ui.py / test_web_refresh_wiring.py): the artifacts carry
# the hooks and helpers that make login/no-JS forms, the owner-only People
# card, the everyone-owns-password card, and the signed-out 401 redirect
# work together. These cannot prove runtime behavior — that is the browser
# GUI gate's job (plus the route assertions in test_auth.py).

import json
from pathlib import Path

import pytest
from flask import g, render_template

from app import app
from conftest import seed_user, sign_in

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text()


def render(template, role="owner", **context):
    """Render a page template as one role, without touching routes or DB.

    The templates read g.user (a dict, like the real before_request hook
    resolves), so this pins the owner/regular markup split directly.
    """
    with app.test_request_context("/"):
        g.user = {"id": 1, "username": "tester", "role": role}
        return render_template(template, **context)


def text(html):
    """Collapse render whitespace so prose assertions survive templates."""
    return " ".join(html.split())


def js_function(js, signature):
    """Return one IIFE's text: from its signature to the next `})();`."""
    start = js.index(signature)
    end = js.index("\n})();", start)
    return js[start:end]


def test_base_carries_user_identity_and_logout():
    html = source("templates/base.html")
    assert "g.user.username" in html
    assert '<form method="post"' in html
    assert "url_for('auth_logout')" in html


# ── People controls: owner only ────────────────────────────────────────

def test_owner_preferences_carries_people_section():
    html = render("preferences.html", role="owner", app_version="test")
    for hook in ("people-card", "people-create", "people-list",
                 "data-current-uid", "allow-signup"):
        assert hook in html, hook
    assert "Only the owner can add or remove people" in text(html)


def test_regular_preferences_hides_people_controls():
    html = render("preferences.html", role="user", app_version="test")
    for hook in ('id="people-card"', 'id="people-create"',
                 'id="people-list"', 'id="allow-signup"',
                 'id="people-error"', "data-current-uid=\"1\""):
        assert hook not in html, hook
    assert "<h3>People</h3>" not in html


def test_preferences_js_wires_people_and_password():
    js = source("static/js/preferences.js")
    people = js_function(js, "(function managePeople()")
    password = js_function(js, "(function manageOwnPassword()")
    # The owner card wires the People endpoints...
    assert "/api/users" in people
    assert "showPrompt" in people
    assert "currentUid" in people
    # ...and returns BEFORE any fetch when the owner-only card is absent.
    guard = 'const card = document.getElementById("people-card");\n' \
            "    if (!card) return;"
    assert guard in people
    # The password flow lives in its own IIFE, for every role.
    assert "/api/auth/password" in password
    assert "password-change" in password
    assert "/api/users" not in password


def test_regular_password_and_performance_cards_still_render():
    html = render("preferences.html", role="user", app_version="test")
    assert 'id="password-card"' in html
    assert 'id="password-change"' in html
    assert 'id="password-error"' in html
    assert 'id="perf-card"' in html


def test_preferences_route_splits_owner_and_regular_markup(client):
    """The real route reads g.user's role: owner gets People, a regular
    account gets only its own password card (plus Performance)."""
    regular = app.test_client()
    sign_in(regular, seed_user("regular"))

    owner_html = client.get("/preferences").get_data(as_text=True)
    regular_html = regular.get("/preferences").get_data(as_text=True)

    assert 'id="people-card"' in owner_html
    assert 'id="people-card"' not in regular_html
    for hook in ('id="password-card"', 'id="password-change"',
                 'id="password-error"', 'id="perf-card"'):
        assert hook in owner_html, hook
        assert hook in regular_html, hook


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
    for path in ("static/js/common.js", "static/js/preferences.js",
                 "static/js/stock.js"):
        engine.eval("new Function(" + json.dumps(source(path)) + ")")


# ── Sign-up page and owner toggle (roadmap #27) ───────────────────────

def test_login_page_wires_the_signup_link():
    page = source("templates/login.html")
    assert "auth_signup" in page
    assert "Create an account" in page


def test_signup_page_is_a_plain_no_js_form():
    page = source("templates/signup.html")
    assert '<form method="post"' in page
    assert "<script" not in page
    assert 'name="confirm_password"' in page
    assert 'autocomplete="new-password"' in page


def test_preferences_carries_the_signup_switch():
    html = render("preferences.html", role="owner", app_version="test")
    assert 'id="allow-signup"' in html
    assert 'for="allow-signup"' in html


def test_preferences_js_wires_signup_toggle():
    js = source("static/js/preferences.js")
    assert "/api/auth/signup-toggle" in js
    assert ".checked" in js


# ── Shared fund classification: readable for all, owner mutations ─────

def test_owner_stock_classification_has_mutation_controls():
    html = render("stock.html", role="owner", symbol="VEQT.TO",
                  watched=False)
    assert 'data-can-manage="true"' in html
    for hook in ("classification-card", "classification-dimension",
                 "classification-rows", "classification-as-of",
                 "classification-add-row", "classification-save",
                 "classification-clear"):
        assert hook in html, hook


def test_regular_stock_classification_is_read_only_but_visible():
    html = render("stock.html", role="user", symbol="VEQT.TO",
                  watched=False)
    assert 'data-can-manage="false"' in html
    # The shared readable card and its anchor stay for everyone.
    for hook in ("classification-card", "classification-dimension",
                 "classification-rows", "classification-status"):
        assert hook in html, hook
    # No owner mutation controls reach a regular account.
    for hook in ("classification-as-of", "classification-add-row",
                 "classification-save", "classification-clear"):
        assert hook not in html, hook
    assert "entered by the server owner" in text(html)


def test_stock_route_splits_owner_and_regular_markup(client):
    """The real stock route renders the shared card for both roles, but
    only the owner's reply carries the mutation controls."""
    regular = app.test_client()
    sign_in(regular, seed_user("regular"))

    owner_html = client.get("/stock/VEQT.TO").get_data(as_text=True)
    regular_html = regular.get("/stock/VEQT.TO").get_data(as_text=True)

    for html in (owner_html, regular_html):
        assert 'id="classification-card"' in html
        assert 'id="classification-dimension"' in html
        assert 'id="classification-rows"' in html
    assert 'id="classification-save"' in owner_html
    assert 'id="classification-save"' not in regular_html
    assert 'data-can-manage="true"' in owner_html
    assert 'data-can-manage="false"' in regular_html


def test_stock_js_renders_read_only_and_wires_owner_controls_safely():
    js = source("static/js/stock.js")
    assert 'classificationCard?.dataset.canManage === "true"' in js
    assert "labelInput.readOnly = true" in js
    assert "percentInput.readOnly = true" in js
    # Owner-only controls are optional-chained: a regular page has none.
    for hook in ("classification-add-row", "classification-save",
                 "classification-clear"):
        assert f'getElementById("{hook}")?.addEventListener' in js
    assert 'classificationDimEl?.addEventListener("change"' in js
