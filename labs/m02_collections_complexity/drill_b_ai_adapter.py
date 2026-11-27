"""M02 Drill B (Spec-First AI Pair): O(n^2) & Unbounded-Memory AuditLogCorrelator.

Remediate the 3 complexity & retention flaws in this AI-generated component:
1. `_pending` uses a `list` and linear scan on every `record_finish` -> O(n^2) batch runtime.
2. `_completed` uses an unbounded `list` that ignores `max_completed_history`.
3. Duplicate `record_start` for an already-pending `event_id` appends duplicates instead of
   overwriting or rejecting cleanly (contract: raise `ValueError` if `event_id` is already pending).
"""

from __future__ import annotations

from drill_a_core import CompactEvent


class AuditLogCorrelator:
    """Correlates task start/finish events into bounded CompactEvent history."""

    def __init__(self, max_completed_history: int = 1000) -> None:
        if max_completed_history < 1:
            raise ValueError("max_completed_history must be >= 1")
        self._max_completed_history = max_completed_history
        # AI BUG 1: list of pending tuples forces O(n) linear scan + O(n) list.pop(i) shift!
        self._pending: list[tuple[str, str, float]] = []
        # AI BUG 2: unbounded list never evicts oldest completed records!
        self._completed: list[CompactEvent] = []

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def record_start(self, event_id: str, tenant: str, start_sec: float) -> None:
        # AI BUG 3: appends blindly without O(1) duplicate pending check
        self._pending.append((event_id, tenant, start_sec))

    def record_finish(self, event_id: str, finish_sec: float) -> CompactEvent | None:
        for idx, (eid, tenant, start_sec) in enumerate(self._pending):
            if eid == event_id:
                self._pending.pop(idx)
                duration_ms = max(0.0, (finish_sec - start_sec) * 1000.0)
                ev = CompactEvent(
                    event_id=event_id,
                    tenant=tenant,
                    duration_ms=duration_ms,
                    timestamp_sec=finish_sec,
                )
                self._completed.append(ev)
                return ev
        return None

    def recent_completed(self) -> tuple[CompactEvent, ...]:
        return tuple(self._completed)
