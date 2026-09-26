# tests/test_users.py
# ===================
# The db layer's user machinery: accounts, ownership columns, the legacy
# claim, and the deletion cascade. NO routes are involved here (no Flask
# client) — this file proves the STORAGE contracts that the auth gate and
# the People card depend on. Route behavior lives in test_auth.py /
# test_multiuser_scoping.py.
#
# DETERMINISM: a fresh_db's first created user has id 1 and its seeded
# Main portfolio has id 1 (the same ids the client fixture's "tester"
# gets). Later ids just count up.

import sqlite3

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import db
from conftest import make_legacy_db, seed_user


def test_init_creates_settings_and_empty_users(fresh_db):
    """init() is user-free until someone claims the server (setup page):
    zero users, and GET settings.round-trip machinery exists."""
    assert db.count_users() == 0
    assert db.get_setting("secret_key") is None
    # The schema exists but owns nothing:
    with sqlite3.connect(fresh_db) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"app_settings", "users", "portfolios", "watchlist",
            "transactions"} <= tables


def test_create_user_hashes_and_seeds_main_portfolio(fresh_db):
    uid = seed_user("alice")
    user = db.get_user(uid)
    assert user["username"] == "alice"
    # The stored value IS a verifiable hash, not a copy of the password:
    assert user["password_hash"] != "pw-1234"
    assert check_password_hash(user["password_hash"], "pw-1234")
    assert db.get_portfolios(uid) == [
        {"id": 1, "name": "Main", "sort_order": 0}]
    assert db.get_users() == [{"id": uid, "username": "alice"}]
    assert db.count_users() == 1


def test_create_user_duplicate_username_case_insensitive(fresh_db):
    seed_user("amy")
    with pytest.raises(sqlite3.IntegrityError):
        seed_user("AMY")
    assert db.count_users() == 1


@pytest.mark.parametrize("bad_user", ["", "   ", "x" * 31])
def test_create_user_rejects_bad_usernames(fresh_db, bad_user):
    with pytest.raises(sqlite3.IntegrityError):
        db.create_user(bad_user, generate_password_hash("pw-1234"))
    assert db.count_users() == 0


def test_create_user_accepts_boundary_lengths(fresh_db):
    db.create_user("x", generate_password_hash("pw-1234"))
    db.create_user("x" * 30, generate_password_hash("pw-1234"))
    assert db.count_users() == 2


def test_get_user_by_username_is_case_insensitive(fresh_db):
    seed_user("amy")
    # NOCASE on the column: any casing matches; the TRIM is route policy.
    assert db.get_user_by_username("AMY")["username"] == "amy"
    assert db.get_user_by_username("nobody") is None


def test_set_password_round_trip(fresh_db):
    uid = seed_user("amy")
    assert db.set_password(uid, generate_password_hash("new-key-9")) is True
    assert not check_password_hash(
        db.get_user(uid)["password_hash"], "pw-1234")
    assert check_password_hash(
        db.get_user(uid)["password_hash"], "new-key-9")
    assert db.set_password(999, "x") is False


def test_get_setting_round_trip_and_overwrite(fresh_db):
    db.set_setting("secret_key", "one")
    assert db.get_setting("secret_key") == "one"
    db.set_setting("secret_key", "two")
    assert db.get_setting("secret_key") == "two"


def test_default_portfolio_id_scopes_and_nones(fresh_db):
    uid_a = seed_user("amy")
    uid_b = seed_user("bert")
    # Two users may both have a Main, and each default is their own:
    assert db.default_portfolio_id(uid_a) == 1
    assert db.default_portfolio_id(uid_b) == 2
    # A user with no portfolios answers None instead of someone else's
    # id. The zero-owned state can never be reached through delete
    # (the last portfolio is refused), so plant it directly the way a
    # corrupted DB would be found — this is the 409 branch's source.
    with sqlite3.connect(fresh_db) as conn:
        conn.execute("DELETE FROM portfolios WHERE user_id = ?", (uid_b,))
    assert db.default_portfolio_id(uid_b) is None
    assert db.default_portfolio_id(uid_a) == 1


def test_init_leaves_no_portfolio_without_a_user(fresh_db):
    # The old auto-create-on-init is GONE: with zero users there is no
    # owner to hold Main, so init() must not invent one.
    with sqlite3.connect(fresh_db) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM portfolios").fetchone()
    assert rows[0] == 0


