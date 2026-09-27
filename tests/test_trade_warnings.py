# tests/test_trade_warnings.py
# =================================
# Roadmap #45 — non-blocking ledger trade sanity warnings.
#
# The write routes (POST log, PUT edit) return a "warnings" list with the
# saved transaction. The write ALWAYS happens; the form shows the warnings.
# Three kinds, in this fixed order: future date, SELL exceeding the held
# position, same-day duplicate (ticker/date/type/qty/price).
#
# Separate from #31 (import duplicate detection): the import replies gain
# NO warnings field.

from datetime import date
from pathlib import Path

import db
from app import compute_trade_warnings
from conftest import make_quote

LEDGER_HTML = Path("templates/ledger.html")
LEDGER_JS = Path("static/js/ledger.js")
LEDGER_CSS = Path("static/style.css")


def seed(price, qty, side="BUY", date_="2026-08-01",
         currency="CAD", fx=1.0, ticker="ABC", pid=1):
    return db.add_transaction(ticker, date_, price, qty, currency, side, fx,
                              portfolio_id=pid)


def row(tx_id, price, qty, side="BUY", date_="2026-08-01",
        ticker="ABC"):
    return {
        "id": tx_id,
        "ticker": ticker,
        "transaction_date": date_,
        "price": price,
        "qty": qty,
        "currency": "CAD",
        "fx_rate": 1.0,
        "transaction_type": side,
        "fee": None,
        "portfolio_id": 1,
    }


# ── Pure helper ───────────────────────────────────────────────────────

def test_helper_future_date_warns():
    warnings = compute_trade_warnings(
        [], ticker="ABC", transaction_date="2026-01-02", qty=1,
        price=10, transaction_type="BUY", exclude_id=999,
        today=date(2026, 1, 1),
    )
    assert warnings == ["date is in the future"]
    # Boundary: TODAY is not the future.
    assert compute_trade_warnings(
        [], ticker="ABC", transaction_date="2026-01-01", qty=1,
        price=10, transaction_type="BUY", exclude_id=999,
        today=date(2026, 1, 1),
    ) == []


def test_helper_oversell():
    rows = [row(1, 10, 10)]
    warnings = compute_trade_warnings(
        rows, ticker="ABC", transaction_date="2026-08-02", qty=15,
        price=12, transaction_type="SELL", exclude_id=999,
        today=date(2099, 1, 1),
    )
    assert len(warnings) == 1
    assert "exceeds the 10 shares held" in warnings[0]


def test_helper_oversell_boundary_and_partial():
    rows = [row(1, 10, 10)]
    # Selling exactly what is held is fine.
    assert compute_trade_warnings(
        rows, ticker="ABC", transaction_date="2026-08-02", qty=10,
        price=12, transaction_type="SELL", exclude_id=999,
        today=date(2099, 1, 1),
    ) == []
    # A partial sale is fine.
    assert compute_trade_warnings(
        rows, ticker="ABC", transaction_date="2026-08-02", qty=4,
        price=12, transaction_type="SELL", exclude_id=999,
        today=date(2099, 1, 1),
    ) == []


def test_helper_oversell_tolerance():
    # 0.1 + 0.2 != 0.3 in binary; the tolerance must absorb the residue.
    rows = [row(1, 10, 0.1), row(2, 10, 0.2)]
    assert compute_trade_warnings(
        rows, ticker="ABC", transaction_date="2026-08-02", qty=0.3,
        price=12, transaction_type="SELL", exclude_id=999,
        today=date(2099, 1, 1),
    ) == []


def test_helper_oversell_ignores_later_rows():
    rows = [row(1, 10, 10, date_="2026-08-01"),
            row(2, 10, 100, date_="2026-09-01")]
    warnings = compute_trade_warnings(
        rows, ticker="ABC", transaction_date="2026-08-02", qty=15,
        price=12, transaction_type="SELL", exclude_id=999,
        today=date(2099, 1, 1),
    )
    assert len(warnings) == 1
    assert "exceeds the 10 shares held" in warnings[0]


def test_helper_duplicate_requires_all_five_fields():
    base = row(1, 10, 2, date_="2026-08-01")
    assert any(
        "duplicate" in w
        for w in compute_trade_warnings(
            [base], ticker="ABC", transaction_date="2026-08-01", qty=2,
            price=10, transaction_type="BUY", exclude_id=999,
            today=date(2099, 1, 1),
        )
    )
    # Each field changed in turn kills the match.
    mutations = [
        dict(ticker="XYZ"),
        dict(transaction_date="2026-08-02"),
        dict(transaction_type="SELL"),
        dict(qty=3),
        dict(price=11),
    ]
    for change in mutations:
        args = {"ticker": "ABC", "transaction_date": "2026-08-01",
                "qty": 2, "price": 10, "transaction_type": "BUY",
                "exclude_id": 999, "today": date(2099, 1, 1)}
        args.update(change)
        assert compute_trade_warnings([base], **args) == [], change


