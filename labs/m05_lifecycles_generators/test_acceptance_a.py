"""Frozen acceptance suite for M05 Drill A."""

import json
from collections.abc import Iterator
from itertools import islice
from types import TracebackType

import pytest

from drill_a_core import (
    CorruptRecordError,
    acquire_workspace_lease,
    iter_valid_records,
    run_cleanup_hooks,
)


class _TrackedResource:
    def __init__(self, name: str, log: list[str], *, fail_enter: bool = False) -> None:
        self.name = name
        self._log = log
        self._fail_enter = fail_enter

    def __enter__(self) -> str:
        self._log.append(f"enter:{self.name}")
        if self._fail_enter:
            raise RuntimeError(f"failed_enter:{self.name}")
        return f"handle:{self.name}"

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        tag = exc_type.__name__ if exc_type is not None else "ok"
        self._log.append(f"exit:{self.name}:{tag}")
        return False


def test_iter_valid_records_skips_comments_and_blanks_lazily() -> None:
    consumed_lines = 0

    def _stream() -> Iterator[str]:
        nonlocal consumed_lines
        payloads = [
            "   \n",
            "# header comment\n",
            '{"id": "t-1", "attempt": 1}\n',
            "  # indented comment\n",
            '{"id": "t-2", "attempt": 2}\n',
            '{"id": "t-3", "attempt": 3}\n',
        ]
        for line in payloads:
            consumed_lines += 1
            yield line
        raise AssertionError("generator should not be exhausted when slicing first 2 records")

    first_two = list(islice(iter_valid_records(_stream()), 2))
    assert first_two == [
        {"id": "t-1", "attempt": 1},
        {"id": "t-2", "attempt": 2},
    ]
    assert consumed_lines == 5


def test_iter_valid_records_chains_json_decode_error_with_exact_line_no() -> None:
    lines = [
        "# comment line 1\n",
        "\n",
        '{"ok": true}\n',
        "{malformed json\n",
    ]
    it = iter_valid_records(lines)
    assert next(it) == {"ok": True}
    with pytest.raises(CorruptRecordError) as exc_info:
        next(it)
    assert exc_info.value.line_no == 4
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.parametrize("bad_literal", ["[1, 2, 3]", "42", '"just_a_string"', "true", "null"])
def test_iter_valid_records_rejects_non_dict_json_values(bad_literal: str) -> None:
    lines = ['{"valid": 1}\n', f"{bad_literal}\n"]
    it = iter_valid_records(lines)
    assert next(it) == {"valid": 1}
    with pytest.raises(CorruptRecordError) as exc_info:
        next(it)
    assert exc_info.value.line_no == 2


def test_acquire_workspace_lease_lifo_on_normal_and_body_exception() -> None:
    log: list[str] = []
    resources = [_TrackedResource("db", log), _TrackedResource("lock", log), _TrackedResource("spool", log)]
    with acquire_workspace_lease(resources) as handles:
        assert handles == ["handle:db", "handle:lock", "handle:spool"]
        log.append("body")

    assert log == [
        "enter:db",
        "enter:lock",
        "enter:spool",
        "body",
        "exit:spool:ok",
        "exit:lock:ok",
        "exit:db:ok",
    ]

    err_log: list[str] = []
    err_resources = [_TrackedResource("r1", err_log), _TrackedResource("r2", err_log)]
    with pytest.raises(ValueError, match="abort_work"), acquire_workspace_lease(err_resources):
        raise ValueError("abort_work")

    assert err_log == [
        "enter:r1",
        "enter:r2",
        "exit:r2:ValueError",
        "exit:r1:ValueError",
    ]


def test_acquire_workspace_lease_rolls_back_entered_resources_if_kth_enter_fails() -> None:
    log: list[str] = []
    resources = [
        _TrackedResource("first", log),
        _TrackedResource("second", log),
        _TrackedResource("third", log, fail_enter=True),
        _TrackedResource("fourth", log),
    ]
    with pytest.raises(RuntimeError, match="failed_enter:third"), acquire_workspace_lease(resources):
        pytest.fail("body must not run when 3rd resource fails __enter__")

    assert log == [
        "enter:first",
        "enter:second",
        "enter:third",
        "exit:second:RuntimeError",
        "exit:first:RuntimeError",
    ]


def test_run_cleanup_hooks_executes_all_hooks_and_bundles_exception_group() -> None:
    executed: list[str] = []

    def _h1() -> None:
        executed.append("h1")
        raise OSError("disk_flush_failed")

    def _h2() -> None:
        executed.append("h2")

    def _h3() -> None:
        executed.append("h3")
        raise ValueError("invalid_cursor_state")

    with pytest.raises(ExceptionGroup) as exc_info:
        run_cleanup_hooks([_h1, _h2, _h3])

    assert executed == ["h1", "h2", "h3"]
    group = exc_info.value
    assert group.message == "cleanup failures"
    assert len(group.exceptions) == 2
    assert isinstance(group.exceptions[0], OSError)
    assert isinstance(group.exceptions[1], ValueError)

    ok_ran: list[str] = []
    run_cleanup_hooks([lambda: ok_ran.append("clean")])
    assert ok_ran == ["clean"]
