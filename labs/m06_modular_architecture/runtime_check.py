"""Gate 5 architectural AST & runtime check for M06 (`m06_modular_architecture`).

Enforces:
1. `drill_a_core.py` imports ZERO side-effecting stdlib modules (`time`, `random`, `os`,
   `sqlite3`, `subprocess`, `socket`) and uses `slots=True` frozen dataclasses.
2. `drill_b_ai_adapter.py` contains ZERO `time.sleep` calls and ZERO module-level mutable
   `list` / `dict` / `set` state.
3. `test_learner_a.py` uses ZERO `unittest.mock` (`Mock`, `MagicMock`, `patch`) or `monkeypatch`.
"""

import ast
from pathlib import Path

FORBIDDEN_CORE_IMPORTS: frozenset[str] = frozenset(
    {"time", "random", "os", "sqlite3", "subprocess", "socket"}
)
MUTABLE_FACTORY_CALLS: frozenset[str] = frozenset({"list", "dict", "set", "defaultdict", "deque"})
FORBIDDEN_TEST_MOCK_NAMES: frozenset[str] = frozenset(
    {"monkeypatch", "MagicMock", "Mock", "NonCallableMock", "AsyncMock"}
)


def _scan_core_imports(tree: ast.Module) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in FORBIDDEN_CORE_IMPORTS:
                    violations.append(
                        f"drill_a_core.py:{node.lineno} imports forbidden module `{root}`"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            root = node.module.split(".", 1)[0]
            if root in FORBIDDEN_CORE_IMPORTS:
                violations.append(
                    f"drill_a_core.py:{node.lineno} imports from forbidden module `{root}`"
                )
    return violations


def _is_mutable_expr(expr: ast.expr | None) -> bool:
    if expr is None:
        return False
    if isinstance(
        expr,
        (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp),
    ):
        return True
    if isinstance(expr, ast.Call):
        if isinstance(expr.func, ast.Name) and expr.func.id in MUTABLE_FACTORY_CALLS:
            return True
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in MUTABLE_FACTORY_CALLS:
            return True
    return False


def _scan_adapter_ast(tree: ast.Module) -> list[str]:
    violations: list[str] = []
    sleep_aliases: set[str] = set()
    time_aliases: set[str] = set()

    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and _is_mutable_expr(stmt.value):
            violations.append(
                f"drill_b_ai_adapter.py:{stmt.lineno} defines forbidden module-level mutable state"
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    time_aliases.add(alias.asname or "time")
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            for alias in node.names:
                if alias.name == "sleep":
                    sleep_aliases.add(alias.asname or "sleep")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            is_direct_sleep = isinstance(node.func, ast.Name) and node.func.id in sleep_aliases
            is_attr_sleep = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "sleep"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in time_aliases
            )
            if is_direct_sleep or is_attr_sleep:
                violations.append(
                    f"drill_b_ai_adapter.py:{node.lineno} calls forbidden `time.sleep`"
                )
    return violations


def _scan_learner_tests_ast(tree: ast.Module) -> list[str]:
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mock" or alias.name.startswith("unittest.mock"):
                    violations.append(
                        f"test_learner_a.py:{node.lineno} imports forbidden `{alias.name}`"
                    )
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module == "mock" or node.module.startswith("unittest.mock"):
                violations.append(
                    f"test_learner_a.py:{node.lineno} imports from forbidden `{node.module}`"
                )
            if node.module == "unittest":
                for alias in node.names:
                    if alias.name == "mock":
                        violations.append(
                            f"test_learner_a.py:{node.lineno} imports forbidden `unittest.mock`"
                        )
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_TEST_MOCK_NAMES:
            violations.append(
                f"test_learner_a.py:{node.lineno} references forbidden `{node.id}`"
            )
        elif isinstance(node, ast.arg) and node.arg == "monkeypatch":
            violations.append(
                f"test_learner_a.py:{node.lineno} uses forbidden `monkeypatch` fixture"
            )
    return violations


def run_check(module_dir: Path) -> tuple[bool, str]:
    parsed: dict[str, ast.Module] = {}
    for fname in ("drill_a_core.py", "drill_b_ai_adapter.py", "test_learner_a.py"):
        fpath = module_dir / fname
        if not fpath.is_file():
            return False, f"Missing required file: {fname}"
        try:
            parsed[fname] = ast.parse(fpath.read_text(encoding="utf-8"), filename=fname)
        except SyntaxError as exc:
            return False, f"SyntaxError in {fname}: {exc}"

    violations: list[str] = []
    violations.extend(_scan_core_imports(parsed["drill_a_core.py"]))
    violations.extend(_scan_adapter_ast(parsed["drill_b_ai_adapter.py"]))
    violations.extend(_scan_learner_tests_ast(parsed["test_learner_a.py"]))
    if violations:
        return False, "; ".join(violations)

    import drill_a_core

    sample_policy = drill_a_core.RetryPolicy()
    if hasattr(sample_policy, "__dict__"):
        return False, "RetryPolicy must use @dataclass(slots=True, frozen=True)"

    try:
        decision = drill_a_core.decide_next_action(
            attempts=(),
            circuit_failures_sec=(),
            circuit_opened_at_sec=None,
            policy=sample_policy,
            now_sec=10.0,
            jitter_ratio=0.5,
        )
    except NotImplementedError as exc:
        return False, f"decide_next_action not implemented: {exc}"

    if decision != drill_a_core.RunNow(attempt_no=1):
        return False, f"Unexpected initial decision: {decision!r}"
    if hasattr(decision, "__dict__"):
        return False, "PlanDecision variants must use @dataclass(slots=True, frozen=True)"

    return (
        True,
        "AST purity audit passed: 0 I/O/clock imports in core, 0 sleep/global state in adapter, 0 mocks/monkeypatch in tests",
    )
