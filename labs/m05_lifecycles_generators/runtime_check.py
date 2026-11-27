"""Gate 5 runtime invariant check for M05 (`m05_lifecycles_generators`).

Enforces:
1. Streaming 100,000 synthetic JSONL lines through `iter_valid_records` under `tracemalloc`
   consumes < 1,048,576 bytes (1 MiB) peak memory delta (proving lazy O(1) streaming).
2. `CorruptRecordError.__cause__` preserves the underlying `json.JSONDecodeError`.
"""

import json
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

TOTAL_SYNTHETIC_LINES = 100_000
MAX_PEAK_DELTA_BYTES = 1_048_576  # 1 MiB


def _synthetic_jsonl_lines(total_lines: int) -> Iterator[str]:
    for idx in range(1, total_lines + 1):
        if idx % 10 == 0:
            yield "   \n"
        elif idx % 15 == 0:
            yield f"# synthetic comment at line {idx}\n"
        else:
            yield f'{{"seq": {idx}, "tenant": "acme", "status": "queued"}}\n'


def run_check(module_dir: Path) -> tuple[bool, str]:
    _ = module_dir
    import drill_a_core

    # Warm up json decoder tables before resetting peak memory counter.
    _ = json.loads('{"warmup": 1}')

    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()

    try:
        baseline_current, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        try:
            valid_count = 0
            for record in drill_a_core.iter_valid_records(
                _synthetic_jsonl_lines(TOTAL_SYNTHETIC_LINES)
            ):
                if "seq" in record:
                    valid_count += 1
        except NotImplementedError as exc:
            return False, f"iter_valid_records not implemented: {exc}"
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        if not was_tracing:
            tracemalloc.stop()

    if valid_count == 0:
        return False, "iter_valid_records yielded 0 records on 100,000-line stream"

    peak_delta = max(0, peak_bytes - baseline_current)
    if peak_delta >= MAX_PEAK_DELTA_BYTES:
        return (
            False,
            f"Peak memory delta {peak_delta:,} bytes exceeded 1 MiB ({MAX_PEAK_DELTA_BYTES:,} bytes) ceiling",
        )

    probe_lines = ['{"ok": 1}\n', "# comment\n", "{broken_json\n"]
    try:
        for _ in drill_a_core.iter_valid_records(probe_lines):
            pass
        return False, "iter_valid_records failed to raise CorruptRecordError on malformed JSON line"
    except drill_a_core.CorruptRecordError as err:
        if err.line_no != 3:
            return False, f"Expected CorruptRecordError.line_no == 3, got {err.line_no}"
        if not isinstance(err.__cause__, json.JSONDecodeError):
            return (
                False,
                f"CorruptRecordError.__cause__ must be json.JSONDecodeError, got {err.__cause__!r}",
            )

    return (
        True,
        f"Streamed {TOTAL_SYNTHETIC_LINES:,} lines ({valid_count:,} records) in {peak_delta:,} B peak delta (<1 MiB); __cause__ verified",
    )
