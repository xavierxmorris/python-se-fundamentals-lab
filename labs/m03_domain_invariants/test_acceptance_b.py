"""Frozen acceptance suite for M03 Drill B (`PolicySchedule`)."""

from __future__ import annotations

import pytest

from drill_a_core import DomainValidationError, TenantId, UtcDate
from drill_b_ai_adapter import NoActivePolicy, PolicyConflictError, PolicyRule, PolicySchedule


def test_half_open_cutover_and_gap_days() -> None:
    schedule = PolicySchedule.from_json_dicts(
        [
            {
                "rule_id": "r-h1",
                "tenant_id": "acme",
                "max_attempts": 2,
                "effective_from": "2025-01-01",
                "effective_until": "2025-07-01",
            },
            {
                "rule_id": "r-h2",
                "tenant_id": "acme",
                "max_attempts": 5,
                "effective_from": "2025-07-01",
                "effective_until": None,
            },
        ]
    )
    acme = TenantId.parse("acme")

    before = schedule.resolve(acme, UtcDate.parse("2024-12-31"))
    assert isinstance(before, NoActivePolicy)

    last_day_h1 = schedule.resolve(acme, UtcDate.parse("2025-06-30"))
    assert isinstance(last_day_h1, PolicyRule)
    assert last_day_h1.rule_id == "r-h1"

    cutover = schedule.resolve(acme, UtcDate.parse("2025-07-01"))
    assert isinstance(cutover, PolicyRule)
    assert cutover.rule_id == "r-h2"
    assert cutover.max_attempts == 5


def test_overlapping_or_inverted_intervals_raise_conflict() -> None:
    with pytest.raises(PolicyConflictError):
        PolicySchedule.from_json_dicts(
            [
                {
                    "rule_id": "r-1",
                    "tenant_id": "acme",
                    "max_attempts": 2,
                    "effective_from": "2025-01-01",
                    "effective_until": "2025-07-02",
                },
                {
                    "rule_id": "r-2",
                    "tenant_id": "acme",
                    "max_attempts": 4,
                    "effective_from": "2025-07-01",
                    "effective_until": "2025-12-31",
                },
            ]
        )

    with pytest.raises(DomainValidationError):
        PolicySchedule.from_json_dicts(
            [
                {
                    "rule_id": "r-empty-window",
                    "tenant_id": "acme",
                    "max_attempts": 2,
                    "effective_from": "2025-07-01",
                    "effective_until": "2025-07-01",
                }
            ]
        )


def test_missing_or_timestamp_fields_rejected_at_boundary() -> None:
    with pytest.raises(DomainValidationError):
        PolicySchedule.from_json_dicts(
            [
                {
                    "rule_id": "r-missing-tenant",
                    "max_attempts": 3,
                    "effective_from": "2025-01-01",
                    "effective_until": None,
                }
            ]
        )

    with pytest.raises(DomainValidationError):
        PolicySchedule.from_json_dicts(
            [
                {
                    "rule_id": "r-timestamp",
                    "tenant_id": "acme",
                    "max_attempts": 3,
                    "effective_from": "2025-01-01T00:00:00Z",
                    "effective_until": None,
                }
            ]
        )
