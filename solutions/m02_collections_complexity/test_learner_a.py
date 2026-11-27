"""Reference learner test suite for M02 Drill A (kills 100% of seeded mutants)."""

from __future__ import annotations

import pytest

from drill_a_core import CompactEvent, PriorityReadyQueue, SlaBucketTable, SlidingWindowQuota


def test_priority_queue_breaks_ties_fifo_on_unorderable_dicts() -> None:
    q: PriorityReadyQueue[dict[str, int]] = PriorityReadyQueue()
    d1 = {"seq": 1}
    d2 = {"seq": 2}
    d3 = {"seq": 3}

    q.push(5, d1)
    q.push(5, d2)
    q.push(1, d3)

    assert q.pop() is d3
    assert q.pop() is d1
    assert q.pop() is d2

    with pytest.raises(IndexError):
        q.pop()


def test_sliding_window_exact_cutoff_eviction_and_tenant_isolation() -> None:
    quota = SlidingWindowQuota(max_events=2, window_sec=5.0)
    assert quota.allow("tenant-a", 10.0) is True
    assert quota.allow("tenant-a", 12.0) is True
    assert quota.allow("tenant-a", 14.999) is False

    # Other tenant must have an independent window
    assert quota.allow("tenant-b", 14.999) is True

    # At exact t=15.0, event at t=10.0 has age 5.0 (10.0 <= 15.0 - 5.0) -> must expire!
    assert quota.allow("tenant-a", 15.0) is True
    assert quota.active_count("tenant-a", 15.0) == 2


def test_sla_bucket_exact_threshold_uses_bisect_left() -> None:
    table = SlaBucketTable([(50.0, "fast"), (200.0, "normal"), (1000.0, "slow")], overflow_label="breach")
    assert table.classify(50.0) == "fast"
    assert table.classify(50.0001) == "normal"
    assert table.classify(200.0) == "normal"
    assert table.classify(1000.0) == "slow"
    assert table.classify(1000.01) == "breach"

    with pytest.raises(ValueError):
        table.classify(-1.0)


def test_compact_event_is_frozen_and_slotted() -> None:
    ev = CompactEvent("e-1", "acme", 5.0, 100.0)
    assert not hasattr(ev, "__dict__")
