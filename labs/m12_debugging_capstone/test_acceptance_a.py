"""Frozen acceptance suite for M12 Drill A (`drill_a_core.py`)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest

from drill_a_core import (
    IdempotencyConflictError,
    StaleFenceError,
    TaskLedgerEngine,
    TaskSnapshot,
    current_span_context,
)


def test_idempotent_replay_runs_prepare_tool_once_and_rejects_conflict(tmp_path: Path) -> None:
    db_file = tmp_path / "ledger.db"
    tool_calls: list[Mapping[str, object]] = []

    def allocate_slot(payload: Mapping[str, object]) -> str:
        tool_calls.append(dict(payload))
        return f"slot-{len(tool_calls)}"

    with TaskLedgerEngine(db_file) as engine:
        first = engine.submit_idempotent(
            request_id="req-100",
            tenant="acme",
            payload={"b": 2, "a": 1},
            prepare_tool=allocate_slot,
        )
        replay = engine.submit_idempotent(
            request_id="req-100",
            tenant="acme",
            payload={"a": 1, "b": 2},
            prepare_tool=allocate_slot,
        )
        assert first.task_id == replay.task_id
        assert first.replayed_count == 0
        assert replay.replayed_count == 1
        assert replay.metadata.get("prepared_ref") == "slot-1"
        assert len(tool_calls) == 1

        with pytest.raises(IdempotencyConflictError):
            engine.submit_idempotent(
                request_id="req-100",
                tenant="acme",
                payload={"a": 1, "b": 999},
                prepare_tool=allocate_slot,
            )
        assert len(tool_calls) == 1


def test_metadata_isolation_across_tenants_and_caller_dicts(tmp_path: Path) -> None:
    db_file = tmp_path / "ledger.db"
    caller_meta = {"env": "prod"}

    with TaskLedgerEngine(db_file) as engine:
        t_acme = engine.submit_idempotent(
            request_id="r-acme",
            tenant="acme",
            payload={"job": 1},
        )
        t_globex = engine.submit_idempotent(
            request_id="r-globex",
            tenant="globex",
            payload={"job": 2},
        )
        t_custom = engine.submit_idempotent(
            request_id="r-custom",
            tenant="initech",
            payload={"job": 3},
            metadata=caller_meta,
        )

        assert t_acme.metadata["origin_tenant"] == "acme"
        assert t_globex.metadata["origin_tenant"] == "globex"
        assert t_custom.metadata["origin_tenant"] == "initech"
        assert caller_meta == {"env": "prod"}


def test_stale_worker_fence_cannot_overwrite_newer_lease(tmp_path: Path) -> None:
    db_file = tmp_path / "ledger.db"
    with TaskLedgerEngine(db_file, max_attempts_default=3) as engine:
        created = engine.submit_idempotent(
            request_id="req-fence",
            tenant="acme",
            payload={"step": "deploy"},
        )
        lease_1 = engine.acquire_lease(created.task_id, worker_id="worker-slow")
        assert lease_1.fence_token == 1

        # Lease reclaimed by worker-fast after timeout
        lease_2 = engine.acquire_lease(created.task_id, worker_id="worker-fast")
        assert lease_2.fence_token == 2

        completed = engine.complete_lease(
            created.task_id,
            fence_token=lease_2.fence_token,
            result="fresh-output",
        )
        assert completed.status == "succeeded"
        assert completed.result == "fresh-output"

        # Zombie worker-slow arrives late with fence_token=1
        with pytest.raises(StaleFenceError):
            engine.complete_lease(
                created.task_id,
                fence_token=lease_1.fence_token,
                result="corrupted-stale-output",
            )

        after = engine.get_task(created.task_id)
        assert after.result == "fresh-output"
        assert after.fence_token == 2


def test_worker_batch_bounded_concurrency_timeout_and_cancellation_propagation(
    tmp_path: Path,
) -> None:
    db_file = tmp_path / "ledger.db"
    with TaskLedgerEngine(db_file, max_attempts_default=2) as engine:
        for i in range(4):
            engine.submit_idempotent(
                request_id=f"batch-{i}",
                tenant="acme",
                payload={"idx": i},
            )

        active = 0
        peak_active = 0

        async def bounded_handler(snap: TaskSnapshot) -> str:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            try:
                await asyncio.sleep(0.01)
                if snap.payload.get("idx") == 3:
                    await asyncio.sleep(0.2)
                return f"done-{snap.request_id}"
            finally:
                active -= 1

        outcomes = asyncio.run(
            engine.run_worker_batch(
                bounded_handler,
                tenant="acme",
                max_concurrency=2,
                task_timeout=0.05,
            )
        )
        assert peak_active <= 2
        assert [o.status for o in outcomes] == ["succeeded", "succeeded", "succeeded", "failed"]
        assert current_span_context() is None

        # Submit a blocking task and verify external cancellation propagates CancelledError
        # without poisoning the leased task into 'dead_letter'!
        cancel_snap = engine.submit_idempotent(
            request_id="cancel-me",
            tenant="globex",
            payload={"hang": True},
            max_attempts=1,
        )
        started = asyncio.Event()

        async def hanging_handler(snap: TaskSnapshot) -> str:
            _ = snap
            started.set()
            await asyncio.sleep(10.0)
            return "unreachable"

        async def cancel_driver() -> None:
            batch_task = asyncio.create_task(
                engine.run_worker_batch(hanging_handler, tenant="globex", task_timeout=10.0)
            )
            await started.wait()
            batch_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await batch_task

        asyncio.run(cancel_driver())
        assert current_span_context() is None
        assert engine.get_task(cancel_snap.task_id).status == "leased"
