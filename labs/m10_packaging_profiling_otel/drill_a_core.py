"""M10 Drill A (Cold-Turkey Core): Profiling (`tracemalloc`) & `contextvars` Span Telemetry.

Implement the contracts below with AI completions disabled.

Required Behavioral Specification
---------------------------------
1. `current_span_context() -> tuple[str, str] | None`:
   - Reads a module-level `contextvars.ContextVar` holding `(trace_id, span_id)` for the
     currently active span, returning `None` when outside any active span.

2. `Tracer`:
   - Stores completed `SpanRecord` items in `self.spans: list[SpanRecord]` in completion order
     and returns a shallow list copy from `self.finished_spans() -> list[SpanRecord]`.
   - `start_span(name: str, **attrs: SpanAttrValue) -> Generator[dict[str, SpanAttrValue], None, None]`:
     * Rejects empty or whitespace-only `name` with `ValueError`.
     * If `current_span_context()` is `None`, generates a fresh 32-char lowercase hex `trace_id`
       and sets `parent_span_id = None`.
     * If nested inside an active span `(active_trace_id, active_span_id)`, inherits
       `trace_id = active_trace_id` and sets `parent_span_id = active_span_id`.
     * Generates a fresh 16-char lowercase hex `span_id` and binds `(trace_id, span_id)` in the
       module `ContextVar`.
     * Yields a mutable `dict[str, SpanAttrValue]` seeded with `attrs` so callers may attach
       dynamic attributes inside the `with` block.
     * On normal exit, records `status="ok"`.
     * If any `BaseException` escapes the body, sets `status="error"` and records
       `"error.type": type(exc).__name__` in the span attributes before re-raising the exception.
     * Always resets the `ContextVar` token in `finally:` and appends the immutable `SpanRecord`
       (whose `attributes` mapping cannot be mutated after completion) to `self.spans`.
   - `start_async_span(name: str, **attrs: SpanAttrValue)` provides an `@asynccontextmanager`
     wrapper sharing the exact same `ContextVar` semantics.

3. `measure_allocations(fn: Callable[[], object]) -> AllocationReport`:
   - Uses `tracemalloc` to execute `fn()` and return `AllocationReport(peak_kib, top_file, top_line)`.
   - `peak_kib` is peak traced bytes divided by `1024.0`.
   - `top_file` and `top_line` identify the top `"lineno"` allocation frame (or `("<none>", 0)`
     if zero allocations occurred).
   - Preserves external `tracemalloc` state: if `tracemalloc.is_tracing()` was `False` before
     `measure_allocations`, `tracemalloc` MUST be stopped in `finally:` (even if `fn` raises);
     if it was already `True`, `tracemalloc` MUST remain tracing afterward.

4. `redact_sensitive_fields(records, secret_keys) -> list[dict[str, str]]`:
   - Returns a new `list[dict[str, str]]` where any entry whose key matches `secret_keys`
     case-insensitively has its value replaced by `"[REDACTED]"` (preserving the original key name).
   - Runs in linear $O(n \\cdot k)$ time without mutating caller mappings.
"""

from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    Callable,
    Generator,
    Mapping,
    Sequence,
)
from collections.abc import (
    Set as AbstractSet,
)
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

type SpanAttrValue = str | int | float | bool

_ACTIVE_SPAN: ContextVar[tuple[str, str] | None] = ContextVar(
    "taskledger_active_span",
    default=None,
)


@dataclass(slots=True, frozen=True)
class SpanRecord:
    """Immutable completed telemetry span."""

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    duration_ms: float
    status: Literal["ok", "error"]
    attributes: Mapping[str, SpanAttrValue]


@dataclass(slots=True, frozen=True)
class AllocationReport:
    """Heap allocation summary captured around a callable invocation."""

    peak_kib: float
    top_file: str
    top_line: int


def current_span_context() -> tuple[str, str] | None:
    """Return `(trace_id, span_id)` for the active span in this execution context, or `None`."""
    raise NotImplementedError("Implement current_span_context using _ACTIVE_SPAN")


class Tracer:
    """Structured `ContextVar`-backed span recorder safe across sync and async call trees."""

    spans: list[SpanRecord]

    def __init__(self) -> None:
        self.spans = []

    def finished_spans(self) -> list[SpanRecord]:
        """Return a shallow list copy of recorded spans."""
        raise NotImplementedError("Implement Tracer.finished_spans")

    @contextmanager
    def start_span(
        self,
        name: str,
        **attrs: SpanAttrValue,
    ) -> Generator[dict[str, SpanAttrValue], None, None]:
        """Start a synchronous/context-propagated span and record a `SpanRecord` on exit."""
        raise NotImplementedError("Implement Tracer.start_span")

    @asynccontextmanager
    async def start_async_span(
        self,
        name: str,
        **attrs: SpanAttrValue,
    ) -> AsyncGenerator[dict[str, SpanAttrValue], None]:
        """Async context manager delegating to `start_span`."""
        with self.start_span(name, **attrs) as span_attrs:
            yield span_attrs


def measure_allocations(fn: Callable[[], object]) -> AllocationReport:
    """Measure peak heap usage in KiB and the top allocation site while calling `fn()`."""
    raise NotImplementedError("Implement measure_allocations with tracemalloc")


def redact_sensitive_fields(
    records: Sequence[Mapping[str, str]],
    secret_keys: AbstractSet[str],
) -> list[dict[str, str]]:
    """Return new dicts with values for case-insensitive `secret_keys` replaced by `'[REDACTED]'`."""
    raise NotImplementedError("Implement redact_sensitive_fields")
