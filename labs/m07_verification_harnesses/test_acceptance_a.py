"""Frozen acceptance suite for M07 Drill A (Canonical Envelope Codec & Digest)."""

import pytest

from drill_a_core import (
    Envelope,
    JsonValue,
    canonical_digest,
    decode_envelope,
    encode_envelope,
)


def test_round_trip_unicode_and_nested_structures() -> None:
    payload: dict[str, JsonValue] = {
        "z_list": [None, True, False, 0, -42, 9_007_199_254_740_993, "café 🚀"],
        "a_nested": {"inner_b": "αβγ", "inner_a": []},
        "empty_map": {},
    }
    env = Envelope(
        tenant="acme:eu",
        task_id="task\x0042|1",
        tool="ledger.reconcile",
        version=3,
        payload=payload,
    )
    encoded = encode_envelope(env)
    assert isinstance(encoded, bytes)
    assert "café 🚀".encode() in encoded
    assert b" " not in encoded.replace("café 🚀".encode(), b"")
    decoded = decode_envelope(encoded)
    assert decoded == env
    assert type(decoded.version) is int


def test_canonicalism_across_permuted_dict_key_insertion_order() -> None:
    env_1 = Envelope(
        tenant="t1",
        task_id="k1",
        tool="run",
        version=1,
        payload={"b": {"y": 2, "x": 1}, "a": [{"d": 4, "c": 3}]},
    )
    env_2 = Envelope(
        tenant="t1",
        task_id="k1",
        tool="run",
        version=1,
        payload={"a": [{"c": 3, "d": 4}], "b": {"x": 1, "y": 2}},
    )
    assert encode_envelope(env_1) == encode_envelope(env_2)
    assert canonical_digest(env_1) == canonical_digest(env_2)
    assert len(canonical_digest(env_1)) == 64


@pytest.mark.parametrize(
    ("triple_left", "triple_right"),
    [
        (("a:b", "c", "tool"), ("a", "b:c", "tool")),
        (("a", "b:c", "d"), ("a", "b", "c:d")),
        (("a\x00b", "c", "d"), ("a", "b\x00c", "d")),
        (("a|b", "c", "d"), ("a", "b|c", "d")),
        (("ab", "", "c"), ("a", "b", "c")),
    ],
)
def test_canonical_digest_has_zero_delimiter_collisions(
    triple_left: tuple[str, str, str],
    triple_right: tuple[str, str, str],
) -> None:
    left = Envelope(
        tenant=triple_left[0],
        task_id=triple_left[1],
        tool=triple_left[2],
        version=1,
        payload={"ok": True},
    )
    right = Envelope(
        tenant=triple_right[0],
        task_id=triple_right[1],
        tool=triple_right[2],
        version=1,
        payload={"ok": True},
    )
    assert canonical_digest(left) != canonical_digest(right)


def test_canonical_digest_changes_when_version_or_payload_changes() -> None:
    base = Envelope(tenant="t", task_id="id", tool="fn", version=1, payload={"n": 1})
    bumped = Envelope(tenant="t", task_id="id", tool="fn", version=2, payload={"n": 1})
    bool_payload = Envelope(tenant="t", task_id="id", tool="fn", version=1, payload={"n": True})
    assert canonical_digest(base) != canonical_digest(bumped)
    assert canonical_digest(base) != canonical_digest(bool_payload)


def test_encode_rejects_floats_non_json_types_bool_version_and_invalid_version() -> None:
    bad_float: dict[str, object] = {"rate": 0.25}
    with pytest.raises(TypeError):
        encode_envelope(
            Envelope("t", "id", "fn", 1, bad_float)  # type: ignore[arg-type]
        )

    bad_nested_float: dict[str, object] = {"items": [1, float("nan")]}
    with pytest.raises(TypeError):
        encode_envelope(
            Envelope("t", "id", "fn", 1, bad_nested_float)  # type: ignore[arg-type]
        )

    with pytest.raises(TypeError):
        encode_envelope(Envelope("t", "id", "fn", True, {}))

    for bad_ver in (0, -1, -99):
        with pytest.raises(ValueError):
            encode_envelope(Envelope("t", "id", "fn", bad_ver, {}))
        with pytest.raises(ValueError):
            canonical_digest(Envelope("t", "id", "fn", bad_ver, {}))


@pytest.mark.parametrize(
    "raw_bytes",
    [
        b"not-json",
        b"[]",
        b"\xff\xfe",
        b'{"tenant":"a","task_id":"b","tool":"c","version":true,"payload":{}}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":false,"payload":{}}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":0,"payload":{}}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":-2,"payload":{}}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":1,"payload":{"x":1.5}}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":1,"payload":[]}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":1}',
        b'{"tenant":"a","task_id":"b","tool":"c","version":1,"payload":{},"extra":1}',
        b'{"tenant":123,"task_id":"b","tool":"c","version":1,"payload":{}}',
    ],
)
def test_decode_rejects_malformed_or_schema_invalid_inputs(raw_bytes: bytes) -> None:
    with pytest.raises(ValueError):
        decode_envelope(raw_bytes)
