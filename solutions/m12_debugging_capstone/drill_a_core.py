"""Reference solution for M12 Drill A (`drill_a_core.py`): Fixed `TaskLedgerEngine`."""

from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
import uuid
from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Self, TypeIs

type TaskStatus = Literal["queued", "leased", "succeeded", "failed", "dead_letter"]
_ACTIVE_SPAN: ContextVar[tuple[str, str] | None] = ContextVar("m12_active_span", default=None)


class LedgerError(Exception):
    """Base exception for `TaskLedgerEngine` invariant violations."""


class IdempotencyConflictError(LedgerError):
    """Raised when `request_id` is replayed with a different tenant or payload."""


class StaleFenceError(LedgerError):
    """Raised when a worker attempts to complete/fail a lease with a stale `fence_token`."""


@dataclass(slots=True, frozen=True)
class SpanEvent:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    status: Literal["ok", "error"]
    attributes: Mapping[str, str | int | bool]


@dataclass(slots=True, frozen=True)
class TaskSnapshot:
    task_id: str
    request_id: str
    tenant: str
    payload: Mapping[str, object]
    metadata: Mapping[str, str]
    status: TaskStatus
    fence_token: int
    attempts: int
    max_attempts: int
    lease_owner: str | None
    result: str | None
    last_error: str | None
    replayed_count: int


def current_span_context() -> tuple[str, str] | None:
    return _ACTIVE_SPAN.get()


def _is_task_status(val: str) -> TypeIs[TaskStatus]:
    return val in ("queued", "leased", "succeeded", "failed", "dead_letter")


def _is_str_object_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


