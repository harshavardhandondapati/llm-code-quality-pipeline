import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_pipeline.datasets.defects4j import Defects4JAdapter
from llm_pipeline.datasets.factory import (
    candidate_report_file_name,
    create_dataset_adapter,
    normalise_dataset_name,
)
from llm_pipeline.exceptions import DatasetCheckoutError, DatasetEnvironmentError
from llm_pipeline.schemas import BugVersion, CommandResult
from llm_pipeline.workspace.manager import WorkspaceManager, WorkspacePaths


class FakeCommandRunner:
    def __init__(self) -> None:
        self.plans: list[
            tuple[int, str, str, bool, Callable[[list[str], Path], None] | None]
        ] = []
        self.calls: list[tuple[list[str], Path, float | None]] = []

    def add_result(
        self,
        *,
        return_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        effect: Callable[[list[str], Path], None] | None = None,
    ) -> None:
        self.plans.append((return_code, stdout, stderr, timed_out, effect))

    def run(
        self,
        command: list[str],
        working_directory: Path | str,
        *,
        timeout_seconds: float | None = None,
        environment: dict[str, str] | None = None,
    ) -> CommandResult:
        if not self.plans:
            raise AssertionError("No fake command result was prepared")
        work_dir = Path(working_directory)
        self.calls.append((list(command), work_dir, timeout_seconds))
        return_code, stdout, stderr, timed_out, effect = self.plans.pop(0)
        if effect is not None:
            effect(list(command), work_dir)
        return CommandResult(
            command=list(command),
            working_directory=work_dir,
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            execution_time_seconds=0.01,
            timed_out=timed_out,
        )


class SettingsStub:
    defects4j_executable_directory: Path | None = None
    bugsinpy_executable_directory: Path | None = None
    test_timeout_seconds = 2400


def make_workspace(tmp_path: Path) -> WorkspacePaths:
    return WorkspaceManager(tmp_path / "workspaces").create_workspace("run_java")


def create_defects4j_checkout(workspace: WorkspacePaths, project: str = "Chart") -> Path:
    project_path = workspace.repository / f"{project}_1_buggy"
    (project_path / "src" / "main" / "java" / "org" / "jfree" / "chart").mkdir(parents=True)
    (project_path / "src" / "main" / "java" / "org" / "jfree" / "chart" / "Title.java").write_text(
        "package org.jfree.chart;\npublic class Title {}\n",
        encoding="utf-8",
    )
    return project_path


def add_metadata_exports(runner: FakeCommandRunner) -> None:
    runner.add_result(stdout="org.jfree.chart.TitleTest::testBug\n")
    runner.add_result(stdout="org.jfree.chart.Title\n")
    runner.add_result(stdout="org.jfree.chart.Title\n")
    runner.add_result(stdout="src/main/java\n")
    runner.add_result(stdout="src/test/java\n")


def test_bug_version_uses_defects4j_values() -> None:
    assert BugVersion.BUGGY.defects4j_value("1") == "1b"
    assert BugVersion.FIXED.defects4j_value("1") == "1f"


def test_validate_environment_runs_defects4j_info(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    runner.add_result(stdout="Project ID: Chart\\nNumber of bugs: 26\\n")
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]

    result = adapter.validate_environment(tmp_path)

    assert result.succeeded is True
    assert runner.calls[0][0] == ["defects4j", "info", "-p", "Chart"]

def test_validate_environment_reports_failed_help_command(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    runner.add_result(return_code=1, stderr="not ready")
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]

    with pytest.raises(DatasetEnvironmentError, match="did not complete"):
        adapter.validate_environment(tmp_path)


def test_checkout_returns_java_bug_case_and_metadata(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_defects4j_checkout(workspace))
    add_metadata_exports(runner)
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]

    checkout = adapter.checkout_bug("Chart", "1", workspace)

    assert checkout.succeeded is True
    assert checkout.bug_case.dataset == "Defects4J"
    assert checkout.bug_case.language == "java"
    assert checkout.bug_case.project == "Chart"
    assert checkout.bug_case.triggering_tests == ["org.jfree.chart.TitleTest::testBug"]
    assert checkout.bug_case.metadata["changed_files"] == [
        "src/main/java/org/jfree/chart/Title.java"
    ]
    assert (workspace.logs / "defects4j_checkout.json").is_file()
    assert (workspace.logs / "defects4j_export_tests_trigger.json").is_file()

    command = runner.calls[0][0]
    assert command[:6] == ["defects4j", "checkout", "-p", "Chart", "-v", "1b"]
    assert command[command.index("-w") + 1].endswith("Chart_1_buggy")


def test_checkout_fixed_version_uses_defects4j_fixed_suffix(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()

    def create_fixed(_command: list[str], _cwd: Path) -> None:
        (workspace.repository / "Chart_1_fixed").mkdir(parents=True)

    runner.add_result(effect=create_fixed)
    add_metadata_exports(runner)
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]

    checkout = adapter.checkout_bug("Chart", "1", workspace, version=BugVersion.FIXED)

    command = runner.calls[0][0]
    assert command[command.index("-v") + 1] == "1f"
    assert checkout.bug_case.metadata["selected_version"] == "fixed"


def test_compile_and_triggering_test_commands_use_project_folder(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_defects4j_checkout(workspace))
    add_metadata_exports(runner)
    runner.add_result(stdout="compiled")
    runner.add_result(return_code=1, stderr="Failing tests: 1")
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]
    checkout = adapter.checkout_bug("Chart", "1", workspace)

    compile_result = adapter.compile_project(checkout)
    test_result = adapter.run_triggering_tests(checkout)

    assert compile_result.succeeded is True
    assert test_result.succeeded is False
    assert runner.calls[-2][0] == ["defects4j", "compile"]
    assert runner.calls[-1][0] == ["defects4j", "test", "-t", "org.jfree.chart.TitleTest::testBug"]
    assert runner.calls[-1][1] == checkout.bug_case.workspace_path
    assert (workspace.logs / "defects4j_compile.json").is_file()
    assert (workspace.logs / "defects4j_test.json").is_file()


def test_checkout_failure_is_logged(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(return_code=2, stderr="checkout failed")
    adapter = Defects4JAdapter(runner)  # type: ignore[arg-type]

    with pytest.raises(DatasetCheckoutError, match="checkout failed"):
        adapter.checkout_bug("Chart", "1", workspace)

    saved = json.loads((workspace.logs / "defects4j_checkout.json").read_text(encoding="utf-8"))
    assert saved["return_code"] == 2


def test_dataset_factory_selects_defects4j() -> None:
    runner = FakeCommandRunner()
    adapter = create_dataset_adapter("defects4j", runner, SettingsStub())  # type: ignore[arg-type]

    assert isinstance(adapter, Defects4JAdapter)
    assert normalise_dataset_name("defects-4j") == "defects4j"
    assert candidate_report_file_name("defects4j") == "defects4j_candidate_selection.json"
