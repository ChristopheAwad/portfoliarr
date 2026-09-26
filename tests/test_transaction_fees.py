"""Fee facts and their effects on portfolio accounting."""

import sqlite3

import pytest

import db
from conftest import make_quote


def seed(price, qty, side="BUY", fee=None, date="2026-08-01",
         currency="CAD", fx=1.0, ticker="ABC"):
    return db.add_transaction(ticker, date, price, qty, currency, side, fx,
                              fee=fee, portfolio_id=1)


def test_fee_schema_and_old_database_migration(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
            transaction_date TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, currency TEXT NOT NULL,
            transaction_type TEXT NOT NULL)""")
        conn.execute("""INSERT INTO transactions
            (ticker, transaction_date, price, qty, currency, transaction_type)
            VALUES ('ABC', '2026-08-01', 10, 2, 'CAD', 'BUY')""")
    db.init()
    db.init()
    with sqlite3.connect(path) as conn:
        columns = {row[1]: row for row in conn.execute(
            "PRAGMA table_info(transactions)")}
    assert columns["fee"][2] == "REAL"
    assert columns["fee"][3] == 0
    old = db.get_transaction(1, 1)
    assert old["fee"] is None
    assert old["fx_rate"] == 1.0
    assert (old["price"], old["qty"], old["transaction_date"]) == (
        10, 2, "2026-08-01")
    new_id = seed(10, 2, fee=1.25)
    assert db.get_transaction(new_id, 1)["fee"] == 1.25
    assert db.update_transaction(new_id, "2026-08-02", 11, 2,
                                 "SELL", 1.0, fee=0.0, portfolio_id=1)
    assert db.get_transaction(new_id, 1)["fee"] == 0.0
    assert db.get_transactions(1)[0]["fee"] == 0.0


@pytest.mark.parametrize("bad", [True, "1", -1, [], {}, float("nan"),
                                     float("inf"), -float("inf")])
def test_invalid_fee_never_changes_a_row(client, fake_market, bad):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    body = {"ticker": "ABC", "date": "2026-08-01", "price": 10,
            "qty": 2, "type": "BUY", "fee": bad}
    response = client.post("/api/transactions", json=body)
    assert response.status_code == 400
    assert "fee" in response.get_json()["error"]
    assert db.get_transactions(1) == []
    tx_id = seed(10, 2, fee=1.25)
    response = client.put(f"/api/transactions/{tx_id}", json=body)
    assert response.status_code == 400
    assert db.get_transaction(tx_id, 1)["fee"] == 1.25


def test_post_put_and_import_legacy_fee(client, fake_market):
    fake_market.quotes["ABC"] = make_quote("ABC", 12, 11, "CAD")
    body = {"ticker": "ABC", "date": "2026-08-01", "price": 10,
            "qty": 2, "type": "BUY"}
    first = client.post("/api/transactions", json=body)
    assert first.status_code == 201
    assert first.get_json()["fee"] is None
    assert db.get_transaction(first.get_json()["id"], 1)["fee"] is None
    second = client.post("/api/transactions", json={**body, "fee": 0})
    assert second.get_json()["fee"] == 0
    change = client.put(f"/api/transactions/{first.get_json()['id']}",
                        json={**body, "date": "2026-08-02", "fee": 3.75,
                              "ticker": "DIFFERENT", "currency": "USD"})
    assert change.status_code == 200
    assert change.get_json()["fee"] == 3.75
    assert change.get_json()["ticker"] == "ABC"
    assert change.get_json()["currency"] == "CAD"
    assert client.get("/api/transactions").get_json()[0]["fee"] == 3.75
    text = "ABC\t16 Mar 2026\t10\t2"
    preview = client.post("/api/transactions/import/preview",
                          json={"text": text})
    assert preview.status_code == 200
    assert preview.get_json()["rows"][0]["transaction_type"] == "BUY"
    assert len(db.get_transactions(1)) == 2
    assert client.post("/api/transactions/import/commit",
                       json={"text": text}).get_json()["imported"] == 1
    assert db.get_transactions(1)[-1]["fee"] is None


def test_summary_ledger_and_history_include_fees(client, fake_market):
    seed(100, 10, fee=10)
    seed(120, 4, "SELL", fee=8, date="2026-08-03")
    fake_market.quotes["ABC"] = make_quote("ABC", 130, 125, "CAD")
    fake_market.histories["ABC"] = {"2026-08-01": 100,
                                     "2026-08-03": 120,
                                     "2026-08-04": 130}
    summary = client.get("/api/portfolio/summary").get_json()
    assert summary["total_value"] == 780
    assert summary["cost_basis"] == 538   # 1010 - (480 - 8)
    assert summary["total_gain"] == 242
    rows = client.get("/api/transactions").get_json()
    assert rows[0]["fee"] == 8
    assert rows[0]["group_cost_basis"] == 538
    assert rows[0]["group_avg_cost"] == 101  # partial sale keeps basis
    assert rows[0]["group_total_gain"] == 242
    assert rows[0]["total_gain"] == 32  # 4*130 - 4*120 - 8
    assert rows[1]["total_gain"] == 290  # 10*130 - 10*100 - 10
    history = client.get("/api/portfolio/history?period=1M").get_json()
    assert history["costs"][-1] == 538


def test_usd_stored_rates_and_native_fee(client, fake_market):
    seed(100, 10, fee=10, currency="USD", fx=1.2)
    seed(120, 4, "SELL", fee=8, date="2026-08-03",
         currency="USD", fx=1.3)
    fake_market.quotes["ABC"] = make_quote("ABC", 130, 125, "USD")
    fake_market.fx_rates["USDCAD"] = 1.4
    summary = client.get("/api/portfolio/summary").get_json()
    assert summary["cost_basis"] == pytest.approx(1010 * 1.2 - 472 * 1.3)
    cad = client.get("/api/transactions").get_json()[0]
    assert cad["group_cost_basis"] == pytest.approx(summary["cost_basis"])
    assert cad["group_value"] == pytest.approx(6 * 130 * 1.4)
    assert cad["group_avg_cost"] == pytest.approx(101 * 1.2)
    native = client.get("/api/transactions?currency=NATIVE").get_json()[0]
    assert native["group_cost_basis"] == 538
    assert native["group_avg_cost"] == 101
    assert native["fee"] == 8


def test_realized_fees_partial_and_short_crossing(client, fake_market):
    seed(100, 10, fee=10)
    seed(120, 15, "SELL", fee=15, date="2026-08-02")
    seed(90, 8, "BUY", fee=8, date="2026-08-03")
    fake_market.names["ABC"] = "ABC"
    result = client.get("/api/portfolio/realized").get_json()
    sale = result["rows"][0]
    assert sale["avg_cost"] == 101
    assert sale["realized"] == pytest.approx(10 * (120 - 1 - 101))
    assert sale["realized_pct"] == pytest.approx(180 / 1010 * 100)
    # The excess sell opens a 5-share short at 119; the first 5 of
    # the covering BUY cost 91 each. The excess 3 open a new long.
    assert result["total_realized"] == pytest.approx(180 + 5 * (119 - 91))
    row = client.get("/api/transactions").get_json()[0]
    assert row["group_avg_cost"] == 91


def test_realized_fee_degrades_with_missing_fx(client, fake_market):
    seed(100, 2, fee=1, currency="USD", fx=None)
    seed(120, 2, "SELL", fee=2, date="2026-08-02",
         currency="USD", fx=1.3)
    result = client.get("/api/portfolio/realized").get_json()
    assert result["total_realized"] is None
    assert result["rows"][0]["avg_cost"] == 100.5
    assert result["rows"][0]["realized"] is None
    assert result["rows"][0]["degraded"]


def test_fee_changes_costs_but_not_price_only_twr(client, fake_market):
    buy = seed(100, 2, date="2026-08-01")
    sell = seed(120, 1, "SELL", date="2026-08-02")  # Saturday
    fake_market.histories["ABC"] = {"2026-08-01": 100,
                                     "2026-08-03": 120,
                                     "2026-08-04": 130}
    before = client.get("/api/portfolio/history?period=1M").get_json()
    assert db.update_transaction(buy, "2026-08-01", 100, 2, "BUY", 1,
                                 fee=4, portfolio_id=1)
    assert db.update_transaction(sell, "2026-08-02", 120, 1, "SELL", 1,
                                 fee=3, portfolio_id=1)
    after = client.get("/api/portfolio/history?period=1M").get_json()
    assert after["costs"] == [204, 87, 87]  # weekend sell lands on Monday
    for key in ("labels", "values", "index_values", "twrr_pct"):
        assert after[key] == before[key]


def test_fee_on_short_open_and_cover(client, fake_market):
    seed(100, 3, "SELL", fee=6)
    seed(90, 3, "BUY", fee=3, date="2026-08-02")
    result = client.get("/api/portfolio/realized").get_json()
    assert result["rows"][0]["avg_cost"] == 98
    assert result["rows"][0]["realized"] == 0
    assert result["total_realized"] == 3 * (98 - 91)


def test_fee_with_failed_quote_still_updates_average(client, fake_market):
    seed(100, 2, fee=8)
    rows = client.get("/api/transactions").get_json()
    assert rows[0]["group_avg_cost"] == 104
    assert "group_value" not in rows[0]
