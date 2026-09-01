# tests/test_validate_tx_fields.py
# ================================
# Unit tests for validate_tx_fields (app.py:322).
#
# WHY THIS FUNCTION?
#   It's the best first-test candidate: a pure input → output function with
#   zero external dependencies (no DB, no network).  It IS the shared
#   validator for BOTH POST (log) and PUT (edit) — locking its behaviour
#   with tests means the two routes can never drift apart silently.
#
# THE FLASK "APPLICATION CONTEXT" GOTCHA
#   Every *error* path inside validate_tx_fields calls json.dumps() via
#   Flask's jsonify().  jsonify() requires an active Flask application
#   context — calling it bare raises RuntimeError.  That's a Flask design
#   choice, not a bug: it needs the context to know the current app's
#   config (JSON encoder, etc.).
#
#   Our helper `check()` wraps every call in with app.app_context().
#   That's the "Arrange" step for error tests — it mirrors what Flask
#   does automatically when a real request comes in.
#
# ARRANGE → ACT → ASSERT
#   Every test follows this three-beat pattern:
#     1. Arrange  — build the input (or mock).
#     2. Act      — call the function under test.
#     3. Assert   — check the output matches expectations.
#   This structure is universal in unit testing; once you see it, every
#   test file reads the same way.

import pytest

from app import app, validate_tx_fields


# ── Helper ────────────────────────────────────────────────────────────
# check() performs the ACT step for us, always inside an app context so
# jsonify() doesn't crash.  We call it from every test instead of
# repeating `with app.app_context():` in each one.

def check(body):
    """Call validate_tx_fields inside a Flask application context."""
    with app.app_context():
        return validate_tx_fields(body)


# ── Happy-path tests ──────────────────────────────────────────────────
# These prove the function ACCEPTS valid input and TRANSLATES the keys
# from the browser's short names ("date") to the DB's explicit ones
# ("transaction_date").  That translation is documented in AGENTS.md:
# "POST and PUT share validate_tx_fields".


def test_valid_body_returns_fields():
    """A fully valid body should return a fields dict (no error)."""
    fields, error = check({
        "date": "2026-08-31",
        "price": 150,
        "qty": 10,
        "type": "buy",
    })
    assert error is None
    assert fields == {
        "transaction_date": "2026-08-31",
        "price": 150,
        "qty": 10,
        "transaction_type": "BUY",
    }


def test_type_is_normalized_to_uppercase():
    """lowercase/mixed-case type and extra whitespace must be tolerated."""
    _, error_buy = check({
        "date": "2026-01-01", "price": 10, "qty": 1, "type": "buy",
    })
    _, error_sell = check({
        "date": "2026-01-01", "price": 10, "qty": 1, "type": " sell ",
    })
    assert error_buy is None
    assert error_sell is None


def test_fractional_qty_passes_through():
    """qty can be fractional (crypto, fractional shares)."""
    fields, error = check({
        "date": "2026-01-01", "price": 50000, "qty": 0.001, "type": "buy",
    })
    assert error is None
    assert fields["qty"] == 0.001


# ── Date failures ─────────────────────────────────────────────────────
# date.fromisoformat() is the whole validator — it raises ValueError for
# anything that isn't a real "YYYY-MM-DD" calendar date.  These tests
# prove that the function rejects the three most common mistakes:
# missing entirely, wrong format, and fake dates like Feb 30.


@pytest.mark.parametrize(
    "body, description",
    [
        ({"price": 10, "qty": 1, "type": "buy"},            "missing date"),
        ({"date": "08/31/2026", "price": 10, "qty": 1, "type": "buy"},
                                                            "US-style date"),
        ({"date": "2026-02-30", "price": 10, "qty": 1, "type": "buy"},
                                                            "fake calendar date"),
    ],
    ids=lambda d: d,  # pytest shows the description string, not the dict
)
def test_date_rejects_invalid(body, description):
    """Invalid dates must return a 400 with a YYYY-MM-DD hint."""
    fields, error = check(body)
    assert fields is None
    assert error[1] == 400
    assert "YYYY-MM-DD" in error[0].get_json()["error"]


# ── Price / qty failures ──────────────────────────────────────────────
# The positive_number() helper inside validate_tx_fields rejects
# non-numbers, bools, zero, and negatives.  Each of these has a subtle
# reason — the comments in app.py:346–356 explain them.


def test_rejects_string_price():
    """price must be a JSON number, not a string like "10"."""
    fields, error = check({
        "date": "2026-01-01", "price": "10", "qty": 1, "type": "buy",
    })
    assert fields is None
    assert error[1] == 400
    assert "number" in error[0].get_json()["error"].lower()


def test_rejects_bool_qty():
    """True/False sneak through isinstance(x, int) — the bool-is-int trap.

    In Python, bool is a subclass of int, so True == 1.  Without the
    isinstance(value, bool) guard in app.py:352, qty=True would pass
    validation.  This test locks in that guard permanently.
    """
    fields, error = check({
        "date": "2026-01-01", "price": 10, "qty": True, "type": "buy",
    })
    assert fields is None
    assert error[1] == 400


def test_rejects_zero_qty():
    """qty must be greater than 0 — zero is nonsensical."""
    fields, error = check({
        "date": "2026-01-01", "price": 10, "qty": 0, "type": "buy",
    })
    assert fields is None
    assert error[1] == 400
    assert "greater than 0" in error[0].get_json()["error"].lower()


def test_rejects_negative_price():
    """price must be positive."""
    fields, error = check({
        "date": "2026-01-01", "price": -5, "qty": 1, "type": "buy",
    })
    assert fields is None
    assert error[1] == 400
    assert "greater than 0" in error[0].get_json()["error"].lower()


# ── Type failures ─────────────────────────────────────────────────────
# Only BUY and SELL are ledger verbs.  Anything else — including missing
# — must be rejected.  The database has a CHECK constraint as a second
# line of defence, but the route should catch it first with a clear
# message.


def test_rejects_unknown_type():
    """type must be BUY or SELL — 'HOLD' is not a ledger verb."""
    fields, error = check({
        "date": "2026-01-01", "price": 10, "qty": 1, "type": "HOLD",
    })
    assert fields is None
    assert error[1] == 400
    assert "BUY or SELL" in error[0].get_json()["error"]


def test_rejects_missing_type():
    """Missing type must be rejected, not silently accepted."""
    fields, error = check({
        "date": "2026-01-01", "price": 10, "qty": 1,
    })
    assert fields is None
    assert error[1] == 400
    assert "BUY or SELL" in error[0].get_json()["error"]
