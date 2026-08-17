"""Find readable project files without leaving the checked-out repository."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Iterable

from llm_pipeline.exceptions import ContextBuildError


class FileDiscovery:
    """Discover configured source/build files and resolve file references safely."""

    DEFAULT_EXCLUDED_DIRECTORIES = {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "env",
        "htmlcov",
        "node_modules",
        "site-packages",
        "venv",
    }

    def __init__(
        self,
        *,
        extensions: Iterable[str] = (".py",),
        include_file_names: Iterable[str] | None = None,
        excluded_directories: Iterable[str] | None = None,
    ) -> None:
        self.extensions = {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in extensions
        }
        self.include_file_names = {
            file_name.lower() for file_name in (include_file_names or ())
        }
        self.excluded_directories = set(
            excluded_directories or self.DEFAULT_EXCLUDED_DIRECTORIES
        )

    def discover(self, project_root: Path | str) -> list[Path]:
        """Return project source files in a stable order."""
        root = self._validated_root(project_root)
        discovered: list[Path] = []

        for current_root, directories, files in os.walk(root):
            # Pruning here avoids walking through virtual environments and build output.
            directories[:] = sorted(
                directory
                for directory in directories
                if directory not in self.excluded_directories
            )

            current_path = Path(current_root)
            for file_name in sorted(files):
                path = current_path / file_name
                if not self._is_supported_file(path) or path.is_symlink():
                    continue
                if self._is_inside(root, path):
                    discovered.append(path.resolve())

        return sorted(discovered, key=lambda path: path.relative_to(root).as_posix())

    def resolve_project_file(
        self,
        project_root: Path | str,
        raw_path: str | Path,
    ) -> Path | None:
        """Resolve one reported path when it points to a real project file."""
        root = self._validated_root(project_root)
        text = str(raw_path).strip().strip('"').strip("'")
        if not text:
            return None

        # Test selectors can look like tests/test_file.py::test_name or Class::method.
        text = text.split("::", 1)[0].strip()
        if not text:
            return None

        candidates: list[Path] = []
        supplied = Path(text)
        if supplied.is_absolute():
            candidates.append(supplied)
        else:
            normalised = Path(*PureWindowsPath(text).parts)
            candidates.append(root / normalised)

            # Some tools report paths prefixed with the project folder name.
            if normalised.parts and normalised.parts[0] == root.name:
                candidates.append(root.joinpath(*normalised.parts[1:]))

        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if (
                self._is_inside(root, resolved)
                and not self._has_excluded_part(root, resolved)
                and resolved.is_file()
                and self._is_supported_file(resolved)
            ):
                return resolved

        # Absolute traceback paths can come from another temporary checkout. Matching
        # their trailing path keeps the logic useful while still returning a local file.
        parts = PureWindowsPath(text).parts
        for size in range(min(len(parts), 6), 0, -1):
            suffix = Path(*parts[-size:])
            possible = (root / suffix).resolve()
            if (
                self._is_inside(root, possible)
                and not self._has_excluded_part(root, possible)
                and possible.is_file()
                and self._is_supported_file(possible)
            ):
                return possible

        return None


    def _is_supported_file(self, path: Path) -> bool:
        """Return True when the file matches the configured source/build inputs."""
        return (
            path.suffix.lower() in self.extensions
            or path.name.lower() in self.include_file_names
        )

    def _has_excluded_part(self, project_root: Path, path: Path) -> bool:
        """Return True when a resolved path is under ignored tooling/dependency folders."""
        try:
            relative_parts = path.resolve().relative_to(project_root.resolve()).parts
        except ValueError:
            return True
        return any(part in self.excluded_directories for part in relative_parts)

    @staticmethod
    def relative_path(project_root: Path | str, path: Path | str) -> str:
        """Return a portable path relative to the checked-out project."""
        root = Path(project_root).expanduser().resolve()
        resolved = Path(path).expanduser().resolve()
        if not FileDiscovery._is_inside(root, resolved):
            raise ContextBuildError(f"File is outside the project root: {resolved}")
        return resolved.relative_to(root).as_posix()

    @staticmethod
    def _validated_root(project_root: Path | str) -> Path:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ContextBuildError(f"Project folder does not exist: {root}")
        return root

    @staticmethod
    def _is_inside(root: Path, path: Path) -> bool:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
        return resolved_path == resolved_root or resolved_root in resolved_path.parents
