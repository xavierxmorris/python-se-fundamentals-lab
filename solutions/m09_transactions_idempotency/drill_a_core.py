"""Reference solution for M09 Drill A: SQLite ACID Transactions, Idempotency & Fencing."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class IdempotencyConflictError(Exception):
    """Raised when an existing request_id is replayed with a different canonical payload."""


class StaleFenceError(Exception):
    """Raised when mutating a task with an outdated fence_token or terminal status."""


class TaskNotFoundError(KeyError):
    """Raised when a task_id does not exist in the ledger."""


@dataclass(slots=True, frozen=True)
class StoredSubmission:
    request_id: str
    task_id: str
    payload_hash: str
    snapshot_json: str
    created_new: bool


@dataclass(slots=True, frozen=True)
class LeaseGrant:
    task_id: str
    worker_id: str
    fence_token: int


def _canonical_json(mapping: Mapping[str, object]) -> str:
    return json.dumps(dict(mapping), sort_keys=True, separators=(",", ":"))


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


class DurableTaskLedger:
    """SQLite-backed durable task ledger with idempotent submissions and lease fencing."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

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

    def submit_idempotent(
        self,
        request_id: str,
        task_id: str,
        payload: Mapping[str, object],
        compute_initial_snapshot: Callable[[], Mapping[str, object]],
    ) -> StoredSubmission:
        canonical_payload = _canonical_json(payload)
        payload_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

        with self._immediate_tx() as conn:
            existing = conn.execute(
                "SELECT task_id, payload_hash, snapshot_json FROM submissions WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                stored_task_id = str(existing[0])
                stored_hash = str(existing[1])
                stored_snapshot = str(existing[2])
                if stored_hash != payload_hash:
                    raise IdempotencyConflictError(
                        f"Conflicting payload for request_id={request_id!r}"
                    )
                return StoredSubmission(
                    request_id=request_id,
                    task_id=stored_task_id,
                    payload_hash=stored_hash,
                    snapshot_json=stored_snapshot,
                    created_new=False,
                )

            snapshot_json = _canonical_json(compute_initial_snapshot())
            conn.execute(
                """
                INSERT INTO tasks (task_id, status, fence_token, lease_owner, outcome_json)
                VALUES (?, 'queued', 0, NULL, NULL)
                """,
                (task_id,),
            )
            conn.execute(
                """
                INSERT INTO submissions (request_id, task_id, payload_hash, snapshot_json)
                VALUES (?, ?, ?, ?)
                """,
                (request_id, task_id, payload_hash, snapshot_json),
            )
            return StoredSubmission(
                request_id=request_id,
                task_id=task_id,
                payload_hash=payload_hash,
                snapshot_json=snapshot_json,
                created_new=True,
            )

    def acquire_lease(self, task_id: str, worker_id: str) -> LeaseGrant:
        with self._immediate_tx() as conn:
            row = conn.execute(
                "SELECT status, fence_token FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(task_id)
            status = str(row[0])
            fence_token = int(row[1])
            if status == "succeeded":
                raise StaleFenceError(
                    f"Task {task_id!r} has already succeeded and cannot be re-leased"
                )
            next_fence = fence_token + 1
            conn.execute(
                """
                UPDATE tasks
                SET status = 'leased', fence_token = ?, lease_owner = ?
                WHERE task_id = ?
                """,
                (next_fence, worker_id, task_id),
            )
            return LeaseGrant(
                task_id=task_id,
                worker_id=worker_id,
                fence_token=next_fence,
            )

    def record_outcome(self, task_id: str, fence_token: int, outcome_json: str) -> None:
        with self._immediate_tx() as conn:
            exists = conn.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if exists is None:
                raise TaskNotFoundError(task_id)
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'succeeded', outcome_json = ?
                WHERE task_id = ? AND fence_token = ? AND status = 'leased'
                """,
                (outcome_json, task_id, fence_token),
            )
            if cur.rowcount != 1:
                raise StaleFenceError(
                    f"Stale or inactive lease for task {task_id!r} (fence_token={fence_token})"
                )

    def get_task_outcome(self, task_id: str) -> tuple[str, int, str | None]:
        row = self._conn.execute(
            "SELECT status, fence_token, outcome_json FROM tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        outcome: str | None = str(row[2]) if row[2] is not None else None
        return (str(row[0]), int(row[1]), outcome)


@contextmanager
def open_ledger(db_path: Path) -> Generator[DurableTaskLedger]:
    """Open a WAL-mode DurableTaskLedger at `db_path` and close cleanly on exit."""
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None)
    try:
        _configure_wal_pragmas(conn)
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    fence_token INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    outcome_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    request_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    payload_hash TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                )
                """
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        else:
            if conn.in_transaction:
                conn.execute("COMMIT")

        yield DurableTaskLedger(conn)
    finally:
        conn.close()
