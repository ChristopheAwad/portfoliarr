"""Focused contracts for production-safe operational logging."""

import logging
import re

import db
import app as app_module
from conftest import make_quote


REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def messages(caplog, event):
    """Return records whose stable key-value message starts with event."""
    prefix = f"event={event} "
    return [record for record in caplog.records
            if record.getMessage().startswith(prefix)]


def test_log_level_resolution_defaults_validates_and_falls_back():
    assert app_module._resolve_log_level(None) == ("INFO", None)
    assert app_module._resolve_log_level("debug") == ("DEBUG", None)
    assert app_module._resolve_log_level("CRITICAL") == ("CRITICAL", None)
    assert app_module._resolve_log_level("verbose") == ("INFO", "verbose")


def test_configured_formatter_is_stable_and_targets_stderr():
    root = logging.getLogger()
    handler = next(
        handler for handler in root.handlers
        if isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is __import__("sys").stderr
    )
    assert handler.formatter.datefmt == "%Y-%m-%dT%H:%M:%S%z"
    rendered = handler.formatter.format(logging.LogRecord(
        "app", logging.INFO, __file__, 1, "event=test", (), None
    ))
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{4} "
        r"INFO app event=test$",
        rendered,
    )


def test_yfinance_info_chatter_is_suppressed():
    assert logging.getLogger("yfinance").level == logging.WARNING


def test_every_response_gets_a_new_server_request_id(client):
    first = client.get("/definitely-not-a-route", headers={
        "X-Request-ID": "do-not-trust-this",
    })
    second = client.get("/api/indices?category=invalid")

    first_id = first.headers["X-Request-ID"]
    second_id = second.headers["X-Request-ID"]
    assert first.status_code == 404
    assert second.status_code == 400
    assert REQUEST_ID_RE.fullmatch(first_id)
    assert REQUEST_ID_RE.fullmatch(second_id)
    assert first_id != second_id
    assert first_id != "do-not-trust-this"


def test_unhandled_error_is_correlated_and_keeps_traceback(
        client, monkeypatch, caplog):
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setattr(db, "get_symbols", lambda: (_ for _ in ()).throw(
        RuntimeError("simulated logging failure")
    ))

    with caplog.at_level(logging.ERROR):
        response = client.get("/api/watchlist")

    (record,) = messages(caplog, "unhandled_error")
    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 500
    assert f"request_id={request_id}" in record.getMessage()
    assert "method=GET" in record.getMessage()
    assert "path='/api/watchlist'" in record.getMessage()
    assert record.exc_info is not None


def test_fast_request_is_debug_and_query_is_not_logged(
        client, monkeypatch, caplog):
    monkeypatch.setattr(app_module, "SLOW_REQUEST_MS", 10**9)
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/indices?category=invalid&secret=private")

    (record,) = messages(caplog, "request_complete")
    text = record.getMessage()
    assert record.levelno == logging.DEBUG
    assert f"request_id={response.headers['X-Request-ID']}" in text
    assert "method=GET" in text
    assert "path='/api/indices'" in text
    assert "status=400" in text
    assert "secret" not in text and "private" not in text


def test_slow_request_is_one_warning_not_a_duplicate(
        client, monkeypatch, caplog):
    monkeypatch.setattr(app_module, "SLOW_REQUEST_MS", 0)
    with caplog.at_level(logging.DEBUG):
        client.get("/api/indices?category=invalid")

    records = messages(caplog, "request_complete")
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING


def test_watchlist_success_audits_only_confirmed_changes(
        client, fake_market, caplog):
    fake_market.quotes["AAPL"] = make_quote("AAPL", 100, 99)
    with caplog.at_level(logging.INFO):
        added = client.post("/api/watchlist", json={"symbol": "aapl"})
        duplicate = client.post("/api/watchlist", json={"symbol": "AAPL"})
        removed = client.delete("/api/watchlist/AAPL")
        missing = client.delete("/api/watchlist/AAPL")

    assert (added.status_code, duplicate.status_code,
            removed.status_code, missing.status_code) == (201, 409, 204, 404)
    (add_record,) = messages(caplog, "watchlist_added")
    (remove_record,) = messages(caplog, "watchlist_removed")
    assert f"request_id={added.headers['X-Request-ID']}" in add_record.getMessage()
    assert "symbol='AAPL'" in add_record.getMessage()
    assert f"request_id={removed.headers['X-Request-ID']}" in remove_record.getMessage()


def test_transaction_create_edit_delete_audits_exclude_financial_values(
        client, fake_market, caplog):
    fake_market.quotes["AAPL"] = make_quote(
        "AAPL", 100, 99, currency="CAD"
    )
    create_body = {
        "ticker": "AAPL", "date": "2026-01-23",
        "price": 98765.4321, "qty": 12345.6789, "type": "BUY",
    }
    with caplog.at_level(logging.INFO):
        created = client.post("/api/transactions", json=create_body)
        tx_id = created.get_json()["id"]
        updated = client.put(f"/api/transactions/{tx_id}", json={
            "date": "2026-02-24", "price": 87654.321,
            "qty": 23456.789, "type": "SELL",
        })
        deleted = client.delete(f"/api/transactions/{tx_id}")

    assert (created.status_code, updated.status_code, deleted.status_code) == (
        201, 200, 204
    )
    (created_record,) = messages(caplog, "transaction_created")
    (updated_record,) = messages(caplog, "transaction_updated")
    (deleted_record,) = messages(caplog, "transaction_deleted")
    assert f"tx_id={tx_id}" in created_record.getMessage()
    assert "ticker='AAPL'" in created_record.getMessage()
    assert "type='BUY'" in created_record.getMessage()
    assert "type='SELL'" in updated_record.getMessage()
    assert f"tx_id={tx_id}" in deleted_record.getMessage()
    audit_text = "\n".join(record.getMessage() for record in (
        created_record, updated_record, deleted_record
    ))
    for private_value in ("98765.4321", "12345.6789", "87654.321",
                          "23456.789", "2026-01-23", "2026-02-24"):
        assert private_value not in audit_text


