# tests/test_fund_classification.py
# =================================
# Tests for the install-wide manual fund classification overrides:
#   * db.classification_overrides storage (JSON weights, upsert, delete)
#   * GET/PUT/DELETE /api/fund-classification/<symbol>
#
# The table is deliberately OWNERLESS (objective reference data about a
# security, like the market overview / search / stock detail): every signed-in
# person reads and writes the same rows. That is documented as an explicit
# exception in project-brief.md. These tests pin that shared behavior.

import db


# ── db layer ─────────────────────────────────────────────────────────────

def test_override_round_trips(fresh_db):
    db.set_classification_override(
        "VEQT.TO", "country", {"United States": 0.4, "Canada": 0.3},
        as_of="2026-01-01",
    )
    row = db.get_classification_override("VEQT.TO", "country")
    assert row["weights"] == {"United States": 0.4, "Canada": 0.3}
    assert row["as_of"] == "2026-01-01"
    assert row["updated_at"]  # stamped, non-empty


def test_override_missing_returns_none(fresh_db):
    assert db.get_classification_override("NOPE", "country") is None


def test_override_upsert_replaces(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("VEQT.TO", "country", {"United States": 1.0})
    row = db.get_classification_override("VEQT.TO", "country")
    assert row["weights"] == {"United States": 1.0}
    # One row per (symbol, dimension), not two.
    rows = db.get_classification_overrides("country")
    assert len(rows) == 1


def test_override_dimensions_are_independent(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("VEQT.TO", "asset", {"Stocks": 1.0})
    all_rows = db.get_classification_overrides()
    dims = {r["dimension"] for r in all_rows}
    assert dims == {"country", "asset"}
    filtered = db.get_classification_overrides("asset")
    assert len(filtered) == 1
    assert filtered[0]["weights"] == {"Stocks": 1.0}


def test_override_as_of_null_when_omitted(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    assert db.get_classification_override("VEQT.TO", "country")["as_of"] is None


def test_delete_override(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    assert db.delete_classification_override("VEQT.TO", "country") is True
    assert db.get_classification_override("VEQT.TO", "country") is None
    # Deleting a missing row reports False.
    assert db.delete_classification_override("VEQT.TO", "country") is False


def test_delete_all_overrides_for_symbol(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("VEQT.TO", "asset", {"Stocks": 1.0})
    db.set_classification_override("XEQT.TO", "country", {"Canada": 1.0})
    assert db.delete_classification_overrides("VEQT.TO") == 2
    assert db.get_classification_override("VEQT.TO", "country") is None


def test_delete_all_overrides_leaves_other_symbols(fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("XEQT.TO", "country", {"Canada": 1.0})
    db.delete_classification_overrides("VEQT.TO")
    rows = db.get_classification_overrides()
    assert [r["symbol"] for r in rows] == ["XEQT.TO"]


# ── route: GET ───────────────────────────────────────────────────────────

def test_get_returns_empty_overrides(client, fresh_db):
    body = client.get("/api/fund-classification/VEQT.TO").get_json()
    assert body == {"symbol": "VEQT.TO", "overrides": {}}


def test_get_returns_stored_overrides(client, fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 0.3})
    body = client.get("/api/fund-classification/VEQT.TO").get_json()
    assert body["symbol"] == "VEQT.TO"
    assert body["overrides"]["country"]["weights"] == {"Canada": 0.3}


def test_get_lowercases_symbol_to_canonical(client, fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 0.3})
    body = client.get("/api/fund-classification/veqt.to").get_json()
    assert body["symbol"] == "VEQT.TO"
    assert "country" in body["overrides"]


# ── route: PUT ───────────────────────────────────────────────────────────

def test_put_stores_and_normalizes(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country",
        "weights": {"United States": 70, "Canada": 30},
        "as_of": "2026-01-01",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["symbol"] == "VEQT.TO"
    assert body["dimension"] == "country"
    assert body["weights"] == {"United States": 0.7, "Canada": 0.3}
    assert body["as_of"] == "2026-01-01"

    stored = client.get("/api/fund-classification/VEQT.TO").get_json()
    assert stored["overrides"]["country"]["weights"] == {
        "United States": 0.7, "Canada": 0.3}


def test_put_drops_zero_fractions(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country",
        "weights": {"United States": 0, "Canada": 50},
    })
    assert res.status_code == 200
    assert res.get_json()["weights"] == {"Canada": 1.0}


def test_put_atomic_on_invalid(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country",
        "weights": {"Canada": -1},
    })
    assert res.status_code == 400
    assert db.get_classification_override("VEQT.TO", "country") is None


def test_put_rejects_unknown_dimension(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "cap", "weights": {"Large": 1},
    })
    assert res.status_code == 400


def test_put_rejects_empty_weights(client, fresh_db):
    for weights in ({}, [], None, "x"):
        res = client.put("/api/fund-classification/VEQT.TO", json={
            "dimension": "country", "weights": weights,
        })
        assert res.status_code == 400, weights


def test_put_rejects_all_zero(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country", "weights": {"Canada": 0},
    })
    assert res.status_code == 400


def test_put_rejects_non_finite_and_bool(client, fresh_db):
    for bad in [float("nan"), float("inf"), True]:
        res = client.put("/api/fund-classification/VEQT.TO", json={
            "dimension": "country", "weights": {"Canada": bad},
        })
        assert res.status_code == 400, bad


def test_put_rejects_string_value(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country", "weights": {"Canada": "50"},
    })
    assert res.status_code == 400


