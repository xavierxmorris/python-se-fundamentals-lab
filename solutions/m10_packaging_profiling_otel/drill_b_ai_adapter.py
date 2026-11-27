"""Reference solution for M10 Drill B (`drill_b_ai_adapter.py`)."""

from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

_ACTIVE_BATCH_TRACE: ContextVar[str | None] = ContextVar(
    "taskledger_batch_trace_id",
    default=None,
)
_BEARER_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")


@dataclass(slots=True, frozen=True)
class TelemetryEvent:
    """Single raw span event arriving at the batch processor."""

    span_id: str
    name: str
    message: str
    attributes: Mapping[str, str]


@dataclass(slots=True, frozen=True)
class ExportedBatch:
    """Result summary emitted after deduplicating, scrubbing, and exporting a batch."""

    trace_id: str
    ndjson: str
    accepted_count: int
    duplicate_count: int


@runtime_checkable
class SpanExporter(Protocol):
    """Port receiving scrubbed NDJSON payloads per trace."""

    def export_ndjson(self, trace_id: str, payload: str) -> None: ...


class TelemetryBatchProcessor:
    """Processes batches of `TelemetryEvent` records into scrubbed NDJSON exports."""

    def __init__(self, exporter: SpanExporter, *, max_dedup_window: int = 1024) -> None:
        if max_dedup_window < 1:
            raise ValueError("max_dedup_window must be >= 1")
        self._exporter = exporter
        self._max_dedup_window = max_dedup_window
        self._dedup_order: deque[str] = deque()
        self._dedup_set: set[str] = set()

    def current_trace_id(self) -> str | None:
        """Return the trace ID active in the current execution context, or `None`."""
        return _ACTIVE_BATCH_TRACE.get()

    def dedup_cache_size(self) -> int:
        """Return the current number of cached span IDs in the deduplication window."""
        return len(self._dedup_set)

    def _record_span_id(self, span_id: str) -> bool:
        """Return `True` if `span_id` is new and record it in the bounded FIFO window."""
        if span_id in self._dedup_set:
            return False
        if len(self._dedup_order) >= self._max_dedup_window:
            evicted = self._dedup_order.popleft()
            self._dedup_set.discard(evicted)
        self._dedup_order.append(span_id)
        self._dedup_set.add(span_id)
        return True

    async def process_batch(
        self,
        trace_id: str,
        events: Sequence[TelemetryEvent],
    ) -> ExportedBatch:
        """Deduplicate events, scrub bearer tokens, export NDJSON, and return `ExportedBatch`."""
        if not trace_id or not trace_id.strip():
            raise ValueError("trace_id must be non-empty")

        token = _ACTIVE_BATCH_TRACE.set(trace_id)
        lines: list[str] = []
        accepted = 0
        duplicates = 0

        try:
            for event in events:
                await asyncio.sleep(0)
                if not self._record_span_id(event.span_id):
                    duplicates += 1
                    continue

                ctx_trace = _ACTIVE_BATCH_TRACE.get()
                assert ctx_trace is not None
                scrubbed_msg = _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", event.message)
                scrubbed_attrs = {
                    k: _BEARER_TOKEN_RE.sub(r"\1[REDACTED]", v)
                    for k, v in event.attributes.items()
                }
                lines.append(
                    json.dumps(
                        {
                            "trace_id": ctx_trace,
                            "span_id": event.span_id,
                            "name": event.name,
                            "message": scrubbed_msg,
                            "attributes": scrubbed_attrs,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                accepted += 1

            final_ndjson = "\n".join(lines)
            if accepted > 0:
                active_tid = _ACTIVE_BATCH_TRACE.get()
                assert active_tid is not None
                self._exporter.export_ndjson(active_tid, final_ndjson)
            return ExportedBatch(
                trace_id=trace_id,
                ndjson=final_ndjson,
                accepted_count=accepted,
                duplicate_count=duplicates,
            )
        finally:
            _ACTIVE_BATCH_TRACE.reset(token)
