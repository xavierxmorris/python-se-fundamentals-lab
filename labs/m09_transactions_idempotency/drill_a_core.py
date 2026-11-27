"""M09 Drill A (Cold-Turkey Core): SQLite ACID Transactions, Idempotency & Lease Fencing.

Implement the following public surface without reading acceptance tests:

1. Exceptions:
   - `class IdempotencyConflictError(Exception)`
   - `class StaleFenceError(Exception)`
   - `class TaskNotFoundError(KeyError)`

2. Frozen slotted dataclasses:
   - `@dataclass(slots=True, frozen=True) class StoredSubmission`:
       * `request_id: str`
       * `task_id: str`
       * `payload_hash: str`
       * `snapshot_json: str`
       * `created_new: bool`
   - `@dataclass(slots=True, frozen=True) class LeaseGrant`:
       * `task_id: str`
       * `worker_id: str`
       * `fence_token: int`

3. `@contextmanager def open_ledger(db_path: Path) -> Generator[DurableTaskLedger]`:
   - Opens `sqlite3.connect(db_path, timeout=10.0, isolation_level=None)`.
   - Configures `PRAGMA journal_mode=WAL;`, `PRAGMA foreign_keys=ON;`, and
     `PRAGMA busy_timeout=10000;`.
   - Initializes `tasks` and `submissions` tables inside `BEGIN IMMEDIATE ... COMMIT`
     (with `ROLLBACK` on error) and closes the connection cleanly in `finally:`.

4. `class DurableTaskLedger`:
   - `submit_idempotent(
         self,
         request_id: str,
         task_id: str,
         payload: Mapping[str, object],
         compute_initial_snapshot: Callable[[], Mapping[str, object]],
     ) -> StoredSubmission`:
       * Canonicalizes `payload` via
         `json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))` and hashes its
         UTF-8 bytes with SHA-256 hex (`payload_hash`).
       * Inside `BEGIN IMMEDIATE` (with `ROLLBACK` on any error):
         - If `request_id` already exists with matching `payload_hash`, ends/commits the
           transaction and returns the stored submission with `created_new=False` WITHOUT
           calling `compute_initial_snapshot`.
         - If `request_id` already exists with a different `payload_hash`, rolls back and
           raises `IdempotencyConflictError` WITHOUT calling `compute_initial_snapshot`.
         - Otherwise invokes `compute_initial_snapshot()`, serializes the returned mapping
           canonically (`json.dumps(dict(...), sort_keys=True, separators=(",", ":"))`),
           inserts the task row (`fence_token=0`, `status='queued'`) and submission row,
           commits, and returns `StoredSubmission(..., created_new=True)`.
   - `acquire_lease(self, task_id: str, worker_id: str) -> LeaseGrant`:
       * Inside `BEGIN IMMEDIATE`: raises `TaskNotFoundError` if `task_id` is missing,
         `StaleFenceError` if `status == 'succeeded'`, otherwise increments
         `fence_token = fence_token + 1`, sets `status = 'leased'` and
         `lease_owner = worker_id`, commits, and returns `LeaseGrant`.
   - `record_outcome(self, task_id: str, fence_token: int, outcome_json: str) -> None`:
       * Inside `BEGIN IMMEDIATE`: raises `TaskNotFoundError` if `task_id` is missing;
         updates `status = 'succeeded', outcome_json = ?`
         `WHERE task_id = ? AND fence_token = ? AND status = 'leased'`; if `rowcount != 1`,
         rolls back and raises `StaleFenceError`; otherwise commits.
   - `get_task_outcome(self, task_id: str) -> tuple[str, int, str | None]`:
       * Returns `(status, fence_token, outcome_json)` or raises `TaskNotFoundError` if
         `task_id` is missing.
"""

import sqlite3
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


class DurableTaskLedger:
    """SQLite-backed durable task ledger with idempotent submissions and lease fencing."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def submit_idempotent(
        self,
        request_id: str,
        task_id: str,
        payload: Mapping[str, object],
        compute_initial_snapshot: Callable[[], Mapping[str, object]],
    ) -> StoredSubmission:
        raise NotImplementedError("Implement submit_idempotent in drill_a_core.py")

    def acquire_lease(self, task_id: str, worker_id: str) -> LeaseGrant:
        raise NotImplementedError("Implement acquire_lease in drill_a_core.py")

    def record_outcome(self, task_id: str, fence_token: int, outcome_json: str) -> None:
        raise NotImplementedError("Implement record_outcome in drill_a_core.py")

    def get_task_outcome(self, task_id: str) -> tuple[str, int, str | None]:
        raise NotImplementedError("Implement get_task_outcome in drill_a_core.py")


@contextmanager
def open_ledger(db_path: Path) -> Generator[DurableTaskLedger]:
    """Open a WAL-mode DurableTaskLedger at `db_path` and close cleanly on exit."""
    raise NotImplementedError("Implement open_ledger in drill_a_core.py")