def test_import_has_one_summary_and_never_logs_pasted_text(
        client, fake_market, caplog):
    fake_market.quotes["AAPL"] = make_quote(
        "AAPL", 100, 99, currency="CAD"
    )
    private_text = "AAPL\t16 Mar 2026\t76543.21\t34567.89"
    with caplog.at_level(logging.INFO):
        response = client.post("/api/transactions/import/commit", json={
            "text": private_text,
        })

    assert response.status_code == 200
    (record,) = messages(caplog, "transaction_import_completed")
    assert "imported_count=1" in record.getMessage()
    assert "failed_count=0" in record.getMessage()
    assert private_text not in caplog.text
    assert "76543.21" not in record.getMessage()
    assert not messages(caplog, "transaction_created")


def test_indices_partial_failure_is_one_aggregate_warning(
        client, fake_market, caplog):
    symbols = [item["symbol"] for item in
               app_module.MARKET_CATEGORIES["europe"]["instruments"]]
    fake_market.quotes[symbols[0]] = make_quote(symbols[0], 100, 99)
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/indices?category=europe")

    records = messages(caplog, "market_quotes_degraded")
    assert response.status_code == 200
    assert len(records) == 1
    text = records[0].getMessage()
    assert f"request_id={response.headers['X-Request-ID']}" in text
    assert "operation=indices" in text
    assert "category='europe'" in text
    assert "attempted=4 succeeded=1 failed=3" in text
    assert repr(symbols[1:]) in text
    assert "error_types=['KeyError']" in text
    assert records[0].exc_info is None


def test_transaction_list_logs_previously_silent_quote_degradation(
        client, fake_market, caplog):
    db.add_transaction("DEAD", "2026-01-01", 10, 2, "CAD", "BUY", 1.0)
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/transactions")

    (record,) = messages(caplog, "market_quotes_degraded")
    assert response.status_code == 200
    assert "operation=transaction_list" in record.getMessage()
    assert "attempted=1 succeeded=0 failed=1" in record.getMessage()
    assert "symbols=['DEAD']" in record.getMessage()
    assert record.exc_info is None


def test_portfolio_summary_uses_shared_aggregate_warning(
        client, fake_market, caplog):
    db.add_transaction("DEAD", "2026-01-01", 10, 2, "CAD", "BUY", 1.0)
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/portfolio/summary")

    (record,) = messages(caplog, "market_quotes_degraded")
    assert response.status_code == 200
    assert "operation=portfolio_summary" in record.getMessage()
    assert "attempted=1 succeeded=0 failed=1" in record.getMessage()
    assert "symbols=['DEAD']" in record.getMessage()
    assert record.exc_info is None


def test_portfolio_history_uses_shared_aggregate_warning(
        client, fake_market, caplog):
    db.add_transaction("DEAD", "2026-01-01", 10, 2, "CAD", "BUY", 1.0)
    with caplog.at_level(logging.WARNING):
        response = client.get("/api/portfolio/history?period=1M")

    (record,) = messages(caplog, "market_history_degraded")
    assert response.status_code == 200
    assert "operation=portfolio_history" in record.getMessage()
    assert "period='1M'" in record.getMessage()
    assert "attempted=1 succeeded=0 failed=1" in record.getMessage()
    assert "symbols=['DEAD']" in record.getMessage()
    assert record.exc_info is None


def test_empty_comparison_history_is_logged_as_a_failed_attempt(
        client, fake_market, caplog):
    fake_market.histories["SPY"] = {}
    with caplog.at_level(logging.WARNING):
        response = client.get(
            "/api/portfolio/history?period=1M&benchmark=SPY"
        )

    (record,) = messages(caplog, "market_history_degraded")
    assert response.status_code == 200
    assert "operation=comparison_history" in record.getMessage()
    assert "attempted=1 succeeded=0 failed=1" in record.getMessage()
    assert "symbols=['SPY']" in record.getMessage()
    assert "error_types=['EmptyHistory']" in record.getMessage()
    assert record.exc_info is None


def test_failed_search_logs_length_not_query(client, monkeypatch, caplog):
    query = "private-investment-search"
    monkeypatch.setattr(app_module, "search_tickers", lambda _query: (
        _ for _ in ()
    ).throw(RuntimeError("Yahoo unavailable")))
    with caplog.at_level(logging.WARNING):
        response = client.get(f"/api/search?q={query}")

    (record,) = messages(caplog, "search_failed")
    assert response.status_code == 503
    assert f"query_length={len(query)}" in record.getMessage()
    assert "error_type=RuntimeError" in record.getMessage()
    assert query not in caplog.text
    assert record.exc_info is None
