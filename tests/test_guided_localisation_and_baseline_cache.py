"""Regression tests for file-level guidance and BugsInPy baseline reuse."""

from __future__ import annotations

from pathlib import Path

from llm_pipeline.prompts.builder import build_bug_detection_prompt
from llm_pipeline.schemas import BugCase, CommandResult, DatasetCheckoutResult
from llm_pipeline.workflow.runner import (
    _add_file_localisation_context,
    _file_localisation_candidates,
    _prepare_or_reuse_bugsinpy_baseline,
)


class FakeBugsInPyAdapter:
    def __init__(self) -> None:
        self.checkout_calls = 0
        self.compile_calls = 0
        self.test_calls = 0

    def checkout_bug(self, project: str, bug_id: str, workspace):
        self.checkout_calls += 1
        project_path = workspace.repository / project
        target = project_path / "package" / "target.py"
        target.parent.mkdir(parents=True)
        target.write_text("def target(value):\n    return value\n", encoding="utf-8")

        log_file = workspace.logs / "bugsinpy_checkout.json"
        log_file.write_text("{}", encoding="utf-8")
        bug_case = BugCase(
            dataset="BugsInPy",
            project=project,
            bug_id=bug_id,
            language="python",
            workspace_path=project_path,
            buggy_revision="buggy",
            fixed_revision="fixed",
            triggering_tests=["tests/test_target.py::test_target"],
            metadata={
                "changed_files": ["package/target.py"],
                "checkout_log": str(log_file),
            },
        )
        return DatasetCheckoutResult(
            bug_case=bug_case,
            command_result=CommandResult(
                command=["bugsinpy-checkout"],
                working_directory=workspace.root,
                return_code=0,
                execution_time_seconds=0.01,
            ),
            log_file=log_file,
        )

    def compile_project(self, checkout):
        self.compile_calls += 1
        return CommandResult(
            command=["bugsinpy-compile"],
            working_directory=checkout.bug_case.workspace_path,
            return_code=0,
            execution_time_seconds=0.01,
        )

    def run_triggering_tests(self, checkout):
        self.test_calls += 1
        return CommandResult(
            command=["bugsinpy-test"],
            working_directory=checkout.bug_case.workspace_path,
            return_code=1,
            stdout=(
                "============================= FAILURES =============================\n"
                "AssertionError: expected benchmark failure\n"
                "=========================== 1 failed in 0.01s ===========================\n"
            ),
            execution_time_seconds=0.01,
        )


def test_prepared_bugsinpy_baseline_is_reused(tmp_path: Path) -> None:
    adapter = FakeBugsInPyAdapter()

    first, first_reused, first_root = _prepare_or_reuse_bugsinpy_baseline(
        adapter=adapter,
        project="sample",
        bug_id="1",
        workspace_root=tmp_path / "workspaces",
    )
    second, second_reused, second_root = _prepare_or_reuse_bugsinpy_baseline(
        adapter=adapter,
        project="sample",
        bug_id="1",
        workspace_root=tmp_path / "workspaces",
    )

    assert first_reused is False
    assert second_reused is True
    assert first_root == second_root
    assert adapter.checkout_calls == 1
    assert adapter.compile_calls == 1
    assert adapter.test_calls == 2
    assert first.checkout.bug_case.workspace_path == second.checkout.bug_case.workspace_path
    assert first.checkout.bug_case.metadata["pipeline_baseline_test_classification"] == "failed"
    assert second.checkout.bug_case.metadata["pipeline_baseline_test_classification"] == "failed"


def _checkout(tmp_path: Path, changed_files: list[str]) -> DatasetCheckoutResult:
    project = tmp_path / "project"
    target = project / "src" / "main" / "Example.java"
    target.parent.mkdir(parents=True)
    target.write_text(
        "public class Example {\n"
        "    boolean value = true;\n"
        "}\n",
        encoding="utf-8",
    )
    test_file = project / "src" / "test" / "ExampleTest.java"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("class ExampleTest {}\n", encoding="utf-8")

    bug_case = BugCase(
        dataset="Defects4J",
        project="Example",
        bug_id="7",
        language="java",
        workspace_path=project,
        triggering_tests=["ExampleTest::testCase"],
        metadata={"changed_files": changed_files},
    )
    return DatasetCheckoutResult(
        bug_case=bug_case,
        command_result=CommandResult(
            command=["defects4j", "checkout"],
            working_directory=tmp_path,
            return_code=0,
            execution_time_seconds=0.01,
        ),
        log_file=tmp_path / "checkout.json",
    )


def test_file_localisation_prefers_application_source_over_changed_test(tmp_path: Path) -> None:
    checkout = _checkout(
        tmp_path,
        ["src/test/ExampleTest.java", "src/main/Example.java"],
    )

    assert _file_localisation_candidates(checkout) == ["src/main/Example.java"]

    context = {"additional_context": {}}
    candidates = _add_file_localisation_context(context, checkout)

    assert candidates == ["src/main/Example.java"]
    additional = context["additional_context"]
    assert additional["file_localisation_level"] == "file"
    assert additional["file_localisation_ground_truth_scope"] == "file_paths_only"
    assert "public class Example" in additional["file_localisation_source"]["src/main/Example.java"]
    assert "function_name" not in additional
    assert "line_start" not in additional


