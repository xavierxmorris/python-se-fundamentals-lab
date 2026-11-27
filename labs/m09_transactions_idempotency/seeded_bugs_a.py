"""Seeded realistic mutants for M09 Gate 4 mutation testing."""

import hashlib
import json
import sqlite3
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

from drill_a_core import (
    DurableTaskLedger,
    IdempotencyConflictError,
    StoredSubmission,
    TaskNotFoundError,
)


def _bug_replay_reexecutes_side_effect(mod: ModuleType) -> None:
    class BuggyLedger(DurableTaskLedger):
        def submit_idempotent(
            self,
            request_id: str,
            task_id: str,
            payload: Mapping[str, object],
            compute_initial_snapshot: Callable[[], Mapping[str, object]],
        ) -> StoredSubmission:
            invoked = False

            def tracked_snapshot() -> Mapping[str, object]:
                nonlocal invoked
                invoked = True
                return compute_initial_snapshot()

            result = super().submit_idempotent(
                request_id,
                task_id,
                payload,
                tracked_snapshot,
            )
            if not invoked:
                compute_initial_snapshot()
            return result

    mod.__dict__["DurableTaskLedger"] = BuggyLedger


def _bug_ignore_payload_conflict(mod: ModuleType) -> None:
    orig_open = mod.open_ledger
    seen_by_scope: dict[tuple[str, str], StoredSubmission] = {}
    instance_scope: dict[int, str] = {}

    class BuggyLedger(DurableTaskLedger):
        def submit_idempotent(
            self,
            request_id: str,
            task_id: str,
            payload: Mapping[str, object],
            compute_initial_snapshot: Callable[[], Mapping[str, object]],
        ) -> StoredSubmission:
            scope = instance_scope.get(id(self), f"inst:{id(self)}")
            key = (scope, request_id)
            try:
                res = super().submit_idempotent(
                    request_id,
                    task_id,
                    payload,
                    compute_initial_snapshot,
                )
            except IdempotencyConflictError:
                cached = seen_by_scope.get(key)
                if cached is not None:
                    return cached
                raise
            replay_copy = StoredSubmission(
                request_id=res.request_id,
                task_id=res.task_id,
                payload_hash=res.payload_hash,
                snapshot_json=res.snapshot_json,
                created_new=False,
            )
            seen_by_scope[key] = replay_copy
            return res

    @contextmanager
    def buggy_open_ledger(db_path: Path) -> Generator[DurableTaskLedger]:
        with orig_open(db_path) as ledger:
            instance_scope[id(ledger)] = str(db_path.resolve())
            try:
                yield ledger
            finally:
                instance_scope.pop(id(ledger), None)

    mod.__dict__["DurableTaskLedger"] = BuggyLedger
    mod.__dict__["open_ledger"] = buggy_open_ledger


def _bug_non_canonical_payload_hash(mod: ModuleType) -> None:
    class BuggyLedger(DurableTaskLedger):
        def submit_idempotent(
            self,
            request_id: str,
            task_id: str,
            payload: Mapping[str, object],
            compute_initial_snapshot: Callable[[], Mapping[str, object]],
        ) -> StoredSubmission:
            non_canonical = json.dumps(
                dict(payload),
                sort_keys=False,
                separators=(",", ":"),
            )
            naive_hash = hashlib.sha256(non_canonical.encode("utf-8")).hexdigest()
            wrapped_payload: dict[str, object] = {
                "__insertion_order_wire__": non_canonical,
                "payload": dict(payload),
            }
            res = super().submit_idempotent(
                request_id,
                task_id,
                wrapped_payload,
                compute_initial_snapshot,
            )
            return StoredSubmission(
                request_id=res.request_id,
                task_id=res.task_id,
                payload_hash=naive_hash,
                snapshot_json=res.snapshot_json,
                created_new=res.created_new,
            )

    mod.__dict__["DurableTaskLedger"] = BuggyLedger


def _bug_ignore_fence_token_on_outcome(mod: ModuleType) -> None:
    class BuggyLedger(DurableTaskLedger):
        def record_outcome(self, task_id: str, fence_token: int, outcome_json: str) -> None:
            try:
                candidates = tuple(vars(self).values())
            except TypeError:
                candidates = ()
            conn = next(
                (val for val in candidates if isinstance(val, sqlite3.Connection)),
                None,
            )
            if conn is not None:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    exists = conn.execute(
                        "SELECT 1 FROM tasks WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()
                    if exists is None:
                        raise TaskNotFoundError(task_id)
                    conn.execute(
                        "UPDATE tasks SET status = 'succeeded', outcome_json = ? WHERE task_id = ?",
                        (outcome_json, task_id),
                    )
                except BaseException:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
                else:
                    if conn.in_transaction:
                        conn.execute("COMMIT")
                return

            _, current_fence, _ = self.get_task_outcome(task_id)
            super().record_outcome(task_id, current_fence, outcome_json)

    mod.__dict__["DurableTaskLedger"] = BuggyLedger


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "replay_reexecutes_side_effect": _bug_replay_reexecutes_side_effect,
    "ignore_payload_conflict": _bug_ignore_payload_conflict,
    "non_canonical_payload_hash": _bug_non_canonical_payload_hash,
    "ignore_fence_token_on_outcome": _bug_ignore_fence_token_on_outcome,
}
