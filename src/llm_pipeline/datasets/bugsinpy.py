"""Connect the pipeline to the BugsInPy command-line tools."""

from __future__ import annotations

import json
import re
from pathlib import Path

from llm_pipeline.datasets.base import DatasetAdapter
from llm_pipeline.exceptions import (
    CommandExecutionError,
    DatasetCheckoutError,
    DatasetEnvironmentError,
    DatasetMetadataError,
)
from llm_pipeline.schemas import (
    BaselineReproductionResult,
    BugCase,
    BugVersion,
    CommandResult,
    DatasetCheckoutResult,
)
from llm_pipeline.utils.command_runner import CommandRunner
from llm_pipeline.workspace.manager import WorkspacePaths


class BugsInPyAdapter(DatasetAdapter):
    """Run BugsInPy commands and convert their output into pipeline schemas."""

    DATASET_NAME = "BugsInPy"
    language = "python"
    source_file_extensions = (".py",)
    source_file_names: tuple[str, ...] = ()
    _SAFE_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

    def __init__(
        self,
        command_runner: CommandRunner,
        *,
        executable_directory: Path | str | None = None,
        timeout_seconds: float = 1200,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        self.command_runner = command_runner
        self.timeout_seconds = timeout_seconds
        self.executable_directory = (
            Path(executable_directory).expanduser()
            if executable_directory is not None
            else None
        )

    def validate_environment(self, working_directory: Path | str) -> CommandResult:
        """Run the checkout help command to confirm that BugsInPy is available."""
        command = [self._executable("bugsinpy-checkout"), "--help"]
        try:
            result = self.command_runner.run(
                command,
                working_directory,
                timeout_seconds=self.timeout_seconds,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                "BugsInPy could not be started. Check that framework/bin is on PATH "
                "or configure the executable directory."
            ) from error

        if not result.succeeded:
            raise DatasetEnvironmentError(
                "BugsInPy was found, but the checkout help command did not complete "
                "successfully."
            )
        return result

    def checkout_bug(
        self,
        project: str,
        bug_id: str,
        workspace: WorkspacePaths,
        *,
        version: BugVersion = BugVersion.BUGGY,
    ) -> DatasetCheckoutResult:
        """Check out one BugsInPy project and read the metadata copied with it."""
        self._validate_project(project)
        self._validate_bug_id(bug_id)

        project_path = workspace.repository / project
        if project_path.exists():
            raise DatasetCheckoutError(
                f"The project folder already exists and will not be overwritten: {project_path}"
            )

        command = [
            self._executable("bugsinpy-checkout"),
            "-p",
            project,
            "-i",
            bug_id,
            "-v",
            version.bugsinpy_value,
            "-w",
            str(workspace.repository),
        ]

        try:
            command_result = self.command_runner.run(
                command,
                workspace.root,
                timeout_seconds=self.timeout_seconds,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                "The bugsinpy-checkout command could not be started."
            ) from error

        log_file = workspace.logs / "bugsinpy_checkout.json"
        self._write_command_log(command_result, log_file)

        if not command_result.succeeded:
            raise DatasetCheckoutError(
                self._failure_message("BugsInPy checkout failed", command_result, log_file)
            )

        # Some BugsInPy scripts can finish without a non-zero return code when the
        # project or bug is invalid. Checking the folder gives us a reliable result.
        if not project_path.is_dir():
            raise DatasetCheckoutError(
                f"BugsInPy did not create the expected project folder: {project_path}. "
                f"Command details were saved to {log_file}."
            )

        metadata = self.read_metadata(project_path)
        self._write_pyenv_version(project_path, metadata.get("python_version"))
        changed_files = self._read_semicolon_file(
            project_path / "bugsinpy_patchfile.info"
        )
        triggering_tests = self._split_semicolon_value(metadata.get("test_file", ""))

        metadata.update(
            {
                "selected_version": version.value,
                "python_version": metadata.get("python_version"),
                "changed_files": changed_files,
                "checkout_log": str(log_file),
            }
        )

        bug_case = BugCase(
            dataset=self.DATASET_NAME,
            project=project,
            bug_id=bug_id,
            language="python",
            workspace_path=project_path,
            buggy_revision=metadata.get("buggy_commit_id"),
            fixed_revision=metadata.get("fixed_commit_id"),
            triggering_tests=triggering_tests,
            metadata=metadata,
        )

        return DatasetCheckoutResult(
            bug_case=bug_case,
            command_result=command_result,
            log_file=log_file,
        )

    def compile_project(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Run BugsInPy's compile step from the checked-out project folder."""
        result = self._run_project_command(
            checkout,
            command_name="bugsinpy-compile",
            log_name="bugsinpy_compile.json",
        )
        return result

    def run_triggering_tests(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Run the tests that BugsInPy associates with the selected bug."""
        result = self._run_project_command(
            checkout,
            command_name="bugsinpy-test",
            log_name="bugsinpy_test.json",
        )
        return result

    def reproduce_baseline(
        self,
        project: str,
        bug_id: str,
        workspace: WorkspacePaths,
    ) -> BaselineReproductionResult:
        """Prepare one buggy project and record whether its relevant test fails."""
        checkout = self.checkout_bug(
            project,
            bug_id,
            workspace,
            version=BugVersion.BUGGY,
        )
        compile_result = self.compile_project(checkout)

        # Running tests after a failed compile usually creates noise rather than
        # useful evidence, so the test step is skipped in that situation.
        test_result = (
            self.run_triggering_tests(checkout) if compile_result.succeeded else None
        )

        summary_file = workspace.outputs / "baseline_reproduction.json"
        result = BaselineReproductionResult(
            checkout=checkout,
            compile_result=compile_result,
            test_result=test_result,
            summary_file=summary_file,
        )
        summary_file.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def read_metadata(project_path: Path | str) -> dict[str, str]:
        """Read the simple key/value file placed in a BugsInPy checkout."""
        info_file = Path(project_path) / "bugsinpy_bug.info"
        if not info_file.is_file():
            raise DatasetMetadataError(
                f"BugsInPy metadata file was not found: {info_file}"
            )

        metadata: dict[str, str] = {}
        try:
            lines = info_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as error:
            raise DatasetMetadataError(
                f"Could not read BugsInPy metadata: {info_file}"
            ) from error

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            clean_key = key.strip()
            clean_value = value.strip().strip('"').strip("'")
            if clean_key:
                metadata[clean_key] = clean_value

        return metadata

    @staticmethod
    def _write_pyenv_version(project_path: Path, python_version: str | None) -> None:
        """Use the Python version requested by BugsInPy metadata when pyenv is available."""
        version = (python_version or "").strip()
        if not version:
            return
        if not re.fullmatch(r"\d+\.\d+(\.\d+)?", version):
            return
        (project_path / ".python-version").write_text(version + "\n", encoding="utf-8")

    def _run_project_command(
        self,
        checkout: DatasetCheckoutResult,
        *,
        command_name: str,
        log_name: str,
    ) -> CommandResult:
        project_path = checkout.bug_case.workspace_path
        if not project_path.is_dir():
            raise DatasetCheckoutError(
                f"Checked-out project folder does not exist: {project_path}"
            )

        runtime = str(
            checkout.bug_case.metadata.get("python_version") or ""
        ).strip()
        environment = {"PYENV_VERSION": runtime} if runtime else None

        try:
            result = self.command_runner.run(
                [self._executable(command_name)],
                project_path,
                timeout_seconds=self.timeout_seconds,
                environment=environment,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                f"The {command_name} command could not be started."
            ) from error

        log_file = self._logs_directory(checkout) / log_name
        self._write_command_log(result, log_file)
        return result

    def _executable(self, command_name: str) -> str:
        if self.executable_directory is None:
            return command_name
        return str(self.executable_directory / command_name)

    @classmethod
    def _validate_project(cls, project: str) -> None:
        if not project or not cls._SAFE_PROJECT.fullmatch(project):
            raise ValueError(
                "project may contain only letters, numbers, dots, underscores, and hyphens"
            )

    @staticmethod
    def _validate_bug_id(bug_id: str) -> None:
        if not bug_id or not bug_id.isdigit():
            raise ValueError("bug_id must contain digits only")

    @staticmethod
    def _split_semicolon_value(value: str) -> list[str]:
        return [item.strip() for item in value.split(";") if item.strip()]

    @classmethod
    def _read_semicolon_file(cls, path: Path) -> list[str]:
        if not path.is_file():
            return []
        try:
            return cls._split_semicolon_value(
                path.read_text(encoding="utf-8", errors="replace").strip()
            )
        except OSError:
            return []

    @staticmethod
    def _logs_directory(checkout: DatasetCheckoutResult) -> Path:
        # The checked-out project lives at <run>/repository/<project>.
        logs_directory = checkout.bug_case.workspace_path.parent.parent / "logs"
        logs_directory.mkdir(parents=True, exist_ok=True)
        return logs_directory

    @staticmethod
    def _write_command_log(result: CommandResult, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _failure_message(
        heading: str,
        result: CommandResult,
        log_file: Path,
    ) -> str:
        details = result.stderr.strip() or result.stdout.strip() or "No output was returned."
        short_details = details[:500]
        return f"{heading}: {short_details} Full command details were saved to {log_file}."
