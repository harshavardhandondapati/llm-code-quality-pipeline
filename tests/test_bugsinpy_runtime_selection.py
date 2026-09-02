"""BugsInPy benchmark commands use the recorded target Python runtime."""

from pathlib import Path

from llm_pipeline.datasets.bugsinpy import BugsInPyAdapter
from llm_pipeline.schemas import BugCase, CommandResult, DatasetCheckoutResult


class CapturingRunner:
    def __init__(self) -> None:
        self.calls = []

    def run(
        self,
        command,
        working_directory,
        *,
        timeout_seconds=None,
        environment=None,
    ):
        self.calls.append(
            {
                "command": list(command),
                "working_directory": Path(working_directory),
                "timeout_seconds": timeout_seconds,
                "environment": dict(environment or {}),
            }
        )
        return CommandResult(
            command=list(command),
            working_directory=Path(working_directory),
            return_code=0,
            execution_time_seconds=0.01,
        )


def _checkout(tmp_path: Path, python_version: str | None) -> DatasetCheckoutResult:
    project = tmp_path / "workspace" / "repository" / "httpie"
    project.mkdir(parents=True)
    log_file = tmp_path / "workspace" / "logs" / "checkout.json"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("{}", encoding="utf-8")

    metadata = {}
    if python_version is not None:
        metadata["python_version"] = python_version

    bug_case = BugCase(
        dataset="BugsInPy",
        project="httpie",
        bug_id="1",
        language="python",
        workspace_path=project,
        metadata=metadata,
    )
    return DatasetCheckoutResult(
        bug_case=bug_case,
        command_result=CommandResult(
            command=["bugsinpy-checkout"],
            working_directory=tmp_path,
            return_code=0,
            execution_time_seconds=0.01,
        ),
        log_file=log_file,
    )


def test_compile_uses_recorded_python_version(tmp_path: Path) -> None:
    runner = CapturingRunner()
    adapter = BugsInPyAdapter(runner, executable_directory="/tools/bin")
    checkout = _checkout(tmp_path, "3.7.3")

    adapter.compile_project(checkout)

    assert runner.calls[-1]["environment"] == {"PYENV_VERSION": "3.7.3"}
    assert runner.calls[-1]["command"] == ["/tools/bin/bugsinpy-compile"]


def test_triggering_test_uses_recorded_python_version(tmp_path: Path) -> None:
    runner = CapturingRunner()
    adapter = BugsInPyAdapter(runner, executable_directory="/tools/bin")
    checkout = _checkout(tmp_path, "3.7.3")

    adapter.run_triggering_tests(checkout)

    assert runner.calls[-1]["environment"] == {"PYENV_VERSION": "3.7.3"}
    assert runner.calls[-1]["command"] == ["/tools/bin/bugsinpy-test"]


def test_missing_python_version_does_not_force_pyenv(tmp_path: Path) -> None:
    runner = CapturingRunner()
    adapter = BugsInPyAdapter(runner, executable_directory="/tools/bin")
    checkout = _checkout(tmp_path, None)

    adapter.compile_project(checkout)

    assert runner.calls[-1]["environment"] == {}
