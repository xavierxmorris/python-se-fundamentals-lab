"""Frozen acceptance suite for M06 Drill A."""

from collections.abc import Sequence

import pytest

from drill_a_core import (
    AttemptRecord,
    DelayUntil,
    DispatcherShell,
    RejectExhausted,
    RetryPolicy,
    RunNow,
    TripCircuit,
    decide_next_action,
)


class _FakeClock:
    def __init__(self, initial: float = 100.0) -> None:
        self.current = initial

    def now_sec(self) -> float:
        return self.current


class _FakeJitter:
    def __init__(self, ratio: float = 1.0) -> None:
        self.ratio = ratio

    def sample_ratio(self) -> float:
        return self.ratio


class _FakeLedger:
    def __init__(self) -> None:
        self.attempts: dict[str, list[AttemptRecord]] = {}
        self.failures: list[float] = []
        self.opened_at: float | None = None

    def get_attempts(self, task_id: str) -> Sequence[AttemptRecord]:
        return tuple(self.attempts.get(task_id, ()))

    def record_attempt(self, task_id: str, record: AttemptRecord) -> None:
        self.attempts.setdefault(task_id, []).append(record)

    def get_circuit_failures(self) -> Sequence[float]:
        return tuple(self.failures)

    def record_circuit_failure(self, timestamp_sec: float) -> None:
        self.failures.append(timestamp_sec)

    def get_circuit_opened_at(self) -> float | None:
        return self.opened_at

    def set_circuit_opened_at(self, opened_at_sec: float | None) -> None:
        self.opened_at = opened_at_sec


def test_decide_next_action_validates_jitter_bounds() -> None:
    policy = RetryPolicy()
    for bad in (-0.01, 1.01, float("nan")):
        with pytest.raises(ValueError):
            decide_next_action(
                attempts=(),
                circuit_failures_sec=(),
                circuit_opened_at_sec=None,
                policy=policy,
                now_sec=10.0,
                jitter_ratio=bad,
            )


def test_decide_next_action_precedence_exhausted_and_succeeded() -> None:
    policy = RetryPolicy(max_attempts=3, failure_threshold=2)
    already_ok = [AttemptRecord(attempt_no=1, timestamp_sec=10.0, succeeded=True)]
    assert decide_next_action(
        attempts=already_ok,
        circuit_failures_sec=[10.0, 11.0, 12.0],
        circuit_opened_at_sec=12.0,
        policy=policy,
        now_sec=13.0,
        jitter_ratio=0.5,
    ) == RejectExhausted(attempts_made=1)

    exhausted = [
        AttemptRecord(attempt_no=1, timestamp_sec=1.0, succeeded=False),
        AttemptRecord(attempt_no=2, timestamp_sec=3.0, succeeded=False),
        AttemptRecord(attempt_no=3, timestamp_sec=7.0, succeeded=False),
    ]
    assert decide_next_action(
        attempts=exhausted,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=50.0,
        jitter_ratio=1.0,
    ) == RejectExhausted(attempts_made=3)


def test_decide_next_action_exponential_backoff_jitter_and_cap() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay_sec=2.0, max_delay_sec=10.0)
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=100.0,
        jitter_ratio=0.0,
    ) == RunNow(attempt_no=1)

    # 1 failure -> raw = min(10, 2 * 2^0) = 2.0; jitter_ratio=0.0 -> effective = 1.0 -> due_at = 101.0
    one_fail = [AttemptRecord(1, 100.0, False)]
    assert decide_next_action(
        attempts=one_fail,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=100.5,
        jitter_ratio=0.0,
    ) == DelayUntil(attempt_no=2, run_at_sec=101.0)
    assert decide_next_action(
        attempts=one_fail,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=101.0,
        jitter_ratio=0.0,
    ) == RunNow(attempt_no=2)

    # 4 failures -> 2 * 2^3 = 16.0 capped at max_delay_sec=10.0; jitter_ratio=1.0 -> effective = 10.0
    four_fails = [
        AttemptRecord(1, 10.0, False),
        AttemptRecord(2, 12.0, False),
        AttemptRecord(3, 16.0, False),
        AttemptRecord(4, 24.0, False),
    ]
    assert decide_next_action(
        attempts=four_fails,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=30.0,
        jitter_ratio=1.0,
    ) == DelayUntil(attempt_no=5, run_at_sec=34.0)


def test_decide_next_action_circuit_open_and_half_open_recovery() -> None:
    policy = RetryPolicy(max_attempts=4, failure_threshold=3, window_sec=60.0, cooldown_sec=15.0)
    failures = [50.0, 70.0, 90.0]

    # Closed circuit trips when recent failures == failure_threshold
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=failures,
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=100.0,
        jitter_ratio=1.0,
    ) == TripCircuit(reopen_at_sec=115.0, recent_failures=3)

    # During cooldown [100.0, 115.0), circuit stays open
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=failures,
        circuit_opened_at_sec=100.0,
        policy=policy,
        now_sec=114.9,
        jitter_ratio=1.0,
    ) == TripCircuit(reopen_at_sec=115.0, recent_failures=2)

    # At exact cooldown boundary now_sec == 115.0, circuit is half-open -> allows probe despite recent failures!
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=[105.0, 108.0, 110.0],
        circuit_opened_at_sec=100.0,
        policy=policy,
        now_sec=115.0,
        jitter_ratio=1.0,
    ) == RunNow(attempt_no=1)


def test_dispatcher_shell_coordinates_ports_deterministically() -> None:
    clock = _FakeClock(200.0)
    jitter = _FakeJitter(1.0)
    ledger = _FakeLedger()
    policy = RetryPolicy(max_attempts=3, base_delay_sec=4.0, failure_threshold=2, cooldown_sec=10.0)
    shell = DispatcherShell(clock=clock, jitter=jitter, ledger=ledger, policy=policy)

    # 1st task fails twice (at t=200 and t=204), tripping the circuit on subsequent plan
    assert shell.dispatch("t-1", lambda n: False) == RunNow(attempt_no=1)
    clock.current = 202.0
    assert shell.dispatch("t-1", lambda n: True) == DelayUntil(attempt_no=2, run_at_sec=204.0)

    clock.current = 204.0
    assert shell.dispatch("t-1", lambda n: False) == RunNow(attempt_no=2)

    # Circuit now has 2 failures within window -> trips at t=205.0 until 215.0
    clock.current = 205.0
    ran_when_open = False

    def _probe(_attempt_no: int) -> bool:
        nonlocal ran_when_open
        ran_when_open = True
        return True

    assert shell.dispatch("t-2", _probe) == TripCircuit(reopen_at_sec=215.0, recent_failures=2)
    assert ran_when_open is False
    assert ledger.get_circuit_opened_at() == 205.0

    # At t=215.0 half-open probe succeeds and closes the circuit
    clock.current = 215.0
    assert shell.dispatch("t-2", lambda n: True) == RunNow(attempt_no=1)
    assert ledger.get_circuit_opened_at() is None
