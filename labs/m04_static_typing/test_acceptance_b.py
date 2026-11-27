"""Frozen acceptance suite for M04 Drill B."""

from collections.abc import Mapping

from drill_a_core import CancelledEvent, Err, Ok, Result, TaskEvent
from drill_b_ai_adapter import BatchReport, EventMiddlewarePipeline


class PrefixAuditHook:
    """Structurally conforms to `EventHook` without inheriting from it."""

    def __init__(self, env_tag: str) -> None:
        self._env_tag = env_tag

    def transform(self, event: TaskEvent, summary: str) -> Result[str, str]:
        if isinstance(event, CancelledEvent) and event.reason == "security_hold":
            return Err("blocked_by_security_hold")
        return Ok(f"{self._env_tag}:{summary}")


class UpperHook:
    def transform(self, event: TaskEvent, summary: str) -> Result[str, str]:
        _ = event
        return Ok(summary.upper())


def test_pipeline_handles_cancelled_event_exhaustively() -> None:
    pipeline = EventMiddlewarePipeline()
    raw: Mapping[str, object] = {
        "kind": "cancelled",
        "task_id": "t-900",
        "reason": "deadline_exceeded",
    }
    assert pipeline.process(raw) == Ok("[t-900] cancelled: deadline_exceeded")


def test_pipeline_runs_structural_hooks_and_short_circuits_on_err() -> None:
    pipeline = EventMiddlewarePipeline(hooks=[PrefixAuditHook("prod"), UpperHook()])

    ok_res = pipeline.process({"kind": "queued", "task_id": "t-1", "priority": 4})
    assert ok_res == Ok("PROD:[T-1] QUEUED (PRIORITY=4)")

    blocked_res = pipeline.process(
        {"kind": "cancelled", "task_id": "t-2", "reason": "security_hold"}
    )
    assert blocked_res == Err("blocked_by_security_hold")


def test_pipeline_batch_rejects_bool_as_int_and_unknown_kinds() -> None:
    pipeline = EventMiddlewarePipeline(hooks=[PrefixAuditHook("stg")])
    payloads: list[Mapping[str, object]] = [
        {"kind": "started", "task_id": "t-10", "worker_id": "w-1"},
        {"kind": "cancelled", "task_id": "t-11", "reason": "manual_stop"},
        {"kind": "queued", "task_id": "t-12", "priority": True},
        {"kind": "unknown", "task_id": "t-13"},
    ]
    report: BatchReport = pipeline.process_batch(payloads)
    assert report == {
        "total": 4,
        "delivered": [
            "stg:[t-10] started on w-1",
            "stg:[t-11] cancelled: manual_stop",
        ],
        "errors": [
            "invalid_priority",
            "unknown_kind:unknown",
        ],
    }
