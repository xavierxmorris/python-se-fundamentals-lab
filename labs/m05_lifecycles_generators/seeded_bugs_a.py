"""Seeded realistic mutants for M05 Gate 4 mutation testing."""

import json
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from types import ModuleType
from typing import TypeIs

from drill_a_core import CorruptRecordError as _OrigCorruptRecordError
from drill_a_core import iter_valid_records as _orig_iter_valid_records


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def _bug_eager_materialization(mod: ModuleType) -> None:
    """Mutant 1: Materializes the entire `lines` iterable into a list before yielding anything."""

    def eager_iter_valid_records(lines: Iterable[str]) -> Iterator[dict[str, object]]:
        buffered = list(lines)
        return _orig_iter_valid_records(buffered)

    mod.__dict__["iter_valid_records"] = eager_iter_valid_records


def _bug_missing_exception_cause(mod: ModuleType) -> None:
    """Mutant 2: Raises CorruptRecordError without `from exc`, leaving `__cause__` as None."""

    def unchained_iter_valid_records(lines: Iterable[str]) -> Iterator[dict[str, object]]:
        for line_no, raw_line in enumerate(lines, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                parsed: object = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise _OrigCorruptRecordError(line_no, str(exc))  # noqa: B904
            if not _is_json_object(parsed):
                raise _OrigCorruptRecordError(line_no, "expected JSON object")
            yield parsed

    mod.__dict__["iter_valid_records"] = unchained_iter_valid_records


def _bug_fifo_and_leaking_lease(mod: ModuleType) -> None:
    """Mutant 3: Enters without ExitStack (leaks on mid-acquisition error) and exits FIFO instead of LIFO."""

    @contextmanager
    def buggy_acquire_workspace_lease[T](
        resources: Sequence[AbstractContextManager[T]],
    ) -> Generator[list[T]]:
        acquired = [cm.__enter__() for cm in resources]
        try:
            yield acquired
        finally:
            for cm in resources:
                cm.__exit__(None, None, None)

    mod.__dict__["acquire_workspace_lease"] = buggy_acquire_workspace_lease


def _bug_cleanup_stops_on_first_error(mod: ModuleType) -> None:
    """Mutant 4: Stops at the first failing cleanup hook instead of running all and raising ExceptionGroup."""

    def buggy_run_cleanup_hooks(hooks: Sequence[Callable[[], None]]) -> None:
        for hook in hooks:
            hook()

    mod.__dict__["run_cleanup_hooks"] = buggy_run_cleanup_hooks


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "eager_materialization": _bug_eager_materialization,
    "missing_exception_cause": _bug_missing_exception_cause,
    "fifo_and_leaking_lease": _bug_fifo_and_leaking_lease,
    "cleanup_stops_on_first_error": _bug_cleanup_stops_on_first_error,
}
