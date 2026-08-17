import json
from pathlib import Path

import pytest

from llm_pipeline.context.source_context import SourceContextBuilder
from llm_pipeline.exceptions import ContextBuildError
from llm_pipeline.schemas import (
    BaselineReproductionResult,
    BugCase,
    CommandResult,
    DatasetCheckoutResult,
)


def make_bug_case(project: Path, *, changed_files: list[str] | None = None) -> BugCase:
    return BugCase(
        dataset="BugsInPy",
        project=project.name,
        bug_id="1",
        language="python",
        workspace_path=project,
        triggering_tests=["tests/test_calculator.py::test_divide"],
        metadata={"changed_files": changed_files or []},
    )


def make_test_result(project: Path, output: str) -> CommandResult:
    return CommandResult(
        command=["bugsinpy-test"],
        working_directory=project,
        return_code=1,
        stdout=output,
        execution_time_seconds=0.1,
    )


def create_small_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "calculator"
    source = project / "src" / "calculator.py"
    test_file = project / "tests" / "test_calculator.py"
    source.parent.mkdir(parents=True)
    test_file.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                "def add(a, b):",
                "    return a + b",
                "",
                "def divide(a, b):",
                "    return a / b",
                "",
            ]
        ),
        encoding="utf-8",
    )
    test_file.write_text(
        "from src.calculator import divide\n\n"
        "def test_divide():\n"
        "    assert divide(4, 0) == 0\n",
        encoding="utf-8",
    )
    return project, source, test_file


def test_extract_failure_locations_reads_traceback_and_pytest_locations() -> None:
    output = (
        '  File "src/calculator.py", line 5, in divide\n'
        "tests/test_calculator.py:4: AssertionError\n"
    )

    locations = SourceContextBuilder._extract_failure_locations(output)

    assert ("src/calculator.py", 5) in locations
    assert ("tests/test_calculator.py", 4) in locations


def test_build_selects_traceback_file_and_triggering_test(tmp_path: Path) -> None:
    project, source, test_file = create_small_project(tmp_path)
    output = (
        'Traceback:\n  File "src/calculator.py", line 5, in divide\n'
        "ZeroDivisionError: division by zero\n"
    )
    builder = SourceContextBuilder(max_files=3)

    context = builder.build(make_bug_case(project), make_test_result(project, output))

    selected = [snippet.file_path for snippet in context.snippets]
    assert source.relative_to(project).as_posix() in selected
    assert test_file.relative_to(project).as_posix() in selected
    assert context.failure_output == output.strip()


