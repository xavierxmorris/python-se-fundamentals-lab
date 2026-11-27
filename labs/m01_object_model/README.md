# M01 · Object Model, Mutability, Aliasing, Identity & Hashing

**Estimated Time:** 60–90 minutes  
**AI Policy:** Drill A = **Cold-Turkey (AI OFF)** · Drill B = **Spec-First AI Pair**

---

## Entry Contract

Design immutable, aliasing-proof, hash-consistent task specifications for `taskledger`.

### Drill A Exports (`drill_a_core.py`)

1. `freeze_value(value: object) -> Hashable`
   - Recursively converts nested containers into an immutable, hashable canonical form:
     - Primitives (`None`, `bool`, `int`, `float`, `str`, `bytes`) are returned unchanged.
     - `list` / `tuple` -> `tuple` of recursively frozen elements.
     - `set` / `frozenset` -> `frozenset` of recursively frozen elements.
     - `Mapping` (keys must all be `str`, otherwise raise `TypeError`) -> immutable, hashable representation whose `==` and `hash()` are independent of key insertion order.
     - Any unsupported/mutable custom object (e.g., `object()`, custom mutable class, `bytearray`) raises `TypeError`.

2. `TaskSpec` (`slots`-backed immutable value object — no `__dict__`)
   - `TaskSpec(task_id: str, tenant: str, tool_name: str, payload: Mapping[str, object], tags: Iterable[str] = ())`
   - Validates `task_id`, `tenant`, and `tool_name` are non-empty, non-whitespace strings (`TypeError` if not `str`, `ValueError` if blank).
   - Deep-freezes/copies `payload` so mutating caller dicts/lists/sets *after* construction never affects `TaskSpec`.
   - Deduplicates and sorts `tags` into canonical `tags: tuple[str, ...]` (`TypeError` if any tag is not `str`).
   - Properties: `task_id -> str`, `tenant -> str`, `tool_name -> str`, `tags -> tuple[str, ...]`.
   - `to_payload_dict() -> dict[str, object]`: returns a fresh mutable deep copy (`dict`/`list`/`set`) so mutating the returned structure never affects `TaskSpec`.
   - Value equality & hashing: two `TaskSpec` instances with semantically identical fields (even if input `payload` keys or duplicate `tags` were ordered differently) satisfy `a == b` and `hash(a) == hash(b)`.

3. `clone_with_overrides(spec: TaskSpec, *, task_id: str | None = None, tenant: str | None = None, tool_name: str | None = None, payload: Mapping[str, object] | None = None, tags: Iterable[str] | None = None) -> TaskSpec`
   - Returns a new isolated `TaskSpec` with any non-`None` fields replaced, without mutating `spec` or aliasing caller override containers.

### Drill B Exports (`drill_b_ai_adapter.py`)

Audit and remediate `RunContext` and `RunContextBatcher`:
- Fix shared mutable metadata state across `add_run(...)` calls.
- Fix caller `retries: Sequence[int]` in-place mutation (`[*retries, next_attempt]`, never `.append(...)` on caller list).
- Fix `for_tenant(tenant: str)` identity comparison bug (`==` value equality, never `is`).
- Ensure `RunContext.metadata` cannot be mutated externally to corrupt stored batch history.

---

## Evaluation Command

```powershell
# From repository root:
.\go.ps1 -Module m01

# Or directly via uv:
uv run --no-sync python scripts/eval_module.py m01
```
