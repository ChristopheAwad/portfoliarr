"""SQLite persistence layer.

Stores five things: the user accounts (multi-user auth), the per-boot
app settings (one row: the session secret), each user's watchlist symbol
list, each user's named portfolios, and the transaction ledger (every
BUY/SELL the user records).

The ledger's design rule: store IMMUTABLE FACTS ONLY. Any value that
depends on the live market price (total value, gain $/%) would freeze
stale the moment it was stored, so those are computed at display time
from live quotes instead — never written here.

OWNERSHIP is the schema's spine: every portfolio row carries the user who
owns it (transactions ride along through their portfolio's foreign key),
and every watchlist row is one user's. Every function that touches this
data takes that owner EXPLICITLY — there is no silent default that could
hand somebody else's ledger to a caller.

This module knows nothing about Flask or yfinance — routes decide WHAT the
data means; this file only knows HOW to store and retrieve rows.
Password hashing (werkzeug) is route-layer policy too: this file stores
the finished hash and verifies nothing.

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
    Migrations follow the same rule: each asks PRAGMA table_info what the
    table already has and ALTERs only the missing column (or rebuilds the
    table once). Running init() on an already-migrated DB changes nothing.

    The WHOLE thing is one explicit transaction (BEGIN IMMEDIATE at the
    top): in modern Python's sqlite3 the DDL statements (CREATE/ALTER/
    DROP) run in AUTOCOMMIT whenever no transaction is open — and this
    function's DDL all come before its only DML — so without the explicit
    BEGIN, a failed migration would leave HALF-committed schema behind
    (the rebuild's shadow table surviving a failed copy, say). With it,
    a failure anywhere rolls the complete schema back: either the whole
    migration happened, or none of it did.
    """
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        # `with conn:` commits the change if the block succeeds and rolls
        # back on error — same idea as a transaction in any database.

        # Key/value table for server-level settings. One value today: the
        # session secret (generated once and persisted, so a container
        # restart doesn't invalidate every signed-in session).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        # The user accounts. Multi-user auth is ownership, not roles: a
        # username + a password hash (the ROUTE layer hashes passwords;
        # this table stores the finished string). The username CHECK is
        # defence in depth behind route validation, in the same spirit as
        # the portfolios name CHECK below: 1-30 characters, no leading or
        # trailing whitespace. UNIQUE + COLLATE NOCASE makes "amy" and
        # "AMY" the same account (case-insensitive uniqueness, case-kept
        # display).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY,
                username      TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK (length(username) BETWEEN 1 AND 30
                           AND username = trim(username)),
                password_hash TEXT NOT NULL
            )
            """
        )

        # The watchlist: one user's symbols to watch, not a global list.
        # (user_id, symbol) is the identity, so two users can watch the
        # same ticker without knowing or caring about each other.
        watchlist_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()
        }
        if not watchlist_columns:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id INTEGER REFERENCES users(id),
                    symbol  TEXT NOT NULL,
                    PRIMARY KEY (user_id, symbol)
                )
                """
            )
        elif "user_id" not in watchlist_columns:
            # Migration: the single-user watchlist becomes one user's list.
            # SQLite can't change a table's PRIMARY KEY in place, so
            # rebuild. Legacy rows land with a NULL user — the setup
            # route's claim_unowned_data() assigns them to the first
            # account. NULLs in a composite PRIMARY KEY are distinct, so
            # unclaimed rows can't collide either.
            conn.execute("""CREATE TABLE watchlist_user (
                user_id INTEGER REFERENCES users(id),
                symbol  TEXT NOT NULL,
                PRIMARY KEY (user_id, symbol))""")
            conn.execute(
                "INSERT INTO watchlist_user (user_id, symbol)"
                " SELECT NULL, symbol FROM watchlist"
            )
            conn.execute("DROP TABLE watchlist")
            conn.execute("ALTER TABLE watchlist_user RENAME TO watchlist")

        # The portfolios table: WHICH user each portfolio belongs to is
        # now part of the row. Public rules this preserves:
        #   * per-user "Main" — two people can both have a portfolio
        #     called Main, so the old GLOBAL name index must go;
        #   * at least one portfolio per user — enforced at the db
        #     function layer, not the schema (COUNT check);
        #   * 1-60 characters, trimmed — the CHECK stays.
        conn.execute("""CREATE TABLE IF NOT EXISTS portfolios (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
                CHECK (length(name) BETWEEN 1 AND 60 AND name = trim(name)),
            sort_order INTEGER NOT NULL,
            user_id INTEGER REFERENCES users(id))""")
        portfolio_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(portfolios)").fetchall()
        }
        if "user_id" not in portfolio_columns:
            # Adding a NULLable FK column is legal in SQLite (only NOT NULL
            # FK additions are not). Legacy rows stay user-owned... by
            # nobody — user_id NULL — until the setup route claims them,
            # and every read below filters WHERE user_id = ?, so nobody
            # sees unclaimed data through the app.
            conn.execute(
                "ALTER TABLE portfolios ADD COLUMN user_id INTEGER"
                " REFERENCES users(id)"
            )
        conn.execute("DROP INDEX IF EXISTS portfolio_name_unique")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS portfolio_name_unique"
            " ON portfolios(user_id, name COLLATE NOCASE)"
        )

        # The transaction ledger. Stores IMMUTABLE FACTS ONLY — nothing that
        # depends on a live market price (such values would freeze stale the
        # moment they were stored). Ownership is TRANSITIVE: the row belongs
        # to the user who owns its portfolio, so itself carries no user_id
        # column. Each column's type choice:
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
            main_row = conn.execute(
                "SELECT id FROM portfolios WHERE name = 'Main'").fetchone()
            if main_row is None:
                # A pre-#23 install had NO portfolios table: create the Main
                # ledger this rebuild copies rows into. No user exists yet,
                # so it starts unclaimed (user_id NULL) and the setup
                # route's claim hands it to the first account.
                main_id = conn.execute(
                    "INSERT INTO portfolios (name, sort_order, user_id)"
                    " VALUES ('Main', 0, NULL)").lastrowid
            else:
                main_id = main_row[0]
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


