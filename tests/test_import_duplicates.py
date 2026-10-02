# tests/test_import_duplicates.py
# =================================
# Roadmap #31 — Possible Duplicate flags in the import preview.
#
# Layered like the feature itself (same shape as test_import.py):
#   - PURE HELPER TESTS: mark_import_duplicates compares parsed import
#     rows against stored transaction dicts. No Flask, no DB, no network.
#     The rule is the #45 five-field match (ticker, date, type, qty,
#     price, each number within FLAT_QTY_TOL) with one deliberate
#     difference: FEE IS NOT COMPARED. The paste format has no fee
#     column, so an existing row with a fee must still flag.
#   - ROUTE TESTS: /api/transactions/import/preview decorates valid rows
#     with the boolean flag and reports duplicate_count; preview stays
#     ZERO-WRITES. Commit is unchanged and still writes every valid row —
#     the explicit confirmation lives in the browser.
#   - FRONTEND SOURCE TESTS: ledger.js renders the count line and the
#     per-row tag, the commit handler confirms via showConfirm, and
#     style.css paints both bold red. String checks, same honest
#     limitation as test_ledger_css.py (pytest cannot run a browser).

from pathlib import Path

import db
import app as app_module
from app import mark_import_duplicates
from conftest import make_quote, seed_user


# ── Helpers & fixtures ────────────────────────────────────────────────

PASTE = "CM\t16 Mar 2026\t132.55\t1.296383"

ROOT = Path(__file__).resolve().parent.parent
LEDGER_JS = (ROOT / "static" / "js" / "ledger.js").read_text()
LEDGER_HTML = (ROOT / "templates" / "ledger.html").read_text()
STYLE_CSS = (ROOT / "static" / "style.css").read_text()


def existing_row(tx_id=1, price=132.55, qty=1.296383, side="BUY",
                 date_="2026-03-16", ticker="CM", fee=None):
    """One stored transaction, shaped exactly like db.get_transactions
    returns it."""
    return {
        "id": tx_id,
        "ticker": ticker,
        "transaction_date": date_,
        "price": price,
        "qty": qty,
        "currency": "USD",
        "fx_rate": 1.3725,
        "transaction_type": side,
        "fee": fee,
        "portfolio_id": 1,
    }


def seed_tx(pid=1, **overrides):
    """Write one ledger row through the real db layer (route tests)."""
    fields = dict(price=132.55, qty=1.296383, side="BUY",
                  date_="2026-03-16", ticker="CM", fee=None)
    fields.update(overrides)
    return db.add_transaction(
        fields["ticker"], fields["date_"], fields["price"], fields["qty"],
        "USD", fields["side"], 1.3725, fee=fields["fee"], portfolio_id=pid,
    )


def commit_handler_body():
    """The commit button's click handler source — the block the confirm
    must live in."""
    start = LEDGER_JS.find('importCommitBtn.addEventListener("click"')
    assert start != -1, "commit click handler not found in ledger.js"
    end = LEDGER_JS.find("\n});", start)
    assert end != -1, "commit click handler has no closing brace"
    return LEDGER_JS[start:end]


def css_rule(needle):
    """The first CSS rule block whose text contains `needle` (same crude
    walk-back-to-brace as test_ledger_css.rule_containing)."""
    i = STYLE_CSS.find(needle)
    assert i != -1, f"needle not found in style.css: {needle!r}"
    start = STYLE_CSS.rfind("{", 0, i)
    end = STYLE_CSS.find("}", i)
    assert start != -1 and end != -1, f"could not isolate rule: {needle!r}"
    return STYLE_CSS[start:end]


# ── Pure helper ───────────────────────────────────────────────────────

def test_match_requires_all_five_fields():
    rows = app_module.parse_import_text(PASTE)
    assert mark_import_duplicates(rows, [existing_row()]) == 1
    assert rows[0]["duplicate"] is True

    # Each field changed in turn kills the match.
    mutations = [
        dict(ticker="XYZ"),
        dict(date_="2026-03-17"),
        dict(side="SELL"),
        dict(qty=2.0),
        dict(price=133.0),
    ]
    for change in mutations:
        rows = app_module.parse_import_text(PASTE)
        assert mark_import_duplicates(rows, [existing_row(**change)]) == 0, change
        assert rows[0]["duplicate"] is False, change


def test_fee_is_ignored():
    """#31 divergence from the roadmap's first sketch, user-approved:
    an existing row with a fee still flags, because import rows carry no
    fee at all (the parser never adds the key)."""
    rows = app_module.parse_import_text(PASTE)
    assert "fee" not in rows[0]
    assert mark_import_duplicates(rows, [existing_row(fee=9.99)]) == 1
    assert rows[0]["duplicate"] is True


def test_tolerance_matches_within_flat_qty_tol_only():
    rows = app_module.parse_import_text(PASTE)
    close = existing_row(qty=1.296383 + 5e-10, price=132.55 - 5e-10)
    assert mark_import_duplicates(rows, [close]) == 1

    rows = app_module.parse_import_text(PASTE)
    loose = existing_row(qty=1.296383 + 1e-6, price=132.55 + 1e-6)
    assert mark_import_duplicates(rows, [loose]) == 0


