# M09 · State, ACID Transactions (`sqlite3` WAL / `BEGIN IMMEDIATE`), Idempotency & Fencing

## Entry Contract

Coding agents routinely write check-then-insert SQL (`SELECT` followed by `INSERT` inside a deferred transaction), re-run side-effecting callbacks on duplicate retries, hash non-canonical JSON strings whose dict keys are ordered differently, or allow a stalled worker whose lease expired to overwrite a newer worker's result. This module drills **explicit SQLite `BEGIN IMMEDIATE` write serialization**, **canonical idempotency keys & conflict detection**, **monotonic lease fencing (`fence_token`)**, and **crash-safe transactional outbox relaying**.

### Exported Surface (`drill_a_core.py` — Cold-Turkey Core, AI OFF)

- Exceptions:
  - `IdempotencyConflictError(Exception)`
  - `StaleFenceError(Exception)`
  - `TaskNotFoundError(KeyError)`
- Frozen slotted dataclasses:
  - `StoredSubmission(request_id: str, task_id: str, payload_hash: str, snapshot_json: str, created_new: bool)`
  - `LeaseGrant(task_id: str, worker_id: str, fence_token: int)`
- `@contextmanager def open_ledger(db_path: Path) -> Generator[DurableTaskLedger]`
  - Opens `sqlite3.connect(db_path, timeout=10.0, isolation_level=None)`, configures `PRAGMA journal_mode=WAL;`, `PRAGMA foreign_keys=ON;`, `PRAGMA busy_timeout=10000;`, initializes schema inside `BEGIN IMMEDIATE ... COMMIT`, and closes the connection cleanly in `finally:`.
- `class DurableTaskLedger`:
  - `submit_idempotent(self, request_id: str, task_id: str, payload: Mapping[str, object], compute_initial_snapshot: Callable[[], Mapping[str, object]]) -> StoredSubmission`
  - `acquire_lease(self, task_id: str, worker_id: str) -> LeaseGrant`
  - `record_outcome(self, task_id: str, fence_token: int, outcome_json: str) -> None`
  - `get_task_outcome(self, task_id: str) -> tuple[str, int, str | None]`

### Exported Surface (`drill_b_ai_adapter.py` — Spec-First AI Pair)

- `OutboxRecord`, `BrokerPort` (`Protocol` with `publish(delivery_key: str, body: str) -> None`), `BatchOutboxRelay`, and `open_outbox_relay(db_path: Path, broker: BrokerPort)`.
- Fix random `uuid4` delivery keys and non-atomic batch commits so crash-and-retry delivers every message effectively once via deterministic `f"outbox:{msg_id}"` keys and explicit per-message claim/mark transactions.

## Workflow

1. **Drill A (AI OFF):** Implement `drill_a_core.py` from its docstring contract, then write tests in `test_learner_a.py` (covering idempotent replay side-effect suppression, payload conflict errors, canonical dict key permutation, and stale `fence_token` rejection) to kill 100% of mutants in `seeded_bugs_a.py`.
2. **Drill B (Spec-First AI Pair):** Audit `drill_b_ai_adapter.py` against `test_acceptance_b.py` and remediate duplicate broker deliveries and dangling partial transactions.

## Evaluation Commands

```powershell
.\go.ps1 -Module m09
uv run --no-sync python scripts/eval_module.py m09
```
