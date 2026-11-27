"""Frozen acceptance suite for M12 Drill B (`drill_b_ai_adapter.py`)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from drill_a_core import TaskLedgerEngine, TaskSnapshot
from drill_b_ai_adapter import (
    BatchAuditReport,
    LedgerConnectionPort,
    generate_tenant_audit_report,
)


def _assert_conservation(report: BatchAuditReport) -> None:
    bucket_sum = (
        report["queued"]
        + report["leased"]
        + report["succeeded"]
        + report["failed"]
        + report["dead_letter"]
    )
    assert bucket_sum == report["total_tasks"]


def test_engine_satisfies_ledger_connection_port(tmp_path: Path) -> None:
    with TaskLedgerEngine(tmp_path / "port.db") as engine:
        assert isinstance(engine, LedgerConnectionPort)


def test_audit_report_tenant_isolation_and_conservation_invariant(tmp_path: Path) -> None:
    db_file = tmp_path / "audit.db"
    with TaskLedgerEngine(db_file, max_attempts_default=1) as engine:
        # Tenant 'acme':
        # 1) t_ok -> succeeded (replayed twice)
        t_ok = engine.submit_idempotent(
            request_id="acme-ok",
            tenant="acme",
            payload={"kind": "ok"},
        )
        engine.submit_idempotent(request_id="acme-ok", tenant="acme", payload={"kind": "ok"})
        engine.submit_idempotent(request_id="acme-ok", tenant="acme", payload={"kind": "ok"})

        # 2) t_dl -> dead_letter (max_attempts=1)
        engine.submit_idempotent(
            request_id="acme-dl",
            tenant="acme",
            payload={"kind": "fail"},
        )

        async def run_acme(snap: TaskSnapshot) -> str:
            if snap.payload.get("kind") == "fail":
                raise RuntimeError("boom")
            return "ok"

        asyncio.run(engine.run_worker_batch(run_acme, tenant="acme"))

        # 3) t_leased -> leased
        t_leased = engine.submit_idempotent(
            request_id="acme-leased",
            tenant="acme",
            payload={"kind": "hold"},
        )
        engine.acquire_lease(t_leased.task_id, worker_id="w-hold")

        # 4) t_queued -> queued
        engine.submit_idempotent(
            request_id="acme-queued",
            tenant="acme",
            payload={"kind": "wait"},
        )

        # 5) t_failed -> failed (max_attempts=2, failed once)
        t_retry = engine.submit_idempotent(
            request_id="acme-retry",
            tenant="acme",
            payload={"kind": "retry"},
            max_attempts=2,
        )
        leased_retry = engine.acquire_lease(t_retry.task_id, worker_id="w-retry")
        engine.fail_lease(
            t_retry.task_id,
            fence_token=leased_retry.fence_token,
            error="transient",
        )

        # Tenant 'globex' noise (must NOT leak into 'acme' report):
        engine.submit_idempotent(request_id="globex-1", tenant="globex", payload={"x": 1})
        engine.submit_idempotent(request_id="globex-1", tenant="globex", payload={"x": 1})
        engine.submit_idempotent(request_id="globex-2", tenant="globex", payload={"x": 2})

        _ = t_ok
        acme_report = generate_tenant_audit_report(engine, "acme")
        _assert_conservation(acme_report)
        assert acme_report == {
            "tenant": "acme",
            "total_tasks": 5,
            "queued": 1,
            "leased": 1,
            "succeeded": 1,
            "failed": 1,
            "dead_letter": 1,
            "replayed_requests": 2,
        }

        globex_report = generate_tenant_audit_report(engine, "globex")
        _assert_conservation(globex_report)
        assert globex_report == {
            "tenant": "globex",
            "total_tasks": 2,
            "queued": 2,
            "leased": 0,
            "succeeded": 0,
            "failed": 0,
            "dead_letter": 0,
            "replayed_requests": 1,
        }

        empty_report = generate_tenant_audit_report(engine, "unknown-tenant")
        _assert_conservation(empty_report)
        assert empty_report["total_tasks"] == 0
        assert empty_report["replayed_requests"] == 0

        with pytest.raises(ValueError):
            generate_tenant_audit_report(engine, "   ")
