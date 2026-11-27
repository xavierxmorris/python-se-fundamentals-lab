"""Reference learner test suite for M01 Drill A (kills 100% of seeded mutants)."""

from __future__ import annotations

import pytest

from drill_a_core import TaskSpec, clone_with_overrides, freeze_value


def test_caller_nested_mutation_cannot_affect_task_spec() -> None:
    nested_list = ["step-1", "step-2"]
    caller_payload: dict[str, object] = {"steps": nested_list, "cfg": {"timeout": 5}}
    spec = TaskSpec("t-1", "acme", "runner", caller_payload, ["beta", "alpha"])

    nested_list.append("mutated-after-init")
    cfg = caller_payload["cfg"]
    assert isinstance(cfg, dict)
    cfg["timeout"] = 999

    assert spec.to_payload_dict() == {"steps": ["step-1", "step-2"], "cfg": {"timeout": 5}}


def test_exported_payload_dict_is_fresh_deep_copy_every_call() -> None:
    spec = TaskSpec("t-2", "acme", "runner", {"items": [10, 20], "nested": {"k": "v"}})

    first_export = spec.to_payload_dict()
    items = first_export["items"]
    assert isinstance(items, list)
    items.clear()
    first_export["extra"] = "tampered"

    second_export = spec.to_payload_dict()
    assert second_export == {"items": [10, 20], "nested": {"k": "v"}}
    assert second_export is not first_export


def test_equality_and_hash_ignore_key_order_and_tag_duplicates() -> None:
    spec_1 = TaskSpec(
        "t-3",
        "acme",
        "search",
        {"b": [1, 2], "a": {"y": 2, "x": 1}},
        ["urgent", "batch", "urgent"],
    )
    spec_2 = TaskSpec(
        "t-3",
        "acme",
        "search",
        {"a": {"x": 1, "y": 2}, "b": [1, 2]},
        ["batch", "urgent"],
    )

    assert spec_1.tags == ("batch", "urgent")
    assert spec_1 == spec_2
    assert hash(spec_1) == hash(spec_2)
    deduped = {spec_1: "first"}
    deduped[spec_2] = "updated"
    assert len(deduped) == 1


def test_freeze_value_rejects_mutable_custom_objects_and_bad_keys() -> None:
    class CustomMutable:
        pass

    with pytest.raises(TypeError):
        freeze_value(CustomMutable())
    with pytest.raises(TypeError):
        freeze_value({"nested": [CustomMutable()]})
    with pytest.raises(TypeError):
        freeze_value(bytearray(b"abc"))
    with pytest.raises(TypeError):
        freeze_value({42: "non-string-key"})


def test_immutability_and_clone_with_overrides() -> None:
    spec = TaskSpec("t-4", "acme", "index", {"q": ["python"]}, ["v1"])
    with pytest.raises(AttributeError):
        spec.task_id = "t-other"  # type: ignore[misc]

    updated = clone_with_overrides(spec, tool_name="reindex", tags=["v2", "v1"])
    assert spec.tool_name == "index"
    assert spec.tags == ("v1",)
    assert updated.tool_name == "reindex"
    assert updated.tags == ("v1", "v2")
    assert updated.to_payload_dict() == {"q": ["python"]}
