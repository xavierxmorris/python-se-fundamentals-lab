"""Reference solution for M11 Drill B (`drill_b_ai_adapter.py`)."""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from drill_a_core import (
    SafeToolResult,
    SecurityBoundaryError,
    build_safe_command,
    parse_untrusted_tool_output,
    resolve_sandbox_path,
)

ALLOWED_SORT_COLUMNS: Final[frozenset[str]] = frozenset(
    {"artifact_id", "rel_path", "size_bytes", "created_seq"}
)
ALLOWED_DIRECTIONS: Final[frozenset[str]] = frozenset({"ASC", "DESC"})

_SORT_SQL_MAP: Final[dict[tuple[str, str], str]] = {
    ("artifact_id", "ASC"): "artifact_id ASC",
    ("artifact_id", "DESC"): "artifact_id DESC",
    ("rel_path", "ASC"): "rel_path ASC",
    ("rel_path", "DESC"): "rel_path DESC",
    ("size_bytes", "ASC"): "size_bytes ASC",
    ("size_bytes", "DESC"): "size_bytes DESC",
    ("created_seq", "ASC"): "created_seq ASC",
    ("created_seq", "DESC"): "created_seq DESC",
}


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
    """Confined workspace artifact manager enforcing path, argv, SQL, and JSON gates."""

    def __init__(
        self,
        workspace_root: Path,
        db_conn: sqlite3.Connection,
        *,
        allowed_binaries: AbstractSet[str] = frozenset({"git", "sha256sum"}),
        max_manifest_bytes: int = 16_384,
        executor: CommandExecutor | None = None,
    ) -> None:
        if max_manifest_bytes < 1:
            raise ValueError("max_manifest_bytes must be >= 1")
        try:
            root_real = workspace_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SecurityBoundaryError(f"Invalid workspace_root: {workspace_root}") from exc
        if not root_real.is_dir():
            raise SecurityBoundaryError("workspace_root must be an existing directory")

        self._workspace_root = root_real
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

    def _resolve_existing_file(self, rel_path: str) -> Path:
        target = resolve_sandbox_path(self._workspace_root, rel_path)
        if not target.is_file():
            raise SecurityBoundaryError(f"Artifact does not exist as regular file: {rel_path!r}")
        return target

    def register_artifact(
        self,
        *,
        artifact_id: str,
        tenant: str,
        rel_path: str,
    ) -> ArtifactRow:
        """Validate `rel_path` inside `workspace_root` and record metadata in SQLite."""
        if not artifact_id.strip() or not tenant.strip():
            raise SecurityBoundaryError("artifact_id and tenant must be non-empty")

        target = self._resolve_existing_file(rel_path)
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
        """Run an allowlisted tool binary against a confined workspace file without a shell."""
        target = self._resolve_existing_file(rel_path)
        argv = build_safe_command(
            binary,
            [*extra_args, str(target)],
            allowed_binaries=self._allowed_binaries,
        )
        if self._executor is not None:
            raw_out = self._executor.run_argv(argv, cwd=self._workspace_root)
        else:
            try:
                completed = subprocess.run(
                    list(argv),
                    shell=False,
                    cwd=str(self._workspace_root),
                    capture_output=True,
                    timeout=10.0,
                    check=True,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SecurityBoundaryError(f"Tool execution failed: {exc}") from exc
            raw_out = completed.stdout

        return parse_untrusted_tool_output(raw_out, max_bytes=self._max_manifest_bytes)

    def load_artifact_manifest(self, rel_path: str) -> SafeToolResult:
        """Read at most `max_manifest_bytes + 1` bytes from a confined file and schema-validate."""
        target = self._resolve_existing_file(rel_path)
        with target.open("rb") as fh:
            raw_bytes = fh.read(self._max_manifest_bytes + 1)
        return parse_untrusted_tool_output(raw_bytes, max_bytes=self._max_manifest_bytes)

    def list_artifacts(
        self,
        tenant: str,
        *,
        sort_by: str = "created_seq",
        direction: str = "ASC",
    ) -> list[ArtifactRow]:
        """List artifacts for `tenant` using strictly allowlisted `ORDER BY` clauses."""
        norm_dir = direction.upper()
        order_clause = _SORT_SQL_MAP.get((sort_by, norm_dir))
        if order_clause is None:
            raise SecurityBoundaryError(
                f"Disallowed sort column or direction: sort_by={sort_by!r}, direction={direction!r}"
            )

        query = (
            "SELECT artifact_id, tenant, rel_path, size_bytes, created_seq "
            f"FROM artifacts WHERE tenant = ? ORDER BY {order_clause}"
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
