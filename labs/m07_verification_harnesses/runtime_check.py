"""Gate 5 runtime & AST invariant check for M07 Verification Harnesses."""

import ast
from pathlib import Path


def _is_decorator_named(node: ast.expr, target: str) -> bool:
    if isinstance(node, ast.Call):
        return _is_decorator_named(node.func, target)
    if isinstance(node, ast.Name):
        return node.id == target
    if isinstance(node, ast.Attribute):
        return node.attr == target
    return False


def _extract_max_examples(node: ast.expr) -> int | None:
    if not isinstance(node, ast.Call) or not _is_decorator_named(node.func, "settings"):
        return None
    for kw in node.keywords:
        if kw.arg == "max_examples" and isinstance(kw.value, ast.Constant):
            val = kw.value.value
            if isinstance(val, int) and not isinstance(val, bool):
                return val
    return None


def _check_hypothesis_ast(test_file: Path) -> tuple[bool, str]:
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    imports_hypothesis = False
    given_tests = 0
    settings_ge_100 = 0

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "hypothesis" or alias.name.startswith("hypothesis."):
                    imports_hypothesis = True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "hypothesis" or node.module.startswith("hypothesis.")
            ):
                imports_hypothesis = True
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            has_given = any(_is_decorator_named(dec, "given") for dec in node.decorator_list)
            if has_given:
                given_tests += 1
                max_ex_values = [
                    val
                    for dec in node.decorator_list
                    if (val := _extract_max_examples(dec)) is not None
                ]
                if any(v >= 100 for v in max_ex_values):
                    settings_ge_100 += 1

    if not imports_hypothesis:
        return False, "test_learner_a.py must import hypothesis and use @given property tests"
    if given_tests < 3:
        return (
            False,
            f"expected >=3 @given property test functions in test_learner_a.py, found {given_tests}",
        )
    if settings_ge_100 < 3:
        return (
            False,
            "each @given property test in test_learner_a.py should set @settings(max_examples>=100, ...)",
        )
    return True, f"{given_tests} Hypothesis @given tests verified"


def run_check(module_dir: Path) -> tuple[bool, str]:
    test_file = module_dir / "test_learner_a.py"
    if not test_file.is_file():
        return False, "missing test_learner_a.py"

    ast_ok, ast_msg = _check_hypothesis_ast(test_file)
    if not ast_ok:
        return False, ast_msg

    try:
        import drill_a_core
    except Exception as exc:
        return False, f"failed to import drill_a_core: {exc}"

    try:
        e1 = drill_a_core.Envelope("a:b", "c", "x|y", 1, {"b": 2, "a": 1})
        e2 = drill_a_core.Envelope("a", "b:c", "x|y", 1, {"a": 1, "b": 2})
        e3 = drill_a_core.Envelope("a:b", "c", "x|y", 1, {"a": 1, "b": 2})
        d1 = drill_a_core.canonical_digest(e1)
        d2 = drill_a_core.canonical_digest(e2)
        d3 = drill_a_core.canonical_digest(e3)
        if d1 == d2:
            return False, "delimiter collision detected in canonical_digest"
        if d1 != d3:
            return False, "canonical_digest differs across reordered dict keys"

        unicode_env = drill_a_core.Envelope("t", "id", "fn", 2, {"txt": "λ-ünîçødé"})
        round_tripped = drill_a_core.decode_envelope(drill_a_core.encode_envelope(unicode_env))
        if round_tripped != unicode_env:
            return False, "round-trip mismatch on non-ASCII Unicode payload"
    except Exception as exc:
        return False, f"runtime verification failed: {exc}"

    return True, f"{ast_msg}; canonical_digest collision-freedom & Unicode round-trip verified"