def test_helper_duplicate_excludes_self():
    base = row(1, 10, 2)
    assert compute_trade_warnings(
        [base], ticker="ABC", transaction_date="2026-08-01", qty=2,
        price=10, transaction_type="BUY", exclude_id=1,
        today=date(2099, 1, 1),
    ) == []


def test_helper_clean_buy_has_no_warnings():
    assert compute_trade_warnings(
        [], ticker="ABC", transaction_date="2026-08-01", qty=5,
        price=10, transaction_type="BUY", exclude_id=999,
    ) == []


# ── Routes ────────────────────────────────────────────────────────────

def test_post_returns_empty_warnings_for_clean_buy(client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    body = {"ticker": "ABC", "date": "2026-08-01", "price": 10,
            "qty": 2, "type": "BUY"}
    response = client.post("/api/transactions", json=body)
    assert response.status_code == 201
    assert response.get_json()["warnings"] == []
    assert len(db.get_transactions(1)) == 1


def test_post_reports_oversell_but_still_writes(client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    seed(10, 10)
    response = client.post("/api/transactions", json={
        "ticker": "ABC", "date": "2026-08-02", "price": 12,
        "qty": 15, "type": "SELL"})
    assert response.status_code == 201
    warnings = response.get_json()["warnings"]
    assert len(warnings) == 1
    assert "exceeds the 10 shares held" in warnings[0]
    assert len(db.get_transactions(1)) == 2


def test_post_reports_future_date_but_still_writes(client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    response = client.post("/api/transactions", json={
        "ticker": "ABC", "date": "2999-01-01", "price": 10,
        "qty": 2, "type": "BUY"})
    assert response.status_code == 201
    assert any("future" in w for w in response.get_json()["warnings"])
    assert len(db.get_transactions(1)) == 1


def test_post_reports_same_day_duplicate(client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    body = {"ticker": "ABC", "date": "2026-08-01", "price": 10,
            "qty": 2, "type": "BUY"}
    assert client.post("/api/transactions", json=body).get_json()[
        "warnings"] == []
    second = client.post("/api/transactions", json=body)
    assert second.status_code == 201
    assert any("duplicate" in w for w in second.get_json()["warnings"])
    assert len(db.get_transactions(1)) == 2


def test_put_does_not_flag_itself(client, fake_market):
    seed(10, 10, date_="2026-08-01")
    sell_id = seed(12, 4, side="SELL", date_="2026-08-02")
    body = {"date": "2026-08-02", "price": 12, "qty": 4, "type": "SELL"}
    response = client.put(f"/api/transactions/{sell_id}", json=body)
    assert response.status_code == 200
    assert response.get_json()["warnings"] == []


def test_put_reports_warning_and_applies_edit(client, fake_market):
    seed(10, 10, date_="2026-08-01")
    sell_id = seed(12, 4, side="SELL", date_="2026-08-02")
    response = client.put(f"/api/transactions/{sell_id}", json={
        "date": "2026-08-02", "price": 12, "qty": 15, "type": "SELL"})
    assert response.status_code == 200
    warnings = response.get_json()["warnings"]
    assert any("exceeds the 10 shares held" in w for w in warnings)
    assert db.get_transaction(sell_id, 1)["qty"] == 15


def test_import_preview_and_commit_have_no_warnings_field(
        client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    text = "ABC\t16 Mar 2026\t10\t2"
    preview = client.post("/api/transactions/import/preview",
                          json={"text": text})
    assert preview.status_code == 200
    assert "warnings" not in preview.get_json()
    commit = client.post("/api/transactions/import/commit",
                         json={"text": text})
    assert commit.status_code == 200
    assert "warnings" not in commit.get_json()


# ── Frontend wiring (source locks; pytest cannot run the browser) ─────

def test_ledger_html_has_hidden_warning_block():
    html = LEDGER_HTML.read_text()
    assert '<ul class="tx-warnings" hidden>' in html


def test_ledger_js_paints_warnings_from_the_reply():
    js = LEDGER_JS.read_text()
    assert 'const txWarningsEl = document.querySelector(".tx-warnings")' in js
    assert "function setTradeWarnings(" in js
    assert "txWarningsEl.hidden = messages.length === 0" in js
    assert "setTradeWarnings(saved?.warnings || [])" in js
    # A fresh submit clears the previous save's warnings.
    assert "txErrorEl.hidden = true;\n    setTradeWarnings([]);" in js


def test_ledger_css_styles_the_warning_block():
    assert ".tx-warnings {" in LEDGER_CSS.read_text()
