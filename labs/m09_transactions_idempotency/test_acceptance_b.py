"""Frozen acceptance suite for M09 Drill B (Transactional BatchOutboxRelay)."""

from pathlib import Path

import pytest

from drill_b_ai_adapter import (
    BatchOutboxRelay,
    BrokerPort,
    OutboxRecord,
    open_outbox_relay,
)


class _CrashableIdempotentBroker:
    """Idempotent broker fake that deduplicates by `delivery_key` and injects crashes."""

    def __init__(self) -> None:
        self.delivered_by_key: dict[str, str] = {}
        self.delivery_order: list[tuple[str, str]] = []
        self.raw_publish_keys: list[str] = []
        self.fail_before_ack_on_call: set[int] = set()
        self.fail_after_accept_on_call: set[int] = set()
        self._call_number = 0

    def publish(self, delivery_key: str, body: str) -> None:
        self._call_number += 1
        self.raw_publish_keys.append(delivery_key)

        if self._call_number in self.fail_before_ack_on_call:
            raise ConnectionError(f"broker unreachable on call {self._call_number}")

        if delivery_key not in self.delivered_by_key:
            self.delivered_by_key[delivery_key] = body
            self.delivery_order.append((delivery_key, body))

        if self._call_number in self.fail_after_accept_on_call:
            raise TimeoutError(f"lost broker ack after accept on call {self._call_number}")


def test_deterministic_delivery_keys_and_idempotent_enqueue(tmp_path: Path) -> None:
    db_path = tmp_path / "outbox.db"
    broker = _CrashableIdempotentBroker()
    assert isinstance(broker, BrokerPort)

    with open_outbox_relay(db_path, broker) as relay:
        assert relay.enqueue("m-1", '{"ev":"created"}') is True
        assert relay.enqueue("m-1", '{"ev":"created"}') is False
        with pytest.raises(ValueError):
            relay.enqueue("m-1", '{"ev":"tampered"}')
        assert relay.enqueue("m-2", '{"ev":"billed"}') is True

        sent = relay.relay_pending()
        assert sent == 2
        assert relay.pending_count() == 0
        assert relay.sent_count() == 2
        assert relay.in_transaction is False
        assert relay.get_record("m-1") == OutboxRecord(
            msg_id="m-1",
            body='{"ev":"created"}',
            status="sent",
            attempts=1,
        )

    assert broker.delivery_order == [
        ("outbox:m-1", '{"ev":"created"}'),
        ("outbox:m-2", '{"ev":"billed"}'),
    ]


def test_mid_batch_crash_commits_prior_items_and_leaves_no_open_tx(tmp_path: Path) -> None:
    db_path = tmp_path / "mid_crash.db"
    broker = _CrashableIdempotentBroker()
    broker.fail_before_ack_on_call.add(3)  # Crash before delivering 3rd message

    with open_outbox_relay(db_path, broker) as relay:
        for i in range(1, 5):
            relay.enqueue(f"msg-{i}", f"payload-{i}")

        with pytest.raises(ConnectionError):
            relay.relay_pending()

        assert relay.in_transaction is False, "relay left an uncommitted SQLite transaction open"
        assert relay.sent_count() == 2
        assert relay.pending_count() == 2

    # Reopen from disk to prove messages 1 & 2 were durably marked sent before crash
    with open_outbox_relay(db_path, broker) as recovered:
        assert isinstance(recovered, BatchOutboxRelay)
        assert recovered.sent_count() == 2
        assert recovered.pending_count() == 2
        relayed = recovered.relay_pending()
        assert relayed == 2
        assert recovered.sent_count() == 4
        assert recovered.pending_count() == 0
        assert recovered.get_record("msg-3").attempts == 2

    assert broker.delivery_order == [
        ("outbox:msg-1", "payload-1"),
        ("outbox:msg-2", "payload-2"),
        ("outbox:msg-3", "payload-3"),
        ("outbox:msg-4", "payload-4"),
    ]


def test_lost_ack_after_broker_accept_retries_effectively_once(tmp_path: Path) -> None:
    db_path = tmp_path / "lost_ack.db"
    broker = _CrashableIdempotentBroker()
    broker.fail_after_accept_on_call.add(1)

    with open_outbox_relay(db_path, broker) as relay:
        relay.enqueue("ord-99", '{"order":99}')

        with pytest.raises(TimeoutError):
            relay.relay_pending()

        assert relay.in_transaction is False
        assert relay.pending_count() == 1
        assert relay.get_record("ord-99") == OutboxRecord(
            msg_id="ord-99",
            body='{"order":99}',
            status="pending",
            attempts=1,
        )

        # Retry succeeds; deterministic delivery_key prevents duplicate broker effect
        assert relay.relay_pending() == 1
        assert relay.pending_count() == 0
        assert relay.sent_count() == 1
        assert relay.get_record("ord-99").attempts == 2

    assert broker.raw_publish_keys == ["outbox:ord-99", "outbox:ord-99"]
    assert len(broker.delivery_order) == 1
    assert broker.delivery_order[0] == ("outbox:ord-99", '{"order":99}')


def test_limit_validation_and_unknown_record_key_error(tmp_path: Path) -> None:
    db_path = tmp_path / "validation.db"
    broker = _CrashableIdempotentBroker()
    with open_outbox_relay(db_path, broker) as relay:
        with pytest.raises(ValueError):
            relay.relay_pending(limit=0)
        with pytest.raises(ValueError):
            relay.relay_pending(limit=True)
        with pytest.raises(KeyError):
            relay.get_record("missing-id")
