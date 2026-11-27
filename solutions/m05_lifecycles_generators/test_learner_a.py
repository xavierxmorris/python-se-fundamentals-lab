"""Reference learner test suite for M05 Drill A (kills 100% of seeded bugs)."""

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


class _SpyContextManager:
    def __init__(self, label: str, events: list[str], *, fail_on_enter: bool = False) -> None:
        self._label = label
        self._events = events
        self._fail_on_enter = fail_on_enter

    def __enter__(self) -> str:
        self._events.append(f"enter:{self._label}")
        if self._fail_on_enter:
            raise RuntimeError(f"boom:{self._label}")
        return self._label

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        marker = exc_type.__name__ if exc_type is not None else "clean"
        self._events.append(f"exit:{self._label}:{marker}")
        return False


def test_iter_valid_records_is_strictly_lazy_and_counts_all_lines() -> None:
    reads = 0

    def _bounded_exploding_stream() -> Iterator[str]:
        nonlocal reads
        raw_items = [
            "\n",
            "  # comment line 2\n",
            '{"task_id": "t-1", "n": 10}\n',
            '{"task_id": "t-2", "n": 20}\n',
        ]
        for item in raw_items:
            reads += 1
            yield item
        raise RuntimeError("eager materialization consumed past islice stop")

    sliced = list(islice(iter_valid_records(_bounded_exploding_stream()), 2))
    assert sliced == [
        {"task_id": "t-1", "n": 10},
        {"task_id": "t-2", "n": 20},
    ]
    assert reads == 4


def test_iter_valid_records_preserves_json_decode_cause_and_rejects_scalars() -> None:
    stream = [
        "# comment 1\n",
        "   \n",
        "{not_json\n",
    ]
    with pytest.raises(CorruptRecordError) as exc_info:
        list(iter_valid_records(stream))

    err = exc_info.value
    assert err.line_no == 3
    assert isinstance(err.__cause__, json.JSONDecodeError)

    with pytest.raises(CorruptRecordError) as list_err:
        list(iter_valid_records(['{"ok": true}\n', "[1, 2]\n"]))
    assert list_err.value.line_no == 2


def test_acquire_workspace_lease_unwinds_lifo_on_success_and_mid_enter_failure() -> None:
    events: list[str] = []
    cms = [
        _SpyContextManager("a", events),
        _SpyContextManager("b", events),
        _SpyContextManager("c", events),
    ]
    with acquire_workspace_lease(cms) as leased:
        assert leased == ["a", "b", "c"]
        events.append("in_body")

    assert events == [
        "enter:a",
        "enter:b",
        "enter:c",
        "in_body",
        "exit:c:clean",
        "exit:b:clean",
        "exit:a:clean",
    ]

    rollback_events: list[str] = []
    failing_cms = [
        _SpyContextManager("r0", rollback_events),
        _SpyContextManager("r1", rollback_events),
        _SpyContextManager("r2", rollback_events, fail_on_enter=True),
        _SpyContextManager("r3", rollback_events),
    ]
    with pytest.raises(RuntimeError, match="boom:r2"), acquire_workspace_lease(failing_cms):
        pass

    assert rollback_events == [
        "enter:r0",
        "enter:r1",
        "enter:r2",
        "exit:r1:RuntimeError",
        "exit:r0:RuntimeError",
    ]


def test_run_cleanup_hooks_runs_every_hook_and_raises_exception_group() -> None:
    call_order: list[str] = []

    def _first() -> None:
        call_order.append("first")
        raise RuntimeError("hook_1_failed")

    def _second() -> None:
        call_order.append("second")

    def _third() -> None:
        call_order.append("third")
        raise KeyError("hook_3_failed")

    with pytest.raises(ExceptionGroup) as exc_info:
        run_cleanup_hooks([_first, _second, _third])

    assert call_order == ["first", "second", "third"]
    assert exc_info.value.message == "cleanup failures"
    assert len(exc_info.value.exceptions) == 2
    assert isinstance(exc_info.value.exceptions[0], RuntimeError)
    assert isinstance(exc_info.value.exceptions[1], KeyError)