def test_claim_unowned_data_adopts_and_backfills_main(tmp_path, monkeypatch):
    """The migration story: an old install's portfolio + watchlist rows
    start owner-less after init(); the setup route's claim hands them to
    the first created user, without duplicating Main."""
    path = tmp_path / "old.db"
    make_legacy_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    db.init()  # idempotent migration
    # The setup route's exact sequence: create WITHOUT seeding Main (an
    # adoption would double it), then claim:
    uid = db.create_user("owner",
                         generate_password_hash("pw-1234"), seed_main=False)
    db.claim_unowned_data(uid)
    # The legacy Main is now owned; its facts untouched:
    assert db.get_portfolios(uid)[0]["name"] == "Main"
    row = db.get_transaction(42, 1)
    assert (row["id"], row["portfolio_id"], row["fee"], row["fx_rate"]) == (
        42, 1, 3.5, 1.31)
    assert db.get_symbols(uid) == ["AAPL"]
    # A portfolio already existed, so the claim did NOT build a second Main —
    # and the seed_main=False rule proves the other half of that in
    # test_setup_adopts_legacy_data_and_signs_in (test_auth.py).


def test_claim_on_fresh_db_gives_main(tmp_path, monkeypatch):
    path = tmp_path / "new.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    uid = seed_user("owner")
    db.claim_unowned_data(uid)
    assert [p["name"] for p in db.get_portfolios(uid)] == ["Main"]
    # Nothing was owner-less, so nothing changed owner:
    with sqlite3.connect(path) as conn:
        nulls = conn.execute(
            "SELECT COUNT(*) FROM portfolios WHERE user_id IS NULL"
        ).fetchone()[0]
    assert nulls == 0


def test_delete_user_requires_exact_username_confirmation(fresh_db):
    uid = seed_user("alice")
    seed_user("bert")   # a second user, so alice isn't the un-deletable last one
    assert db.delete_user(uid, "alice ") == "mismatch"   # trailing space
    assert db.delete_user(uid, "ALICE") == "mismatch"    # case-sensitive
    assert db.delete_user(999, "alice") == "missing"
    assert db.delete_user(uid, "alice") == "deleted"


def test_delete_user_cascades_owned_data(fresh_db):
    """Deleting a person removes EVERYTHING they own in one go: their
    portfolios, those portfolios' transactions, and their watchlist rows.
    Another user's rows never move."""
    uid_a = seed_user("alice")
    uid_b = seed_user("bert")
    second_a = db.create_portfolio("Growth", uid_a)
    db.add_symbol("AAPL", uid_a)
    db.add_symbol("MSFT", uid_a)
    db.add_symbol("NVDA", uid_b)
    db.add_transaction("AAPL", "2026-01-01", 10, 2, "CAD", "BUY", 1,
                       portfolio_id=1)
    db.add_transaction("AAPL", "2026-01-02", 12, 3, "CAD", "BUY", 1,
                       portfolio_id=second_a)
    # Sanity: bert owns two transactions' worth of nothing + own data:
    db.add_transaction("NVDA", "2026-01-01", 5, 1, "CAD", "BUY", 1,
                       portfolio_id=2)
    assert db.delete_user(uid_a, "alice") == "deleted"
    assert db.get_portfolios(uid_a) == []
    assert db.get_symbols(uid_a) == []
    assert db.get_transaction(1, 1) is None
    # Bert's own data SURVIVES the deletion of alice (id 3 is bert's row):
    assert db.get_transaction(3, 2)["ticker"] == "NVDA"
    assert db.get_portfolios(uid_b) == [
        {"id": 2, "name": "Main", "sort_order": 0}]
    assert db.get_symbols(uid_b) == ["NVDA"]
    with sqlite3.connect(db.DB_PATH) as conn:
        orphans = conn.execute(
            "SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert orphans == 1                              # only bert's, no orphans


def test_delete_user_never_removes_last_user(fresh_db):
    uid = seed_user("alice")
    assert db.delete_user(uid, "alice") == "last"
    assert db.count_users() == 1


def test_users_survive_reinit(fresh_db):
    """db.init() re-runs on every boot; users/settings/seeded Main must
    neither vanish nor duplicate."""
    uid = seed_user("amy")
    db.set_setting("secret_key", "stable")
    db.init()
    assert db.count_users() == 1
    assert db.get_user(uid)["username"] == "amy"
    assert db.get_portfolios(uid) == [
        {"id": 1, "name": "Main", "sort_order": 0}]
    assert db.get_setting("secret_key") == "stable"


def test_get_users_omits_password_hashes(fresh_db):
    """The list reply shape is {{id, username}}: hashes stay in get_user."""
    seed_user("amy")
    seed_user("bert")
    assert db.get_users() == [
        {"id": 1, "username": "amy"}, {"id": 2, "username": "bert"}]