# ---------------------------------------------------------------------------
# SERVER SETTINGS — one key/value row today: the session secret. Settings
# live HERE (not Flask config) because they must survive container restarts
# exactly like the ledger, and the route layer reads them at boot.
# ---------------------------------------------------------------------------

def get_setting(key):
    """Return one setting's value, or None when it was never stored."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def set_setting(key, value):
    """Insert or replace one setting. REPLACE also updates the rowid,
    which is fine — settings have no meaningful order."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# USERS — the auth spine. Hashing is ROUTE policy (werkzeug lives there);
# these functions store and look up the finished hash. get_user deliberately
# includes password_hash (the login path needs it), while get_users() — the
# People-list reply — omits it: hashes must never leave the server.
# ---------------------------------------------------------------------------
def get_users():
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id, username FROM users ORDER BY id")]


def get_user(user_id):
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, username, password_hash FROM users WHERE id = ?",
            (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_username(username):
    """Exact-string username lookup — NOCASE comes from the column's
    declared COLLATE, so the caller may pass any casing; what it may NOT
    pass is an untrimmed name (that's route policy, and the CHECK agrees)."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, username, password_hash FROM users"
            " WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def count_users():
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(username, password_hash, seed_main=True):
    """Insert one account AND, by default, its first portfolio ('Main')
    in one write.

    Both statements run in one BEGIN IMMEDIATE block, so a username
    collision rolls EVERYTHING back — an account can never exist without
    its Main portfolio. Duplicate usernames raise IntegrityError (the
    UNIQUE + NOCASE constraint catches case-insensitive repeats); the
    route turns that into its 'taken' reply.

    Setup calls this with seed_main=False: the legacy there has to be
    CLAIMED first (an old install's 'Main' portfolio must be adopted, not
    doubled), and claim_unowned_data is what seeds Main when there is
    nothing legitimately to adopt.
    """
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        user_id = cursor.lastrowid
        if seed_main:
            conn.execute(
                "INSERT INTO portfolios (name, sort_order, user_id)"
                " VALUES ('Main', 0, ?)", (user_id,)
            )
        return user_id


def set_password(user_id, password_hash):
    """Store a NEW hash (verification of the old password already happened
    in the route). False means no such user."""
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        return cursor.rowcount > 0


def delete_user(user_id, confirmation):
    """Delete one account and EVERYTHING it owns, in one transaction:
    its portfolios, those portfolios' transactions, and its watchlist
    rows. Same outcome vocabulary as delete_portfolio:

        "missing"   no such user id
        "mismatch"  typed username != stored username (exact match)
        "last"      refusing to delete the only account (it's the one
                    thing keeping the server reachable at all)
        "deleted"   done

    Deleting the account you're signed in as is the ROUTE layer's rule
    (it knows the session); this layer only refuses the LAST user.
    """
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT username FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return "missing"
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1:
            return "last"
        if confirmation != row[0]:
            return "mismatch"
        conn.execute("""DELETE FROM transactions WHERE portfolio_id IN
            (SELECT id FROM portfolios WHERE user_id = ?)""", (user_id,))
        conn.execute("DELETE FROM portfolios WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM watchlist WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return "deleted"


def claim_unowned_data(user_id):
    """Adopt every owner-less portfolio/watchlist row into one account.

    Only the SETUP route calls this, exactly once, while the users table
    is empty: legacy rows carry user_id NULL from the migration, and this
    UPDATE is what turns 'nobody owns it' into 'the first account does'.
    If the claim finds no portfolio at all (a fresh install), it seeds
    the account's Main — create_user's usual guarantee.
    """
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE portfolios SET user_id = ? WHERE user_id IS NULL",
            (user_id,))
        conn.execute(
            "UPDATE watchlist SET user_id = ? WHERE user_id IS NULL",
            (user_id,))
        owned = conn.execute(
            "SELECT 1 FROM portfolios WHERE user_id = ? LIMIT 1",
            (user_id,)).fetchone()
        if owned is None:
            conn.execute(
                "INSERT INTO portfolios (name, sort_order, user_id)"
                " VALUES ('Main', 0, ?)", (user_id,))


def get_portfolios(user_id):
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(
            "SELECT id, name, sort_order FROM portfolios"
            " WHERE user_id = ? ORDER BY sort_order, id", (user_id,))]


def get_portfolio(portfolio_id, user_id):
    """One portfolio, but only when ITS OWNER signs: an id owned by
    somebody else is indistinguishable from a made-up id (None). The
    reply keeps the pre-#26 reply shape (id, name, sort_order) — the
    owner check rides in the WHERE clause, not in the payload."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, name, sort_order FROM portfolios"
            " WHERE id = ? AND user_id = ?",
            (portfolio_id, user_id)).fetchone()
    return dict(row) if row else None


