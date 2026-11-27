"""Frozen acceptance suite for M09 Drill A (DurableTaskLedger, Idempotency & Fencing)."""

import hashlib
import json
import sqlite3
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from drill_a_core import (
    IdempotencyConflictError,
    LeaseGrant,
    StaleFenceError,
    StoredSubmission,
    TaskNotFoundError,
    open_ledger,
)


def test_value_objects_are_frozen_slotted_and_exceptions_typed() -> None:
    sub = StoredSubmission("r1", "t1", "abc", "{}", True)
    lease = LeaseGrant("t1", "w1", 1)
    assert hasattr(StoredSubmission, "__slots__")
    assert hasattr(LeaseGrant, "__slots__")
    assert not hasattr(sub, "__dict__")
    assert not hasattr(lease, "__dict__")
    with pytest.raises(FrozenInstanceError):
        sub.created_new = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        lease.fence_token = 2  # type: ignore[misc]
    assert issubclass(TaskNotFoundError, KeyError)


def test_idempotent_submission_replay_and_canonical_key_order(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    side_effects = 0

    def build_snapshot() -> dict[str, object]:
        nonlocal side_effects
        side_effects += 1
        return {"seq": side_effects, "state": "initialized"}

    with open_ledger(db_path) as ledger:
        first = ledger.submit_idempotent(
            "req-100",
            "task-100",
            {"b": [1, 2], "a": {"z": True, "y": "ok"}},
            build_snapshot,
        )
        expected_canonical = json.dumps(
            {"a": {"y": "ok", "z": True}, "b": [1, 2]},
            sort_keys=True,
            separators=(",", ":"),
        )
        expected_hash = hashlib.sha256(expected_canonical.encode("utf-8")).hexdigest()
        assert first == StoredSubmission(
            request_id="req-100",
            task_id="task-100",
            payload_hash=expected_hash,
            snapshot_json='{"seq":1,"state":"initialized"}',
            created_new=True,
        )
        assert side_effects == 1
        assert ledger.get_task_outcome("task-100") == ("queued", 0, None)

        # Replay with permuted dict key order at both top-level and nested dict
        replay = ledger.submit_idempotent(
            "req-100",
            "task-100",
            {"a": {"y": "ok", "z": True}, "b": [1, 2]},
            build_snapshot,
        )
        assert replay == StoredSubmission(
            request_id="req-100",
            task_id="task-100",
            payload_hash=expected_hash,
            snapshot_json='{"seq":1,"state":"initialized"}',
            created_new=False,
        )
        assert side_effects == 1


def test_idempotency_conflict_and_snapshot_error_rollback(tmp_path: Path) -> None:
    db_path = tmp_path / "conflict.db"
    calls = 0

    def make_snap() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    with open_ledger(db_path) as ledger:
        ledger.submit_idempotent("req-1", "task-1", {"amount": 50}, make_snap)
        assert calls == 1

        with pytest.raises(IdempotencyConflictError):
            ledger.submit_idempotent("req-1", "task-1", {"amount": 75}, make_snap)
        assert calls == 1

        # Failing snapshot callback must roll back cleanly so a retry succeeds
        def exploding_snap() -> dict[str, object]:
            raise RuntimeError("disk snapshot failed")

        with pytest.raises(RuntimeError, match="disk snapshot failed"):
            ledger.submit_idempotent("req-2", "task-2", {"x": 1}, exploding_snap)

        with pytest.raises(TaskNotFoundError):
            ledger.get_task_outcome("task-2")

        recovered = ledger.submit_idempotent("req-2", "task-2", {"x": 1}, make_snap)
        assert recovered.created_new is True
        assert ledger.get_task_outcome("task-2") == ("queued", 0, None)


def test_lease_fencing_blocks_stale_workers_and_completed_reentry(tmp_path: Path) -> None:
    db_path = tmp_path / "fencing.db"
    with open_ledger(db_path) as ledger:
        ledger.submit_idempotent("req-f", "task-f", {"op": "charge"}, lambda: {"v": 1})

        # Cannot record outcome while still 'queued' (before lease)
        with pytest.raises(StaleFenceError):
            ledger.record_outcome("task-f", 0, '{"res":"premature"}')

        lease_a = ledger.acquire_lease("task-f", "worker-a")
        assert lease_a == LeaseGrant(task_id="task-f", worker_id="worker-a", fence_token=1)
        assert ledger.get_task_outcome("task-f") == ("leased", 1, None)

        # Worker A stalls; Worker B steals lease and advances fence_token to 2
        lease_b = ledger.acquire_lease("task-f", "worker-b")
        assert lease_b == LeaseGrant(task_id="task-f", worker_id="worker-b", fence_token=2)
        assert ledger.get_task_outcome("task-f") == ("leased", 2, None)

        # Stale Worker A wakes up and tries to commit with fence_token=1
        with pytest.raises(StaleFenceError):
            ledger.record_outcome("task-f", lease_a.fence_token, '{"winner":"worker-a"}')
        assert ledger.get_task_outcome("task-f") == ("leased", 2, None)

        # Current Worker B commits successfully with fence_token=2
        ledger.record_outcome("task-f", lease_b.fence_token, '{"winner":"worker-b"}')
        assert ledger.get_task_outcome("task-f") == (
            "succeeded",
            2,
            '{"winner":"worker-b"}',
        )

        # Terminal 'succeeded' task rejects both duplicate record_outcome and re-lease
        with pytest.raises(StaleFenceError):
            ledger.record_outcome("task-f", lease_b.fence_token, '{"winner":"tamper"}')
        with pytest.raises(StaleFenceError):
            ledger.acquire_lease("task-f", "worker-c")


def test_missing_task_raises_task_not_found_and_wal_mode_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "wal_check.db"
    with open_ledger(db_path) as ledger:
        with pytest.raises(TaskNotFoundError):
            ledger.acquire_lease("nope", "w1")
        with pytest.raises(TaskNotFoundError):
            ledger.record_outcome("nope", 1, "{}")
        with pytest.raises(TaskNotFoundError):
            ledger.get_task_outcome("nope")

    conn = sqlite3.connect(db_path)
    try:
        mode = str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower()
    finally:
        conn.close()
    assert mode == "wal"


def test_concurrent_threads_submit_idempotent_runs_side_effect_once(tmp_path: Path) -> None:
    db_path = tmp_path / "concurrent.db"
    with open_ledger(db_path):
        pass

    barrier = threading.Barrier(6)
    lock = threading.Lock()
    side_effect_runs = 0
    results: list[StoredSubmission] = []
    errors: list[BaseException] = []

    def snap() -> dict[str, object]:
        nonlocal side_effect_runs
        with lock:
            side_effect_runs += 1
            return {"invocation": side_effect_runs}

    def worker(idx: int) -> None:
        payload: dict[str, object] = (
            {"k1": "v1", "k2": 42} if idx % 2 == 0 else {"k2": 42, "k1": "v1"}
        )
        try:
            barrier.wait()
            with open_ledger(db_path) as ledger:
                sub = ledger.submit_idempotent("shared-req", "shared-task", payload, snap)
            with lock:
                results.append(sub)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 6
    assert side_effect_runs == 1
    assert sum(1 for r in results if r.created_new) == 1
    assert sum(1 for r in results if not r.created_new) == 5
    assert len({r.snapshot_json for r in results}) == 1
