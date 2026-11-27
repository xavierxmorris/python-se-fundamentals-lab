"""M06 Drill B (Spec-First AI Pair): Refactoring SpaghettiDispatcher around injected ports.

Audit and remediate `SpaghettiDispatcher` below:
1. Delete module-level `_GLOBAL_FAILURES` so dispatcher instances never bleed failure state.
2. Delete `time.time()` and `time.sleep()` calls; read timestamps exclusively from `self._clock.now_sec()`
   and delegate retry/circuit decisions to `decide_next_action`.
3. Never block when `DelayUntil` / `TripCircuit` / `RejectExhausted` is returned—return a
   `DispatchOutcome(..., executed=False, succeeded=False)` immediately.
"""

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from drill_a_core import (
    AttemptRecord,
    ClockPort,
    DelayUntil,
    PlanDecision,
    RejectExhausted,
    RetryPolicy,
    RunNow,
    TripCircuit,
)

# FLAW 1: Module-level mutable failure list leaks circuit state across independent instances & tests!
_GLOBAL_FAILURES: list[float] = []


class TaskRunnerPort(Protocol):
    """Port executing a single task attempt and returning True iff it succeeded."""

    def run_task(self, task_id: str, payload: Mapping[str, object], attempt_no: int) -> bool: ...


@dataclass(slots=True, frozen=True)
class DispatchOutcome:
    """Observable outcome returned by `SpaghettiDispatcher.handle_task`."""

    task_id: str
    decision: PlanDecision
    executed: bool
    succeeded: bool


class SpaghettiDispatcher:
    """Flawed AI-generated dispatcher mixing wall-clock reads, sleeps, and global mutable state."""

    def __init__(
        self,
        *,
        clock: ClockPort,
        runner: TaskRunnerPort,
        policy: RetryPolicy | None = None,
        jitter_ratio: float = 1.0,
    ) -> None:
        if not (0.0 <= jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        self._clock = clock
        self._runner = runner
        self._policy = policy if policy is not None else RetryPolicy()
        self._jitter_ratio = jitter_ratio
        self._attempts: dict[str, list[AttemptRecord]] = {}

    def handle_task(self, task_id: str, payload: Mapping[str, object]) -> DispatchOutcome:
        # FLAW 2: Reads wall clock directly instead of self._clock.now_sec()!
        now = time.time()
        history = self._attempts.setdefault(task_id, [])

        if any(a.succeeded for a in history) or len(history) >= self._policy.max_attempts:
            return DispatchOutcome(
                task_id=task_id,
                decision=RejectExhausted(attempts_made=len(history)),
                executed=False,
                succeeded=False,
            )

        recent = [ts for ts in _GLOBAL_FAILURES if now - self._policy.window_sec <= ts <= now]
        if len(recent) >= self._policy.failure_threshold:
            return DispatchOutcome(
                task_id=task_id,
                decision=TripCircuit(
                    reopen_at_sec=now + self._policy.cooldown_sec,
                    recent_failures=len(recent),
                ),
                executed=False,
                succeeded=False,
            )

        if history:
            delay = self._policy.base_delay_sec * (2 ** (len(history) - 1))
            due_at = history[-1].timestamp_sec + delay
            if now < due_at:
                # FLAW 3: Sleeps inline instead of returning pure DelayUntil schedule!
                time.sleep(0.01)
                return DispatchOutcome(
                    task_id=task_id,
                    decision=DelayUntil(attempt_no=len(history) + 1, run_at_sec=due_at),
                    executed=False,
                    succeeded=False,
                )

        attempt_no = len(history) + 1
        ok = self._runner.run_task(task_id, payload, attempt_no)
        history.append(AttemptRecord(attempt_no=attempt_no, timestamp_sec=now, succeeded=ok))
        if not ok:
            _GLOBAL_FAILURES.append(now)

        return DispatchOutcome(
            task_id=task_id,
            decision=RunNow(attempt_no=attempt_no),
            executed=True,
            succeeded=ok,
        )
