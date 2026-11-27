"""Frozen acceptance suite for M08 Drill B (AsyncToolPump Structured Concurrency)."""

import asyncio
import contextlib
import time

import pytest

from drill_b_ai_adapter import AsyncToolInvoker, AsyncToolPump, ToolCall, ToolResult


class _TrackingInvoker:
    def __init__(self, delays: dict[str, float], fail_ids: set[str] | None = None) -> None:
        self._delays = delays
        self._fail_ids = fail_ids or set()
        self.active = 0
        self.peak_active = 0
        self.entered = asyncio.Event()
        self.cancelled_ids: list[str] = []

    async def invoke(self, call: ToolCall) -> str:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.entered.set()
        try:
            await asyncio.sleep(self._delays.get(call.call_id, 0.01))
            if call.call_id in self._fail_ids:
                raise RuntimeError(f"tool failure on {call.call_id}")
            return f"{call.tool_name}:{call.payload}"
        except asyncio.CancelledError:
            self.cancelled_ids.append(call.call_id)
            raise
        finally:
            self.active -= 1


def test_pump_batch_enforces_backpressure_and_preserves_order() -> None:
    async def _scenario() -> None:
        calls = [
            ToolCall(call_id=f"c-{i}", tool_name="echo", payload=f"p-{i}")
            for i in range(6)
        ]
        delays = {
            "c-0": 0.035,
            "c-1": 0.010,
            "c-2": 0.030,
            "c-3": 0.005,
            "c-4": 0.025,
            "c-5": 0.005,
        }
        invoker = _TrackingInvoker(delays)
        assert isinstance(invoker, AsyncToolInvoker)
        pump = AsyncToolPump(invoker, max_concurrency=2)

        results = await pump.pump_batch(calls, per_call_timeout=1.0)
        assert results == [
            ToolResult(call_id=f"c-{i}", output=f"echo:p-{i}") for i in range(6)
        ]
        assert 1 <= invoker.peak_active <= 2
        assert pump.in_flight_count == 0
        assert pump.completed_count == 6

    asyncio.run(_scenario())


def test_pump_batch_failure_cancels_siblings_without_orphan_tasks() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        calls = [
            ToolCall(call_id="c-0", tool_name="op", payload="fail-fast"),
            ToolCall(call_id="c-1", tool_name="op", payload="slow-sibling"),
            ToolCall(call_id="c-2", tool_name="op", payload="slow-sibling-2"),
        ]
        invoker = _TrackingInvoker(
            {"c-0": 0.01, "c-1": 0.4, "c-2": 0.4},
            fail_ids={"c-0"},
        )
        pump = AsyncToolPump(invoker, max_concurrency=3)

        raised_group = False
        try:
            await pump.pump_batch(calls, per_call_timeout=1.0)
        except ExceptionGroup as eg:
            raised_group = any(isinstance(e, RuntimeError) for e in eg.exceptions)

        leaked = set(asyncio.all_tasks()) - baseline
        for task in leaked:
            task.cancel()
        if leaked:
            await asyncio.gather(*leaked, return_exceptions=True)

        assert raised_group, "pump_batch must propagate tool failure via TaskGroup ExceptionGroup"
        assert not leaked, f"pump_batch leaked {len(leaked)} orphan task(s)"
        assert pump.in_flight_count == 0
        assert sorted(invoker.cancelled_ids) == ["c-1", "c-2"]

    asyncio.run(_scenario())


def test_pump_batch_propagates_cancelled_error_and_cleans_up_in_flight() -> None:
    async def _scenario() -> None:
        baseline = set(asyncio.all_tasks())
        calls = [
            ToolCall(call_id="c-1", tool_name="op", payload="1"),
            ToolCall(call_id="c-2", tool_name="op", payload="2"),
        ]
        invoker = _TrackingInvoker({"c-1": 1.0, "c-2": 1.0})
        pump = AsyncToolPump(invoker, max_concurrency=2)

        batch_task = asyncio.create_task(pump.pump_batch(calls, per_call_timeout=2.0))
        wait_entered = asyncio.create_task(invoker.entered.wait())
        async with asyncio.timeout(1.0):
            await asyncio.wait({batch_task, wait_entered}, return_when=asyncio.FIRST_COMPLETED)
        if not wait_entered.done():
            wait_entered.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_entered
        if batch_task.done():
            await batch_task
        batch_task.cancel()

        propagated_cancel = False
        try:
            await batch_task
        except asyncio.CancelledError:
            propagated_cancel = True

        leaked = set(asyncio.all_tasks()) - baseline
        for task in leaked:
            task.cancel()
        if leaked:
            await asyncio.gather(*leaked, return_exceptions=True)

        assert propagated_cancel, "pump_batch must re-raise asyncio.CancelledError"
        assert not leaked
        assert pump.in_flight_count == 0

    asyncio.run(_scenario())


def test_throttle_delay_uses_non_blocking_async_sleep() -> None:
    async def _scenario() -> None:
        calls = [
            ToolCall(call_id=f"t-{i}", tool_name="ping", payload=str(i))
            for i in range(4)
        ]
        invoker = _TrackingInvoker({f"t-{i}": 0.005 for i in range(4)})
        pump = AsyncToolPump(invoker, max_concurrency=4, throttle_delay=0.06)

        ticks = 0
        running = True

        async def ticker() -> None:
            nonlocal ticks
            while running:
                await asyncio.sleep(0.002)
                if running:
                    ticks += 1

        ticker_task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        start = time.perf_counter()
        try:
            results = await pump.pump_batch(calls, per_call_timeout=1.0)
        finally:
            elapsed = time.perf_counter() - start
            running = False
            await ticker_task

        assert len(results) == 4
        assert elapsed < 0.18, f"throttle_delay serialized/blocked loop (elapsed={elapsed:.3f}s)"
        assert ticks >= 2, "throttle_delay blocked the event loop instead of using asyncio.sleep"

    asyncio.run(_scenario())


def test_per_call_timeout_and_argument_validation() -> None:
    async def _scenario() -> None:
        invoker = _TrackingInvoker({"slow": 0.4})
        with pytest.raises(ValueError):
            AsyncToolPump(invoker, max_concurrency=0)
        with pytest.raises(ValueError):
            AsyncToolPump(invoker, throttle_delay=-0.1)

        pump = AsyncToolPump(invoker, max_concurrency=2)
        with pytest.raises(ValueError):
            await pump.pump_batch([], per_call_timeout=0.0)

        with pytest.raises(ExceptionGroup) as exc_info:
            await pump.pump_batch(
                [ToolCall(call_id="slow", tool_name="hang", payload="x")],
                per_call_timeout=0.02,
            )
        assert any(isinstance(e, TimeoutError) for e in exc_info.value.exceptions)
        assert pump.in_flight_count == 0

    asyncio.run(_scenario())
