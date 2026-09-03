# tests/test_import.py
# =====================
# Tests for the transaction importer: parse_import_text + the two import
# routes (preview / commit).
#
# Layered like the feature itself (same concepts as test_routes.py):
#   - PARSER UNIT TESTS: a pure function — no Flask, no fixtures, no
#     network. Its contract: broken lines come back as DATA (a row with
#     an "error" reason), never as exceptions, and valid lines come back
#     fully normalized (uppercase ticker, ISO date, floats, forced BUY).
#   - ROUTE TESTS: the Flask test client (conftest.py) against the
#     throwaway fresh_db, with get_quote patched AS APP.PY USES IT —
#     "patch where it's used" (app.get_quote, never market_data.get_quote;
#     see the banner in test_routes.py for the name-collision subtlety).
#
# WHAT'S WORTH TESTING AT THIS LAYER?
#   - the zero-writes rule: preview NEVER touches the ledger
#   - normalization: " cm " in, "CM" stored; "16 Mar 2026" in,
#     "2026-03-16" stored
#   - best-effort: a dead ticker or a broken line fails ALONE — its
#     neighbours still import
#   - the no-dedup decision: committing the same text twice doubles the
#     rows (documented behavior, so test that it's what actually happens)

from types import SimpleNamespace

import pytest

import db
import app as app_module


# ── Helpers & fixtures ────────────────────────────────────────────────

# The feature.md sample format: four TAB-separated columns. \t in a normal
# Python string IS the tab character — no need for raw strings here.
PASTE = "CM\t16 Mar 2026\t132.55\t1.296383"


def make_quote(symbol, currency="USD"):
    """Build a quote dict in exactly the shape market_data.get_quote
    returns (same helper idea as test_routes.py)."""
    return {
        "symbol": symbol,
        "price": 100.0,
        "previous_close": 95.0,
        "currency": currency,
        "change": 5.0,
        "change_pct": 5.263,
    }


@pytest.fixture
def fake_market(monkeypatch):
    """Patch get_quote AS APP.PY USES IT: a dict lookup where a missing
    key raises KeyError — which is exactly what the routes' except blocks
    see during a real Yahoo failure for an unknown symbol."""
    quotes = {}
    monkeypatch.setattr(app_module, "get_quote", lambda symbol: quotes[symbol])
    return SimpleNamespace(quotes=quotes)


# ── Parser unit tests (pure — no Flask, no DB, no network) ────────────

def test_parse_happy_path():
    """The feature.md sample line, end to end: tab-split, uppercase
    ticker, ISO date, floats, forced BUY, no error."""
    rows = app_module.parse_import_text(PASTE)
    assert rows == [{
        "line": 1,
        "raw": PASTE,
        "ticker": "CM",
        "transaction_date": "2026-03-16",
        "price": 132.55,
        "qty": 1.296383,
        "transaction_type": "BUY",
        "error": None,
    }]


def test_parse_accepts_non_padded_day():
    """strptime's %d tolerates a missing leading zero — '1 May 2026' is
    the same calendar date as '01 May 2026'."""
    (row,) = app_module.parse_import_text("CM\t1 May 2026\t10\t1")
    assert row["transaction_date"] == "2026-05-01"
    assert row["error"] is None


def test_parse_normalizes_padding_and_case():
    """Paste cosmetics (spaces around fields, lowercase ticker) never
    reach the ledger — same trim + uppercase rule as log_transaction."""
    (row,) = app_module.parse_import_text(
        " cm \t 16 Mar 2026 \t 132.55 \t 1.296383 "
    )
    assert row["ticker"] == "CM"
    assert row["price"] == 132.55
    assert row["error"] is None


def test_parse_skips_blank_lines_but_counts_them():
    """Blank lines are paste noise — skipped as rows, but they still
    COUNT for line numbers, so the report matches the user's editor."""
    rows = app_module.parse_import_text("\n\n" + PASTE)
    assert len(rows) == 1
    assert rows[0]["line"] == 3