def test_error_rows_are_skipped():
    """A broken line has no comparison fields — it must never be flagged
    (and never crash the helper)."""
    rows = app_module.parse_import_text("CM\t16 Mar 2026\t132.55")
    assert rows[0]["error"] is not None
    assert mark_import_duplicates(rows, [existing_row()]) == 0
    assert rows[0]["duplicate"] is False


def test_counts_each_row_once_even_with_several_matches():
    rows = app_module.parse_import_text(PASTE)
    assert mark_import_duplicates(
        rows, [existing_row(1), existing_row(2)]) == 1

    # Two identical paste rows matching one stored row: two flags.
    rows = app_module.parse_import_text(PASTE + "\n" + PASTE)
    assert mark_import_duplicates(rows, [existing_row()]) == 2
    assert [row["duplicate"] for row in rows] == [True, True]


def test_transposed_date_is_not_a_duplicate():
    """Roadmap #31's required mistype case: 13 vs 31 is a transposed
    digit pair. The check compares exact ISO strings — no fuzzy dates."""
    rows = app_module.parse_import_text("CM\t31 Mar 2026\t132.55\t1.296383")
    assert mark_import_duplicates(rows, [existing_row(date_="2026-03-13")]) == 0

    rows = app_module.parse_import_text("CM\t13 Mar 2026\t132.55\t1.296383")
    assert mark_import_duplicates(rows, [existing_row(date_="2026-03-13")]) == 1


def test_type_must_match():
    """Every imported row is a BUY; a same-fields SELL is another trade."""
    rows = app_module.parse_import_text(PASTE)
    assert mark_import_duplicates(rows, [existing_row(side="SELL")]) == 0
    assert rows[0]["duplicate"] is False


def test_every_row_gets_a_boolean():
    rows = app_module.parse_import_text(PASTE + "\nCM\tbad\t10\t1")
    assert mark_import_duplicates(rows, [existing_row()]) == 1
    assert [row["duplicate"] for row in rows] == [True, False]


# ── Preview route ─────────────────────────────────────────────────────

def test_preview_flags_existing_transaction(client, fake_market):
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)
    seed_tx()

    res = client.post("/api/transactions/import/preview", json={"text": PASTE})
    body = res.get_json()
    assert res.status_code == 200
    assert body["valid_count"] == 1
    assert body["duplicate_count"] == 1
    assert body["rows"][0]["duplicate"] is True
    assert len(db.get_transactions(1)) == 1  # preview stores NOTHING


def test_preview_without_matches_reports_zero(client, fake_market):
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)

    res = client.post("/api/transactions/import/preview", json={"text": PASTE})
    body = res.get_json()
    assert body["duplicate_count"] == 0
    assert body["rows"][0]["duplicate"] is False


def test_invalid_rows_are_not_counted(client, fake_market):
    seed_tx()  # CM exists; NOPE is unquotable below
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)
    res = client.post("/api/transactions/import/preview", json={
        "text": PASTE + "\nNOPE\t16 Mar 2026\t132.55\t1.296383",
    })
    body = res.get_json()
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 1
    assert body["duplicate_count"] == 1
    assert body["rows"][0]["duplicate"] is True
    assert body["rows"][1]["duplicate"] is False


def test_duplicates_are_per_portfolio(client, fake_market):
    """Bert's stored CM is invisible to tester's preview: the comparison
    reads g.portfolio_id only."""
    seed_user("bert")
    seed_tx(pid=2)
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)

    res = client.post("/api/transactions/import/preview", json={"text": PASTE})
    body = res.get_json()
    assert body["duplicate_count"] == 0
    assert body["rows"][0]["duplicate"] is False


def test_commit_still_writes_flagged_rows(client, fake_market):
    """Server commits stay all-or-nothing; the confidence step is the
    browser's confirm dialog."""
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)
    fake_market.fx_on[("USDCAD", "2026-03-16")] = 1.3725
    seed_tx()

    preview = client.post("/api/transactions/import/preview",
                          json={"text": PASTE}).get_json()
    assert preview["duplicate_count"] == 1

    res = client.post("/api/transactions/import/commit", json={"text": PASTE})
    assert res.status_code == 200
    assert res.get_json()["imported"] == 1
    assert len(db.get_transactions(1)) == 2


def test_preview_reply_always_has_duplicate_count(client, fake_market):
    fake_market.quotes["CM"] = make_quote("CM", 100.0, 95.0)

    body = client.post("/api/transactions/import/preview",
                       json={"text": PASTE}).get_json()
    assert isinstance(body["duplicate_count"], int)
    assert body["duplicate_count"] == 0


# ── Frontend source contracts ─────────────────────────────────────────

def test_ledger_js_renders_duplicate_ui():
    for needle in ("import-duplicate-tag", "import-duplicate-summary",
                   "duplicate_count", "Possible Duplicate"):
        assert needle in LEDGER_JS, needle


def test_commit_handler_confirms_duplicates():
    body = commit_handler_body()
    for needle in ("showConfirm", "previewDuplicateCount", "Import anyway",
                   "row looks like it already exists", "rows look like"):
        assert needle in body, needle


def test_css_marks_duplicates_bold_red():
    for selector in (".import-duplicate-summary", ".import-duplicate-tag"):
        rule = css_rule(selector)
        assert "font-weight: 700" in rule, selector
        assert "color: var(--red-neg)" in rule, selector


def test_hint_documents_duplicate_marking():
    assert "Possible Duplicate" in LEDGER_HTML
    assert "there is no duplicate detection" not in LEDGER_HTML
