# M05 · Lazy Generators (`yield`), `ExitStack` Lifecycles & `ExceptionGroup` / `except*`

## Entry Contract & Invariants

Streaming pipelines and multi-resource lifecycles require three deterministic guarantees that AI-generated code routinely violates:
1. **$O(1)$-Memory Lazy Streaming:** Never materialize an arbitrary `Iterable[str]` with `list(lines)` or `[...]` before yielding records.
2. **Strict LIFO Acquisition Rollback (`contextlib.ExitStack`):** When acquiring `N` context managers dynamically, if resource `k` raises inside `__enter__`, already-entered resources `0..k-1` must still exit in reverse (`LIFO`) order.
3. **Lossless Multi-Error Teardown (`ExceptionGroup` & `except*`):** Independent cleanup callbacks must all execute even when earlier callbacks fail, bundling failures into `ExceptionGroup` and recovering only expected transient errors via selective `except*`.

---

## Drill A — Cold-Turkey Core (`drill_a_core.py` + `test_learner_a.py`, AI OFF)

Implement the following exported symbols in `drill_a_core.py`:

### 1. `CorruptRecordError` & Lazy `iter_valid_records`
- `class CorruptRecordError(ValueError):`
  - Stores `line_no: int` (`def __init__(self, line_no: int, detail: str = "corrupt JSONL record") -> None:`).
- `def iter_valid_records(lines: Iterable[str]) -> Iterator[dict[str, object]]:`
  - Lazy generator over `lines` tracking 1-based `line_no` across **all** input lines (including skipped lines).
  - Skips empty/whitespace-only lines and comment lines whose stripped content starts with `"#"`.
  - Parses each remaining line with `json.loads`:
    - Chains `json.JSONDecodeError` via `raise CorruptRecordError(line_no, str(exc)) from exc` so `__cause__` is preserved.
    - Rejects valid JSON values that are not JSON objects (e.g., `[1, 2]`, `42`, `"str"`, `true`, `null`) by raising `CorruptRecordError(line_no, ...)`.
  - Yields `dict[str, object]` lazily without buffering `lines` into a list.

### 2. Dynamic Resource Lease via `ExitStack`
- `@contextmanager def acquire_workspace_lease[T](resources: Sequence[AbstractContextManager[T]]) -> Generator[list[T]]:`
  - Enters every context manager in `resources` sequentially using `contextlib.ExitStack`.
  - Yields the `list[T]` of entered resource handles.
  - Guarantees strict `LIFO` (`reverse`) `__exit__` order both on normal/exceptional body completion **and** for `0..k-1` when resource `k` raises during `__enter__`.

### 3. Lossless Cleanup Hook Runner
- `def run_cleanup_hooks(hooks: Sequence[Callable[[], None]]) -> None:`
  - Invokes **every** hook in `hooks` in order, even if earlier hooks raise `Exception`.
  - Collects all raised `Exception` instances and raises `ExceptionGroup("cleanup failures", errors)` if one or more hooks failed.

Write comprehensive adversarial tests in `test_learner_a.py` to kill 100% of mutants in `seeded_bugs_a.py`.

---

## Drill B — Spec-First AI Pair (`drill_b_ai_adapter.py`)

`drill_b_ai_adapter.py` contains a flawed `BatchArchiveExporter` that:
1. Opens shard `SpoolHandle` writers in a loop without `ExitStack` / `closing`, leaking open spool handles whenever shard creation or `iter_valid_records` fails mid-stream.
2. Wraps `run_cleanup_hooks(cleanup_hooks)` in a broad `except Exception:` block instead of selective `except* TempSpoolError`, swallowing fatal cleanup errors (`PermissionError`, `OSError`, etc.) alongside recoverable `TempSpoolError` warnings.

Refactor `BatchArchiveExporter.export_stream` to:
- Manage every `SpoolHandle` via `ExitStack` + `contextlib.closing` so all opened spools are closed on both normal exit and mid-stream failure.
- Route valid records round-robin across `shard_names` (`record_index % len(shard_names)`).
- Catch `except* TempSpoolError` selectively around `run_cleanup_hooks(cleanup_hooks)`, recording each `TempSpoolError` message in `ExportReport.recovered_spool_warnings` while allowing non-`TempSpoolError` sub-exceptions to propagate.

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m05
uv run --no-sync python scripts/eval_module.py m05
```
