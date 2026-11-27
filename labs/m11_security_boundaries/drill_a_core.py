"""M11 Drill A (Cold-Turkey Core): Path, URL, Subprocess & Untrusted Tool Output Gates.

Implement the contracts below with AI completions disabled.

Required Behavioral Specification
---------------------------------
1. `resolve_sandbox_path(sandbox_root: Path, untrusted_rel: str) -> Path`:
   - Requires `sandbox_root` to exist as a directory (`sandbox_root.resolve(strict=True)`),
     raising `SecurityBoundaryError` otherwise.
   - Rejects empty or whitespace-only `untrusted_rel`, null bytes (`"\\x00"`), leading `"/"` or
     `"\\\\"`, and any `":"` (blocking Windows drive-absolute `C:\\...` and drive-relative `C:foo`).
   - Resolves `candidate = (root_real / untrusted_rel).resolve(strict=False)` and enforces
     `candidate.is_relative_to(root_real)` so `..` escapes, sibling-prefix tricks
     (`../sandbox_evil/file.txt`), and symlinks targeting paths outside `root_real` all raise
     `SecurityBoundaryError`.

2. `validate_outbound_url(raw_url: str, allowed_hosts: AbstractSet[str]) -> str`:
   - Enforces `https` scheme only, rejects empty strings, backslashes, and whitespace/control
     characters, and rejects embedded `username`/`password` userinfo (`https://evil@host`).
   - Extracts normalized lowercase hostname, rejects any literal IPv4/IPv6 address that is
     loopback, private, link-local (`169.254.169.254`), multicast, unspecified, reserved, or
     IPv4-mapped private/loopback (`::ffff:127.0.0.1` via `ip.ipv4_mapped`) using `ipaddress`.
   - Enforces exact membership in normalized `{h.lower() for h in allowed_hosts}`, raising
     `SecurityBoundaryError` on any violation.

3. `build_safe_command(binary: str, args: Sequence[str], *, allowed_binaries: AbstractSet[str]) -> tuple[str, ...]`:
   - Validates `binary` is non-empty, contains no path/drive separators (`"/"`, `"\\\\"`, `":"`),
     whitespace, or control/null characters, and is a member of `allowed_binaries`.
   - Validates no element of `args` contains `"\\x00"`, `"\\r"`, or `"\\n"`.
   - Returns `(binary, "--", *args)`, raising `SecurityBoundaryError` on any violation.

4. `parse_untrusted_tool_output(raw_bytes: bytes, *, max_bytes: int = 16_384, max_items: int = 50) -> SafeToolResult`:
   - Enforces `len(raw_bytes) <= max_bytes` BEFORE UTF-8 or JSON decoding.
   - Parses a JSON object with exact keys `{"tool", "status", "items"}` (rejecting missing,
     extra, or duplicate keys).
   - Validates `tool: str` (`1..64` printable ASCII chars, not whitespace-only),
     `status` in `("ok", "error")`, and `items: list[str]` (`len <= max_items`, each `str`
     `<= 256` chars with no control chars `ord(ch) < 0x20`).
   - Raises `SecurityBoundaryError` on any violation.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class SecurityBoundaryError(ValueError):
    """Raised when an untrusted input or tool output violates a security boundary."""


@dataclass(slots=True, frozen=True)
class SafeToolResult:
    """Validated, immutable tool output record."""

    tool: str
    status: Literal["ok", "error"]
    items: tuple[str, ...]


def resolve_sandbox_path(sandbox_root: Path, untrusted_rel: str) -> Path:
    """Resolve `untrusted_rel` strictly inside existing directory `sandbox_root`."""
    raise NotImplementedError("Implement resolve_sandbox_path")


def validate_outbound_url(raw_url: str, allowed_hosts: AbstractSet[str]) -> str:
    """Validate `raw_url` as an SSRF-safe HTTPS URL targeting `allowed_hosts`."""
    raise NotImplementedError("Implement validate_outbound_url")


def build_safe_command(
    binary: str,
    args: Sequence[str],
    *,
    allowed_binaries: AbstractSet[str],
) -> tuple[str, ...]:
    """Construct an injection-safe `(binary, '--', *args)` argv tuple."""
    raise NotImplementedError("Implement build_safe_command")


def parse_untrusted_tool_output(
    raw_bytes: bytes,
    *,
    max_bytes: int = 16_384,
    max_items: int = 50,
) -> SafeToolResult:
    """Bound, decode, and schema-validate untrusted JSON bytes into `SafeToolResult`."""
    raise NotImplementedError("Implement parse_untrusted_tool_output")