class TaskLedgerEngine:
    """SQLite WAL + bounded `asyncio.TaskGroup` + `ContextVar` traced task execution engine."""

    connection: sqlite3.Connection
    spans: list[SpanEvent]

    def __init__(self, db_path: Path, *, max_attempts_default: int = 3) -> None:
        if max_attempts_default < 1:
            raise ValueError("max_attempts_default must be >= 1")
        self._max_attempts_default = max_attempts_default
        self._default_metadata: dict[str, str] = {"source": "ledger"}
        self.spans = []
        self.connection = sqlite3.connect(str(db_path), isolation_level=None)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS tasks ("
            "task_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, tenant TEXT NOT NULL, "
            "payload_json TEXT NOT NULL, metadata_json TEXT NOT NULL, status TEXT NOT NULL, "
            "fence_token INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, "
            "max_attempts INTEGER NOT NULL DEFAULT 3, lease_owner TEXT, result TEXT, "
            "last_error TEXT, replayed_count INTEGER NOT NULL DEFAULT 0)"
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Generator[None, None, None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.connection.execute("COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    @contextmanager
    def start_span(
        self, name: str, **attrs: str | int | bool
    ) -> Generator[dict[str, str | int | bool], None, None]:
        parent = _ACTIVE_SPAN.get()
        trace_id, parent_id = (secrets.token_hex(16), None) if parent is None else parent
        span_id = secrets.token_hex(8)
        token = _ACTIVE_SPAN.set((trace_id, span_id))
        live_attrs: dict[str, str | int | bool] = dict(attrs)
        status: Literal["ok", "error"] = "ok"
        try:
            yield live_attrs
        except BaseException as exc:
            status = "error"
            live_attrs["error.type"] = type(exc).__name__
            raise
        finally:
            _ACTIVE_SPAN.reset(token)
            self.spans.append(
                SpanEvent(trace_id, span_id, parent_id, name, status, MappingProxyType(dict(live_attrs)))
            )

    def get_task(self, task_id: str) -> TaskSnapshot:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task_id: {task_id!r}")
        raw_p: object = json.loads(str(row[3]))
        raw_m: object = json.loads(str(row[4]))
        p_map = dict(raw_p) if _is_str_object_dict(raw_p) else {}
        m_map = {k: str(v) for k, v in raw_m.items()} if _is_str_object_dict(raw_m) else {}
        st = str(row[5])
        assert _is_task_status(st)
        return TaskSnapshot(
            str(row[0]), str(row[1]), str(row[2]), MappingProxyType(p_map), MappingProxyType(m_map),
            st, int(row[6]), int(row[7]), int(row[8]),
            None if row[9] is None else str(row[9]),
            None if row[10] is None else str(row[10]),
            None if row[11] is None else str(row[11]), int(row[12]),
        )

    def submit_idempotent(
        self, *, request_id: str, tenant: str, payload: Mapping[str, object],
        prepare_tool: Callable[[Mapping[str, object]], str] | None = None,
        metadata: Mapping[str, str] | None = None, max_attempts: int | None = None,
    ) -> TaskSnapshot:
        if not request_id.strip() or not tenant.strip():
            raise ValueError("request_id and tenant must be non-empty")
        payload_copy = dict(payload)
        canonical = json.dumps(payload_copy, sort_keys=True, separators=(",", ":"))
        eff_max = self._max_attempts_default if max_attempts is None else max_attempts
        if eff_max < 1:
            raise ValueError("max_attempts must be >= 1")

        with self._tx():
            existing = self.connection.execute(
                "SELECT task_id, tenant, payload_json FROM tasks WHERE request_id = ?", (request_id,)
            ).fetchone()
            if existing is not None:
                if str(existing[1]) != tenant or str(existing[2]) != canonical:
                    raise IdempotencyConflictError(f"Conflicting replay for {request_id!r}")
                self.connection.execute(
                    "UPDATE tasks SET replayed_count = replayed_count + 1 WHERE request_id = ?",
                    (request_id,),
                )
                tid = str(existing[0])
            else:
                meta: dict[str, str] = (
                    dict(self._default_metadata) if metadata is None else dict(metadata)
                )
                meta.setdefault("origin_tenant", tenant)
                meta["last_request_id"] = request_id
                if prepare_tool is not None:
                    meta["prepared_ref"] = prepare_tool(dict(payload_copy))
                tid = f"tsk-{uuid.uuid4().hex[:12]}"
                meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"))
                self.connection.execute(
                    "INSERT INTO tasks (task_id, request_id, tenant, payload_json, metadata_json, "
                    "status, max_attempts) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                    (tid, request_id, tenant, canonical, meta_json, eff_max),
                )
        return self.get_task(tid)

    def acquire_lease(self, task_id: str, *, worker_id: str) -> TaskSnapshot:
        with self._tx():
            cur = self.connection.execute(
                "UPDATE tasks SET status = 'leased', fence_token = fence_token + 1, "
                "attempts = attempts + 1, lease_owner = ? WHERE task_id = ? "
                "AND status IN ('queued', 'failed', 'leased') AND attempts < max_attempts",
                (worker_id, task_id),
            )
            if cur.rowcount != 1:
                raise LedgerError(f"Task {task_id!r} cannot be leased")
        return self.get_task(task_id)

    def complete_lease(self, task_id: str, *, fence_token: int, result: str) -> TaskSnapshot:
        with self._tx():
            cur = self.connection.execute(
                "UPDATE tasks SET status = 'succeeded', result = ?, last_error = NULL, "
                "lease_owner = NULL WHERE task_id = ? AND status = 'leased' AND fence_token = ?",
                (result, task_id, fence_token),
            )
            if cur.rowcount != 1:
                raise StaleFenceError(f"Stale fence_token={fence_token} for {task_id!r}")
        return self.get_task(task_id)

    def fail_lease(self, task_id: str, *, fence_token: int, error: str) -> TaskSnapshot:
        with self._tx():
            cur = self.connection.execute(
                "UPDATE tasks SET status = CASE WHEN attempts >= max_attempts THEN 'dead_letter' "
                "ELSE 'failed' END, last_error = ?, lease_owner = NULL "
                "WHERE task_id = ? AND status = 'leased' AND fence_token = ?",
                (error, task_id, fence_token),
            )
            if cur.rowcount != 1:
                raise StaleFenceError(f"Stale fence {fence_token} for {task_id!r}")
        return self.get_task(task_id)

    def _claim_runnable(self, *, worker_id: str, tenant: str | None) -> list[TaskSnapshot]:
        sql = "SELECT task_id FROM tasks WHERE status IN ('queued', 'failed') AND attempts < max_attempts"
        params: tuple[str, ...] = (tenant,) if tenant is not None else ()
        if tenant is not None:
            sql += " AND tenant = ?"
        ids = [str(r[0]) for r in self.connection.execute(sql + " ORDER BY rowid ASC", params)]
        return [self.acquire_lease(tid, worker_id=worker_id) for tid in ids]

    async def execute_leased_task(
        self, leased: TaskSnapshot, handler: Callable[[TaskSnapshot], Awaitable[str]],
        *, task_timeout: float = 1.0,
    ) -> TaskSnapshot:
        try:
            with self.start_span("task.execute", task_id=leased.task_id, tenant=leased.tenant):
                async with asyncio.timeout(task_timeout):
                    out = await handler(leased)
        except Exception as exc:
            return self.fail_lease(
                leased.task_id, fence_token=leased.fence_token, error=f"{type(exc).__name__}: {exc}"
            )
        return self.complete_lease(leased.task_id, fence_token=leased.fence_token, result=out)

    async def run_worker_batch(
        self, handler: Callable[[TaskSnapshot], Awaitable[str]], *, worker_id: str = "worker",
        tenant: str | None = None, max_concurrency: int = 4, task_timeout: float = 1.0,
    ) -> list[TaskSnapshot]:
        if max_concurrency < 1 or task_timeout <= 0:
            raise ValueError("max_concurrency >= 1 and task_timeout > 0 required")
        claimed = self._claim_runnable(worker_id=worker_id, tenant=tenant)
        sem = asyncio.Semaphore(max_concurrency)

        async def _guarded(item: TaskSnapshot) -> TaskSnapshot:
            async with sem:
                return await self.execute_leased_task(item, handler, task_timeout=task_timeout)

        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_guarded(item)) for item in claimed]
        return [t.result() for t in tasks]
