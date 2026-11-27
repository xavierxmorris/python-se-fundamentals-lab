"""Frozen acceptance suite for M08 Drill A (Structured Concurrency & Offloading)."""

import asyncio
import contextlib
import hashlib
from collections.abc import Sequence

import pytest

from drill_a_core import offload_blocking_digest, run_bounded_batch


def test_preserves_input_order_when_workers_finish_out_of_order() -> None:
    async def _scenario() -> None:
        delays = [0.045, 0.005, 0.025, 0.001, 0.015]

        async def worker(pair: tuple[int, float]) -> str:
            idx, delay = pair
            await asyncio.sleep(delay)
            return f"item-{idx}"

        pairs = list(enumerate(delays))
        result = await run_bounded_batch(
            pairs,
            worker,
            max_concurrency=5,
            per_item_timeout=1.0,
        )
        assert result == [f"item-{i}" for i in range(len(delays))]

    asyncio.run(_scenario())


def test_enforces_max_concurrency_backpressure_ceiling() -> None:
    async def _scenario() -> None:
        active = 0
        peak_active = 0

        async def worker(val: int) -> int:
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            try:
                await asyncio.sleep(0.02)
                return val * 10
            finally:
                active -= 1

        items = list(range(9))
        out = await run_bounded_batch(
            items,
            worker,
            max_concurrency=3,
            per_item_timeout=1.0,
        )
        assert out == [x * 10 for x in items]
        assert active == 0
        assert 2 <= peak_active <= 3

    asyncio.run(_scenario())


def test_timeout_applied_inside_semaphore_acquisition() -> None:
    async def _scenario() -> None:
        async def worker(val: int) -> int:
            await asyncio.sleep(0.025)
            return val + 1

        # 3 serialized items take ~0.075s wall time, each individually < 0.06s timeout
        result = await run_bounded_batch(
            [10, 20, 30],
            worker,
            max_concurrency=1,
            per_item_timeout=0.06,
        )
        assert result == [11, 21, 31]

    asyncio.run(_scenario())


def test_per_item_timeout_cancels_siblings_and_leaves_zero_leaked_tasks() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        cleaned_up: list[int] = []

        async def worker(idx: int) -> int:
            try:
                if idx == 1:
                    await asyncio.sleep(0.5)
                else:
                    await asyncio.sleep(0.25)
                return idx
            finally:
                cleaned_up.append(idx)

        with pytest.raises(ExceptionGroup) as exc_info:
            await run_bounded_batch(
                [0, 1, 2],
                worker,
                max_concurrency=3,
                per_item_timeout=0.03,
            )
        assert any(isinstance(err, TimeoutError) for err in exc_info.value.exceptions)
        remaining = set(asyncio.all_tasks()) - baseline
        for leaked in remaining:
            leaked.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        assert not remaining
        assert sorted(cleaned_up) == [0, 1, 2]

    asyncio.run(_scenario())


def test_worker_failure_cancels_siblings_and_leaks_zero_tasks() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        cancelled_siblings: list[int] = []

        async def worker(idx: int) -> int:
            if idx == 2:
                await asyncio.sleep(0.01)
                raise RuntimeError("worker-2-boom")
            try:
                await asyncio.sleep(0.4)
                return idx
            except asyncio.CancelledError:
                cancelled_siblings.append(idx)
                raise

        with pytest.raises(ExceptionGroup) as exc_info:
            await run_bounded_batch(
                [0, 1, 2, 3],
                worker,
                max_concurrency=4,
                per_item_timeout=1.0,
            )
        assert any(isinstance(err, RuntimeError) for err in exc_info.value.exceptions)
        remaining = set(asyncio.all_tasks()) - baseline
        for leaked in remaining:
            leaked.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        assert not remaining
        assert sorted(cancelled_siblings) == [0, 1, 3]

    asyncio.run(_scenario())


def test_external_cancellation_propagates_cancelled_error_without_leaks() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        entered = asyncio.Event()
        cleaned = 0

        async def slow_worker(val: int) -> int:
            nonlocal cleaned
            entered.set()
            try:
                await asyncio.sleep(1.0)
                return val
            finally:
                cleaned += 1

        batch_task = asyncio.create_task(
            run_bounded_batch(
                [1, 2, 3],
                slow_worker,
                max_concurrency=2,
                per_item_timeout=2.0,
            )
        )
        wait_entered = asyncio.create_task(entered.wait())
        async with asyncio.timeout(1.0):
            await asyncio.wait({batch_task, wait_entered}, return_when=asyncio.FIRST_COMPLETED)
        if not wait_entered.done():
            wait_entered.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_entered
        if batch_task.done():
            await batch_task
        batch_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await batch_task

        remaining = set(asyncio.all_tasks()) - baseline
        for leaked in remaining:
            leaked.cancel()
        if remaining:
            await asyncio.gather(*remaining, return_exceptions=True)
        assert not remaining
        assert cleaned >= 1

    asyncio.run(_scenario())


def test_parameter_validation_and_empty_batch() -> None:
    async def _noop(x: int) -> int:
        return x

    async def _scenario() -> None:
        empty: Sequence[int] = ()
        assert await run_bounded_batch(empty, _noop, max_concurrency=2, per_item_timeout=0.5) == []

        for bad_conc in (0, -1, True, False):
            with pytest.raises(ValueError):
                await run_bounded_batch([1], _noop, max_concurrency=bad_conc, per_item_timeout=0.5)

        for bad_timeout in (0.0, -0.5, float("nan"), True, False):
            with pytest.raises(ValueError):
                await run_bounded_batch([1], _noop, max_concurrency=1, per_item_timeout=bad_timeout)

        for bad_iters in (0, -10, True):
            with pytest.raises(ValueError):
                await offload_blocking_digest(b"abc", iterations=bad_iters)

    asyncio.run(_scenario())


def test_offload_blocking_digest_correctness_and_event_loop_liveness() -> None:
    async def _scenario() -> None:
        payload = b"taskledger-structured-concurrency"
        iterations = 100_000
        expected = hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()

        ticks = 0
        digest_running = True

        async def heartbeat() -> None:
            nonlocal ticks
            while digest_running:
                await asyncio.sleep(0.002)
                if digest_running:
                    ticks += 1

        ticker_task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0)
        try:
            actual = await offload_blocking_digest(payload, iterations=iterations)
        finally:
            digest_running = False
            await ticker_task

        assert actual == expected
        assert ticks >= 2

    asyncio.run(_scenario())
