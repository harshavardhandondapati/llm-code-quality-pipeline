from pathlib import Path

import pytest

from llm_pipeline.context.file_discovery import FileDiscovery
from llm_pipeline.exceptions import ContextBuildError


def test_discover_returns_python_files_in_stable_order(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "z_last.py").write_text("z = 1\n", encoding="utf-8")
    (project / "src" / "a_first.py").write_text("a = 1\n", encoding="utf-8")
    (project / "README.md").write_text("text", encoding="utf-8")

    files = FileDiscovery().discover(project)

    assert [path.name for path in files] == ["a_first.py", "z_last.py"]


def test_discover_skips_virtual_environment_and_cache_folders(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / ".venv" / "Lib").mkdir(parents=True)
    (project / "__pycache__").mkdir()
    (project / "src" / "main.py").write_text("value = 1\n", encoding="utf-8")
    (project / ".venv" / "Lib" / "dependency.py").write_text("x = 1\n", encoding="utf-8")
    (project / "__pycache__" / "cached.py").write_text("x = 1\n", encoding="utf-8")

    files = FileDiscovery().discover(project)

    assert [path.name for path in files] == ["main.py"]


def test_discover_rejects_missing_project_folder(tmp_path: Path) -> None:
    with pytest.raises(ContextBuildError, match="does not exist"):
        FileDiscovery().discover(tmp_path / "missing")


def test_resolve_project_file_handles_pytest_selector(tmp_path: Path) -> None:
    project = tmp_path / "project"
    test_file = project / "tests" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")

    resolved = FileDiscovery().resolve_project_file(
        project,
        "tests/test_example.py::test_example",
    )

    assert resolved == test_file.resolve()


def test_resolve_project_file_handles_project_name_prefix(tmp_path: Path) -> None:
    project = tmp_path / "black"
    source = project / "src" / "formatter.py"
    source.parent.mkdir(parents=True)
    source.write_text("def format_code():\n    pass\n", encoding="utf-8")

    resolved = FileDiscovery().resolve_project_file(
        project,
        "black/src/formatter.py",
    )

    assert resolved == source.resolve()


def test_resolve_project_file_does_not_return_external_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external.py"
    external.write_text("secret = True\n", encoding="utf-8")

    resolved = FileDiscovery().resolve_project_file(project, external)

    assert resolved is None


def test_relative_path_rejects_external_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "outside.py"
    external.write_text("x = 1\n", encoding="utf-8")

    with pytest.raises(ContextBuildError, match="outside the project root"):
        FileDiscovery.relative_path(project, external)
