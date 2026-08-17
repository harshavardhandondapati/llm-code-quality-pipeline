from pathlib import Path

import pytest

from llm_pipeline.exceptions import WorkspaceError
from llm_pipeline.workspace.manager import WorkspaceManager


def test_create_workspace_builds_standard_folders(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    workspace = manager.create_workspace("run_test_001")

    assert workspace.root.is_dir()
    assert workspace.repository.is_dir()
    assert workspace.logs.is_dir()
    assert workspace.outputs.is_dir()


def test_create_workspace_generates_unique_run_ids(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    first = manager.create_workspace()
    second = manager.create_workspace()

    assert first.root != second.root
    assert first.root.name.startswith("run_")
    assert second.root.name.startswith("run_")


def test_duplicate_workspace_is_not_overwritten(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    manager.create_workspace("same_run")

    with pytest.raises(WorkspaceError, match="already exists"):
        manager.create_workspace("same_run")


def test_reset_workspace_removes_old_files(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create_workspace("reset_me")
    old_file = workspace.repository / "old.py"
    old_file.write_text("print('old')", encoding="utf-8")

    reset = manager.reset_workspace(workspace)

    assert old_file.exists() is False
    assert reset.repository.is_dir()
    assert reset.logs.is_dir()
    assert reset.outputs.is_dir()


def test_remove_workspace_deletes_run_folder(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.create_workspace("remove_me")

    removed = manager.remove_workspace(workspace)

    assert removed is True
    assert workspace.root.exists() is False
    assert manager.remove_workspace(workspace) is False


def test_get_workspace_returns_existing_paths(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    created = manager.create_workspace("existing_run")

    loaded = manager.get_workspace("existing_run")

    assert loaded == created


def test_run_id_cannot_escape_workspace_root(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    with pytest.raises(WorkspaceError, match="run_id"):
        manager.create_workspace("../outside")


def test_remove_workspace_refuses_external_path(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    external = tmp_path / "do-not-delete"
    external.mkdir()

    with pytest.raises(WorkspaceError, match="outside the workspace root"):
        manager.remove_workspace(external)

    assert external.is_dir()
