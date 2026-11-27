# M04 · Python 3.14 Static Typing: PEP 695 Generics, `Protocol`, Unions & `TypeIs`

## Entry Contract & Invariants

Strict static types in Python 3.14 act as executable guardrails that reject illegal states and constrain AI-generated adapters before tests run. Every file you write in this module (`drill_a_core.py`, `drill_b_ai_adapter.py`, `test_learner_a.py`) must use **zero `Any`**, **zero `cast`**, and **zero `# type: ignore`**.

---

## Drill A — Cold-Turkey Core (`drill_a_core.py` + `test_learner_a.py`, AI OFF)

Implement the following exported symbols in `drill_a_core.py`:

### 1. PEP 695 `Result` & Combinators
- `@dataclass(slots=True, frozen=True) class Ok[T]: value: T`
- `@dataclass(slots=True, frozen=True) class Err[E]: error: E`
- `type Result[T, E] = Ok[T] | Err[E]`
- `def is_ok[T, E](r: Result[T, E]) -> TypeIs[Ok[T]]:` — returns `True` iff `r` is `Ok`, narrowing both `if` and `else` branches.
- `def map_ok[T, U, E](r: Result[T, E], fn: Callable[[T], U]) -> Result[U, E]:` — transforms `Ok(v)` into `Ok(fn(v))`; returns `Err` unchanged without calling `fn`.
- `def and_then[T, U, E](r: Result[T, E], fn: Callable[[T], Result[U, E]]) -> Result[U, E]:` — monadic bind: returns `fn(v)` for `Ok(v)` without double-wrapping; returns `Err` unchanged without calling `fn`.

### 2. Structural `ToolPlugin` Protocol
- `@runtime_checkable class ToolPlugin[InT, OutT](Protocol):`
  - `@property def name(self) -> str: ...`
  - `def execute(self, request: InT) -> Result[OutT, str]: ...`
- `def invoke_plugin[InT, OutT](plugin: ToolPlugin[InT, OutT], request: InT) -> Result[OutT, str]:`
  - If `not plugin.name.strip()`, return `Err("invalid_plugin_name")` without calling `plugin.execute`.
  - Otherwise delegate to `plugin.execute(request)`.

### 3. Discriminated `TaskEvent` Union & Boundary Parser
- Frozen `slots=True` event dataclasses:
  - `QueuedEvent(kind: Literal["queued"], task_id: str, priority: int)`
  - `StartedEvent(kind: Literal["started"], task_id: str, worker_id: str)`
  - `FinishedEvent(kind: Literal["finished"], task_id: str, exit_code: int)`
  - `CancelledEvent(kind: Literal["cancelled"], task_id: str, reason: str)`
  - `type TaskEvent = QueuedEvent | StartedEvent | FinishedEvent | CancelledEvent`
- `def summarize_event(ev: TaskEvent) -> str:` — exhaustive `match` + `assert_never`:
  - `QueuedEvent` -> `f"[{ev.task_id}] queued (priority={ev.priority})"`
  - `StartedEvent` -> `f"[{ev.task_id}] started on {ev.worker_id}"`
  - `FinishedEvent` with `exit_code == 0` -> `f"[{ev.task_id}] succeeded (exit_code=0)"`
  - `FinishedEvent` with `exit_code != 0` -> `f"[{ev.task_id}] failed (exit_code={ev.exit_code})"`
  - `CancelledEvent` -> `f"[{ev.task_id}] cancelled: {ev.reason}"`
  - Unmatched runtime objects -> `assert_never(ev)`
- `def parse_event_dict(raw: Mapping[str, object]) -> Result[TaskEvent, str]:`
  - Requires `task_id` to be a non-blank `str` (`Err("invalid_task_id")`), `kind` to be a `str` (`Err("invalid_kind")`).
  - Rejects `bool` where `int` is required (`isinstance(True, int)` is `True` in Python!):
    - `"queued"` requires strict `int` `priority` (`Err("invalid_priority")`).
    - `"started"` requires non-blank `str` `worker_id` (`Err("invalid_worker_id")`).
    - `"finished"` requires strict `int` `exit_code` (`Err("invalid_exit_code")`).
    - `"cancelled"` requires non-blank `str` `reason` (`Err("invalid_reason")`).
    - Any other `kind` returns `Err(f"unknown_kind:{kind}")`.

Write thorough tests in `test_learner_a.py` to kill 100% of mutants in `seeded_bugs_a.py`.

---

## Drill B — Spec-First AI Pair (`drill_b_ai_adapter.py`)

`drill_b_ai_adapter.py` contains a loosely typed `EventMiddlewarePipeline` with 4 `Any` annotations, `bool`-as-`int` acceptance, ignored hook errors, and a missing `"cancelled"` branch that silently returns `None`.

Refactor it to expose:
- `class BatchReport(TypedDict): total: int; delivered: list[str]; errors: list[str]`
- `class EventHook(Protocol): def transform(self, event: TaskEvent, summary: str) -> Result[str, str]: ...`
- `class EventMiddlewarePipeline:`
  - `__init__(self, hooks: Sequence[EventHook] = ()) -> None`
  - `process(self, raw_event: Mapping[str, object]) -> Result[str, str]` (parses via `parse_event_dict`, summarizes via `summarize_event`, runs hooks in order short-circuiting on `Err`)
  - `process_batch(self, payloads: Sequence[Mapping[str, object]]) -> BatchReport`

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m04
uv run --no-sync python scripts/eval_module.py m04
```
