"""Reference solution for M11 Drill A (`drill_a_core.py`)."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeIs
from urllib.parse import urlsplit, urlunsplit


class SecurityBoundaryError(ValueError):
    """Raised when an untrusted input or tool output violates a security boundary."""


@dataclass(slots=True, frozen=True)
class SafeToolResult:
    """Validated, immutable tool output record."""

    tool: str
    status: Literal["ok", "error"]
    items: tuple[str, ...]


def _is_str_object_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _is_valid_status(val: object) -> TypeIs[Literal["ok", "error"]]:
    return val in ("ok", "error")


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or not ip.is_global
    ):
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None and _is_forbidden_ip(ip.ipv4_mapped):
            return True
        if ip.sixtofour is not None and _is_forbidden_ip(ip.sixtofour):
            return True
        if ip.teredo is not None:
            server_ip, client_ip = ip.teredo
            if _is_forbidden_ip(server_ip) or _is_forbidden_ip(client_ip):
                return True
    return False


def resolve_sandbox_path(sandbox_root: Path, untrusted_rel: str) -> Path:
    """Resolve `untrusted_rel` strictly inside existing directory `sandbox_root`."""
    try:
        root_real = sandbox_root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SecurityBoundaryError(f"Invalid sandbox_root: {sandbox_root}") from exc

    if not root_real.is_dir():
        raise SecurityBoundaryError("sandbox_root must be an existing directory")

    if (
        not untrusted_rel
        or not untrusted_rel.strip()
        or "\x00" in untrusted_rel
        or untrusted_rel.startswith(("/", "\\"))
        or ":" in untrusted_rel
    ):
        raise SecurityBoundaryError("Disallowed relative path syntax")

    try:
        candidate = (root_real / untrusted_rel).resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise SecurityBoundaryError("Failed to resolve candidate path safely") from exc

    if not candidate.is_relative_to(root_real):
        raise SecurityBoundaryError("Candidate path escapes sandbox_root")

    return candidate


def validate_outbound_url(raw_url: str, allowed_hosts: AbstractSet[str]) -> str:
    """Validate `raw_url` as an SSRF-safe HTTPS URL targeting `allowed_hosts`."""
    if (
        not raw_url
        or "\\" in raw_url
        or any(ch.isspace() or ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in raw_url)
    ):
        raise SecurityBoundaryError("URL contains empty, backslash, whitespace, or control chars")

    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise SecurityBoundaryError("Malformed URL") from exc

    if parsed.scheme.lower() != "https":
        raise SecurityBoundaryError("Only https scheme is permitted")

    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise SecurityBoundaryError("Embedded URL credentials/userinfo are forbidden")

    if parsed.hostname is None or not parsed.hostname:
        raise SecurityBoundaryError("URL must include a valid hostname")

    if port is not None and not (1 <= port <= 65535):
        raise SecurityBoundaryError("Invalid URL port")

    host = parsed.hostname.lower()
    if "%" in host:
        raise SecurityBoundaryError("IPv6 zone identifiers are forbidden")

    try:
        ip_obj = ipaddress.ip_address(host)
    except ValueError:
        ip_obj = None

    if ip_obj is not None and _is_forbidden_ip(ip_obj):
        raise SecurityBoundaryError(f"Outbound IP address {host!r} is forbidden")

    normalized_allowed = {
        h[1:-1].lower() if h.startswith("[") and h.endswith("]") else h.lower()
        for h in allowed_hosts
        if h
    }
    if host not in normalized_allowed:
        raise SecurityBoundaryError(f"Host {host!r} is not in allowed_hosts")

    formatted_host = f"[{host}]" if ":" in host else host
    norm_netloc = f"{formatted_host}:{port}" if port is not None else formatted_host
    return urlunsplit(("https", norm_netloc, parsed.path, parsed.query, parsed.fragment))


def build_safe_command(
    binary: str,
    args: Sequence[str],
    *,
    allowed_binaries: AbstractSet[str],
) -> tuple[str, ...]:
    """Construct an injection-safe `(binary, '--', *args)` argv tuple."""
    if (
        not binary
        or "\x00" in binary
        or "/" in binary
        or "\\" in binary
        or ":" in binary
        or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in binary)
    ):
        raise SecurityBoundaryError("Invalid binary name")

    if binary not in allowed_binaries:
        raise SecurityBoundaryError(f"Binary {binary!r} is not allowlisted")

    validated_args: list[str] = []
    for arg in args:
        if "\x00" in arg or "\r" in arg or "\n" in arg:
            raise SecurityBoundaryError("Command argument contains forbidden control character")
        validated_args.append(arg)

    return (binary, "--", *validated_args)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, val in pairs:
        if key in result:
            raise SecurityBoundaryError(f"Duplicate JSON key: {key!r}")
        result[key] = val
    return result


def _reject_nonstandard_constant(token: str) -> object:
    raise SecurityBoundaryError(f"Non-standard JSON constant forbidden: {token!r}")


def parse_untrusted_tool_output(
    raw_bytes: bytes,
    *,
    max_bytes: int = 16_384,
    max_items: int = 50,
) -> SafeToolResult:
    """Bound, decode, and schema-validate untrusted JSON bytes into `SafeToolResult`."""
    if max_bytes < 1 or max_items < 0:
        raise ValueError("max_bytes must be >= 1 and max_items must be >= 0")

    if len(raw_bytes) > max_bytes:
        raise SecurityBoundaryError(
            f"Tool output size {len(raw_bytes)} exceeds max_bytes={max_bytes}"
        )

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SecurityBoundaryError("Tool output is not valid UTF-8") from exc

    try:
        decoded: object = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except json.JSONDecodeError as exc:
        raise SecurityBoundaryError("Tool output is not valid JSON") from exc

    if not _is_str_object_dict(decoded):
        raise SecurityBoundaryError("Tool output root must be a JSON object")

    if set(decoded.keys()) != {"tool", "status", "items"}:
        raise SecurityBoundaryError("Tool output must contain exact keys {'tool', 'status', 'items'}")

    tool_val = decoded["tool"]
    status_val = decoded["status"]
    items_val = decoded["items"]

    if (
        not isinstance(tool_val, str)
        or not (1 <= len(tool_val) <= 64)
        or not tool_val.strip()
        or not all(0x20 <= ord(ch) <= 0x7E for ch in tool_val)
    ):
        raise SecurityBoundaryError("Invalid 'tool' identifier")

    if not _is_valid_status(status_val):
        raise SecurityBoundaryError("Invalid 'status' value; expected 'ok' or 'error'")

    if not _is_object_list(items_val) or len(items_val) > max_items:
        raise SecurityBoundaryError("Invalid 'items' list or exceeds max_items")

    clean_items: list[str] = []
    for item in items_val:
        if (
            not isinstance(item, str)
            or len(item) > 256
            or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in item)
        ):
            raise SecurityBoundaryError("Invalid item string in 'items'")
        clean_items.append(item)

    return SafeToolResult(tool=tool_val, status=status_val, items=tuple(clean_items))
