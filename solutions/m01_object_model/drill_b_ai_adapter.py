"""Reference solution for M01 Drill B: Remediated RunContextBatcher."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(slots=True, frozen=True)
class RunContext:
    """Immutable execution context envelope attached to a scheduled TaskSpec."""

    task_id: str
    tenant: str
    attempt_history: tuple[int, ...]
    metadata: Mapping[str, str]


class RunContextBatcher:
    """Collects aliasing-safe RunContext envelopes for a dispatch wave."""

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
        fresh_meta: dict[str, str] = {} if metadata is None else {str(k): str(v) for k, v in metadata.items()}
        fresh_meta.setdefault("wave_id", self._wave_id)
        fresh_meta["last_task_id"] = task_id

        attempts = (*tuple(retries), len(retries) + 1)
        ctx = RunContext(
            task_id=task_id,
            tenant=tenant,
            attempt_history=attempts,
            metadata=MappingProxyType(fresh_meta),
        )
        self._contexts.append(ctx)
        return ctx

    def for_tenant(self, tenant: str) -> list[RunContext]:
        return [ctx for ctx in self._contexts if ctx.tenant == tenant]

    def snapshot_all(self) -> tuple[RunContext, ...]:
        return tuple(self._contexts)
