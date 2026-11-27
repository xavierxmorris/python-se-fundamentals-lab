"""M04 Drill B Reference Solution: Strictly typed EventMiddlewarePipeline."""

from collections.abc import Mapping, Sequence
from typing import Protocol, TypedDict

from drill_a_core import Ok, Result, TaskEvent, is_ok, parse_event_dict, summarize_event


class BatchReport(TypedDict):
    total: int
    delivered: list[str]
    errors: list[str]


class EventHook(Protocol):
    def transform(self, event: TaskEvent, summary: str) -> Result[str, str]: ...


class EventMiddlewarePipeline:
    """Strictly typed event validation, formatting, and middleware pipeline."""

    def __init__(self, hooks: Sequence[EventHook] = ()) -> None:
        self._hooks: tuple[EventHook, ...] = tuple(hooks)

    def process(self, raw_event: Mapping[str, object]) -> Result[str, str]:
        parsed = parse_event_dict(raw_event)
        if not is_ok(parsed):
            return parsed

        event = parsed.value
        current_summary = summarize_event(event)
        for hook in self._hooks:
            step = hook.transform(event, current_summary)
            if not is_ok(step):
                return step
            current_summary = step.value
        return Ok(current_summary)

    def process_batch(self, payloads: Sequence[Mapping[str, object]]) -> BatchReport:
        delivered: list[str] = []
        errors: list[str] = []
        for payload in payloads:
            outcome = self.process(payload)
            if is_ok(outcome):
                delivered.append(outcome.value)
            else:
                errors.append(outcome.error)
        return {
            "total": len(payloads),
            "delivered": delivered,
            "errors": errors,
        }
