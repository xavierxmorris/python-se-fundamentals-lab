"""Reference learner test suite for M11 Drill A (`drill_a_core.py`)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from drill_a_core import (
    SafeToolResult,
    SecurityBoundaryError,
    build_safe_command,
    parse_untrusted_tool_output,
    resolve_sandbox_path,
    validate_outbound_url,
)


def test_resolve_sandbox_path_blocks_sibling_prefix_dotdot_drives_and_symlinks(
    tmp_path: Path,
) -> None:
    """Kills `bug_sibling_prefix_bypass` and verifies full path confinement."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ok_file = sandbox / "sub" / "artifact.txt"
    ok_file.parent.mkdir()
    ok_file.write_text("safe", encoding="utf-8")

    sibling = tmp_path / "sandbox_evil"
    sibling.mkdir()
    outside_secret = sibling / "file.txt"
    outside_secret.write_text("secret", encoding="utf-8")

    assert resolve_sandbox_path(sandbox, "sub/artifact.txt") == ok_file.resolve()

    for vector in (
        "",
        "   ",
        "sub/\x00evil.txt",
        "/etc/passwd",
        "\\Windows\\win.ini",
        "C:\\Windows\\win.ini",
        "C:evil.txt",
        "../file.txt",
        "../sandbox_evil/file.txt",
    ):
        with pytest.raises(SecurityBoundaryError):
            resolve_sandbox_path(sandbox, vector)

    sym_path = sandbox / "sym_outside.txt"
    try:
        os.symlink(outside_secret, sym_path)
    except OSError:
        pass
    else:
        with pytest.raises(SecurityBoundaryError):
            resolve_sandbox_path(sandbox, "sym_outside.txt")


def test_validate_outbound_url_blocks_userinfo_and_ipv6_mapped_loopback() -> None:
    """Kills `bug_url_userinfo_and_mapped_ipv6`."""
    allowed = {"allowed.example.com", "::ffff:127.0.0.1", "169.254.169.254"}
    assert (
        validate_outbound_url("https://ALLOWED.example.com/api/v1", allowed)
        == "https://allowed.example.com/api/v1"
    )

    for bad_url in (
        "http://allowed.example.com/api",
        "https://evil@allowed.example.com/api",
        "https://user:secret@allowed.example.com/api",
        "https://[::ffff:127.0.0.1]/internal",
        "https://[::1]/internal",
        "https://169.254.169.254/latest/meta-data",
        "https://127.0.0.1/admin",
    ):
        with pytest.raises(SecurityBoundaryError):
            validate_outbound_url(bad_url, allowed)


def test_parse_untrusted_tool_output_rejects_oversize_and_extra_keys() -> None:
    """Kills `bug_untrusted_output_extra_keys_and_size`."""
    good = json.dumps({"tool": "linter", "status": "error", "items": ["E001"]}).encode("utf-8")
    assert parse_untrusted_tool_output(good, max_bytes=256) == SafeToolResult(
        tool="linter",
        status="error",
        items=("E001",),
    )

    oversized = json.dumps(
        {"tool": "linter", "status": "ok", "items": ["x" * 200]}
    ).encode("utf-8")
    with pytest.raises(SecurityBoundaryError):
        parse_untrusted_tool_output(oversized, max_bytes=64)

    extra_keys = json.dumps(
        {"tool": "linter", "status": "ok", "items": [], "__proto__": "polluted"}
    ).encode("utf-8")
    with pytest.raises(SecurityBoundaryError):
        parse_untrusted_tool_output(extra_keys)


def test_build_safe_command_inserts_double_dash_and_rejects_control_chars() -> None:
    """Kills `bug_command_missing_double_dash_and_newlines`."""
    cmd = build_safe_command("rg", ["--files", "needle"], allowed_binaries={"rg"})
    assert cmd == ("rg", "--", "--files", "needle")

    with pytest.raises(SecurityBoundaryError):
        build_safe_command("rg", ["injected\nflag"], allowed_binaries={"rg"})

    with pytest.raises(SecurityBoundaryError):
        build_safe_command("rg", ["injected\rflag"], allowed_binaries={"rg"})

    with pytest.raises(SecurityBoundaryError):
        build_safe_command("rg", ["null\x00byte"], allowed_binaries={"rg"})
