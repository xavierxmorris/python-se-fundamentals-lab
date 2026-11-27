"""Gate 5 runtime & AST security invariant check for M11 (`m11_security_boundaries`)."""

from __future__ import annotations

import ast
import json
import sqlite3
import tempfile
from pathlib import Path

_FORBIDDEN_CALL_NAMES = frozenset({"eval", "exec"})
_FORBIDDEN_IMPORTS = frozenset({"pickle"})


def _scan_ast_violations(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=py_file.name)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".", 1)[0]
                if root_mod in _FORBIDDEN_IMPORTS:
                    violations.append(f"{py_file.name}:{node.lineno} imports forbidden '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            mod_name = node.module or ""
            if mod_name.split(".", 1)[0] in _FORBIDDEN_IMPORTS:
                violations.append(f"{py_file.name}:{node.lineno} imports from forbidden '{mod_name}'")
            for alias in node.names:
                if alias.name == "commonprefix":
                    violations.append(
                        f"{py_file.name}:{node.lineno} imports insecure 'commonprefix'"
                    )
        elif isinstance(node, ast.Attribute):
            if node.attr == "commonprefix":
                violations.append(
                    f"{py_file.name}:{node.lineno} uses insecure 'os.path.commonprefix'"
                )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALL_NAMES:
                violations.append(f"{py_file.name}:{node.lineno} calls forbidden '{node.func.id}()'")
            if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_CALL_NAMES:
                violations.append(
                    f"{py_file.name}:{node.lineno} calls forbidden '.{node.func.attr}()'"
                )
            for kw in node.keywords:
                if kw.arg == "shell" and not (
                    isinstance(kw.value, ast.Constant) and kw.value.value is False
                ):
                    violations.append(
                        f"{py_file.name}:{node.lineno} passes non-False 'shell=' keyword"
                    )
    return violations


def run_check(module_dir: Path) -> tuple[bool, str]:
    """Verify AST bans and adversarial path/URL/payload confinement gates."""
    for target_name in ("drill_a_core.py", "drill_b_ai_adapter.py"):
        target_path = module_dir / target_name
        if not target_path.is_file():
            return False, f"Missing {target_name}"
        ast_issues = _scan_ast_violations(target_path)
        if ast_issues:
            return False, "; ".join(ast_issues)

    try:
        from drill_a_core import (
            SecurityBoundaryError,
            parse_untrusted_tool_output,
            resolve_sandbox_path,
            validate_outbound_url,
        )
        from drill_b_ai_adapter import WorkspaceArtifactRunner
    except Exception as exc:
        return False, f"Failed to import M11 modules: {exc}"

    with tempfile.TemporaryDirectory(prefix="m11_gate5_") as tmp:
        base = Path(tmp)
        sandbox = base / "sandbox"
        sandbox.mkdir()
        sibling = base / "sandbox_evil"
        sibling.mkdir()
        (sibling / "leak.json").write_text(
            json.dumps({"tool": "leak", "status": "ok", "items": []}),
            encoding="utf-8",
        )

        # 1. Sibling-prefix traversal check
        try:
            resolve_sandbox_path(sandbox, "../sandbox_evil/leak.json")
            return False, "resolve_sandbox_path allowed '../sandbox_evil/leak.json' bypass"
        except SecurityBoundaryError:
            pass
        except Exception as exc:
            return False, f"resolve_sandbox_path raised unexpected exception: {exc!r}"

        # 2. URL userinfo & IPv6-mapped loopback SSRF checks
        for bad_url in (
            "https://user@allowed.example.com/hook",
            "https://[::ffff:127.0.0.1]/admin",
        ):
            try:
                validate_outbound_url(bad_url, {"allowed.example.com", "::ffff:127.0.0.1"})
                return False, f"validate_outbound_url allowed SSRF vector {bad_url!r}"
            except SecurityBoundaryError:
                pass
            except Exception as exc:
                return False, f"validate_outbound_url raised unexpected exception: {exc!r}"

        # 3. 32 KiB oversized payload rejection
        oversized = (
            b'{"tool":"scan","status":"ok","items":["' + (b"A" * (32 * 1024)) + b'"]}'
        )
        try:
            parse_untrusted_tool_output(oversized)
            return False, "parse_untrusted_tool_output accepted 32 KiB payload (>16 KiB limit)"
        except SecurityBoundaryError:
            pass
        except Exception as exc:
            return False, f"parse_untrusted_tool_output raised unexpected exception: {exc!r}"

        # 4. WorkspaceArtifactRunner end-to-end boundary checks
        oversized_file = sandbox / "oversized.json"
        oversized_file.write_bytes(oversized)
        conn = sqlite3.connect(":memory:")
        try:
            runner = WorkspaceArtifactRunner(sandbox, conn)
            try:
                runner.load_artifact_manifest("../sandbox_evil/leak.json")
                return False, "WorkspaceArtifactRunner allowed sibling-prefix manifest read"
            except SecurityBoundaryError:
                pass

            try:
                runner.load_artifact_manifest("oversized.json")
                return False, "WorkspaceArtifactRunner accepted 32 KiB manifest"
            except SecurityBoundaryError:
                pass
        finally:
            conn.close()

    return (
        True,
        "AST clean (0 shell=True/eval/exec/pickle/commonprefix); sibling-prefix, user@host, "
        "[::ffff:127.0.0.1], and 32 KiB payload vectors blocked",
    )
