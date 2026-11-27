"""Reference solution for M03 Drill B: Half-Open PolicySchedule & Overlap Detection."""

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


def _intervals_overlap(a: PolicyRule, b: PolicyRule) -> bool:
    # Half-open intervals [a.from, a.until) and [b.from, b.until) overlap iff:
    # a.from < b.until (or b.until is None) AND b.from < a.until (or a.until is None)
    a_starts_before_b_ends = b.effective_until is None or a.effective_from < b.effective_until
    b_starts_before_a_ends = a.effective_until is None or b.effective_from < a.effective_until
    return a_starts_before_b_ends and b_starts_before_a_ends


class PolicySchedule:
    """Immutable schedule of non-overlapping per-tenant PolicyRules."""

    def __init__(self, rules: Sequence[PolicyRule]) -> None:
        by_tenant: dict[TenantId, list[PolicyRule]] = {}
        for rule in rules:
            if rule.effective_until is not None and rule.effective_until <= rule.effective_from:
                raise DomainValidationError(
                    "effective_until",
                    "effective_until must be strictly after effective_from",
                )
            existing = by_tenant.setdefault(rule.tenant_id, [])
            for prev in existing:
                if _intervals_overlap(prev, rule):
                    raise PolicyConflictError(
                        f"Overlapping policy rules {prev.rule_id!r} and {rule.rule_id!r} "
                        f"for tenant {rule.tenant_id.value!r}"
                    )
            existing.append(rule)
        self._rules = tuple(rules)

    @classmethod
    def from_json_dicts(cls, raw_rules: Sequence[Mapping[str, object]]) -> PolicySchedule:
        parsed: list[PolicyRule] = []
        for raw in raw_rules:
            rule_id_obj = raw.get("rule_id")
            if not isinstance(rule_id_obj, str) or not rule_id_obj.strip() or rule_id_obj != rule_id_obj.strip():
                raise DomainValidationError("rule_id", "rule_id must be a non-blank unpadded str")

            tenant_obj = raw.get("tenant_id")
            if not isinstance(tenant_obj, str):
                raise DomainValidationError("tenant_id", "missing or non-string tenant_id")

            from_obj = raw.get("effective_from")
            if not isinstance(from_obj, str):
                raise DomainValidationError("effective_from", "missing or non-string effective_from")

            if "effective_until" not in raw:
                raise DomainValidationError("effective_until", "effective_until key is required (str or None)")
            until_obj = raw["effective_until"]
            if until_obj is None:
                until_date: UtcDate | None = None
            elif isinstance(until_obj, str):
                until_date = UtcDate.parse(until_obj)
            else:
                raise DomainValidationError("effective_until", "must be YYYY-MM-DD str or None")

            max_att_obj = raw.get("max_attempts")
            if isinstance(max_att_obj, bool) or not isinstance(max_att_obj, int) or max_att_obj < 1:
                raise DomainValidationError("max_attempts", "max_attempts must be int >= 1")

            parsed.append(
                PolicyRule(
                    rule_id=rule_id_obj,
                    tenant_id=TenantId.parse(tenant_obj),
                    max_attempts=max_att_obj,
                    effective_from=UtcDate.parse(from_obj),
                    effective_until=until_date,
                )
            )
        return cls(parsed)

    def resolve(self, tenant_id: TenantId, on_date: UtcDate) -> PolicyRule | NoActivePolicy:
        for rule in self._rules:
            if rule.tenant_id == tenant_id and rule.effective_from <= on_date and (
                rule.effective_until is None or on_date < rule.effective_until
            ):
                return rule
        return NoActivePolicy(tenant_id=tenant_id, on_date=on_date)
