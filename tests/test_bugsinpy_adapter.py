import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llm_pipeline.datasets.bugsinpy import BugsInPyAdapter
from llm_pipeline.exceptions import (
    DatasetCheckoutError,
    DatasetEnvironmentError,
    DatasetMetadataError,
)
from llm_pipeline.schemas import BugVersion, CommandResult
from llm_pipeline.workspace.manager import WorkspaceManager, WorkspacePaths


class FakeCommandRunner:
    """Return planned command results and keep the calls for assertions."""

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


def make_workspace(tmp_path: Path) -> WorkspacePaths:
    return WorkspaceManager(tmp_path / "workspaces").create_workspace("run_batch3")


def create_checkout_files(
    workspace: WorkspacePaths,
    project: str = "black",
) -> Path:
    project_path = workspace.repository / project
    project_path.mkdir(parents=True)
    (project_path / "bugsinpy_bug.info").write_text(
        '\n'.join(
            [
                'python_version="3.8.3"',
                'buggy_commit_id="buggy123"',
                'fixed_commit_id="fixed456"',
                'test_file="tests/test_one.py;tests/test_two.py"',
            ]
        ),
        encoding="utf-8",
    )
    (project_path / "bugsinpy_patchfile.info").write_text(
        "src/one.py;src/two.py;",
        encoding="utf-8",
    )
    return project_path


def test_bug_version_uses_bugsinpy_values() -> None:
    assert BugVersion.BUGGY.bugsinpy_value == "0"
    assert BugVersion.FIXED.bugsinpy_value == "1"


def test_validate_environment_runs_checkout_help(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    runner.add_result(stdout="usage")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    result = adapter.validate_environment(tmp_path)

    assert result.succeeded is True
    assert runner.calls[0][0] == ["bugsinpy-checkout", "--help"]


def test_validate_environment_reports_failed_help_command(tmp_path: Path) -> None:
    runner = FakeCommandRunner()
    runner.add_result(return_code=1, stderr="not ready")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    with pytest.raises(DatasetEnvironmentError, match="did not complete"):
        adapter.validate_environment(tmp_path)


def test_checkout_returns_bug_case_and_saves_metadata(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    checkout = adapter.checkout_bug("black", "1", workspace)

    assert checkout.succeeded is True
    assert checkout.bug_case.dataset == "BugsInPy"
    assert checkout.bug_case.project == "black"
    assert checkout.bug_case.buggy_revision == "buggy123"
    assert checkout.bug_case.fixed_revision == "fixed456"
    assert checkout.bug_case.triggering_tests == [
        "tests/test_one.py",
        "tests/test_two.py",
    ]
    assert checkout.bug_case.metadata["changed_files"] == [
        "src/one.py",
        "src/two.py",
    ]
    assert checkout.log_file.is_file()

    command = runner.calls[0][0]
    assert command[0] == "bugsinpy-checkout"
    assert command[command.index("-v") + 1] == "0"
    assert command[command.index("-w") + 1] == str(workspace.repository)


def test_checkout_fixed_version_uses_version_one(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    checkout = adapter.checkout_bug(
        "black",
        "1",
        workspace,
        version=BugVersion.FIXED,
    )

    command = runner.calls[0][0]
    assert command[command.index("-v") + 1] == "1"
    assert checkout.bug_case.metadata["selected_version"] == "fixed"


def test_checkout_uses_configured_executable_directory(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    executable_dir = tmp_path / "BugsInPy" / "framework" / "bin"
    adapter = BugsInPyAdapter(
        runner,  # type: ignore[arg-type]
        executable_directory=executable_dir,
    )

    adapter.checkout_bug("black", "1", workspace)

    assert runner.calls[0][0][0] == str(executable_dir / "bugsinpy-checkout")


def test_checkout_rejects_unsafe_project_name(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    adapter = BugsInPyAdapter(FakeCommandRunner())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="project may contain"):
        adapter.checkout_bug("../black", "1", workspace)


def test_checkout_rejects_non_numeric_bug_id(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    adapter = BugsInPyAdapter(FakeCommandRunner())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="digits only"):
        adapter.checkout_bug("black", "one", workspace)


def test_checkout_failure_is_logged(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(return_code=2, stderr="checkout failed")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    with pytest.raises(DatasetCheckoutError, match="checkout failed"):
        adapter.checkout_bug("black", "1", workspace)

    log_file = workspace.logs / "bugsinpy_checkout.json"
    assert log_file.is_file()
    saved = json.loads(log_file.read_text(encoding="utf-8"))
    assert saved["return_code"] == 2


def test_checkout_checks_that_project_folder_was_created(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(return_code=0)
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    with pytest.raises(DatasetCheckoutError, match="expected project folder"):
        adapter.checkout_bug("black", "1", workspace)


def test_read_metadata_ignores_comments_and_unknown_lines(tmp_path: Path) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    (project_path / "bugsinpy_bug.info").write_text(
        "# comment\npython_version='3.8'\ninvalid line\ntest_file=\"tests/a.py\"\n",
        encoding="utf-8",
    )

    metadata = BugsInPyAdapter.read_metadata(project_path)

    assert metadata == {
        "python_version": "3.8",
        "test_file": "tests/a.py",
    }


def test_read_metadata_requires_info_file(tmp_path: Path) -> None:
    with pytest.raises(DatasetMetadataError, match="was not found"):
        BugsInPyAdapter.read_metadata(tmp_path)


def test_compile_and_test_commands_use_project_folder(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    runner.add_result(stdout="compiled")
    runner.add_result(return_code=1, stderr="expected failing test")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]
    checkout = adapter.checkout_bug("black", "1", workspace)

    compile_result = adapter.compile_project(checkout)
    test_result = adapter.run_triggering_tests(checkout)

    assert compile_result.succeeded is True
    assert test_result.succeeded is False
    assert runner.calls[1][0] == ["bugsinpy-compile"]
    assert runner.calls[2][0] == ["bugsinpy-test"]
    assert runner.calls[1][1] == checkout.bug_case.workspace_path
    assert (workspace.logs / "bugsinpy_compile.json").is_file()
    assert (workspace.logs / "bugsinpy_test.json").is_file()


def test_baseline_stops_when_compile_fails(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    runner.add_result(return_code=1, stderr="compile failed")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    result = adapter.reproduce_baseline("black", "1", workspace)

    assert result.setup_succeeded is False
    assert result.test_result is None
    assert result.baseline_failure_observed is False
    assert len(runner.calls) == 2
    assert result.summary_file.is_file()


def test_baseline_records_expected_test_failure(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    runner.add_result(stdout="compiled")
    runner.add_result(return_code=1, stderr="one test failed")
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    result = adapter.reproduce_baseline("black", "1", workspace)

    assert result.setup_succeeded is True
    assert result.baseline_failure_observed is True
    summary = json.loads(result.summary_file.read_text(encoding="utf-8"))
    assert summary["test_result"]["return_code"] == 1


def test_baseline_does_not_treat_timeout_as_bug_failure(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    runner = FakeCommandRunner()
    runner.add_result(effect=lambda _command, _cwd: create_checkout_files(workspace))
    runner.add_result(stdout="compiled")
    runner.add_result(return_code=124, stderr="timed out", timed_out=True)
    adapter = BugsInPyAdapter(runner)  # type: ignore[arg-type]

    result = adapter.reproduce_baseline("black", "1", workspace)

    assert result.baseline_failure_observed is False
