"""M10 Drill B (Spec-First AI Pair): Telemetry Batch Processor.

WARNING: This "AI-generated" adapter contains 3 production defects:
  1. `_seen_spans` is an unbounded `list[str]` ($O(n)$ scan + memory leak ignoring `max_dedup_window`).
  2. `self.active_trace_id` is stored on `self`, scrambling `trace_id` across concurrent async batches.
  3. Per-event `re.compile(...)` + quadratic `ndjson_payload += ...` string concatenation inside the loop.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


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
        self._seen_spans: list[str] = []
        self.active_trace_id: str | None = None

    def current_trace_id(self) -> str | None:
        """Return the trace ID active in the current execution context, or `None`."""
        return self.active_trace_id

    def dedup_cache_size(self) -> int:
        """Return the current number of cached span IDs in the deduplication window."""
        return len(self._seen_spans)

    async def process_batch(
        self,
        trace_id: str,
        events: Sequence[TelemetryEvent],
    ) -> ExportedBatch:
        """Deduplicate events, scrub bearer tokens, export NDJSON, and return `ExportedBatch`."""
        if not trace_id or not trace_id.strip():
            raise ValueError("trace_id must be non-empty")

        self.active_trace_id = trace_id
        ndjson_payload = ""
        accepted = 0
        duplicates = 0

        for event in events:
            await asyncio.sleep(0)
            if event.span_id in self._seen_spans:
                duplicates += 1
                continue
            self._seen_spans.append(event.span_id)

            token_pattern = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
            scrubbed_msg = token_pattern.sub(r"\1[REDACTED]", event.message)
            scrubbed_attrs = {
                k: token_pattern.sub(r"\1[REDACTED]", v) for k, v in event.attributes.items()
            }
            line = json.dumps(
                {
                    "trace_id": self.active_trace_id,
                    "span_id": event.span_id,
                    "name": event.name,
                    "message": scrubbed_msg,
                    "attributes": scrubbed_attrs,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            ndjson_payload = ndjson_payload + line + "\n"
            accepted += 1

        final_ndjson = ndjson_payload.rstrip("\n")
        if accepted > 0:
            self._exporter.export_ndjson(self.active_trace_id or trace_id, final_ndjson)
        self.active_trace_id = None
        return ExportedBatch(
            trace_id=trace_id,
            ndjson=final_ndjson,
            accepted_count=accepted,
            duplicate_count=duplicates,
        )
