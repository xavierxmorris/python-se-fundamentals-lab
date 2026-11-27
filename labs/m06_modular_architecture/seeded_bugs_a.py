"""Seeded realistic mutants for M06 Gate 4 mutation testing."""

from collections.abc import Callable, Sequence
from types import ModuleType

import drill_a_core as _core


def _bug_missing_max_delay_cap(mod: ModuleType) -> None:
    """Mutant 1: Omits `policy.max_delay_sec` cap when computing exponential backoff."""

    def uncapped_decide_next_action(
        *,
        attempts: Sequence[_core.AttemptRecord],
        circuit_failures_sec: Sequence[float],
        circuit_opened_at_sec: float | None,
        policy: _core.RetryPolicy,
        now_sec: float,
        jitter_ratio: float,
    ) -> _core.PlanDecision:
        if not (0.0 <= jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        if any(a.succeeded for a in attempts) or len(attempts) >= policy.max_attempts:
            return _core.RejectExhausted(attempts_made=len(attempts))
        if circuit_opened_at_sec is not None:
            if now_sec < circuit_opened_at_sec + policy.cooldown_sec:
                recent = [
                    ts
                    for ts in circuit_failures_sec
                    if now_sec - policy.window_sec <= ts <= now_sec
                ]
                return _core.TripCircuit(
                    reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        else:
            recent = [
                ts
                for ts in circuit_failures_sec
                if now_sec - policy.window_sec <= ts <= now_sec
            ]
            if len(recent) >= policy.failure_threshold:
                return _core.TripCircuit(
                    reopen_at_sec=now_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        if len(attempts) == 0:
            return _core.RunNow(attempt_no=1)
        failed_count = len(attempts)
        raw = policy.base_delay_sec * (2 ** (failed_count - 1))
        effective = raw * (0.5 + 0.5 * jitter_ratio)
        due_at = attempts[-1].timestamp_sec + effective
        if now_sec >= due_at:
            return _core.RunNow(attempt_no=failed_count + 1)
        return _core.DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)

    mod.__dict__["decide_next_action"] = uncapped_decide_next_action


def _bug_wrong_backoff_exponent(mod: ModuleType) -> None:
    """Mutant 2: Uses `2 ** failed_count` instead of `2 ** (failed_count - 1)`."""

    def shifted_exponent_decide(
        *,
        attempts: Sequence[_core.AttemptRecord],
        circuit_failures_sec: Sequence[float],
        circuit_opened_at_sec: float | None,
        policy: _core.RetryPolicy,
        now_sec: float,
        jitter_ratio: float,
    ) -> _core.PlanDecision:
        if not (0.0 <= jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        if any(a.succeeded for a in attempts) or len(attempts) >= policy.max_attempts:
            return _core.RejectExhausted(attempts_made=len(attempts))
        if circuit_opened_at_sec is not None:
            if now_sec < circuit_opened_at_sec + policy.cooldown_sec:
                recent = [
                    ts
                    for ts in circuit_failures_sec
                    if now_sec - policy.window_sec <= ts <= now_sec
                ]
                return _core.TripCircuit(
                    reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        else:
            recent = [
                ts
                for ts in circuit_failures_sec
                if now_sec - policy.window_sec <= ts <= now_sec
            ]
            if len(recent) >= policy.failure_threshold:
                return _core.TripCircuit(
                    reopen_at_sec=now_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        if len(attempts) == 0:
            return _core.RunNow(attempt_no=1)
        failed_count = len(attempts)
        raw = min(policy.max_delay_sec, policy.base_delay_sec * (2**failed_count))
        effective = raw * (0.5 + 0.5 * jitter_ratio)
        due_at = attempts[-1].timestamp_sec + effective
        if now_sec >= due_at:
            return _core.RunNow(attempt_no=failed_count + 1)
        return _core.DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)

    mod.__dict__["decide_next_action"] = shifted_exponent_decide


def _bug_circuit_threshold_off_by_one(mod: ModuleType) -> None:
    """Mutant 3: Uses `len(recent) > policy.failure_threshold` instead of `>=`."""

    def off_by_one_threshold_decide(
        *,
        attempts: Sequence[_core.AttemptRecord],
        circuit_failures_sec: Sequence[float],
        circuit_opened_at_sec: float | None,
        policy: _core.RetryPolicy,
        now_sec: float,
        jitter_ratio: float,
    ) -> _core.PlanDecision:
        if not (0.0 <= jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        if any(a.succeeded for a in attempts) or len(attempts) >= policy.max_attempts:
            return _core.RejectExhausted(attempts_made=len(attempts))
        if circuit_opened_at_sec is not None:
            if now_sec < circuit_opened_at_sec + policy.cooldown_sec:
                recent = [
                    ts
                    for ts in circuit_failures_sec
                    if now_sec - policy.window_sec <= ts <= now_sec
                ]
                return _core.TripCircuit(
                    reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        else:
            recent = [
                ts
                for ts in circuit_failures_sec
                if now_sec - policy.window_sec <= ts <= now_sec
            ]
            if len(recent) > policy.failure_threshold:
                return _core.TripCircuit(
                    reopen_at_sec=now_sec + policy.cooldown_sec,
                    recent_failures=len(recent),
                )
        if len(attempts) == 0:
            return _core.RunNow(attempt_no=1)
        failed_count = len(attempts)
        raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (failed_count - 1)))
        effective = raw * (0.5 + 0.5 * jitter_ratio)
        due_at = attempts[-1].timestamp_sec + effective
        if now_sec >= due_at:
            return _core.RunNow(attempt_no=failed_count + 1)
        return _core.DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)

    mod.__dict__["decide_next_action"] = off_by_one_threshold_decide


def _bug_ignores_half_open_cooldown(mod: ModuleType) -> None:
    """Mutant 4: Stays permanently tripped once `circuit_opened_at_sec` is set, ignoring cooldown expiry."""

    def stuck_open_decide(
        *,
        attempts: Sequence[_core.AttemptRecord],
        circuit_failures_sec: Sequence[float],
        circuit_opened_at_sec: float | None,
        policy: _core.RetryPolicy,
        now_sec: float,
        jitter_ratio: float,
    ) -> _core.PlanDecision:
        if not (0.0 <= jitter_ratio <= 1.0):
            raise ValueError("jitter_ratio must be in [0.0, 1.0]")
        if any(a.succeeded for a in attempts) or len(attempts) >= policy.max_attempts:
            return _core.RejectExhausted(attempts_made=len(attempts))
        recent = [
            ts for ts in circuit_failures_sec if now_sec - policy.window_sec <= ts <= now_sec
        ]
        if circuit_opened_at_sec is not None:
            return _core.TripCircuit(
                reopen_at_sec=circuit_opened_at_sec + policy.cooldown_sec,
                recent_failures=len(recent),
            )
        if len(recent) >= policy.failure_threshold:
            return _core.TripCircuit(
                reopen_at_sec=now_sec + policy.cooldown_sec,
                recent_failures=len(recent),
            )
        if len(attempts) == 0:
            return _core.RunNow(attempt_no=1)
        failed_count = len(attempts)
        raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** (failed_count - 1)))
        effective = raw * (0.5 + 0.5 * jitter_ratio)
        due_at = attempts[-1].timestamp_sec + effective
        if now_sec >= due_at:
            return _core.RunNow(attempt_no=failed_count + 1)
        return _core.DelayUntil(attempt_no=failed_count + 1, run_at_sec=due_at)

    mod.__dict__["decide_next_action"] = stuck_open_decide


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "missing_max_delay_cap": _bug_missing_max_delay_cap,
    "wrong_backoff_exponent": _bug_wrong_backoff_exponent,
    "circuit_threshold_off_by_one": _bug_circuit_threshold_off_by_one,
    "ignores_half_open_cooldown": _bug_ignores_half_open_cooldown,
}
