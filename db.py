"""SQLite persistence layer.

Currently stores exactly one thing: the watchlist symbol list. It will grow
to hold the transaction ledger later.

This module knows nothing about Flask or yfinance — routes decide WHAT the
data means; this file only knows HOW to store and retrieve rows.

The database file lives in instance/ (gitignored, per Flask convention) so
data survives dev-server restarts — unlike the in-memory quote cache, which
is deliberately disposable.
"""

# pathlib's Path is the modern way to build filesystem paths (no manual
# string joining with "/", no platform-specific separators to worry about).
from pathlib import Path

# sqlite3 is part of Python's standard library — no pip install needed.
# It talks to a self-contained database file on disk.
import sqlite3

# Resolve the database path relative to THIS file, not the current working
# directory. That way the app finds its data no matter where you launch
# `python app.py` from.
DB_PATH = Path(__file__).resolve().parent / "instance" / "portfolio.db"


def _connect():
    """Open a fresh connection to the database file.

    One short-lived connection per operation is the simplest safe pattern:
    SQLite handles file locking for us, and we never share a connection
    across threads (Flask's dev server can serve requests on several).
    """
    return sqlite3.connect(DB_PATH)


def init():
    """Create the watchlist table if it doesn't already exist.

    CREATE TABLE IF NOT EXISTS is idempotent — safe to run on every startup.
    The table is deliberately tiny: the symbol IS the identity, and making it
    the PRIMARY KEY means the database itself rejects duplicates (a second
    line of defence behind the 409 check in the route).
    """
    with _connect() as conn:
        # `with conn:` commits the change if the block succeeds and rolls
        # back on error — same idea as a transaction in any database.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY
            )
            """
        )


def get_symbols():
    """Return the watchlist as a list of symbol strings, in insertion order.

    Every SQLite table has a hidden `rowid` that counts up as rows are
    inserted, so ORDER BY rowid = "oldest watchlist entry first" — a stable,
    meaningful order without storing an extra timestamp column.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist ORDER BY rowid"
        ).fetchall()
    # fetchall() returns a list of one-value tuples: [("AAPL",), ("MSFT",)].
    # Unpack each tuple to get the plain string out.
    return [row[0] for row in rows]


def add_symbol(symbol):
    """Insert a symbol. Raises sqlite3.IntegrityError if it already exists
    (PRIMARY KEY violation) — the route layer turns that into a 409."""
    with _connect() as conn:
        # The ? placeholder passes the value SEPARATELY from the SQL text,
        # so the database engine treats it as data only. Building SQL by
        # string formatting would let a crafted symbol execute extra SQL —
        # the classic "SQL injection" hole. Always parameterize.
        conn.execute(
            "INSERT INTO watchlist (symbol) VALUES (?)", (symbol,)
        )


def remove_symbol(symbol):
    """Delete a symbol's row. Returns True if a row was actually removed,
    False if the symbol wasn't in the watchlist (route turns that into 404).

    cursor.rowcount reports how many rows the last statement touched.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE symbol = ?", (symbol,)
        )
        return cursor.rowcount > 0
