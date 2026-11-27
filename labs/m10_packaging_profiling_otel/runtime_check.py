"""Gate 5 runtime invariant check for M10 (`m10_packaging_profiling_otel`)."""

from __future__ import annotations

import asyncio
from pathlib import Path


def run_check(module_dir: Path) -> tuple[bool, str]:
    """Verify concurrent async span isolation and bounded dedup memory invariants."""
    _ = module_dir
    try:
        from drill_a_core import Tracer, current_span_context
        from drill_b_ai_adapter import TelemetryBatchProcessor, TelemetryEvent
    except Exception as exc:
        return False, f"Failed to import M10 modules: {exc}"

    tracer = Tracer()

    async def run_trace_tree(task_idx: int) -> tuple[str, str, str]:
        with tracer.start_span(f"root-{task_idx}", task=task_idx):
            root_ctx = current_span_context()
            if root_ctx is None:
                raise AssertionError("Expected active root span context")
            await asyncio.sleep(0.002)
            with tracer.start_span(f"child-{task_idx}", step=1):
                child_ctx = current_span_context()
                if child_ctx is None:
                    raise AssertionError("Expected active child span context")
                await asyncio.sleep(0.002)
            after_child = current_span_context()
            if after_child != root_ctx:
                raise AssertionError(
                    f"Task {task_idx} context corrupted after child: {after_child} != {root_ctx}"
                )
            return root_ctx[0], root_ctx[1], child_ctx[1]

    async def exercise_all() -> tuple[list[tuple[str, str, str]], int]:
        handles: list[asyncio.Task[tuple[str, str, str]]] = []
        async with asyncio.TaskGroup() as tg:
            for idx in range(20):
                handles.append(tg.create_task(run_trace_tree(idx)))

        class NullExporter:
            def export_ndjson(self, trace_id: str, payload: str) -> None:
                _ = (trace_id, payload)

        proc = TelemetryBatchProcessor(NullExporter(), max_dedup_window=512)
        events = [
            TelemetryEvent(
                span_id=f"ev-{i}",
                name="metric",
                message="Bearer tok_12345",
                attributes={"env": "prod"},
            )
            for i in range(5_000)
        ]
        await proc.process_batch("bulk-trace", events)
        return [h.result() for h in handles], proc.dedup_cache_size()

    try:
        results, cache_size = asyncio.run(exercise_all())
    except Exception as exc:
        return False, f"Runtime concurrency/batch check failed: {exc}"

    if current_span_context() is not None:
        return False, f"Leaked span ContextVar after completion: {current_span_context()!r}"

    spans = tracer.finished_spans()
    if len(spans) != 40:
        return False, f"Expected 40 finished spans across 20 tasks, got {len(spans)}"

    by_id = {s.span_id: s for s in spans}
    trace_ids = {r[0] for r in results}
    if len(trace_ids) != 20:
        return False, f"Expected 20 distinct trace_ids across 20 root spans, got {len(trace_ids)}"

    for trace_id, root_id, child_id in results:
        root_span = by_id.get(root_id)
        child_span = by_id.get(child_id)
        if root_span is None or child_span is None:
            return False, "Missing recorded root or child span"
        if root_span.parent_span_id is not None or root_span.trace_id != trace_id:
            return False, f"Corrupted root span hierarchy: {root_span!r}"
        if child_span.trace_id != trace_id or child_span.parent_span_id != root_id:
            return (
                False,
                f"Cross-task span contamination: child {child_span!r} expected parent {root_id}",
            )

    if cache_size > 512:
        return False, f"TelemetryBatchProcessor dedup window leaked: size {cache_size} > 512"

    return (
        True,
        f"20 concurrent async trace trees isolated (40 spans), ContextVar clean, dedup window bounded ({cache_size}/512)",
    )
