"""Reference solution for M08 Drill B: Hardened AsyncToolPump."""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(slots=True, frozen=True)
class ToolCall:
    call_id: str
    tool_name: str
    payload: str


@dataclass(slots=True, frozen=True)
class ToolResult:
    call_id: str
    output: str


@runtime_checkable
class AsyncToolInvoker(Protocol):
    async def invoke(self, call: ToolCall) -> str: ...


class AsyncToolPump:
    def __init__(
        self,
        invoker: AsyncToolInvoker,
        *,
        max_concurrency: int = 4,
        throttle_delay: float = 0.0,
    ) -> None:
        if isinstance(max_concurrency, bool) or max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if isinstance(throttle_delay, bool) or math.isnan(throttle_delay) or throttle_delay < 0.0:
            raise ValueError("throttle_delay must be >= 0.0")
        self._invoker = invoker
        self._max_concurrency = max_concurrency
        self._throttle_delay = throttle_delay
        self._in_flight = 0
        self._completed = 0

    @property
    def in_flight_count(self) -> int:
        return self._in_flight

    @property
    def completed_count(self) -> int:
        return self._completed

    async def pump_batch(
        self,
        calls: Sequence[ToolCall],
        *,
        per_call_timeout: float = 5.0,
    ) -> list[ToolResult]:
        if isinstance(per_call_timeout, bool) or math.isnan(per_call_timeout) or per_call_timeout <= 0:
            raise ValueError("per_call_timeout must be > 0")
        if not calls:
            return []

        semaphore = asyncio.Semaphore(self._max_concurrency)
        results_by_index: dict[int, ToolResult] = {}

        async def _execute_indexed(index: int, call: ToolCall) -> None:
            async with semaphore:
                self._in_flight += 1
                try:
                    if self._throttle_delay > 0:
                        await asyncio.sleep(self._throttle_delay)
                    async with asyncio.timeout(per_call_timeout):
                        output = await self._invoker.invoke(call)
                finally:
                    self._in_flight -= 1
                self._completed += 1
                results_by_index[index] = ToolResult(call_id=call.call_id, output=output)

        async with asyncio.TaskGroup() as tg:
            for index, call in enumerate(calls):
                tg.create_task(_execute_indexed(index, call))

        return [results_by_index[index] for index in range(len(calls))]
