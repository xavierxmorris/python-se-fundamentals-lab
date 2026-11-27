"""Frozen acceptance suite for M10 Drill B (`drill_b_ai_adapter.py`)."""

from __future__ import annotations

import asyncio
import json

import pytest

from drill_b_ai_adapter import (
    SpanExporter,
    TelemetryBatchProcessor,
    TelemetryEvent,
)


class RecordingExporter:
    """In-memory `SpanExporter` test fake."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def export_ndjson(self, trace_id: str, payload: str) -> None:
        self.calls.append((trace_id, payload))


def test_exporter_satisfies_runtime_protocol() -> None:
    exporter = RecordingExporter()
    assert isinstance(exporter, SpanExporter)


def test_bounded_fifo_dedup_window_evicts_oldest() -> None:
    exporter = RecordingExporter()
    processor = TelemetryBatchProcessor(exporter, max_dedup_window=4)

    events = [
        TelemetryEvent(span_id=f"s-{i}", name="work", message="ok", attributes={})
        for i in range(10)
    ]
    batch1 = asyncio.run(processor.process_batch("trace-window", events))
    assert batch1.accepted_count == 10
    assert batch1.duplicate_count == 0
    assert processor.dedup_cache_size() == 4

    # s-6..s-9 are still inside the 4-element FIFO window; s-0 was evicted.
    replay = [
        TelemetryEvent(span_id="s-9", name="work", message="ok", attributes={}),
        TelemetryEvent(span_id="s-0", name="work", message="ok", attributes={}),
    ]
    batch2 = asyncio.run(processor.process_batch("trace-window", replay))
    assert batch2.duplicate_count == 1
    assert batch2.accepted_count == 1
    assert processor.dedup_cache_size() == 4


def test_concurrent_batches_isolate_active_trace_id() -> None:
    exporter = RecordingExporter()
    processor = TelemetryBatchProcessor(exporter, max_dedup_window=256)
    observed_inside: dict[str, set[str | None]] = {}

    class InspectingExporter:
        def __init__(self) -> None:
            self.exports: dict[str, list[dict[str, object]]] = {}

        def export_ndjson(self, trace_id: str, payload: str) -> None:
            observed_inside.setdefault(trace_id, set()).add(processor.current_trace_id())
            rows = [json.loads(line) for line in payload.splitlines() if line]
            self.exports[trace_id] = rows

    spy = InspectingExporter()
    isolated_proc = TelemetryBatchProcessor(spy, max_dedup_window=256)

    async def run_concurrent() -> None:
        async with asyncio.TaskGroup() as tg:
            for t_idx in range(8):
                tid = f"trace-{t_idx:02d}"
                evs = [
                    TelemetryEvent(
                        span_id=f"{tid}-span-{j}",
                        name="step",
                        message="Authorization: Bearer secret_tok_99",
                        attributes={"auth": "bearer abc.def.ghi"},
                    )
                    for j in range(5)
                ]
                tg.create_task(isolated_proc.process_batch(tid, evs))

    asyncio.run(run_concurrent())
    assert isolated_proc.current_trace_id() is None
    assert len(spy.exports) == 8

    for t_idx in range(8):
        tid = f"trace-{t_idx:02d}"
        rows = spy.exports[tid]
        assert len(rows) == 5
        for row in rows:
            assert row["trace_id"] == tid
            assert "[REDACTED]" in str(row["message"])
            assert "secret_tok_99" not in str(row["message"])


def test_invalid_configuration_and_trace_id_rejected() -> None:
    exporter = RecordingExporter()
    with pytest.raises(ValueError):
        TelemetryBatchProcessor(exporter, max_dedup_window=0)

    proc = TelemetryBatchProcessor(exporter, max_dedup_window=8)
    with pytest.raises(ValueError):
        asyncio.run(proc.process_batch("   ", []))