def default_portfolio_id(user_id):
    """The user's first ordered portfolio — the fallback for API requests
    that omit portfolio_id. Returns None when the user owns nothing (the
    route answers 409 rather than guessing another person's ledger)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM portfolios WHERE user_id = ?"
            " ORDER BY sort_order, id LIMIT 1", (user_id,)
        ).fetchone()
    return row[0] if row else None


def create_portfolio(name, user_id):
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(row[0].casefold() == name.casefold() for row in
               conn.execute("SELECT name FROM portfolios WHERE user_id = ?",
                            (user_id,))):
            raise sqlite3.IntegrityError("portfolio name already exists")
        cursor = conn.execute(
            "INSERT INTO portfolios (name, sort_order, user_id)"
            " VALUES (?, (SELECT COALESCE(MAX(sort_order), -1) + 1"
            " FROM portfolios WHERE user_id = ?), ?)",
            (name, user_id, user_id))
        return cursor.lastrowid


def rename_portfolio(portfolio_id, user_id, name):
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(row[0] != portfolio_id and row[1].casefold() == name.casefold()
               for row in conn.execute(
                   "SELECT id, name FROM portfolios"
                   " WHERE id != ? AND user_id = ?",
                   (portfolio_id, user_id))):
            raise sqlite3.IntegrityError("portfolio name already exists")
        return conn.execute(
            "UPDATE portfolios SET name = ? WHERE id = ? AND user_id = ?",
            (name, portfolio_id, user_id)).rowcount > 0


def move_portfolio(portfolio_id, user_id, direction):
    """Swap adjacent display positions in one write transaction."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM portfolios WHERE user_id = ?"
            " ORDER BY sort_order, id", (user_id,))]
        if portfolio_id not in ids:
            return None
        index = ids.index(portfolio_id)
        neighbor = index + (-1 if direction == "up" else 1)
        if not 0 <= neighbor < len(ids):
            return False
        ids[index], ids[neighbor] = ids[neighbor], ids[index]
        conn.executemany(
            "UPDATE portfolios SET sort_order = ? WHERE id = ? AND user_id = ?",
            [(order, pid, user_id) for order, pid in enumerate(ids)])
        return True


