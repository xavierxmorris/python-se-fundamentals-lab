"""Gate 5 runtime invariant check for M02 (`m02_collections_complexity`)."""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path


def run_check(module_dir: Path) -> tuple[bool, str]:
    _ = module_dir
    import drill_a_core
    import drill_b_ai_adapter

    sample = drill_a_core.CompactEvent("ev-0", "acme", 10.0, 100.0)
    if hasattr(sample, "__dict__"):
        return False, "CompactEvent must use slots=True and have no __dict__"

    n_events = 25_000
    max_keep = 500
    correlator = drill_b_ai_adapter.AuditLogCorrelator(max_completed_history=max_keep)

    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    tracemalloc.reset_peak()

    t0 = time.perf_counter()
    try:
        for i in range(n_events):
            correlator.record_start(f"id-{i}", "acme", float(i))
        # Finish in reverse order so a naive list scan hits worst-case O(n^2) (~3.1e8 ops!)
        for i in range(n_events - 1, -1, -1):
            correlator.record_finish(f"id-{i}", float(i) + 0.01)
        elapsed = time.perf_counter() - t0
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        if not was_tracing:
            tracemalloc.stop()

    if elapsed > 6.0:
        return (
            False,
            f"AuditLogCorrelator took {elapsed:.2f}s for {n_events} reverse correlations (expected <6.0s O(n) hash lookup)",
        )
    retained = len(correlator.recent_completed())
    if retained != max_keep:
        return False, f"Expected bounded history of {max_keep}, got {retained}"

    peak_mib = peak_bytes / (1024 * 1024)
    if peak_mib > 12.0:
        return False, f"Peak memory {peak_mib:.2f} MiB exceeded 12.0 MiB ceiling"

    return (
        True,
        f"CompactEvent slots verified; {n_events} reverse correlations completed in {elapsed * 1000:.1f}ms (peak {peak_mib:.2f} MiB)",
    )
