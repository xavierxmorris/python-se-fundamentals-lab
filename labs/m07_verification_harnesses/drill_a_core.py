"""M07 Drill A (Cold-Turkey Core): Canonical Envelope Codec & Collision-Free Digest.

Implement the following public surface without reading acceptance tests:

1. Type aliases:
   - `type JsonScalar = str | int | bool | None`
   - `type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]`

2. `@dataclass(slots=True, frozen=True) class Envelope`:
   Fields (in exact positional order):
   - `tenant: str`
   - `task_id: str`
   - `tool: str`
   - `version: int`
   - `payload: dict[str, JsonValue]`

3. `encode_envelope(env: Envelope) -> bytes`:
   - Validates `env` is an `Envelope` instance (`TypeError` otherwise).
   - Validates `tenant`, `task_id`, and `tool` are `str` (`TypeError` otherwise; empty
     strings and arbitrary valid UTF-8 characters are allowed).
   - Validates `version` is a strict `int` (`isinstance(env.version, bool)` MUST raise
     `TypeError`!). If `env.version < 1`, raises `ValueError`.
   - Validates `payload` is a `dict` whose keys are `str` and whose values recursively
     conform to `JsonValue` (`str | int | bool | None | list[JsonValue] | dict[str, JsonValue]`).
     Any `float` (including `0.0`, `NaN`, `Infinity`), `tuple`, `set`, `bytes`, or custom
     object anywhere inside `payload` MUST raise `TypeError`.
   - Encodes the envelope as a canonical JSON object with exact keys
     `{"tenant", "task_id", "tool", "version", "payload"}` using:
     `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, encoded to UTF-8
     bytes (`.encode("utf-8")`). Lone UTF-16 surrogates fail UTF-8 encoding (`ValueError`).

4. `decode_envelope(raw: bytes) -> Envelope`:
   - Validates `raw` is `bytes` (`TypeError` if not `bytes`, e.g. `str` or `bytearray`).
   - Decodes UTF-8 strictly (`ValueError` on invalid UTF-8) and parses JSON (`ValueError`
     on malformed JSON, duplicate object keys, or any JSON `float` / `NaN` / `Infinity`).
   - Validates top-level JSON value is an object with exact key set
     `{"tenant", "task_id", "tool", "version", "payload"}` (missing or extra keys raise
     `ValueError`).
   - Validates field types and bounds strictly:
     * `tenant`, `task_id`, `tool` must be `str` (`ValueError` otherwise).
     * `version` must be an `int` and MUST NOT be a `bool` (`True`/`False` must raise
       `ValueError`), with `version >= 1` (`ValueError` otherwise).
     * `payload` must be a JSON object (`dict[str, JsonValue]`) containing no floats or
       invalid values (`ValueError` otherwise).
   - Returns the reconstructed `Envelope`.

5. `canonical_digest(env: Envelope) -> str`:
   - Validates `env` using the exact same rules and error classes (`TypeError` / `ValueError`)
     as `encode_envelope(env)`.
   - Computes a lowercase 64-character SHA-256 hex digest over a collision-free canonical
     representation covering `(env.tenant, env.task_id, env.tool, env.version, env.payload)`,
     specifically serializing `[env.tenant, env.task_id, env.tool, env.version, env.payload]`
     as canonical UTF-8 JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`)
     before hashing with `hashlib.sha256(...).hexdigest()`.
   - Distinct `(tenant, task_id, tool)` triples such as `("a:b", "c", "x")` vs
     `("a", "b:c", "x")` MUST never collide, and permuting dictionary key insertion order
     anywhere in `payload` MUST yield the exact same digest.
"""

from dataclasses import dataclass

type JsonScalar = str | int | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(slots=True, frozen=True)
class Envelope:
    tenant: str
    task_id: str
    tool: str
    version: int
    payload: dict[str, JsonValue]


def encode_envelope(env: Envelope) -> bytes:
    """Encode `env` into canonical UTF-8 JSON bytes."""
    raise NotImplementedError("Implement encode_envelope in drill_a_core.py")


def decode_envelope(raw: bytes) -> Envelope:
    """Decode and strictly validate an `Envelope` from UTF-8 JSON bytes."""
    raise NotImplementedError("Implement decode_envelope in drill_a_core.py")


def canonical_digest(env: Envelope) -> str:
    """Return a collision-free canonical SHA-256 hex digest for `env`."""
    raise NotImplementedError("Implement canonical_digest in drill_a_core.py")
