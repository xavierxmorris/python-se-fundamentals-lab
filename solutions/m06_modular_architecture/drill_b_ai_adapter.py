"""M06 Drill B Reference Solution: Port-injected dispatcher with instance-isolated state."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from drill_a_core import (
    AttemptRecord,
    ClockPort,
    PlanDecision,
    RetryPolicy,
    RunNow,
    TripCircuit,
    decide_next_action,
)


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
    """Refactored imperative shell delegating policy math to `decide_next_action`."""

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
        self._circuit_failures_sec: list[float] = []
        self._circuit_opened_at_sec: float | None = None

    def handle_task(self, task_id: str, payload: Mapping[str, object]) -> DispatchOutcome:
        now = self._clock.now_sec()
        history = self._attempts.get(task_id, ())

        decision = decide_next_action(
            attempts=history,
            circuit_failures_sec=self._circuit_failures_sec,
            circuit_opened_at_sec=self._circuit_opened_at_sec,
            policy=self._policy,
            now_sec=now,
            jitter_ratio=self._jitter_ratio,
        )

        if isinstance(decision, TripCircuit):
            if self._circuit_opened_at_sec is None:
                self._circuit_opened_at_sec = now
            return DispatchOutcome(
                task_id=task_id,
                decision=decision,
                executed=False,
                succeeded=False,
            )

        if not isinstance(decision, RunNow):
            return DispatchOutcome(
                task_id=task_id,
                decision=decision,
                executed=False,
                succeeded=False,
            )

        succeeded = self._runner.run_task(task_id, payload, decision.attempt_no)
        finished_at = self._clock.now_sec()
        self._attempts.setdefault(task_id, []).append(
            AttemptRecord(
                attempt_no=decision.attempt_no,
                timestamp_sec=finished_at,
                succeeded=succeeded,
            )
        )
        if succeeded:
            if self._circuit_opened_at_sec is not None:
                self._circuit_opened_at_sec = None
        else:
            self._circuit_failures_sec.append(finished_at)
            if self._circuit_opened_at_sec is not None:
                self._circuit_opened_at_sec = finished_at

        return DispatchOutcome(
            task_id=task_id,
            decision=decision,
            executed=True,
            succeeded=succeeded,
        )
