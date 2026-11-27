"""Frozen acceptance suite for M01 Drill B (`RunContextBatcher`)."""

from __future__ import annotations

import pytest

from drill_b_ai_adapter import RunContextBatcher


def test_add_run_does_not_leak_shared_metadata_across_calls() -> None:
    batcher_a = RunContextBatcher("wave-1")
    batcher_b = RunContextBatcher("wave-2")

    ctx_1 = batcher_a.add_run("task-alpha", "acme", [1])
    ctx_2 = batcher_b.add_run("task-beta", "globex", [1, 2])

    assert ctx_1.metadata["wave_id"] == "wave-1"
    assert ctx_1.metadata["last_task_id"] == "task-alpha"
    assert ctx_2.metadata["wave_id"] == "wave-2"
    assert ctx_2.metadata["last_task_id"] == "task-beta"


def test_add_run_does_not_mutate_caller_retries_or_metadata() -> None:
    batcher = RunContextBatcher("wave-9")
    caller_retries = [1, 2]
    caller_meta = {"region": "ap-southeast-2"}

    ctx = batcher.add_run("task-9", "acme", caller_retries, caller_meta)

    assert caller_retries == [1, 2]
    assert caller_meta == {"region": "ap-southeast-2"}
    assert ctx.attempt_history == (1, 2, 3)

    caller_meta["region"] = "mutated"
    assert ctx.metadata["region"] == "ap-southeast-2"

    with pytest.raises(TypeError):
        ctx.metadata["injected"] = "boom"  # type: ignore[index]


def test_for_tenant_uses_value_equality_not_identity() -> None:
    batcher = RunContextBatcher("wave-eq")
    stored_tenant = "".join(["ten", "ant", "-", str(42)])
    lookup_tenant = f"tenant-{21 * 2}"
    assert stored_tenant == lookup_tenant
    assert stored_tenant is not lookup_tenant

    batcher.add_run("t-1", stored_tenant, [])
    batcher.add_run("t-2", "other", [])

    matched = batcher.for_tenant(lookup_tenant)
    assert [c.task_id for c in matched] == ["t-1"]
