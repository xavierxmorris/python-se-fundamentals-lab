"""Reference learner test suite for M04 Drill A (kills 100% of seeded bugs)."""

from drill_a_core import (
    CancelledEvent,
    Err,
    FinishedEvent,
    Ok,
    QueuedEvent,
    Result,
    StartedEvent,
    and_then,
    invoke_plugin,
    is_ok,
    map_ok,
    parse_event_dict,
    summarize_event,
)


def _narrow_outcome(outcome: Result[int, str]) -> str:
    if is_ok(outcome):
        return f"ok:{outcome.value + 1}"
    return f"err:{outcome.error}"


def test_is_ok_and_both_branch_narrowing() -> None:
    assert is_ok(Ok(7)) is True
    assert is_ok(Err("bad")) is False
    assert _narrow_outcome(Ok(7)) == "ok:8"
    assert _narrow_outcome(Err("bad")) == "err:bad"


def test_map_ok_preserves_err_and_transforms_ok() -> None:
    assert map_ok(Ok(3), lambda n: n * 4) == Ok(12)

    invoked = False

    def _fail_if_called(n: int) -> int:
        nonlocal invoked
        invoked = True
        return n

    err_val: Result[int, str] = Err("upstream_down")
    mapped = map_ok(err_val, _fail_if_called)
    assert mapped == Err("upstream_down")
    assert invoked is False


def test_and_then_flat_maps_without_double_wrapping() -> None:
    def _halve_even(n: int) -> Result[int, str]:
        if n % 2 == 0:
            return Ok(n // 2)
        return Err("odd_value")

    chained_ok = and_then(Ok(8), _halve_even)
    assert chained_ok == Ok(4)
    assert and_then(chained_ok, _halve_even) == Ok(2)
    assert and_then(Ok(5), _halve_even) == Err("odd_value")
    assert and_then(Err("initial_failure"), _halve_even) == Err("initial_failure")


def test_tool_plugin_structural_subtyping_and_name_check() -> None:
    class WordCountPlugin:
        def __init__(self, label: str) -> None:
            self._label = label

        @property
        def name(self) -> str:
            return self._label

        def execute(self, request: str) -> Result[int, str]:
            words = [w for w in request.split() if w]
            return Ok(len(words))

    assert invoke_plugin(WordCountPlugin("word-count"), "one two three") == Ok(3)
    assert invoke_plugin(WordCountPlugin(""), "one two") == Err("invalid_plugin_name")
    assert invoke_plugin(WordCountPlugin("   \t "), "one two") == Err("invalid_plugin_name")


def test_summarize_event_distinguishes_nonzero_exit_and_includes_cancel_reason() -> None:
    assert summarize_event(QueuedEvent("queued", "t-1", 5)) == "[t-1] queued (priority=5)"
    assert summarize_event(StartedEvent("started", "t-1", "w-alpha")) == "[t-1] started on w-alpha"
    assert summarize_event(FinishedEvent("finished", "t-1", 0)) == "[t-1] succeeded (exit_code=0)"
    assert summarize_event(FinishedEvent("finished", "t-2", 9)) == "[t-2] failed (exit_code=9)"
    assert (
        summarize_event(CancelledEvent("cancelled", "t-3", "spot_eviction"))
        == "[t-3] cancelled: spot_eviction"
    )


def test_parse_event_dict_rejects_booleans_for_ints_and_malformed_fields() -> None:
    assert parse_event_dict({"kind": "queued", "task_id": "t-1", "priority": 0}) == Ok(
        QueuedEvent("queued", "t-1", 0)
    )
    assert parse_event_dict({"kind": "queued", "task_id": "t-1", "priority": True}) == Err(
        "invalid_priority"
    )
    assert parse_event_dict({"kind": "queued", "task_id": "t-1", "priority": False}) == Err(
        "invalid_priority"
    )
    assert parse_event_dict({"kind": "finished", "task_id": "t-1", "exit_code": True}) == Err(
        "invalid_exit_code"
    )
    assert parse_event_dict({"kind": "finished", "task_id": "t-1", "exit_code": -1}) == Ok(
        FinishedEvent("finished", "t-1", -1)
    )
    assert parse_event_dict({"kind": "started", "task_id": "t-1", "worker_id": "w-2"}) == Ok(
        StartedEvent("started", "t-1", "w-2")
    )
    assert parse_event_dict({"kind": "cancelled", "task_id": "t-1", "reason": "user_cancel"}) == Ok(
        CancelledEvent("cancelled", "t-1", "user_cancel")
    )
    assert parse_event_dict({"kind": "cancelled", "task_id": "t-1", "reason": ""}) == Err(
        "invalid_reason"
    )
    assert parse_event_dict({"kind": "bogus", "task_id": "t-1"}) == Err("unknown_kind:bogus")
    assert parse_event_dict({"kind": "queued", "task_id": ""}) == Err("invalid_task_id")
