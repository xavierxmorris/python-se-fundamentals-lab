"""M05 Drill B (Spec-First AI Pair): Batch archive exporter with spool lifecycles & except*.

Audit and remediate the flawed AI-generated `BatchArchiveExporter` below:
1. Manage opened `SpoolHandle` writers with `ExitStack` + `closing` so mid-acquisition or
   mid-stream errors close every already-opened spool deterministically.
2. Replace broad `except Exception:` around `run_cleanup_hooks` with selective
   `except* TempSpoolError` so recoverable `TempSpoolError` messages are recorded in
   `recovered_spool_warnings` while non-`TempSpoolError` sub-exceptions propagate!
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from drill_a_core import iter_valid_records, run_cleanup_hooks


class TempSpoolError(RuntimeError):
    """Recoverable temporary spool cleanup failure."""


@runtime_checkable
class SpoolHandle(Protocol):
    """Structural protocol for shard spool writers."""

    @property
    def closed(self) -> bool: ...

    def write_record(self, record: Mapping[str, object]) -> None: ...

    def close(self) -> None: ...


class SpoolWriter:
    """In-memory shard spool handle tracking written records and close state."""

    def __init__(self, shard_name: str) -> None:
        self.shard_name = shard_name
        self._records: list[dict[str, object]] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def records(self) -> list[dict[str, object]]:
        return [dict(item) for item in self._records]

    def write_record(self, record: Mapping[str, object]) -> None:
        if self._closed:
            raise RuntimeError(f"spool {self.shard_name!r} is already closed")
        self._records.append(dict(record))

    def close(self) -> None:
        self._closed = True


@dataclass(slots=True, frozen=True)
class ExportReport:
    """Summary returned by `BatchArchiveExporter.export_stream`."""

    written_per_shard: dict[str, int]
    total_records: int
    recovered_spool_warnings: tuple[str, ...]


class BatchArchiveExporter:
    """Flawed AI-generated exporter that leaks spool handles and swallows non-TempSpoolError failures."""

    def __init__(
        self,
        shard_names: Sequence[str],
        spool_factory: Callable[[str], SpoolHandle] = SpoolWriter,
    ) -> None:
        if not shard_names:
            raise ValueError("shard_names must be non-empty")
        self._shard_names: tuple[str, ...] = tuple(shard_names)
        self._spool_factory = spool_factory

    def export_stream(
        self,
        lines: Iterable[str],
        cleanup_hooks: Sequence[Callable[[], None]] = (),
    ) -> ExportReport:
        # FLAW 1: Opens spools without ExitStack; mid-acquisition or mid-stream errors leak open handles!
        spools = [self._spool_factory(name) for name in self._shard_names]
        counts: dict[str, int] = dict.fromkeys(self._shard_names, 0)
        total = 0

        for record in iter_valid_records(lines):
            idx = total % len(spools)
            shard_name = self._shard_names[idx]
            spools[idx].write_record(record)
            counts[shard_name] += 1
            total += 1

        for spool in spools:
            spool.close()

        # FLAW 2: Catches broad Exception (including ExceptionGroup with fatal errors!) instead of except* TempSpoolError.
        recovered: list[str] = []
        try:
            run_cleanup_hooks(cleanup_hooks)
        except Exception as exc:
            recovered.append(str(exc))

        return ExportReport(
            written_per_shard=counts,
            total_records=total,
            recovered_spool_warnings=tuple(recovered),
        )
