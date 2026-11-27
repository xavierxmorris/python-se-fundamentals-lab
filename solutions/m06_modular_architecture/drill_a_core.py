"""M06 Drill A Reference Solution: Deep Modules & Functional Core / Imperative Shell."""

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
    if not (0.0 <= jitter_ratio <= 1.0):
        raise ValueError(f"jitter_ratio must be within [0.0, 1.0], got {jitter_ratio!r}")

    if any(a.succeeded for a in attempts) or len(attempts) >= policy.max_attempts:
        return RejectExhausted(attempts_made=len(attempts))

    if circuit_opened_at_sec is not None:
        reopen_at = circuit_opened_at_sec + policy.cooldown_sec
        if now_sec < reopen_at:
            recent = [
                ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec
            ]
            return TripCircuit(reopen_at_sec=reopen_at, recent_failures=len(recent))
    else:
        recent = [
            ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec
        ]
        if len(recent) >= policy.failure_threshold:
            return TripCircuit(
                reopen_at_sec=now_sec + policy.cooldown_sec,
                recent_failures=len(recent),
            )

    if len(attempts) == 0:
        return RunNow(attempt_no=1)

    failed_count = len(attempts)
    raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (failed_count - 1)))
    effective = raw * (0.5 + 0.5 * jitter_ratio)
    due_at = attempts[-1].timestamp_sec + effective
    if now_sec >= due_at:
        return RunNow(attempt_no=failed_count + 1)
    return DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)


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
        now = self._clock.now_sec()
        ratio = self._jitter.sample_ratio()
        attempts = self._ledger.get_attempts(task_id)
        failures = self._ledger.get_circuit_failures()
        opened_at = self._ledger.get_circuit_opened_at()

        decision = decide_next_action(
            attempts=attempts,
            circuit_failures_sec=failures,
            circuit_opened_at_sec=opened_at,
            policy=self._policy,
            now_sec=now,
            jitter_ratio=ratio,
        )
        if isinstance(decision, TripCircuit) and opened_at is None:
            self._ledger.set_circuit_opened_at(now)
        return decision

    def dispatch(self, task_id: str, execute: Callable[[int], bool]) -> PlanDecision:
        """Plan next action and execute `execute(attempt_no)` iff `RunNow`, updating ledger state."""
        decision = self.plan(task_id)
        if not isinstance(decision, RunNow):
            return decision

        succeeded = execute(decision.attempt_no)
        finished_at = self._clock.now_sec()
        self._ledger.record_attempt(
            task_id,
            AttemptRecord(
                attempt_no=decision.attempt_no,
                timestamp_sec=finished_at,
                succeeded=succeeded,
            ),
        )
        if succeeded:
            if self._ledger.get_circuit_opened_at() is not None:
                self._ledger.set_circuit_opened_at(None)
        else:
            self._ledger.record_circuit_failure(finished_at)
            if self._ledger.get_circuit_opened_at() is not None:
                self._ledger.set_circuit_opened_at(finished_at)
        return decision
