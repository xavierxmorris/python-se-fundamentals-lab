"""Learner test suite for M09 Drill A (ACID Transactions, Idempotency & Lease Fencing).

Cover at minimum:
1. Duplicate idempotent replay returns `created_new=False` with the original stored
   snapshot WITHOUT invoking `compute_initial_snapshot` a second time.
2. Replaying an existing `request_id` with a modified payload raises
   `IdempotencyConflictError` without mutating stored state.
3. Canonical JSON hashing treats reordered dictionary keys (including nested dicts) as
   identical payloads rather than raising `IdempotencyConflictError`.
4. Monotonic `fence_token` enforcement in `acquire_lease` / `record_outcome` rejects stale
   workers and already-succeeded tasks with `StaleFenceError` (and missing tasks with
   `TaskNotFoundError`).
"""

import pytest


def test_placeholder_replace_with_transactions_idempotency_suite() -> None:
    pytest.fail("Replace this placeholder with your transactions & idempotency test suite.")
