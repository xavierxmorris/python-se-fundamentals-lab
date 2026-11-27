"""M07 Drill B (Spec-First AI Pair): Batch Charge Reconciler & Ledger Storage Adapters."""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


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


class InMemoryStorageFake:
    def __init__(self) -> None:
        self._by_id: dict[str, ChargeEntry] = {}

    def save(self, entry: ChargeEntry) -> None:
        self._by_id[entry.charge_id] = entry

    def list_by_tenant(self, tenant: str) -> list[ChargeEntry]:
        matches = [e for e in self._by_id.values() if e.tenant == tenant]
        return sorted(matches, key=lambda e: (e.timestamp, e.charge_id))

    def list_all(self) -> list[ChargeEntry]:
        return sorted(self._by_id.values(), key=lambda e: (e.timestamp, e.charge_id))


class JsonFileStorage:
    def __init__(self, file_path: Path) -> None:
        self._path = file_path

    def save(self, entry: ChargeEntry) -> None:
        rows = self._read_raw()
        rows.append(asdict(entry))
        self._path.write_text(json.dumps(rows), encoding="utf-8")

    def list_by_tenant(self, tenant: str) -> list[ChargeEntry]:
        return [e for e in self.list_all() if e.tenant == tenant]

    def list_all(self) -> list[ChargeEntry]:
        return [ChargeEntry(**row) for row in self._read_raw()]

    def _read_raw(self) -> list[dict[str, object]]:
        if not self._path.exists():
            return []
        loaded: list[dict[str, object]] = json.loads(self._path.read_text(encoding="utf-8"))
        return loaded


def reconcile_charges(entries: Sequence[ChargeEntry]) -> ReconcileSummary:
    ordered = sorted(entries, key=lambda e: e.timestamp)
    gross = sum(float(e.amount_usd) for e in ordered)
    fees = sum(float(e.fee_usd) for e in ordered)
    net = gross - fees
    return ReconcileSummary(
        gross_usd=str(gross) if ordered else "0.00",
        fee_usd=str(fees) if ordered else "0.00",
        net_usd=str(net) if ordered else "0.00",
        net_cents=int(net * 100),
        ordered_charge_ids=tuple(e.charge_id for e in ordered),
    )
