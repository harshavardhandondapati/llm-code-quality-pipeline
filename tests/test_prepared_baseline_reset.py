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


def test_reset_restores_head_even_when_repair_is_staged(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")

    source = repo / "example.py"
    source.write_text("buggy = True\n", encoding="utf-8")
    _git(repo, "add", "example.py")
    _git(repo, "commit", "-m", "buggy baseline")

    source.write_text("buggy = False\n", encoding="utf-8")
    _git(repo, "add", "example.py")

    _reset_project_changes(repo)

    assert source.read_text(encoding="utf-8") == "buggy = True\n"

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo,
        check=False,
    )
    working = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=repo,
        check=False,
    )
    assert staged.returncode == 0
    assert working.returncode == 0
