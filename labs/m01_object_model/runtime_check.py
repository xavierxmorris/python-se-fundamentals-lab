"""Gate 5 runtime invariant check for M01 (`m01_object_model`)."""

from __future__ import annotations

from pathlib import Path
from typing import TypeIs


def _is_obj_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def run_check(module_dir: Path) -> tuple[bool, str]:
    _ = module_dir
    import drill_a_core
    import drill_b_ai_adapter

    raw: dict[str, object] = {"nested": [1, 2, {"k": "v"}]}
    spec = drill_a_core.TaskSpec("t-rt", "acme", "tool", raw, ["z", "a", "z"])

    if hasattr(spec, "__dict__"):
        return False, "TaskSpec must use __slots__ and not expose a per-instance __dict__"

    attr_name = "".join(["dynamic", "_extra"])
    try:
        setattr(spec, attr_name, 123)
        return False, "TaskSpec allowed dynamic attribute attachment"
    except AttributeError:
        pass

    exported = spec.to_payload_dict()
    nested = exported["nested"]
    if not _is_obj_list(nested):
        return False, "to_payload_dict() must reconstruct nested list values as fresh lists"
    nested.append("tamper")
    if spec.to_payload_dict()["nested"] != [1, 2, {"k": "v"}]:
        return False, "Mutating to_payload_dict() corrupted internal TaskSpec state"

    batcher = drill_b_ai_adapter.RunContextBatcher("wave-rt")
    ctx = batcher.add_run("t-rt", "".join(["ac", "me"]), [1])
    try:
        ctx.metadata["tamper"] = "bad"  # type: ignore[index]
        return False, "RunContext.metadata must be a read-only mapping (e.g. MappingProxyType)"
    except TypeError:
        pass

    return True, "TaskSpec slots/immutability + deep copy isolation + RunContext read-only mapping verified"
