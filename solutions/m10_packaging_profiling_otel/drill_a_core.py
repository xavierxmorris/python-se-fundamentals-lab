"""Reference solution for M10 Drill A (`drill_a_core.py`)."""

from __future__ import annotations

import secrets
import time
import tracemalloc
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
from types import MappingProxyType
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
    return _ACTIVE_SPAN.get()


class Tracer:
    """Structured `ContextVar`-backed span recorder safe across sync and async call trees."""

    spans: list[SpanRecord]

    def __init__(self) -> None:
        self.spans = []

    def finished_spans(self) -> list[SpanRecord]:
        """Return a shallow list copy of recorded spans."""
        return list(self.spans)

    @contextmanager
    def start_span(
        self,
        name: str,
        **attrs: SpanAttrValue,
    ) -> Generator[dict[str, SpanAttrValue], None, None]:
        """Start a context-propagated span and record an immutable `SpanRecord` on exit."""
        if not name or not name.strip():
            raise ValueError("span name must be non-empty")

        parent = _ACTIVE_SPAN.get()
        if parent is None:
            trace_id = secrets.token_hex(16)
            parent_span_id: str | None = None
        else:
            trace_id, parent_span_id = parent

        span_id = secrets.token_hex(8)
        token = _ACTIVE_SPAN.set((trace_id, span_id))
        live_attrs: dict[str, SpanAttrValue] = dict(attrs)
        started_ns = time.perf_counter_ns()
        status: Literal["ok", "error"] = "ok"

        try:
            yield live_attrs
        except BaseException as exc:
            status = "error"
            live_attrs["error.type"] = type(exc).__name__
            raise
        finally:
            duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
            _ACTIVE_SPAN.reset(token)
            self.spans.append(
                SpanRecord(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    name=name,
                    duration_ms=duration_ms,
                    status=status,
                    attributes=MappingProxyType(dict(live_attrs)),
                )
            )

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
    tracemalloc_file = tracemalloc.__file__ or "tracemalloc.py"
    was_tracing = tracemalloc.is_tracing()
    if was_tracing:
        tracemalloc.reset_peak()
        before = tracemalloc.take_snapshot()
        keepalive = fn()
        after = tracemalloc.take_snapshot()
        _, peak_bytes = tracemalloc.get_traced_memory()
        del keepalive
        diffs = [
            d
            for d in after.compare_to(before, "lineno")
            if d.size_diff > 0 and d.traceback[0].filename != tracemalloc_file
        ]
        if diffs:
            frame = diffs[0].traceback[0]
            return AllocationReport(
                peak_kib=peak_bytes / 1024.0,
                top_file=frame.filename,
                top_line=frame.lineno,
            )
        stats = [s for s in after.statistics("lineno") if s.traceback[0].filename != tracemalloc_file]
    else:
        tracemalloc.start()
        try:
            keepalive = fn()
            snapshot = tracemalloc.take_snapshot()
            _, peak_bytes = tracemalloc.get_traced_memory()
            del keepalive
        finally:
            tracemalloc.stop()
        stats = [
            s for s in snapshot.statistics("lineno") if s.traceback[0].filename != tracemalloc_file
        ]

    if not stats:
        return AllocationReport(peak_kib=peak_bytes / 1024.0, top_file="<none>", top_line=0)

    top_frame = stats[0].traceback[0]
    return AllocationReport(
        peak_kib=peak_bytes / 1024.0,
        top_file=top_frame.filename,
        top_line=top_frame.lineno,
    )


def redact_sensitive_fields(
    records: Sequence[Mapping[str, str]],
    secret_keys: AbstractSet[str],
) -> list[dict[str, str]]:
    """Return new dicts with values for case-insensitive `secret_keys` replaced by `'[REDACTED]'`."""
    lowered_secrets = {key.lower() for key in secret_keys}
    return [
        {k: ("[REDACTED]" if k.lower() in lowered_secrets else v) for k, v in rec.items()}
        for rec in records
    ]
