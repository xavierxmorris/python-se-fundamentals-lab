"""Frozen acceptance suite for M07 Drill B (Golden-Master & Storage Contract Suite)."""

from collections.abc import Callable
from pathlib import Path

import pytest

from drill_b_ai_adapter import (
    ChargeEntry,
    InMemoryStorageFake,
    JsonFileStorage,
    LedgerStoragePort,
    ReconcileSummary,
    reconcile_charges,
)

GOLDEN_CORPUS: tuple[ChargeEntry, ...] = (
    ChargeEntry("chg-003", "acme", 1_700_000_200, "0.10", "0.01"),
    ChargeEntry("chg-002", "acme", 1_700_000_100, "0.20", "0.00"),
    ChargeEntry("chg-001", "acme", 1_700_000_100, "19.99", "0.30"),
    ChargeEntry("chg-004", "globex", 1_700_000_150, "0.29", "0.00"),
)


def test_golden_master_reconcile_exact_decimal_and_tie_break_order() -> None:
    summary = reconcile_charges(GOLDEN_CORPUS)
    assert summary == ReconcileSummary(
        gross_usd="20.58",
        fee_usd="0.31",
        net_usd="20.27",
        net_cents=2027,
        ordered_charge_ids=("chg-001", "chg-002", "chg-004", "chg-003"),
    )


def test_golden_master_classic_float_drift_vectors() -> None:
    tenth_plus_twenty = (
        ChargeEntry("b-id", "acme", 10, "0.10", "0.00"),
        ChargeEntry("a-id", "acme", 10, "0.20", "0.00"),
    )
    assert reconcile_charges(tenth_plus_twenty) == ReconcileSummary(
        gross_usd="0.30",
        fee_usd="0.00",
        net_usd="0.30",
        net_cents=30,
        ordered_charge_ids=("a-id", "b-id"),
    )

    twenty_nine_cents = (ChargeEntry("c-1", "acme", 1, "0.29", "0.00"),)
    assert reconcile_charges(twenty_nine_cents) == ReconcileSummary(
        gross_usd="0.29",
        fee_usd="0.00",
        net_usd="0.29",
        net_cents=29,
        ordered_charge_ids=("c-1",),
    )

    assert reconcile_charges(()) == ReconcileSummary(
        gross_usd="0.00",
        fee_usd="0.00",
        net_usd="0.00",
        net_cents=0,
        ordered_charge_ids=(),
    )


StorageFactory = Callable[[Path], LedgerStoragePort]


def _make_memory_store(_tmp: Path) -> LedgerStoragePort:
    return InMemoryStorageFake()


def _make_json_file_store(tmp: Path) -> LedgerStoragePort:
    return JsonFileStorage(tmp / "ledger_charges.json")


@pytest.mark.parametrize("factory", [_make_memory_store, _make_json_file_store])
def test_storage_port_shared_contract(tmp_path: Path, factory: StorageFactory) -> None:
    store = factory(tmp_path)
    assert isinstance(store, LedgerStoragePort)
    assert store.list_all() == []
    assert store.list_by_tenant("acme") == []

    for item in GOLDEN_CORPUS:
        store.save(item)

    assert [e.charge_id for e in store.list_all()] == [
        "chg-001",
        "chg-002",
        "chg-004",
        "chg-003",
    ]
    assert [e.charge_id for e in store.list_by_tenant("acme")] == [
        "chg-001",
        "chg-002",
        "chg-003",
    ]

    # Upserting an existing charge_id must replace in place without creating duplicates
    updated = ChargeEntry("chg-002", "acme", 1_700_000_050, "0.50", "0.02")
    store.save(updated)
    acme_rows = store.list_by_tenant("acme")
    assert [e.charge_id for e in acme_rows] == ["chg-002", "chg-001", "chg-003"]
    assert acme_rows[0] == updated

    # Mutating returned list must not corrupt stored state
    acme_rows.clear()
    assert len(store.list_by_tenant("acme")) == 3


def test_fake_and_json_storage_produce_identical_reconciliation(tmp_path: Path) -> None:
    fake = InMemoryStorageFake()
    disk = JsonFileStorage(tmp_path / "parity.json")
    events = [
        *GOLDEN_CORPUS,
        ChargeEntry("chg-003", "acme", 1_700_000_100, "1.10", "0.05"),
    ]
    for ev in events:
        fake.save(ev)
        disk.save(ev)

    assert disk.list_all() == fake.list_all()
    assert reconcile_charges(disk.list_all()) == reconcile_charges(fake.list_all())
