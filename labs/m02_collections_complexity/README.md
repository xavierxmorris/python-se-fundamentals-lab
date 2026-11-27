# M02 · Collections, Complexity Intuition & Memory Layout

**Estimated Time:** 60–90 minutes  
**AI Policy:** Drill A = **Cold-Turkey (AI OFF)** · Drill B = **Spec-First AI Pair**

---

## Entry Contract

Implement $O(1)$ / $O(\log n)$ scheduling, rate-limiting, SLA-classification, and event-correlation primitives for `taskledger` using `heapq`, `collections.deque`, `bisect`, `dict`, and `@dataclass(slots=True, frozen=True)`.

### Drill A Exports (`drill_a_core.py`)

1. `CompactEvent` (`@dataclass(slots=True, frozen=True)`):
   - Fields: `event_id: str`, `tenant: str`, `duration_ms: float`, `timestamp_sec: float`.
   - Must have no per-instance `__dict__`.

2. `PriorityReadyQueue[T]`:
   - Min-priority queue backed by `heapq`: lower integer `priority` pops first.
   - `push(priority: int, item: T) -> None`: rejects `bool` or non-`int` `priority` with `TypeError`.
   - `pop() -> T` and `peek() -> T`: break equal-priority ties in strict **FIFO arrival order** without ever comparing `item` (`T` may be a `dict` or custom object without `<`). Raise `IndexError` when empty.
   - `__len__() -> int` and `__bool__() -> bool`.

3. `SlidingWindowQuota`:
   - `SlidingWindowQuota(max_events: int, window_sec: float)` (`ValueError` if `max_events < 1` or `window_sec <= 0`).
   - `allow(tenant: str, now_sec: float) -> bool`:
     - Uses a per-tenant `deque[float]` in amortized $O(1)$ time.
     - Half-open active window `(now_sec - window_sec, now_sec]`: any prior timestamp `ts <= now_sec - window_sec` is expired and evicted before checking capacity.
     - If active count `< max_events`, records `now_sec` and returns `True`; else returns `False` without recording `now_sec`.
   - `active_count(tenant: str, now_sec: float) -> int`: evicts expired entries for `tenant` and returns remaining active count.

4. `SlaBucketTable`:
   - `SlaBucketTable(tiers: Sequence[tuple[float, str]], overflow_label: str = "breach")`:
     - Validates `tiers` is non-empty and thresholds are strictly positive and strictly increasing (`ValueError` otherwise).
   - `classify(duration_ms: float) -> str`:
     - Rejects `duration_ms < 0` with `ValueError`.
     - Uses `bisect.bisect_left` over sorted upper-bound thresholds so `duration_ms <= threshold` maps to that tier's label (exact boundary `duration_ms == threshold` belongs to that tier!), returning `overflow_label` when `duration_ms` exceeds all thresholds.

### Drill B Exports (`drill_b_ai_adapter.py`)

Refactor `AuditLogCorrelator` from $O(n^2)$ `list` scanning and unbounded retention to:
- $O(1)$ hash-indexed pending lookup (`dict[str, tuple[str, float]]`), and
- Bounded ring-buffer retention via `deque(maxlen=max_completed_history)`.

---

## Evaluation Command

```powershell
.\go.ps1 -Module m02
# or:
uv run --no-sync python scripts/eval_module.py m02
```
