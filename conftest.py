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

import pytest

import db
from app import app


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


@pytest.fixture
def client(fresh_db):
    """A Flask test client wired to the throwaway database.

    The TEST CLIENT — the concept:
      Flask ships a fake browser. client.get("/api/watchlist") calls the
      real route function through real Flask machinery (routing, JSON
      parsing, status codes) but WITHOUT a network, a port, or a running
      server. Responses are real Response objects: .status_code, .get_json().
    """
    return app.test_client()
