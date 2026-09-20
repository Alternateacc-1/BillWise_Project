"""Bill storage. SQLite locally, DynamoDB behind the same interface in AWS.

Deliberately small: one table, JSON blobs, no ORM. The pipeline owns the
shapes; this just persists them.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
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
    if config.PROVIDER == "aws":
        from . import aws_clients

        aws_clients.dynamodb().put_item(
            TableName=config.DDB_TABLE,
            Item={
                "bill_id": {"S": bill_id},
                "status": {"S": status},
                "updated_at": {"S": _now()},
                # One JSON blob rather than mapped attributes: the pipeline
                # owns these shapes and they change often. A document store
                # should not also be a schema.
                "payload": {"S": json.dumps(payload)},
                # S3 objects expire after a day; the record must not outlive
                # the bill it describes.
                "ttl": {"N": str(int(time.time()) + 86400)},
            },
        )
        return

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
    if config.PROVIDER == "aws":
        from . import aws_clients

        item = aws_clients.dynamodb().get_item(
            TableName=config.DDB_TABLE,
            Key={"bill_id": {"S": bill_id}},
        ).get("Item")
        if not item:
            return None
        stamp = item.get("updated_at", {}).get("S", "")
        return {
            "bill_id": bill_id,
            "status": item["status"]["S"],
            "created_at": stamp,
            "updated_at": stamp,
            **json.loads(item["payload"]["S"]),
        }

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
