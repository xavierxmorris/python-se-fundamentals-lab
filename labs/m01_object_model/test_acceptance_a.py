"""Frozen acceptance oracle for M01 Drill A."""

from __future__ import annotations

import pytest

from drill_a_core import TaskSpec, clone_with_overrides, freeze_value


def test_freeze_value_canonical_and_hashable() -> None:
    left = {"b": [1, {"x": 10, "y": 20}], "a": {"tag2", "tag1"}}
    right = {"a": {"tag1", "tag2"}, "b": [1, {"y": 20, "x": 10}]}

    f_left = freeze_value(left)
    f_right = freeze_value(right)
    assert f_left == f_right
    assert hash(f_left) == hash(f_right)
    assert freeze_value([1, [2, 3]]) == (1, (2, 3))
    assert freeze_value({1, 2}) == frozenset({1, 2})


def test_freeze_value_rejects_unfreezeable_and_non_str_keys() -> None:
    with pytest.raises(TypeError):
        freeze_value({"bad": bytearray(b"mut")})
    with pytest.raises(TypeError):
        freeze_value({"bad": object()})
    with pytest.raises(TypeError):
        freeze_value({1: "integer-key"})


def test_task_spec_isolates_caller_and_output_mutations() -> None:
    nested_args = ["alpha", "beta"]
    nested_retries = [1, 2]
    raw_payload: dict[str, object] = {"args": nested_args, "meta": {"retries": nested_retries}}
    raw_tags = ["urgent", "search", "urgent"]

    spec = TaskSpec("t-100", "acme", "web_search", raw_payload, raw_tags)

    nested_args.append("MUTATED")
    nested_retries.append(999)
    raw_tags.append("injected")

    exported = spec.to_payload_dict()
    assert exported == {"args": ["alpha", "beta"], "meta": {"retries": [1, 2]}}
    assert spec.tags == ("search", "urgent")

    exported_args = exported["args"]
    assert isinstance(exported_args, list)
    exported_args.clear()
    assert spec.to_payload_dict()["args"] == ["alpha", "beta"]


def test_task_spec_equality_and_hashing_across_key_and_tag_order() -> None:
    spec_a = TaskSpec(
        "t-1",
        "acme",
        "index",
        {"z": [1, 2], "a": {"k2": "v2", "k1": "v1"}},
        ["b", "a", "a"],
    )
    spec_b = TaskSpec(
        "t-1",
        "acme",
        "index",
        {"a": {"k1": "v1", "k2": "v2"}, "z": [1, 2]},
        ["a", "b"],
    )
    assert spec_a == spec_b
    assert hash(spec_a) == hash(spec_b)
    assert len({spec_a, spec_b}) == 1


def test_clone_with_overrides_preserves_original_and_isolates_override() -> None:
    base = TaskSpec("t-1", "acme", "index", {"items": [1, 2]}, ["p1"])
    new_payload: dict[str, object] = {"items": [10]}
    cloned = clone_with_overrides(base, tenant="globex", payload=new_payload, tags=["p2", "p1"])
    new_payload["items"] = [999]

    assert base.tenant == "acme"
    assert base.to_payload_dict() == {"items": [1, 2]}
    assert base.tags == ("p1",)

    assert cloned.tenant == "globex"
    assert cloned.task_id == "t-1"
    assert cloned.to_payload_dict() == {"items": [10]}
    assert cloned.tags == ("p1", "p2")


def test_task_spec_validation_and_immutability() -> None:
    spec = TaskSpec("t-1", "acme", "index", {})
    with pytest.raises(AttributeError):
        spec.tenant = "evil"  # type: ignore[misc]
    with pytest.raises(ValueError):
        TaskSpec("   ", "acme", "index", {})
    with pytest.raises(TypeError):
        TaskSpec("t-1", "acme", "index", {}, [123])  # type: ignore[list-item]
