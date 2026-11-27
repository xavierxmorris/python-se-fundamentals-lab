"""Seeded subtle security mutants for M11 Gate 4 mutation testing."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from types import ModuleType
from typing import Literal, TypeIs
from urllib.parse import urlsplit, urlunsplit

from drill_a_core import SafeToolResult, SecurityBoundaryError


def _is_str_object_dict(val: object) -> TypeIs[dict[str, object]]:
    return isinstance(val, dict)


def _is_object_list(val: object) -> TypeIs[list[object]]:
    return isinstance(val, list)


def _is_valid_status(val: object) -> TypeIs[Literal["ok", "error"]]:
    return val in ("ok", "error")


def _bug_sibling_prefix_bypass(mod: ModuleType) -> None:
    """Bug 1: Uses `str(candidate).startswith(str(root_real))` allowing `../sandbox_evil`."""

    def buggy_resolve_sandbox_path(sandbox_root: Path, untrusted_rel: str) -> Path:
        try:
            root_real = sandbox_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SecurityBoundaryError("sandbox_root does not exist") from exc
        if not root_real.is_dir():
            raise SecurityBoundaryError("sandbox_root must be a directory")
        if (
            not untrusted_rel
            or not untrusted_rel.strip()
            or "\x00" in untrusted_rel
            or untrusted_rel.startswith(("/", "\\"))
            or ":" in untrusted_rel
        ):
            raise SecurityBoundaryError("Invalid relative path")
        candidate = (root_real / untrusted_rel).resolve(strict=False)
        if not str(candidate).startswith(str(root_real)):
            raise SecurityBoundaryError("Path escapes sandbox")
        return candidate

    mod.__dict__["resolve_sandbox_path"] = buggy_resolve_sandbox_path


def _bug_url_userinfo_and_mapped_ipv6(mod: ModuleType) -> None:
    """Bug 2: Allows `user@host` credentials and ignores IPv6/IPv4-mapped loopback IPs."""

    def buggy_validate_outbound_url(raw_url: str, allowed_hosts: AbstractSet[str]) -> str:
        if not raw_url or "\\" in raw_url or any(ch.isspace() or ord(ch) < 0x20 for ch in raw_url):
            raise SecurityBoundaryError("Invalid URL characters")
        parsed = urlsplit(raw_url)
        if parsed.scheme.lower() != "https" or parsed.hostname is None:
            raise SecurityBoundaryError("HTTPS URL with hostname required")
        host = parsed.hostname.lower()
        try:
            ipv4 = ipaddress.IPv4Address(host)
        except ValueError:
            ipv4 = None
        if ipv4 is not None and (
            ipv4.is_loopback or ipv4.is_private or ipv4.is_link_local or not ipv4.is_global
        ):
            raise SecurityBoundaryError("Forbidden IPv4 literal")
        normalized_allowed = {
            h[1:-1].lower() if h.startswith("[") and h.endswith("]") else h.lower()
            for h in allowed_hosts
        }
        if host not in normalized_allowed:
            raise SecurityBoundaryError("Host not in allowlist")
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, parsed.fragment))

    mod.__dict__["validate_outbound_url"] = buggy_validate_outbound_url


def _bug_untrusted_output_extra_keys_and_size(mod: ModuleType) -> None:
    """Bug 3: Ignores `max_bytes` cap and permits unknown extra keys in JSON object."""

    def buggy_parse_untrusted_tool_output(
        raw_bytes: bytes,
        *,
        max_bytes: int = 16_384,
        max_items: int = 50,
    ) -> SafeToolResult:
        _ = max_bytes
        try:
            decoded = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecurityBoundaryError("Malformed JSON") from exc
        if not _is_str_object_dict(decoded):
            raise SecurityBoundaryError("Expected JSON object")
        if not {"tool", "status", "items"}.issubset(decoded.keys()):
            raise SecurityBoundaryError("Missing required keys")
        tool_val = decoded["tool"]
        status_val = decoded["status"]
        items_val = decoded["items"]
        if (
            not isinstance(tool_val, str)
            or not (1 <= len(tool_val) <= 64)
            or not tool_val.strip()
            or not all(0x20 <= ord(ch) <= 0x7E for ch in tool_val)
        ):
            raise SecurityBoundaryError("Invalid tool field")
        if not _is_valid_status(status_val):
            raise SecurityBoundaryError("Invalid status")
        if not _is_object_list(items_val) or len(items_val) > max_items:
            raise SecurityBoundaryError("Invalid items")
        clean_items: list[str] = []
        for entry in items_val:
            if not isinstance(entry, str) or len(entry) > 256 or any(ord(c) < 0x20 for c in entry):
                raise SecurityBoundaryError("Invalid item")
            clean_items.append(entry)
        return SafeToolResult(tool=tool_val, status=status_val, items=tuple(clean_items))

    mod.__dict__["parse_untrusted_tool_output"] = buggy_parse_untrusted_tool_output


def _bug_command_missing_double_dash_and_newlines(mod: ModuleType) -> None:
    """Bug 4: Omits `'--'` option terminator and allows `'\\n'` / `'\\r'` in arguments."""

    def buggy_build_safe_command(
        binary: str,
        args: Sequence[str],
        *,
        allowed_binaries: AbstractSet[str],
    ) -> tuple[str, ...]:
        if (
            not binary
            or "\x00" in binary
            or any(ch.isspace() or ord(ch) < 0x20 for ch in binary)
            or "/" in binary
            or "\\" in binary
            or ":" in binary
            or binary not in allowed_binaries
        ):
            raise SecurityBoundaryError("Disallowed binary")
        for arg in args:
            if "\x00" in arg:
                raise SecurityBoundaryError("Null byte in arg")
        return (binary, *args)

    mod.__dict__["build_safe_command"] = buggy_build_safe_command


SEEDED_BUGS: dict[str, Callable[[ModuleType], None]] = {
    "bug_sibling_prefix_bypass": _bug_sibling_prefix_bypass,
    "bug_url_userinfo_and_mapped_ipv6": _bug_url_userinfo_and_mapped_ipv6,
    "bug_untrusted_output_extra_keys_and_size": _bug_untrusted_output_extra_keys_and_size,
    "bug_command_missing_double_dash_and_newlines": _bug_command_missing_double_dash_and_newlines,
}
