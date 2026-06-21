from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DB_PATH = Path(os.getenv("FAMILY_CFO_DB_PATH", "data/family_cfo.db"))
MEMBERS = ["아빠", "엄마", "민주", "나영", "대균"]


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DEFAULT_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def connection_scope(db_path: str | Path | None = None):
    conn = get_connection(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT '가족',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cash_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_date TEXT NOT NULL,
    tx_type TEXT NOT NULL CHECK (tx_type IN ('입금', '지출')),
    member_name TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    category TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investment_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    ticker TEXT NOT NULL DEFAULT '',
    market_type TEXT NOT NULL,
    currency TEXT NOT NULL DEFAULT 'KRW',
    manual_current_price REAL,
    manual_current_value REAL,
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS investment_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES investment_assets(id) ON DELETE CASCADE,
    trade_date TEXT NOT NULL,
    trade_type TEXT NOT NULL CHECK (trade_type IN ('매수', '매도')),
    quantity REAL NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL CHECK (unit_price >= 0),
    fx_rate REAL NOT NULL DEFAULT 1 CHECK (fx_rate > 0),
    total_amount_krw REAL NOT NULL CHECK (total_amount_krw > 0),
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS price_cache (
    symbol TEXT PRIMARY KEY,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'Yahoo Finance'
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_name TEXT NOT NULL,
    target_amount REAL NOT NULL CHECK (target_amount > 0),
    current_amount REAL NOT NULL DEFAULT 0 CHECK (current_amount >= 0),
    start_date TEXT NOT NULL,
    target_date TEXT NOT NULL,
    owner TEXT NOT NULL,
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL,
    event_time TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    event_type TEXT NOT NULL,
    participants TEXT NOT NULL DEFAULT '',
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    owner TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('예정', '진행중', '완료')),
    memo TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    deadline TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS poll_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_text TEXT NOT NULL,
    UNIQUE (poll_id, option_text)
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    voter_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (poll_id, voter_name)
);
"""


def initialize_database(db_path: str | Path | None = None, seed: bool = False) -> None:
    with connection_scope(db_path) as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO users (name, role) VALUES (?, ?)",
            [(name, "부모") if name in ("아빠", "엄마") else (name, "자녀") for name in MEMBERS],
        )
        if seed and conn.execute("SELECT COUNT(*) FROM cash_transactions").fetchone()[0] == 0:
            conn.execute("DELETE FROM users")
            _seed_sample_data(conn)


def remove_initial_demo_data(db_path: str | Path | None = None) -> None:
    """Remove only the original bundled demo rows, once, without touching user records."""
    migration = "remove_initial_demo_v1"
    with connection_scope(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS app_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        if conn.execute("SELECT 1 FROM app_migrations WHERE name = ?", (migration,)).fetchone():
            return
        conn.execute("DELETE FROM cash_transactions WHERE memo = '초기 가족 공동자금'")
        conn.execute("DELETE FROM investment_assets WHERE memo = '샘플 투자' AND ticker IN ('005930.KS', 'AAPL', '360750.KS')")
        conn.execute("DELETE FROM goals WHERE memo IN ('가족여행 준비', '생신 식사와 선물')")
        conn.execute("DELETE FROM events WHERE memo IN ('저녁 식사', '검진 예약', '케이크 준비')")
        conn.execute("DELETE FROM tasks WHERE memo IN ('후보 3곳 정리', '이번 달 회비')")
        conn.execute("DELETE FROM polls WHERE title = '다음 가족모임 메뉴'")
        conn.execute("INSERT INTO app_migrations (name) VALUES (?)", (migration,))


def _seed_sample_data(conn: sqlite3.Connection) -> None:
    today = date.today()
    conn.executemany(
        "INSERT INTO users (name, role) VALUES (?, ?)",
        [(name, "부모") if name in ("아빠", "엄마") else (name, "자녀") for name in MEMBERS],
    )
    deposits = [("나영", 100_000), ("민주", 100_000), ("대균", 100_000), ("아빠", 200_000), ("엄마", 200_000)]
    conn.executemany(
        "INSERT INTO cash_transactions (tx_date, tx_type, member_name, amount, category, memo) VALUES (?, '입금', ?, ?, '투자금', ?)",
        [(today.isoformat(), member, amount, "초기 가족 공동자금") for member, amount in deposits],
    )

    assets = [
        ("삼성전자", "005930.KS", "한국주식", "KRW", 75_000, None, "샘플 투자"),
        ("Apple", "AAPL", "미국주식", "USD", 210, None, "샘플 투자"),
        ("TIGER 미국S&P500", "360750.KS", "ETF", "KRW", 22_000, None, "샘플 투자"),
    ]
    conn.executemany(
        "INSERT INTO investment_assets (asset_name, ticker, market_type, currency, manual_current_price, manual_current_value, memo) VALUES (?, ?, ?, ?, ?, ?, ?)",
        assets,
    )
    asset_ids = {row["ticker"]: row["id"] for row in conn.execute("SELECT id, ticker FROM investment_assets")}
    trades = [
        (asset_ids["005930.KS"], (today - timedelta(days=70)).isoformat(), "매수", 1, 70_000, 1, 70_000),
        (asset_ids["AAPL"], (today - timedelta(days=55)).isoformat(), "매수", 0.5, 190, 1_400, 133_000),
        (asset_ids["360750.KS"], (today - timedelta(days=40)).isoformat(), "매수", 2, 20_000, 1, 40_000),
    ]
    conn.executemany(
        "INSERT INTO investment_transactions (asset_id, trade_date, trade_type, quantity, unit_price, fx_rate, total_amount_krw, memo) VALUES (?, ?, ?, ?, ?, ?, ?, '초기 샘플 매수')",
        trades,
    )

    goals = [
        ("가족여행 기금", 5_000_000, 700_000, today - timedelta(days=90), today + timedelta(days=300), "나영", "가족여행 준비"),
        ("부모님 생신 이벤트", 1_000_000, 250_000, today - timedelta(days=45), today + timedelta(days=150), "민주", "생신 식사와 선물"),
    ]
    conn.executemany(
        "INSERT INTO goals (goal_name, target_amount, current_amount, start_date, target_date, owner, memo) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(n, t, c, s.isoformat(), d.isoformat(), o, m) for n, t, c, s, d, o, m in goals],
    )

    events = [
        (today + timedelta(days=5), "18:30", "가족모임", "가족모임", ", ".join(MEMBERS), "저녁 식사"),
        (today + timedelta(days=12), "10:00", "부모님 병원 일정", "병원", "아빠, 엄마, 민주", "검진 예약"),
        (today + timedelta(days=20), "19:00", "가족 생일", "생일", ", ".join(MEMBERS), "케이크 준비"),
    ]
    conn.executemany(
        "INSERT INTO events (event_date, event_time, title, event_type, participants, memo) VALUES (?, ?, ?, ?, ?, ?)",
        [(d.isoformat(), t, n, typ, p, m) for d, t, n, typ, p, m in events],
    )
    conn.executemany(
        "INSERT INTO tasks (title, owner, due_date, status, memo) VALUES (?, ?, ?, ?, ?)",
        [
            ("가족여행 숙소 알아보기", "나영", (today + timedelta(days=14)).isoformat(), "진행중", "후보 3곳 정리"),
            ("공동통장 이체 확인", "대균", (today + timedelta(days=3)).isoformat(), "예정", "이번 달 회비"),
        ],
    )
    poll_id = conn.execute(
        "INSERT INTO polls (title, deadline) VALUES (?, ?)",
        ("다음 가족모임 메뉴", (today + timedelta(days=7)).isoformat()),
    ).lastrowid
    conn.executemany(
        "INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)",
        [(poll_id, option) for option in ("한식", "중식", "고기")],
    )


def fetch_all(query: str, params: Iterable[Any] = (), db_path: str | Path | None = None) -> list[dict[str, Any]]:
    with connection_scope(db_path) as conn:
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]


def fetch_one(query: str, params: Iterable[Any] = (), db_path: str | Path | None = None) -> dict[str, Any] | None:
    with connection_scope(db_path) as conn:
        row = conn.execute(query, tuple(params)).fetchone()
        return dict(row) if row else None


def execute(query: str, params: Iterable[Any] = (), db_path: str | Path | None = None) -> int:
    with connection_scope(db_path) as conn:
        cursor = conn.execute(query, tuple(params))
        return int(cursor.lastrowid or 0)


def add_cash_transaction(tx_date: str, tx_type: str, member: str, amount: float, category: str, memo: str = "", db_path=None) -> int:
    return execute(
        "INSERT INTO cash_transactions (tx_date, tx_type, member_name, amount, category, memo) VALUES (?, ?, ?, ?, ?, ?)",
        (tx_date, tx_type, member, amount, category, memo), db_path,
    )


def update_cash_transaction(transaction_id: int, tx_date: str, tx_type: str, member: str, amount: float, category: str, memo: str = "", db_path=None) -> None:
    execute(
        "UPDATE cash_transactions SET tx_date=?, tx_type=?, member_name=?, amount=?, category=?, memo=? WHERE id=?",
        (tx_date, tx_type, member, amount, category, memo, transaction_id), db_path,
    )


def add_asset(asset_name: str, ticker: str, market_type: str, currency: str, manual_price: float | None, manual_value: float | None, memo: str = "", db_path=None) -> int:
    return execute(
        "INSERT INTO investment_assets (asset_name, ticker, market_type, currency, manual_current_price, manual_current_value, memo) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (asset_name, ticker.strip().upper(), market_type, currency, manual_price, manual_value, memo), db_path,
    )


def update_asset(asset_id: int, asset_name: str, ticker: str, market_type: str, currency: str, manual_price: float | None, manual_value: float | None, memo: str = "", db_path=None) -> None:
    execute(
        "UPDATE investment_assets SET asset_name=?, ticker=?, market_type=?, currency=?, manual_current_price=?, manual_current_value=?, memo=? WHERE id=?",
        (asset_name, ticker.strip().upper(), market_type, currency, manual_price, manual_value, memo, asset_id), db_path,
    )


def add_investment_transaction(asset_id: int, trade_date: str, trade_type: str, quantity: float, unit_price: float, fx_rate: float, total_amount_krw: float, memo: str = "", db_path=None) -> int:
    return execute(
        "INSERT INTO investment_transactions (asset_id, trade_date, trade_type, quantity, unit_price, fx_rate, total_amount_krw, memo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (asset_id, trade_date, trade_type, quantity, unit_price, fx_rate, total_amount_krw, memo), db_path,
    )


def update_investment_transaction(transaction_id: int, asset_id: int, trade_date: str, trade_type: str, quantity: float, unit_price: float, fx_rate: float, total_amount_krw: float, memo: str = "", db_path=None) -> None:
    execute(
        "UPDATE investment_transactions SET asset_id=?, trade_date=?, trade_type=?, quantity=?, unit_price=?, fx_rate=?, total_amount_krw=?, memo=? WHERE id=?",
        (asset_id, trade_date, trade_type, quantity, unit_price, fx_rate, total_amount_krw, memo, transaction_id), db_path,
    )


def update_asset_manual_value(asset_id: int, manual_price: float | None, manual_value: float | None, db_path=None) -> None:
    execute("UPDATE investment_assets SET manual_current_price = ?, manual_current_value = ? WHERE id = ?", (manual_price, manual_value, asset_id), db_path)


def upsert_price_cache(symbol: str, price: float, currency: str, source: str = "Yahoo Finance", db_path=None) -> None:
    execute(
        """INSERT INTO price_cache (symbol, price, currency, fetched_at, source)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET price=excluded.price, currency=excluded.currency,
           fetched_at=excluded.fetched_at, source=excluded.source""",
        (symbol, price, currency, datetime.now().isoformat(timespec="seconds"), source), db_path,
    )


def get_cached_price(symbol: str, db_path=None) -> dict[str, Any] | None:
    return fetch_one("SELECT * FROM price_cache WHERE symbol = ?", (symbol,), db_path)


def add_goal(name: str, target: float, current: float, start: str, target_date: str, owner: str, memo: str = "", db_path=None) -> int:
    return execute("INSERT INTO goals (goal_name, target_amount, current_amount, start_date, target_date, owner, memo) VALUES (?, ?, ?, ?, ?, ?, ?)", (name, target, current, start, target_date, owner, memo), db_path)


def update_goal(goal_id: int, name: str, target: float, current: float, start: str, target_date: str, owner: str, memo: str = "", db_path=None) -> None:
    execute("UPDATE goals SET goal_name=?, target_amount=?, current_amount=?, start_date=?, target_date=?, owner=?, memo=? WHERE id=?", (name, target, current, start, target_date, owner, memo, goal_id), db_path)


def add_event(event_date: str, event_time: str, title: str, event_type: str, participants: str, memo: str = "", db_path=None) -> int:
    return execute("INSERT INTO events (event_date, event_time, title, event_type, participants, memo) VALUES (?, ?, ?, ?, ?, ?)", (event_date, event_time, title, event_type, participants, memo), db_path)


def update_event(event_id: int, event_date: str, event_time: str, title: str, event_type: str, participants: str, memo: str = "", db_path=None) -> None:
    execute("UPDATE events SET event_date=?, event_time=?, title=?, event_type=?, participants=?, memo=? WHERE id=?", (event_date, event_time, title, event_type, participants, memo, event_id), db_path)


def add_task(title: str, owner: str, due_date: str, status: str, memo: str = "", db_path=None) -> int:
    return execute("INSERT INTO tasks (title, owner, due_date, status, memo) VALUES (?, ?, ?, ?, ?)", (title, owner, due_date, status, memo), db_path)


def update_task(task_id: int, title: str, owner: str, due_date: str, status: str, memo: str = "", db_path=None) -> None:
    execute("UPDATE tasks SET title=?, owner=?, due_date=?, status=?, memo=? WHERE id=?", (title, owner, due_date, status, memo, task_id), db_path)


def update_task_status(task_id: int, status: str, db_path=None) -> None:
    execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id), db_path)


def add_poll(title: str, options: list[str], deadline: str, db_path=None) -> int:
    with connection_scope(db_path) as conn:
        poll_id = conn.execute("INSERT INTO polls (title, deadline) VALUES (?, ?)", (title, deadline)).lastrowid
        conn.executemany("INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)", [(poll_id, option) for option in options])
        return int(poll_id)


def update_poll(poll_id: int, title: str, deadline: str, options: list[str] | None = None, db_path=None) -> None:
    with connection_scope(db_path) as conn:
        conn.execute("UPDATE polls SET title=?, deadline=? WHERE id=?", (title, deadline, poll_id))
        vote_count = conn.execute("SELECT COUNT(*) FROM poll_votes WHERE poll_id=?", (poll_id,)).fetchone()[0]
        if options is not None and vote_count == 0:
            conn.execute("DELETE FROM poll_options WHERE poll_id=?", (poll_id,))
            conn.executemany("INSERT INTO poll_options (poll_id, option_text) VALUES (?, ?)", [(poll_id, option) for option in options])


def cast_vote(poll_id: int, option_id: int, voter: str, db_path=None) -> int:
    return execute("INSERT INTO poll_votes (poll_id, option_id, voter_name) VALUES (?, ?, ?)", (poll_id, option_id, voter), db_path)


def delete_record(table_name: str, record_id: int, db_path=None) -> None:
    allowed = {"cash_transactions", "investment_assets", "investment_transactions", "goals", "events", "tasks", "polls"}
    if table_name not in allowed:
        raise ValueError("삭제할 수 없는 항목입니다.")
    execute(f"DELETE FROM {table_name} WHERE id=?", (record_id,), db_path)


def table(name: str, order_by: str = "id DESC", db_path=None) -> list[dict[str, Any]]:
    allowed = {"users", "cash_transactions", "investment_assets", "investment_transactions", "goals", "events", "tasks", "polls", "poll_options", "poll_votes"}
    if name not in allowed:
        raise ValueError("허용되지 않은 테이블입니다.")
    return fetch_all(f"SELECT * FROM {name} ORDER BY {order_by}", db_path=db_path)
