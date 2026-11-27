"""Reference learner test suite for M12 Drill A (`drill_a_core.py`).

Isolates and kills 100% of the 4 capstone incident root causes in `seeded_bugs_a.py`.
"""

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


def test_rca_1_idempotent_replay_does_not_reexecute_prepare_tool(tmp_path: Path) -> None:
    """Kills `bug_1_duplicate_replay_tool_call`."""
    invocations = 0

    def side_effect_tool(payload: Mapping[str, object]) -> str:
        nonlocal invocations
        invocations += 1
        return f"tok-{invocations}-{payload.get('op')}"

    with TaskLedgerEngine(tmp_path / "rca1.db") as engine:
        initial = engine.submit_idempotent(
            request_id="req-dup-check",
            tenant="acme",
            payload={"op": "invoice", "cents": 500},
            prepare_tool=side_effect_tool,
        )
        replayed = engine.submit_idempotent(
            request_id="req-dup-check",
            tenant="acme",
            payload={"cents": 500, "op": "invoice"},
            prepare_tool=side_effect_tool,
        )
        assert invocations == 1
        assert initial.task_id == replayed.task_id
        assert replayed.replayed_count == 1
        assert replayed.metadata.get("prepared_ref") == "tok-1-invoice"

        with pytest.raises(IdempotencyConflictError):
            engine.submit_idempotent(
                request_id="req-dup-check",
                tenant="acme",
                payload={"op": "invoice", "cents": 999},
                prepare_tool=side_effect_tool,
            )
        assert invocations == 1


def test_rca_2_metadata_does_not_bleed_across_tenants_or_mutate_caller(tmp_path: Path) -> None:
    """Kills `bug_2_shared_mutable_metadata`."""
    caller_dict = {"team": "payments"}
    with TaskLedgerEngine(tmp_path / "rca2.db") as engine:
        first = engine.submit_idempotent(
            request_id="r-1",
            tenant="acme",
            payload={"n": 1},
        )
        second = engine.submit_idempotent(
            request_id="r-2",
            tenant="globex",
            payload={"n": 2},
        )
        third = engine.submit_idempotent(
            request_id="r-3",
            tenant="umbrella",
            payload={"n": 3},
            metadata=caller_dict,
        )

        assert first.metadata["origin_tenant"] == "acme"
        assert second.metadata["origin_tenant"] == "globex"
        assert third.metadata["origin_tenant"] == "umbrella"
        assert caller_dict == {"team": "payments"}


def test_rca_3_worker_propagates_cancelled_error_without_swallowing(tmp_path: Path) -> None:
    """Kills `bug_3_swallowed_cancelled_error`."""
    with TaskLedgerEngine(tmp_path / "rca3.db", max_attempts_default=1) as engine:
        queued = engine.submit_idempotent(
            request_id="slow-req",
            tenant="acme",
            payload={"wait": True},
        )
        leased = engine.acquire_lease(queued.task_id, worker_id="w-cancel")
        in_handler = asyncio.Event()

        async def blocking_worker(snap: TaskSnapshot) -> str:
            _ = snap
            assert current_span_context() is not None
            in_handler.set()
            await asyncio.sleep(30.0)
            return "done"

        async def run_and_cancel() -> None:
            task = asyncio.create_task(
                engine.execute_leased_task(leased, blocking_worker, task_timeout=30.0)
            )
            await in_handler.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(run_and_cancel())
        assert current_span_context() is None
        assert engine.get_task(queued.task_id).status == "leased"
        assert any(s.status == "error" for s in engine.spans)


def test_rca_4_complete_lease_rejects_stale_fence_token(tmp_path: Path) -> None:
    """Kills `bug_4_missing_fence_token_check`."""
    with TaskLedgerEngine(tmp_path / "rca4.db", max_attempts_default=3) as engine:
        snap = engine.submit_idempotent(
            request_id="fence-req",
            tenant="acme",
            payload={"k": "v"},
        )
        stale_lease = engine.acquire_lease(snap.task_id, worker_id="w-old")
        fresh_lease = engine.acquire_lease(snap.task_id, worker_id="w-new")
        assert fresh_lease.fence_token > stale_lease.fence_token

        # Stale worker attempts to complete while w-new owns the lease
        with pytest.raises(StaleFenceError):
            engine.complete_lease(
                snap.task_id,
                fence_token=stale_lease.fence_token,
                result="stale-result",
            )

        done = engine.complete_lease(
            snap.task_id,
            fence_token=fresh_lease.fence_token,
            result="authoritative-result",
        )
        assert done.status == "succeeded"
        assert done.result == "authoritative-result"

        # Stale worker attempts to overwrite after completion
        with pytest.raises(StaleFenceError):
            engine.complete_lease(
                snap.task_id,
                fence_token=stale_lease.fence_token,
                result="late-overwrite",
            )
        assert engine.get_task(snap.task_id).result == "authoritative-result"
