"""M03 Drill B (Spec-First AI Pair): PolicySchedule Boundary & Half-Open Interval Bugs.

Audit and remediate the 3 domain-invariant defects in this AI-generated schedule parser:
1. Silently coerces missing/invalid fields (`str(raw.get("tenant_id", ""))`) instead of
   parsing through `TenantId.parse` / `UtcDate.parse` and raising `DomainValidationError`.
2. Uses closed `<= effective_until` comparison instead of half-open `[effective_from, effective_until)`,
   causing cutover day `old_until == new_from` (`2025-07-01`) to match the old rule or false-conflict!
3. Fails to detect overlapping policy windows for the same tenant at schedule construction time
   (`PolicyConflictError` must be raised when two rules for the same tenant overlap, or when
   `effective_until <= effective_from`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from drill_a_core import DomainValidationError, TenantId, UtcDate


class PolicyConflictError(ValueError):
    """Raised when two policy rules for the same tenant have overlapping effective intervals."""


@dataclass(slots=True, frozen=True)
class NoActivePolicy:
    """Explicit result when no policy covers `(tenant_id, on_date)`."""

    tenant_id: TenantId
    on_date: UtcDate


@dataclass(slots=True, frozen=True)
class PolicyRule:
    """Effective retry policy over half-open interval `[effective_from, effective_until)`."""

    rule_id: str
    tenant_id: TenantId
    max_attempts: int
    effective_from: UtcDate
    effective_until: UtcDate | None


class PolicySchedule:
    """Immutable schedule of non-overlapping per-tenant PolicyRules."""

    def __init__(self, rules: Sequence[PolicyRule]) -> None:
        self._rules = tuple(rules)

    @classmethod
    def from_json_dicts(cls, raw_rules: Sequence[Mapping[str, object]]) -> PolicySchedule:
        parsed: list[PolicyRule] = []
        for raw in raw_rules:
            # AI BUG 1: string slicing & silent fallback instead of strict boundary parsing
            rule_id = str(raw.get("rule_id", "")).strip()
            tenant_raw = str(raw.get("tenant_id", "default"))
            from_raw = str(raw.get("effective_from", ""))[:10]
            until_obj = raw.get("effective_until")
            max_att_obj = raw.get("max_attempts", 3)
            max_att = max_att_obj if isinstance(max_att_obj, int) else 3

            if not rule_id:
                raise DomainValidationError("rule_id", "missing rule_id")

            until_date = UtcDate.parse(str(until_obj)[:10]) if until_obj is not None else None
            parsed.append(
                PolicyRule(
                    rule_id=rule_id,
                    tenant_id=TenantId.parse(tenant_raw),
                    max_attempts=max_att,
                    effective_from=UtcDate.parse(from_raw),
                    effective_until=until_date,
                )
            )
        # AI BUG 3: never validates `effective_until > effective_from` or checks interval overlaps!
        return cls(parsed)

    def resolve(self, tenant_id: TenantId, on_date: UtcDate) -> PolicyRule | NoActivePolicy:
        for rule in self._rules:
            # AI BUG 2: closed `<=` upper bound breaks half-open cutover day!
            if (
                rule.tenant_id == tenant_id
                and rule.effective_from <= on_date
                and (rule.effective_until is None or on_date <= rule.effective_until)
            ):
                return rule
        return NoActivePolicy(tenant_id=tenant_id, on_date=on_date)
