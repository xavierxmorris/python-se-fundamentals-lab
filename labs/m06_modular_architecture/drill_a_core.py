"""M06 Drill A (Cold-Turkey Core): Deep Modules & Functional Core / Imperative Shell.

Rules:
- Zero imports of `time`, `random`, `os`, `sqlite3`, `subprocess`, or `socket`.
- Pure deterministic planning in `decide_next_action`; thin side-effect orchestration in `DispatcherShell`.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True, frozen=True)
class RetryPolicy:
    """Immutable retry and circuit-breaker configuration."""

    max_attempts: int = 3
    base_delay_sec: float = 1.0
    max_delay_sec: float = 30.0
    failure_threshold: int = 3
    window_sec: float = 60.0
    cooldown_sec: float = 15.0


@dataclass(slots=True, frozen=True)
class AttemptRecord:
    """Immutable record of a single task execution attempt."""

    attempt_no: int
    timestamp_sec: float
    succeeded: bool


@dataclass(slots=True, frozen=True)
class RunNow:
    """Decision instructing the shell to execute `attempt_no` immediately."""

    attempt_no: int


@dataclass(slots=True, frozen=True)
class DelayUntil:
    """Decision instructing the shell to defer `attempt_no` until `run_at_sec`."""

    attempt_no: int
    run_at_sec: float


@dataclass(slots=True, frozen=True)
class TripCircuit:
    """Decision indicating the circuit breaker is open until `reopen_at_sec`."""

    reopen_at_sec: float
    recent_failures: int


@dataclass(slots=True, frozen=True)
class RejectExhausted:
    """Decision indicating the task already succeeded or exhausted `max_attempts`."""

    attempts_made: int


type PlanDecision = RunNow | DelayUntil | TripCircuit | RejectExhausted


def decide_next_action(
    *,
    attempts: Sequence[AttemptRecord],
    circuit_failures_sec: Sequence[float],
    circuit_opened_at_sec: float | None,
    policy: RetryPolicy,
    now_sec: float,
    jitter_ratio: float,
) -> PlanDecision:
    """Pure functional retry & circuit-breaker planner.

    Exact precedence and backoff contract:
    1. Validate `0.0 <= jitter_ratio <= 1.0` (`ValueError` otherwise).
    2. If any `a.succeeded` in `attempts` or `len(attempts) >= policy.max_attempts`,
       return `RejectExhausted(attempts_made=len(attempts))`.
    3. If `circuit_opened_at_sec is not None`:
       - If `now_sec < circuit_opened_at_sec + policy.cooldown_sec`, count
         `recent = [ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec]`
         and return `TripCircuit(reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec, recent_failures=len(recent))`.
       - Else circuit is half-open: do NOT re-trip on pre-cooldown failures; proceed to step 5.
    4. Else (`circuit_opened_at_sec is None`):
       - Count `recent = [ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec]`.
       - If `len(recent) >= policy.failure_threshold`, return
         `TripCircuit(reopen_at_sec=now_sec + policy.cooldown_sec, recent_failures=len(recent))`.
    5. If `len(attempts) == 0`, return `RunNow(attempt_no=1)`.
    6. Otherwise let `failed_count = len(attempts)`:
       - `raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (failed_count - 1)))`
       - `effective = raw * (0.5 + 0.5 * jitter_ratio)`
       - `due_at = attempts[-1].timestamp_sec + effective`
       - If `now_sec >= due_at`, return `RunNow(attempt_no=failed_count + 1)`,
         else `DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)`.
    """
    raise NotImplementedError("Implement decide_next_action in drill_a_core.py")


class ClockPort(Protocol):
    """Narrow port supplying current monotonic/wall timestamp in seconds."""

    def now_sec(self) -> float: ...


class JitterPort(Protocol):
    """Narrow port supplying deterministic or random jitter ratio in [0.0, 1.0]."""

    def sample_ratio(self) -> float: ...


class LedgerPort(Protocol):
    """Narrow port persisting per-task attempt history and circuit state."""

    def get_attempts(self, task_id: str) -> Sequence[AttemptRecord]: ...

    def record_attempt(self, task_id: str, record: AttemptRecord) -> None: ...

    def get_circuit_failures(self) -> Sequence[float]: ...

    def record_circuit_failure(self, timestamp_sec: float) -> None: ...

    def get_circuit_opened_at(self) -> float | None: ...

    def set_circuit_opened_at(self, opened_at_sec: float | None) -> None: ...


class DispatcherShell:
    """Imperative shell coordinating `decide_next_action` across injected ports."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        jitter: JitterPort,
        ledger: LedgerPort,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._clock = clock
        self._jitter = jitter
        self._ledger = ledger
        self._policy = policy if policy is not None else RetryPolicy()

    def plan(self, task_id: str) -> PlanDecision:
        """Read current state from ports, run `decide_next_action`, and persist newly tripped circuits."""
        raise NotImplementedError("Implement DispatcherShell.plan in drill_a_core.py")

    def dispatch(self, task_id: str, execute: Callable[[int], bool]) -> PlanDecision:
        """Plan next action and execute `execute(attempt_no)` iff `RunNow`, updating ledger state."""
        raise NotImplementedError("Implement DispatcherShell.dispatch in drill_a_core.py")
