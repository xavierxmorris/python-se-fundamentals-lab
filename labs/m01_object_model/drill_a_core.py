"""M01 Drill A (Cold-Turkey Core, AI OFF): Object Model, Aliasing, Identity & Hashing.

Behavioral Contract
-------------------
1. `freeze_value(value: object) -> Hashable`:
   - Primitives (`None`, `bool`, `int`, `float`, `str`, `bytes`) -> unchanged.
   - `list` or `tuple` -> `tuple` of recursively frozen items.
   - `set` or `frozenset` -> `frozenset` of recursively frozen items.
   - `Mapping` -> validate every key is `str` (else `TypeError`), recursively freeze values,
     and return an immutable, hashable representation invariant to key insertion order.
   - Any other type (`bytearray`, `object()`, custom mutable instances) -> raise `TypeError`.

2. `TaskSpec`:
   - Must use `__slots__` (no per-instance `__dict__`; dynamic attribute assignment raises `AttributeError`).
   - `__init__(self, task_id: str, tenant: str, tool_name: str, payload: Mapping[str, object], tags: Iterable[str] = ())`
   - Validate `task_id`, `tenant`, `tool_name` are `str` (`TypeError` otherwise) and non-blank (`ValueError` if `.strip() == ""`).
   - Validate `payload` is a `Mapping` with `str` keys and freeze/deep-copy its contents defensively.
   - Normalize `tags` into a sorted, deduplicated `tuple[str, ...]` (`TypeError` if `tags` is a bare `str`/`bytes` or any element is not `str` — note: accept any `Iterable[str]` such as `list[str]`, `tuple[str, ...]`, `set[str]`; reject non-`str` elements with `TypeError`).
   - Read-only properties: `task_id`, `tenant`, `tool_name`, `tags`.
   - `to_payload_dict(self) -> dict[str, object]`: return a fresh deep copy (`dict` / `list` / `set`) so mutating the returned dict/lists never mutates `self`.
   - Semantic `__eq__` and `__hash__`: equal content (regardless of original dict key order or duplicate/unsorted input tags) yields `a == b` and `hash(a) == hash(b)`.

3. `clone_with_overrides(spec: TaskSpec, *, task_id=None, tenant=None, tool_name=None, payload=None, tags=None) -> TaskSpec`:
   - Return a new `TaskSpec` with specified fields overridden, leaving `spec` untouched and isolated.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping


def freeze_value(value: object) -> Hashable:
    """Recursively convert nested containers into an immutable, hashable value."""
    raise NotImplementedError("Implement freeze_value in drill_a_core.py")


class TaskSpec:
    """Immutable, hashable, aliasing-safe specification for a TaskLedger job."""

    __slots__ = ("_frozen_payload", "_payload_template", "_tags", "_task_id", "_tenant", "_tool_name")

    def __init__(
        self,
        task_id: str,
        tenant: str,
        tool_name: str,
        payload: Mapping[str, object],
        tags: Iterable[str] = (),
    ) -> None:
        raise NotImplementedError("Implement TaskSpec.__init__ in drill_a_core.py")

    @property
    def task_id(self) -> str:
        raise NotImplementedError("Implement TaskSpec.task_id")

    @property
    def tenant(self) -> str:
        raise NotImplementedError("Implement TaskSpec.tenant")

    @property
    def tool_name(self) -> str:
        raise NotImplementedError("Implement TaskSpec.tool_name")

    @property
    def tags(self) -> tuple[str, ...]:
        raise NotImplementedError("Implement TaskSpec.tags")

    def to_payload_dict(self) -> dict[str, object]:
        """Return a fresh deep mutable dictionary copy of the payload."""
        raise NotImplementedError("Implement TaskSpec.to_payload_dict")


def clone_with_overrides(
    spec: TaskSpec,
    *,
    task_id: str | None = None,
    tenant: str | None = None,
    tool_name: str | None = None,
    payload: Mapping[str, object] | None = None,
    tags: Iterable[str] | None = None,
) -> TaskSpec:
    """Create an isolated copy of `spec` with any non-None fields replaced."""
    raise NotImplementedError("Implement clone_with_overrides in drill_a_core.py")
