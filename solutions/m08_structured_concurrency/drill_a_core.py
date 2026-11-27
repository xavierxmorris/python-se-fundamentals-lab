"""Reference solution for M08 Drill A: Bounded Structured Concurrency & Thread Offloading."""

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable, Sequence


def _pbkdf2_sha256_hex(payload: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()


async def run_bounded_batch[T, R](
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    max_concurrency: int,
    per_item_timeout: float,
) -> list[R]:
    """Execute `worker` across `items` with bounded concurrency, deadlines, and TaskGroup cleanup."""
    if isinstance(max_concurrency, bool) or max_concurrency < 1:
        raise ValueError(f"max_concurrency must be >= 1, got {max_concurrency!r}")
    if isinstance(per_item_timeout, bool) or math.isnan(per_item_timeout) or per_item_timeout <= 0:
        raise ValueError(f"per_item_timeout must be > 0, got {per_item_timeout!r}")
    if not items:
        return []

    semaphore = asyncio.Semaphore(max_concurrency)
    results_by_index: dict[int, R] = {}

    async def _run_indexed(index: int, item: T) -> None:
        async with semaphore, asyncio.timeout(per_item_timeout):
            results_by_index[index] = await worker(item)

    async with asyncio.TaskGroup() as tg:
        for index, item in enumerate(items):
            tg.create_task(_run_indexed(index, item))

    return [results_by_index[index] for index in range(len(items))]


async def offload_blocking_digest(payload: bytes, *, iterations: int = 25_000) -> str:
    """Compute iterative PBKDF2-HMAC-SHA256 hex digest off the event loop via asyncio.to_thread."""
    if isinstance(iterations, bool) or iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations!r}")
    return await asyncio.to_thread(_pbkdf2_sha256_hex, payload, iterations)