def test_real_prompt_contains_file_scope_and_failure_signal_without_fix_answer() -> None:
    context = {
        "project": "sample",
        "bug_id": "3",
        "language": "python",
        "failure_output": (
            "/tmp/env/site-packages/_pytest/runner.py\n"
            "AttributeError: <module 'package.target'> does not have the attribute 'normalise'\n"
        ),
        "failing_tests": ["tests/test_target.py::test_case"],
        "snippets": [
            {
                "file_path": "tests/test_target.py",
                "start_line": 1,
                "end_line": 2,
                "content": "def test_case():\n    pass\n",
            }
        ],
        "additional_context": {
            "selected_files": ["tests/test_target.py"],
            "benchmark_hints_used": False,
            "benchmark_changed_files": [],
            "file_localisation_level": "file",
            "file_localisation_guidance": ["package/target.py"],
            "file_localisation_source": {
                "package/target.py": "def normalise(value):\n    return value\n"
            },
        },
    }

    prompt = build_bug_detection_prompt(context, real_llm=True)
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "File-level repair scope" in text
    assert "package/target.py" in text
    assert "def normalise(value)" in text
    assert "AttributeError" in text
    assert "Observed Python module reference: package.target" in text
    assert "No method name, faulty line, expected code change" in text
    assert "official patch" in text
    assert "Known benchmark focus" not in text
    assert "The repair must make" not in text


def test_old_metadata_alone_still_does_not_leak_file_path_to_prompt() -> None:
    context = {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "AssertionError",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "module.py",
                "start_line": 1,
                "end_line": 1,
                "content": "value = 1\n",
            }
        ],
        "additional_context": {
            "selected_files": ["module.py"],
            "benchmark_hints_used": False,
            "benchmark_changed_files": ["httpie/downloads.py"],
        },
    }

    prompt = build_bug_detection_prompt(context, real_llm=True)
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "httpie/downloads.py" not in text
    assert "Known benchmark focus" not in text


class FakeGitBugsInPyAdapter:
    """Small git-backed checkout that mimics BugsInPy's fixed-test copy."""

    def __init__(self) -> None:
        self.checkout_calls = 0

    @staticmethod
    def _git(project: Path, *args: str) -> None:
        import subprocess

        completed = subprocess.run(
            ["git", *args],
            cwd=project,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    def checkout_bug(self, project: str, bug_id: str, workspace):
        self.checkout_calls += 1
        project_path = workspace.repository / project
        source = project_path / "package" / "target.py"
        benchmark_test = project_path / "tests" / "test_target.py"
        source.parent.mkdir(parents=True)
        benchmark_test.parent.mkdir(parents=True)
        source.write_text("buggy = True\n", encoding="utf-8")
        benchmark_test.write_text("old_test = True\n", encoding="utf-8")

        self._git(project_path, "init")
        self._git(project_path, "config", "user.email", "test@example.com")
        self._git(project_path, "config", "user.name", "Test User")
        self._git(project_path, "add", "package/target.py", "tests/test_target.py")
        self._git(project_path, "commit", "-m", "buggy baseline")

        # This mirrors bugsinpy-checkout: the buggy source stays at HEAD while
        # the triggering test is copied from the fixed revision into the tree.
        benchmark_test.write_text("fixed_revision_test = True\n", encoding="utf-8")

        log_file = workspace.logs / "bugsinpy_checkout.json"
        log_file.write_text("{}", encoding="utf-8")
        bug_case = BugCase(
            dataset="BugsInPy",
            project=project,
            bug_id=bug_id,
            language="python",
            workspace_path=project_path,
            buggy_revision="HEAD",
            fixed_revision="HEAD",
            triggering_tests=["tests/test_target.py"],
            metadata={
                "changed_files": ["package/target.py"],
                "test_file": "tests/test_target.py",
                "checkout_log": str(log_file),
            },
        )
        return DatasetCheckoutResult(
            bug_case=bug_case,
            command_result=CommandResult(
                command=["bugsinpy-checkout"],
                working_directory=workspace.root,
                return_code=0,
                execution_time_seconds=0.01,
            ),
            log_file=log_file,
        )

    def compile_project(self, checkout):
        return CommandResult(
            command=["bugsinpy-compile"],
            working_directory=checkout.bug_case.workspace_path,
            return_code=0,
            execution_time_seconds=0.01,
        )

    def run_triggering_tests(self, checkout):
        return CommandResult(
            command=["bugsinpy-test"],
            working_directory=checkout.bug_case.workspace_path,
            return_code=0,
            stdout=(
                "============================= FAILURES =============================\n"
                "AssertionError: benchmark defect reproduced\n"
                "=========================== 1 failed in 0.01s ===========================\n"
            ),
            execution_time_seconds=0.01,
        )


def test_cached_bugsinpy_reuse_resets_source_without_losing_fixed_revision_test(
    tmp_path: Path,
) -> None:
    adapter = FakeGitBugsInPyAdapter()
    first, first_reused, _ = _prepare_or_reuse_bugsinpy_baseline(
        adapter=adapter,
        project="sample",
        bug_id="1",
        workspace_root=tmp_path / "workspaces",
    )
    project = first.checkout.bug_case.workspace_path
    source = project / "package" / "target.py"
    benchmark_test = project / "tests" / "test_target.py"

    assert first_reused is False
    assert benchmark_test.read_text(encoding="utf-8") == "fixed_revision_test = True\n"

    # Simulate a model repair left in the shared prepared checkout.
    source.write_text("buggy = False\n", encoding="utf-8")

    second, second_reused, _ = _prepare_or_reuse_bugsinpy_baseline(
        adapter=adapter,
        project="sample",
        bug_id="1",
        workspace_root=tmp_path / "workspaces",
    )

    assert second_reused is True
    assert adapter.checkout_calls == 1
    assert source.read_text(encoding="utf-8") == "buggy = True\n"
    assert benchmark_test.read_text(encoding="utf-8") == "fixed_revision_test = True\n"
    assert second.checkout.bug_case.metadata["pipeline_baseline_test_classification"] == "failed"