def delete_portfolio(portfolio_id, user_id, confirmation):
    """Return deleted, missing, last, or mismatch; never leave orphan trades."""
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT name FROM portfolios WHERE id = ? AND user_id = ?",
                           (portfolio_id, user_id)).fetchone()
        if row is None:
            return "missing"
        if conn.execute("SELECT COUNT(*) FROM portfolios WHERE user_id = ?",
                        (user_id,)).fetchone()[0] == 1:
            return "last"
        if confirmation != row[0]:
            return "mismatch"
        conn.execute("DELETE FROM transactions WHERE portfolio_id = ?", (portfolio_id,))
        conn.execute("DELETE FROM portfolios WHERE id = ? AND user_id = ?",
                     (portfolio_id, user_id))
        ids = [r[0] for r in conn.execute("SELECT id FROM portfolios WHERE user_id = ? ORDER BY sort_order, id",
                                          (user_id,))]
        conn.executemany("UPDATE portfolios SET sort_order = ? WHERE id = ? AND user_id = ?",
                         [(order, pid, user_id) for order, pid in enumerate(ids)])
        return "deleted"


def get_symbols(user_id):
    """Return the user's watchlist as a list of symbol strings, in
    insertion order.

    Every SQLite table has a hidden `rowid` that counts up as rows are
    inserted, so ORDER BY rowid = "oldest watchlist entry first" — a stable,
    meaningful order without storing an extra timestamp column.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE user_id = ? ORDER BY rowid",
            (user_id,),
        ).fetchall()
    # fetchall() returns a list of one-value tuples: [("AAPL",), ("MSFT",)].
    # Unpack each tuple to get the plain string out.
    return [row[0] for row in rows]


def add_symbol(symbol, user_id):
    """Insert a symbol into the user's watchlist. Raises
    sqlite3.IntegrityError if it already exists (PRIMARY KEY violation;
    the (user_id, symbol) pair is the identity, so two users may watch
    the same ticker) — the route layer turns that into a 409."""
    with _connect() as conn:
        # The ? placeholder passes the value SEPARATELY from the SQL text,
        # so the database engine treats it as data only. Building SQL by
        # string formatting would let a crafted symbol execute extra SQL —
        # the classic "SQL injection" hole. Always parameterize.
        conn.execute(
            "INSERT INTO watchlist (user_id, symbol) VALUES (?, ?)",
            (user_id, symbol),
        )


def is_watched(symbol, user_id):
    """Membership check FOR ONE USER: is this exact symbol on their
    watchlist?

    Deliberately an EXACT match (no strip/upper here) — normalizing is the
    route layer's job (it does it for add/remove too), and a silent
    normalization here would let a sloppy caller keep passing unnormalized
    symbols that only *happen* to work for uppercase input. The stock page
    route calls this at render time to stamp the watch button's initial
    state, so the page knows it's watched before any JavaScript runs.
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM watchlist WHERE symbol = ? AND user_id = ?"
            " LIMIT 1", (symbol, user_id),
        ).fetchone()
    return row is not None


