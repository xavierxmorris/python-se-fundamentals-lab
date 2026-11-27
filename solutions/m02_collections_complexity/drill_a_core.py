"""Reference solution for M02 Drill A: Collections, Complexity & Slots Memory Layout."""

from __future__ import annotations

import bisect
import heapq
from collections import deque
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
        self._heap: list[tuple[int, int, T]] = []
        self._seq: int = 0

    def push(self, priority: int, item: T) -> None:
        if isinstance(priority, bool) or not isinstance(priority, int):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError("priority must be an int (not bool)")
        heapq.heappush(self._heap, (priority, self._seq, item))
        self._seq += 1

    def pop(self) -> T:
        if not self._heap:
            raise IndexError("pop from an empty PriorityReadyQueue")
        _, _, item = heapq.heappop(self._heap)
        return item

    def peek(self) -> T:
        if not self._heap:
            raise IndexError("peek from an empty PriorityReadyQueue")
        return self._heap[0][2]

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)


class SlidingWindowQuota:
    """Amortized O(1) per-tenant sliding-window rate limiter backed by collections.deque."""

    def __init__(self, max_events: int, window_sec: float) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        if window_sec <= 0.0:
            raise ValueError("window_sec must be > 0")
        self._max_events = max_events
        self._window_sec = float(window_sec)
        self._windows: dict[str, deque[float]] = {}

    def _prune(self, q: deque[float], now_sec: float) -> None:
        cutoff = now_sec - self._window_sec
        while q and q[0] <= cutoff:
            q.popleft()

    def allow(self, tenant: str, now_sec: float) -> bool:
        q = self._windows.get(tenant)
        if q is None:
            q = deque[float]()
            self._windows[tenant] = q
        self._prune(q, now_sec)
        if len(q) >= self._max_events:
            return False
        q.append(float(now_sec))
        return True

    def active_count(self, tenant: str, now_sec: float) -> int:
        q = self._windows.get(tenant)
        if q is None:
            return 0
        self._prune(q, now_sec)
        return len(q)


class SlaBucketTable:
    """O(log k) latency tier classifier backed by bisect."""

    def __init__(self, tiers: Sequence[tuple[float, str]], overflow_label: str = "breach") -> None:
        if not tiers:
            raise ValueError("tiers must not be empty")
        thresholds: list[float] = []
        labels: list[str] = []
        prev = 0.0
        for raw_limit, label in tiers:
            limit = float(raw_limit)
            if limit <= 0.0 or limit <= prev:
                raise ValueError("tier thresholds must be strictly positive and strictly increasing")
            if not label:
                raise ValueError("tier label must not be empty")
            thresholds.append(limit)
            labels.append(label)
            prev = limit
        self._thresholds: tuple[float, ...] = tuple(thresholds)
        self._labels: tuple[str, ...] = tuple(labels)
        self._overflow_label = overflow_label

    def classify(self, duration_ms: float) -> str:
        if duration_ms < 0.0:
            raise ValueError("duration_ms must be >= 0")
        idx = bisect.bisect_left(self._thresholds, duration_ms)
        if idx < len(self._labels):
            return self._labels[idx]
        return self._overflow_label
