"""Portfolio migration and isolation tests; every database is temporary."""

import sqlite3

import pytest

import db
from conftest import make_quote


def test_legacy_rows_migrate_once_with_facts_and_global_watchlist(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE watchlist (symbol TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO watchlist VALUES ('AAPL')")
        conn.execute("""CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
            transaction_date TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, currency TEXT NOT NULL, fx_rate REAL,
            fee REAL, transaction_type TEXT NOT NULL)""")
        conn.execute("""INSERT INTO transactions VALUES
            (42, 'AAPL', '2026-01-01', 12.5, 2, 'USD', 1.31, 3.5, 'BUY')""")
    db.init()
    db.init()
    assert db.get_portfolios() == [{"id": 1, "name": "Main", "sort_order": 0}]
    row = db.get_transaction(42, 1)
    assert (row["id"], row["portfolio_id"], row["fee"], row["fx_rate"]) == (
        42, 1, 3.5, 1.31)
    assert db.get_symbols() == ["AAPL"]
    with pytest.raises(sqlite3.IntegrityError):
        db.add_transaction("AAPL", "2026-01-02", 1, 1, "CAD", "BUY", 1,
                           portfolio_id=999)


def test_oldest_schema_migrates_missing_fee_and_fx(tmp_path, monkeypatch):
    path = tmp_path / "oldest.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
            transaction_date TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, currency TEXT NOT NULL,
            transaction_type TEXT NOT NULL)""")
        conn.execute("INSERT INTO transactions VALUES (7, 'AAPL', '2026-01-01', 10, 1, 'USD', 'BUY')")
        conn.execute("INSERT INTO transactions VALUES (8, 'CM', '2026-01-02', 20, 1, 'CAD', 'BUY')")
    db.init()
    db.init()
    assert db.get_transaction(7)["fee"] is None
    assert db.get_transaction(7)["fx_rate"] is None
    assert db.get_transaction(8)["fx_rate"] == 1.0
    assert [row["id"] for row in db.get_transactions()] == [8, 7]


def test_failed_rebuild_rolls_back_legacy_table(tmp_path, monkeypatch):
    path = tmp_path / "broken.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, ticker TEXT NOT NULL,
            transaction_date TEXT NOT NULL, price REAL NOT NULL,
            qty REAL NOT NULL, currency TEXT NOT NULL,
            transaction_type TEXT NOT NULL)""")
        conn.execute("INSERT INTO transactions VALUES (9, 'AAPL', '2026-01-01', 10, 1, 'CAD', 'CORRUPT')")
    with pytest.raises(sqlite3.IntegrityError):
        db.init()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT id, transaction_type FROM transactions").fetchone() == (9, "CORRUPT")
        assert "portfolio_id" not in [row[1] for row in conn.execute("PRAGMA table_info(transactions)")]
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'transactions_scoped'").fetchone() is None


def test_portfolio_management_and_atomic_delete(client):
    main = client.get("/api/portfolios").json[0]
    assert main["name"] == "Main"
    second = client.post("/api/portfolios", json={"name": "  Retirement  "})
    assert second.status_code == 201
    pid = second.json["id"]
    assert second.json["name"] == "Retirement"
    assert client.post("/api/portfolios", json={"name": "retirement"}).status_code == 409
    assert client.patch(f"/api/portfolios/{pid}/move", json={"direction": "up"}).status_code == 200
    assert [p["id"] for p in client.get("/api/portfolios").json] == [pid, main["id"]]
    assert client.delete(f"/api/portfolios/{pid}", json={"name": "wrong"}).status_code == 409
    assert client.delete(f"/api/portfolios/{pid}", json={"name": "Retirement"}).status_code == 204
    assert client.delete(f"/api/portfolios/{main['id']}", json={"name": "Main"}).status_code == 409


@pytest.mark.parametrize("bad,status", [("x", 400), ("0", 400), ("-1", 400), ("999", 404)])
def test_invalid_portfolio_is_rejected_before_market_calls(client, fake_market, bad, status):
    assert client.get(f"/api/portfolio/summary?portfolio_id={bad}").status_code == status
    assert client.get(f"/api/transactions?portfolio_id={bad}").status_code == status
    assert client.post(f"/api/transactions?portfolio_id={bad}", json={}).status_code == status


def test_same_ticker_is_isolated_in_summary_ledger_and_deletion(client, fake_market):
    second = client.post("/api/portfolios", json={"name": "Growth"}).json["id"]
    first_id = db.add_transaction("AAPL", "2026-01-01", 10, 2, "CAD", "BUY", 1,
                                  portfolio_id=1)
    other_id = db.add_transaction("AAPL", "2026-01-01", 20, 3, "CAD", "BUY", 1,
                                  portfolio_id=second)
    fake_market.quotes["AAPL"] = make_quote("AAPL", 30, 28, "CAD")
    assert client.get("/api/portfolio/summary?portfolio_id=1").json["total_value"] == 60
    assert client.get(f"/api/portfolio/summary?portfolio_id={second}").json["total_value"] == 90
    assert [t["id"] for t in client.get("/api/transactions?portfolio_id=1").json] == [first_id]
    assert [t["id"] for t in client.get(f"/api/transactions?portfolio_id={second}").json] == [other_id]
    assert client.delete(f"/api/transactions/{other_id}?portfolio_id=1").status_code == 404
    assert client.delete("/api/transactions/ticker/AAPL?portfolio_id=1").status_code == 204
    assert db.get_transaction(other_id, second) is not None


