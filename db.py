"""SQLite persistence layer.

Stores two things: the watchlist symbol list, and the transaction ledger
(every BUY/SELL the user records).

The ledger's design rule: store IMMUTABLE FACTS ONLY. Any value that
depends on the live market price (total value, gain $/%) would freeze
stale the moment it was stored, so those are computed at display time
from live quotes instead — never written here.

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
    """Create every table this app needs, if it doesn't already exist.

    CREATE TABLE IF NOT EXISTS is idempotent — safe to run on every startup.
    """
    with _connect() as conn:
        # `with conn:` commits the change if the block succeeds and rolls
        # back on error — same idea as a transaction in any database.

        # The watchlist table is deliberately tiny: the symbol IS the
        # identity, and making it the PRIMARY KEY means the database itself
        # rejects duplicates (a second line of defence behind the 409 check
        # in the route).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY
            )
            """
        )

        # The transaction ledger. Stores IMMUTABLE FACTS ONLY — nothing that
        # depends on a live market price (such values would freeze stale the
        # moment they were stored). Each column's type choice:
        #
        #   id               SQLite convention: INTEGER PRIMARY KEY is an
        #                    alias for the hidden rowid, so it auto-numbers
        #                    itself (1, 2, 3, ...) with no extra keyword.
        #   ticker           TEXT — same canonical UPPERCASE form everywhere.
        #   transaction_date SQLite has no DATE type. We store ISO text
        #                    ("2026-08-31"), which sorts lexicographically —
        #                    and for ISO dates that IS chronological order.
        #   price / qty      REAL (floating point). REAL for qty too, so
        #                    fractional shares and crypto amounts work.
        #   currency         The security's TRADING currency ("USD", "CAD"),
        #                    auto-filled by the route layer from yfinance.
        #   fx_rate          The USD→CAD conversion rate ON THE
        #                    TRANSACTION'S DATE (the USDCAD=X close that
        #                    day), auto-derived by the route layer from
        #                    yfinance — a historical FACT, stored once
        #                    and never recomputed. CAD rows store 1.0;
        #                    NULL means "rate unknown" (pre-feature rows,
        #                    or Yahoo couldn't answer) and display falls
        #                    back to the live rate. Nullable on purpose:
        #                    a missing fact must not block a real one.
        #   transaction_type The CHECK constraint is a second line of
        #                    defence behind route validation: the database
        #                    itself refuses anything that isn't BUY or SELL.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id               INTEGER PRIMARY KEY,
                ticker           TEXT NOT NULL,
                transaction_date TEXT NOT NULL,
                price            REAL NOT NULL,
                qty              REAL NOT NULL,
                currency         TEXT NOT NULL,
                fx_rate          REAL,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('BUY', 'SELL'))
            )
            """
        )

        # Migration for databases created BEFORE fx_rate existed (the
        # feature shipped after the first ledger did). CREATE TABLE IF
        # NOT EXISTS won't add a column to an existing table, so we ask
        # the table what it has (PRAGMA table_info) and ALTER only when
        # the column is missing — which makes this idempotent, like
        # every other part of init(). New databases already have the
        # column and skip the ALTER entirely.
        columns = {
            row[1]  # PRAGMA table_info rows: (cid, name, type, notnull, dflt_value, pk)
            for row in conn.execute(
                "PRAGMA table_info(transactions)"
            ).fetchall()
        }
        if "fx_rate" not in columns:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN fx_rate REAL"
            )

        # Backfill what migration CAN know: a CAD row needs no conversion
        # (the rate is exactly 1.0 — a true fact, not a guess). USD rows
        # from before the feature keep NULL: we genuinely don't know what
        # the rate was on their dates, and inventing one now would bake a
        # lie into the facts table. Display falls back to the live rate
        # for them; editing a row backfills its real date-based fact.
        conn.execute(
            "UPDATE transactions SET fx_rate = 1.0"
            " WHERE currency = 'CAD' AND fx_rate IS NULL"
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


# ---------------------------------------------------------------------------
# TRANSACTION LEDGER — the facts table. add stores what happened; get
# returns those facts untouched; update corrects the user-typed facts plus
# the date-derived fx_rate (ticker/currency excluded from its SET list by
# design); delete removes a row for good. Any price-dependent value (gain,
# current value) is computed elsewhere, from live quotes — never stored.
# ---------------------------------------------------------------------------

def add_transaction(ticker, transaction_date, price, qty, currency,
                    transaction_type, fx_rate):
    """Insert one BUY or SELL row. Returns the new row's auto-numbered id.

    Validation has already happened in the route layer (fields checked,
    ticker proven real, currency + fx_rate fetched from Yahoo) — this
    function is the dumb, trusted writer. fx_rate arrives EXPLICITLY
    (no default): it is an immutable fact like the price itself, and a
    silent default could only ever invent one. CAD rows carry 1.0; USD
    rows carry the transaction date's USDCAD close (or None when Yahoo
    couldn't answer — the display layer's cue to fall back). If the route
    slipped a bad transaction_type past its checks, the table's CHECK
    constraint raises IntegrityError here: defence in depth means BOTH
    layers would have to fail.

    Same ? placeholder rule as add_symbol: values travel separately from
    SQL text, so even hostile input is inert data, never executable SQL.
    """
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transactions
                (ticker, transaction_date, price, qty, currency, fx_rate,
                 transaction_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, transaction_date, price, qty, currency, fx_rate,
             transaction_type),
        )
        # lastrowid: the id SQLite just assigned to THIS insert. Telling the
        # caller which row was created makes the route's 201 response more
        # useful (and makes future edit/delete routes possible).
        return cursor.lastrowid


def get_transactions():
    """Return every transaction, newest first, as a list of plain dicts.

    Newest first because a ledger is read like a bank statement: the most
    recent event is what you check first. Two keys sort it — transaction_date
    first (the day it happened), then id (the order rows were inserted that
    day, since later ids were inserted later).

    sqlite3.Row is a row wrapper that behaves like a tuple BUT remembers its
    column names. dict(row) then turns each row into {"ticker": "AAPL", ...}
    — exactly the shape jsonify needs. Setting row_factory on the connection
    switches every fetch from that connection to Row objects.
    """
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, ticker, transaction_date, price, qty, currency,
                   fx_rate, transaction_type
            FROM transactions
            ORDER BY transaction_date DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_transaction(tx_id):
    """Return ONE transaction as a dict, or None if that id doesn't exist.

    Routes use this for the 404-before-validation check: when a PUT/DELETE
    names an id, "no transaction with that id" is the most useful error —
    far better than validating fields for a row that was never there.
    Same SELECT shape as get_transactions, narrowed to one id.
    """
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, ticker, transaction_date, price, qty, currency,
                   fx_rate, transaction_type
            FROM transactions
            WHERE id = ?
            """,
            (tx_id,),
        ).fetchone()
    return dict(row) if row else None


