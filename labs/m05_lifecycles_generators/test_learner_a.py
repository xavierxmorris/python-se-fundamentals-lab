"""Learner test suite for M05 Drill A (Cold-Turkey Core).

Replace the placeholder below with tests covering:
- Lazy `iter_valid_records` streaming (no eager `list(lines)` buffering), 1-based `line_no`,
  non-dict JSON rejection, and `CorruptRecordError.__cause__` preservation
- `acquire_workspace_lease` LIFO exit ordering on normal completion, body exception, and mid-acquisition failure
- `run_cleanup_hooks` running every hook and raising `ExceptionGroup("cleanup failures", ...)`
"""

import pytest


def test_learner_placeholder() -> None:
    pytest.fail("Replace test_learner_placeholder in test_learner_a.py with real M05 Drill A tests.")
