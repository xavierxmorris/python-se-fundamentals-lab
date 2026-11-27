"""Reference learner test suite for M06 Drill A (zero mocks/monkeypatch, kills 100% of mutants)."""

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


class _ManualClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now_sec(self) -> float:
        return self.t


class _StaticJitter:
    def __init__(self, ratio: float = 1.0) -> None:
        self.ratio = ratio

    def sample_ratio(self) -> float:
        return self.ratio


class _InMemoryLedger:
    def __init__(self) -> None:
        self._attempts: dict[str, list[AttemptRecord]] = {}
        self._failures: list[float] = []
        self._opened_at: float | None = None

    def get_attempts(self, task_id: str) -> Sequence[AttemptRecord]:
        return tuple(self._attempts.get(task_id, ()))

    def record_attempt(self, task_id: str, record: AttemptRecord) -> None:
        self._attempts.setdefault(task_id, []).append(record)

    def get_circuit_failures(self) -> Sequence[float]:
        return tuple(self._failures)

    def record_circuit_failure(self, timestamp_sec: float) -> None:
        self._failures.append(timestamp_sec)

    def get_circuit_opened_at(self) -> float | None:
        return self._opened_at

    def set_circuit_opened_at(self, opened_at_sec: float | None) -> None:
        self._opened_at = opened_at_sec


def test_backoff_exponent_and_max_delay_cap() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay_sec=4.0, max_delay_sec=10.0)

    # First failure -> 2**(1 - 1) == 1 -> raw = 4.0, jitter=1.0 -> effective = 4.0 -> due at 14.0
    after_one = [AttemptRecord(attempt_no=1, timestamp_sec=10.0, succeeded=False)]
    assert decide_next_action(
        attempts=after_one,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=12.0,
        jitter_ratio=1.0,
    ) == DelayUntil(attempt_no=2, run_at_sec=14.0)
    assert decide_next_action(
        attempts=after_one,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=14.0,
        jitter_ratio=1.0,
    ) == RunNow(attempt_no=2)

    # Three failures -> 4.0 * 2**2 = 16.0, capped by max_delay_sec=10.0 -> jitter=0.5 -> effective = 7.5
    after_three = [
        AttemptRecord(attempt_no=1, timestamp_sec=10.0, succeeded=False),
        AttemptRecord(attempt_no=2, timestamp_sec=14.0, succeeded=False),
        AttemptRecord(attempt_no=3, timestamp_sec=22.0, succeeded=False),
    ]
    assert decide_next_action(
        attempts=after_three,
        circuit_failures_sec=(),
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=25.0,
        jitter_ratio=0.5,
    ) == DelayUntil(attempt_no=4, run_at_sec=29.5)


def test_circuit_threshold_exact_boundary_and_window_filtering() -> None:
    policy = RetryPolicy(max_attempts=4, failure_threshold=3, window_sec=30.0, cooldown_sec=12.0)

    # 1 expired failure (t=69.9 < 100 - 30) + 2 recent failures -> below threshold 3 -> RunNow
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=[69.9, 80.0, 95.0],
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=100.0,
        jitter_ratio=1.0,
    ) == RunNow(attempt_no=1)

    # Exact boundary: 3 failures in [70.0, 100.0] == failure_threshold -> TripCircuit
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=[70.0, 80.0, 100.0],
        circuit_opened_at_sec=None,
        policy=policy,
        now_sec=100.0,
        jitter_ratio=1.0,
    ) == TripCircuit(reopen_at_sec=112.0, recent_failures=3)


def test_half_open_cooldown_allows_probe_without_retripping_on_old_failures() -> None:
    policy = RetryPolicy(max_attempts=4, base_delay_sec=2.0, failure_threshold=2, window_sec=60.0, cooldown_sec=15.0)
    pre_cooldown_failures = [45.0, 49.0]

    # Before cooldown expiry (t=64.9 < 50 + 15): remains open
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=pre_cooldown_failures,
        circuit_opened_at_sec=50.0,
        policy=policy,
        now_sec=64.9,
        jitter_ratio=1.0,
    ) == TripCircuit(reopen_at_sec=65.0, recent_failures=2)

    # At cooldown expiry (t=65.0 >= 50 + 15): half-open allows probe even though failures are still in 60s window!
    assert decide_next_action(
        attempts=(),
        circuit_failures_sec=pre_cooldown_failures,
        circuit_opened_at_sec=50.0,
        policy=policy,
        now_sec=65.0,
        jitter_ratio=1.0,
    ) == RunNow(attempt_no=1)


def test_exhausted_precedence_and_jitter_validation() -> None:
    policy = RetryPolicy(max_attempts=2)
    with pytest.raises(ValueError):
        decide_next_action(
            attempts=(),
            circuit_failures_sec=(),
            circuit_opened_at_sec=None,
            policy=policy,
            now_sec=0.0,
            jitter_ratio=-0.1,
        )

    done = [AttemptRecord(attempt_no=1, timestamp_sec=5.0, succeeded=True)]
    assert decide_next_action(
        attempts=done,
        circuit_failures_sec=[5.0, 6.0, 7.0],
        circuit_opened_at_sec=7.0,
        policy=policy,
        now_sec=8.0,
        jitter_ratio=0.0,
    ) == RejectExhausted(attempts_made=1)


def test_dispatcher_shell_half_open_probe_reopen_and_close() -> None:
    clock = _ManualClock(10.0)
    jitter = _StaticJitter(1.0)
    ledger = _InMemoryLedger()
    policy = RetryPolicy(max_attempts=3, base_delay_sec=2.0, failure_threshold=2, cooldown_sec=10.0)
    shell = DispatcherShell(clock=clock, jitter=jitter, ledger=ledger, policy=policy)

    assert shell.dispatch("task-a", lambda _n: False) == RunNow(attempt_no=1)
    assert shell.dispatch("task-b", lambda _n: False) == RunNow(attempt_no=1)

    # Next task trips circuit at t=10.0 until t=20.0
    assert shell.dispatch("task-c", lambda _n: True) == TripCircuit(reopen_at_sec=20.0, recent_failures=2)
    assert ledger.get_circuit_opened_at() == 10.0

    # Half-open probe at t=20.0 fails -> re-opens circuit at 20.0 until 30.0
    clock.t = 20.0
    assert shell.dispatch("task-c", lambda _n: False) == RunNow(attempt_no=1)
    assert ledger.get_circuit_opened_at() == 20.0

    # Half-open probe at t=30.0 succeeds -> closes circuit
    clock.t = 30.0
    assert shell.dispatch("task-d", lambda _n: True) == RunNow(attempt_no=1)
    assert ledger.get_circuit_opened_at() is None
