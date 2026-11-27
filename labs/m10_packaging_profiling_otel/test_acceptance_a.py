"""Frozen acceptance suite for M10 Drill A (`drill_a_core.py`)."""

from __future__ import annotations

import asyncio
import tracemalloc

import pytest

from drill_a_core import (
    Tracer,
    current_span_context,
    measure_allocations,
    redact_sensitive_fields,
)


def test_root_and_nested_span_hierarchy() -> None:
    tracer = Tracer()
    assert current_span_context() is None

    with tracer.start_span("http.request", method="POST", retries=0) as root_attrs:
        ctx_root = current_span_context()
        assert ctx_root is not None
        root_trace_id, root_span_id = ctx_root
        assert len(root_trace_id) == 32
        assert len(root_span_id) == 16
        root_attrs["status_code"] = 201

        with tracer.start_span("db.query", table="tasks") as child_attrs:
            ctx_child = current_span_context()
            assert ctx_child is not None
            child_trace_id, child_span_id = ctx_child
            assert child_trace_id == root_trace_id
            assert child_span_id != root_span_id
            child_attrs["rows"] = 1

        assert current_span_context() == ctx_root

    assert current_span_context() is None
    finished = tracer.finished_spans()
    assert len(finished) == 2
    child_span, root_span = finished[0], finished[1]

    assert child_span.name == "db.query"
    assert child_span.trace_id == root_trace_id
    assert child_span.parent_span_id == root_span_id
    assert child_span.status == "ok"
    assert child_span.attributes["rows"] == 1
    assert child_span.duration_ms >= 0.0

    assert root_span.name == "http.request"
    assert root_span.parent_span_id is None
    assert root_span.attributes["status_code"] == 201
    assert root_span.status == "ok"

    with pytest.raises(TypeError):
        root_span.attributes["mutated"] = "nope"  # type: ignore[index]


def test_span_exception_records_error_and_resets_context() -> None:
    tracer = Tracer()

    with tracer.start_span("outer"):
        outer_ctx = current_span_context()
        assert outer_ctx is not None
        with pytest.raises(KeyError, match="missing_id"), tracer.start_span("failing_child", op="lookup"):
            raise KeyError("missing_id")
        assert current_span_context() == outer_ctx

    assert current_span_context() is None
    spans = tracer.finished_spans()
    assert len(spans) == 2
    failed, outer = spans[0], spans[1]
    assert failed.status == "error"
    assert failed.attributes["error.type"] == "KeyError"
    assert failed.attributes["op"] == "lookup"
    assert outer.status == "ok"


def test_invalid_span_name_rejected() -> None:
    tracer = Tracer()
    with pytest.raises(ValueError), tracer.start_span("   "):
        pass


def test_async_taskgroup_context_isolation() -> None:
    tracer = Tracer()

    async def worker(idx: int) -> tuple[str, str, str]:
        async with tracer.start_async_span(f"worker-{idx}", worker_id=idx):
            root_ctx = current_span_context()
            assert root_ctx is not None
            await asyncio.sleep(0.002)
            with tracer.start_span(f"step-{idx}"):
                child_ctx = current_span_context()
                assert child_ctx is not None
                await asyncio.sleep(0.002)
            assert current_span_context() == root_ctx
            return root_ctx[0], root_ctx[1], child_ctx[1]

    async def main() -> list[tuple[str, str, str]]:
        tasks: list[asyncio.Task[tuple[str, str, str]]] = []
        async with asyncio.TaskGroup() as tg:
            for i in range(12):
                tasks.append(tg.create_task(worker(i)))
        return [t.result() for t in tasks]

    results = asyncio.run(main())
    assert current_span_context() is None
    assert len({r[0] for r in results}) == 12

    by_span_id = {s.span_id: s for s in tracer.finished_spans()}
    for trace_id, root_span_id, child_span_id in results:
        root_rec = by_span_id[root_span_id]
        child_rec = by_span_id[child_span_id]
        assert root_rec.trace_id == trace_id
        assert root_rec.parent_span_id is None
        assert child_rec.trace_id == trace_id
        assert child_rec.parent_span_id == root_span_id


def test_measure_allocations_captures_peak_and_preserves_tracing_state() -> None:
    if tracemalloc.is_tracing():
        tracemalloc.stop()

    def allocate_payload() -> list[bytes]:
        return [bytes(4096) for _ in range(32)]

    report = measure_allocations(allocate_payload)
    assert not tracemalloc.is_tracing()
    assert report.peak_kib >= 100.0
    assert report.top_file.endswith(".py")
    assert report.top_line > 0

    tracemalloc.start()
    try:
        report_while_active = measure_allocations(allocate_payload)
        assert tracemalloc.is_tracing()
        assert report_while_active.peak_kib >= 100.0
    finally:
        tracemalloc.stop()


def test_redact_sensitive_fields_case_insensitive_and_non_mutating() -> None:
    original = [
        {"tenant": "acme", "Authorization": "Bearer secret-123", "API_KEY": "k-999"},
        {"tenant": "globex", "password": "hunter2", "note": "keep-me"},
    ]
    snapshot = [dict(row) for row in original]

    redacted = redact_sensitive_fields(original, {"authorization", "api_key", "PASSWORD"})
    assert original == snapshot
    assert redacted == [
        {"tenant": "acme", "Authorization": "[REDACTED]", "API_KEY": "[REDACTED]"},
        {"tenant": "globex", "password": "[REDACTED]", "note": "keep-me"},
    ]
