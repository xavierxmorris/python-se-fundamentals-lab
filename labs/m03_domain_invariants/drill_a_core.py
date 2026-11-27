"""M03 Drill A (Cold-Turkey Core, AI OFF): Domain Invariants & Lifecycle State Machine.

Behavioral Contract
-------------------
- Never use `assert` for validation; raise `DomainValidationError(field, reason)`.
- `TaskId.parse(raw)` / `TenantId.parse(raw)`: strict `^[a-z0-9][a-z0-9_-]{0,63}$`, no whitespace stripping.
- `UtcDate.parse(raw)`: strict 10-char `YYYY-MM-DD` calendar date (reject timestamps & invalid calendar days).
- State machine transitions:
  * `parse_new_task(raw) -> QueuedTask` (`max_attempts` must be `int >= 1`, not `bool`).
  * `lease_task(task, *, worker_id, lease_token) -> LeasedTask` (only from `QueuedTask`; `worker_id` non-blank `str`; `lease_token` `int >= 1`).
  * `complete_task(task, *, lease_token, output_summary) -> SucceededTask` (only from `LeasedTask`; mismatched token -> `StaleLeaseError`; non-blank `output_summary`).
  * `fail_task(task, *, lease_token, error_reason, fatal=False) -> RetryableFailedTask | DeadLetterTask`
    (only from `LeasedTask`; mismatched token -> `StaleLeaseError`; non-blank `error_reason`; `DeadLetterTask` if `fatal` or `attempt_no >= max_attempts`).
  * `requeue_task(task) -> QueuedTask` (only from `RetryableFailedTask`).
  * Any illegal source state raises `InvalidTransitionError`.
"""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from dataclasses import dataclass


class DomainValidationError(ValueError):
    """Structured boundary validation failure."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


class InvalidTransitionError(RuntimeError):
    """Raised when attempting an illegal state-machine transition."""


class StaleLeaseError(RuntimeError):
    """Raised when a worker presents an outdated or non-matching lease_token."""


@dataclass(slots=True, frozen=True)
class TaskId:
    value: str

    @classmethod
    def parse(cls, raw: str) -> TaskId:
        raise NotImplementedError("Implement TaskId.parse")


@dataclass(slots=True, frozen=True)
class TenantId:
    value: str

    @classmethod
    def parse(cls, raw: str) -> TenantId:
        raise NotImplementedError("Implement TenantId.parse")


@dataclass(slots=True, frozen=True, order=True)
class UtcDate:
    value: datetime.date

    @classmethod
    def parse(cls, raw: str) -> UtcDate:
        raise NotImplementedError("Implement UtcDate.parse")

    def __str__(self) -> str:
        return self.value.isoformat()


@dataclass(slots=True, frozen=True)
class QueuedTask:
    task_id: TaskId
    tenant_id: TenantId
    scheduled_for: UtcDate
    max_attempts: int
    attempts_used: int = 0
    last_error: str | None = None


@dataclass(slots=True, frozen=True)
class LeasedTask:
    task_id: TaskId
    tenant_id: TenantId
    scheduled_for: UtcDate
    max_attempts: int
    attempt_no: int
    worker_id: str
    lease_token: int


@dataclass(slots=True, frozen=True)
class SucceededTask:
    task_id: TaskId
    tenant_id: TenantId
    scheduled_for: UtcDate
    attempt_no: int
    worker_id: str
    output_summary: str


@dataclass(slots=True, frozen=True)
class RetryableFailedTask:
    task_id: TaskId
    tenant_id: TenantId
    scheduled_for: UtcDate
    max_attempts: int
    attempts_used: int
    error_reason: str


@dataclass(slots=True, frozen=True)
class DeadLetterTask:
    task_id: TaskId
    tenant_id: TenantId
    scheduled_for: UtcDate
    attempts_used: int
    failure_reason: str
    fatal: bool


type TaskRecord = QueuedTask | LeasedTask | SucceededTask | RetryableFailedTask | DeadLetterTask


def parse_new_task(raw: Mapping[str, object]) -> QueuedTask:
    raise NotImplementedError("Implement parse_new_task")


def lease_task(task: TaskRecord, *, worker_id: str, lease_token: int) -> LeasedTask:
    raise NotImplementedError("Implement lease_task")


def complete_task(task: TaskRecord, *, lease_token: int, output_summary: str) -> SucceededTask:
    raise NotImplementedError("Implement complete_task")


def fail_task(
    task: TaskRecord,
    *,
    lease_token: int,
    error_reason: str,
    fatal: bool = False,
) -> RetryableFailedTask | DeadLetterTask:
    raise NotImplementedError("Implement fail_task")


def requeue_task(task: TaskRecord) -> QueuedTask:
    raise NotImplementedError("Implement requeue_task")
