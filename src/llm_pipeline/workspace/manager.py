"""Create isolated folders for individual pipeline runs."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from llm_pipeline.exceptions import WorkspaceError


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    """The folders used by one pipeline run."""

    root: Path
    repository: Path
    logs: Path
    outputs: Path


class WorkspaceManager:
    """Manage temporary run folders below one configured root directory."""

    _SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def create_workspace(self, run_id: str | None = None) -> WorkspacePaths:
        """Create a clean workspace and return its standard subfolders."""
        selected_run_id = run_id or self.generate_run_id()
        self._validate_run_id(selected_run_id)

        root = self.workspace_root / selected_run_id
        if root.exists():
            raise WorkspaceError(f"Workspace already exists: {root}")

        paths = self._build_paths(root)
        try:
            paths.repository.mkdir(parents=True)
            paths.logs.mkdir()
            paths.outputs.mkdir()
        except OSError as error:
            if root.exists():
                shutil.rmtree(root, ignore_errors=True)
            raise WorkspaceError(f"Could not create workspace {root}: {error}") from error

        return paths

    def reset_workspace(self, workspace: WorkspacePaths | Path | str) -> WorkspacePaths:
        """Remove a run's contents and recreate the standard empty folders."""
        root = self._workspace_root_from(workspace)
        self._ensure_safe_child(root)

        if root.exists():
            shutil.rmtree(root)

        paths = self._build_paths(root)
        paths.repository.mkdir(parents=True)
        paths.logs.mkdir()
        paths.outputs.mkdir()
        return paths

    def remove_workspace(self, workspace: WorkspacePaths | Path | str) -> bool:
        """Delete one workspace. Return False when it is already absent."""
        root = self._workspace_root_from(workspace)
        self._ensure_safe_child(root)

        if not root.exists():
            return False
        if not root.is_dir():
            raise WorkspaceError(f"Workspace path is not a directory: {root}")

        shutil.rmtree(root)
        return True

    def get_workspace(self, run_id: str) -> WorkspacePaths:
        """Return the expected paths for an existing workspace."""
        self._validate_run_id(run_id)
        root = (self.workspace_root / run_id).resolve()
        self._ensure_safe_child(root)
        if not root.is_dir():
            raise WorkspaceError(f"Workspace does not exist: {root}")
        return self._build_paths(root)

    @staticmethod
    def generate_run_id() -> str:
        """Create a readable identifier with a timestamp and short random suffix."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"run_{timestamp}_{uuid4().hex[:8]}"

    def _validate_run_id(self, run_id: str) -> None:
        if not run_id or not self._SAFE_RUN_ID.fullmatch(run_id):
            raise WorkspaceError(
                "run_id may contain only letters, numbers, dots, underscores, and hyphens"
            )

    def _workspace_root_from(self, workspace: WorkspacePaths | Path | str) -> Path:
        value = workspace.root if isinstance(workspace, WorkspacePaths) else Path(workspace)
        return value.expanduser().resolve()

    def _ensure_safe_child(self, path: Path) -> None:
        if path == self.workspace_root or self.workspace_root not in path.parents:
            raise WorkspaceError(
                f"Refusing to modify a path outside the workspace root: {path}"
            )

    @staticmethod
    def _build_paths(root: Path) -> WorkspacePaths:
        return WorkspacePaths(
            root=root,
            repository=root / "repository",
            logs=root / "logs",
            outputs=root / "outputs",
        )
