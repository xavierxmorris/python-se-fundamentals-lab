"""Seeded mutants for M01 Gate 4 mutation kill-rate check."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable, Mapping
from types import ModuleType

from drill_a_core import TaskSpec as _OrigTaskSpec
from drill_a_core import freeze_value as _orig_freeze_value


def _bug_shallow_input_copy(mod: ModuleType) -> None:
    """Bug 1: TaskSpec only shallow-copies `payload` via `dict(payload)`, leaving nested lists aliased."""

    class ShallowInputTaskSpec(_OrigTaskSpec):
        __slots__ = ("_raw_shallow",)
        _raw_shallow: dict[str, object]

        def __init__(
            self,
            task_id: str,
            tenant: str,
            tool_name: str,
            payload: Mapping[str, object],
            tags: Iterable[str] = (),
        ) -> None:
            super().__init__(task_id, tenant, tool_name, payload, tags)
            object.__setattr__(self, "_raw_shallow", dict(payload))

        def to_payload_dict(self) -> dict[str, object]:
            return dict(self._raw_shallow)

    mod.__dict__["TaskSpec"] = ShallowInputTaskSpec


def _bug_uncopied_payload_export(mod: ModuleType) -> None:
    """Bug 2: `to_payload_dict()` returns the same cached mutable dict across calls."""

    class CachedExportTaskSpec(_OrigTaskSpec):
        __slots__ = ("_cached_export",)
        _cached_export: dict[str, object]

        def __init__(
            self,
            task_id: str,
            tenant: str,
            tool_name: str,
            payload: Mapping[str, object],
            tags: Iterable[str] = (),
        ) -> None:
            super().__init__(task_id, tenant, tool_name, payload, tags)
            object.__setattr__(self, "_cached_export", super().to_payload_dict())

        def to_payload_dict(self) -> dict[str, object]:
            return self._cached_export

    mod.__dict__["TaskSpec"] = CachedExportTaskSpec


def _bug_tag_and_key_order_hash_drift(mod: ModuleType) -> None:
    """Bug 3: Preserves raw tag order/duplicates and unsorted dict key order in hash/eq."""

    class OrderSensitiveTaskSpec(_OrigTaskSpec):
        __slots__ = ("_raw_key_order", "_raw_tags")
        _raw_key_order: tuple[str, ...]
        _raw_tags: tuple[str, ...]

        def __init__(
            self,
            task_id: str,
            tenant: str,
            tool_name: str,
            payload: Mapping[str, object],
            tags: Iterable[str] = (),
        ) -> None:
            tag_list = list(tags)
            super().__init__(task_id, tenant, tool_name, payload, tag_list)
            object.__setattr__(self, "_raw_tags", tuple(tag_list))
            object.__setattr__(self, "_raw_key_order", tuple(payload.keys()))

        @property
        def tags(self) -> tuple[str, ...]:
            return self._raw_tags

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, OrderSensitiveTaskSpec):
                return NotImplemented
            return (
                super().__eq__(other)
                and self.tags == other.tags
                and self._raw_key_order == other._raw_key_order
            )

        def __hash__(self) -> int:
            return hash((super().__hash__(), self.tags, self._raw_key_order))

    mod.__dict__["TaskSpec"] = OrderSensitiveTaskSpec


def _bug_accepts_mutable_objects_in_freeze(mod: ModuleType) -> None:
    """Bug 4: `freeze_value` converts unknown mutable objects via `repr(value)` instead of raising TypeError."""

    def permissive_freeze(value: object) -> Hashable:
        try:
            return _orig_freeze_value(value)
        except TypeError:
            return repr(value)

    mod.__dict__["freeze_value"] = permissive_freeze


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_shallow_input_copy": _bug_shallow_input_copy,
    "bug_uncopied_payload_export": _bug_uncopied_payload_export,
    "bug_tag_and_key_order_hash_drift": _bug_tag_and_key_order_hash_drift,
    "bug_accepts_mutable_objects_in_freeze": _bug_accepts_mutable_objects_in_freeze,
}
