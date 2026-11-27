"""Reference learner test suite for M03 Drill A (kills 100% of seeded mutants)."""

from __future__ import annotations

import pytest

from drill_a_core import (
    DeadLetterTask,
    DomainValidationError,
    InvalidTransitionError,
    RetryableFailedTask,
    StaleLeaseError,
    TaskId,
    UtcDate,
    complete_task,
    fail_task,
    lease_task,
    parse_new_task,
    requeue_task,
)


def test_boundary_parsers_reject_whitespace_uppercase_and_timestamps() -> None:
    with pytest.raises(DomainValidationError):
        TaskId.parse(" task-1 ")
    with pytest.raises(DomainValidationError):
        TaskId.parse("TaskUpper")
    with pytest.raises(DomainValidationError):
        UtcDate.parse("2025-07-01T12:00:00")
    with pytest.raises(DomainValidationError):
        UtcDate.parse(" 2025-07-01 ")
    with pytest.raises(DomainValidationError):
        UtcDate.parse("2025-02-29")


def test_exact_max_attempts_routes_to_dead_letter() -> None:
    q0 = parse_new_task(
        {
            "task_id": "t-max",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 2,
        }
    )
    l1 = lease_task(q0, worker_id="w-1", lease_token=10)
    f1 = fail_task(l1, lease_token=10, error_reason="err-1")
    assert isinstance(f1, RetryableFailedTask)

    q1 = requeue_task(f1)
    l2 = lease_task(q1, worker_id="w-2", lease_token=11)
    f2 = fail_task(l2, lease_token=11, error_reason="err-2")
    assert isinstance(f2, DeadLetterTask)
    assert f2.attempts_used == 2


def test_stale_lease_token_rejected_on_complete_and_fail() -> None:
    q0 = parse_new_task(
        {
            "task_id": "t-fence",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 3,
        }
    )
    leased = lease_task(q0, worker_id="w-1", lease_token=42)
    with pytest.raises(StaleLeaseError):
        complete_task(leased, lease_token=41, output_summary="stale")
    with pytest.raises(StaleLeaseError):
        fail_task(leased, lease_token=41, error_reason="stale")


def test_terminal_states_cannot_transition_again() -> None:
    q0 = parse_new_task(
        {
            "task_id": "t-term",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 1,
        }
    )
    leased = lease_task(q0, worker_id="w-1", lease_token=1)
    done = complete_task(leased, lease_token=1, output_summary="done")

    with pytest.raises(InvalidTransitionError):
        lease_task(done, worker_id="w-2", lease_token=2)

    leased_dlq = lease_task(q0, worker_id="w-1", lease_token=3)
    dead = fail_task(leased_dlq, lease_token=3, error_reason="exhausted")
    assert isinstance(dead, DeadLetterTask)
    with pytest.raises(InvalidTransitionError):
        lease_task(dead, worker_id="w-2", lease_token=4)
