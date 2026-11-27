"""Reference solution for M07 Drill B: Exact Decimal Reconciler & Contract-Matched Storage."""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Final, Protocol, TypeIs, runtime_checkable

_CENT: Final[Decimal] = Decimal("0.01")


@dataclass(slots=True, frozen=True)
class ChargeEntry:
    charge_id: str
    tenant: str
    timestamp: int
    amount_usd: str
    fee_usd: str


@dataclass(slots=True, frozen=True)
class ReconcileSummary:
    gross_usd: str
    fee_usd: str
    net_usd: str
    net_cents: int
    ordered_charge_ids: tuple[str, ...]


@runtime_checkable
class LedgerStoragePort(Protocol):
    def save(self, entry: ChargeEntry) -> None: ...
    def list_by_tenant(self, tenant: str) -> list[ChargeEntry]: ...
    def list_all(self) -> list[ChargeEntry]: ...


def _sort_key(entry: ChargeEntry) -> tuple[int, str]:
    return (entry.timestamp, entry.charge_id)


def _parse_cents_decimal(raw_usd: str) -> Decimal:
    return Decimal(raw_usd).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _format_usd(amount: Decimal) -> str:
    return f"{amount.quantize(_CENT, rounding=ROUND_HALF_EVEN):.2f}"


def _is_obj_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _is_obj_dict(val: object) -> TypeIs[dict[object, object]]:
    return isinstance(val, dict)


class InMemoryStorageFake:
    def __init__(self) -> None:
        self._by_id: dict[str, ChargeEntry] = {}

    def save(self, entry: ChargeEntry) -> None:
        self._by_id[entry.charge_id] = entry

    def list_by_tenant(self, tenant: str) -> list[ChargeEntry]:
        matches = [e for e in self._by_id.values() if e.tenant == tenant]
        return sorted(matches, key=_sort_key)

    def list_all(self) -> list[ChargeEntry]:
        return sorted(self._by_id.values(), key=_sort_key)


class JsonFileStorage:
    def __init__(self, file_path: Path) -> None:
        self._path = file_path

    def save(self, entry: ChargeEntry) -> None:
        by_id = {existing.charge_id: existing for existing in self._load_entries()}
        by_id[entry.charge_id] = entry
        ordered = sorted(by_id.values(), key=_sort_key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item) for item in ordered]
        self._path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def list_by_tenant(self, tenant: str) -> list[ChargeEntry]:
        return [e for e in self.list_all() if e.tenant == tenant]

    def list_all(self) -> list[ChargeEntry]:
        return sorted(self._load_entries(), key=_sort_key)

    def _load_entries(self) -> list[ChargeEntry]:
        if not self._path.exists():
            return []
        parsed: object = json.loads(self._path.read_text(encoding="utf-8"))
        if not _is_obj_list(parsed):
            raise ValueError("Corrupt ledger JSON: expected top-level list")
        entries: list[ChargeEntry] = []
        for item in parsed:
            if not _is_obj_dict(item):
                raise ValueError("Corrupt ledger entry: expected JSON object")
            charge_id = item.get("charge_id")
            tenant = item.get("tenant")
            timestamp = item.get("timestamp")
            amount_usd = item.get("amount_usd")
            fee_usd = item.get("fee_usd")
            if (
                not isinstance(charge_id, str)
                or not isinstance(tenant, str)
                or isinstance(timestamp, bool)
                or not isinstance(timestamp, int)
                or not isinstance(amount_usd, str)
                or not isinstance(fee_usd, str)
            ):
                raise ValueError("Corrupt ledger entry fields")
            entries.append(
                ChargeEntry(
                    charge_id=charge_id,
                    tenant=tenant,
                    timestamp=timestamp,
                    amount_usd=amount_usd,
                    fee_usd=fee_usd,
                )
            )
        return entries


def reconcile_charges(entries: Sequence[ChargeEntry]) -> ReconcileSummary:
    ordered = sorted(entries, key=_sort_key)
    gross = sum((_parse_cents_decimal(e.amount_usd) for e in ordered), start=Decimal("0.00"))
    fees = sum((_parse_cents_decimal(e.fee_usd) for e in ordered), start=Decimal("0.00"))
    net = gross - fees
    net_cents = int((net * 100).to_integral_value(rounding=ROUND_HALF_EVEN))
    return ReconcileSummary(
        gross_usd=_format_usd(gross),
        fee_usd=_format_usd(fees),
        net_usd=_format_usd(net),
        net_cents=net_cents,
        ordered_charge_ids=tuple(e.charge_id for e in ordered),
    )
