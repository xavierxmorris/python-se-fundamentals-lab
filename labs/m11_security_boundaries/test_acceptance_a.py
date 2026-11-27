"""Frozen acceptance suite for M11 Drill A (`drill_a_core.py`)."""

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


def test_resolve_sandbox_path_accepts_nested_and_rejects_escapes(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    nested = sandbox / "reports" / "q4.json"
    nested.parent.mkdir()
    nested.write_text("{}", encoding="utf-8")

    sibling_evil = tmp_path / "sandbox_evil"
    sibling_evil.mkdir()
    (sibling_evil / "secret.txt").write_text("top-secret", encoding="utf-8")

    resolved = resolve_sandbox_path(sandbox, "reports/q4.json")
    assert resolved == nested.resolve()

    missing_root = tmp_path / "does_not_exist"
    with pytest.raises(SecurityBoundaryError):
        resolve_sandbox_path(missing_root, "file.txt")

    file_as_root = nested
    with pytest.raises(SecurityBoundaryError):
        resolve_sandbox_path(file_as_root, "file.txt")

    bad_inputs = [
        "",
        "   ",
        "reports\x00.json",
        "/etc/passwd",
        "\\Windows\\System32\\drivers\\etc\\hosts",
        "C:\\Windows\\win.ini",
        "C:relative.txt",
        "../secret.txt",
        "reports/../../secret.txt",
        "../sandbox_evil/secret.txt",
    ]
    for bad in bad_inputs:
        with pytest.raises(SecurityBoundaryError):
            resolve_sandbox_path(sandbox, bad)

    outside_target = sibling_evil / "secret.txt"
    escape_link = sandbox / "escape_link.txt"
    try:
        os.symlink(outside_target, escape_link)
    except OSError:
        pass
    else:
        with pytest.raises(SecurityBoundaryError):
            resolve_sandbox_path(sandbox, "escape_link.txt")


def test_validate_outbound_url_enforces_https_allowlist_and_ssrf_blocks() -> None:
    allowed = {"API.Example.com", "hooks.partner.internal"}
    clean = validate_outbound_url("https://api.example.com/v1/tasks?limit=10", allowed)
    assert clean == "https://api.example.com/v1/tasks?limit=10"

    clean_upper = validate_outbound_url("https://HOOKS.PARTNER.INTERNAL:8443/notify", allowed)
    assert clean_upper == "https://hooks.partner.internal:8443/notify"

    rejected_urls = [
        "",
        "http://api.example.com/v1",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://api.example.com/v1 with space",
        "https://api.example.com/v1\r\nX-Injected: 1",
        "https://evil@api.example.com/v1",
        "https://user:pass@api.example.com/v1",
        "https://@api.example.com/v1",
        "https://untrusted.example.com/v1",
        "https://api.example.com.evil.com/v1",
        "https://127.0.0.1/admin",
        "https://10.0.0.5/internal",
        "https://192.168.1.1/router",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/loopback",
        "https://[::ffff:127.0.0.1]/mapped-loopback",
        "https://[::ffff:169.254.169.254]/mapped-imds",
    ]
    permissive_hosts = allowed | {
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
    }
    for bad_url in rejected_urls:
        with pytest.raises(SecurityBoundaryError):
            validate_outbound_url(bad_url, permissive_hosts)


def test_build_safe_command_enforces_binary_allowlist_and_option_terminator() -> None:
    argv = build_safe_command(
        "git",
        ["--evil-flag-neutralized", "main"],
        allowed_binaries={"git", "rg"},
    )
    assert argv == ("git", "--", "--evil-flag-neutralized", "main")

    bad_binaries = ["", "bash", "/usr/bin/git", "..\\git", "git -c", "git\x00", "C:git"]
    for bad_bin in bad_binaries:
        with pytest.raises(SecurityBoundaryError):
            build_safe_command(bad_bin, ["status"], allowed_binaries={"git", "rg"})

    for bad_arg in ["ok\x00hidden", "line1\nline2", "cr\rinject"]:
        with pytest.raises(SecurityBoundaryError):
            build_safe_command("git", [bad_arg], allowed_binaries={"git"})


def test_parse_untrusted_tool_output_enforces_size_keys_and_content_bounds() -> None:
    valid_raw = json.dumps(
        {"tool": "artifact_scan", "status": "ok", "items": ["alpha", "beta"]}
    ).encode("utf-8")
    parsed = parse_untrusted_tool_output(valid_raw)
    assert parsed == SafeToolResult(tool="artifact_scan", status="ok", items=("alpha", "beta"))

    # Byte cap checked BEFORE decode (invalid UTF-8 + oversize still raises SecurityBoundaryError)
    with pytest.raises(SecurityBoundaryError):
        parse_untrusted_tool_output(b"\xff" * 129, max_bytes=128)

    # Extra unknown key rejected
    with pytest.raises(SecurityBoundaryError):
        parse_untrusted_tool_output(
            json.dumps(
                {"tool": "scan", "status": "ok", "items": [], "unexpected": True}
            ).encode("utf-8")
        )

    # Missing key rejected
    with pytest.raises(SecurityBoundaryError):
        parse_untrusted_tool_output(json.dumps({"tool": "scan", "status": "ok"}).encode("utf-8"))

    # Invalid status, tool name, item count, item length, control char
    bad_payloads: list[dict[str, object]] = [
        {"tool": "", "status": "ok", "items": []},
        {"tool": "x" * 65, "status": "ok", "items": []},
        {"tool": "bad\x1btool", "status": "ok", "items": []},
        {"tool": "scan", "status": "pending", "items": []},
        {"tool": "scan", "status": "ok", "items": ["a", "b", "c"]},
        {"tool": "scan", "status": "ok", "items": ["x" * 257]},
        {"tool": "scan", "status": "ok", "items": ["line\nbreak"]},
        {"tool": "scan", "status": "ok", "items": [123]},
    ]
    for obj in bad_payloads:
        raw = json.dumps(obj).encode("utf-8")
        with pytest.raises(SecurityBoundaryError):
            parse_untrusted_tool_output(raw, max_items=2)
