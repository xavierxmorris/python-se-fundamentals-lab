"""Seeded realistic mutants for M07 Gate 4 mutation testing."""

import hashlib
import json
from collections.abc import Callable
from types import ModuleType
from typing import Protocol, TypeIs


class _EnvelopeLike(Protocol):
    @property
    def tenant(self) -> str: ...
    @property
    def task_id(self) -> str: ...
    @property
    def tool(self) -> str: ...
    @property
    def version(self) -> int: ...
    @property
    def payload(self) -> object: ...


def _is_obj_dict(val: object) -> TypeIs[dict[object, object]]:
    return isinstance(val, dict)


def _bug_delimiter_collision_digest(mod: ModuleType) -> None:
    orig_encode = mod.encode_envelope

    def buggy_canonical_digest(env: _EnvelopeLike) -> str:
        orig_encode(env)
        payload_json = json.dumps(
            env.payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        naive = f"{env.tenant}:{env.task_id}:{env.tool}:{env.version}:{payload_json}"
        return hashlib.sha256(naive.encode("utf-8")).hexdigest()

    mod.canonical_digest = buggy_canonical_digest  # type: ignore[attr-defined]


def _bug_unsorted_keys_encode(mod: ModuleType) -> None:
    orig_encode = mod.encode_envelope

    def buggy_encode_envelope(env: _EnvelopeLike) -> bytes:
        orig_encode(env)
        doc = {
            "tenant": env.tenant,
            "task_id": env.task_id,
            "tool": env.tool,
            "version": env.version,
            "payload": env.payload,
        }
        return json.dumps(
            doc,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    mod.encode_envelope = buggy_encode_envelope  # type: ignore[attr-defined]


def _bug_ascii_corrupt_unicode_encode(mod: ModuleType) -> None:
    orig_encode = mod.encode_envelope

    def buggy_encode_envelope(env: _EnvelopeLike) -> bytes:
        valid_utf8: bytes = orig_encode(env)
        text = valid_utf8.decode("utf-8")
        return text.encode("ascii", errors="replace")

    mod.encode_envelope = buggy_encode_envelope  # type: ignore[attr-defined]


def _bug_permissive_version_decode(mod: ModuleType) -> None:
    orig_decode = mod.decode_envelope
    envelope_cls = mod.Envelope

    def buggy_decode_envelope(raw: bytes) -> object:
        try:
            return orig_decode(raw)
        except ValueError:
            text = raw.decode("utf-8")
            parsed: object = json.loads(text)
            if not _is_obj_dict(parsed):
                raise
            required = {"tenant", "task_id", "tool", "version", "payload"}
            if set(parsed.keys()) != required:
                raise
            tenant = parsed["tenant"]
            task_id = parsed["task_id"]
            tool = parsed["tool"]
            version = parsed["version"]
            payload = parsed["payload"]
            if (
                isinstance(tenant, str)
                and isinstance(task_id, str)
                and isinstance(tool, str)
                and isinstance(version, int)
                and version >= 0
                and _is_obj_dict(payload)
            ):
                return envelope_cls(
                    tenant=tenant,
                    task_id=task_id,
                    tool=tool,
                    version=version,
                    payload=payload,
                )
            raise

    mod.decode_envelope = buggy_decode_envelope  # type: ignore[attr-defined]


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "delimiter_collision_digest": _bug_delimiter_collision_digest,
    "unsorted_keys_encode": _bug_unsorted_keys_encode,
    "ascii_corrupt_unicode_encode": _bug_ascii_corrupt_unicode_encode,
    "permissive_version_decode": _bug_permissive_version_decode,
}
