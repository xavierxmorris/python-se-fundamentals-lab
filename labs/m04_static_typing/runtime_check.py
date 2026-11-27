"""Gate 5 runtime & AST check for M04 (`m04_static_typing`).

Enforces:
1. Zero `Any` or `cast` imports/names in `drill_a_core.py`, `drill_b_ai_adapter.py`, and `test_learner_a.py`.
2. Zero `# type: ignore` comments in those three files.
3. Presence of PEP 695 `ast.TypeAlias` (`type ... = ...`) and `type_params` in `drill_a_core.py`.
"""

import ast
import io
import re
import tokenize
from pathlib import Path

FORBIDDEN_TYPING_IDENTIFIERS: frozenset[str] = frozenset({"Any", "cast"})
TARGET_FILES: tuple[str, ...] = (
    "drill_a_core.py",
    "drill_b_ai_adapter.py",
    "test_learner_a.py",
)
TYPE_IGNORE_RE = re.compile(r"type\s*:\s*ignore", re.IGNORECASE)


def _find_forbidden_ast_usages(tree: ast.AST, filename: str) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in FORBIDDEN_TYPING_IDENTIFIERS:
                    violations.append(f"{filename}:{node.lineno} imports forbidden `{alias.name}`")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_TYPING_IDENTIFIERS:
            violations.append(f"{filename}:{node.lineno} references forbidden `{node.id}`")
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_TYPING_IDENTIFIERS:
            violations.append(f"{filename}:{node.lineno} references forbidden `.{node.attr}`")
    return violations


def _find_type_ignore_comments(source: str, filename: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT and TYPE_IGNORE_RE.search(tok.string):
            violations.append(f"{filename}:{tok.start[0]} contains forbidden `type: ignore` comment")
    return violations


def run_check(module_dir: Path) -> tuple[bool, str]:
    violations: list[str] = []
    core_has_type_alias = False
    core_has_type_params = False

    for fname in TARGET_FILES:
        fpath = module_dir / fname
        if not fpath.is_file():
            return False, f"Missing required file: {fname}"
        source = fpath.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=fname)
        except SyntaxError as exc:
            return False, f"SyntaxError in {fname}: {exc}"

        violations.extend(_find_forbidden_ast_usages(tree, fname))
        violations.extend(_find_type_ignore_comments(source, fname))

        if fname == "drill_a_core.py":
            for node in ast.walk(tree):
                if isinstance(node, ast.TypeAlias):
                    core_has_type_alias = True
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.TypeAlias)) and node.type_params:
                    core_has_type_params = True

    if not core_has_type_alias:
        violations.append("drill_a_core.py must use PEP 695 `type ... = ...` (`ast.TypeAlias`)")
    if not core_has_type_params:
        violations.append("drill_a_core.py must use PEP 695 generic type parameters (`[T]`)")

    if violations:
        return False, "; ".join(violations)
    return True, "AST & comment audit passed: 0 Any/cast/type:ignore, PEP 695 verified"
