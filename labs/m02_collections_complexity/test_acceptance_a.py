"""Frozen acceptance oracle for M02 Drill A."""

from __future__ import annotations

import pytest

from drill_a_core import CompactEvent, PriorityReadyQueue, SlaBucketTable, SlidingWindowQuota


def test_priority_ready_queue_fifo_ties_and_unorderable_items() -> None:
    q: PriorityReadyQueue[dict[str, str]] = PriorityReadyQueue()
    first = {"id": "a"}
    second = {"id": "b"}
    urgent = {"id": "urgent"}

    q.push(10, first)
    q.push(10, second)
    q.push(1, urgent)

    assert len(q) == 3
    assert q.peek() == urgent
    assert q.pop() == urgent
    assert q.pop() == first
    assert q.pop() == second
    assert len(q) == 0

    with pytest.raises(IndexError):
        q.pop()
    with pytest.raises(TypeError):
        q.push(True, first)


def test_sliding_window_quota_boundary_and_tenant_isolation() -> None:
    quota = SlidingWindowQuota(max_events=2, window_sec=10.0)

    assert quota.allow("acme", 100.0) is True
    assert quota.allow("acme", 104.0) is True
    assert quota.allow("acme", 109.9) is False
    assert quota.allow("globex", 109.9) is True

    # At exact boundary 110.0, timestamp 100.0 has age 10.0 (ts <= now - window) -> expired!
    assert quota.allow("acme", 110.0) is True
    assert quota.active_count("acme", 110.0) == 2


def test_sla_bucket_table_bisect_thresholds() -> None:
    sla = SlaBucketTable([(25.0, "p50"), (100.0, "p95"), (500.0, "p99")], overflow_label="timeout_risk")
    assert sla.classify(0.0) == "p50"
    assert sla.classify(25.0) == "p50"
    assert sla.classify(25.01) == "p95"
    assert sla.classify(100.0) == "p95"
    assert sla.classify(500.0) == "p99"
    assert sla.classify(500.1) == "timeout_risk"

    with pytest.raises(ValueError):
        sla.classify(-0.1)
    with pytest.raises(ValueError):
        SlaBucketTable([(100.0, "a"), (100.0, "b")])


def test_compact_event_slots() -> None:
    ev = CompactEvent("e-1", "acme", 12.5, 1000.0)
    assert not hasattr(ev, "__dict__")
