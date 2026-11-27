# M06 · Modular Architecture: Deep Modules & Functional Core / Imperative Shell

## Entry Contract & Invariants

Left unsupervised, coding agents routinely tangle clocks (`time.time()`), sleeps (`time.sleep()`), randomness (`random.random()`), global mutable state, and domain retry/circuit-breaker rules into one monolithic method—forcing slow, flaky `monkeypatch` tests.

In this module you separate:
1. **Functional Core (`decide_next_action`):** A 100% pure, deterministic function over immutable slotted dataclasses (`RetryPolicy`, `AttemptRecord`, `PlanDecision`) with **zero** imports of `time`, `random`, `os`, `sqlite3`, `subprocess`, or `socket`.
2. **Imperative Shell (`DispatcherShell` & `SpaghettiDispatcher`):** Thin coordinators over narrow structural `Protocol` ports (`ClockPort`, `JitterPort`, `LedgerPort`, `TaskRunnerPort`) with instance-isolated state and zero `time.sleep`.

---

## Drill A — Cold-Turkey Core (`drill_a_core.py` + `test_learner_a.py`, AI OFF)

### 1. Frozen Slotted Domain Value Types
- `@dataclass(slots=True, frozen=True) class RetryPolicy:`
  - `max_attempts: int = 3`
  - `base_delay_sec: float = 1.0`
  - `max_delay_sec: float = 30.0`
  - `failure_threshold: int = 3`
  - `window_sec: float = 60.0`
  - `cooldown_sec: float = 15.0`
- `@dataclass(slots=True, frozen=True) class AttemptRecord:`
  - `attempt_no: int`
  - `timestamp_sec: float`
  - `succeeded: bool`
- Decision sum type (`type PlanDecision = RunNow | DelayUntil | TripCircuit | RejectExhausted`), all `@dataclass(slots=True, frozen=True)`:
  - `RunNow(attempt_no: int)`
  - `DelayUntil(attempt_no: int, run_at_sec: float)`
  - `TripCircuit(reopen_at_sec: float, recent_failures: int)`
  - `RejectExhausted(attempts_made: int)`

### 2. Pure Functional Core: `decide_next_action`

```python
def decide_next_action(
    *,
    attempts: Sequence[AttemptRecord],
    circuit_failures_sec: Sequence[float],
    circuit_opened_at_sec: float | None,
    policy: RetryPolicy,
    now_sec: float,
    jitter_ratio: float,
) -> PlanDecision:
```

**Exact Evaluation Precedence & Backoff Formula:**
1. **Validate Jitter:** Require `0.0 <= jitter_ratio <= 1.0` (`ValueError` otherwise).
2. **Terminal / Exhausted Check:** If any `a.succeeded` in `attempts` or `len(attempts) >= policy.max_attempts`, return `RejectExhausted(attempts_made=len(attempts))`.
3. **Open / Half-Open Circuit Check (`circuit_opened_at_sec is not None`):**
   - If `now_sec < circuit_opened_at_sec + policy.cooldown_sec`: count `recent = [ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec]` and return `TripCircuit(reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec, recent_failures=len(recent))`.
   - Else (`now_sec >= circuit_opened_at_sec + policy.cooldown_sec`): the circuit is **half-open** — do **not** re-trip on pre-cooldown failures; proceed directly to step 5!
4. **Closed Circuit Threshold Check (`circuit_opened_at_sec is None`):**
   - Count `recent = [ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec]`.
   - If `len(recent) >= policy.failure_threshold`, return `TripCircuit(reopen_at_sec=now_sec + policy.cooldown_sec, recent_failures=len(recent))`.
5. **Initial Attempt:** If `len(attempts) == 0`, return `RunNow(attempt_no=1)`.
6. **Exponential Backoff with Deterministic Jitter:**
   - Let `failed_count = len(attempts)`.
   - Compute:
     - `raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (failed_count - 1)))`
     - `effective = raw * (0.5 + 0.5 * jitter_ratio)`
     - `due_at = attempts[-1].timestamp_sec + effective`
   - If `now_sec >= due_at`, return `RunNow(attempt_no=failed_count + 1)`; otherwise return `DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)`.

### 3. Narrow Ports & `DispatcherShell`
- `ClockPort`: `def now_sec(self) -> float: ...`
- `JitterPort`: `def sample_ratio(self) -> float: ...`
- `LedgerPort`:
  - `def get_attempts(self, task_id: str) -> Sequence[AttemptRecord]: ...`
  - `def record_attempt(self, task_id: str, record: AttemptRecord) -> None: ...`
  - `def get_circuit_failures(self) -> Sequence[float]: ...`
  - `def record_circuit_failure(self, timestamp_sec: float) -> None: ...`
  - `def get_circuit_opened_at(self) -> float | None: ...`
  - `def set_circuit_opened_at(self, opened_at_sec: float | None) -> None: ...`
- `DispatcherShell(*, clock: ClockPort, jitter: JitterPort, ledger: LedgerPort, policy: RetryPolicy | None = None)`:
  - `plan(self, task_id: str) -> PlanDecision`: evaluates `decide_next_action`; if `TripCircuit` is returned while `ledger.get_circuit_opened_at() is None`, records `ledger.set_circuit_opened_at(now)`.
  - `dispatch(self, task_id: str, execute: Callable[[int], bool]) -> PlanDecision`: calls `plan(task_id)`. Only when `RunNow` is returned does it call `execute(decision.attempt_no)`, record the `AttemptRecord` at `clock.now_sec()`, clear `circuit_opened_at` (`None`) on a succeeding probe, or record a circuit failure (and refresh `circuit_opened_at` if already half-open) on failure.

Write fast, deterministic tests in `test_learner_a.py` using **zero `unittest.mock` / `monkeypatch`** to kill 100% of mutants in `seeded_bugs_a.py`.

---

## Drill B — Spec-First AI Pair (`drill_b_ai_adapter.py`)

`drill_b_ai_adapter.py` contains a `SpaghettiDispatcher` that reads `time.time()`, blocks with `time.sleep()`, and mutates a module-level `_GLOBAL_FAILURES: list[float] = []` shared across instances.

Refactor `SpaghettiDispatcher` around injected `ClockPort` and `TaskRunnerPort` protocols:
- Remove all `time.time()`, `time.sleep()`, and module-level mutable state.
- Isolate per-task `AttemptRecord` history and circuit failure state inside each `SpaghettiDispatcher` instance.
- Delegate retry/circuit decisions to `decide_next_action` and return `DispatchOutcome(task_id, decision, executed, succeeded)`.

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m06
uv run --no-sync python scripts/eval_module.py m06
```
