"""Gate 5 runtime invariant check for M08 Structured Concurrency."""

import asyncio
import contextlib
import hashlib
from pathlib import Path


async def _verify_invariants() -> tuple[bool, str]:
    import drill_a_core

    # 1. Peak concurrency <= max_concurrency & order preservation
    active = 0
    peak_active = 0

    async def bounded_worker(idx: int) -> int:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0.02 if idx % 2 == 0 else 0.005)
            return idx * 3
        finally:
            active -= 1

    ordered = await drill_a_core.run_bounded_batch(
        list(range(8)),
        bounded_worker,
        max_concurrency=3,
        per_item_timeout=1.0,
    )
    if ordered != [i * 3 for i in range(8)]:
        return False, "run_bounded_batch failed to preserve input order"
    if peak_active > 3:
        return False, f"peak active workers ({peak_active}) exceeded max_concurrency=3"

    # 2. Zero leaked tasks after failing run_bounded_batch
    before_fail = set(asyncio.all_tasks())

    async def failing_worker(idx: int) -> int:
        if idx == 1:
            await asyncio.sleep(0.005)
            raise RuntimeError("gate5-fail")
        await asyncio.sleep(0.3)
        return idx

    failed_cleanly = False
    try:
        await drill_a_core.run_bounded_batch(
            [0, 1, 2, 3],
            failing_worker,
            max_concurrency=4,
            per_item_timeout=1.0,
        )
    except ExceptionGroup:
        failed_cleanly = True

    leaked_fail = set(asyncio.all_tasks()) - before_fail
    for task in leaked_fail:
        task.cancel()
    if leaked_fail:
        await asyncio.gather(*leaked_fail, return_exceptions=True)
    if not failed_cleanly:
        return False, "failing batch did not raise ExceptionGroup"
    if leaked_fail:
        return False, f"leaked {len(leaked_fail)} task(s) after failing run_bounded_batch"

    # 3. Zero leaked tasks & CancelledError propagation on external cancellation
    before_cancel = set(asyncio.all_tasks())
    entered = asyncio.Event()

    async def cancellable_worker(idx: int) -> int:
        entered.set()
        await asyncio.sleep(1.0)
        return idx

    batch_task = asyncio.create_task(
        drill_a_core.run_bounded_batch(
            [10, 20, 30],
            cancellable_worker,
            max_concurrency=2,
            per_item_timeout=2.0,
        )
    )
    wait_entered = asyncio.create_task(entered.wait())
    async with asyncio.timeout(1.0):
        await asyncio.wait({batch_task, wait_entered}, return_when=asyncio.FIRST_COMPLETED)
    if not wait_entered.done():
        wait_entered.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await wait_entered
    if batch_task.done():
        await batch_task
    batch_task.cancel()
    cancelled_propagated = False
    try:
        await batch_task
    except asyncio.CancelledError:
        cancelled_propagated = True

    leaked_cancel = set(asyncio.all_tasks()) - before_cancel
    for task in leaked_cancel:
        task.cancel()
    if leaked_cancel:
        await asyncio.gather(*leaked_cancel, return_exceptions=True)
    if not cancelled_propagated:
        return False, "run_bounded_batch swallowed asyncio.CancelledError"
    if leaked_cancel:
        return False, f"leaked {len(leaked_cancel)} task(s) after external cancellation"

    # 4. Event-loop ticks smoothly during offload_blocking_digest
    ticks = 0
    hashing = True

    async def ticker() -> None:
        nonlocal ticks
        while hashing:
            await asyncio.sleep(0.002)
            if hashing:
                ticks += 1

    payload = b"gate5-offload-check"
    iterations = 100_000
    expected_hex = hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()
    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    try:
        digest = await drill_a_core.offload_blocking_digest(payload, iterations=iterations)
    finally:
        hashing = False
        await ticker_task

    if digest != expected_hex:
        return False, "offload_blocking_digest returned incorrect PBKDF2-HMAC-SHA256 hex"
    if ticks < 2:
        return False, f"event loop stalled during offload_blocking_digest (ticks={ticks})"

    return (
        True,
        f"0 leaked tasks on failure/cancel, peak_active={peak_active}<=3, heartbeat ticks={ticks}",
    )


def run_check(module_dir: Path) -> tuple[bool, str]:
    if not (module_dir / "drill_a_core.py").is_file():
        return False, "missing drill_a_core.py"
    try:
        return asyncio.run(_verify_invariants())
    except Exception as exc:
        return False, f"runtime verification failed: {exc}"
