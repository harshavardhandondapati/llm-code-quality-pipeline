from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_pipeline.schemas import (
    ApprovalDecision,
    BugCase,
    BugDetectionResult,
    CommandResult,
    FixGenerationResult,
    HumanApprovalResult,
    PipelineMetrics,
    PipelineResult,
    ReviewIssue,
    RunStatus,
    Severity,
    SourceContext,
    SourceSnippet,
    ValidationResult,
)


def make_bug_case(tmp_path: Path) -> BugCase:
    return BugCase(
        dataset="BugsInPy",
        project="sample-project",
        bug_id="1",
        language="python",
        workspace_path=tmp_path,
        triggering_tests=["tests/test_sample.py::test_example"],
    )


def test_command_result_success_property(tmp_path: Path) -> None:
    result = CommandResult(
        command=["python", "-V"],
        working_directory=tmp_path,
        return_code=0,
        execution_time_seconds=0.01,
    )
    assert result.succeeded is True


def test_source_snippet_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError):
        SourceSnippet(
            file_path="example.py",
            content="print('hello')",
            start_line=10,
            end_line=5,
        )


def test_review_issue_rejects_end_line_without_start_line() -> None:
    with pytest.raises(ValidationError):
        ReviewIssue(
            file_path="example.py",
            line_end=10,
            severity=Severity.HIGH,
            category="logic",
            description="Incorrect condition",
            recommendation="Correct the comparison",
        )


def test_bug_detection_requires_file_when_bug_is_found() -> None:
    with pytest.raises(ValidationError):
        BugDetectionResult(
            bug_found=True,
            explanation="A defect is present.",
            confidence=0.8,
        )


def test_bug_detection_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        BugDetectionResult(
            bug_found=False,
            explanation="No defect found.",
            confidence=1.2,
        )


def test_human_approval_adds_timestamp() -> None:
    result = HumanApprovalResult(decision=ApprovalDecision.APPROVED)
    assert result.reviewed_at is not None


def test_validation_successful_repair_property() -> None:
    result = ValidationResult(
        patch_applied=True,
        compilation_passed=True,
        triggering_tests_passed=True,
        full_test_suite_passed=True,
    )
    assert result.successful_repair is True


def test_pipeline_result_populates_completion_time(tmp_path: Path) -> None:
    result = PipelineResult(
        status=RunStatus.COMPLETED,
        bug_case=make_bug_case(tmp_path),
        metrics=PipelineMetrics(workflow_repair_success=True),
    )
    assert result.completed_at is not None


def test_complete_schema_chain_can_be_created(tmp_path: Path) -> None:
    bug_case = make_bug_case(tmp_path)
    context = SourceContext(
        project=bug_case.project,
        bug_id=bug_case.bug_id,
        language=bug_case.language,
        failure_output="AssertionError",
        failing_tests=bug_case.triggering_tests,
        snippets=[
            SourceSnippet(
                file_path="sample.py",
                content="def add(a, b):\n    return a - b",
                start_line=1,
                end_line=2,
            )
        ],
    )
    issue = ReviewIssue(
        file_path="sample.py",
        line_start=2,
        line_end=2,
        severity=Severity.HIGH,
        category="logic",
        description="The function subtracts instead of adding.",
        recommendation="Replace subtraction with addition.",
    )
    detection = BugDetectionResult(
        bug_found=True,
        file_path="sample.py",
        function_name="add",
        line_start=2,
        line_end=2,
        explanation="The operator does not match the function intent.",
        confidence=0.99,
    )
    fix = FixGenerationResult(
        patch=(
            "--- a/sample.py\n"
            "+++ b/sample.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b\n"
        ),
        explanation="Use addition in the add function.",
        files_modified=["sample.py"],
    )
    result = PipelineResult(
        bug_case=bug_case,
        source_context=context,
        bug_detection=detection,
        fix_generation=fix,
    )

    assert result.bug_case.dataset == "BugsInPy"
    assert result.fix_generation is not None
    assert issue.severity is Severity.HIGH


def test_bug_version_maps_to_dataset_values() -> None:
    from llm_pipeline.schemas import BugVersion

    assert BugVersion.BUGGY.bugsinpy_value == "0"
    assert BugVersion.FIXED.bugsinpy_value == "1"
