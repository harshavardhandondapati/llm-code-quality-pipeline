"""Regression test for prepared BugsInPy source reset."""

from __future__ import annotations

import subprocess
from pathlib import Path

from llm_pipeline.workflow.runner import _reset_project_changes


def _git(repo: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_reset_restores_candidate_source_but_preserves_benchmark_test_patch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    source = repo / "example.py"
    benchmark_test = repo / "test_example.py"
    source.write_text("buggy = True\n", encoding="utf-8")
    benchmark_test.write_text("old_test = True\n", encoding="utf-8")
    _git(repo, "add", "example.py", "test_example.py")
    _git(repo, "commit", "-m", "buggy baseline")

    # BugsInPy copies the fixed-revision test into the buggy checkout. A model
    # later changes only the candidate application source file.
    benchmark_test.write_text("fixed_revision_test = True\n", encoding="utf-8")
    source.write_text("buggy = False\n", encoding="utf-8")
    _git(repo, "add", "example.py")

    _reset_project_changes(repo, files=["example.py"])

    assert source.read_text(encoding="utf-8") == "buggy = True\n"
    assert benchmark_test.read_text(encoding="utf-8") == "fixed_revision_test = True\n"

    staged_source = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", "example.py"],
        cwd=repo,
        check=False,
    )
    assert staged_source.returncode == 0


def test_reset_restores_deleted_candidate_without_resetting_benchmark_test(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    source = repo / "example.py"
    benchmark_test = repo / "test_example.py"
    source.write_text("buggy = True\n", encoding="utf-8")
    benchmark_test.write_text("old_test = True\n", encoding="utf-8")
    _git(repo, "add", "example.py", "test_example.py")
    _git(repo, "commit", "-m", "buggy baseline")

    benchmark_test.write_text("fixed_revision_test = True\n", encoding="utf-8")
    source.unlink()

    _reset_project_changes(repo, files=["example.py"])

    assert source.read_text(encoding="utf-8") == "buggy = True\n"
    assert benchmark_test.read_text(encoding="utf-8") == "fixed_revision_test = True\n"
