"""Reference learner test suite for M10 Drill A (`drill_a_core.py`)."""

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


def test_concurrent_tasks_do_not_scramble_span_hierarchy() -> None:
    """Kills `bug_instance_span_state` by interleaving async tasks on one shared Tracer."""
    tracer = Tracer()
    gate = asyncio.Event()
    ready_count = 0

    async def branch(idx: int) -> tuple[str, str, str]:
        nonlocal ready_count
        with tracer.start_span(f"req-{idx}", branch=idx):
            outer_ctx = current_span_context()
            assert outer_ctx is not None
            ready_count += 1
            if ready_count == 6:
                gate.set()
            await gate.wait()
            await asyncio.sleep(0.001)
            with tracer.start_span(f"db-{idx}"):
                inner_ctx = current_span_context()
                assert inner_ctx is not None
                await asyncio.sleep(0.001)
            assert current_span_context() == outer_ctx
            return outer_ctx[0], outer_ctx[1], inner_ctx[1]

    async def runner() -> list[tuple[str, str, str]]:
        tasks: list[asyncio.Task[tuple[str, str, str]]] = []
        async with asyncio.TaskGroup() as tg:
            for i in range(6):
                tasks.append(tg.create_task(branch(i)))
        return [t.result() for t in tasks]

    outcomes = asyncio.run(runner())
    assert current_span_context() is None
    assert len({trace_id for trace_id, _, _ in outcomes}) == 6

    by_span = {s.span_id: s for s in tracer.finished_spans()}
    for trace_id, root_id, child_id in outcomes:
        assert by_span[root_id].parent_span_id is None
        assert by_span[child_id].trace_id == trace_id
        assert by_span[child_id].parent_span_id == root_id


def test_exception_resets_contextvar_token_and_records_error_metadata() -> None:
    """Kills `bug_missing_token_reset_on_error` and `bug_error_recorded_as_ok`."""
    tracer = Tracer()
    assert current_span_context() is None

    with pytest.raises(RuntimeError, match="boom"), tracer.start_span("explode", step="parse"):
        assert current_span_context() is not None
        raise RuntimeError("boom")

    # Token must be reset to None even when exception escapes root span!
    assert current_span_context() is None

    # Subsequent root span must NOT inherit the dead failed span as parent!
    with tracer.start_span("fresh-root"):
        pass

    spans = tracer.finished_spans()
    assert len(spans) == 2
    failed_span, next_root = spans[0], spans[1]
    assert failed_span.status == "error"
    assert failed_span.attributes.get("error.type") == "RuntimeError"
    assert failed_span.attributes.get("step") == "parse"
    assert next_root.parent_span_id is None
    assert next_root.trace_id != failed_span.trace_id


def test_redact_sensitive_fields_preserves_inputs_and_matches_case_insensitively() -> None:
    """Kills `bug_redact_mutates_and_case_sensitive`."""
    raw_dict = {"X-Api-Key": "secret-val", "Authorization": "Bearer xyz", "user": "alice"}
    records = [raw_dict]

    output = redact_sensitive_fields(records, {"x-api-key", "authorization"})

    assert raw_dict["X-Api-Key"] == "secret-val"
    assert raw_dict["Authorization"] == "Bearer xyz"
    assert output == [{"X-Api-Key": "[REDACTED]", "Authorization": "[REDACTED]", "user": "alice"}]
    assert output[0] is not raw_dict


def test_measure_allocations_cleans_up_tracemalloc_even_on_error() -> None:
    if tracemalloc.is_tracing():
        tracemalloc.stop()

    report = measure_allocations(lambda: bytearray(64 * 1024))
    assert not tracemalloc.is_tracing()
    assert report.peak_kib >= 60.0
    assert report.top_line > 0

    def bad_fn() -> object:
        raise ValueError("alloc failure")

    with pytest.raises(ValueError, match="alloc failure"):
        measure_allocations(bad_fn)
    assert not tracemalloc.is_tracing()
