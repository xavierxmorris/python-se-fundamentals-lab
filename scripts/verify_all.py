"""End-to-end repository verifier:
1) Confirms every untouched starter module in labs/ fails Gate 3 and Gate 4 cleanly (non-vacuous gates).
2) Confirms all 12 reference solutions in solutions/ pass Gates 1-5 at 100%.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_module import MODULES, evaluate_module, print_module_result


def main() -> int:
    print("======================================================================")
    print("STAGE A: Verifying untouched starter labs fail Gate 3 & Gate 4 cleanly")
    print("======================================================================")
    starter_errors: list[str] = []
    for slug in MODULES:
        res = evaluate_module(slug, use_solutions=False)
        by_num = {g.gate_number: g for g in res.gates}
        g3 = by_num[3]
        g4 = by_num[4]
        if res.passed:
            starter_errors.append(f"{slug}: untouched starter unexpectedly passed all gates!")
        if g3.passed:
            starter_errors.append(f"{slug}: untouched starter unexpectedly passed Gate 3 (Frozen Oracle)!")
        if g4.passed:
            starter_errors.append(f"{slug}: untouched starter unexpectedly passed Gate 4 (Seeded-Bug Kill Rate)!")
        status = "OK (expected starter fail)" if (not g3.passed and not g4.passed) else "UNEXPECTED PASS"
        print(f"  [{status}] {slug}: Gate3={'PASS' if g3.passed else 'FAIL'}, Gate4={'PASS' if g4.passed else 'FAIL'}")

    if starter_errors:
        print("\nStarter sanity verification FAILED:", file=sys.stderr)
        for err in starter_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("\n======================================================================")
    print("STAGE B: Verifying all 12 reference solutions pass Gates 1-5 (100%)")
    print("======================================================================")
    solution_failures: list[str] = []
    for slug in MODULES:
        res = evaluate_module(slug, use_solutions=True)
        print_module_result(res)
        if not res.passed:
            solution_failures.append(slug)

    if solution_failures:
        print(
            f"\nVerification FAILED: {len(solution_failures)}/{len(MODULES)} solution module(s) failed: "
            f"{', '.join(solution_failures)}",
            file=sys.stderr,
        )
        return 1

    print(
        "\nALL CHECKS PASSED: 12/12 untouched starters failed non-vacuously and "
        "12/12 reference solutions passed Gates 1-5!"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
