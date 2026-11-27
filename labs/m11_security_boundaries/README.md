# M11 · Security & Trust Boundaries: Path, Subprocess, SQL & AI/Tool Output Gates

## Entry Contract & Overview

In `taskledger`, both external user parameters and AI/MCP tool outputs cross untrusted boundaries. Every file path, outbound webhook/API URL, subprocess argument vector, SQL sort clause, and JSON tool payload must pass structural confinement gates before execution or persistence.

### Exported Surface

#### Drill A (`drill_a_core.py`)
- `class SecurityBoundaryError(ValueError)`
- `@dataclass(slots=True, frozen=True) class SafeToolResult`:
  - `tool: str`
  - `status: Literal["ok", "error"]`
  - `items: tuple[str, ...]`
- `resolve_sandbox_path(sandbox_root: Path, untrusted_rel: str) -> Path`
- `validate_outbound_url(raw_url: str, allowed_hosts: AbstractSet[str]) -> str`
- `build_safe_command(binary: str, args: Sequence[str], *, allowed_binaries: AbstractSet[str]) -> tuple[str, ...]`
- `parse_untrusted_tool_output(raw_bytes: bytes, *, max_bytes: int = 16_384, max_items: int = 50) -> SafeToolResult`

#### Drill B (`drill_b_ai_adapter.py`)
- `@dataclass(slots=True, frozen=True) class ArtifactRow`
- `class CommandExecutor(Protocol)`
- `class WorkspaceArtifactRunner`

---

## Drills

1. **Drill A — Cold-Turkey Core (AI OFF):**
   Implement `drill_a_core.py` from its docstring contract and write adversarial boundary tests in `test_learner_a.py` killing all 4 mutants in `seeded_bugs_a.py` (sibling-prefix path traversal, `user@host` & IPv6-mapped loopback SSRF, oversized/extra-key JSON payloads, and missing `--` / newline injection in command vectors).
2. **Drill B — Spec-First AI Pair:**
   Audit and remediate `WorkspaceArtifactRunner` in `drill_b_ai_adapter.py` to eliminate all 4 classic vulnerabilities: `os.path.commonprefix` path traversal, `subprocess.run(..., shell=True)` command injection, f-string SQL `ORDER BY` injection without column allowlisting, and unbounded JSON manifest loading.

---

## Evaluation Commands

```powershell
.\go.ps1 -Module m11
uv run --no-sync python scripts/eval_module.py m11
```
