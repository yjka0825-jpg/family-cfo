import sqlite3

import database as db


def test_initialization_has_members_but_no_demo_records(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path)
    db.initialize_database(path)
    assert len(db.table("users", db_path=path)) == 5
    assert len(db.table("cash_transactions", db_path=path)) == 0
    assert len(db.table("investment_assets", db_path=path)) == 0


def test_records_can_be_updated_and_deleted(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path)
    tx_id = db.add_cash_transaction("2026-06-01", "입금", "민주", 100_000, "기타", "실제 기록", path)
    db.update_cash_transaction(tx_id, "2026-06-02", "지출", "나영", 50_000, "생활비", "수정됨", path)
    row = db.fetch_one("SELECT * FROM cash_transactions WHERE id=?", (tx_id,), path)
    assert row["tx_type"] == "지출"
    assert row["amount"] == 50_000
    db.delete_record("cash_transactions", tx_id, path)
    assert db.fetch_one("SELECT * FROM cash_transactions WHERE id=?", (tx_id,), path) is None


def test_original_demo_rows_are_removed_once(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path, seed=True)
    assert len(db.table("cash_transactions", db_path=path)) == 5
    db.remove_initial_demo_data(path)
    db.remove_initial_demo_data(path)
    assert len(db.table("cash_transactions", db_path=path)) == 0
    assert len(db.table("investment_assets", db_path=path)) == 0


def test_duplicate_vote_is_rejected(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path, seed=False)
    poll_id = db.add_poll("여행지", ["제주", "부산"], "2026-12-31", path)
    option = db.fetch_one("SELECT id FROM poll_options WHERE poll_id=? ORDER BY id", (poll_id,), path)
    db.cast_vote(poll_id, option["id"], "민주", path)
    with __import__("pytest").raises(sqlite3.IntegrityError):
        db.cast_vote(poll_id, option["id"], "민주", path)