def test_parse_handles_windows_line_endings():
    """splitlines() treats \r\n as one ending — a Windows-notepad paste
    parses identically to a Unix one."""
    text = PASTE + "\r\nCM\t30 Mar 2026\t128.89\t1.333187"
    rows = app_module.parse_import_text(text)
    assert len(rows) == 2
    assert rows[1]["transaction_date"] == "2026-03-30"


def test_parse_reports_wrong_column_count():
    """A 3-column line fails LOUDLY with a reason — and never aborts the
    batch: the good line after it still parses."""
    rows = app_module.parse_import_text(
        "CM\t16 Mar 2026\t132.55\n" + PASTE
    )
    assert len(rows) == 2
    assert "4 tab-separated columns" in rows[0]["error"]
    # The column-count check runs BEFORE any field parsing — so nothing
    # was extracted, and every field stays None for this row.
    assert rows[0]["ticker"] is None
    assert rows[0]["price"] is None
    assert rows[1]["error"] is None


def test_parse_rejects_non_english_or_wrong_order_dates():
    """'2026-03-16' (ISO) does NOT match '%d %b %Y' — the format's date
    is day-month-name-year, and anything else fails with a reason."""
    (row,) = app_module.parse_import_text("CM\t2026-03-16\t132.55\t1")
    assert row["transaction_date"] is None
    assert "16 Mar 2026" in row["error"]


def test_parse_rejects_non_numeric_numbers():
    (row,) = app_module.parse_import_text("CM\t16 Mar 2026\tlots\t1")
    assert row["error"] is not None
    assert "price" in row["error"]


@pytest.mark.parametrize("price,qty", [("0", "1"), ("-5", "1"), ("10", "0"), ("10", "-1")])
def test_parse_rejects_non_positive_numbers(price, qty):
    """Same > 0 rule as validate_tx_fields: however well '0' or '-5'
    parses, it's nonsense in a ledger."""
    (row,) = app_module.parse_import_text(f"CM\t16 Mar 2026\t{price}\t{qty}")
    assert row["error"] is not None


# ── Preview route ─────────────────────────────────────────────────────

def test_preview_reports_rows_and_derived_currency(client, fake_market):
    """The preview is a dress rehearsal: valid rows decorated with the
    quote's currency (CM on Yahoo = the NYSE listing = USD) — and the
    ledger untouched. THE zero-writes assertion."""
    fake_market.quotes["CM"] = make_quote("CM", currency="USD")

    res = client.post("/api/transactions/import/preview", json={"text": PASTE})
    body = res.get_json()
    assert res.status_code == 200
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 0
    assert body["rows"][0]["currency"] == "USD"
    assert body["rows"][0]["error"] is None
    assert db.get_transactions() == []   # preview stores NOTHING


def test_preview_marks_unquotable_ticker_invalid(client, fake_market):
    """No quote → the ticker isn't proven real → the row goes invalid
    with the same verdict log_transaction's 404 uses."""
    res = client.post("/api/transactions/import/preview", json={"text": PASTE})
    body = res.get_json()
    assert res.status_code == 200        # the request worked; the ROW failed
    assert body["valid_count"] == 0
    assert body["rows"][0]["error"] == "unknown or unquotable ticker"
    assert db.get_transactions() == []


def test_preview_counts_mixed_rows(client, fake_market):
    """One good line + one broken line → 1 valid, 1 invalid, each row
    carrying its own verdict. The report needs BOTH to be useful."""
    fake_market.quotes["CM"] = make_quote("CM")
    res = client.post("/api/transactions/import/preview", json={
        # Second line: right column count, wrong date format → the date
        # check's reason (the column-count reason is the parser test's job).
        "text": PASTE + "\nCM\t2026-03-16\t132.55\t1",
    })
    body = res.get_json()
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 1
    assert body["rows"][0]["error"] is None
    assert "date" in body["rows"][1]["error"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {},                                   # no JSON body at all
        {"json": ["rows"]},                   # JSON, but not a dict
        {"json": {"text": "   "}},            # whitespace-only paste
    ],
    ids=["no body", "non-dict body", "blank text"],
)
def test_preview_rejects_bad_bodies_with_400(client, kwargs):
    res = client.post("/api/transactions/import/preview", **kwargs)
    assert res.status_code == 400


