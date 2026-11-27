"""5-Stage Evaluation Gate runner for Python 3.14 & SE Fundamentals Lab."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LABS_DIR = REPO_ROOT / "labs"
SOLUTIONS_DIR = REPO_ROOT / "solutions"

MODULES: tuple[str, ...] = (
    "m01_object_model",
    "m02_collections_complexity",
    "m03_domain_invariants",
    "m04_static_typing",
    "m05_lifecycles_generators",
    "m06_modular_architecture",
    "m07_verification_harnesses",
    "m08_structured_concurrency",
    "m09_transactions_idempotency",
    "m10_packaging_profiling_otel",
    "m11_security_boundaries",
    "m12_debugging_capstone",
)

REQUIRED_LAB_FILES: tuple[str, ...] = (
    "README.md",
    "drill_a_core.py",
    "test_acceptance_a.py",
    "test_learner_a.py",
    "seeded_bugs_a.py",
    "drill_b_ai_adapter.py",
    "test_acceptance_b.py",
    "runtime_check.py",
)

REQUIRED_SOLUTION_FILES: tuple[str, ...] = (
    "drill_a_core.py",
    "test_learner_a.py",
    "drill_b_ai_adapter.py",
)

MUTANT_CONFTEST_SOURCE = '''"""Injected by scripts/eval_module.py during Gate 4 mutant evaluation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def pytest_configure(config: object) -> None:
    mutant_id = os.environ.get("TASKLEDGER_MUTANT_ID")
    if not mutant_id:
        return
    import drill_a_core
    import seeded_bugs_a

    patcher = seeded_bugs_a.SEEDED_BUGS[mutant_id]
    target_attr = getattr(patcher, "target", None) or getattr(patcher, "_target_attr", None)
    if hasattr(patcher, "apply") and callable(patcher.apply):
        patcher.apply(drill_a_core)
    elif isinstance(patcher, type) and isinstance(target_attr, str):
        setattr(drill_a_core, target_attr, patcher)
    elif callable(patcher):
        patcher(drill_a_core)
    else:
        raise TypeError(f"Unsupported seeded bug entry for {mutant_id!r}: {type(patcher)!r}")
