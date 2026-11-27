"""Reference learner test suite for M09 Drill A (kills 100% of seeded_bugs_a mutants)."""

from pathlib import Path

import pytest

from drill_a_core import (
    IdempotencyConflictError,
    StaleFenceError,
    TaskNotFoundError,
    open_ledger,
)


def test_duplicate_replay_returns_stored_snapshot_without_rerunning_side_effect(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "replay.db"
    invocations = 0

    def compute_snapshot() -> dict[str, object]:
        nonlocal invocations
        invocations += 1
        return {"run": invocations, "status": "seeded"}

    with open_ledger(db_path) as ledger:
        first = ledger.submit_idempotent(
            "req-replay",
            "task-replay",
            {"tenant": "acme", "units": 3},
            compute_snapshot,
        )
        assert first.created_new is True
        assert invocations == 1

        second = ledger.submit_idempotent(
            "req-replay",
            "task-replay",
            {"tenant": "acme", "units": 3},
            compute_snapshot,
        )
        assert second.created_new is False
        assert second.snapshot_json == first.snapshot_json
        assert second.payload_hash == first.payload_hash
        assert invocations == 1


def test_payload_divergence_on_same_request_id_raises_conflict(tmp_path: Path) -> None:
    db_path = tmp_path / "conflict.db"
    calls = 0

    def snap() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"ok": True}

    with open_ledger(db_path) as ledger:
        ledger.submit_idempotent("req-42", "task-42", {"amount": 100}, snap)
        with pytest.raises(IdempotencyConflictError):
            ledger.submit_idempotent("req-42", "task-42", {"amount": 999}, snap)
        assert calls == 1

    # Conflict check also persists across a fresh ledger connection
    with open_ledger(db_path) as reopened, pytest.raises(IdempotencyConflictError):
        reopened.submit_idempotent("req-42", "task-42", {"amount": 101}, snap)


def test_canonical_payload_hash_matches_across_reordered_dict_keys(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "canonical.db"
    side_effects = 0

    def snap() -> dict[str, object]:
        nonlocal side_effects
        side_effects += 1
        return {"step": side_effects}

    with open_ledger(db_path) as ledger:
        created = ledger.submit_idempotent(
            "req-keys",
            "task-keys",
            {"z_last": 9, "a_first": {"beta": 2, "alpha": 1}},
            snap,
        )
        replayed = ledger.submit_idempotent(
            "req-keys",
            "task-keys",
            {"a_first": {"alpha": 1, "beta": 2}, "z_last": 9},
            snap,
        )
        assert created.created_new is True
        assert replayed.created_new is False
        assert replayed.payload_hash == created.payload_hash
        assert side_effects == 1


def test_fence_token_prevents_stale_worker_overwrite_and_checks_missing_tasks(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "fence.db"
    with open_ledger(db_path) as ledger:
        with pytest.raises(TaskNotFoundError):
            ledger.acquire_lease("missing", "w-0")
        with pytest.raises(TaskNotFoundError):
            ledger.record_outcome("missing", 1, "{}")
        with pytest.raises(TaskNotFoundError):
            ledger.get_task_outcome("missing")

        ledger.submit_idempotent("req-1", "task-1", {"job": "bill"}, lambda: {"ok": 1})
        lease_1 = ledger.acquire_lease("task-1", "worker-1")
        lease_2 = ledger.acquire_lease("task-1", "worker-2")
        assert lease_1.fence_token == 1
        assert lease_2.fence_token == 2

        with pytest.raises(StaleFenceError):
            ledger.record_outcome("task-1", lease_1.fence_token, '{"by":"worker-1"}')

        assert ledger.get_task_outcome("task-1") == ("leased", 2, None)

        ledger.record_outcome("task-1", lease_2.fence_token, '{"by":"worker-2"}')
        assert ledger.get_task_outcome("task-1") == (
            "succeeded",
            2,
            '{"by":"worker-2"}',
        )

        with pytest.raises(StaleFenceError):
            ledger.record_outcome("task-1", lease_1.fence_token, '{"by":"late-worker-1"}')
        with pytest.raises(StaleFenceError):
            ledger.acquire_lease("task-1", "worker-3")
