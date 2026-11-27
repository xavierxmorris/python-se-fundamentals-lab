"""Reference learner test suite for M08 Drill A (kills 100% of seeded_bugs_a mutants)."""

import asyncio
import contextlib
import hashlib

import pytest

from drill_a_core import offload_blocking_digest, run_bounded_batch


def test_preserves_input_order_under_inverted_completion_times() -> None:
    async def _scenario() -> None:
        schedule = [(0, 0.04), (1, 0.005), (2, 0.025), (3, 0.001)]

        async def worker(entry: tuple[int, float]) -> str:
            idx, delay = entry
            await asyncio.sleep(delay)
            return f"slot-{idx}"

        out = await run_bounded_batch(
            schedule,
            worker,
            max_concurrency=4,
            per_item_timeout=1.0,
        )
        assert out == ["slot-0", "slot-1", "slot-2", "slot-3"]

    asyncio.run(_scenario())


def test_respects_max_concurrency_high_water_mark_and_validates_args() -> None:
    async def _scenario() -> None:
        active = 0
        max_seen = 0

        async def worker(n: int) -> int:
            nonlocal active, max_seen
            active += 1
            max_seen = max(max_seen, active)
            try:
                await asyncio.sleep(0.02)
                return n + 100
            finally:
                active -= 1

        res = await run_bounded_batch(
            list(range(8)),
            worker,
            max_concurrency=2,
            per_item_timeout=1.0,
        )
        assert res == [n + 100 for n in range(8)]
        assert max_seen == 2
        assert active == 0

        with pytest.raises(ValueError):
            await run_bounded_batch([1], worker, max_concurrency=0, per_item_timeout=1.0)
        with pytest.raises(ValueError):
            await run_bounded_batch([1], worker, max_concurrency=1, per_item_timeout=0.0)

    asyncio.run(_scenario())


def test_propagates_cancelled_error_and_cancels_siblings_without_leaks() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        started = asyncio.Event()
        cleaned_up = 0

        async def slow_worker(item: int) -> int:
            nonlocal cleaned_up
            started.set()
            try:
                await asyncio.sleep(1.0)
                return item
            finally:
                cleaned_up += 1

        task = asyncio.create_task(
            run_bounded_batch(
                [1, 2, 3, 4],
                slow_worker,
                max_concurrency=2,
                per_item_timeout=2.0,
            )
        )
        wait_started = asyncio.create_task(started.wait())
        async with asyncio.timeout(1.0):
            await asyncio.wait({task, wait_started}, return_when=asyncio.FIRST_COMPLETED)
        if not wait_started.done():
            wait_started.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_started
        if task.done():
            await task
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert set(asyncio.all_tasks()) == baseline
        assert cleaned_up >= 1

    asyncio.run(_scenario())


def test_worker_failure_and_per_item_timeout_raise_exception_group_cleanly() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())

        async def failing(item: int) -> int:
            if item == 0:
                raise ValueError("bad-item")
            await asyncio.sleep(0.3)
            return item

        with pytest.raises(ExceptionGroup) as err_info:
            await run_bounded_batch(
                [0, 1, 2],
                failing,
                max_concurrency=3,
                per_item_timeout=1.0,
            )
        assert any(isinstance(e, ValueError) for e in err_info.value.exceptions)
        assert set(asyncio.all_tasks()) == baseline

        async def sleepy(item: int) -> int:
            await asyncio.sleep(0.2)
            return item

        with pytest.raises(ExceptionGroup) as timeout_info:
            await run_bounded_batch(
                [1],
                sleepy,
                max_concurrency=1,
                per_item_timeout=0.02,
            )
        assert any(isinstance(e, TimeoutError) for e in timeout_info.value.exceptions)
        assert set(asyncio.all_tasks()) == baseline

    asyncio.run(_scenario())


def test_offload_blocking_digest_keeps_2ms_ticker_running_off_loop() -> None:
    async def _scenario() -> None:
        payload = b"m08-learner-ticker-payload"
        iterations = 100_000
        expected = hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()

        ticks = 0
        running = True

        async def ticker_2ms() -> None:
            nonlocal ticks
            while running:
                await asyncio.sleep(0.002)
                if running:
                    ticks += 1

        ticker = asyncio.create_task(ticker_2ms())
        await asyncio.sleep(0)
        try:
            digest = await offload_blocking_digest(payload, iterations=iterations)
        finally:
            running = False
            await ticker

        assert digest == expected
        assert ticks >= 2

    asyncio.run(_scenario())
