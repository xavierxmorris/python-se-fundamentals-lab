"""M12 Drill B (Spec-First AI Extension & Audit): Tenant Batch Audit Report.

WARNING: This "AI-generated" audit query contains 2 subtle defects:
  1. Omits `WHERE tenant = ?`, leaking other tenants' tasks and replays into the report.
  2. Double-counts `replayed_requests` inside `total_tasks`, violating the conservation law
     `succeeded + failed + dead_letter + leased + queued == total_tasks`.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol, TypedDict, runtime_checkable

from drill_a_core import TaskLedgerEngine


class BatchAuditReport(TypedDict):
    """Per-tenant task lifecycle and idempotency audit report."""

    tenant: str
    total_tasks: int
    queued: int
    leased: int
    succeeded: int
    failed: int
    dead_letter: int
    replayed_requests: int


@runtime_checkable
class LedgerConnectionPort(Protocol):
    """Structural port satisfied by `TaskLedgerEngine`."""

    connection: sqlite3.Connection


def generate_tenant_audit_report(engine: TaskLedgerEngine, tenant: str) -> BatchAuditReport:
    """Aggregate strict per-tenant lifecycle state counts and idempotent replay totals."""
    if not tenant or not tenant.strip():
        raise ValueError("tenant must be non-empty")

    counts: dict[str, int] = {
        "queued": 0,
        "leased": 0,
        "succeeded": 0,
        "failed": 0,
        "dead_letter": 0,
    }
    replayed_total = 0

    # BUGS: missing `WHERE tenant = ?` AND adds `replayed_total` into `total_tasks`!
    rows = engine.connection.execute(
        "SELECT status, COUNT(*), COALESCE(SUM(replayed_count), 0) FROM tasks GROUP BY status"
    ).fetchall()

    for status_raw, count_raw, replay_raw in rows:
        status_key = str(status_raw)
        if status_key in counts:
            counts[status_key] += int(count_raw)
        replayed_total += int(replay_raw)

    total_tasks = sum(counts.values()) + replayed_total
    return BatchAuditReport(
        tenant=tenant,
        total_tasks=total_tasks,
        queued=counts["queued"],
        leased=counts["leased"],
        succeeded=counts["succeeded"],
        failed=counts["failed"],
        dead_letter=counts["dead_letter"],
        replayed_requests=replayed_total,
    )
