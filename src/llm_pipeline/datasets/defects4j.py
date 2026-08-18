"""Connect the pipeline to the Defects4J command-line tools for Java bugs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from llm_pipeline.datasets.base import DatasetAdapter
from llm_pipeline.exceptions import (
    CommandExecutionError,
    DatasetCheckoutError,
    DatasetEnvironmentError,
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


class Defects4JAdapter(DatasetAdapter):
    """Run Defects4J commands and convert their output into pipeline schemas."""

    DATASET_NAME = "Defects4J"
    language = "java"
    source_file_extensions = (".java", ".xml", ".gradle", ".kts")
    source_file_names = ("pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle")

    _SAFE_PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    _SAFE_BUG_ID = re.compile(r"^[0-9]+$")

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
        """Confirm that Defects4J can run a real lightweight project query."""
        command = [self._executable("defects4j"), "info", "-p", "Chart"]
        try:
            result = self.command_runner.run(
                command,
                working_directory,
                timeout_seconds=self.timeout_seconds,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                "Defects4J could not be started. Check that the defects4j command is on PATH "
                "or configure PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY."
            ) from error

        output = f"{result.stdout}\n{result.stderr}"
        if not result.succeeded or "Project ID: Chart" not in output:
            raise DatasetEnvironmentError(
                "Defects4J was found, but 'defects4j info -p Chart' did not complete successfully."
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
        """Check out one Defects4J project version into an isolated workspace."""
        self._validate_project(project)
        self._validate_bug_id(bug_id)

        project_path = workspace.repository / f"{project}_{bug_id}_{version.value}"
        if project_path.exists():
            raise DatasetCheckoutError(
                f"The project folder already exists and will not be overwritten: {project_path}"
            )

        command = [
            self._executable("defects4j"),
            "checkout",
            "-p",
            project,
            "-v",
            version.defects4j_value(bug_id),
            "-w",
            str(project_path),
        ]

        try:
            command_result = self.command_runner.run(
                command,
                workspace.root,
                timeout_seconds=self.timeout_seconds,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                "The defects4j checkout command could not be started."
            ) from error

        log_file = workspace.logs / "defects4j_checkout.json"
        self._write_command_log(command_result, log_file)

        if not command_result.succeeded:
            raise DatasetCheckoutError(
                self._failure_message("Defects4J checkout failed", command_result, log_file)
            )

        if not project_path.is_dir():
            raise DatasetCheckoutError(
                f"Defects4J did not create the expected project folder: {project_path}. "
                f"Command details were saved to {log_file}."
            )

        metadata = self.read_metadata(project_path, workspace.logs)
        triggering_tests = self._split_lines(metadata.get("tests.trigger", ""))
        changed_files = self._modified_classes_to_files(
            metadata.get("classes.modified", ""),
            metadata.get("dir.src.classes", "src/main/java"),
        )

        metadata.update(
            {
                "selected_version": version.value,
                "changed_files": changed_files,
                "checkout_log": str(log_file),
                "defects4j_version": version.defects4j_value(bug_id),
            }
        )

        bug_case = BugCase(
            dataset=self.DATASET_NAME,
            project=project,
            bug_id=bug_id,
            language=self.language,
            workspace_path=project_path,
            triggering_tests=triggering_tests,
            metadata=metadata,
        )

        return DatasetCheckoutResult(
            bug_case=bug_case,
            command_result=command_result,
            log_file=log_file,
        )

    def compile_project(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Compile the checked-out Defects4J project."""
        return self._run_project_command(
            checkout,
            [self._executable("defects4j"), "compile"],
            "defects4j_compile.json",
        )

    def run_triggering_tests(self, checkout: DatasetCheckoutResult) -> CommandResult:
        """Run Defects4J triggering tests when available, otherwise run the project tests."""
        tests = checkout.bug_case.triggering_tests
        if tests:
            # The first Java pass keeps validation focused by running the first recorded
            # triggering test. A later extension can iterate over every trigger or run the
            # full suite once the Defects4J environment is stable.
            command = [self._executable("defects4j"), "test", "-t", tests[0]]
        else:
            command = [self._executable("defects4j"), "test"]
        return self._run_project_command(checkout, command, "defects4j_test.json")

    def reproduce_baseline(
        self,
        project: str,
        bug_id: str,
        workspace: WorkspacePaths,
    ) -> BaselineReproductionResult:
        """Check out a buggy Java project, compile it and run the relevant tests."""
        checkout = self.checkout_bug(
            project,
            bug_id,
            workspace,
            version=BugVersion.BUGGY,
        )
        compile_result = self.compile_project(checkout)
        test_result = self.run_triggering_tests(checkout) if compile_result.succeeded else None

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

    def read_metadata(self, project_path: Path | str, log_directory: Path | str) -> dict[str, str]:
        """Read useful Defects4J metadata with defects4j export."""
        project_root = Path(project_path).expanduser().resolve()
        logs = Path(log_directory).expanduser().resolve()
        metadata: dict[str, str] = {}
        for property_name in (
            "tests.trigger",
            "classes.modified",
            "classes.relevant",
            "dir.src.classes",
            "dir.src.tests",
        ):
            result = self.command_runner.run(
                [self._executable("defects4j"), "export", "-p", property_name],
                project_root,
                timeout_seconds=self.timeout_seconds,
            )
            safe_name = property_name.replace(".", "_")
            self._write_command_log(result, logs / f"defects4j_export_{safe_name}.json")
            if result.succeeded:
                metadata[property_name] = result.stdout.strip()
            else:
                metadata[property_name] = ""
        return metadata

    def _run_project_command(
        self,
        checkout: DatasetCheckoutResult,
        command: list[str],
        log_name: str,
    ) -> CommandResult:
        try:
            result = self.command_runner.run(
                command,
                checkout.bug_case.workspace_path,
                timeout_seconds=self.timeout_seconds,
            )
        except CommandExecutionError as error:
            raise DatasetEnvironmentError(
                f"The Defects4J command could not be started: {' '.join(command)}"
            ) from error

        log_file = Path(checkout.bug_case.metadata.get("checkout_log", checkout.log_file)).parent / log_name
        self._write_command_log(result, log_file)
        return result

    def _executable(self, command_name: str) -> str:
        if self.executable_directory is None:
            return command_name
        return str(self.executable_directory / command_name)

    @classmethod
    def _validate_project(cls, project: str) -> None:
        if not cls._SAFE_PROJECT.fullmatch(project):
            raise ValueError(
                "project may contain only letters, numbers, dots, underscores, and hyphens"
            )

    @classmethod
    def _validate_bug_id(cls, bug_id: str) -> None:
        if not cls._SAFE_BUG_ID.fullmatch(str(bug_id)):
            raise ValueError("bug_id must contain digits only")

    @staticmethod
    def _split_lines(value: str) -> list[str]:
        return [line.strip() for line in value.splitlines() if line.strip()]

    @classmethod
    def _modified_classes_to_files(cls, classes_text: str, source_directory: str) -> list[str]:
        files: list[str] = []
        source_root = source_directory.strip().strip("/") or "src/main/java"
        for class_name in cls._split_lines(classes_text):
            java_path = class_name.replace(".", "/") + ".java"
            files.append(f"{source_root}/{java_path}")
        return files

    @staticmethod
    def _write_command_log(result: CommandResult, log_file: Path) -> None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(
            json.dumps(result.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _failure_message(prefix: str, result: CommandResult, log_file: Path) -> str:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "no command output captured"
        return f"{prefix}: {detail}. Command details were saved to {log_file}."
