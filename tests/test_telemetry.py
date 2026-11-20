import re
import sqlite3
from threading import Thread

import pytest

import app as routes
import db
import telemetry
from conftest import seed_user, sign_in


SETTINGS = "/api/telemetry/settings"
REPORT = "/api/telemetry/report"
CLIENT = "/api/telemetry/client"


def marker(client):
    match = re.search(r'data-local-telemetry-generation="([0-9a-f]{32})"',
                      client.get("/").get_data(as_text=True))
    return match[1] if match else None


def batch(generation, duration=2001):
    return dict(generation=generation, page="dashboard", viewport="narrow",
                sections=[dict(metric="dashboard_summary", outcome="failed"),
                          dict(metric="dashboard_chart", outcome="ready",
                               duration_ms=duration)])


def test_owner_opt_in_report_and_old_page(client, fresh_db):
    path = fresh_db.with_name("telemetry.db")
    assert client.get(SETTINGS).json == {"enabled": False}
    assert marker(client) is None
    assert client.get(REPORT).status_code == 404
    assert client.put(SETTINGS, json={"enabled": True}).json == {"enabled": True}
    original = marker(client)
    assert original
    assert client.get(REPORT).json["first_event_minute"] is None
    assert not path.exists()
    assert client.put(SETTINGS, json={"enabled": True}).status_code == 200
    assert marker(client) == original
    for duration in (2000, 2001):
        assert client.post(CLIENT, json=batch(original, duration)).status_code == 204
    report = client.get(REPORT)
    assert report.headers["Cache-Control"] == "no-store"
    assert report.json["sections"]["dashboard_chart"]["ready"] == 2
    assert report.json["sections"]["dashboard_chart"]["slow"] == 1
    assert report.json["sections"]["dashboard_summary"]["failed"] == 2
    assert report.json["recent_slow_chart"][0]["viewport"] == "narrow"
    assert original not in report.get_data(as_text=True)
    assert original.encode() not in path.read_bytes()
    assert client.put(SETTINGS, json={"enabled": False}).status_code == 200
    assert marker(client) is None
    assert client.post(CLIENT, json=batch(original)).status_code == 204
    assert client.put(SETTINGS, json={"enabled": True}).status_code == 200
    assert marker(client) != original
    assert client.post(CLIENT, json=batch(original)).status_code == 204
    assert client.get(REPORT).json["sections"]["dashboard_chart"]["ready"] == 2


