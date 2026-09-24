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

    The parent directory is created on demand (exist_ok makes this a no-op
    once present). WHY: sqlite3.connect() creates the FILE but not the
    folders leading to it. This machine has instance/ lying around, but a
    fresh checkout — CI, or the Docker image's first boot on a new volume —
    doesn't, and the import-time db.init() crashed on it ("unable to open
    database file"). Self-healing here means the data layer works anywhere,
    with zero setup.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
        conn.execute("""CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL
                CHECK (length(name) BETWEEN 1 AND 60 AND name = trim(name)),
            sort_order INTEGER NOT NULL)""")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS portfolio_name_unique ON portfolios(name COLLATE NOCASE)")
        if not conn.execute("SELECT 1 FROM portfolios LIMIT 1").fetchone():
            conn.execute("INSERT INTO portfolios (name, sort_order) VALUES ('Main', 0)")

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
        #   fee              Optional commission for the whole trade in its
        #                    native currency. NULL means not recorded.
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
                fee              REAL,
                currency         TEXT NOT NULL,
                fx_rate          REAL,
                transaction_type TEXT NOT NULL CHECK (transaction_type IN ('BUY', 'SELL')),
                portfolio_id INTEGER NOT NULL REFERENCES portfolios(id)
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
        if "fee" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN fee REAL")
        if "portfolio_id" not in columns:
            # SQLite cannot add a NOT NULL foreign key to a populated table.
            # Rebuild it in this transaction so a failed copy keeps the old ledger.
            conn.execute("""CREATE TABLE transactions_scoped (
                id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
                transaction_date TEXT NOT NULL, price REAL NOT NULL,
                qty REAL NOT NULL, fee REAL, currency TEXT NOT NULL,
                fx_rate REAL, transaction_type TEXT NOT NULL
                    CHECK (transaction_type IN ('BUY', 'SELL')),
                portfolio_id INTEGER NOT NULL REFERENCES portfolios(id))""")
            main_id = conn.execute("SELECT id FROM portfolios WHERE name = 'Main'").fetchone()[0]
            conn.execute("""INSERT INTO transactions_scoped
                (id, ticker, transaction_date, price, qty, fee, currency,
                 fx_rate, transaction_type, portfolio_id)
                SELECT id, ticker, transaction_date, price, qty, fee, currency,
                       fx_rate, transaction_type, ? FROM transactions""", (main_id,))
            conn.execute("DROP TABLE transactions")
            conn.execute("ALTER TABLE transactions_scoped RENAME TO transactions")
        conn.execute("CREATE INDEX IF NOT EXISTS tx_portfolio_date ON transactions(portfolio_id, transaction_date DESC, id DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS tx_portfolio_ticker ON transactions(portfolio_id, ticker)")

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


def get_portfolios():
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id, name, sort_order FROM portfolios ORDER BY sort_order, id")]


def get_portfolio(portfolio_id):
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, name, sort_order FROM portfolios WHERE id = ?",
                           (portfolio_id,)).fetchone()
        return dict(row) if row else None


def default_portfolio_id():
    with _connect() as conn:
        return conn.execute("SELECT id FROM portfolios ORDER BY sort_order, id LIMIT 1").fetchone()[0]


def create_portfolio(name):
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(row[0].casefold() == name.casefold() for row in
               conn.execute("SELECT name FROM portfolios")):
            raise sqlite3.IntegrityError("portfolio name already exists")
        cursor = conn.execute("INSERT INTO portfolios (name, sort_order) VALUES (?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM portfolios))", (name,))
        return cursor.lastrowid


def rename_portfolio(portfolio_id, name):
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(row[0] != portfolio_id and row[1].casefold() == name.casefold()
               for row in conn.execute("SELECT id, name FROM portfolios")):
            raise sqlite3.IntegrityError("portfolio name already exists")
        return conn.execute("UPDATE portfolios SET name = ? WHERE id = ?",
                            (name, portfolio_id)).rowcount > 0


