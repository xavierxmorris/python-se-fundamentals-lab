"""Seeded realistic mutants for M08 Gate 4 mutation testing."""

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable, Sequence
from types import ModuleType


def _validate_batch_args(max_concurrency: int, per_item_timeout: float) -> None:
    if isinstance(max_concurrency, bool) or max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    if isinstance(per_item_timeout, bool) or math.isnan(per_item_timeout) or per_item_timeout <= 0:
        raise ValueError("per_item_timeout must be > 0")


def _bug_unbounded_concurrency(mod: ModuleType) -> None:
    async def buggy_run_bounded_batch[T, R](
        items: Sequence[T],
        worker: Callable[[T], Awaitable[R]],
        *,
        max_concurrency: int,
        per_item_timeout: float,
    ) -> list[R]:
        _validate_batch_args(max_concurrency, per_item_timeout)
        if not items:
            return []
        results_by_index: dict[int, R] = {}

        async def _run_one(index: int, item: T) -> None:
            async with asyncio.timeout(per_item_timeout):
                results_by_index[index] = await worker(item)

        async with asyncio.TaskGroup() as tg:
            for idx, item in enumerate(items):
                tg.create_task(_run_one(idx, item))

        return [results_by_index[idx] for idx in range(len(items))]

    mod.__dict__["run_bounded_batch"] = buggy_run_bounded_batch


def _bug_completion_order_results(mod: ModuleType) -> None:
    async def buggy_run_bounded_batch[T, R](
        items: Sequence[T],
        worker: Callable[[T], Awaitable[R]],
        *,
        max_concurrency: int,
        per_item_timeout: float,
    ) -> list[R]:
        _validate_batch_args(max_concurrency, per_item_timeout)
        if not items:
            return []
        semaphore = asyncio.Semaphore(max_concurrency)
        completed: list[R] = []

        async def _run_one(item: T) -> None:
            async with semaphore, asyncio.timeout(per_item_timeout):
                completed.append(await worker(item))

        async with asyncio.TaskGroup() as tg:
            for item in items:
                tg.create_task(_run_one(item))

        return completed

    mod.__dict__["run_bounded_batch"] = buggy_run_bounded_batch


def _bug_swallow_cancelled_error(mod: ModuleType) -> None:
    async def buggy_run_bounded_batch[T, R](
        items: Sequence[T],
        worker: Callable[[T], Awaitable[R]],
        *,
        max_concurrency: int,
        per_item_timeout: float,
    ) -> list[R]:
        _validate_batch_args(max_concurrency, per_item_timeout)
        if not items:
            return []
        semaphore = asyncio.Semaphore(max_concurrency)
        results_by_index: dict[int, R] = {}

        async def _run_one(index: int, item: T) -> None:
            async with semaphore, asyncio.timeout(per_item_timeout):
                results_by_index[index] = await worker(item)

        try:
            async with asyncio.TaskGroup() as tg:
                for idx, item in enumerate(items):
                    tg.create_task(_run_one(idx, item))
        except Exception:
            raise
        except BaseException:
            return [results_by_index[idx] for idx in sorted(results_by_index)]

        return [results_by_index[idx] for idx in range(len(items))]

    mod.__dict__["run_bounded_batch"] = buggy_run_bounded_batch


def _bug_sync_blocking_digest(mod: ModuleType) -> None:
    async def buggy_offload_blocking_digest(
        payload: bytes,
        *,
        iterations: int = 25_000,
    ) -> str:
        if isinstance(iterations, bool) or iterations < 1:
            raise ValueError("iterations must be >= 1")
        return hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()

    mod.__dict__["offload_blocking_digest"] = buggy_offload_blocking_digest


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "unbounded_concurrency": _bug_unbounded_concurrency,
    "completion_order_results": _bug_completion_order_results,
    "swallow_cancelled_error": _bug_swallow_cancelled_error,
    "sync_blocking_digest": _bug_sync_blocking_digest,
}