def test_access_and_payload_validation(client, fresh_db):
    anonymous = routes.app.test_client()
    assert anonymous.post(CLIENT, json=batch("a" * 32)).status_code == 401
    assert anonymous.get(REPORT).headers["Cache-Control"] == "no-store"
    regular = routes.app.test_client()
    sign_in(regular, seed_user("regular"))
    assert regular.get(REPORT).status_code == 403
    assert regular.put(SETTINGS, json={"enabled": True}).status_code == 403
    assert client.put(SETTINGS, json={"enabled": "true"}).status_code == 400
    assert client.put(SETTINGS, json={"enabled": True},
                      headers={"Origin": "https://elsewhere.example"}).status_code == 403
    assert client.put(SETTINGS, data=b" " * 257,
                      content_type="application/json").status_code == 413
    assert client.put(SETTINGS, json={"enabled": True}).status_code == 200
    generation = marker(regular)
    assert generation
    assert "data-local-telemetry-generation" not in regular.get("/preferences").text
    assert "Local telemetry is on" in regular.get("/preferences").text
    assert "id=\"telemetry-enabled\"" not in regular.get("/preferences").text
    assert regular.post(CLIENT, json=batch(generation, True)).status_code == 400
    assert regular.post(CLIENT, json=batch(generation),
                        headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert not fresh_db.with_name("telemetry.db").exists()
    assert regular.post(CLIENT, json=batch(generation),
                        headers={"Origin": "http://localhost"}).status_code == 204


def test_report_storage_error_is_distinct(client, fresh_db):
    client.put(SETTINGS, json={"enabled": True})
    fresh_db.with_name("telemetry.db").write_bytes(b"not a database")
    assert client.get(REPORT).status_code == 503
    assert client.post(CLIENT, json=batch(marker(client))).status_code == 204


def test_failed_setting_read_keeps_pages_available(client, monkeypatch, caplog):
    regular = routes.app.test_client()
    sign_in(regular, seed_user("regular"))
    monkeypatch.setattr(routes, "_telemetry_last_warning", float("-inf"))

    def busy(key, **kwargs):
        assert key == telemetry.SETTING
        raise sqlite3.OperationalError("settings read failed")

    monkeypatch.setattr(db, "get_setting", busy)
    for page in ("/", "/ledger"):
        response = client.get(page)
        assert response.status_code == 200
        assert "data-local-telemetry-generation" not in response.text
    preferences = regular.get("/preferences")
    assert preferences.status_code == 200
    assert "Local telemetry status is unavailable" in preferences.text
    settings = client.get(SETTINGS)
    assert settings.status_code == 503
    assert settings.headers["Cache-Control"] == "no-store"
    assert caplog.text.count("event=local_telemetry_unavailable") == 1


def test_import_zero_on_http_success_is_counted(client):
    client.put(SETTINGS, json={"enabled": True})
    rejected = client.post("/api/transactions/import/commit", json={"text": "invalid row"})
    assert rejected.status_code == 200
    assert rejected.json["imported"] == 0
    report = client.get(REPORT).json
    assert report["actions"]["import_commit"] == {
        "total": 1, "outcomes": {"failed": {"format": 1}}}


def test_save_and_preview_request_outcomes(client, monkeypatch):
    monkeypatch.setattr(routes, "get_quote", {"TEST": {"currency": "CAD"}}.__getitem__)
    assert client.put(SETTINGS, json={"enabled": True}).status_code == 200
    fields = dict(date="2026-01-01", price=10, qty=1, type="BUY")
    created = client.post("/api/transactions", json=dict(fields, ticker="TEST"))
    assert created.status_code == 201
    assert client.post("/api/transactions", json={}).status_code == 400
    assert client.post("/api/transactions", json=dict(fields, ticker="MISSING")).status_code == 404
    assert client.put(f"/api/transactions/{created.json['id']}", json=fields).status_code == 200
    assert client.put("/api/transactions/999", json=fields).status_code == 404
    assert client.post("/api/transactions?portfolio_id=999", json=fields).status_code == 404
    for text in ("TEST\t1 Jan 2026\t10\t1\ninvalid row", "invalid row"):
        assert client.post("/api/transactions/import/preview", json={"text": text}).status_code == 200
    assert client.get(REPORT).json["actions"] == {
        "save_create": {"total": 3, "outcomes": {
            "success": {"none": 1}, "failed": {"validation": 1, "unquotable": 1}}},
        "save_edit": {"total": 2, "outcomes": {
            "success": {"none": 1}, "failed": {"not_found": 1}}},
        "import_preview": {"total": 2, "outcomes": {
            "partial": {"format": 1}, "failed": {"format": 1}}},
        "import_commit": {"total": 0, "outcomes": {}},
    }


@pytest.mark.parametrize("state", ["off", "broken"])
def test_disabled_setting_is_a_noop(client, state):
    db.set_setting("local_telemetry_generation", state)
    assert client.put(SETTINGS, json={"enabled": False}).json == {"enabled": False}
    assert db.get_setting("local_telemetry_generation") == state


def test_retention_and_window_boundaries(tmp_path, monkeypatch):
    path = tmp_path / "telemetry.db"
    event = ("dashboard_chart", "ready", None, 2500, "narrow")
    end = 30_000_000
    minute = end - telemetry.RETENTION_MINUTES
    monkeypatch.setattr(telemetry, "current_minute", lambda: minute)
    telemetry.record(path, [event])
    minute += 1
    telemetry.record(path, [event])
    minute = end - telemetry.WEEK_MINUTES
    telemetry.record(path, [event])
    minute += 1
    telemetry.record(path, [event])
    minute = end
    telemetry.record(path, [event])
    assert telemetry.report(path)["sections"]["dashboard_chart"]["ready"] == 2
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT MIN(minute) FROM events").fetchone()[0] == end - telemetry.RETENTION_MINUTES + 1
    telemetry.record(path, [event] * telemetry.MAX_ROWS)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*), MIN(minute) FROM events").fetchone() == (20_000, end)
    assert len(telemetry.report(path)["recent_slow_chart"]) == 5


def test_action_is_dropped_if_consent_rotates(client, monkeypatch):
    from threading import Event

    client.put(SETTINGS, json={"enabled": True})
    entered, release = Event(), Event()
    real = routes._import_text_or_error

    def delayed():
        entered.set()
        assert release.wait(3)
        return real()

    monkeypatch.setattr(routes, "_import_text_or_error", delayed)
    other = routes.app.test_client()
    sign_in(other, 1)
    responses = []
    worker = Thread(target=lambda: responses.append(other.post(
        "/api/transactions/import/commit", json={"text": "invalid row"})))
    worker.start()
    try:
        assert entered.wait(3)
        assert client.put(SETTINGS, json={"enabled": False}).status_code == 200
        assert client.put(SETTINGS, json={"enabled": True}).status_code == 200
    finally:
        release.set()
        worker.join(3)
    assert responses[0].status_code == 200
    assert client.get(REPORT).json["actions"]["import_commit"]["total"] == 0


def test_telemetry_write_failure_preserves_ledger_response(client, monkeypatch, caplog):
    client.put(SETTINGS, json={"enabled": True})
    monkeypatch.setattr(routes, "_telemetry_last_warning", float("-inf"))
    monkeypatch.setattr(routes, "get_quote", lambda ticker: {"currency": "CAD"})

    def fail(path, events):
        raise sqlite3.OperationalError("private diagnostic detail")

    monkeypatch.setattr(telemetry, "record", fail)
    for _ in range(2):
        response = client.post("/api/transactions", json=dict(
            ticker="TEST", date="2026-01-01", price=10, qty=1, type="BUY"))
        assert response.status_code == 201
    assert len(db.get_transactions(1)) == 2
    assert caplog.text.count("event=local_telemetry_unavailable") == 1
    assert "private diagnostic detail" not in caplog.text
