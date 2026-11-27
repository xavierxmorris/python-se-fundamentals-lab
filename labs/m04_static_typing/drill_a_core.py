"""M04 Drill A (Cold-Turkey Core): PEP 695 generics, Protocol, TypeIs & discriminated unions.

Rules:
- Zero `Any`, zero `cast`, and zero `# type: ignore` comments.
- Use Python 3.12-3.14 PEP 695 type parameter syntax (`class Ok[T]:`, `type Result[T, E] = ...`).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeIs, runtime_checkable


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
    raise NotImplementedError("Implement is_ok in drill_a_core.py")


def map_ok[T, U, E](r: Result[T, E], fn: Callable[[T], U]) -> Result[U, E]:
    """Apply `fn` to `r.value` when `r` is `Ok`, wrapping in `Ok`; preserve `Err` unchanged."""
    raise NotImplementedError("Implement map_ok in drill_a_core.py")


def and_then[T, U, E](r: Result[T, E], fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
    """Monadic bind: apply `fn` to `r.value` when `r` is `Ok`; preserve `Err` unchanged."""
    raise NotImplementedError("Implement and_then in drill_a_core.py")


@runtime_checkable
class ToolPlugin[InT, OutT](Protocol):
    """Structural protocol for third-party tool plugins (no inheritance required)."""

    @property
    def name(self) -> str: ...

    def execute(self, request: InT) -> Result[OutT, str]: ...


def invoke_plugin[InT, OutT](plugin: ToolPlugin[InT, OutT], request: InT) -> Result[OutT, str]:
    """Validate `plugin.name` is non-blank (`Err('invalid_plugin_name')` if blank), else execute."""
    raise NotImplementedError("Implement invoke_plugin in drill_a_core.py")


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
    """Format a `TaskEvent` exhaustively using `match` and `typing.assert_never`.

    Required formats:
    - QueuedEvent:    f"[{ev.task_id}] queued (priority={ev.priority})"
    - StartedEvent:   f"[{ev.task_id}] started on {ev.worker_id}"
    - FinishedEvent:  f"[{ev.task_id}] succeeded (exit_code=0)" when exit_code == 0,
                      else f"[{ev.task_id}] failed (exit_code={ev.exit_code})"
    - CancelledEvent: f"[{ev.task_id}] cancelled: {ev.reason}"
    - Fallback:       assert_never(ev)
    """
    raise NotImplementedError("Implement summarize_event in drill_a_core.py")


def parse_event_dict(raw: Mapping[str, object]) -> Result[TaskEvent, str]:
    """Parse an untrusted mapping into `Ok(TaskEvent)` or `Err(reason)` without `Any` or `cast`.

    Validation rules:
    - `task_id` must be a non-blank `str`, else `Err("invalid_task_id")`.
    - `kind` must be a `str`, else `Err("invalid_kind")`.
    - `"queued"`: `priority` must be an `int` and NOT a `bool`, else `Err("invalid_priority")`.
    - `"started"`: `worker_id` must be a non-blank `str`, else `Err("invalid_worker_id")`.
    - `"finished"`: `exit_code` must be an `int` and NOT a `bool`, else `Err("invalid_exit_code")`.
    - `"cancelled"`: `reason` must be a non-blank `str`, else `Err("invalid_reason")`.
    - Any other `kind`: `Err(f"unknown_kind:{kind}")`.
    """
    raise NotImplementedError("Implement parse_event_dict in drill_a_core.py")
