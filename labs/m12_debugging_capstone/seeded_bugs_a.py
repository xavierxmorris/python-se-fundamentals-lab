"""Seeded mutants re-introducing each of M12's 4 incident root causes individually."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from types import ModuleType
from typing import TypeIs

from drill_a_core import (
    IdempotencyConflictError,
    StaleFenceError,
    TaskLedgerEngine,
    TaskSnapshot,
)


def _is_mutable_str_dict(val: Mapping[str, str]) -> TypeIs[dict[str, str]]:
    return isinstance(val, dict)


def _bug_1_duplicate_replay_tool_call(mod: ModuleType) -> None:
    """Bug 1: Invokes `prepare_tool` before checking existing `request_id` record."""

    class _Bug1Engine(TaskLedgerEngine):
        def submit_idempotent(
            self,
            *,
            request_id: str,
            tenant: str,
            payload: Mapping[str, object],
            prepare_tool: Callable[[Mapping[str, object]], str] | None = None,
            metadata: Mapping[str, str] | None = None,
            max_attempts: int | None = None,
        ) -> TaskSnapshot:
            if not request_id.strip() or not tenant.strip():
                raise ValueError("request_id and tenant must be non-empty")
            canonical_payload = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
            eff_max = self._max_attempts_default if max_attempts is None else max_attempts
            prepared_ref = prepare_tool(dict(payload)) if prepare_tool is not None else None
            meta = dict(self._default_metadata) if metadata is None else dict(metadata)
            meta.setdefault("origin_tenant", tenant)
            meta["last_request_id"] = request_id
            if prepared_ref is not None:
                meta["prepared_ref"] = prepared_ref

            self.connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self.connection.execute(
                    "SELECT task_id, tenant, payload_json FROM tasks WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing[1]) != tenant or str(existing[2]) != canonical_payload:
                        raise IdempotencyConflictError(f"Conflicting replay for {request_id!r}")
                    self.connection.execute(
                        "UPDATE tasks SET replayed_count = replayed_count + 1 "
                        "WHERE request_id = ?",
                        (request_id,),
                    )
                    self.connection.execute("COMMIT")
                    return self.get_task(str(existing[0]))

                task_id = f"tsk-{uuid.uuid4().hex[:12]}"
                meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"))
                self.connection.execute(
                    "INSERT INTO tasks (task_id, request_id, tenant, payload_json, metadata_json, "
                    "status, max_attempts) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                    (task_id, request_id, tenant, canonical_payload, meta_json, eff_max),
                )
                self.connection.execute("COMMIT")
                return self.get_task(task_id)
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    mod.__dict__["TaskLedgerEngine"] = _Bug1Engine


def _bug_2_shared_mutable_metadata(mod: ModuleType) -> None:
    """Bug 2: Shares `self._default_metadata` and mutates caller `metadata` across submissions."""

    class _Bug2Engine(TaskLedgerEngine):
        def submit_idempotent(
            self,
            *,
            request_id: str,
            tenant: str,
            payload: Mapping[str, object],
            prepare_tool: Callable[[Mapping[str, object]], str] | None = None,
            metadata: Mapping[str, str] | None = None,
            max_attempts: int | None = None,
        ) -> TaskSnapshot:
            if not request_id.strip() or not tenant.strip():
                raise ValueError("request_id and tenant must be non-empty")
            canonical_payload = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
            eff_max = self._max_attempts_default if max_attempts is None else max_attempts

            self.connection.execute("BEGIN IMMEDIATE")
            try:
                existing = self.connection.execute(
                    "SELECT task_id, tenant, payload_json FROM tasks WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing[1]) != tenant or str(existing[2]) != canonical_payload:
                        raise IdempotencyConflictError(f"Conflicting replay for {request_id!r}")
                    self.connection.execute(
                        "UPDATE tasks SET replayed_count = replayed_count + 1 "
                        "WHERE request_id = ?",
                        (request_id,),
                    )
                    self.connection.execute("COMMIT")
                    return self.get_task(str(existing[0]))

                if metadata is None:
                    meta = self._default_metadata
                else:
                    meta = metadata if _is_mutable_str_dict(metadata) else dict(metadata)
                meta.setdefault("origin_tenant", tenant)
                meta["last_request_id"] = request_id
                if prepare_tool is not None:
                    meta["prepared_ref"] = prepare_tool(dict(payload))

                task_id = f"tsk-{uuid.uuid4().hex[:12]}"
                meta_json = json.dumps(meta, sort_keys=True, separators=(",", ":"))
                self.connection.execute(
                    "INSERT INTO tasks (task_id, request_id, tenant, payload_json, metadata_json, "
                    "status, max_attempts) VALUES (?, ?, ?, ?, ?, 'queued', ?)",
                    (task_id, request_id, tenant, canonical_payload, meta_json, eff_max),
                )
                self.connection.execute("COMMIT")
                return self.get_task(task_id)
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    mod.__dict__["TaskLedgerEngine"] = _Bug2Engine


def _bug_3_swallowed_cancelled_error(mod: ModuleType) -> None:
    """Bug 3: Catches `BaseException` inside worker, swallowing `asyncio.CancelledError`."""

    class _Bug3Engine(TaskLedgerEngine):
        async def execute_leased_task(
            self,
            leased: TaskSnapshot,
            handler: Callable[[TaskSnapshot], Awaitable[str]],
            *,
            task_timeout: float = 1.0,
        ) -> TaskSnapshot:
            try:
                with self.start_span("task.execute", task_id=leased.task_id, tenant=leased.tenant):
                    async with asyncio.timeout(task_timeout):
                        out = await handler(leased)
            except BaseException as exc:
                return self.fail_lease(
                    leased.task_id,
                    fence_token=leased.fence_token,
                    error=f"{type(exc).__name__}: {exc}",
                )
            return self.complete_lease(
                leased.task_id, fence_token=leased.fence_token, result=out
            )

    mod.__dict__["TaskLedgerEngine"] = _Bug3Engine


def _bug_4_missing_fence_token_check(mod: ModuleType) -> None:
    """Bug 4: `complete_lease` omits `AND status = 'leased' AND fence_token = ?`."""

    class _Bug4Engine(TaskLedgerEngine):
        def complete_lease(
            self, task_id: str, *, fence_token: int, result: str
        ) -> TaskSnapshot:
            _ = fence_token
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                cur = self.connection.execute(
                    "UPDATE tasks SET status = 'succeeded', result = ?, last_error = NULL, "
                    "lease_owner = NULL WHERE task_id = ?",
                    (result, task_id),
                )
                if cur.rowcount != 1:
                    raise StaleFenceError(f"Unknown task {task_id!r}")
                self.connection.execute("COMMIT")
                return self.get_task(task_id)
            except BaseException:
                if self.connection.in_transaction:
                    self.connection.execute("ROLLBACK")
                raise

    mod.__dict__["TaskLedgerEngine"] = _Bug4Engine


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_1_duplicate_replay_tool_call": _bug_1_duplicate_replay_tool_call,
    "bug_2_shared_mutable_metadata": _bug_2_shared_mutable_metadata,
    "bug_3_swallowed_cancelled_error": _bug_3_swallowed_cancelled_error,
    "bug_4_missing_fence_token_check": _bug_4_missing_fence_token_check,
}