def update_transaction(tx_id, transaction_date, price, qty, transaction_type,
                       fx_rate):
    """Correct the user-editable facts of one transaction.

    The SET list names FIVE columns — date, price, qty, type, fx_rate.
    Ticker and currency are deliberately ABSENT: the ticker is the row's
    identity, and currency is the yfinance fact derived from it at insert
    time. fx_rate IS yfinance-derived too, but it derives from the DATE —
    so when the user corrects the date, a stale rate would be a wrong
    fact, and fx_rate travels with the date (the one documented
    exception). Excluding ticker/currency from the SQL itself (not just
    the route) means no future caller of this function can accidentally
    rewrite either.

    Validation has already happened in the route layer (same rules as
    logging a new transaction — they share one helper). Returns True if a
    row was actually updated, False if the id doesn't exist (rowcount 0),
    which the route turns into a 404.
    """
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE transactions
            SET transaction_date = ?, price = ?, qty = ?, transaction_type = ?,
                fx_rate = ?
            WHERE id = ?
            """,
            (transaction_date, price, qty, transaction_type, fx_rate, tx_id),
        )
        return cursor.rowcount > 0


def delete_transaction(tx_id):
    """Remove one transaction permanently. Returns True if a row was
    actually deleted, False if the id doesn't exist (route turns that
    into a 404 — e.g. a second DELETE after the first one succeeded).

    Deletion is IMMEDIATE and unrecoverable: this is the immutable-facts
    table's one destructive verb, which is exactly why the UI gates it
    behind a confirm() dialog.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ?", (tx_id,)
        )
        return cursor.rowcount > 0
