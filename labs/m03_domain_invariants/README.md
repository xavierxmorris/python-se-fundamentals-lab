# M03 · Domain Modeling, Invariants & Parse-Don't-Validate

**Estimated Time:** 60–90 minutes  
**AI Policy:** Drill A = **Cold-Turkey (AI OFF)** · Drill B = **Spec-First AI Pair**

---

## Entry Contract

Parse untrusted boundary inputs *once* into validated value objects and enforce `taskledger`'s lifecycle state machine so illegal states and transitions are unrepresentable. Never use `assert` for validation (must hold under `python -O`).

### Drill A Exports (`drill_a_core.py`)

1. Typed Errors:
   - `DomainValidationError(field: str, reason: str)` (subclass of `ValueError` with `.field` and `.reason` attributes).
   - `InvalidTransitionError(RuntimeError)`
   - `StaleLeaseError(RuntimeError)`

2. Boundary Value Objects (`@dataclass(slots=True, frozen=True)`):
   - `TaskId.parse(raw: str) -> TaskId` (`field="task_id"`) and `TenantId.parse(raw: str) -> TenantId` (`field="tenant_id"`):
     - Reject non-`str`, leading/trailing whitespace (do **not** silently `.strip()`), control chars, or values not matching `^[a-z0-9][a-z0-9_-]{0,63}$`.
   - `UtcDate.parse(raw: str) -> UtcDate` (`field="utc_date"`):
     - Ordered (`order=True`) wrapper around `datetime.date`.
     - Must be exact 10-char `YYYY-MM-DD` valid calendar date (reject timestamps like `2025-07-01T00:00:00`, whitespace padding, or impossible dates like `2025-02-30`).

3. Explicit Lifecycle States & Transitions:
   - States: `QueuedTask`, `LeasedTask`, `SucceededTask`, `RetryableFailedTask`, `DeadLetterTask`, and union `TaskRecord`.
   - `parse_new_task(raw: Mapping[str, object]) -> QueuedTask`: parses `"task_id"`, `"tenant_id"`, `"scheduled_for"`, and `"max_attempts"` (`int >= 1`, rejecting `bool`).
   - `lease_task(task: TaskRecord, *, worker_id: str, lease_token: int) -> LeasedTask`: valid **only** from `QueuedTask` (`attempt_no = attempts_used + 1`); validates non-blank `worker_id` and `lease_token >= 1` (`int`, not `bool`).
   - `complete_task(task: TaskRecord, *, lease_token: int, output_summary: str) -> SucceededTask`: valid **only** from `LeasedTask` with exact `lease_token` (`StaleLeaseError` on mismatch).
   - `fail_task(task: TaskRecord, *, lease_token: int, error_reason: str, fatal: bool = False) -> RetryableFailedTask | DeadLetterTask`: valid **only** from `LeasedTask` with exact `lease_token`; routes to `DeadLetterTask` when `fatal=True` or `attempt_no >= max_attempts`, else `RetryableFailedTask`.
   - `requeue_task(task: TaskRecord) -> QueuedTask`: valid **only** from `RetryableFailedTask`.

### Drill B Exports (`drill_b_ai_adapter.py`)

Refactor `PolicySchedule` (`from_json_dicts`, `resolve`) to enforce half-open `[effective_from, effective_until)` date intervals per tenant, reject overlapping rules with `PolicyConflictError`, reject malformed/missing fields via `DomainValidationError`, and return `NoActivePolicy` on date gaps.

---

## Evaluation Command

```powershell
.\go.ps1 -Module m03
# or:
uv run --no-sync python scripts/eval_module.py m03
```
