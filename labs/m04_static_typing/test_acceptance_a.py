"""Frozen acceptance suite for M04 Drill A."""

import pytest

from drill_a_core import (
    CancelledEvent,
    Err,
    FinishedEvent,
    Ok,
    QueuedEvent,
    Result,
    StartedEvent,
    TaskEvent,
    and_then,
    invoke_plugin,
    is_ok,
    map_ok,
    parse_event_dict,
    summarize_event,
)


def _extract_or_len(res: Result[int, str]) -> int:
    if is_ok(res):
        return res.value
    return len(res.error)


def test_is_ok_narrows_both_branches() -> None:
    assert is_ok(Ok(42)) is True
    assert is_ok(Err("boom")) is False
    assert _extract_or_len(Ok(10)) == 10
    assert _extract_or_len(Err("timeout")) == 7


def test_map_ok_transforms_ok_and_preserves_err_without_calling_fn() -> None:
    assert map_ok(Ok(5), lambda x: f"v={x * 2}") == Ok("v=10")

    called = False

    def _never(x: int) -> str:
        nonlocal called
        called = True
        return str(x)

    err_in: Result[int, str] = Err("network_unreachable")
    assert map_ok(err_in, _never) == Err("network_unreachable")
    assert called is False


def test_and_then_chains_and_short_circuits() -> None:
    def _parse_positive(raw: str) -> Result[int, str]:
        if raw.isdigit() and int(raw) > 0:
            return Ok(int(raw))
        return Err("not_positive")

    assert and_then(Ok("12"), _parse_positive) == Ok(12)
    assert and_then(Ok("0"), _parse_positive) == Err("not_positive")
    assert and_then(Err("missing_input"), _parse_positive) == Err("missing_input")


def test_structural_tool_plugin_and_blank_name_guard() -> None:
    class UppercasePlugin:
        def __init__(self, plugin_name: str) -> None:
            self._name = plugin_name

        @property
        def name(self) -> str:
            return self._name

        def execute(self, request: str) -> Result[int, str]:
            if not request:
                return Err("empty_request")
            return Ok(len(request.upper()))

    assert invoke_plugin(UppercasePlugin("upper-len"), "hello") == Ok(5)
    assert invoke_plugin(UppercasePlugin("upper-len"), "") == Err("empty_request")
    assert invoke_plugin(UppercasePlugin("   "), "hello") == Err("invalid_plugin_name")


def test_summarize_event_exhaustive_variants() -> None:
    events: list[TaskEvent] = [
        QueuedEvent("queued", "t-100", 2),
        StartedEvent("started", "t-100", "worker-east-1"),
        FinishedEvent("finished", "t-100", 0),
        FinishedEvent("finished", "t-101", 137),
        CancelledEvent("cancelled", "t-102", "user_aborted"),
    ]
    summaries = [summarize_event(ev) for ev in events]
    assert summaries == [
        "[t-100] queued (priority=2)",
        "[t-100] started on worker-east-1",
        "[t-100] succeeded (exit_code=0)",
        "[t-101] failed (exit_code=137)",
        "[t-102] cancelled: user_aborted",
    ]


def test_summarize_event_rejects_non_union_runtime_value() -> None:
    bogus: object = {"kind": "queued", "task_id": "t-1", "priority": 1}
    with pytest.raises(AssertionError):
        summarize_event(bogus)  # pyright: ignore[reportArgumentType]


def test_parse_event_dict_happy_paths_and_strict_rejections() -> None:
    assert parse_event_dict({"kind": "queued", "task_id": "t-1", "priority": 3}) == Ok(
        QueuedEvent("queued", "t-1", 3)
    )
    assert parse_event_dict({"kind": "started", "task_id": "t-1", "worker_id": "w-9"}) == Ok(
        StartedEvent("started", "t-1", "w-9")
    )
    assert parse_event_dict({"kind": "finished", "task_id": "t-1", "exit_code": 0}) == Ok(
        FinishedEvent("finished", "t-1", 0)
    )
    assert parse_event_dict({"kind": "cancelled", "task_id": "t-1", "reason": "timeout"}) == Ok(
        CancelledEvent("cancelled", "t-1", "timeout")
    )

    assert parse_event_dict({"kind": "queued", "task_id": "  ", "priority": 1}) == Err("invalid_task_id")
    assert parse_event_dict({"kind": 123, "task_id": "t-1"}) == Err("invalid_kind")
    assert parse_event_dict({"kind": "queued", "task_id": "t-1", "priority": True}) == Err("invalid_priority")
    assert parse_event_dict({"kind": "finished", "task_id": "t-1", "exit_code": False}) == Err("invalid_exit_code")
    assert parse_event_dict({"kind": "started", "task_id": "t-1", "worker_id": ""}) == Err("invalid_worker_id")
    assert parse_event_dict({"kind": "cancelled", "task_id": "t-1", "reason": "   "}) == Err("invalid_reason")
    assert parse_event_dict({"kind": "paused", "task_id": "t-1"}) == Err("unknown_kind:paused")
