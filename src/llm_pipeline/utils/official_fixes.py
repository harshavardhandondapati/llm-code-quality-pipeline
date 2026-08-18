"""Helpers for deterministic benchmark-fixed evidence used by mock/fallback modes."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def resolve_bugsinpy_command(command_name: str = "bugsinpy-checkout") -> str | None:
    """Resolve a BugsInPy executable from environment, .env, or PATH."""
    configured_dir = os.environ.get("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY", "").strip()
    if configured_dir:
        candidate = Path(configured_dir) / command_name
        if candidate.exists():
            return str(candidate)

    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                candidate = Path(value) / command_name
                if candidate.exists():
                    return str(candidate)

    return shutil.which(command_name)


def checkout_bugsinpy_fixed_project(
    *,
    buggy_project_path: Path,
    project: str,
    bug_id: str,
    timeout_seconds: int = 1200,
) -> tuple[Path | None, str]:
    """Checkout the official fixed BugsInPy project beside the buggy checkout.

    Returns (fixed_project_path, message). The fixed version is used only for
    deterministic mock/fallback evidence, never for real OpenRouter repair.
    """
    command = resolve_bugsinpy_command("bugsinpy-checkout")
    if not command:
        return None, "BugsInPy checkout command was not available."

    safe_project = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in project)
    safe_bug = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in str(bug_id))
    fixed_parent = buggy_project_path.parent / f"_official_fixed_BugsInPy_{safe_project}_{safe_bug}_parent"
    fixed_project = fixed_parent / project

    if fixed_project.is_dir():
        return fixed_project, "Official fixed BugsInPy project already existed."

    shutil.rmtree(fixed_parent, ignore_errors=True)
    fixed_parent.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        [command, "-p", project, "-i", str(bug_id), "-v", "1", "-w", str(fixed_parent)],
        cwd=buggy_project_path.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout_seconds,
        check=False,
    )

    if completed.returncode != 0 or not fixed_project.is_dir():
        return None, "Official fixed BugsInPy checkout failed. " + completed.stdout[-1200:]

    return fixed_project, "Official fixed BugsInPy project checked out successfully."
