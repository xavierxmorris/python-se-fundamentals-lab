"""Seeded subtle mutants for M10 Gate 4 mutation testing."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from types import MappingProxyType, ModuleType
from typing import Literal


def _bug_instance_span_state(module: ModuleType) -> None:
    """Bug 1: Stores active span on instance/global field instead of ContextVar (races in async)."""
    last_active: list[tuple[str, str] | None] = [None]

    def racy_current_span_context() -> tuple[str, str] | None:
        return last_active[0]

    @contextmanager
    def racy_start_span(
        self: object,
        name: str,
        **attrs: str | int | float | bool,
    ) -> Generator[dict[str, str | int | float | bool], None, None]:
        if not name or not name.strip():
            raise ValueError("span name must be non-empty")
        prev = getattr(self, "_current_span", None)
        if prev is None:
            trace_id = secrets.token_hex(16)
            parent_span_id: str | None = None
        else:
            trace_id, parent_span_id = prev
        span_id = secrets.token_hex(8)
        cur = (trace_id, span_id)
        object.__setattr__(self, "_current_span", cur)
        last_active[0] = cur
        live_attrs: dict[str, str | int | float | bool] = dict(attrs)
        started = time.perf_counter_ns()
        status: Literal["ok", "error"] = "ok"
        try:
            yield live_attrs
        except BaseException as exc:
            status = "error"
            live_attrs["error.type"] = type(exc).__name__
            raise
        finally:
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            object.__setattr__(self, "_current_span", prev)
            last_active[0] = prev
            rec = module.SpanRecord(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                duration_ms=elapsed_ms,
                status=status,
                attributes=MappingProxyType(dict(live_attrs)),
            )
            spans_list: list[object] = getattr(self, "spans")  # noqa: B009
            spans_list.append(rec)

    module.current_span_context = racy_current_span_context  # type: ignore[attr-defined]
    module.Tracer.start_span = racy_start_span  # type: ignore[attr-defined]


def _bug_missing_token_reset_on_error(module: ModuleType) -> None:
    """Bug 2: Resets ContextVar token only on normal exit, leaking dead span context on error."""
    active_var = module._ACTIVE_SPAN

    @contextmanager
    def leaky_start_span(
        self: object,
        name: str,
        **attrs: str | int | float | bool,
    ) -> Generator[dict[str, str | int | float | bool], None, None]:
        if not name or not name.strip():
            raise ValueError("span name must be non-empty")
        parent = active_var.get()
        if parent is None:
            trace_id = secrets.token_hex(16)
            parent_span_id: str | None = None
        else:
            trace_id, parent_span_id = parent
        span_id = secrets.token_hex(8)
        token = active_var.set((trace_id, span_id))
        live_attrs: dict[str, str | int | float | bool] = dict(attrs)
        started = time.perf_counter_ns()
        status: Literal["ok", "error"] = "ok"
        try:
            yield live_attrs
            active_var.reset(token)
        except BaseException as exc:
            status = "error"
            live_attrs["error.type"] = type(exc).__name__
            raise
        finally:
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            rec = module.SpanRecord(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                duration_ms=elapsed_ms,
                status=status,
                attributes=MappingProxyType(dict(live_attrs)),
            )
            spans_list: list[object] = getattr(self, "spans")  # noqa: B009
            spans_list.append(rec)

    module.Tracer.start_span = leaky_start_span  # type: ignore[attr-defined]


def _bug_error_recorded_as_ok(module: ModuleType) -> None:
    """Bug 3: Re-raises exception and resets token, but leaves span status='ok' without error.type."""
    active_var = module._ACTIVE_SPAN

    @contextmanager
    def blind_start_span(
        self: object,
        name: str,
        **attrs: str | int | float | bool,
    ) -> Generator[dict[str, str | int | float | bool], None, None]:
        if not name or not name.strip():
            raise ValueError("span name must be non-empty")
        parent = active_var.get()
        if parent is None:
            trace_id = secrets.token_hex(16)
            parent_span_id: str | None = None
        else:
            trace_id, parent_span_id = parent
        span_id = secrets.token_hex(8)
        token = active_var.set((trace_id, span_id))
        live_attrs: dict[str, str | int | float | bool] = dict(attrs)
        started = time.perf_counter_ns()
        try:
            yield live_attrs
        finally:
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            active_var.reset(token)
            rec = module.SpanRecord(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                duration_ms=elapsed_ms,
                status="ok",
                attributes=MappingProxyType(dict(live_attrs)),
            )
            spans_list: list[object] = getattr(self, "spans")  # noqa: B009
            spans_list.append(rec)

    module.Tracer.start_span = blind_start_span  # type: ignore[attr-defined]


def _bug_redact_mutates_and_case_sensitive(module: ModuleType) -> None:
    """Bug 4: Matches secret keys case-sensitively and mutates caller dicts in place."""

    def buggy_redact(
        records: Sequence[Mapping[str, str]],
        secret_keys: AbstractSet[str],
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for rec in records:
            target = rec if isinstance(rec, dict) else dict(rec)
            for key in list(target.keys()):
                if key in secret_keys:
                    target[key] = "[REDACTED]"
            out.append(target)
        return out

    module.redact_sensitive_fields = buggy_redact  # type: ignore[attr-defined]


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_instance_span_state": _bug_instance_span_state,
    "bug_missing_token_reset_on_error": _bug_missing_token_reset_on_error,
    "bug_error_recorded_as_ok": _bug_error_recorded_as_ok,
    "bug_redact_mutates_and_case_sensitive": _bug_redact_mutates_and_case_sensitive,
}