def test_build_centres_snippet_around_reported_line(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = project / "module.py"
    project.mkdir()
    source.write_text(
        "\n".join(f"line_{number} = {number}" for number in range(1, 101)),
        encoding="utf-8",
    )
    bug_case = BugCase(
        dataset="BugsInPy",
        project="project",
        bug_id="1",
        language="python",
        workspace_path=project,
    )
    result = make_test_result(
        project,
        'File "module.py", line 50, in broken_function\nAssertionError',
    )
    builder = SourceContextBuilder(
        max_files=1,
        context_lines_before=2,
        context_lines_after=3,
    )

    context = builder.build(bug_case, result)
    snippet = context.snippets[0]

    assert snippet.start_line == 48
    assert snippet.end_line == 53
    assert "line_50 = 50" in snippet.content
    assert "line_47 = 47" not in snippet.content


def test_build_does_not_use_changed_file_ground_truth_by_default(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    hidden = project / "hidden_fix.py"
    hidden.write_text("answer = 42\n", encoding="utf-8")
    bug_case = make_bug_case(project, changed_files=["hidden_fix.py"])
    builder = SourceContextBuilder(max_files=2, use_benchmark_hints=False)

    context = builder.build(bug_case, make_test_result(project, "AssertionError"))

    reasons = context.additional_context["selection_reasons"]
    hidden_reasons = reasons.get("hidden_fix.py", [])
    assert "listed in benchmark changed-file metadata" not in hidden_reasons
    assert context.additional_context["benchmark_hints_used"] is False


def test_build_can_use_benchmark_hints_when_explicitly_enabled(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    hidden = project / "hidden_fix.py"
    hidden.write_text("answer = 42\n", encoding="utf-8")
    bug_case = make_bug_case(project, changed_files=["hidden_fix.py"])
    builder = SourceContextBuilder(max_files=4, use_benchmark_hints=True)

    context = builder.build(bug_case, make_test_result(project, "AssertionError"))

    reasons = context.additional_context["selection_reasons"]["hidden_fix.py"]
    assert "listed in benchmark changed-file metadata" in reasons
    assert context.additional_context["benchmark_hints_used"] is True


def test_build_uses_discovery_when_failure_output_has_no_file(tmp_path: Path) -> None:
    project, source, _test_file = create_small_project(tmp_path)
    builder = SourceContextBuilder(max_files=2)

    context = builder.build(
        make_bug_case(project),
        make_test_result(project, "AssertionError: values differ"),
    )

    assert source.relative_to(project).as_posix() in [
        snippet.file_path for snippet in context.snippets
    ]


def test_build_respects_maximum_file_count(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for number in range(6):
        (project / f"module_{number}.py").write_text(
            f"value = {number}\n",
            encoding="utf-8",
        )
    bug_case = BugCase(
        dataset="BugsInPy",
        project="project",
        bug_id="1",
        language="python",
        workspace_path=project,
    )

    context = SourceContextBuilder(max_files=3).build(
        bug_case,
        make_test_result(project, "AssertionError"),
    )

    assert len(context.snippets) == 3


def test_build_respects_total_source_character_limit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for number in range(3):
        (project / f"module_{number}.py").write_text(
            (f"value_{number} = 'abcdefghij'\n" * 200),
            encoding="utf-8",
        )
    bug_case = BugCase(
        dataset="BugsInPy",
        project="project",
        bug_id="1",
        language="python",
        workspace_path=project,
    )

    context = SourceContextBuilder(
        max_files=3,
        max_source_characters=1_000,
    ).build(bug_case, make_test_result(project, "AssertionError"))

    total = sum(len(snippet.content) for snippet in context.snippets)
    assert total <= 1_000
    assert context.additional_context["source_character_limit"] == 1_000


def test_build_truncates_long_failure_output_and_keeps_the_end(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    long_output = "old output\n" * 100 + "FINAL ERROR MESSAGE"
    builder = SourceContextBuilder(max_failure_output_characters=500)

    context = builder.build(make_bug_case(project), make_test_result(project, long_output))

    assert context.failure_output.startswith("[Earlier test output was omitted.]")
    assert context.failure_output.endswith("FINAL ERROR MESSAGE")
    assert context.additional_context["failure_output_truncated"] is True


def test_build_raises_when_project_has_no_python_files(tmp_path: Path) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    (project / "README.md").write_text("No source here", encoding="utf-8")
    bug_case = BugCase(
        dataset="BugsInPy",
        project="empty",
        bug_id="1",
        language="python",
        workspace_path=project,
    )

    with pytest.raises(ContextBuildError, match="No readable Python source files"):
        SourceContextBuilder().build(
            bug_case,
            make_test_result(project, "AssertionError"),
        )


def test_save_writes_json_and_readable_text(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    builder = SourceContextBuilder(max_files=2)
    context = builder.build(
        make_bug_case(project),
        make_test_result(project, "AssertionError"),
    )

    saved = builder.save(context, tmp_path / "outputs")

    assert saved.json_file.is_file()
    assert saved.text_file.is_file()
    data = json.loads(saved.json_file.read_text(encoding="utf-8"))
    assert data["project"] == "calculator"
    readable = saved.text_file.read_text(encoding="utf-8")
    assert "Project: calculator" in readable
    assert "Source snippets:" in readable


def test_build_from_baseline_uses_batch3_result(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    bug_case = make_bug_case(project)
    checkout_command = CommandResult(
        command=["bugsinpy-checkout"],
        working_directory=tmp_path,
        return_code=0,
        execution_time_seconds=0.1,
    )
    checkout = DatasetCheckoutResult(
        bug_case=bug_case,
        command_result=checkout_command,
        log_file=tmp_path / "checkout.json",
    )
    baseline = BaselineReproductionResult(
        checkout=checkout,
        compile_result=CommandResult(
            command=["bugsinpy-compile"],
            working_directory=project,
            return_code=0,
            execution_time_seconds=0.1,
        ),
        test_result=make_test_result(
            project,
            'File "src/calculator.py", line 5\nZeroDivisionError',
        ),
        summary_file=tmp_path / "baseline.json",
    )

    saved = SourceContextBuilder(max_files=2).build_from_baseline(
        baseline,
        tmp_path / "outputs",
    )

    assert saved.context.project == "calculator"
    assert saved.json_file.name == "source_context.json"


def test_build_from_baseline_rejects_missing_test_result(tmp_path: Path) -> None:
    project, _source, _test_file = create_small_project(tmp_path)
    bug_case = make_bug_case(project)
    checkout = DatasetCheckoutResult(
        bug_case=bug_case,
        command_result=CommandResult(
            command=["bugsinpy-checkout"],
            working_directory=tmp_path,
            return_code=0,
            execution_time_seconds=0.1,
        ),
        log_file=tmp_path / "checkout.json",
    )
    baseline = BaselineReproductionResult(
        checkout=checkout,
        compile_result=CommandResult(
            command=["bugsinpy-compile"],
            working_directory=project,
            return_code=1,
            execution_time_seconds=0.1,
        ),
        test_result=None,
        summary_file=tmp_path / "baseline.json",
    )

    with pytest.raises(ContextBuildError, match="baseline test was not run"):
        SourceContextBuilder().build_from_baseline(
            baseline,
            tmp_path / "outputs",
        )
