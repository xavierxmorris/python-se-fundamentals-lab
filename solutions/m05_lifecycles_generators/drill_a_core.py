"""M05 Drill A Reference Solution: Lazy generators, ExitStack lifecycles & ExceptionGroup."""

import json
from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import TypeIs


class CorruptRecordError(ValueError):
    """Raised when a JSONL line cannot be decoded into a JSON object dict."""

    line_no: int

    def __init__(self, line_no: int, detail: str = "corrupt JSONL record") -> None:
        self.line_no = line_no
        super().__init__(f"line {line_no}: {detail}")


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    return isinstance(value, dict)


def iter_valid_records(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    """Lazily yield JSON object dicts from a line stream without materializing `lines`."""
    for line_no, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            parsed: object = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise CorruptRecordError(line_no, str(exc)) from exc
        if not _is_json_object(parsed):
            raise CorruptRecordError(
                line_no,
                f"expected JSON object dict, got {type(parsed).__name__}",
            )
        yield parsed


@contextmanager
def acquire_workspace_lease[T](
    resources: Sequence[AbstractContextManager[T]],
) -> Generator[list[T]]:
    """Acquire `resources` dynamically via `ExitStack` with strict LIFO rollback on any failure."""
    with ExitStack() as stack:
        acquired: list[T] = [stack.enter_context(cm) for cm in resources]
        yield acquired


def run_cleanup_hooks(hooks: Sequence[Callable[[], None]]) -> None:
    """Execute all `hooks` in order and raise `ExceptionGroup('cleanup failures', errors)` if any fail."""
    errors: list[Exception] = []
    for hook in hooks:
        try:
            hook()
        except Exception as exc:
            errors.append(exc)
    if errors:
        raise ExceptionGroup("cleanup failures", errors)
