import sys
from pathlib import Path

import pytest

from llm_pipeline.exceptions import CommandExecutionError
from llm_pipeline.utils.command_runner import CommandRunner


def test_runner_captures_successful_command(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(
        [sys.executable, "-c", "print('hello from batch 2')"],
        tmp_path,
    )

    assert result.succeeded is True
    assert result.return_code == 0
    assert result.stdout.strip() == "hello from batch 2"
    assert result.stderr == ""
    assert result.execution_time_seconds >= 0


def test_runner_records_non_zero_return_code(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import sys; print('expected failure', file=sys.stderr); sys.exit(3)",
        ],
        tmp_path,
    )

    assert result.succeeded is False
    assert result.return_code == 3
    assert "expected failure" in result.stderr
    assert result.timed_out is False


def test_runner_marks_a_timeout(tmp_path: Path) -> None:
    runner = CommandRunner(default_timeout_seconds=0.1)

    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(2)"],
        tmp_path,
    )

    assert result.succeeded is False
    assert result.return_code == CommandRunner.TIMEOUT_RETURN_CODE
    assert result.timed_out is True
    assert "timed out" in result.stderr.lower()


def test_runner_merges_environment_values(tmp_path: Path) -> None:
    runner = CommandRunner()

    result = runner.run(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ['BATCH_TWO_VALUE'])",
        ],
        tmp_path,
        environment={"BATCH_TWO_VALUE": "available"},
    )

    assert result.stdout.strip() == "available"


def test_runner_rejects_a_string_command(tmp_path: Path) -> None:
    runner = CommandRunner()

    with pytest.raises(TypeError, match="sequence of separate arguments"):
        runner.run("python -V", tmp_path)  # type: ignore[arg-type]


def test_runner_rejects_missing_working_directory(tmp_path: Path) -> None:
    runner = CommandRunner()

    with pytest.raises(CommandExecutionError, match="Working directory"):
        runner.run([sys.executable, "-V"], tmp_path / "missing")


def test_runner_reports_missing_executable(tmp_path: Path) -> None:
    runner = CommandRunner()

    with pytest.raises(CommandExecutionError, match="Could not start command"):
        runner.run(["command-that-does-not-exist-12345"], tmp_path)
