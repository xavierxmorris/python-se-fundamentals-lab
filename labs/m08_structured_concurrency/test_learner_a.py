"""Learner test suite for M08 Drill A (Structured Concurrency & Thread Offloading).

Note: `pytest-asyncio` is NOT installed — wrap async scenarios in `asyncio.run(...)`
inside synchronous `def test_...() -> None:` functions.

Cover at minimum:
1. Input-order preservation when earlier items finish slower than later items.
2. `max_concurrency` enforcement via an active high-water-mark counter, plus `ValueError`
   validation for invalid `max_concurrency` and `per_item_timeout`.
3. Sibling cancellation on worker failure/timeout AND external `CancelledError`
   propagation (never swallowed by `except BaseException:`) with zero leaked tasks.
4. Concurrent 2ms heartbeat ticker proving `offload_blocking_digest` runs off the event
   loop thread via `asyncio.to_thread` while producing the exact PBKDF2-HMAC-SHA256 hex.
"""

import pytest


def test_placeholder_replace_with_structured_concurrency_suite() -> None:
    pytest.fail("Replace this placeholder with your structured concurrency test suite for Drill A.")
