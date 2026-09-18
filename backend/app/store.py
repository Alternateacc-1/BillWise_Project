"""Bill storage. SQLite locally, DynamoDB behind the same interface later.

Deliberately small: one table, JSON blobs, no ORM. The pipeline owns the
shapes; this just persists them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import config

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "billsahi.sqlite"

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
    bill_id      TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    payload      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _lock, _connect() as conn:
        conn.executescript(SCHEMA)


def put(bill_id: str, status: str, payload: dict) -> None:
    init()
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM bills WHERE bill_id = ?", (bill_id,)
        ).fetchone()
        created = existing["created_at"] if existing else _now()
        conn.execute(
            "INSERT OR REPLACE INTO bills "
            "(bill_id, status, created_at, updated_at, payload) VALUES (?,?,?,?,?)",
            (bill_id, status, created, _now(), json.dumps(payload)),
        )


def get(bill_id: str) -> dict | None:
    init()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM bills WHERE bill_id = ?", (bill_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "bill_id": row["bill_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **json.loads(row["payload"]),
    }


def provider() -> str:
    return config.PROVIDER
