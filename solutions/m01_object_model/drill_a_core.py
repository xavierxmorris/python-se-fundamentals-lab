"""Reference solution for M01 Drill A: Object Model, Aliasing, Identity & Hashing."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeIs


@dataclass(slots=True, frozen=True)
class _FrozenMapping:
    """Hashable, order-independent canonical mapping representation."""

    entries: tuple[tuple[str, Hashable], ...]


def _is_list_or_tuple(val: object) -> TypeIs[list[object] | tuple[object, ...]]:
    return isinstance(val, (list, tuple))


def _is_set_or_frozenset(val: object) -> TypeIs[set[object] | frozenset[object]]:
    return isinstance(val, (set, frozenset))


def _is_mapping(val: object) -> TypeIs[Mapping[object, object]]:
    return isinstance(val, Mapping)


def _is_object_iterable(val: object) -> TypeIs[Iterable[object]]:
    return isinstance(val, Iterable)


def _validate_non_blank_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a str, got {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"{name} must not be empty or whitespace")
    return value


def _normalize_tags(tags: object) -> tuple[str, ...]:
    if isinstance(tags, (str, bytes)) or not _is_object_iterable(tags):
        raise TypeError("tags must be an iterable of str items, not a bare str/bytes")
    seen: set[str] = set()
    for item in tags:
        if not isinstance(item, str):
            raise TypeError(f"every tag must be a str, got {type(item).__name__}")
        seen.add(item)
    return tuple(sorted(seen))


def _iter_str_keyed_mapping[K, V](mapping_obj: Mapping[K, V]) -> list[tuple[str, V]]:
    pairs: list[tuple[str, V]] = []
    for k, val in mapping_obj.items():
        if not isinstance(k, str):
            raise TypeError(f"mapping keys must be str, got {type(k).__name__}")
        pairs.append((k, val))
    return pairs


def _deep_clone_mapping[K, V](mapping_obj: Mapping[K, V]) -> dict[str, object]:
    cloned: dict[str, object] = {}
    for k, v in _iter_str_keyed_mapping(mapping_obj):
        cloned[k] = _deep_clone_payload_value(v)
    return cloned


def _deep_clone_payload_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if _is_list_or_tuple(value):
        return [_deep_clone_payload_value(item) for item in value]
    if _is_set_or_frozenset(value):
        return {_deep_clone_payload_value(item) for item in value}
    if _is_mapping(value):
        return _deep_clone_mapping(value)
    raise TypeError(f"Unsupported mutable or custom value type: {type(value).__name__}")


def freeze_value(value: object) -> Hashable:
    """Recursively convert nested containers into an immutable, hashable value."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if _is_list_or_tuple(value):
        return tuple(freeze_value(item) for item in value)
    if _is_set_or_frozenset(value):
        return frozenset(freeze_value(item) for item in value)
    if _is_mapping(value):
        pairs = [(k, freeze_value(v)) for k, v in _iter_str_keyed_mapping(value)]
        pairs.sort(key=lambda pair: pair[0])
        return _FrozenMapping(tuple(pairs))
    raise TypeError(f"Unsupported value type for freeze_value: {type(value).__name__}")


class TaskSpec:
    """Immutable, hashable, aliasing-safe specification for a TaskLedger job."""

    __slots__ = ("_frozen_payload", "_payload_template", "_tags", "_task_id", "_tenant", "_tool_name")

    _task_id: str
    _tenant: str
    _tool_name: str
    _frozen_payload: Hashable
    _payload_template: dict[str, object]
    _tags: tuple[str, ...]

    def __init__(
        self,
        task_id: str,
        tenant: str,
        tool_name: str,
        payload: Mapping[str, object],
        tags: Iterable[str] = (),
    ) -> None:
        if not isinstance(payload, Mapping):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise TypeError(f"payload must be a Mapping, got {type(payload).__name__}")

        valid_task_id = _validate_non_blank_str("task_id", task_id)
        valid_tenant = _validate_non_blank_str("tenant", tenant)
        valid_tool = _validate_non_blank_str("tool_name", tool_name)
        frozen_payload = freeze_value(payload)
        cloned_payload = _deep_clone_mapping(payload)
        normalized_tags = _normalize_tags(tags)

        object.__setattr__(self, "_task_id", valid_task_id)
        object.__setattr__(self, "_tenant", valid_tenant)
        object.__setattr__(self, "_tool_name", valid_tool)
        object.__setattr__(self, "_frozen_payload", frozen_payload)
        object.__setattr__(self, "_payload_template", cloned_payload)
        object.__setattr__(self, "_tags", normalized_tags)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("TaskSpec is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("TaskSpec is immutable")

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def tenant(self) -> str:
        return self._tenant

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def tags(self) -> tuple[str, ...]:
        return self._tags

    def to_payload_dict(self) -> dict[str, object]:
        return _deep_clone_mapping(self._payload_template)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TaskSpec):
            return NotImplemented
        return (
            self._task_id == other._task_id
            and self._tenant == other._tenant
            and self._tool_name == other._tool_name
            and self._tags == other._tags
            and self._frozen_payload == other._frozen_payload
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._task_id,
                self._tenant,
                self._tool_name,
                self._tags,
                self._frozen_payload,
            )
        )

    def __repr__(self) -> str:
        return (
            f"TaskSpec(task_id={self._task_id!r}, tenant={self._tenant!r}, "
            f"tool_name={self._tool_name!r}, tags={self._tags!r})"
        )


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
    return TaskSpec(
        task_id=spec.task_id if task_id is None else task_id,
        tenant=spec.tenant if tenant is None else tenant,
        tool_name=spec.tool_name if tool_name is None else tool_name,
        payload=spec.to_payload_dict() if payload is None else payload,
        tags=spec.tags if tags is None else tags,
    )
