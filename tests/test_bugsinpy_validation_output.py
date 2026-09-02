"""Regression tests for BugsInPy wrapper-output validation."""

from pathlib import Path

from llm_pipeline.repair.apply_patch import _test_output_passed
from llm_pipeline.schemas import CommandResult


def _result(*, return_code: int = 0, stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(
        command=["bugsinpy-test"],
        working_directory=Path("."),
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        execution_time_seconds=0.01,
    )


def test_bugsinpy_zero_wrapper_code_with_inner_traceback_is_failure() -> None:
    result = _result(
        stdout=(
            "pytest tests/test_downloads.py::TestDownloadUtils::test_unique_filename\n"
            "RUN EVERY COMMAND\n"
            "0\n"
            "Traceback (most recent call last):\n"
            "  File \"env/lib/python3.10/site-packages/_pytest/main.py\", line 12\n"
            "ImportError: cannot import name 'MutableMapping' from 'collections'\n"
            "During handling of the above exception, another exception occurred:\n"
            "ModuleNotFoundError: No module named 'UserDict'\n"
        )
    )

    assert _test_output_passed(result, dataset="BugsInPy") is False


def test_bugsinpy_clean_zero_wrapper_code_can_pass() -> None:
    result = _result(
        stdout=(
            "pytest tests/test_downloads.py::TestDownloadUtils::test_unique_filename\n"
            "1 passed in 0.08s\n"
        )
    )

    assert _test_output_passed(result, dataset="BugsInPy") is True


def test_bugsinpy_nonzero_wrapper_code_fails() -> None:
    result = _result(return_code=1, stdout="1 failed in 0.08s")

    assert _test_output_passed(result, dataset="BugsInPy") is False


def test_defects4j_failing_count_behaviour_is_unchanged() -> None:
    passed = _result(stdout="Failing tests: 0")
    failed = _result(stdout="Failing tests: 1")

    assert _test_output_passed(passed, dataset="Defects4J") is True
    assert _test_output_passed(failed, dataset="Defects4J") is False
