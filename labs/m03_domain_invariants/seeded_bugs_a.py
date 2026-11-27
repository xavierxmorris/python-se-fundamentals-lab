"""Seeded mutants for M03 Gate 4 mutation kill-rate check."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from types import ModuleType

from drill_a_core import (
    DeadLetterTask,
    DomainValidationError,
    InvalidTransitionError,
    LeasedTask,
    QueuedTask,
    RetryableFailedTask,
    SucceededTask,
    TaskId,
    TaskRecord,
    UtcDate,
)


def _bug_off_by_one_max_attempts(mod: ModuleType) -> None:
    """Bug 1: Uses `>` instead of `>=` when checking `attempt_no >= max_attempts`."""

    def buggy_fail_task(
        task: TaskRecord,
        *,
        lease_token: int,
        error_reason: str,
        fatal: bool = False,
    ) -> RetryableFailedTask | DeadLetterTask:
        if not isinstance(task, LeasedTask):
            raise InvalidTransitionError("fail_task requires LeasedTask")
        if task.lease_token != lease_token:
            raise mod.StaleLeaseError("stale lease")
        if fatal or task.attempt_no > task.max_attempts:  # BUG: should be >=
            return DeadLetterTask(
                task_id=task.task_id,
                tenant_id=task.tenant_id,
                scheduled_for=task.scheduled_for,
                attempts_used=task.attempt_no,
                failure_reason=error_reason,
                fatal=fatal,
            )
        return RetryableFailedTask(
            task_id=task.task_id,
            tenant_id=task.tenant_id,
            scheduled_for=task.scheduled_for,
            max_attempts=task.max_attempts,
            attempts_used=task.attempt_no,
            error_reason=error_reason,
        )

    mod.__dict__["fail_task"] = buggy_fail_task


def _bug_accepts_stale_lease_token(mod: ModuleType) -> None:
    """Bug 2: `complete_task` ignores `lease_token` mismatch, allowing stale worker completion."""

    def buggy_complete_task(
        task: TaskRecord,
        *,
        lease_token: int,
        output_summary: str,
    ) -> SucceededTask:
        _ = lease_token
        if not isinstance(task, LeasedTask):
            raise InvalidTransitionError("complete_task requires LeasedTask")
        if not output_summary.strip():
            raise DomainValidationError("output_summary", "must not be blank")
        return SucceededTask(
            task_id=task.task_id,
            tenant_id=task.tenant_id,
            scheduled_for=task.scheduled_for,
            attempt_no=task.attempt_no,
            worker_id=task.worker_id,
            output_summary=output_summary,
        )

    mod.__dict__["complete_task"] = buggy_complete_task


def _bug_allows_terminal_transition(mod: ModuleType) -> None:
    """Bug 3: `lease_task` allows re-leasing a `SucceededTask` or `DeadLetterTask`."""

    def buggy_lease_task(task: TaskRecord, *, worker_id: str, lease_token: int) -> LeasedTask:
        if isinstance(task, (QueuedTask, DeadLetterTask, SucceededTask)):
            attempts_used = getattr(task, "attempts_used", 0)
            max_attempts = getattr(task, "max_attempts", 3)
            return LeasedTask(
                task_id=task.task_id,
                tenant_id=task.tenant_id,
                scheduled_for=task.scheduled_for,
                max_attempts=max_attempts,
                attempt_no=attempts_used + 1,
                worker_id=worker_id,
                lease_token=lease_token,
            )
        raise InvalidTransitionError("cannot lease")

    mod.__dict__["lease_task"] = buggy_lease_task


def _bug_permissive_boundary_parsing(mod: ModuleType) -> None:
    """Bug 4: `UtcDate.parse` accepts whitespace-padded or timestamp strings via `.strip()[:10]`."""

    class PermissiveUtcDate(UtcDate):
        @classmethod
        def parse(cls, raw: str) -> PermissiveUtcDate:
            if len(raw.strip()) < 10:
                raise DomainValidationError("utc_date", "invalid date")
            try:
                parsed = datetime.date.fromisoformat(raw.strip()[:10])
            except ValueError as exc:
                raise DomainValidationError("utc_date", str(exc)) from exc
            return cls(parsed)

    class PermissiveTaskId(TaskId):
        @classmethod
        def parse(cls, raw: str) -> PermissiveTaskId:
            if not raw.strip():
                raise DomainValidationError("task_id", "empty")
            return cls(raw.strip().lower())

    mod.__dict__["UtcDate"] = PermissiveUtcDate
    mod.__dict__["TaskId"] = PermissiveTaskId


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_off_by_one_max_attempts": _bug_off_by_one_max_attempts,
    "bug_accepts_stale_lease_token": _bug_accepts_stale_lease_token,
    "bug_allows_terminal_transition": _bug_allows_terminal_transition,
    "bug_permissive_boundary_parsing": _bug_permissive_boundary_parsing,
}
