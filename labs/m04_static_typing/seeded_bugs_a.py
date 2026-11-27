"""Seeded realistic mutants for M04 Gate 4 mutation testing."""

from collections.abc import Callable, Mapping
from types import ModuleType

import drill_a_core as _core


def _mutant_map_ok_corrupts_err(module: ModuleType) -> None:
    def buggy_map_ok[T, U, E](
        r: _core.Result[T, E],
        fn: Callable[[T], U],
    ) -> _core.Result[U, E]:
        if isinstance(r, _core.Ok):
            return _core.Ok(fn(r.value))
        raise ValueError("unexpected Err passed to map_ok")

    module.map_ok = buggy_map_ok  # type: ignore[attr-defined]


def _mutant_and_then_double_wraps(module: ModuleType) -> None:
    def buggy_and_then[T, U, E](
        r: _core.Result[T, E],
        fn: Callable[[T], _core.Result[U, E]],
    ) -> object:
        if isinstance(r, _core.Ok):
            return _core.Ok(fn(r.value))
        return r

    module.and_then = buggy_and_then  # type: ignore[attr-defined]


def _mutant_summarize_event_drops_failure_and_reason(module: ModuleType) -> None:
    def buggy_summarize_event(ev: _core.TaskEvent) -> str:
        match ev:
            case _core.QueuedEvent(task_id=tid, priority=prio):
                return f"[{tid}] queued (priority={prio})"
            case _core.StartedEvent(task_id=tid, worker_id=wid):
                return f"[{tid}] started on {wid}"
            case _core.FinishedEvent(task_id=tid, exit_code=code):
                return f"[{tid}] succeeded (exit_code={code})"
            case _core.CancelledEvent(task_id=tid):
                return f"[{tid}] cancelled"

    module.summarize_event = buggy_summarize_event  # type: ignore[attr-defined]


def _mutant_parse_event_allows_bool_as_int(module: ModuleType) -> None:
    def buggy_parse_event_dict(raw: Mapping[str, object]) -> _core.Result[_core.TaskEvent, str]:
        task_id = raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return _core.Err("invalid_task_id")
        kind = raw.get("kind")
        if not isinstance(kind, str):
            return _core.Err("invalid_kind")
        match kind:
            case "queued":
                priority = raw.get("priority")
                if not isinstance(priority, int):
                    return _core.Err("invalid_priority")
                return _core.Ok(_core.QueuedEvent("queued", task_id, priority))
            case "started":
                worker_id = raw.get("worker_id")
                if not isinstance(worker_id, str) or not worker_id.strip():
                    return _core.Err("invalid_worker_id")
                return _core.Ok(_core.StartedEvent("started", task_id, worker_id))
            case "finished":
                exit_code = raw.get("exit_code")
                if not isinstance(exit_code, int):
                    return _core.Err("invalid_exit_code")
                return _core.Ok(_core.FinishedEvent("finished", task_id, exit_code))
            case "cancelled":
                reason = raw.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    return _core.Err("invalid_reason")
                return _core.Ok(_core.CancelledEvent("cancelled", task_id, reason))
            case _:
                return _core.Err(f"unknown_kind:{kind}")

    module.parse_event_dict = buggy_parse_event_dict  # type: ignore[attr-defined]


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "map_ok_corrupts_err": _mutant_map_ok_corrupts_err,
    "and_then_double_wraps": _mutant_and_then_double_wraps,
    "summarize_event_drops_failure_and_reason": _mutant_summarize_event_drops_failure_and_reason,
    "parse_event_allows_bool_as_int": _mutant_parse_event_allows_bool_as_int,
}
