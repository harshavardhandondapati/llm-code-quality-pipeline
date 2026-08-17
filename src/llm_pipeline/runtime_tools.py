"""Resolve benchmark tool locations for local and cloud runs."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root for this installed source tree."""
    return Path(__file__).resolve().parents[2]


def configured_tools_directory(root: Path | None = None) -> Path:
    """Return the preferred benchmark tools directory.

    The deployed Docker image uses /app/tools. Local runs use ./tools when it
    exists. PIPELINE_TOOLS_DIRECTORY can override both.
    """
    configured = os.environ.get("PIPELINE_TOOLS_DIRECTORY", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = (root or project_root()).resolve()
    return base / "tools"


def tool_directory_candidates(root: Path | None = None) -> list[Path]:
    """Return benchmark tool roots in preference order."""
    base = (root or project_root()).resolve()
    values = [configured_tools_directory(base), base / "tools", Path("/app/tools"), Path("/opt/tools")]
    unique: list[Path] = []
    for value in values:
        resolved = value.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def bugsinpy_bin_directory(root: Path | None = None) -> Path | None:
    """Return a BugsInPy framework/bin directory if it exists."""
    for tools_dir in tool_directory_candidates(root):
        for name in ("BugsInPy", "bugsinpy"):
            candidate = tools_dir / name / "framework" / "bin"
            if (candidate / "bugsinpy-checkout").exists():
                return candidate
    return None


def defects4j_bin_directory(root: Path | None = None) -> Path | None:
    """Return a Defects4J framework/bin directory if it exists."""
    for tools_dir in tool_directory_candidates(root):
        for name in ("defects4j", "Defects4J"):
            candidate = tools_dir / name / "framework" / "bin"
            if (candidate / "defects4j").exists():
                return candidate
    return None
