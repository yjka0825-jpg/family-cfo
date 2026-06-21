import sqlite3

import database as db


def test_seed_is_idempotent(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path)
    db.initialize_database(path)
    assert len(db.table("users", db_path=path)) == 5
    assert len(db.table("cash_transactions", db_path=path)) == 5
    assert len(db.table("investment_assets", db_path=path)) == 3


def test_duplicate_vote_is_rejected(tmp_path):
    path = tmp_path / "family.db"
    db.initialize_database(path, seed=False)
    poll_id = db.add_poll("여행지", ["제주", "부산"], "2026-12-31", path)
    option = db.fetch_one("SELECT id FROM poll_options WHERE poll_id=? ORDER BY id", (poll_id,), path)
    db.cast_vote(poll_id, option["id"], "민주", path)
    with __import__("pytest").raises(sqlite3.IntegrityError):
        db.cast_vote(poll_id, option["id"], "민주", path)
