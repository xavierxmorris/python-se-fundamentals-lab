"""M09 Drill B (Spec-First AI Pair): Crash-Safe Transactional BatchOutboxRelay.

This AI-generated `BatchOutboxRelay` contains classic durability & idempotency defects:
- Generates a fresh random `uuid.uuid4()` `delivery_key` on every publish attempt instead
  of deterministic `f"outbox:{msg_id}"`, causing duplicate downstream deliveries whenever
  a batch crashes mid-flight or loses a broker acknowledgement.
- Uses implicit SQLite transactions and only commits at the very end of `relay_pending()`,
  leaving uncommitted partial state (`conn.in_transaction == True`) and losing progress
  for already-published messages when a later message raises an error.
"""

import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class OutboxRecord:
    msg_id: str
    body: str
    status: str
    attempts: int


@runtime_checkable
class BrokerPort(Protocol):
    def publish(self, delivery_key: str, body: str) -> None: ...


class BatchOutboxRelay:
    def __init__(self, conn: sqlite3.Connection, broker: BrokerPort) -> None:
        self._conn = conn
        self._broker = broker
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                msg_id TEXT NOT NULL UNIQUE,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    def enqueue(self, msg_id: str, body: str) -> bool:
        row = self._conn.execute(
            "SELECT body FROM outbox WHERE msg_id = ?",
            (msg_id,),
        ).fetchone()
        if row is not None:
            if str(row[0]) != body:
                raise ValueError(f"Conflicting outbox body for msg_id={msg_id!r}")
            return False
        self._conn.execute(
            "INSERT INTO outbox (msg_id, body, status, attempts) VALUES (?, ?, 'pending', 0)",
            (msg_id, body),
        )
        self._conn.commit()
        return True

    def relay_pending(self, *, limit: int = 50) -> int:
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be >= 1")
        rows = self._conn.execute(
            "SELECT msg_id, body FROM outbox WHERE status = 'pending' ORDER BY seq ASC LIMIT ?",
            (limit,),
        ).fetchall()

        relayed = 0
        for raw_id, raw_body in rows:
            msg_id = str(raw_id)
            body = str(raw_body)
            self._conn.execute(
                "UPDATE outbox SET attempts = attempts + 1 WHERE msg_id = ?",
                (msg_id,),
            )
            self._broker.publish(str(uuid.uuid4()), body)
            self._conn.execute(
                "UPDATE outbox SET status = 'sent' WHERE msg_id = ?",
                (msg_id,),
            )
            relayed += 1

        self._conn.commit()
        return relayed

    def get_record(self, msg_id: str) -> OutboxRecord:
        row = self._conn.execute(
            "SELECT msg_id, body, status, attempts FROM outbox WHERE msg_id = ?",
            (msg_id,),
        ).fetchone()
        if row is None:
            raise KeyError(msg_id)
        return OutboxRecord(
            msg_id=str(row[0]),
            body=str(row[1]),
            status=str(row[2]),
            attempts=int(row[3]),
        )

    def pending_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE status = 'pending'"
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def sent_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM outbox WHERE status = 'sent'"
        ).fetchone()
        return int(row[0]) if row is not None else 0


@contextmanager
def open_outbox_relay(db_path: Path, broker: BrokerPort) -> Generator[BatchOutboxRelay]:
    conn = sqlite3.connect(db_path, timeout=10.0)
    try:
        yield BatchOutboxRelay(conn, broker)
    finally:
        conn.close()