# ── Commit route ──────────────────────────────────────────────────────

def test_commit_inserts_rows_and_derives_currency(client, fake_market):
    """The whole pipeline in one test: paste in, ledger row out — with
    the ticker normalized, the date converted, the currency taken from
    the quote, and the type forced to BUY."""
    fake_market.quotes["CM"] = make_quote("CM", currency="USD")

    res = client.post("/api/transactions/import/commit", json={"text": PASTE})
    body = res.get_json()
    assert res.status_code == 200
    assert body["imported"] == 1
    assert body["failed"] == []

    (row,) = db.get_transactions()
    assert row["ticker"] == "CM"
    assert row["transaction_date"] == "2026-03-16"
    assert row["price"] == 132.55
    assert row["qty"] == 1.296383
    assert row["currency"] == "USD"
    assert row["transaction_type"] == "BUY"


def test_commit_best_effort_skips_dead_ticker(client, fake_market):
    """Per-row resilience: one dead ticker fails ALONE — its neighbours
    still import, and the report explains exactly what didn't make it."""
    fake_market.quotes["AAPL"] = make_quote("AAPL")
    res = client.post("/api/transactions/import/commit", json={
        "text": PASTE + "\nAAPL\t16 Mar 2026\t229.5\t10",
    })
    body = res.get_json()
    assert res.status_code == 200
    assert body["imported"] == 1          # AAPL made it...
    assert len(body["failed"]) == 1       # ...CM didn't
    assert body["failed"][0]["error"] == "unknown or unquotable ticker"
    assert body["failed"][0]["ticker"] == "CM"
    assert [tx["ticker"] for tx in db.get_transactions()] == ["AAPL"]


def test_commit_reports_parse_failures_and_imports_the_rest(client, fake_market):
    """Same best-effort rule at the PARSE stage: a broken line is a
    report entry, not an exception that kills the batch."""
    fake_market.quotes["CM"] = make_quote("CM")
    res = client.post("/api/transactions/import/commit", json={
        "text": "CM\t16 Mar 2026\t132.55\n" + PASTE,
    })
    body = res.get_json()
    assert res.status_code == 200
    assert body["imported"] == 1
    assert "4 tab-separated columns" in body["failed"][0]["error"]
    assert [tx["ticker"] for tx in db.get_transactions()] == ["CM"]


def test_commit_200_even_when_nothing_qualifies(client, fake_market):
    """The request succeeded; the report IS the answer. imported == 0 is
    an honest 200 — a 400 would claim the request was malformed."""
    res = client.post("/api/transactions/import/commit", json={
        "text": "CM\t16 Mar 2026\t132.55",
    })
    body = res.get_json()
    assert res.status_code == 200
    assert body["imported"] == 0
    assert len(body["failed"]) == 1
    assert db.get_transactions() == []


def test_commit_recommitting_duplicates_by_design(client, fake_market):
    """THE no-dedup decision, made testable: the ledger has no identity
    beyond its own auto-numbers, so the same text committed twice lands
    twice. Documented in the panel's hint text — this test pins that
    behavior so a future dedup feature must change it consciously."""
    fake_market.quotes["CM"] = make_quote("CM")
    first = client.post("/api/transactions/import/commit", json={"text": PASTE})
    second = client.post("/api/transactions/import/commit", json={"text": PASTE})
    assert first.get_json()["imported"] == 1
    assert second.get_json()["imported"] == 1
    assert len(db.get_transactions()) == 2


def test_commit_rejects_bad_bodies_with_400(client):
    res = client.post("/api/transactions/import/commit")   # no JSON body
    assert res.status_code == 400
