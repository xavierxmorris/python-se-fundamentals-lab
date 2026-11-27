"""Reference learner Hypothesis & boundary test suite for M07 Drill A."""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from drill_a_core import (
    Envelope,
    JsonScalar,
    JsonValue,
    canonical_digest,
    decode_envelope,
    encode_envelope,
)

_SCALARS: st.SearchStrategy[JsonScalar] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.text(
        alphabet=st.characters(
            exclude_categories=("Cs",),
        ),
        max_size=24,
    ),
)


def _nested_json(children: st.SearchStrategy[JsonValue]) -> st.SearchStrategy[JsonValue]:
    return st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=12), children, max_size=4),
    )


_JSON_VALUES: st.SearchStrategy[JsonValue] = st.recursive(
    _SCALARS,
    _nested_json,
    max_leaves=12,
)

_PAYLOADS: st.SearchStrategy[dict[str, JsonValue]] = st.dictionaries(
    st.text(max_size=16),
    _JSON_VALUES,
    max_size=6,
)

_DELIM_TEXT: st.SearchStrategy[str] = st.text(
    alphabet=st.sampled_from(["a", "b", "c", ":", "\x00", "|", "λ", "🚀"]),
    max_size=10,
)

_ENVELOPES: st.SearchStrategy[Envelope] = st.builds(
    Envelope,
    tenant=st.one_of(_DELIM_TEXT, st.text(max_size=20)),
    task_id=st.one_of(_DELIM_TEXT, st.text(max_size=20)),
    tool=st.one_of(_DELIM_TEXT, st.text(max_size=20)),
    version=st.integers(min_value=1, max_value=10_000),
    payload=_PAYLOADS,
)


def _reverse_dict_keys(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [_reverse_dict_keys(item) for item in value]
    if isinstance(value, dict):
        reversed_items = list(value.items())[::-1]
        return {k: _reverse_dict_keys(v) for k, v in reversed_items}
    return value


@settings(max_examples=100, deadline=None)
@given(env=_ENVELOPES)
def test_property_round_trip_lossless_across_unicode_and_nested_json(
    env: Envelope,
) -> None:
    raw = encode_envelope(env)
    decoded = decode_envelope(raw)
    assert decoded == env
    assert type(decoded.version) is int
    assert encode_envelope(decoded) == raw


@settings(max_examples=100, deadline=None)
@given(
    env=_ENVELOPES,
    extra_first_key=st.text(min_size=1, max_size=8),
    extra_second_key=st.text(min_size=1, max_size=8),
)
def test_property_canonicalism_invariant_under_dict_key_permutation(
    env: Envelope,
    extra_first_key: str,
    extra_second_key: str,
) -> None:
    assume(extra_first_key != extra_second_key)
    forward_payload: dict[str, JsonValue] = {
        extra_first_key: 1,
        extra_second_key: 2,
    }
    for k, v in env.payload.items():
        if k not in forward_payload:
            forward_payload[k] = v

    reversed_payload_val = _reverse_dict_keys(forward_payload)
    assert isinstance(reversed_payload_val, dict)

    env_forward = Envelope(
        tenant=env.tenant,
        task_id=env.task_id,
        tool=env.tool,
        version=env.version,
        payload=forward_payload,
    )
    env_reversed = Envelope(
        tenant=env.tenant,
        task_id=env.task_id,
        tool=env.tool,
        version=env.version,
        payload=reversed_payload_val,
    )
    assert encode_envelope(env_forward) == encode_envelope(env_reversed)
    assert canonical_digest(env_forward) == canonical_digest(env_reversed)


@settings(max_examples=100, deadline=None)
@given(
    triple_a=st.tuples(_DELIM_TEXT, _DELIM_TEXT, _DELIM_TEXT),
    triple_b=st.tuples(_DELIM_TEXT, _DELIM_TEXT, _DELIM_TEXT),
    payload=_PAYLOADS,
)
def test_property_injectivity_no_delimiter_collisions(
    triple_a: tuple[str, str, str],
    triple_b: tuple[str, str, str],
    payload: dict[str, JsonValue],
) -> None:
    assume(triple_a != triple_b)
    env_a = Envelope(triple_a[0], triple_a[1], triple_a[2], 1, payload)
    env_b = Envelope(triple_b[0], triple_b[1], triple_b[2], 1, payload)
    assert canonical_digest(env_a) != canonical_digest(env_b)


def test_explicit_delimiter_shift_and_unicode_wire_bytes() -> None:
    for delim in (":", "\x00", "|"):
        left = Envelope(f"a{delim}b", "c", "tool", 1, {})
        right = Envelope("a", f"b{delim}c", "tool", 1, {})
        assert canonical_digest(left) != canonical_digest(right)

    unicode_env = Envelope("acme", "t-1", "echo", 1, {"greeting": "héllo 🌍"})
    wire = encode_envelope(unicode_env)
    assert "héllo 🌍".encode() in wire
    assert decode_envelope(wire) == unicode_env


def test_boundary_rejection_of_bool_version_zero_version_and_floats() -> None:
    with pytest.raises(TypeError):
        encode_envelope(Envelope("t", "id", "fn", True, {}))

    with pytest.raises(TypeError):
        encode_envelope(
            Envelope("t", "id", "fn", 1, {"bad": 0.5})  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError):
        encode_envelope(Envelope("t", "id", "fn", 0, {}))

    for bad_raw in (
        b'{"tenant":"t","task_id":"id","tool":"fn","version":true,"payload":{}}',
        b'{"tenant":"t","task_id":"id","tool":"fn","version":false,"payload":{}}',
        b'{"tenant":"t","task_id":"id","tool":"fn","version":0,"payload":{}}',
        b'{"tenant":"t","task_id":"id","tool":"fn","version":-1,"payload":{}}',
        b'{"tenant":"t","task_id":"id","tool":"fn","version":1,"payload":{"f":1.2}}',
    ):
        with pytest.raises(ValueError):
            decode_envelope(bad_raw)
