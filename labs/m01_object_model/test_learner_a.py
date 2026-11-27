"""Learner test suite for M01 Drill A (Cold-Turkey Core).

Replace the placeholder test below with unit and boundary tests covering:
- Deep aliasing isolation on caller input mutation (nested dicts/lists/sets)
- Deep aliasing isolation on mutating `spec.to_payload_dict()` return values
- Semantic equality (`==`) and `hash()` parity across dict key order & duplicate/reordered tags
- Immutability (attribute rebinding / new attribute assignment rejected) and `clone_with_overrides`
- Rejection of unfreezeable objects and invalid field types
"""

from __future__ import annotations

import pytest


def test_placeholder_replace_with_real_tests() -> None:
    pytest.fail(
        "Replace this placeholder in labs/m01_object_model/test_learner_a.py "
        "with tests that verify TaskSpec, freeze_value, and clone_with_overrides."
    )