def move_portfolio(portfolio_id, direction):
    """Swap adjacent display positions in one write transaction."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM portfolios ORDER BY sort_order, id")]
        if portfolio_id not in ids:
            return None
        index = ids.index(portfolio_id)
        neighbor = index + (-1 if direction == "up" else 1)
        if not 0 <= neighbor < len(ids):
            return False
        ids[index], ids[neighbor] = ids[neighbor], ids[index]
        conn.executemany("UPDATE portfolios SET sort_order = ? WHERE id = ?",
                         [(order, pid) for order, pid in enumerate(ids)])
        return True


def delete_portfolio(portfolio_id, confirmation):
    """Return deleted, missing, last, or mismatch; never leave orphan trades."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT name FROM portfolios WHERE id = ?",
                           (portfolio_id,)).fetchone()
        if row is None:
            return "missing"
        if conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 1:
            return "last"
        if confirmation != row[0]:
            return "mismatch"
        conn.execute("DELETE FROM transactions WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
        ids = [r[0] for r in conn.execute("SELECT id FROM portfolios ORDER BY sort_order, id")]
        conn.executemany("UPDATE portfolios SET sort_order = ? WHERE id = ?",
                         [(order, pid) for order, pid in enumerate(ids)])
        return "deleted"


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


def is_watched(symbol):
    """Membership check: is this exact symbol on the watchlist?

    Deliberately an EXACT match (no strip/upper here) — normalizing is the
    route layer's job (it does it for add/remove too), and a silent
    normalization here would let a sloppy caller keep passing unnormalized
    symbols that only *happen* to work for uppercase input. The stock page
    route calls this at render time to stamp the watch button's initial
    state, so the page knows it's watched before any JavaScript runs.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol = ? LIMIT 1", (symbol,)
        ).fetchone()
    return row is not None


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
                    transaction_type, fx_rate, fee=None, portfolio_id=None):
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
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transactions
                (ticker, transaction_date, price, qty, currency, fx_rate,
                  transaction_type, fee, portfolio_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (ticker, transaction_date, price, qty, currency, fx_rate,
              transaction_type, fee, portfolio_id),
        )
        # lastrowid: the id SQLite just assigned to THIS insert. Telling the
        # caller which row was created makes the route's 201 response more
        # useful (and makes future edit/delete routes possible).
        return cursor.lastrowid


def get_transactions(portfolio_id=None):
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
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, ticker, transaction_date, price, qty, currency,
                    fx_rate, transaction_type, fee, portfolio_id
            FROM transactions
            WHERE portfolio_id = ?
            ORDER BY transaction_date DESC, id DESC
            """, (portfolio_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_transaction(tx_id, portfolio_id=None):
    """Return ONE transaction as a dict, or None if that id doesn't exist.

    Routes use this for the 404-before-validation check: when a PUT/DELETE
    names an id, "no transaction with that id" is the most useful error —
    far better than validating fields for a row that was never there.
    Same SELECT shape as get_transactions, narrowed to one id.
    """
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT id, ticker, transaction_date, price, qty, currency,
                    fx_rate, transaction_type, fee, portfolio_id
            FROM transactions
            WHERE id = ? AND portfolio_id = ?
            """,
            (tx_id, portfolio_id),
        ).fetchone()
    return dict(row) if row else None


def update_transaction(tx_id, transaction_date, price, qty, transaction_type,
                       fx_rate, fee=None, portfolio_id=None):
    """Correct the user-editable facts of one transaction.

    The SET list names SIX columns — date, price, qty, type, fx_rate, fee.
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
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE transactions
            SET transaction_date = ?, price = ?, qty = ?, transaction_type = ?,
                fx_rate = ?, fee = ?
            WHERE id = ? AND portfolio_id = ?
            """,
            (transaction_date, price, qty, transaction_type, fx_rate, fee, tx_id,
             portfolio_id),
        )
        return cursor.rowcount > 0


def delete_transaction(tx_id, portfolio_id=None):
    """Remove one transaction permanently. Returns True if a row was
    actually deleted, False if the id doesn't exist (route turns that
    into a 404 — e.g. a second DELETE after the first one succeeded).

    Deletion is IMMEDIATE and unrecoverable: this is the immutable-facts
    table's one destructive verb, which is exactly why the UI gates it
    behind a confirm() dialog.
    """
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND portfolio_id = ?",
            (tx_id, portfolio_id),
        )
        return cursor.rowcount > 0


def delete_transactions_for_ticker(ticker, portfolio_id=None):
    """Delete EVERY transaction of one ticker — the ledger's one BULK
    verb, sitting next to delete_transaction's single-row verb. Returns
    the number of rows actually deleted: 0 means no row carried this
    ticker (the route turns that into a 404 — "no such group", which is
    also what an empty ledger looks like).

    The WHERE clause is an exact match on the canonical UPPERCASE ticker,
    on purpose: "AAPL" (NYSE, USD) and "AAPL.TO" (TSX, CAD) are different
    securities that must never wipe each other. Parameterized like every
    query here — the ticker travels as data, never as SQL text.
    """
    if portfolio_id is None:
        portfolio_id = default_portfolio_id()
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE ticker = ? AND portfolio_id = ?",
            (ticker, portfolio_id),
        )
        return cursor.rowcount