def test_shared_watchlist_survives_portfolio_removal(client):
    other = client.post("/api/portfolios", json={"name": "Other"}).json["id"]
    db.add_symbol("AAPL")
    db.add_transaction("AAPL", "2026-01-01", 1, 1, "CAD", "BUY", 1,
                       portfolio_id=other)
    assert client.delete(f"/api/portfolios/{other}", json={"name": "Other"}).status_code == 204
    assert db.get_symbols() == ["AAPL"]
    assert db.get_transactions(other) == []


@pytest.mark.parametrize("url", [
    "/api/portfolio/history?period=5D", "/api/portfolio/allocation?by=sector",
    "/api/portfolio/realized", "/api/transactions/import/preview",
    "/api/transactions/import/commit", "/api/transactions/1",
    "/api/transactions/ticker/AAPL",
])
def test_all_portfolio_endpoints_reject_deleted_id(client, url):
    other = client.post("/api/portfolios", json={"name": "Other"}).json["id"]
    assert client.delete(f"/api/portfolios/{other}", json={"name": "Other"}).status_code == 204
    separator = "&" if "?" in url else "?"
    target = f"{url}{separator}portfolio_id={other}"
    if "import" in url:
        response = client.post(target, json={"text": "AAPL\t16 Mar 2026\t1\t1"})
    elif url.startswith("/api/transactions/"):
        response = client.delete(target)
    else:
        response = client.get(target)
    assert response.status_code == 404


def test_cross_portfolio_edit_and_import_destination(client, fake_market):
    other = client.post("/api/portfolios", json={"name": "Other"}).json["id"]
    tx = db.add_transaction("AAPL", "2026-01-01", 10, 1, "CAD", "BUY", 1,
                            portfolio_id=other)
    assert client.put(f"/api/transactions/{tx}?portfolio_id=1",
                      json={"date": "2026-01-01", "price": 20, "qty": 2,
                            "type": "SELL"}).status_code == 404
    assert db.get_transaction(tx, other)["price"] == 10
    fake_market.quotes["AAPL"] = make_quote("AAPL", 30, 29, "CAD")
    text = "AAPL\t16 Mar 2026\t10\t2"
    assert client.post("/api/transactions/import/preview?portfolio_id=1",
                       json={"text": text}).json["valid_count"] == 1
    assert len(db.get_transactions(1)) == 0
    assert client.post(f"/api/transactions/import/commit?portfolio_id={other}",
                       json={"text": text}).json["imported"] == 1
    assert len(db.get_transactions(1)) == 0
    assert len(db.get_transactions(other)) == 2


@pytest.mark.parametrize("name", ["", "   ", 4, None, "x" * 61])
def test_invalid_names_do_not_create_portfolios(client, name):
    assert client.post("/api/portfolios", json={"name": name}).status_code == 400
    assert len(db.get_portfolios()) == 1


def test_names_trim_and_duplicate_on_rename(client):
    first = client.post("/api/portfolios", json={"name": "Épargne"}).json["id"]
    other = client.post("/api/portfolios", json={"name": "Other"}).json["id"]
    assert client.patch(f"/api/portfolios/{other}",
                        json={"name": "  Retirement "}).json["name"] == "Retirement"
    assert client.patch(f"/api/portfolios/{first}",
                        json={"name": "retirement"}).status_code == 409
    assert db.get_portfolio(first)["name"] == "Épargne"
    assert client.post("/api/portfolios", json={"name": "éPARGNE"}).status_code == 409


def test_history_and_realized_replay_only_selected_trades(client, fake_market):
    other = client.post("/api/portfolios", json={"name": "Other"}).json["id"]
    db.add_transaction("AAPL", "2026-08-28", 100, 2, "CAD", "BUY", 1,
                       portfolio_id=1)
    db.add_transaction("AAPL", "2026-08-31", 120, 1, "CAD", "SELL", 1,
                       portfolio_id=1)
    db.add_transaction("AAPL", "2026-08-28", 30, 4, "CAD", "BUY", 1,
                       portfolio_id=other)
    fake_market.histories["AAPL"] = {"2026-08-28": 100, "2026-08-31": 110}
    first = client.get("/api/portfolio/history?period=5D&portfolio_id=1").json
    second = client.get(f"/api/portfolio/history?period=5D&portfolio_id={other}").json
    assert first["costs"] == [200, 80]
    assert second["costs"] == [120, 120]
    assert first["values"] != second["values"]
    assert len(client.get("/api/portfolio/realized?portfolio_id=1").json["rows"]) == 1
    assert client.get(f"/api/portfolio/realized?portfolio_id={other}").json["rows"] == []
