"""Gate 5 runtime invariant check for M03 (`m03_domain_invariants`)."""

from __future__ import annotations

import ast
from pathlib import Path


def run_check(module_dir: Path) -> tuple[bool, str]:
    for filename in ("drill_a_core.py", "drill_b_ai_adapter.py"):
        src = (module_dir / filename).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=filename)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                return (
                    False,
                    f"{filename}:{node.lineno} uses `assert` for validation (stripped under python -O); raise DomainValidationError instead",
                )

    import drill_a_core
    import drill_b_ai_adapter

    q = drill_a_core.parse_new_task(
        {
            "task_id": "inv-1",
            "tenant_id": "acme",
            "scheduled_for": "2025-07-01",
            "max_attempts": 1,
        }
    )
    leased = drill_a_core.lease_task(q, worker_id="w-1", lease_token=1)
    dlq = drill_a_core.fail_task(leased, lease_token=1, error_reason="boom")
    if not isinstance(dlq, drill_a_core.DeadLetterTask):
        return False, "attempt == max_attempts must transition directly to DeadLetterTask"

    sched = drill_b_ai_adapter.PolicySchedule.from_json_dicts(
        [
            {
                "rule_id": "old",
                "tenant_id": "acme",
                "max_attempts": 2,
                "effective_from": "2025-01-01",
                "effective_until": "2025-07-01",
            },
            {
                "rule_id": "new",
                "tenant_id": "acme",
                "max_attempts": 4,
                "effective_from": "2025-07-01",
                "effective_until": None,
            },
        ]
    )
    hit = sched.resolve(drill_a_core.TenantId.parse("acme"), drill_a_core.UtcDate.parse("2025-07-01"))
    if not isinstance(hit, drill_b_ai_adapter.PolicyRule) or hit.rule_id != "new":
        return False, "Exact cutover date 2025-07-01 did not resolve to the new half-open policy rule"

    return True, "Zero `assert` statements in domain code; exact cutover & exhaustion invariants verified"
