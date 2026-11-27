"""M01 Drill B (Spec-First AI Pair): Flawed AI-generated RunContextBatcher.

Audit and fix the 3 object-model defects in this component:
1. Shared mutable default/class metadata dictionary across `add_run` calls.
2. In-place mutation of the caller's `retries` sequence (`retries.append(...)`).
3. Object identity comparison (`is`) instead of value equality (`==`) in `for_tenant`,
   plus exposed mutable `metadata` on `RunContext`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

_SHARED_DEFAULT_METADATA: dict[str, str] = {}


@dataclass(slots=True, frozen=True)
class RunContext:
    """Execution context envelope attached to a scheduled TaskSpec."""

    task_id: str
    tenant: str
    attempt_history: tuple[int, ...]
    metadata: Mapping[str, str]


class RunContextBatcher:
    """Collects RunContext envelopes for a dispatch wave."""

    def __init__(self, wave_id: str) -> None:
        if not wave_id.strip():
            raise ValueError("wave_id must not be blank")
        self._wave_id = wave_id
        self._contexts: list[RunContext] = []

    @property
    def wave_id(self) -> str:
        return self._wave_id

    def add_run(
        self,
        task_id: str,
        tenant: str,
        retries: Sequence[int],
        metadata: Mapping[str, str] | None = None,
    ) -> RunContext:
        # AI BUG 1: falls back to a shared module-level dict and mutates it!
        active_meta = _SHARED_DEFAULT_METADATA if metadata is None else dict(metadata)
        active_meta.setdefault("wave_id", self._wave_id)
        active_meta["last_task_id"] = task_id

        # AI BUG 2: mutates caller's list in place if `retries` happens to be a list!
        if isinstance(retries, list):
            retries.append(len(retries) + 1)
            attempts = tuple(retries)
        else:
            attempts = (*retries, len(retries) + 1)

        # AI BUG 3a: stores mutable dict directly instead of read-only MappingProxyType
        ctx = RunContext(
            task_id=task_id,
            tenant=tenant,
            attempt_history=attempts,
            metadata=active_meta,
        )
        self._contexts.append(ctx)
        return ctx

    def for_tenant(self, tenant: str) -> list[RunContext]:
        # AI BUG 3b: uses `is` identity instead of `==` value equality!
        return [ctx for ctx in self._contexts if ctx.tenant is tenant]

    def snapshot_all(self) -> tuple[RunContext, ...]:
        _ = MappingProxyType  # Hint: read-only mapping wrapper available in `types`
        return tuple(self._contexts)
