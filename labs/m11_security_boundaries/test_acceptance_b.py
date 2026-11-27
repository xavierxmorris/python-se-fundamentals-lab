"""Frozen acceptance suite for M11 Drill B (`drill_b_ai_adapter.py`)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from drill_a_core import SafeToolResult, SecurityBoundaryError
from drill_b_ai_adapter import CommandExecutor, WorkspaceArtifactRunner


class RecordingExecutor:
    """In-memory `CommandExecutor` recording argv invocations without spawning a shell."""

    def __init__(self, response: bytes) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self._response = response

    def run_argv(self, argv: Sequence[str], *, cwd: Path) -> bytes:
        self.calls.append((tuple(argv), cwd))
        return self._response


def test_executor_satisfies_protocol() -> None:
    fake = RecordingExecutor(b"{}")
    assert isinstance(fake, CommandExecutor)


def test_sibling_prefix_traversal_blocked_in_register_and_manifest(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "ok.txt").write_text("hello", encoding="utf-8")

    ws_evil = tmp_path / "workspace_evil"
    ws_evil.mkdir()
    (ws_evil / "stolen.json").write_text(
        json.dumps({"tool": "steal", "status": "ok", "items": ["secret"]}),
        encoding="utf-8",
    )

    conn = sqlite3.connect(":memory:")
    try:
        runner = WorkspaceArtifactRunner(ws, conn)
        row = runner.register_artifact(artifact_id="a1", tenant="acme", rel_path="ok.txt")
        assert row.size_bytes == 5

        with pytest.raises(SecurityBoundaryError):
            runner.register_artifact(
                artifact_id="evil",
                tenant="acme",
                rel_path="../workspace_evil/stolen.json",
            )

        with pytest.raises(SecurityBoundaryError):
            runner.load_artifact_manifest("../workspace_evil/stolen.json")
    finally:
        conn.close()


def test_command_runner_enforces_binary_allowlist_and_double_dash(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    target = ws / "bundle.tar"
    target.write_bytes(b"data")

    valid_json = json.dumps({"tool": "git", "status": "ok", "items": ["clean"]}).encode("utf-8")
    exec_spy = RecordingExecutor(valid_json)

    conn = sqlite3.connect(":memory:")
    try:
        runner = WorkspaceArtifactRunner(
            ws,
            conn,
            allowed_binaries={"git"},
            executor=exec_spy,
        )
        result = runner.run_artifact_tool("git", "bundle.tar", extra_args=["--stat"])
        assert result == SafeToolResult(tool="git", status="ok", items=("clean",))
        assert len(exec_spy.calls) == 1
        recorded_argv, recorded_cwd = exec_spy.calls[0]
        assert recorded_argv == ("git", "--", "--stat", str(target.resolve()))
        assert recorded_cwd == ws.resolve()

        with pytest.raises(SecurityBoundaryError):
            runner.run_artifact_tool("sh", "bundle.tar", extra_args=["-c", "whoami"])

        with pytest.raises(SecurityBoundaryError):
            runner.run_artifact_tool("git", "bundle.tar", extra_args=["bad\narg"])
    finally:
        conn.close()


def test_sql_order_by_injection_rejected_and_valid_sorts_work(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "small.bin").write_bytes(b"12")
    (ws / "large.bin").write_bytes(b"123456")

    conn = sqlite3.connect(":memory:")
    try:
        runner = WorkspaceArtifactRunner(ws, conn)
        runner.register_artifact(artifact_id="a-small", tenant="acme", rel_path="small.bin")
        runner.register_artifact(artifact_id="a-large", tenant="acme", rel_path="large.bin")
        runner.register_artifact(artifact_id="other", tenant="globex", rel_path="small.bin")

        desc_rows = runner.list_artifacts("acme", sort_by="size_bytes", direction="desc")
        assert [r.artifact_id for r in desc_rows] == ["a-large", "a-small"]

        injection_vectors = [
            ("size_bytes DESC; DROP TABLE artifacts --", "ASC"),
            ("(SELECT CASE WHEN 1=1 THEN created_seq ELSE size_bytes END)", "ASC"),
            ("tenant", "ASC"),
            ("size_bytes", "ASC LIMIT 1 --"),
        ]
        for bad_col, bad_dir in injection_vectors:
            with pytest.raises(SecurityBoundaryError):
                runner.list_artifacts("acme", sort_by=bad_col, direction=bad_dir)
    finally:
        conn.close()


def test_manifest_enforces_byte_limit_and_strict_schema(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    good_manifest = ws / "good.json"
    good_manifest.write_text(
        json.dumps({"tool": "checker", "status": "ok", "items": ["item-1"]}),
        encoding="utf-8",
    )
    extra_key_manifest = ws / "extra.json"
    extra_key_manifest.write_text(
        json.dumps({"tool": "checker", "status": "ok", "items": [], "injected": "yes"}),
        encoding="utf-8",
    )
    huge_manifest = ws / "huge.json"
    huge_manifest.write_bytes(b"{" + b" " * 2048 + b"}")

    conn = sqlite3.connect(":memory:")
    try:
        runner = WorkspaceArtifactRunner(ws, conn, max_manifest_bytes=512)
        assert runner.load_artifact_manifest("good.json") == SafeToolResult(
            tool="checker",
            status="ok",
            items=("item-1",),
        )
        with pytest.raises(SecurityBoundaryError):
            runner.load_artifact_manifest("extra.json")
        with pytest.raises(SecurityBoundaryError):
            runner.load_artifact_manifest("huge.json")
    finally:
        conn.close()
