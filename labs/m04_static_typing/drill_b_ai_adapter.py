"""M04 Drill B (Spec-First AI Pair): Event middleware pipeline.

Audit and remediate the flawed AI-generated pipeline below:
- Replace all `Any` leaks with `Mapping[str, object]`, `EventHook(Protocol)`, `BatchReport(TypedDict)`, and `Result`.
- Delegate parsing & formatting to `parse_event_dict` and `summarize_event` so `"cancelled"` and `bool`-as-`int` cases are handled soundly.
- Short-circuit hook execution when an `EventHook` returns `Err`.
"""

from collections.abc import Sequence
from typing import Any, Protocol, TypedDict

from drill_a_core import Err, Ok, Result, TaskEvent


class BatchReport(TypedDict):
    total: int
    delivered: list[str]
    errors: list[str]


class EventHook(Protocol):
    def transform(self, event: TaskEvent, summary: str) -> Result[str, str]: ...


class EventMiddlewarePipeline:
    """Flawed AI-generated middleware pipeline with `Any` holes and missing union cases."""

    def __init__(self, hooks: Sequence[Any] = ()) -> None:
        self._hooks: list[Any] = list(hooks)

    def process(self, raw_event: dict[str, Any]) -> Result[str, str]:
        task_id = raw_event.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            return Err("invalid_task_id")

        kind = raw_event.get("kind")
        if kind == "queued":
            priority = raw_event.get("priority")
            if not isinstance(priority, int):
                return Err("invalid_priority")
            summary = f"[{task_id}] queued (priority={priority})"
        elif kind == "started":
            worker_id = raw_event.get("worker_id")
            if not isinstance(worker_id, str) or not worker_id.strip():
                return Err("invalid_worker_id")
            summary = f"[{task_id}] started on {worker_id}"
        elif kind == "finished":
            exit_code = raw_event.get("exit_code")
            if not isinstance(exit_code, int):
                return Err("invalid_exit_code")
            state = "succeeded" if exit_code == 0 else "failed"
            summary = f"[{task_id}] {state} (exit_code={exit_code})"
        else:
            return None

        for hook in self._hooks:
            step = hook.transform(raw_event, summary)
            if isinstance(step, Ok):
                summary = step.value
        return Ok(summary)

    def process_batch(self, payloads: Sequence[dict[str, Any]]) -> BatchReport:
        delivered: list[str] = []
        errors: list[str] = []
        for item in payloads:
            outcome = self.process(item)
            if isinstance(outcome, Ok):
                delivered.append(outcome.value)
            elif isinstance(outcome, Err):
                errors.append(outcome.error)
        return {"total": len(payloads), "delivered": delivered, "errors": errors}
