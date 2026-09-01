# tests/test_db.py
# =================
# Unit tests for db.py — the SQLite persistence layer.
#
# THE NEW CONCEPT IN THIS FILE: testing real I/O safely.
#   db.py is NOT a pure function like validate_tx_fields — it reads and
#   writes a file on disk. The trick is the `fresh_db` fixture (conftest.py):
#   it points db.DB_PATH at a throwaway file in a temp directory, so every
#   test gets a virgin database and the real instance/portfolio.db is never
#   touched. Arrange → Act → Assert still applies, but "Arrange" now means
#   "seed known rows through the layer's own functions".
#
# WHAT'S WORTH TESTING HERE?
#   Not SQL syntax — the behaviour we depend on:
#   - round-trips (what we store is what we read back, under the SAME keys)
#   - ordering guarantees the UI relies on (watchlist insertion order,
#     ledger newest-first)
#   - the database as a SECOND LINE OF DEFENCE: PRIMARY KEY and CHECK
#     constraints reject what routes should never let through
#   - the update-only-four-fields contract (AGENTS.md): ticker/currency
#     are identity + a yfinance fact, and the SQL itself must not touch them

import sqlite3

import pytest

import db


# ── init ──────────────────────────────────────────────────────────────

def test_init_is_idempotent(fresh_db):
    """init() runs on every server startup — calling it twice (import
    time + restart) must be harmless, thanks to CREATE TABLE IF NOT EXISTS."""
    db.init()
    db.init()  # no exception = pass


# ── Watchlist ─────────────────────────────────────────────────────────

def test_watchlist_round_trip_preserves_insertion_order(fresh_db):
    """get_symbols() returns oldest-first — the UI's stable row order."""
    db.add_symbol("MSFT")
    db.add_symbol("AAPL")
    db.add_symbol("BTC-USD")
    assert db.get_symbols() == ["MSFT", "AAPL", "BTC-USD"]


def test_watchlist_duplicate_rejected_by_primary_key(fresh_db):
    """The symbol IS the primary key, so the DATABASE rejects duplicates
    (sqlite3.IntegrityError) — the route translates that into a 409.
    Testing the raw raise proves the constraint exists at this layer,
    independent of any route code."""
    db.add_symbol("AAPL")
    with pytest.raises(sqlite3.IntegrityError):
        db.add_symbol("AAPL")


def test_watchlist_remove_reports_whether_it_deleted(fresh_db):
    """remove_symbol returns True if a row was really removed, False if
    the symbol wasn't there — the route turns False into a 404."""
    db.add_symbol("AAPL")
    assert db.remove_symbol("AAPL") is True
    assert db.remove_symbol("AAPL") is False   # already gone
    assert db.get_symbols() == []


# ── Transactions: write & read ────────────────────────────────────────

def test_transaction_round_trip(fresh_db):
    """Store one row, read it back: same values, SAME COLUMN NAMES.
    The dict keys are the DB's explicit vocabulary (transaction_date,
    transaction_type) — the route layer translates browser keys to these."""
    tx_id = db.add_transaction(
        ticker="AAPL", transaction_date="2026-08-31",
        price=229.5, qty=10, currency="USD", transaction_type="BUY",
    )
    # lastrowid: SQLite hands back the auto-numbered id of THIS insert.
    assert isinstance(tx_id, int)
    assert db.get_transaction(tx_id) == {
        "id": tx_id,
        "ticker": "AAPL",
        "transaction_date": "2026-08-31",
        "price": 229.5,
        "qty": 10,
        "currency": "USD",
        "transaction_type": "BUY",
    }


def test_transactions_read_newest_first(fresh_db):
    """The ledger is read like a bank statement: newest event first.
    Sort key is (transaction_date DESC, id DESC) — same-day rows keep
    insertion order, reversed."""
    db.add_transaction("AAPL", "2026-08-01", 100.0, 1, "USD", "BUY")
    db.add_transaction("MSFT", "2026-08-31", 200.0, 1, "USD", "BUY")
    db.add_transaction("TSLA", "2026-08-31", 300.0, 1, "USD", "BUY")
    tickers = [row["ticker"] for row in db.get_transactions()]
    assert tickers == ["TSLA", "MSFT", "AAPL"]


def test_get_transaction_missing_id_returns_none(fresh_db):
    """Unknown id → None (not a crash) — routes rely on this for their
    404-before-validation check."""
    assert db.get_transaction(999) is None


# ── Transactions: update ──────────────────────────────────────────────

def test_update_changes_only_the_four_editable_fields(fresh_db):
    """THE edit contract (AGENTS.md): PUT rewrites what the user typed —
    date, price, qty, type — and can never touch ticker (identity) or
    currency (the yfinance fact derived from it). The SET list in the SQL
    enforces this; this test proves it holds at the data layer itself."""
    tx_id = db.add_transaction("AAPL", "2026-08-01", 100.0, 5, "USD", "BUY")
    assert db.update_transaction(tx_id, "2026-08-02", 110.0, 7, "SELL") is True
    row = db.get_transaction(tx_id)
    # The four user-typed fields DID change...
    assert row["transaction_date"] == "2026-08-02"
    assert row["price"] == 110.0
    assert row["qty"] == 7
    assert row["transaction_type"] == "SELL"
    # ...and the two protected fields DID NOT.
    assert row["ticker"] == "AAPL"
    assert row["currency"] == "USD"


def test_update_missing_id_returns_false(fresh_db):
    """rowcount 0 → False — the route turns that into a 404."""
    assert db.update_transaction(999, "2026-08-02", 1.0, 1, "BUY") is False


# ── Transactions: delete ──────────────────────────────────────────────

def test_delete_reports_whether_it_deleted(fresh_db):
    """True on the real delete, False on the repeat (double-click case:
    route turns the second one into a 404, and the UI refreshes anyway)."""
    tx_id = db.add_transaction("AAPL", "2026-08-31", 229.5, 10, "USD", "BUY")
    assert db.delete_transaction(tx_id) is True
    assert db.delete_transaction(tx_id) is False
    assert db.get_transaction(tx_id) is None


# ── Transactions: defence in depth ────────────────────────────────────

def test_check_constraint_rejects_bad_transaction_type(fresh_db):
    """If the route's validation ever slipped a non-BUY/SELL type through,
    the table's CHECK constraint raises IntegrityError here — two layers
    must BOTH fail before bad data lands. This test proves layer two works
    even though layer one (validate_tx_fields) is what we normally trust."""
    with pytest.raises(sqlite3.IntegrityError):
        db.add_transaction("AAPL", "2026-08-31", 100.0, 1, "USD", "HOLD")
