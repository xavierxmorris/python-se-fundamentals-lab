"""M11 Drill B (Spec-First AI Pair): Workspace Artifact Runner.

WARNING: This "AI-generated" adapter contains 4 classic security vulnerabilities:
  1. Uses `os.path.commonprefix` for path confinement (character prefix, bypassed by `../ws_evil`).
  2. Executes external commands via `subprocess.run(..., shell=True)` with string interpolation.
  3. Interpolates `ORDER BY {sort_by} {direction}` via f-string without strict column allowlisting.
  4. Deserializes JSON manifests without enforcing `max_manifest_bytes` or strict schema validation.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from drill_a_core import SafeToolResult, SecurityBoundaryError

ALLOWED_SORT_COLUMNS: Final[frozenset[str]] = frozenset(
    {"artifact_id", "rel_path", "size_bytes", "created_seq"}
)
ALLOWED_DIRECTIONS: Final[frozenset[str]] = frozenset({"ASC", "DESC"})


@dataclass(slots=True, frozen=True)
class ArtifactRow:
    """Registered workspace artifact metadata persisted in SQLite."""

    artifact_id: str
    tenant: str
    rel_path: str
    size_bytes: int
    created_seq: int


@runtime_checkable
class CommandExecutor(Protocol):
    """Port executing a validated `argv` sequence without a shell."""

    def run_argv(self, argv: Sequence[str], *, cwd: Path) -> bytes: ...


class WorkspaceArtifactRunner:
    """Manages workspace artifacts, tool invocations, manifests, and sorted catalog queries."""

    def __init__(
        self,
        workspace_root: Path,
        db_conn: sqlite3.Connection,
        *,
        allowed_binaries: AbstractSet[str] = frozenset({"git", "sha256sum"}),
        max_manifest_bytes: int = 16_384,
        executor: CommandExecutor | None = None,
    ) -> None:
        self._workspace_root = workspace_root.resolve()
        self._db = db_conn
        self._allowed_binaries = frozenset(allowed_binaries)
        self._max_manifest_bytes = max_manifest_bytes
        self._executor = executor
        self._seq = 0
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                tenant TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_seq INTEGER NOT NULL
            )
            """
        )

    def _naive_path(self, rel_path: str) -> Path:
        candidate = (self._workspace_root / rel_path).resolve()
        if os.path.commonprefix([str(self._workspace_root), str(candidate)]) != str(
            self._workspace_root
        ):
            raise SecurityBoundaryError("Path outside workspace")
        return candidate

    def register_artifact(
        self,
        *,
        artifact_id: str,
        tenant: str,
        rel_path: str,
    ) -> ArtifactRow:
        """Validate `rel_path` inside `workspace_root` and record metadata in SQLite."""
        target = self._naive_path(rel_path)
        size_bytes = target.stat().st_size
        self._seq += 1
        row = ArtifactRow(
            artifact_id=artifact_id,
            tenant=tenant,
            rel_path=rel_path,
            size_bytes=size_bytes,
            created_seq=self._seq,
        )
        self._db.execute(
            "INSERT INTO artifacts (artifact_id, tenant, rel_path, size_bytes, created_seq) "
            "VALUES (?, ?, ?, ?, ?)",
            (row.artifact_id, row.tenant, row.rel_path, row.size_bytes, row.created_seq),
        )
        self._db.commit()
        return row

    def run_artifact_tool(
        self,
        binary: str,
        rel_path: str,
        extra_args: Sequence[str] = (),
    ) -> SafeToolResult:
        """Run an allowlisted tool binary against a confined workspace file and parse its JSON."""
        target = self._naive_path(rel_path)
        if self._executor is not None:
            raw_out = self._executor.run_argv((binary, *extra_args, str(target)), cwd=self._workspace_root)
        else:
            joined_args = " ".join(extra_args)
            cmd = f"{binary} {joined_args} {target}".strip()
            completed = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self._workspace_root),
                capture_output=True,
                check=True,
            )
            raw_out = completed.stdout

        payload = json.loads(raw_out.decode("utf-8"))
        return SafeToolResult(
            tool=str(payload.get("tool", binary)),
            status="ok" if payload.get("status") == "ok" else "error",
            items=tuple(str(x) for x in payload.get("items", [])),
        )

    def load_artifact_manifest(self, rel_path: str) -> SafeToolResult:
        """Read and validate an untrusted JSON tool manifest inside `workspace_root`."""
        target = self._naive_path(rel_path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        return SafeToolResult(
            tool=str(payload["tool"]),
            status="ok" if payload["status"] == "ok" else "error",
            items=tuple(str(x) for x in payload["items"]),
        )

    def list_artifacts(
        self,
        tenant: str,
        *,
        sort_by: str = "created_seq",
        direction: str = "ASC",
    ) -> list[ArtifactRow]:
        """List artifacts for `tenant` ordered by allowlisted `sort_by` and `direction`."""
        query = (
            "SELECT artifact_id, tenant, rel_path, size_bytes, created_seq "
            f"FROM artifacts WHERE tenant = ? ORDER BY {sort_by} {direction}"
        )
        rows = self._db.execute(query, (tenant,)).fetchall()
        return [
            ArtifactRow(
                artifact_id=str(r[0]),
                tenant=str(r[1]),
                rel_path=str(r[2]),
                size_bytes=int(r[3]),
                created_seq=int(r[4]),
            )
            for r in rows
        ]
