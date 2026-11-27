# M10 · Packaging (`uv`), Profiling (`tracemalloc`) & Context Telemetry

## Entry Contract & Overview

In `taskledger`, performance bottlenecks must be measured with heap/CPU profiles rather than guessed, and structured spans must propagate cleanly across synchronous call stacks and concurrent `asyncio` tasks without cross-task contamination.

### Exported Surface

#### Drill A (`drill_a_core.py`)
- `SpanAttrValue = str | int | float | bool`
- `@dataclass(slots=True, frozen=True) class SpanRecord`:
  - `trace_id: str` (32-char lowercase hex)
  - `span_id: str` (16-char lowercase hex)
  - `parent_span_id: str | None`
  - `name: str`
  - `duration_ms: float`
  - `status: Literal["ok", "error"]`
  - `attributes: Mapping[str, SpanAttrValue]`
- `@dataclass(slots=True, frozen=True) class AllocationReport`:
  - `peak_kib: float`
  - `top_file: str`
  - `top_line: int`
- `current_span_context() -> tuple[str, str] | None`
- `class Tracer`:
  - `spans: list[SpanRecord]`
  - `finished_spans() -> list[SpanRecord]`
  - `@contextmanager start_span(name: str, **attrs: SpanAttrValue) -> Generator[dict[str, SpanAttrValue], None, None]`
  - `@asynccontextmanager start_async_span(name: str, **attrs: SpanAttrValue) -> AsyncGenerator[dict[str, SpanAttrValue], None]`
- `measure_allocations(fn: Callable[[], object]) -> AllocationReport`
- `redact_sensitive_fields(records: Sequence[Mapping[str, str]], secret_keys: AbstractSet[str]) -> list[dict[str, str]]`

#### Drill B (`drill_b_ai_adapter.py`)
- `@dataclass(slots=True, frozen=True) class TelemetryEvent`
- `@dataclass(slots=True, frozen=True) class ExportedBatch`
- `class SpanExporter(Protocol)`
- `class TelemetryBatchProcessor`

---

## Drills

1. **Drill A — Cold-Turkey Core (AI OFF):**
   Implement `drill_a_core.py` from its docstring specification and write adversarial tests in `test_learner_a.py` covering concurrent `asyncio` task span isolation, `ContextVar` token reset on exceptions, error status recording, `tracemalloc` lifecycle preservation, and non-mutating case-insensitive secret redaction.
2. **Drill B — Spec-First AI Pair:**
   Audit and remediate `TelemetryBatchProcessor` in `drill_b_ai_adapter.py` to replace the unbounded $O(n)$ `_seen_spans` list with a bounded FIFO `deque` + `set` window, replace the racy `self.active_trace_id` attribute with `ContextVar` isolation, and eliminate per-event `re.compile` + quadratic string concatenation.

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m10
uv run --no-sync python scripts/eval_module.py m10
```
