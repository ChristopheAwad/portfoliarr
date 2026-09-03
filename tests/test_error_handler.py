# tests/test_error_handler.py
# ===========================
# Tests for the TIER 2 top-level error handler (app.py) — the safety net
# that turns unhandled BUGS into a JSON 500 instead of Flask's default
# HTML error page.
#
# THE CONCEPT THIS FILE ISOLATES: an "unhandled" exception is one that
# escapes a route WITHOUT the route's own try/except. We manufacture one
# by monkeypatching a db helper to raise — patch WHERE IT'S USED: routes
# reach db.get_symbols through the db module object, so patching the
# module attribute reroutes every caller (the golden rule from
# test_routes.py, applied to a module instead of an imported name).
#
# WHY PROPAGATE_EXCEPTIONS MATTERS: Flask re-raises unhandled exceptions
# (letting the test runner / debugger see them) instead of running error
# handlers when testing or debug mode is on. Our handler is the
# PRODUCTION path, so the test pins PROPAGATE_EXCEPTIONS = False to
# reproduce production behavior deterministically. monkeypatch restores
# the old value afterwards — tests can't leak config into each other.

import db

# NAME-COLLISION RULE (see test_routes.py): `from app import app` hands us
# the Flask INSTANCE; `import app as app_module` hands us the module, whose
# namespace is where patching works.
import app as app_module


def test_unhandled_exception_becomes_json_500(client, monkeypatch):
    """A genuine bug (RuntimeError escaping a route) -> JSON 500."""
    # Production mode: don't re-raise, run the error handlers.
    monkeypatch.setitem(
        app_module.app.config, "PROPAGATE_EXCEPTIONS", False
    )

    def broken_get_symbols():
        raise RuntimeError("simulated bug — deliberately not an HTTP error")

    monkeypatch.setattr(db, "get_symbols", broken_get_symbols)

    # GET /api/watchlist calls db.get_symbols() OUTSIDE any try/except,
    # so the RuntimeError escapes the route and reaches the handler.
    response = client.get("/api/watchlist")

    assert response.status_code == 500
    assert response.get_json() == {"error": "internal server error"}


def test_http_errors_are_not_relabelled_as_500(client):
    """The handler must NOT swallow Flask's own HTTP errors: a 404 from a
    typo'd URL stays a 404 (isinstance guard passes it through)."""
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404
