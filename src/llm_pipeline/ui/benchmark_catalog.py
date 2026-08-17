"""Discover benchmark projects and bug IDs for the Streamlit runner."""

from __future__ import annotations

import csv
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from llm_pipeline.runtime_tools import tool_directory_candidates


@dataclass(frozen=True)
class BugCatalog:
    """Projects and bug IDs available for one benchmark dataset."""

    dataset: str
    label: str
    projects: dict[str, list[str]]
    source: str
    message: str = ""

    @property
    def available(self) -> bool:
        return bool(self.projects)


def discover_benchmark_catalog(project_root: Path | str | None = None) -> dict[str, BugCatalog]:
    """Return available BugsInPy and Defects4J bug choices.

    The UI uses this at runtime. If a benchmark tool is not installed, a small
    verified fallback is returned so the evidence dashboard remains usable.
    """
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    return {
        "bugsinpy": _discover_bugsinpy(root),
        "defects4j": _discover_defects4j(root),
    }


def _discover_bugsinpy(root: Path) -> BugCatalog:
    projects_dir = _find_bugsinpy_projects_dir(root)
    if projects_dir is not None:
        projects = _scan_bugsinpy_projects(projects_dir)
        if projects:
            return BugCatalog(
                dataset="bugsinpy",
                label="BugsInPy",
                projects=projects,
                source=str(projects_dir),
                message="Projects were discovered from the local BugsInPy metadata.",
            )

    return BugCatalog(
        dataset="bugsinpy",
        label="BugsInPy",
        projects={"httpie": ["1"]},
        source="verified fallback",
        message="BugsInPy was not found, so only the verified httpie-1 evidence case is listed.",
    )


def _discover_defects4j(root: Path) -> BugCatalog:
    # Prefer metadata inside the supplied project root. This keeps unit tests
    # isolated and makes cloud deployments use ./tools before any global command.
    projects_dir = _find_defects4j_projects_dir(root)
    if projects_dir is not None:
        projects = _scan_defects4j_projects(projects_dir)
        if projects:
            return BugCatalog(
                dataset="defects4j",
                label="Defects4J",
                projects=projects,
                source=str(projects_dir),
                message="Projects were discovered from the local Defects4J metadata.",
            )

    command_projects = _defects4j_projects_from_command(root)
    if command_projects:
        return BugCatalog(
            dataset="defects4j",
            label="Defects4J",
            projects=command_projects,
            source="defects4j command",
            message="Projects were discovered using the local Defects4J command.",
        )

    return BugCatalog(
        dataset="defects4j",
        label="Defects4J",
        projects={"Chart": ["1"]},
        source="verified fallback",
        message="Defects4J was not found, so only the verified Chart-1 evidence case is listed.",
    )


def _find_bugsinpy_projects_dir(root: Path) -> Path | None:
    candidates: list[Path] = []
    for tools_dir in tool_directory_candidates(root):
        candidates.extend(
            [
                tools_dir / "BugsInPy" / "projects",
                tools_dir / "bugsinpy" / "projects",
            ]
        )
    candidates.append(root / "BugsInPy" / "projects")

    executable_dir = os.environ.get("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY", "").strip()
    if executable_dir:
        bin_dir = Path(executable_dir).expanduser().resolve()
        # Usual layout: BugsInPy/framework/bin -> BugsInPy/projects.
        candidates.insert(0, bin_dir.parents[1] / "projects" if len(bin_dir.parents) > 1 else bin_dir / "projects")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _scan_bugsinpy_projects(projects_dir: Path) -> dict[str, list[str]]:
    projects: dict[str, list[str]] = {}
    for project_dir in sorted(projects_dir.iterdir()):
        bugs_dir = project_dir / "bugs"
        if not project_dir.is_dir() or not bugs_dir.is_dir():
            continue
        bug_ids = sorted(
            [path.name for path in bugs_dir.iterdir() if path.is_dir() and path.name.isdigit()],
            key=lambda value: int(value),
        )
        if bug_ids:
            projects[project_dir.name] = bug_ids
    return projects


def _find_defects4j_projects_dir(root: Path) -> Path | None:
    candidates: list[Path] = []
    for tools_dir in tool_directory_candidates(root):
        candidates.extend(
            [
                tools_dir / "defects4j" / "framework" / "projects",
                tools_dir / "Defects4J" / "framework" / "projects",
            ]
        )

    executable_dir = os.environ.get("PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY", "").strip()
    if executable_dir:
        bin_dir = Path(executable_dir).expanduser().resolve()
        candidates.insert(0, bin_dir.parent / "projects")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _scan_defects4j_projects(projects_dir: Path) -> dict[str, list[str]]:
    projects: dict[str, list[str]] = {}
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        bug_file = project_dir / "active-bugs.csv"
        if not bug_file.is_file():
            continue
        bug_ids = _bug_ids_from_csv(bug_file)
        if bug_ids:
            projects[project_dir.name] = bug_ids
    return projects


def _bug_ids_from_csv(path: Path) -> list[str]:
    bug_ids: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            value = row[0].strip()
            if value.isdigit():
                bug_ids.add(value)
    return sorted(bug_ids, key=lambda value: int(value))


def _defects4j_projects_from_command(root: Path) -> dict[str, list[str]]:
    defects4j = _resolve_defects4j_command()
    if not defects4j:
        return {}

    pids = _run_command([defects4j, "pids"], root)
    project_ids = _parse_tokens(pids, allow_letters=True)
    projects: dict[str, list[str]] = {}
    for project_id in project_ids:
        bids = _run_command([defects4j, "bids", "-p", project_id], root)
        bug_ids = _parse_tokens(bids, allow_letters=False)
        if bug_ids:
            projects[project_id] = sorted(bug_ids, key=lambda value: int(value))
    return projects


def _resolve_defects4j_command() -> str | None:
    executable_dir = os.environ.get("PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY", "").strip()
    if executable_dir:
        candidate = Path(executable_dir).expanduser() / "defects4j"
        if candidate.exists():
            return str(candidate)
    return shutil.which("defects4j")


def _run_command(command: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _parse_tokens(output: str, *, allow_letters: bool) -> list[str]:
    values: list[str] = []
    pattern = r"[A-Za-z][A-Za-z0-9_+-]*" if allow_letters else r"\d+"
    for match in re.findall(pattern, output):
        if match not in values:
            values.append(match)
    return values


def option_count(projects: dict[str, list[str]]) -> int:
    """Return the number of selectable bug cases in a project map."""
    return sum(len(ids) for ids in projects.values())


def project_names(projects: dict[str, list[str]]) -> list[str]:
    """Sort project names for stable display."""
    return sorted(projects, key=lambda value: value.lower())
