"""Gate 5 end-to-end concurrent integration check for M12 (`m12_debugging_capstone`)."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from pathlib import Path


def run_check(module_dir: Path) -> tuple[bool, str]:
    """Verify multi-tenant idempotency, fencing, cancellation cleanup, spans, and audit totals."""
    _ = module_dir
    try:
        from drill_a_core import (
            StaleFenceError,
            TaskLedgerEngine,
            TaskSnapshot,
            current_span_context,
        )
        from drill_b_ai_adapter import generate_tenant_audit_report
    except Exception as exc:
        return False, f"Failed to import M12 modules: {exc}"

    with tempfile.TemporaryDirectory(prefix="m12_gate5_") as tmp_dir:
        db_path = Path(tmp_dir) / "capstone.sqlite3"
        side_effects: list[str] = []

        def prep_hook(payload: Mapping[str, object]) -> str:
            tok = f"prep-{payload.get('id', 'x')}-{len(side_effects) + 1}"
            side_effects.append(tok)
            return tok

        with TaskLedgerEngine(db_path, max_attempts_default=2) as engine:
            # 1. Multi-tenant submissions + idempotent replays + metadata isolation
            a1 = engine.submit_idempotent(
                request_id="acme-1",
                tenant="acme",
                payload={"id": 1, "mode": "ok"},
                prepare_tool=prep_hook,
            )
            engine.submit_idempotent(
                request_id="acme-1",
                tenant="acme",
                payload={"mode": "ok", "id": 1},
                prepare_tool=prep_hook,
            )
            engine.submit_idempotent(
                request_id="acme-1",
                tenant="acme",
                payload={"id": 1, "mode": "ok"},
                prepare_tool=prep_hook,
            )
            if len(side_effects) != 1:
                return (
                    False,
                    f"Idempotent replay executed prepare_tool {len(side_effects)} times (expected 1)",
                )

            g1 = engine.submit_idempotent(
                request_id="globex-1",
                tenant="globex",
                payload={"id": 10, "mode": "ok"},
            )
            engine.submit_idempotent(
                request_id="globex-1",
                tenant="globex",
                payload={"id": 10, "mode": "ok"},
            )

            if a1.metadata.get("origin_tenant") != "acme":
                return False, f"Corrupted acme metadata: {a1.metadata!r}"
            if g1.metadata.get("origin_tenant") != "globex":
                return (
                    False,
                    f"Cross-tenant metadata bleed on globex: {g1.metadata!r}",
                )

            engine.submit_idempotent(
                request_id="acme-2",
                tenant="acme",
                payload={"id": 2, "mode": "fail"},
            )

            # 2. Stale worker fence check
            fenced = engine.submit_idempotent(
                request_id="acme-fence",
                tenant="acme",
                payload={"id": 3, "mode": "manual"},
            )
            l1 = engine.acquire_lease(fenced.task_id, worker_id="w1")
            l2 = engine.acquire_lease(fenced.task_id, worker_id="w2")
            engine.complete_lease(fenced.task_id, fence_token=l2.fence_token, result="winner-w2")
            try:
                engine.complete_lease(fenced.task_id, fence_token=l1.fence_token, result="stale-w1")
                return False, "Stale worker fence overwrote completed lease without StaleFenceError"
            except StaleFenceError:
                pass

            if engine.get_task(fenced.task_id).result != "winner-w2":
                return False, "Stale worker mutated persisted result"

            # 3. Concurrent batch execution + cancellation cleanup + 0 leaked tasks
            async def orchestrate() -> tuple[bool, str]:
                baseline_tasks = set(asyncio.all_tasks())

                async def worker_fn(snap: TaskSnapshot) -> str:
                    await asyncio.sleep(0.005)
                    if snap.payload.get("mode") == "fail":
                        raise RuntimeError("expected failure")
                    return f"ok:{snap.request_id}"

                await engine.run_worker_batch(worker_fn, max_concurrency=3, task_timeout=0.5)

                # Now exercise mid-flight cancellation cleanup on a slow globex task
                engine.submit_idempotent(
                    request_id="globex-cancel",
                    tenant="globex",
                    payload={"id": 99, "mode": "slow"},
                )
                entered = asyncio.Event()

                async def slow_fn(snap: TaskSnapshot) -> str:
                    _ = snap
                    entered.set()
                    await asyncio.sleep(10.0)
                    return "never"

                runner_task = asyncio.create_task(
                    engine.run_worker_batch(
                        slow_fn,
                        tenant="globex",
                        max_concurrency=2,
                        task_timeout=10.0,
                    )
                )
                await entered.wait()
                runner_task.cancel()
                try:
                    await runner_task
                    return False, "run_worker_batch swallowed CancelledError instead of propagating"
                except asyncio.CancelledError:
                    pass

                remaining = set(asyncio.all_tasks()) - baseline_tasks
                if remaining:
                    return False, f"Leaked {len(remaining)} orphan asyncio task(s)"
                return True, "ok"

            ok_async, msg_async = asyncio.run(orchestrate())
            if not ok_async:
                return False, msg_async

            if current_span_context() is not None:
                return False, f"ContextVar leaked active span: {current_span_context()!r}"

            # 4. Verify tenant audit reports & conservation invariant
            acme_audit = generate_tenant_audit_report(engine, "acme")
            globex_audit = generate_tenant_audit_report(engine, "globex")

            for rpt in (acme_audit, globex_audit):
                total_check = (
                    rpt["queued"]
                    + rpt["leased"]
                    + rpt["succeeded"]
                    + rpt["failed"]
                    + rpt["dead_letter"]
                )
                if total_check != rpt["total_tasks"]:
                    return (
                        False,
                        f"Audit conservation invariant violated for {rpt['tenant']}: {rpt!r}",
                    )

            if (
                acme_audit["total_tasks"] != 3
                or acme_audit["succeeded"] != 2
                or acme_audit["failed"] != 1
                or acme_audit["replayed_requests"] != 2
            ):
                return False, f"Unexpected acme audit totals: {acme_audit!r}"

            if (
                globex_audit["total_tasks"] != 2
                or globex_audit["succeeded"] != 1
                or globex_audit["leased"] != 1
                or globex_audit["replayed_requests"] != 1
            ):
                return False, f"Unexpected globex audit totals: {globex_audit!r}"

    return (
        True,
        "2-tenant SQLite WAL + async batch verified: 0 duplicate side effects, stale fence blocked, "
        "0 leaked tasks on cancel, ContextVar clean, audit totals exact",
    )