def test_put_rejects_too_many_entries(client, fresh_db):
    res = client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country",
        "weights": {f"R{i}": 1 for i in range(51)},
    })
    assert res.status_code == 400


def test_put_rejects_blank_long_and_duplicate_labels(client, fresh_db):
    cases = [
        {"Canada": 50, "": 50},
        {"Canada": 50, "x" * 41: 50},
        {"Canada": 50, "canada": 50},          # duplicate after case-fold
        {"Canada": 50, " Canada ": 50},        # duplicate after trim
    ]
    for weights in cases:
        res = client.put("/api/fund-classification/VEQT.TO", json={
            "dimension": "country", "weights": weights,
        })
        assert res.status_code == 400, weights


def test_put_rejects_bad_as_of(client, fresh_db):
    for as_of in ["2026-13-40", "not-a-date", 20260101]:
        res = client.put("/api/fund-classification/VEQT.TO", json={
            "dimension": "country", "weights": {"Canada": 1}, "as_of": as_of,
        })
        assert res.status_code == 400, as_of


def test_put_rejects_bad_symbol(client, fresh_db):
    res = client.put("/api/fund-classification/bad%20symbol", json={
        "dimension": "country", "weights": {"Canada": 1},
    })
    assert res.status_code == 400


# ── route: DELETE ────────────────────────────────────────────────────────

def test_delete_one_dimension(client, fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("VEQT.TO", "asset", {"Stocks": 1.0})
    res = client.delete("/api/fund-classification/VEQT.TO?dimension=country")
    assert res.status_code == 200
    assert res.get_json()["deleted"] == 1
    remaining = client.get("/api/fund-classification/VEQT.TO").get_json()
    assert "asset" in remaining["overrides"]
    assert "country" not in remaining["overrides"]


def test_delete_all_dimensions(client, fresh_db):
    db.set_classification_override("VEQT.TO", "country", {"Canada": 1.0})
    db.set_classification_override("VEQT.TO", "asset", {"Stocks": 1.0})
    res = client.delete("/api/fund-classification/VEQT.TO")
    assert res.get_json()["deleted"] == 2


def test_delete_unknown_symbol_reports_zero(client, fresh_db):
    res = client.delete("/api/fund-classification/NOPE?dimension=country")
    assert res.status_code == 200
    assert res.get_json()["deleted"] == 0


def test_delete_bad_dimension_400(client, fresh_db):
    res = client.delete("/api/fund-classification/VEQT.TO?dimension=bogus")
    assert res.status_code == 400


# ── auth ─────────────────────────────────────────────────────────────────

def test_signed_out_requests_are_401(fresh_db):
    from app import app
    anon = app.test_client()
    assert anon.get("/api/fund-classification/VEQT.TO").status_code == 401
    assert anon.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country", "weights": {"Canada": 1}}).status_code == 401
    assert anon.delete(
        "/api/fund-classification/VEQT.TO?dimension=country").status_code == 401


# ── install-wide sharing ─────────────────────────────────────────────────

def test_overrides_are_shared_across_users(client, fresh_db):
    """Install-wide on purpose: user A's entry is visible to user B."""
    from conftest import seed_user
    from app import app

    user_b_id = seed_user("someone-else", "other-password-1234")
    other = app.test_client()
    with other.session_transaction() as session:
        session["user_id"] = user_b_id

    client.put("/api/fund-classification/VEQT.TO", json={
        "dimension": "country", "weights": {"Canada": 100}})
    body = other.get("/api/fund-classification/VEQT.TO").get_json()
    assert body["overrides"]["country"]["weights"] == {"Canada": 1.0}
