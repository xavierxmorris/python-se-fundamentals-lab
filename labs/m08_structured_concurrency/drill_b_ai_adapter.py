"""M08 Drill B (Spec-First AI Pair): AsyncToolPump Remediation.

This AI-generated `AsyncToolPump` contains classic concurrency anti-patterns:
- Spawns raw `asyncio.create_task(...)` coroutines without `asyncio.TaskGroup`, leaking
  running orphan tasks when an earlier tool invocation raises an error.
- Ignores `max_concurrency` backpressure when fanning out tool calls.
- Calls blocking `time.sleep(...)` on the event loop thread instead of `await asyncio.sleep(...)`.
- Catches `BaseException`, swallowing `asyncio.CancelledError` and leaving `in_flight_count`
  corrupted when cancelled or failing.
"""

import asyncio
import math
import time
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

        async def _execute(call: ToolCall) -> ToolResult:
            self._in_flight += 1
            if self._throttle_delay > 0:
                time.sleep(self._throttle_delay)
            output = await self._invoker.invoke(call)
            self._in_flight -= 1
            self._completed += 1
            return ToolResult(call_id=call.call_id, output=output)

        spawned = [asyncio.create_task(_execute(call)) for call in calls]
        results: list[ToolResult] = []
        try:
            for task in spawned:
                results.append(await task)
        except BaseException:
            return results
        return results
