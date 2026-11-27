"""Frozen acceptance suite for M05 Drill B."""

import pytest

from drill_a_core import CorruptRecordError
from drill_b_ai_adapter import BatchArchiveExporter, SpoolWriter, TempSpoolError


def test_exporter_closes_all_spools_on_mid_stream_corrupt_record() -> None:
    created: list[SpoolWriter] = []

    def _factory(shard: str) -> SpoolWriter:
        writer = SpoolWriter(shard)
        created.append(writer)
        return writer

    exporter = BatchArchiveExporter(["shard-a", "shard-b"], spool_factory=_factory)
    lines = [
        '{"task": "t-1"}\n',
        '{"task": "t-2"}\n',
        "{corrupt_json_at_line_3\n",
        '{"task": "t-4"}\n',
    ]

    with pytest.raises(CorruptRecordError) as exc_info:
        exporter.export_stream(lines)

    assert exc_info.value.line_no == 3
    assert len(created) == 2
    assert all(w.closed for w in created)


def test_exporter_closes_earlier_spools_if_factory_fails_mid_acquisition() -> None:
    created: list[SpoolWriter] = []

    def _flaky_factory(shard: str) -> SpoolWriter:
        if shard == "shard-c":
            raise OSError("no space left on device")
        writer = SpoolWriter(shard)
        created.append(writer)
        return writer

    exporter = BatchArchiveExporter(["shard-a", "shard-b", "shard-c"], spool_factory=_flaky_factory)
    with pytest.raises(OSError, match="no space left"):
        exporter.export_stream(['{"task": "t-1"}\n'])

    assert [w.shard_name for w in created] == ["shard-a", "shard-b"]
    assert all(w.closed for w in created)


def test_exporter_recovers_temp_spool_errors_via_except_star() -> None:
    created: dict[str, SpoolWriter] = {}

    def _factory(shard: str) -> SpoolWriter:
        writer = SpoolWriter(shard)
        created[shard] = writer
        return writer

    def _warn_1() -> None:
        raise TempSpoolError("stale .tmp marker on shard-a")

    def _warn_2() -> None:
        raise TempSpoolError("delayed unlink on shard-b")

    exporter = BatchArchiveExporter(["shard-a", "shard-b"], spool_factory=_factory)
    report = exporter.export_stream(
        [
            "# batch header\n",
            '{"task": "t-1"}\n',
            '{"task": "t-2"}\n',
            '{"task": "t-3"}\n',
        ],
        cleanup_hooks=[_warn_1, _warn_2],
    )

    assert report.total_records == 3
    assert report.written_per_shard == {"shard-a": 2, "shard-b": 1}
    assert report.recovered_spool_warnings == (
        "stale .tmp marker on shard-a",
        "delayed unlink on shard-b",
    )
    assert all(w.closed for w in created.values())


def test_exporter_propagates_non_temp_spool_cleanup_exceptions() -> None:
    exporter = BatchArchiveExporter(["shard-a"])

    def _recoverable() -> None:
        raise TempSpoolError("harmless temp residue")

    def _fatal() -> None:
        raise PermissionError("audit archive ACL denied")

    with pytest.raises(ExceptionGroup) as exc_info:
        exporter.export_stream(['{"task": "t-1"}\n'], cleanup_hooks=[_recoverable, _fatal])

    remaining = exc_info.value.exceptions
    assert len(remaining) == 1
    assert isinstance(remaining[0], PermissionError)
