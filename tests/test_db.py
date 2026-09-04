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
#   - the update contract: user-typed fields + the date-derived fx_rate
#     may change; ticker/currency (identity + its yfinance fact) must not

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
    transaction_type) — the route layer translates browser keys to these.
    fx_rate is the currency fact derived from the transaction's DATE (the
    USDCAD close that day); CAD rows store 1.0, pre-feature USD rows NULL."""
    tx_id = db.add_transaction(
        ticker="AAPL", transaction_date="2026-08-31",
        price=229.5, qty=10, currency="USD", transaction_type="BUY",
        fx_rate=1.3821,
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
        "fx_rate": 1.3821,
    }


def test_transactions_read_newest_first(fresh_db):
    """The ledger is read like a bank statement: newest event first.
    Sort key is (transaction_date DESC, id DESC) — same-day rows keep
    insertion order, reversed."""
    db.add_transaction("AAPL", "2026-08-01", 100.0, 1, "USD", "BUY", 1.40)
    db.add_transaction("MSFT", "2026-08-31", 200.0, 1, "USD", "BUY", 1.39)
    db.add_transaction("TSLA", "2026-08-31", 300.0, 1, "USD", "BUY", 1.39)
    tickers = [row["ticker"] for row in db.get_transactions()]
    assert tickers == ["TSLA", "MSFT", "AAPL"]


def test_get_transaction_missing_id_returns_none(fresh_db):
    """Unknown id → None (not a crash) — routes rely on this for their
    404-before-validation check."""
    assert db.get_transaction(999) is None


# ── Migration: the fx_rate column on pre-feature databases ───────────

def test_init_migrates_legacy_ledger_and_backfills_cad(tmp_path, monkeypatch):
    """A database created BEFORE fx_rate existed must come out of init()
    with the new column present, CAD rows backfilled to 1.0 (the true
    rate — no conversion ever needed), and USD rows left NULL ("rate
    unknown — display falls back to the live rate"). init() runs on every
    startup, so the migration must be idempotent too."""
    legacy_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", legacy_path)

    # Build the OLD schema by hand: the pre-feature transactions table.
    with sqlite3.connect(legacy_path) as conn:
        conn.execute(
            """
            CREATE TABLE transactions (
                id               INTEGER PRIMARY KEY,
                ticker           TEXT NOT NULL,
                transaction_date TEXT NOT NULL,
                price            REAL NOT NULL,
                qty              REAL NOT NULL,
                currency         TEXT NOT NULL,
                transaction_type TEXT NOT NULL
                    CHECK (transaction_type IN ('BUY', 'SELL'))
            )
            """
        )
        conn.execute(
            "INSERT INTO transactions"
            " (ticker, transaction_date, price, qty, currency,"
            "  transaction_type)"
            " VALUES ('AAPL', '2026-01-15', 100.0, 2, 'USD', 'BUY')"
        )
        conn.execute(
            "INSERT INTO transactions"
            " (ticker, transaction_date, price, qty, currency,"
            "  transaction_type)"
            " VALUES ('RY.TO', '2026-01-20', 50.0, 3, 'CAD', 'BUY')"
        )

    db.init()  # the migration under test
    db.init()  # ...and it must survive a second run (idempotent)

    by_ticker = {row["ticker"]: row for row in db.get_transactions()}
    assert by_ticker["AAPL"]["fx_rate"] is None   # unknown → live fallback
    assert by_ticker["RY.TO"]["fx_rate"] == 1.0   # the true CAD "rate"


# ── Transactions: update ──────────────────────────────────────────────

def test_update_changes_user_fields_and_the_date_derived_fx_rate(fresh_db):
    """THE edit contract, evolved: PUT rewrites what the user typed —
    date, price, qty, type — plus fx_rate, which is a yfinance fact but
    DERIVED FROM THE DATE: when the user corrects the date, a stale rate
    would be a wrong fact, so fx_rate travels with the date (the one
    documented exception). Ticker (identity) and currency (the yfinance
    fact derived from IT) still can never move."""
    tx_id = db.add_transaction("AAPL", "2026-08-01", 100.0, 5, "USD", "BUY",
                               1.40)
    assert db.update_transaction(tx_id, "2026-08-02", 110.0, 7, "SELL",
                                 1.39) is True
    row = db.get_transaction(tx_id)
    # The user-typed fields DID change...
    assert row["transaction_date"] == "2026-08-02"
    assert row["price"] == 110.0
    assert row["qty"] == 7
    assert row["transaction_type"] == "SELL"
    # ...the date-derived fact followed the date...
    assert row["fx_rate"] == 1.39
    # ...and the two protected fields DID NOT.
    assert row["ticker"] == "AAPL"
    assert row["currency"] == "USD"


def test_update_missing_id_returns_false(fresh_db):
    """rowcount 0 → False — the route turns that into a 404."""
    assert db.update_transaction(999, "2026-08-02", 1.0, 1, "BUY",
                                 1.0) is False


# ── Transactions: delete ──────────────────────────────────────────────

def test_delete_reports_whether_it_deleted(fresh_db):
    """True on the real delete, False on the repeat (double-click case:
    route turns the second one into a 404, and the UI refreshes anyway)."""
    tx_id = db.add_transaction("AAPL", "2026-08-31", 229.5, 10, "USD", "BUY",
                               1.39)
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
        db.add_transaction("AAPL", "2026-08-31", 100.0, 1, "USD", "HOLD",
                           1.39)


# ── Fresh-checkout self-healing ───────────────────────────────────────

def test_init_creates_missing_instance_directory(tmp_path, monkeypatch):
    """A fresh checkout has NO instance/ directory (it's gitignored) — and
    sqlite3.connect() creates the DB file but not the folders above it, so
    db.init() used to crash there with "unable to open database file".
    CI's very first run hit exactly this. _connect() now mkdirs the parent
    on demand; this test recreates the CI situation to keep it fixed:
    DB_PATH pointed inside a directory that doesn't exist yet."""
    fresh_path = tmp_path / "brand_new_dir" / "portfolio.db"
    assert not fresh_path.parent.exists()  # the fresh-checkout condition
    monkeypatch.setattr(db, "DB_PATH", fresh_path)
    db.init()  # used to raise sqlite3.OperationalError
    assert fresh_path.exists()
    # The schema is real and usable, not just a file on disk.
    tx_id = db.add_transaction("AAPL", "2026-08-31", 229.5, 10, "USD",
                               "BUY", 1.39)
    assert db.get_transaction(tx_id) is not None
