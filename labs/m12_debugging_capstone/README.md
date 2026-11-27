# M12 · Capstone: Scientific Debugging, Trace-Driven RCA & End-to-End Service Audit

## Entry Contract & Overview

`m12_debugging_capstone` brings together every layer of `taskledger` — immutable snapshots (`M01`/`M03`), strict typing (`M04`), bounded `asyncio.TaskGroup` concurrency & cancellation (`M08`), SQLite `BEGIN IMMEDIATE` idempotency & monotonic lease fencing (`M09`), and `ContextVar` span telemetry (`M10`).

Unlike earlier modules where `drill_a_core.py` starts blank, **`labs/m12_debugging_capstone/drill_a_core.py` ships a working-looking ~200-line `TaskLedgerEngine` seeded with 4 interacting production defects**. Apply the scientific debugging loop: write minimal deterministic reproduction tests in `test_learner_a.py` first, then fix each root cause cleanly.

### Exported Surface

#### Drill A (`drill_a_core.py`)
- `class LedgerError(Exception)`
- `class IdempotencyConflictError(LedgerError)`
- `class StaleFenceError(LedgerError)`
- `type TaskStatus = Literal["queued", "leased", "succeeded", "failed", "dead_letter"]`
- `@dataclass(slots=True, frozen=True) class SpanEvent`
- `@dataclass(slots=True, frozen=True) class TaskSnapshot`
- `current_span_context() -> tuple[str, str] | None`
- `class TaskLedgerEngine`

#### Drill B (`drill_b_ai_adapter.py`)
- `class BatchAuditReport(TypedDict)`
- `class LedgerConnectionPort(Protocol)`
- `generate_tenant_audit_report(engine: TaskLedgerEngine, tenant: str) -> BatchAuditReport`

---

## Drills

1. **Drill A — Incident Triage & Root-Cause Fix (AI OFF):**
   Reproduce all 4 production defects in `test_learner_a.py` (duplicate `prepare_tool` execution on idempotent replay, shared mutable `metadata` bleeding across tenants, worker catching `BaseException` and swallowing `asyncio.CancelledError`, and `complete_lease` omitting `fence_token` validation), then fix `drill_a_core.py`.
2. **Drill B — Spec-First AI Extension & Audit:**
   Audit and remediate `generate_tenant_audit_report` in `drill_b_ai_adapter.py` so every tenant report enforces strict SQL tenant isolation, exact `replayed_requests` tracking, and the conservation law `succeeded + failed + dead_letter + leased + queued == total_tasks`.

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m12
uv run --no-sync python scripts/eval_module.py m12
```
