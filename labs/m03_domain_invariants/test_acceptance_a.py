"""Frozen acceptance oracle for M03 Drill A."""

from __future__ import annotations

import pytest

from drill_a_core import (
    DeadLetterTask,
    DomainValidationError,
    InvalidTransitionError,
    RetryableFailedTask,
    StaleLeaseError,
    TaskId,
    TenantId,
    UtcDate,
    complete_task,
    fail_task,
    lease_task,
    parse_new_task,
    requeue_task,
)


def test_boundary_value_parsers_reject_malformed_inputs() -> None:
    assert TaskId.parse("task_01-alpha").value == "task_01-alpha"
    assert TenantId.parse("acme-corp").value == "acme-corp"
    assert str(UtcDate.parse("2025-07-01")) == "2025-07-01"

    for bad_slug in ["", " acme", "acme ", "ACME", "-leading", "_leading", "a" * 65, "bad\x00id"]:
        with pytest.raises(DomainValidationError):
            TaskId.parse(bad_slug)

    for bad_date in ["", " 2025-07-01", "2025-02-30", "2025-07-01T00:00:00", "2025/07/01", "25-07-01"]:
        with pytest.raises(DomainValidationError):
            UtcDate.parse(bad_date)


def test_parse_new_task_rejects_bool_or_non_positive_attempts() -> None:
    queued = parse_new_task(
        {
            "task_id": "t-1",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 2,
        }
    )
    assert queued.max_attempts == 2
    assert queued.attempts_used == 0

    with pytest.raises(DomainValidationError):
        parse_new_task(
            {
                "task_id": "t-1",
                "tenant_id": "acme",
                "scheduled_for": "2025-07-01",
                "max_attempts": True,
            }
        )
    with pytest.raises(DomainValidationError):
        parse_new_task(
            {
                "task_id": "t-1",
                "tenant_id": "acme",
                "scheduled_for": "2025-07-01",
                "max_attempts": 0,
            }
        )


def test_lifecycle_retry_exhaustion_fencing_and_terminal_guards() -> None:
    q0 = parse_new_task(
        {
            "task_id": "job-9",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 2,
        }
    )
    leased_1 = lease_task(q0, worker_id="w-1", lease_token=101)
    assert leased_1.attempt_no == 1

    with pytest.raises(StaleLeaseError):
        complete_task(leased_1, lease_token=100, output_summary="wrong token")
    with pytest.raises(StaleLeaseError):
        fail_task(leased_1, lease_token=999, error_reason="wrong token")

    failed_1 = fail_task(leased_1, lease_token=101, error_reason="transient timeout")
    assert isinstance(failed_1, RetryableFailedTask)
    assert failed_1.attempts_used == 1

    q1 = requeue_task(failed_1)
    assert q1.attempts_used == 1
    assert q1.last_error == "transient timeout"

    leased_2 = lease_task(q1, worker_id="w-2", lease_token=102)
    assert leased_2.attempt_no == 2

    dead = fail_task(leased_2, lease_token=102, error_reason="second timeout")
    assert isinstance(dead, DeadLetterTask)
    assert dead.attempts_used == 2
    assert dead.fatal is False

    with pytest.raises(InvalidTransitionError):
        lease_task(dead, worker_id="w-3", lease_token=103)
    with pytest.raises(InvalidTransitionError):
        requeue_task(dead)


def test_complete_and_fatal_failure_transitions() -> None:
    q0 = parse_new_task(
        {
            "task_id": "job-ok",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 3,
        }
    )
    leased = lease_task(q0, worker_id="w-1", lease_token=1)
    done = complete_task(leased, lease_token=1, output_summary="ok")
    assert done.output_summary == "ok"

    with pytest.raises(InvalidTransitionError):
        lease_task(done, worker_id="w-2", lease_token=2)

    leased_fatal = lease_task(q0, worker_id="w-1", lease_token=5)
    fatal_dlq = fail_task(leased_fatal, lease_token=5, error_reason="schema error", fatal=True)
    assert isinstance(fatal_dlq, DeadLetterTask)
    assert fatal_dlq.fatal is True
