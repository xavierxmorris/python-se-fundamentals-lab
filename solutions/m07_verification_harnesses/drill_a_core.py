"""Reference solution for M07 Drill A: Canonical Envelope Codec & Collision-Free Digest."""

import hashlib
import json
from dataclasses import dataclass
from typing import Final, TypeIs

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {"tenant", "task_id", "tool", "version", "payload"}
)


@dataclass(slots=True, frozen=True)
class Envelope:
    tenant: str
    task_id: str
    tool: str
    version: int
    payload: dict[str, JsonValue]


def _is_obj_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def _is_obj_dict(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_pair_list(value: object) -> TypeIs[list[tuple[str, object]]]:
    return isinstance(value, list)


def _validate_json_value(value: object, *, error_cls: type[Exception]) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if _is_obj_list(value):
        return [_validate_json_value(item, error_cls=error_cls) for item in value]
    if _is_obj_dict(value):
        validated_dict: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise error_cls(f"JSON object key must be str, got {type(key).__name__}")
            validated_dict[key] = _validate_json_value(item, error_cls=error_cls)
        return validated_dict
    raise error_cls(f"Unsupported non-JsonValue type: {type(value).__name__}")


def _validate_envelope(env: Envelope) -> dict[str, JsonValue]:
    if not isinstance(env, Envelope):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"Expected Envelope, got {type(env).__name__}")
    if (
        not isinstance(env.tenant, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        or not isinstance(env.task_id, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        or not isinstance(env.tool, str)  # pyright: ignore[reportUnnecessaryIsInstance]
    ):
        raise TypeError("Envelope tenant, task_id, and tool must be str")
    if isinstance(env.version, bool) or not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
        env.version, int
    ):
        raise TypeError("Envelope version must be a strict int (bool is not allowed)")
    if env.version < 1:
        raise ValueError(f"Envelope version must be >= 1, got {env.version}")
    payload_obj: object = env.payload
    if not _is_obj_dict(payload_obj):
        raise TypeError("Envelope payload must be a dict[str, JsonValue]")

    clean_payload: dict[str, JsonValue] = {}
    for key, val in payload_obj.items():
        if not isinstance(key, str):
            raise TypeError(f"Payload key must be str, got {type(key).__name__}")
        clean_payload[key] = _validate_json_value(val, error_cls=TypeError)
    return clean_payload


def _reject_float(token: str) -> object:
    raise ValueError(f"Floats are forbidden in canonical envelopes: {token!r}")


def _reject_constant(token: str) -> object:
    raise ValueError(f"Non-standard JSON constant forbidden: {token!r}")


def _unique_object_pairs(pairs: object) -> dict[str, object]:
    if not _is_pair_list(pairs):
        raise ValueError("Invalid JSON object pairs")
    result: dict[str, object] = {}
    for key, val in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key detected: {key!r}")
        result[key] = val
    return result


def encode_envelope(env: Envelope) -> bytes:
    """Encode `env` into canonical UTF-8 JSON bytes."""
    clean_payload = _validate_envelope(env)
    doc: dict[str, object] = {
        "tenant": env.tenant,
        "task_id": env.task_id,
        "tool": env.tool,
        "version": env.version,
        "payload": clean_payload,
    }
    serialized = json.dumps(
        doc,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return serialized.encode("utf-8")


def decode_envelope(raw: bytes) -> Envelope:
    """Decode and strictly validate an `Envelope` from UTF-8 JSON bytes."""
    if not isinstance(raw, bytes):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise TypeError(f"Expected bytes, got {type(raw).__name__}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid UTF-8 bytes in raw envelope") from exc

    try:
        parsed: object = json.loads(
            text,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object_pairs,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed JSON in raw envelope") from exc

    if not _is_obj_dict(parsed):
        raise ValueError("Top-level envelope JSON must be an object")

    actual_keys = frozenset(k for k in parsed if isinstance(k, str))
    if len(actual_keys) != len(parsed) or actual_keys != _REQUIRED_KEYS:
        raise ValueError("Envelope JSON keys do not match required schema")

    tenant = parsed["tenant"]
    task_id = parsed["task_id"]
    tool = parsed["tool"]
    version = parsed["version"]
    raw_payload = parsed["payload"]

    if (
        not isinstance(tenant, str)
        or not isinstance(task_id, str)
        or not isinstance(tool, str)
    ):
        raise ValueError("tenant, task_id, and tool must be strings")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("version must be an integer >= 1 (booleans forbidden)")
    if not _is_obj_dict(raw_payload):
        raise ValueError("payload must be a JSON object")

    clean_payload: dict[str, JsonValue] = {}
    for key, val in raw_payload.items():
        if not isinstance(key, str):
            raise ValueError("payload keys must be strings")
        clean_payload[key] = _validate_json_value(val, error_cls=ValueError)

    return Envelope(
        tenant=tenant,
        task_id=task_id,
        tool=tool,
        version=version,
        payload=clean_payload,
    )


def canonical_digest(env: Envelope) -> str:
    """Return a collision-free canonical SHA-256 hex digest for `env`."""
    clean_payload = _validate_envelope(env)
    canonical_frame = json.dumps(
        [env.tenant, env.task_id, env.tool, env.version, clean_payload],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_frame).hexdigest()
