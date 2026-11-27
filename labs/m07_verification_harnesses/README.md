# M07 · Executable Verification: Contract Fakes, Golden Masters & `Hypothesis`

## Entry Contract

In the AI era, `MagicMock` tests that mirror an implementation's own assumptions routinely miss delimiter collisions, key-order canonicalism bugs, Unicode corruption, and binary floating-point drift. This module drills **property-based testing (`Hypothesis`)**, **golden-master parity harnesses**, and **contract-verified storage fakes** on the `taskledger` envelope & fee-reconciliation boundary.

### Exported Surface (`drill_a_core.py` — Cold-Turkey Core, AI OFF)

- `type JsonScalar = str | int | bool | None`
- `type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]`
- `@dataclass(slots=True, frozen=True) class Envelope`:
  - `tenant: str`
  - `task_id: str`
  - `tool: str`
  - `version: int`
  - `payload: dict[str, JsonValue]`
- `def encode_envelope(env: Envelope) -> bytes` — deterministic, lossless canonical UTF-8 JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`), rejecting floats/`NaN`/non-`JsonValue` values (and `bool` for `version`) with `TypeError` and `version < 1` with `ValueError`.
- `def decode_envelope(raw: bytes) -> Envelope` — strict inverse validating schema, exact required keys, and field types (`bool` must never be accepted for `version: int`), raising `ValueError` on malformed JSON, schema violations, floats, or invalid versions.
- `def canonical_digest(env: Envelope) -> str` — collision-free SHA-256 hex digest over canonical framing so distinct `(tenant, task_id, tool)` triples containing `":"`, `"\x00"`, or `"|"` never collide and reordered dict keys produce identical digests.

### Exported Surface (`drill_b_ai_adapter.py` — Spec-First AI Pair)

- `ChargeEntry`, `ReconcileSummary`, `LedgerStoragePort` (`Protocol`), `InMemoryStorageFake`, `JsonFileStorage`, and `reconcile_charges(entries: Sequence[ChargeEntry]) -> ReconcileSummary`.
- Fix binary float rounding/drift (`Decimal` exact cents arithmetic), non-canonical tie-break sorting on matching timestamps, and `JsonFileStorage` contract divergence against `InMemoryStorageFake`.

## Workflow

1. **Drill A (AI OFF):** Implement `drill_a_core.py` from its docstring specification, then write genuine `@hypothesis.given(...)` (`@settings(max_examples=100, deadline=None)`) property tests and boundary error tests in `test_learner_a.py` to kill 100% of mutants in `seeded_bugs_a.py`.
2. **Drill B (Spec-First AI Pair):** Audit `drill_b_ai_adapter.py` against `test_acceptance_b.py` (golden-master vectors + shared `LedgerStoragePort` contract suite) and remediate all defects.

## Evaluation Commands

```powershell
.\go.ps1 -Module m07
uv run --no-sync python scripts/eval_module.py m07
```
