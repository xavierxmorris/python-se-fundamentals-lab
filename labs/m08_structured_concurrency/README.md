# M08 · Structured Concurrency: `asyncio.TaskGroup`, Cancellation & Backpressure

## Entry Contract

Coding agents routinely generate `asyncio` code that spawns fire-and-forget `asyncio.create_task(...)` coroutines (leaking orphan background tasks when one sibling fails), swallows `asyncio.CancelledError` via broad `except BaseException:` handlers, launches unbounded fan-out without a semaphore, or runs CPU-bound hashing synchronously on the event loop thread. This module drills **structured concurrency (`asyncio.TaskGroup`)**, **bounded backpressure (`asyncio.Semaphore`)**, **scoped deadlines (`asyncio.timeout`)**, **clean cancellation propagation**, and **thread-pool offloading (`asyncio.to_thread`)**.

### Exported Surface (`drill_a_core.py` — Cold-Turkey Core, AI OFF)

- `async def run_bounded_batch[T, R](items: Sequence[T], worker: Callable[[T], Awaitable[R]], *, max_concurrency: int, per_item_timeout: float) -> list[R]`
  - Validates `max_concurrency >= 1` and `per_item_timeout > 0` (raising `ValueError` otherwise, including booleans or `NaN`).
  - Preserves exact input order in the returned `list[R]`.
  - Bounds active concurrent `worker` executions to `<= max_concurrency` using `asyncio.Semaphore(max_concurrency)`.
  - Applies `async with asyncio.timeout(per_item_timeout):` **inside** the semaphore acquisition around `await worker(item)`.
  - Uses `async with asyncio.TaskGroup() as tg:` so worker failures or external cancellation cancel and await all sibling tasks with **zero leaked tasks**, and never swallows `asyncio.CancelledError`.
- `async def offload_blocking_digest(payload: bytes, *, iterations: int = 25_000) -> str`
  - Uses `await asyncio.to_thread(...)` to compute `hashlib.pbkdf2_hmac("sha256", payload, b"taskledger", iterations).hex()` off the event loop thread so concurrent heartbeats keep ticking without blocking.

### Exported Surface (`drill_b_ai_adapter.py` — Spec-First AI Pair)

- `ToolCall`, `ToolResult`, `AsyncToolInvoker` (`Protocol`), and `AsyncToolPump`.
- Remediate `AsyncToolPump` so it replaces leaked `asyncio.create_task` fan-out, blocking `time.sleep`, and `except BaseException:` cancellation swallowing with `asyncio.TaskGroup`, `asyncio.Semaphore`, `asyncio.sleep`, and `finally:` cleanup that always re-raises `asyncio.CancelledError`.

## Workflow

1. **Drill A (AI OFF):** Implement `drill_a_core.py` from its docstring contract, then write deterministic `asyncio.run(...)` tests in `test_learner_a.py` (covering concurrency high-water marks, out-of-order completion, `CancelledError` propagation, and a concurrent 2ms event-loop ticker during `offload_blocking_digest`) to kill 100% of mutants in `seeded_bugs_a.py`.
2. **Drill B (Spec-First AI Pair):** Audit `drill_b_ai_adapter.py` against `test_acceptance_b.py` and fix task leaks, backpressure, blocking sleep, and cancellation handling.

## Evaluation Commands

```powershell
.\go.ps1 -Module m08
uv run --no-sync python scripts/eval_module.py m08
```
