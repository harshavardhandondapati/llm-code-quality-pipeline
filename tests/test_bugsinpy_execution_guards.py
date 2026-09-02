"""Regression tests for BugsInPy execution, scope, and cache safety guards."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from llm_pipeline.datasets.bugsinpy import classify_bugsinpy_test_result
from llm_pipeline.repair.apply_patch import (
    _apply_llm_patch_by_search,
    _compile_after_patch,
    _normalise_patch_block,
    _repair_scope_violation,
    apply_generated_patch,
)
from llm_pipeline.schemas import BugCase, CommandResult, DatasetCheckoutResult
from llm_pipeline.workflow import runner as workflow_runner
from llm_pipeline.workflow.runner import _baseline_failed, _install_checked_out_project


def _command_result(
    tmp_path: Path,
    *,
    return_code: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> CommandResult:
    return CommandResult(
        command=["bugsinpy-test"],
        working_directory=tmp_path,
        return_code=return_code,
        stdout=stdout,
        stderr=stderr,
        execution_time_seconds=0.01,
    )


def _checkout(project: Path) -> DatasetCheckoutResult:
    project.mkdir(parents=True, exist_ok=True)
    log_file = project.parent / "checkout.json"
    log_file.write_text("{}", encoding="utf-8")
    return DatasetCheckoutResult(
        bug_case=BugCase(
            dataset="BugsInPy",
            project="sample",
            bug_id="1",
            language="python",
            workspace_path=project,
            metadata={"python_version": "3.7.3", "changed_files": ["package/target.py"]},
        ),
        command_result=CommandResult(
            command=["bugsinpy-checkout"],
            working_directory=project.parent,
            return_code=0,
            execution_time_seconds=0.01,
        ),
        log_file=log_file,
    )


def test_classifier_accepts_real_pytest_failure(tmp_path: Path) -> None:
    result = _command_result(
        tmp_path,
        return_code=0,
        stdout=(
            "============================= FAILURES =============================\n"
            "AttributeError: missing application helper\n"
            "=========================== 1 failed in 0.10s ===========================\n"
        ),
    )

    assert classify_bugsinpy_test_result(result) == "failed"
    assert _baseline_failed(result, dataset="bugsinpy") is True


def test_classifier_rejects_collection_import_error_even_with_wrapper_zero_and_fail_file(
    tmp_path: Path,
) -> None:
    (tmp_path / "bugsinpy_fail.txt").write_text("pytest failed to collect\n", encoding="utf-8")
    result = _command_result(
        tmp_path,
        return_code=0,
        stdout=(
            "==================================== ERRORS ====================================\n"
            "ERROR collecting tests/test_target.py\n"
            "ImportError while importing test module '/tmp/tests/test_target.py'.\n"
            "ModuleNotFoundError: No module named 'sample'\n"
            "=========================== 1 error in 0.10s =============================\n"
        ),
    )

    assert classify_bugsinpy_test_result(result) == "error"
    assert _baseline_failed(result, dataset="bugsinpy") is False


def test_classifier_rejects_old_pytest_startup_crash(tmp_path: Path) -> None:
    result = _command_result(
        tmp_path,
        stdout=(
            "Traceback (most recent call last):\n"
            "  File 'env/lib/python3.10/site-packages/_pytest/main.py', line 12\n"
            "ImportError: cannot import name 'MutableMapping' from 'collections'\n"
            "ModuleNotFoundError: No module named 'UserDict'\n"
        ),
    )

    assert classify_bugsinpy_test_result(result) == "error"
    assert _baseline_failed(result, dataset="BugsInPy") is False


def test_classifier_accepts_clean_pass(tmp_path: Path) -> None:
    result = _command_result(
        tmp_path,
        stdout=(
            "collected 1 item\n"
            "tests/test_target.py .\n"
            "=========================== 1 passed in 0.10s ===========================\n"
        ),
    )

    assert classify_bugsinpy_test_result(result) == "passed"


def test_repair_scope_rejects_non_candidate_file() -> None:
    fix_result = {
        "patch": "--- a/package/other.py\n+++ b/package/other.py\n@@ -1 +1 @@\n-old\n+new\n",
        "files_modified": ["package/other.py"],
        "fixed_files": {},
    }

    reason = _repair_scope_violation(
        fix_result=fix_result,
        patch_text=fix_result["patch"],
        allowed_files=["package/target.py"],
    )

    assert reason is not None
    assert "package/other.py" in reason


def test_apply_patch_stops_before_compile_when_repair_leaves_file_scope(tmp_path: Path) -> None:
    project = tmp_path / "project"
    package = project / "package"
    package.mkdir(parents=True)
    target = package / "target.py"
    other = package / "other.py"
    target.write_text("value = 1\n", encoding="utf-8")
    other.write_text("old = True\n", encoding="utf-8")
    checkout = _checkout(project)

    class AdapterThatMustNotRun:
        def compile_project(self, checkout):  # pragma: no cover - should never run
            raise AssertionError("compile should be skipped for scope violation")

        def run_triggering_tests(self, checkout):  # pragma: no cover - should never run
            raise AssertionError("tests should be skipped for scope violation")

    fix_result = {
        "patch": (
            "--- a/package/other.py\n"
            "+++ b/package/other.py\n"
            "@@ -1 +1 @@\n"
            "-old = True\n"
            "+old = False\n"
        ),
        "files_modified": ["package/other.py"],
        "fixed_files": {},
    }

    validation = apply_generated_patch(
        checkout=checkout,
        fix_result=fix_result,
        adapter=AdapterThatMustNotRun(),  # type: ignore[arg-type]
        outputs_dir=tmp_path / "outputs",
        allowed_files=["package/target.py"],
    )

    assert validation["patch_applied"] is False
    assert validation["compilation_passed"] is False
    assert "outside the benchmark candidate scope" in validation["failure_reason"]
    assert other.read_text(encoding="utf-8") == "old = True\n"


def test_bugsinpy_post_patch_compile_reuses_prepared_env(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "package" / "target.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    env_bin = project / "env" / "bin"
    env_bin.mkdir(parents=True)
    (env_bin / "python").symlink_to(Path(sys.executable).resolve())
    checkout = _checkout(project)

    class AdapterThatMustNotCompile:
        def compile_project(self, checkout):  # pragma: no cover - should never run
            raise AssertionError("bugsinpy-compile must not rebuild prepared env")

    result = _compile_after_patch(
        checkout=checkout,
        adapter=AdapterThatMustNotCompile(),  # type: ignore[arg-type]
        project_root=project,
        target_files=["package/target.py"],
    )

    assert result.succeeded is True
    assert result.command[1:3] == ["-m", "py_compile"]
    assert str(source.resolve()) in result.command


def test_editable_install_preserves_benchmark_dependencies(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    env_python = project / "env" / "bin" / "python"
    env_python.parent.mkdir(parents=True)
    env_python.write_text("", encoding="utf-8")
    (project / "setup.py").write_text("from setuptools import setup\nsetup()\n", encoding="utf-8")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(workflow_runner.subprocess, "run", fake_run)

    result = _install_checked_out_project(project, log_dir)

    assert result is not None and result.succeeded
    assert captured["command"] == [
        str(env_python),
        "-m",
        "pip",
        "install",
        "--no-deps",
        "-e",
        ".",
    ]
    saved = json.loads((log_dir / "project_editable_install.json").read_text(encoding="utf-8"))
    assert saved["return_code"] == 0


def test_detection_must_stay_inside_candidate_scope() -> None:
    from llm_pipeline.workflow.runner import _detection_matches_file_scope

    candidates = ["httpie/downloads.py"]
    assert _detection_matches_file_scope(
        {"bug_found": True, "file_path": "httpie/downloads.py"},
        candidates,
    )
    assert not _detection_matches_file_scope(
        {"bug_found": True, "file_path": "httpie/__init__.py"},
        candidates,
    )
    assert not _detection_matches_file_scope(
        {"bug_found": False, "file_path": None},
        candidates,
    )


def test_runtime_test_error_counts_as_reproduced_bug(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = CommandResult(
        command=["bugsinpy-test"],
        working_directory=project,
        return_code=0,
        stdout=(
            "collected 1 item\n"
            "tests/test_target.py E\n"
            "============================== ERRORS ==============================\n"
            "ERROR at setup of test_target\n"
            "RuntimeError: application setup defect\n"
            "========================= 1 error in 0.10s =========================\n"
        ),
        stderr="",
        execution_time_seconds=0.1,
    )

    assert classify_bugsinpy_test_result(result) == "failed"
    assert workflow_runner._baseline_failed(result, dataset="bugsinpy") is True

def test_patch_block_preserves_python_triple_quotes() -> None:
    block = 'def helper():\n    """Valid docstring."""\n    return 1\n'

    assert _normalise_patch_block(block) == block


def test_search_apply_preserves_triple_quoted_docstring(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "package" / "target.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def target():\n"
        "    return 1\n",
        encoding="utf-8",
    )

    patch = (
        "--- a/package/target.py\n"
        "+++ b/package/target.py\n"
        "@@ ... @@\n"
        "-def target():\n"
        "-    return 1\n"
        "+def target():\n"
        '+    """Valid docstring."""\n'
        "+    return 2\n"
    )

    assert _apply_llm_patch_by_search(project, patch) is True
    updated = source.read_text(encoding="utf-8")
    assert '"""Valid docstring."""' in updated
    compile(updated, str(source), "exec")