'''


@dataclass(slots=True, frozen=True)
class GateResult:
    gate_number: int
    name: str
    passed: bool
    summary: str
    details: str = ""


@dataclass(slots=True, frozen=True)
class ModuleEvalResult:
    slug: str
    used_solutions: bool
    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)


def resolve_modules(selector: str) -> list[str]:
    cleaned = selector.strip().replace("\\", "/").strip("/")
    if cleaned.startswith("labs/"):
        cleaned = cleaned.removeprefix("labs/")
    elif cleaned.startswith("solutions/"):
        cleaned = cleaned.removeprefix("solutions/")

    lower = cleaned.lower()
    if lower == "all":
        return list(MODULES)

    for slug in MODULES:
        prefix = slug.split("_", 1)[0]
        if lower in (slug, prefix):
            return [slug]

    valid = ", ".join(m.split("_", 1)[0] for m in MODULES)
    raise ValueError(f"Unknown module selector {selector!r}. Expected 'all', full slug, or one of: {valid}")


def _run_cmd(
    args: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
    timeout_sec: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}{existing_pp}" if existing_pp else str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout_sec,
        check=False,
    )


def _trim_output(stdout: str, stderr: str, max_lines: int = 30) -> str:
    combined = "\n".join(part.strip() for part in (stdout, stderr) if part.strip()).strip()
    if not combined:
        return ""
    lines = combined.splitlines()
    if len(lines) <= max_lines:
        return combined
    head = "\n".join(lines[: max_lines - 5])
    tail = "\n".join(lines[-5:])
    return f"{head}\n... ({len(lines) - max_lines} lines omitted) ...\n{tail}"


def _prepare_workspace(slug: str, dest: Path, *, use_solutions: bool) -> None:
    lab_src = LABS_DIR / slug
    if not lab_src.is_dir():
        raise FileNotFoundError(f"Missing lab directory: {lab_src}")

    missing_lab = [f for f in REQUIRED_LAB_FILES if not (lab_src / f).is_file()]
    if missing_lab:
        raise FileNotFoundError(f"Lab {slug} missing required files: {missing_lab}")

    shutil.copytree(
        lab_src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", ".hypothesis", "*.pyc"),
    )

    if use_solutions:
        sol_src = SOLUTIONS_DIR / slug
        if not sol_src.is_dir():
            raise FileNotFoundError(f"Missing solutions directory: {sol_src}")
        missing_sol = [f for f in REQUIRED_SOLUTION_FILES if not (sol_src / f).is_file()]
        if missing_sol:
            raise FileNotFoundError(f"Solutions {slug} missing required files: {missing_sol}")
        for item in sol_src.iterdir():
            if item.is_file() and item.suffix == ".py":
                shutil.copy2(item, dest / item.name)


def _gate1_ruff(work_dir: Path) -> GateResult:
    ruff_cfg = REPO_ROOT / "pyproject.toml"
    proc = _run_cmd(
        [sys.executable, "-m", "ruff", "check", "--config", str(ruff_cfg), "."],
        cwd=work_dir,
    )
    if proc.returncode == 0:
        return GateResult(1, "ruff check", True, "0 lint violations")
    return GateResult(
        1,
        "ruff check",
        False,
        "lint violations detected",
        _trim_output(proc.stdout, proc.stderr),
    )


def _gate2_pyright(work_dir: Path) -> GateResult:
    cfg_path = work_dir / "pyrightconfig.json"
    cfg_path.write_text(
        json.dumps(
            {
                "pythonVersion": "3.14",
                "typeCheckingMode": "strict",
                "reportMissingTypeStubs": False,
                "include": [
                    "drill_a_core.py",
                    "drill_b_ai_adapter.py",
                    "test_learner_a.py",
                    "test_acceptance_a.py",
                    "test_acceptance_b.py",
                    "seeded_bugs_a.py",
                    "runtime_check.py",
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    try:
        proc = _run_cmd(
            [
                sys.executable,
                "-m",
                "pyright",
                "--pythonpath",
                sys.executable,
                "--project",
                str(cfg_path),
            ],
            cwd=work_dir,
        )
    finally:
        cfg_path.unlink(missing_ok=True)

    if proc.returncode == 0:
        return GateResult(2, "pyright --strict", True, "0 errors, 0 warnings")
    return GateResult(
        2,
        "pyright --strict",
        False,
        "strict type check failed",
        _trim_output(proc.stdout, proc.stderr),
    )


def _gate3_oracle(work_dir: Path) -> GateResult:
    basetemp = work_dir.parent / "basetemp_g3"
    proc = _run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            f"--basetemp={basetemp}",
            "test_acceptance_a.py",
            "test_acceptance_b.py",
        ],
        cwd=work_dir,
    )
    if proc.returncode == 0:
        last_line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "acceptance suite passed"
        return GateResult(3, "Frozen Oracle (pytest)", True, last_line)
    return GateResult(
        3,
        "Frozen Oracle (pytest)",
        False,
        "acceptance tests failed",
        _trim_output(proc.stdout, proc.stderr),
    )


def _gate4_mutation(work_dir: Path) -> GateResult:
    basetemp_base = work_dir.parent / "basetemp_g4_base"
    baseline = _run_cmd(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            f"--basetemp={basetemp_base}",
            "test_learner_a.py",
        ],
        cwd=work_dir,
    )
    if baseline.returncode != 0:
        return GateResult(
            4,
            "Seeded-Bug Kill Rate",
            False,
            "test_learner_a.py failed on unmutated drill_a_core.py",
            _trim_output(baseline.stdout, baseline.stderr),
        )

    probe = _run_cmd(
        [
            sys.executable,
            "-c",
            "import json, seeded_bugs_a; print(json.dumps(list(seeded_bugs_a.SEEDED_BUGS.keys())))",
        ],
        cwd=work_dir,
    )
    if probe.returncode != 0:
        return GateResult(
            4,
            "Seeded-Bug Kill Rate",
            False,
            "unable to load SEEDED_BUGS from seeded_bugs_a.py",
            _trim_output(probe.stdout, probe.stderr),
        )

    mutant_ids: list[str] = json.loads(probe.stdout.strip())
    if len(mutant_ids) < 3:
        return GateResult(
            4,
            "Seeded-Bug Kill Rate",
            False,
            f"expected >=3 seeded bugs, found {len(mutant_ids)}",
        )

    conftest_path = work_dir / "conftest.py"
    conftest_path.write_text(MUTANT_CONFTEST_SOURCE, encoding="utf-8")
    killed: list[str] = []
    survived: list[str] = []
    errored: list[tuple[str, str]] = []
    try:
        for idx, mutant_id in enumerate(mutant_ids):
            mutant_tmp = work_dir.parent / f"basetemp_m_{idx}"
            run = _run_cmd(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=no",
                    "-p",
                    "no:cacheprovider",
                    f"--basetemp={mutant_tmp}",
                    "test_learner_a.py",
                ],
                cwd=work_dir,
                extra_env={"TASKLEDGER_MUTANT_ID": mutant_id},
            )
            if run.returncode == 1:
                killed.append(mutant_id)
            elif run.returncode == 0:
                survived.append(mutant_id)
            else:
                errored.append((mutant_id, _trim_output(run.stdout, run.stderr, max_lines=12)))
    finally:
        conftest_path.unlink(missing_ok=True)

    total = len(mutant_ids)
    rate_pct = int(round((len(killed) / total) * 100))
    if not survived and not errored:
        return GateResult(
            4,
            "Seeded-Bug Kill Rate",
            True,
            f"{len(killed)}/{total} mutants killed ({rate_pct}%)",
        )

    detail_parts: list[str] = []
    if survived:
        detail_parts.append(f"Surviving mutants (tests passed when they should fail): {', '.join(survived)}")
    for mid, err_txt in errored:
        detail_parts.append(f"Mutant {mid} crashed collection/harness:\n{err_txt}")
    return GateResult(
        4,
        "Seeded-Bug Kill Rate",
        False,
        f"{len(killed)}/{total} mutants killed ({rate_pct}%)",
        "\n".join(detail_parts),
    )


def _gate5_runtime(work_dir: Path) -> GateResult:
    snippet = (
        "import json, pathlib, runtime_check; "
        "ok, msg = runtime_check.run_check(pathlib.Path('.').resolve()); "
        "print(json.dumps({'ok': bool(ok), 'msg': str(msg)}))"
    )
    proc = _run_cmd([sys.executable, "-c", snippet], cwd=work_dir)
    if proc.returncode != 0:
        return GateResult(
            5,
            "Runtime Invariant",
            False,
            "runtime_check.py raised an unhandled exception",
            _trim_output(proc.stdout, proc.stderr),
        )
    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return GateResult(5, "Runtime Invariant", False, "runtime_check.py produced no output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return GateResult(
            5,
            "Runtime Invariant",
            False,
            "invalid JSON from runtime_check.py wrapper",
            _trim_output(proc.stdout, proc.stderr),
        )
    ok = bool(payload["ok"])
    msg = str(payload["msg"])
    return GateResult(
        5,
        "Runtime Invariant",
        ok,
        msg if ok else "invariant violated",
        "" if ok else msg,
    )


def evaluate_module(slug: str, *, use_solutions: bool = False) -> ModuleEvalResult:
    with tempfile.TemporaryDirectory(prefix=f"eval_{slug}_") as tmp_root:
        work_dir = Path(tmp_root) / slug
        _prepare_workspace(slug, work_dir, use_solutions=use_solutions)
        gates = (
            _gate1_ruff(work_dir),
            _gate2_pyright(work_dir),
            _gate3_oracle(work_dir),
            _gate4_mutation(work_dir),
            _gate5_runtime(work_dir),
        )
        return ModuleEvalResult(slug=slug, used_solutions=use_solutions, gates=gates)


def print_module_result(result: ModuleEvalResult) -> None:
    mode_tag = "SOLUTIONS" if result.used_solutions else "WORKSPACE"
    overall = "PASS" if result.passed else "FAIL"
    print(f"\n=== [{overall}] {result.slug} ({mode_tag}) ===")
    for gate in result.gates:
        status = "PASS" if gate.passed else "FAIL"
        print(f"  Gate {gate.gate_number} ({gate.name}): {status} - {gate.summary}")
        if not gate.passed and gate.details:
            indented = "\n".join(f"      {line}" for line in gate.details.splitlines())
            print(indented)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate one or all Python SE Fundamentals Lab modules across Gates 1-5."
    )
    parser.add_argument(
        "module",
        help="Module id ('m01'..'m12', full module slug, or 'all').",
    )
    parser.add_argument(
        "--use-solutions",
        action="store_true",
        help="Overlay reference files from solutions/<module_slug>/ into a temporary workspace before running gates.",
    )
    args = parser.parse_args(argv)

    try:
        targets = resolve_modules(args.module)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    results: list[ModuleEvalResult] = []
    for slug in targets:
        res = evaluate_module(slug, use_solutions=args.use_solutions)
        print_module_result(res)
        results.append(res)

    passed_count = sum(1 for r in results if r.passed)
    print(f"\nSummary: {passed_count}/{len(results)} module(s) passed all 5 gates.")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
