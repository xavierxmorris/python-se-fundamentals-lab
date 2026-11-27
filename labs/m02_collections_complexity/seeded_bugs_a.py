"""Seeded mutants for M02 Gate 4 mutation kill-rate check."""

from __future__ import annotations

import bisect
import heapq
from collections import deque
from collections.abc import Callable, Sequence
from types import ModuleType


def _bug_heap_missing_tiebreaker(mod: ModuleType) -> None:
    """Bug 1: Pushes `(priority, item)` without monotonic FIFO sequence counter."""

    class BrokenQueue[T]:
        def __init__(self) -> None:
            self._heap: list[tuple[int, T]] = []

        def push(self, priority: int, item: T) -> None:
            if isinstance(priority, bool) or not isinstance(priority, int):  # pyright: ignore[reportUnnecessaryIsInstance]
                raise TypeError("priority must be int")
            heapq.heappush(self._heap, (priority, item))  # type: ignore[type-var]

        def pop(self) -> T:
            if not self._heap:
                raise IndexError("empty")
            return heapq.heappop(self._heap)[1]  # type: ignore[type-var]

        def peek(self) -> T:
            if not self._heap:
                raise IndexError("empty")
            return self._heap[0][1]

        def __len__(self) -> int:
            return len(self._heap)

    mod.__dict__["PriorityReadyQueue"] = BrokenQueue


def _bug_quota_strict_inequality_boundary(mod: ModuleType) -> None:
    """Bug 2: Uses `<` instead of `<=` when expiring window timestamps (`now - window` off-by-one)."""

    class OffByOneQuota:
        def __init__(self, max_events: int, window_sec: float) -> None:
            if max_events < 1 or window_sec <= 0:
                raise ValueError("invalid quota params")
            self._max = max_events
            self._win = window_sec
            self._buckets: dict[str, deque[float]] = {}

        def allow(self, tenant: str, now_sec: float) -> bool:
            q = self._buckets.setdefault(tenant, deque())
            cutoff = now_sec - self._win
            while q and q[0] < cutoff:  # BUG: should be <= cutoff
                q.popleft()
            if len(q) >= self._max:
                return False
            q.append(now_sec)
            return True

        def active_count(self, tenant: str, now_sec: float) -> int:
            q = self._buckets.get(tenant)
            if not q:
                return 0
            cutoff = now_sec - self._win
            while q and q[0] < cutoff:
                q.popleft()
            return len(q)

    mod.__dict__["SlidingWindowQuota"] = OffByOneQuota


def _bug_quota_shared_tenant_deque(mod: ModuleType) -> None:
    """Bug 3: Shares a single deque across all tenants instead of per-tenant isolation."""

    class SharedBucketQuota:
        def __init__(self, max_events: int, window_sec: float) -> None:
            if max_events < 1 or window_sec <= 0:
                raise ValueError("invalid quota params")
            self._max = max_events
            self._win = window_sec
            self._shared: deque[float] = deque()

        def allow(self, tenant: str, now_sec: float) -> bool:
            _ = tenant
            cutoff = now_sec - self._win
            while self._shared and self._shared[0] <= cutoff:
                self._shared.popleft()
            if len(self._shared) >= self._max:
                return False
            self._shared.append(now_sec)
            return True

        def active_count(self, tenant: str, now_sec: float) -> int:
            _ = tenant
            cutoff = now_sec - self._win
            while self._shared and self._shared[0] <= cutoff:
                self._shared.popleft()
            return len(self._shared)

    mod.__dict__["SlidingWindowQuota"] = SharedBucketQuota


def _bug_sla_bisect_right_threshold(mod: ModuleType) -> None:
    """Bug 4: Uses `bisect_right` instead of `bisect_left`, misclassifying exact tier boundaries."""

    class BisectRightSla:
        def __init__(self, tiers: Sequence[tuple[float, str]], overflow_label: str = "breach") -> None:
            if not tiers:
                raise ValueError("tiers must not be empty")
            thresholds: list[float] = []
            labels: list[str] = []
            prev = 0.0
            for limit, label in tiers:
                if limit <= 0 or limit <= prev:
                    raise ValueError("thresholds must be strictly positive and strictly increasing")
                thresholds.append(float(limit))
                labels.append(label)
                prev = float(limit)
            self._thresholds = tuple(thresholds)
            self._labels = tuple(labels)
            self._overflow = overflow_label

        def classify(self, duration_ms: float) -> str:
            if duration_ms < 0:
                raise ValueError("duration_ms must be >= 0")
            idx = bisect.bisect_right(self._thresholds, duration_ms)
            return self._labels[idx] if idx < len(self._labels) else self._overflow

    mod.__dict__["SlaBucketTable"] = BisectRightSla


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_heap_missing_tiebreaker": _bug_heap_missing_tiebreaker,
    "bug_quota_strict_inequality_boundary": _bug_quota_strict_inequality_boundary,
    "bug_quota_shared_tenant_deque": _bug_quota_shared_tenant_deque,
    "bug_sla_bisect_right_threshold": _bug_sla_bisect_right_threshold,
}
