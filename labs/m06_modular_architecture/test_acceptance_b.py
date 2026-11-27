"""Frozen acceptance suite for M06 Drill B."""

from collections.abc import Mapping

from drill_a_core import DelayUntil, RejectExhausted, RetryPolicy, RunNow, TripCircuit
from drill_b_ai_adapter import SpaghettiDispatcher


class _SteppingClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def now_sec(self) -> float:
        return self.now


class _RecordingRunner:
    def __init__(self, outcomes: list[bool]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[str, int]] = []

    def run_task(self, task_id: str, payload: Mapping[str, object], attempt_no: int) -> bool:
        _ = payload
        self.calls.append((task_id, attempt_no))
        return self._outcomes.pop(0)


def test_spaghetti_dispatcher_uses_injected_clock_and_caps_backoff() -> None:
    clock = _SteppingClock(500.0)
    runner = _RecordingRunner([False, False, True])
    policy = RetryPolicy(max_attempts=4, base_delay_sec=10.0, max_delay_sec=12.0, failure_threshold=5)
    dispatcher = SpaghettiDispatcher(clock=clock, runner=runner, policy=policy, jitter_ratio=1.0)

    r1 = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r1.decision == RunNow(attempt_no=1)
    assert r1.executed is True and r1.succeeded is False

    clock.now = 505.0
    r_wait = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r_wait.decision == DelayUntil(attempt_no=2, run_at_sec=510.0)
    assert r_wait.executed is False

    clock.now = 510.0
    r2 = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r2.decision == RunNow(attempt_no=2)
    assert r2.executed is True and r2.succeeded is False

    # 2 failures -> 10 * 2^1 = 20 capped at max_delay_sec=12.0 -> due at 522.0
    clock.now = 521.0
    r_capped = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r_capped.decision == DelayUntil(attempt_no=3, run_at_sec=522.0)

    clock.now = 522.0
    r3 = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r3.decision == RunNow(attempt_no=3)
    assert r3.executed is True and r3.succeeded is True

    r_done = dispatcher.handle_task("job-1", {"op": "sync"})
    assert r_done.decision == RejectExhausted(attempts_made=3)
    assert r_done.executed is False
    assert runner.calls == [("job-1", 1), ("job-1", 2), ("job-1", 3)]


def test_spaghetti_dispatcher_isolates_failure_windows_between_instances() -> None:
    clock_a = _SteppingClock(100.0)
    runner_a = _RecordingRunner([False, False, True])
    policy = RetryPolicy(max_attempts=3, failure_threshold=2, window_sec=60.0, cooldown_sec=20.0)
    disp_a = SpaghettiDispatcher(clock=clock_a, runner=runner_a, policy=policy, jitter_ratio=1.0)

    disp_a.handle_task("a-1", {})
    disp_a.handle_task("a-2", {})

    # disp_a's circuit is now tripped
    tripped = disp_a.handle_task("a-3", {})
    assert tripped.decision == TripCircuit(reopen_at_sec=120.0, recent_failures=2)
    assert tripped.executed is False

    # A separate instance disp_b MUST NOT inherit disp_a's failures!
    clock_b = _SteppingClock(100.0)
    runner_b = _RecordingRunner([True])
    disp_b = SpaghettiDispatcher(clock=clock_b, runner=runner_b, policy=policy, jitter_ratio=1.0)
    clean = disp_b.handle_task("b-1", {})
    assert clean.decision == RunNow(attempt_no=1)
    assert clean.executed is True and clean.succeeded is True

    # After cooldown expires on disp_a (t=120.0), half-open probe succeeds and closes circuit
    clock_a.now = 120.0
    recovered = disp_a.handle_task("a-3", {})
    assert recovered.decision == RunNow(attempt_no=1)
    assert recovered.executed is True and recovered.succeeded is True
