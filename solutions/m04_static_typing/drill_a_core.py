"""M04 Drill A Reference Solution: PEP 695 generics, Protocol, TypeIs & discriminated unions."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeIs, assert_never, runtime_checkable


@dataclass(slots=True, frozen=True)
class Ok[T]:
    """Successful outcome wrapper."""

    value: T


@dataclass(slots=True, frozen=True)
class Err[E]:
    """Error outcome wrapper."""

    error: E


type Result[T, E] = Ok[T] | Err[E]


def is_ok[T, E](r: Result[T, E]) -> TypeIs[Ok[T]]:
    """Return True iff `r` is an `Ok` instance, narrowing both branches via PEP 742 `TypeIs`."""
    return isinstance(r, Ok)


def map_ok[T, U, E](r: Result[T, E], fn: Callable[[T], U]) -> Result[U, E]:
    """Apply `fn` to `r.value` when `r` is `Ok`, wrapping in `Ok`; preserve `Err` unchanged."""
    if is_ok(r):
        return Ok(fn(r.value))
    return r


def and_then[T, U, E](r: Result[T, E], fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
    """Monadic bind: apply `fn` to `r.value` when `r` is `Ok`; preserve `Err` unchanged."""
    if is_ok(r):
        return fn(r.value)
    return r


@runtime_checkable
class ToolPlugin[InT, OutT](Protocol):
    """Structural protocol for third-party tool plugins (no inheritance required)."""

    @property
    def name(self) -> str: ...

    def execute(self, request: InT) -> Result[OutT, str]: ...


def invoke_plugin[InT, OutT](plugin: ToolPlugin[InT, OutT], request: InT) -> Result[OutT, str]:
    """Validate `plugin.name` is non-blank (`Err('invalid_plugin_name')` if blank), else execute."""
    if not plugin.name.strip():
        return Err("invalid_plugin_name")
    return plugin.execute(request)


@dataclass(slots=True, frozen=True)
class QueuedEvent:
    kind: Literal["queued"]
    task_id: str
    priority: int


@dataclass(slots=True, frozen=True)
class StartedEvent:
    kind: Literal["started"]
    task_id: str
    worker_id: str


@dataclass(slots=True, frozen=True)
class FinishedEvent:
    kind: Literal["finished"]
    task_id: str
    exit_code: int


@dataclass(slots=True, frozen=True)
class CancelledEvent:
    kind: Literal["cancelled"]
    task_id: str
    reason: str


type TaskEvent = QueuedEvent | StartedEvent | FinishedEvent | CancelledEvent


def summarize_event(ev: TaskEvent) -> str:
    """Format a `TaskEvent` exhaustively using `match` and `typing.assert_never`."""
    match ev:
        case QueuedEvent(task_id=task_id, priority=priority):
            return f"[{task_id}] queued (priority={priority})"
        case StartedEvent(task_id=task_id, worker_id=worker_id):
            return f"[{task_id}] started on {worker_id}"
        case FinishedEvent(task_id=task_id, exit_code=exit_code):
            if exit_code == 0:
                return f"[{task_id}] succeeded (exit_code=0)"
            return f"[{task_id}] failed (exit_code={exit_code})"
        case CancelledEvent(task_id=task_id, reason=reason):
            return f"[{task_id}] cancelled: {reason}"
        case _:
            assert_never(ev)


def _is_strict_int(value: object) -> TypeIs[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_blank_str(value: object) -> TypeIs[str]:
    return isinstance(value, str) and bool(value.strip())


def parse_event_dict(raw: Mapping[str, object]) -> Result[TaskEvent, str]:
    """Parse an untrusted mapping into `Ok(TaskEvent)` or `Err(reason)` without `Any` or `cast`."""
    task_id = raw.get("task_id")
    if not _is_non_blank_str(task_id):
        return Err("invalid_task_id")

    kind = raw.get("kind")
    if not isinstance(kind, str):
        return Err("invalid_kind")

    match kind:
        case "queued":
            priority = raw.get("priority")
            if not _is_strict_int(priority):
                return Err("invalid_priority")
            return Ok(QueuedEvent("queued", task_id, priority))
        case "started":
            worker_id = raw.get("worker_id")
            if not _is_non_blank_str(worker_id):
                return Err("invalid_worker_id")
            return Ok(StartedEvent("started", task_id, worker_id))
        case "finished":
            exit_code = raw.get("exit_code")
            if not _is_strict_int(exit_code):
                return Err("invalid_exit_code")
            return Ok(FinishedEvent("finished", task_id, exit_code))
        case "cancelled":
            reason = raw.get("reason")
            if not _is_non_blank_str(reason):
                return Err("invalid_reason")
            return Ok(CancelledEvent("cancelled", task_id, reason))
        case _:
            return Err(f"unknown_kind:{kind}")
