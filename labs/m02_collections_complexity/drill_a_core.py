"""M02 Drill A (Cold-Turkey Core, AI OFF): Collections, Complexity & Slots Memory Layout.

Behavioral Contract
-------------------
1. `CompactEvent`: `@dataclass(slots=True, frozen=True)` with fields:
   - `event_id: str`
   - `tenant: str`
   - `duration_ms: float`
   - `timestamp_sec: float`

2. `PriorityReadyQueue[T]`:
   - `push(priority: int, item: T) -> None`: min-heap enqueue (`TypeError` if `priority` is `bool` or not `int`).
   - `pop() -> T`: pop lowest `priority`; ties broken in strict FIFO insertion order without comparing `item`s. Raise `IndexError` if empty.
   - `peek() -> T`: return next item to pop without removing it. Raise `IndexError` if empty.
   - `__len__() -> int`

3. `SlidingWindowQuota(max_events: int, window_sec: float)`:
   - Raise `ValueError` if `max_events < 1` or `window_sec <= 0`.
   - `allow(tenant: str, now_sec: float) -> bool`: per-tenant `deque` tracking timestamps in `(now_sec - window_sec, now_sec]`.
     Timestamps with `ts <= now_sec - window_sec` are expired and pruned. If remaining `< max_events`, append `now_sec` and return `True`; else `False`.
   - `active_count(tenant: str, now_sec: float) -> int`: prune expired timestamps for `tenant` and return active count.

4. `SlaBucketTable(tiers: Sequence[tuple[float, str]], overflow_label: str = "breach")`:
   - Raise `ValueError` if `tiers` is empty, any threshold `<= 0`, or thresholds are not strictly increasing.
   - `classify(duration_ms: float) -> str`: raise `ValueError` if `duration_ms < 0`; use `bisect_left` so `duration_ms <= threshold` matches that tier, else `overflow_label`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CompactEvent:
    """Memory-compact immutable execution audit record (no per-instance __dict__)."""

    event_id: str
    tenant: str
    duration_ms: float
    timestamp_sec: float


class PriorityReadyQueue[T]:
    """Min-priority queue with strict FIFO tie-breaking for arbitrary unorderable payloads."""

    def __init__(self) -> None:
        raise NotImplementedError("Implement PriorityReadyQueue.__init__")

    def push(self, priority: int, item: T) -> None:
        raise NotImplementedError("Implement PriorityReadyQueue.push")

    def pop(self) -> T:
        raise NotImplementedError("Implement PriorityReadyQueue.pop")

    def peek(self) -> T:
        raise NotImplementedError("Implement PriorityReadyQueue.peek")

    def __len__(self) -> int:
        raise NotImplementedError("Implement PriorityReadyQueue.__len__")


class SlidingWindowQuota:
    """Amortized O(1) per-tenant sliding-window rate limiter backed by collections.deque."""

    def __init__(self, max_events: int, window_sec: float) -> None:
        raise NotImplementedError("Implement SlidingWindowQuota.__init__")

    def allow(self, tenant: str, now_sec: float) -> bool:
        raise NotImplementedError("Implement SlidingWindowQuota.allow")

    def active_count(self, tenant: str, now_sec: float) -> int:
        raise NotImplementedError("Implement SlidingWindowQuota.active_count")


class SlaBucketTable:
    """O(log k) latency tier classifier backed by bisect."""

    def __init__(self, tiers: Sequence[tuple[float, str]], overflow_label: str = "breach") -> None:
        raise NotImplementedError("Implement SlaBucketTable.__init__")

    def classify(self, duration_ms: float) -> str:
        raise NotImplementedError("Implement SlaBucketTable.classify")
