"""Reference solution for M03 Drill A: Domain Invariants & Lifecycle State Machine."""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def _parse_slug(field: str, raw: object) -> str:
    if not isinstance(raw, str):
        raise DomainValidationError(field, f"expected str, got {type(raw).__name__}")
    if not _SLUG_RE.fullmatch(raw):
        raise DomainValidationError(
            field,
            "must be 1..64 lowercase ASCII chars matching ^[a-z0-9][a-z0-9_-]{0,63}$ with no whitespace",
        )
    return raw


def _require_positive_int(field: str, raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise DomainValidationError(field, "must be an int (not bool)")
    if raw < 1:
        raise DomainValidationError(field, "must be >= 1")
    return raw


def _require_non_blank_str(field: str, raw: object) -> str:
    if not isinstance(raw, str):
        raise DomainValidationError(field, f"expected str, got {type(raw).__name__}")
    if not raw.strip():
        raise DomainValidationError(field, "must not be empty or whitespace")
    return raw


@dataclass(slots=True, frozen=True)
class TaskId:
    value: str

    @classmethod
    def parse(cls, raw: str) -> TaskId:
        return cls(_parse_slug("task_id", raw))


@dataclass(slots=True, frozen=True)
class TenantId:
    value: str

    @classmethod
    def parse(cls, raw: str) -> TenantId:
        return cls(_parse_slug("tenant_id", raw))


@dataclass(slots=True, frozen=True, order=True)
class UtcDate:
    value: datetime.date

    @classmethod
    def parse(cls, raw: str) -> UtcDate:
        if not isinstance(raw, str):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise DomainValidationError("utc_date", f"expected str, got {type(raw).__name__}")
        if not _DATE_RE.fullmatch(raw):
            raise DomainValidationError("utc_date", "must be strict YYYY-MM-DD without whitespace or time")
        try:
            parsed = datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise DomainValidationError("utc_date", str(exc)) from exc
        return cls(parsed)

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

    def __post_init__(self) -> None:
        _require_positive_int("max_attempts", self.max_attempts)
        if isinstance(self.attempts_used, bool) or not isinstance(self.attempts_used, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise DomainValidationError("attempts_used", "must be int")
        if self.attempts_used < 0 or self.attempts_used >= self.max_attempts:
            raise DomainValidationError("attempts_used", "must satisfy 0 <= attempts_used < max_attempts")


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
    raw_task_id = raw.get("task_id")
    raw_tenant_id = raw.get("tenant_id")
    raw_date = raw.get("scheduled_for")
    raw_max_attempts = raw.get("max_attempts")

    if not isinstance(raw_task_id, str):
        raise DomainValidationError("task_id", "missing or non-string task_id")
    if not isinstance(raw_tenant_id, str):
        raise DomainValidationError("tenant_id", "missing or non-string tenant_id")
    if not isinstance(raw_date, str):
        raise DomainValidationError("scheduled_for", "missing or non-string scheduled_for")

    return QueuedTask(
        task_id=TaskId.parse(raw_task_id),
        tenant_id=TenantId.parse(raw_tenant_id),
        scheduled_for=UtcDate.parse(raw_date),
        max_attempts=_require_positive_int("max_attempts", raw_max_attempts),
    )


def lease_task(task: TaskRecord, *, worker_id: str, lease_token: int) -> LeasedTask:
    if not isinstance(task, QueuedTask):
        raise InvalidTransitionError(f"cannot lease task in state {type(task).__name__}")
    valid_worker = _require_non_blank_str("worker_id", worker_id)
    valid_token = _require_positive_int("lease_token", lease_token)
    return LeasedTask(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        scheduled_for=task.scheduled_for,
        max_attempts=task.max_attempts,
        attempt_no=task.attempts_used + 1,
        worker_id=valid_worker,
        lease_token=valid_token,
    )


def complete_task(task: TaskRecord, *, lease_token: int, output_summary: str) -> SucceededTask:
    if not isinstance(task, LeasedTask):
        raise InvalidTransitionError(f"cannot complete task in state {type(task).__name__}")
    valid_token = _require_positive_int("lease_token", lease_token)
    if task.lease_token != valid_token:
        raise StaleLeaseError(f"expected lease_token {task.lease_token}, got {valid_token}")
    valid_summary = _require_non_blank_str("output_summary", output_summary)
    return SucceededTask(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        scheduled_for=task.scheduled_for,
        attempt_no=task.attempt_no,
        worker_id=task.worker_id,
        output_summary=valid_summary,
    )


def fail_task(
    task: TaskRecord,
    *,
    lease_token: int,
    error_reason: str,
    fatal: bool = False,
) -> RetryableFailedTask | DeadLetterTask:
    if not isinstance(task, LeasedTask):
        raise InvalidTransitionError(f"cannot fail task in state {type(task).__name__}")
    valid_token = _require_positive_int("lease_token", lease_token)
    if task.lease_token != valid_token:
        raise StaleLeaseError(f"expected lease_token {task.lease_token}, got {valid_token}")
    valid_reason = _require_non_blank_str("error_reason", error_reason)

    if fatal or task.attempt_no >= task.max_attempts:
        return DeadLetterTask(
            task_id=task.task_id,
            tenant_id=task.tenant_id,
            scheduled_for=task.scheduled_for,
            attempts_used=task.attempt_no,
            failure_reason=valid_reason,
            fatal=fatal,
        )
    return RetryableFailedTask(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        scheduled_for=task.scheduled_for,
        max_attempts=task.max_attempts,
        attempts_used=task.attempt_no,
        error_reason=valid_reason,
    )


def requeue_task(task: TaskRecord) -> QueuedTask:
    if not isinstance(task, RetryableFailedTask):
        raise InvalidTransitionError(f"cannot requeue task in state {type(task).__name__}")
    return QueuedTask(
        task_id=task.task_id,
        tenant_id=task.tenant_id,
        scheduled_for=task.scheduled_for,
        max_attempts=task.max_attempts,
        attempts_used=task.attempts_used,
        last_error=task.error_reason,
    )
