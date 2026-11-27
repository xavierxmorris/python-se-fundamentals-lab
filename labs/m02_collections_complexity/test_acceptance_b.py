"""Frozen acceptance suite for M02 Drill B (`AuditLogCorrelator`)."""

from __future__ import annotations

import pytest

from drill_b_ai_adapter import AuditLogCorrelator


def test_correlator_bounded_fifo_retention() -> None:
    correlator = AuditLogCorrelator(max_completed_history=3)
    for i in range(5):
        eid = f"ev-{i}"
        correlator.record_start(eid, "acme", float(i))
        ev = correlator.record_finish(eid, float(i) + 0.25)
        assert ev is not None
        assert ev.duration_ms == pytest.approx(250.0)

    history = correlator.recent_completed()
    assert [e.event_id for e in history] == ["ev-2", "ev-3", "ev-4"]
    assert correlator.pending_count == 0


def test_correlator_rejects_duplicate_pending_and_ignores_unknown_finish() -> None:
    correlator = AuditLogCorrelator(max_completed_history=10)
    correlator.record_start("ev-dup", "acme", 10.0)

    with pytest.raises(ValueError):
        correlator.record_start("ev-dup", "acme", 11.0)

    assert correlator.record_finish("unknown-id", 12.0) is None
    finished = correlator.record_finish("ev-dup", 12.5)
    assert finished is not None
    assert correlator.pending_count == 0
    # Re-starting after completion is valid because it is no longer pending
    correlator.record_start("ev-dup", "acme", 20.0)
    assert correlator.pending_count == 1
