"""Reference solution for M02 Drill B: O(1) Hash-Indexed & Bounded AuditLogCorrelator."""

from __future__ import annotations

from collections import deque

from drill_a_core import CompactEvent


class AuditLogCorrelator:
    """Correlates task start/finish events in O(1) time with bounded ring retention."""

    def __init__(self, max_completed_history: int = 1000) -> None:
        if max_completed_history < 1:
            raise ValueError("max_completed_history must be >= 1")
        self._pending: dict[str, tuple[str, float]] = {}
        self._completed: deque[CompactEvent] = deque(maxlen=max_completed_history)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def record_start(self, event_id: str, tenant: str, start_sec: float) -> None:
        if event_id in self._pending:
            raise ValueError(f"event_id {event_id!r} is already pending")
        self._pending[event_id] = (tenant, float(start_sec))

    def record_finish(self, event_id: str, finish_sec: float) -> CompactEvent | None:
        entry = self._pending.pop(event_id, None)
        if entry is None:
            return None
        tenant, start_sec = entry
        duration_ms = max(0.0, (float(finish_sec) - start_sec) * 1000.0)
        ev = CompactEvent(
            event_id=event_id,
            tenant=tenant,
            duration_ms=duration_ms,
            timestamp_sec=float(finish_sec),
        )
        self._completed.append(ev)
        return ev

    def recent_completed(self) -> tuple[CompactEvent, ...]:
        return tuple(self._completed)
