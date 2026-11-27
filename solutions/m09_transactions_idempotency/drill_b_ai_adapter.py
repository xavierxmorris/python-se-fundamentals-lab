"""Reference solution for M09 Drill B: Crash-Safe Transactional BatchOutboxRelay."""

import sqlite3
import time
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


def _configure_wal_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA busy_timeout=10000;")
    for attempt in range(20):
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 19:
                raise
            time.sleep(0.005)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=10000;")


class BatchOutboxRelay:
    def __init__(self, conn: sqlite3.Connection, broker: BrokerPort) -> None:
        self._conn = conn
        self._broker = broker
        with self._immediate_tx() as tx:
            tx.execute(
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

    @contextmanager
    def _immediate_tx(self) -> Generator[sqlite3.Connection]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise
        else:
            if self._conn.in_transaction:
                self._conn.execute("COMMIT")

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    def enqueue(self, msg_id: str, body: str) -> bool:
        with self._immediate_tx() as tx:
            row = tx.execute(
                "SELECT body FROM outbox WHERE msg_id = ?",
                (msg_id,),
            ).fetchone()
            if row is not None:
                if str(row[0]) != body:
                    raise ValueError(f"Conflicting outbox body for msg_id={msg_id!r}")
                return False
            tx.execute(
                "INSERT INTO outbox (msg_id, body, status, attempts) VALUES (?, ?, 'pending', 0)",
                (msg_id, body),
            )
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

            with self._immediate_tx() as tx:
                claim = tx.execute(
                    """
                    UPDATE outbox
                    SET attempts = attempts + 1
                    WHERE msg_id = ? AND status = 'pending'
                    """,
                    (msg_id,),
                )
                if claim.rowcount != 1:
                    continue

            delivery_key = f"outbox:{msg_id}"
            self._broker.publish(delivery_key, body)

            with self._immediate_tx() as tx:
                tx.execute(
                    "UPDATE outbox SET status = 'sent' WHERE msg_id = ?",
                    (msg_id,),
                )
            relayed += 1

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
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        _configure_wal_pragmas(conn)
        yield BatchOutboxRelay(conn, broker)
    finally:
        conn.close()
