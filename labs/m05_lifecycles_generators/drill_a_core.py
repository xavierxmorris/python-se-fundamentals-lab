"""M05 Drill A (Cold-Turkey Core): Lazy generators, ExitStack lifecycles & ExceptionGroup."""

from collections.abc import Callable, Generator, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager


class CorruptRecordError(ValueError):
    """Raised when a JSONL line cannot be decoded into a JSON object dict."""

    line_no: int

    def __init__(self, line_no: int, detail: str = "corrupt JSONL record") -> None:
        self.line_no = line_no
        super().__init__(f"line {line_no}: {detail}")


def iter_valid_records(lines: Iterable[str]) -> Iterator[dict[str, object]]:
    """Lazily yield JSON object dicts from a line stream without materializing `lines`.

    Contract:
    - Count 1-based `line_no` across ALL input lines (including blank and `#` comment lines).
    - Skip empty/whitespace-only lines and lines whose stripped text starts with `"#"`.
    - Chain `json.JSONDecodeError` via `raise CorruptRecordError(line_no, str(exc)) from exc`.
    - Raise `CorruptRecordError(line_no, ...)` if decoded JSON is not a `dict` (e.g. list, int, str).
    """
    raise NotImplementedError("Implement iter_valid_records in drill_a_core.py")


@contextmanager
def acquire_workspace_lease[T](
    resources: Sequence[AbstractContextManager[T]],
) -> Generator[list[T]]:
    """Acquire `resources` dynamically via `ExitStack` with strict LIFO rollback on any failure."""
    raise NotImplementedError("Implement acquire_workspace_lease in drill_a_core.py")


def run_cleanup_hooks(hooks: Sequence[Callable[[], None]]) -> None:
    """Execute all `hooks` in order and raise `ExceptionGroup('cleanup failures', errors)` if any fail."""
    raise NotImplementedError("Implement run_cleanup_hooks in drill_a_core.py")