def remove_symbol(symbol, user_id):
    """Delete the user's row for one symbol. Returns True if a row was
    actually removed, False if it wasn't on THIS user's watchlist (route
    turns that into 404 — the same symbol watched by someone else is a
    different row that this statement never touches).

    cursor.rowcount reports how many rows the last statement touched.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM watchlist WHERE symbol = ? AND user_id = ?",
            (symbol, user_id),
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
                    transaction_type, fx_rate, fee=None, *, portfolio_id):
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

    portfolio_id is REQUIRED and KEYWORD-ONLY: ownership is never
    guessed. The route layer always has it (the portfolio-resolution
    hook verified it against the signed-in user first).

    Same ? placeholder rule as add_symbol: values travel separately from
    SQL text, so even hostile input is inert data, never executable SQL.
    """
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


def get_transactions(portfolio_id):
    """Return every transaction of ONE portfolio, newest first, as a list
    of plain dicts.

    Newest first because a ledger is read like a bank statement: the most
    recent event is what you check first. Two keys sort it — transaction_date
    first (the day it happened), then id (the order rows were inserted that
    day, since later ids were inserted later).

    sqlite3.Row is a row wrapper that behaves like a tuple BUT remembers its
    column names. dict(row) then turns each row into {"ticker": "AAPL", ...}
    — exactly the shape jsonify needs. Setting row_factory on the connection
    switches every fetch from that connection to Row objects.

    portfolio_id is required (no fallback): the hook that verified
    ownership always supplies it, and a silent default here could only
    ever leak the wrong person's ledger.
    """
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


def get_transaction(tx_id, portfolio_id):
    """Return ONE transaction as a dict, or None if that id doesn't exist
    IN THAT PORTFOLIO (an id owned by another portfolio — or another
    user — reads exactly as 'not found').

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
                    fx_rate, transaction_type, fee, portfolio_id
            FROM transactions
            WHERE id = ? AND portfolio_id = ?
            """,
            (tx_id, portfolio_id),
        ).fetchone()
    return dict(row) if row else None


def update_transaction(tx_id, transaction_date, price, qty, transaction_type,
                       fx_rate, fee=None, *, portfolio_id):
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
    row was actually updated, False if the id doesn't exist in this
    portfolio (rowcount 0), which the route turns into a 404.
    """
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


def delete_transaction(tx_id, portfolio_id):
    """Remove one transaction permanently. Returns True if a row was
    actually deleted, False if the id doesn't exist in this portfolio
    (route turns that into a 404 — e.g. a second DELETE after the first
    one succeeded).

    Deletion is IMMEDIATE and unrecoverable: this is the immutable-facts
    table's one destructive verb, which is exactly why the UI gates it
    behind a confirm() dialog.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND portfolio_id = ?",
            (tx_id, portfolio_id),
        )
        return cursor.rowcount > 0


def delete_transactions_for_ticker(ticker, portfolio_id):
    """Delete EVERY transaction of one ticker IN ONE PORTFOLIO — the
    ledger's one BULK verb, sitting next to delete_transaction's
    single-row verb. Returns the number of rows actually deleted: 0 means
    no row carried this ticker (the route turns that into a 404 — "no
    such group", which is also what an empty ledger looks like).

    The WHERE clause is an exact match on the canonical UPPERCASE ticker,
    on purpose: "AAPL" (NYSE, USD) and "AAPL.TO" (TSX, CAD) are different
    securities that must never wipe each other. Parameterized like every
    query here — the ticker travels as data, never as SQL text.
    """
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM transactions WHERE ticker = ? AND portfolio_id = ?",
            (ticker, portfolio_id),
        )
        return cursor.rowcount
