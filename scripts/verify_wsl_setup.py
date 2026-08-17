"""Check the local WSL environment needed by the final pipeline."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from llm_pipeline.config import get_settings


def main() -> None:
    settings = get_settings()
    settings.ensure_runtime_directories()
    print("Python settings loaded: OK")
    print(f"workspace_root: {settings.workspace_root}")
    print(f"timeout_seconds: {settings.test_timeout_seconds}")

    if not settings.bugsinpy_executable_directory:
        raise SystemExit("PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY is not set in .env")
    bin_dir = settings.bugsinpy_executable_directory
    checkout = bin_dir / "bugsinpy-checkout"
    compile_cmd = bin_dir / "bugsinpy-compile"
    test_cmd = bin_dir / "bugsinpy-test"
    for path in [checkout, compile_cmd, test_cmd]:
        print(f"{path.name}: {'OK' if path.exists() else 'MISSING'}")
        if not path.exists():
            raise SystemExit(f"Missing BugsInPy command: {path}")

    result = subprocess.run([str(checkout), "--help"], text=True, capture_output=True, check=False, timeout=60)
    print(f"bugsinpy-checkout --help return code: {result.returncode}")
    if result.returncode != 0:
        raise SystemExit("BugsInPy help command did not complete successfully")
    if shutil.which("git") is None:
        raise SystemExit("git command was not found")
    print("WSL environment verification: OK")


if __name__ == "__main__":
    main()
