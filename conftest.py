# conftest.py — shared pytest setup for the WHOLE test suite.
#
# Two jobs:
#   1. (Original) make the project root importable so tests can say
#      `from app import ...` — pytest adds a conftest.py's directory to
#      sys.path automatically.
#   2. (Now) hold FIXTURES shared by multiple test files.
#
# FIXTURES — the concept
#   A fixture is a named chunk of setup a test asks for by listing its name
#   as a parameter:  def test_something(fresh_db):  ...
#   pytest runs the fixture BEFORE the test and tears it down AFTER.
#   Fixtures kill copy-pasted setup code AND make dependencies visible:
#   you can read a test's parameter list and know exactly what world it
#   needs to run in.
#
#   `tmp_path`  — built-in pytest fixture: a fresh empty temp directory
#                 that exists for THIS test only, auto-deleted later.
#   `monkeypatch` — built-in pytest fixture for safely swapping attributes
#                 (paths, functions...) for the duration of one test.
#                 Everything it changes is restored automatically — a test
#                 can never leak its hacks into the next test.

from types import SimpleNamespace
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

import db
import market_data
import app as app_module
from app import app


@pytest.fixture(autouse=True)
def fresh_market_caches():
    """Empty every process-memory market cache around every test."""
    market_data.clear_market_caches()
    yield
    market_data.clear_market_caches()


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Point the db layer at a throwaway SQLite file for one test.

    WHY: db.py builds DB_PATH (instance/portfolio.db) at module level, and
    every _connect() reads it at call time. Swapping db.DB_PATH is therefore
    the single switch that redirects ALL reads/writes — no app code needed.
    Without this, running tests would write to your REAL ledger.

    tmp_path gives each test its own untouched database file, so tests are
    isolated: no leftovers from a previous test can change the outcome.
    """
    test_db_path = tmp_path / "test_portfolio.db"
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    db.init()  # create the schema in the throwaway file
    return test_db_path


def seed_user(username, password="pw-1234"):
    """Create a user row the way the route layer would (hash first).
    Returns the new user id. Duplicate usernames raise sqlite3.IntegrityError.
    """
    return db.create_user(username, generate_password_hash(password))


def main_portfolio_id(user_id=1):
    """A user's first ordered portfolio id. The `client` fixture always
    seeds tester as user id 1, whose Main is portfolio id 1 (the first
    user in a fresh test DB), so the default is safe there."""
    return db.get_portfolios(user_id)[0]["id"]


# The `client` fixture's identity: user id 1 / portfolio id 1. Documented
# so single-user tests can hardcode ids; multi-user tests call seed_user
# with OTHER names (reusing "tester" would trip the username conflict).
CLIENT_USER_ID = 1
TESTER_PASSWORD = "test-password-1234"


@pytest.fixture
def client(fresh_db):
    """A Flask test client wired to the throwaway database, signed in as
    the seeded tester user.

    The session cookie is FORGED (session_transaction writes the signed
    cookie directly) instead of running the /auth/login form every test:
    a login costs one ~scrypt check per test and adds ~seconds to the
    suite for no extra coverage — the login route itself has dedicated
    tests in test_auth.py. Watching, scope-level and gate behavior stay
    under test exactly as they would with a real login.

    The TEST CLIENT — the concept:
      Flask ships a fake browser. client.get("/api/watchlist") calls the
      real route function through real Flask machinery (routing, JSON
      parsing, status codes) but WITHOUT a network, a port, or a running
      server. Responses are real Response objects: .status_code, .get_json().
    """
    test_client = app.test_client()
    user_id = seed_user("tester", TESTER_PASSWORD)
    with test_client.session_transaction() as session:
        session["user_id"] = user_id
    return test_client


# ── The fake market ───────────────────────────────────────────────────
#
# Shared by test_routes.py and test_stock.py (both exercise routes that
# fetch market data), so it lives here in conftest — the agreed home for
# anything more than one test file needs.

def make_legacy_db(path):
    """Build a database in the PRE-multi-user schema by hand: the exact
    shape a committed Portfoliarr wrote before users/ownership existed.
    db.init() must migrate it unchanged (facts preserved), and the setup
    route's claim must hand the legacy portfolio + watchlist to the first
    user. Returns nothing; the schema speaks for itself.
    """
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO watchlist VALUES ('AAPL')")
        conn.execute("""CREATE TABLE portfolios (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL
                CHECK (length(name) BETWEEN 1 AND 60 AND name = trim(name)),
            sort_order INTEGER NOT NULL)""")
        conn.execute("""CREATE UNIQUE INDEX portfolio_name_unique
            ON portfolios(name COLLATE NOCASE)""")
        conn.execute("INSERT INTO portfolios VALUES (1, 'Main', 0)")
        conn.execute("""CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
            transaction_date TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, currency TEXT NOT NULL, fx_rate REAL,
            fee REAL, transaction_type TEXT NOT NULL,
            portfolio_id INTEGER NOT NULL REFERENCES portfolios(id))""")
        conn.execute("""INSERT INTO transactions VALUES
            (42, 'AAPL', '2026-01-01', 12.5, 2, 'USD', 1.31, 3.5, 'BUY', 1)""")


def make_quote(symbol, price, previous_close, currency="USD"):
    """Build a quote dict in exactly the shape market_data.get_quote
    returns (raw floats + derived day-move numbers). A plain helper, not a
    fixture — fixtures are for SETUP; this just builds test data."""
    return {
        "symbol": symbol,
        "price": price,
        "previous_close": previous_close,
        "currency": currency,
        "change": price - previous_close,
        "change_pct": (price - previous_close) / previous_close * 100,
    }


@pytest.fixture
def fake_market(monkeypatch):
    """Swap the market-data names AS APP.PY USES THEM.

    Patching app.get_quote (not market_data.get_quote!) — the golden
    mocking rule "patch where it's USED": app.py did `from market_data
    import get_quote`, so the name routes actually look up is
    app.get_quote. Patching market_data.get_quote instead would silently
    do nothing — the #1 mocking mistake.

    The patches are dict lookups, so "unknown symbol" is simulated by the
    key simply being ABSENT: quotes["NOPE"] raises KeyError, every route
    catches it, and the resilience paths get exercised exactly as they
    would with a real Yahoo outage.

    The FX helpers get the same treatment: fx_rates is keyed "USDCAD"
    (the live-rate lookup), fx_on is keyed (pair, "YYYY-MM-DD") (the
    historical-rate lookup). prices_on is keyed (symbol, "YYYY-MM-DD") —
    the ledger prefill's dated close. An ABSENT key = "Yahoo couldn't
    answer" — the exact failure path the routes' fallbacks exist for.
    """
    quotes, names, histories, stats = {}, {}, {}, {}
    fx_rates, fx_on = {}, {}
    prices_on = {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    monkeypatch.setattr(app_module, "get_name", lambda symbol: names[symbol])
    monkeypatch.setattr(app_module, "get_history",
                        lambda symbol, period: histories[symbol])
    monkeypatch.setattr(app_module, "get_stats", lambda symbol: stats[symbol])
    monkeypatch.setattr(app_module, "get_fx_rate",
                        lambda base, target: fx_rates[f"{base}{target}"])
    monkeypatch.setattr(app_module, "get_fx_rate_on",
                        lambda base, target, date_iso:
                            fx_on[(f"{base}{target}", date_iso)])
    monkeypatch.setattr(app_module, "get_price_on",
                        lambda symbol, date_iso: prices_on[(symbol, date_iso)])
    return SimpleNamespace(quotes=quotes, names=names, histories=histories,
                           stats=stats, fx_rates=fx_rates, fx_on=fx_on,
                           prices_on=prices_on)
