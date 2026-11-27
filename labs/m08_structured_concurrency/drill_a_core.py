"""M08 Drill A (Cold-Turkey Core): Bounded Structured Concurrency & Thread Offloading.

Implement the following public surface without reading acceptance tests:

1. `async def run_bounded_batch[T, R](
       items: Sequence[T],
       worker: Callable[[T], Awaitable[R]],
       *,
       max_concurrency: int,
       per_item_timeout: float,
   ) -> list[R]`:
   - Validates `max_concurrency >= 1` (`bool` rejected) and `per_item_timeout > 0`
     (`bool` and `NaN` rejected), raising `ValueError` otherwise.
   - Returns `[]` when `items` is empty (after validating parameters).
   - Preserves the exact input order of `items` in the returned `list[R]`, regardless of
     the order in which individual `worker(item)` coroutines complete.
   - Limits active concurrent `worker` executions to `<= max_concurrency` using
     `asyncio.Semaphore(max_concurrency)`.
   - Applies `async with asyncio.timeout(per_item_timeout):` INSIDE the semaphore
     acquisition around `await worker(item)` (waiting for a semaphore slot does not burn
     the item's execution timeout).
   - Orchestrates child tasks inside `async with asyncio.TaskGroup() as tg:` so that if
     any worker raises an exception (or times out) or the caller cancels
     `run_bounded_batch` externally, all sibling tasks are cancelled and awaited cleanly
     with zero leaked background tasks, and `asyncio.CancelledError` is never swallowed.

2. `async def offload_blocking_digest(payload: bytes, *, iterations: int = 25_000) -> str`:
   - Validates `iterations >= 1` (`bool` rejected), raising `ValueError` otherwise.
   - Uses `await asyncio.to_thread(...)` to compute
     `hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()` off the
     event loop thread so concurrent tasks/heartbeats keep ticking smoothly while hashing.
"""

from collections.abc import Awaitable, Callable, Sequence


async def run_bounded_batch[T, R](
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    max_concurrency: int,
    per_item_timeout: float,
) -> list[R]:
    """Execute `worker` across `items` with bounded concurrency, deadlines, and TaskGroup cleanup."""
    raise NotImplementedError("Implement run_bounded_batch in drill_a_core.py")


async def offload_blocking_digest(payload: bytes, *, iterations: int = 25_000) -> str:
    """Compute iterative PBKDF2-HMAC-SHA256 hex digest off the event loop via asyncio.to_thread."""
    raise NotImplementedError("Implement offload_blocking_digest in drill_a_core.py")
