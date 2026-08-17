"""Shared typed schemas for all pipeline components."""

from __future__ import annotations

from datetime import datetime, timezone
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and validates assignment."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


class ModelProvider(StrEnum):
    """Supported model-provider categories."""

    MOCK = "mock"
    OPENROUTER = "openrouter"
    PROPRIETARY = "proprietary"
    OPEN_MODEL = "open_model"




class BugVersion(StrEnum):
    """Version of a benchmark bug selected for checkout."""

    BUGGY = "buggy"
    FIXED = "fixed"

    @property
    def bugsinpy_value(self) -> str:
        """Return the value expected by the BugsInPy checkout command."""
        return "0" if self is BugVersion.BUGGY else "1"

    def defects4j_value(self, bug_id: str | int) -> str:
        """Return the value expected by the Defects4J checkout command."""
        suffix = "b" if self is BugVersion.BUGGY else "f"
        return f"{bug_id}{suffix}"


class PipelineStage(StrEnum):
    """Ordered logical stages in the proposed pipeline."""

    DATASET_CHECKOUT = "dataset_checkout"
    BASELINE_TEST = "baseline_test"
    CONTEXT_BUILD = "context_build"
    CODE_REVIEW = "code_review"
    BUG_DETECTION = "bug_detection"
    FIX_GENERATION = "fix_generation"
    HUMAN_APPROVAL = "human_approval"
    PATCH_APPLICATION = "patch_application"
    VALIDATION = "validation"
    METRICS = "metrics"
    RESULT_RECORDING = "result_recording"


class Severity(StrEnum):
    """Severity assigned to a review issue."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalDecision(StrEnum):
    """Human decision for a generated patch."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"


class RunStatus(StrEnum):
    """Overall status of a pipeline execution."""

    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class CommandResult(StrictModel):
    """Result from a command executed in a controlled workspace."""

    command: list[str] = Field(min_length=1)
    working_directory: Path
    return_code: int
    stdout: str = ""
    stderr: str = ""
    execution_time_seconds: float = Field(ge=0)
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        """Return True only when the command completed successfully."""
        return self.return_code == 0 and not self.timed_out


class BugCase(StrictModel):
    """A reproducible benchmark bug selected for a pipeline run."""

    dataset: str = Field(min_length=1)
    project: str = Field(min_length=1)
    bug_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    workspace_path: Path
    buggy_revision: str | None = None
    fixed_revision: str | None = None
    triggering_tests: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetCheckoutResult(StrictModel):
    """Checked-out benchmark bug together with its command evidence."""

    bug_case: BugCase
    command_result: CommandResult
    log_file: Path

    @property
    def succeeded(self) -> bool:
        """Return True when the checkout command completed successfully."""
        return self.command_result.succeeded


class BaselineReproductionResult(StrictModel):
    """Result of preparing a buggy project and running its relevant tests."""

    checkout: DatasetCheckoutResult
    compile_result: CommandResult
    test_result: CommandResult | None = None
    summary_file: Path

    @property
    def setup_succeeded(self) -> bool:
        """Return True when checkout and compile both completed successfully."""
        return self.checkout.succeeded and self.compile_result.succeeded

    @property
    def baseline_failure_observed(self) -> bool:
        """Return True when the buggy-version test shows a failure."""
        if not self.setup_succeeded or self.test_result is None or self.test_result.timed_out:
            return False
        output = f"{self.test_result.stdout}\n{self.test_result.stderr}".lower()
        return (not self.test_result.succeeded) or " failed" in output or "= failed" in output


class SourceSnippet(StrictModel):
    """A bounded source-code excerpt provided to an LLM."""

    file_path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "SourceSnippet":
        if self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class SourceContext(StrictModel):
    """Context assembled from source code, tests, and benchmark metadata."""

    project: str = Field(min_length=1)
    bug_id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    failure_output: str
    failing_tests: list[str] = Field(default_factory=list)
    snippets: list[SourceSnippet] = Field(min_length=1)
    additional_context: dict[str, Any] = Field(default_factory=dict)


class SourceContextBuildResult(StrictModel):
    """Saved source context and the files created for later stages."""

    context: SourceContext
    json_file: Path
    text_file: Path


class ReviewIssue(StrictModel):
    """One issue identified during LLM-assisted code review."""

    file_path: str = Field(min_length=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    severity: Severity
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_optional_line_range(self) -> "ReviewIssue":
        if self.line_start is None and self.line_end is not None:
            raise ValueError("line_start is required when line_end is provided")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class TokenUsage(StrictModel):
    """Token usage reported by an LLM provider."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelCallMetadata(StrictModel):
    """Reproducibility and performance metadata for one model call."""

    provider: ModelProvider
    model_name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    execution_time_seconds: float = Field(ge=0)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    raw_response_path: Path | None = None


class CodeReviewResult(StrictModel):
    """Structured result from the code-review stage."""

    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str
    model_call: ModelCallMetadata | None = None


class BugDetectionResult(StrictModel):
    """Structured result from the bug-detection stage."""

    bug_found: bool
    file_path: str | None = None
    function_name: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    explanation: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    model_call: ModelCallMetadata | None = None

    @model_validator(mode="after")
    def validate_detection(self) -> "BugDetectionResult":
        if self.line_start is None and self.line_end is not None:
            raise ValueError("line_start is required when line_end is provided")
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_end < self.line_start
        ):
            raise ValueError("line_end must be greater than or equal to line_start")
        if self.bug_found and not self.file_path:
            raise ValueError("file_path is required when bug_found is true")
        return self


class FixGenerationResult(StrictModel):
    """Structured result from the fix-generation stage."""

    patch: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    files_modified: list[str] = Field(min_length=1)
    model_call: ModelCallMetadata | None = None


class HumanApprovalResult(StrictModel):
    """Human review outcome for a generated patch."""

    decision: ApprovalDecision
    reviewer_comment: str | None = None
    review_time_seconds: float = Field(default=0, ge=0)
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def populate_review_timestamp(self) -> "HumanApprovalResult":
        if self.decision in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.REJECTED,
        } and self.reviewed_at is None:
            self.reviewed_at = utc_now()
        return self


class ValidationResult(StrictModel):
    """Outcome of applying and testing a generated patch."""

    patch_applied: bool = False
    compilation_passed: bool = False
    triggering_tests_passed: bool = False
    full_test_suite_passed: bool = False
    changed_files: list[str] = Field(default_factory=list)
    compile_result: CommandResult | None = None
    triggering_test_result: CommandResult | None = None
    full_test_result: CommandResult | None = None
    failure_reason: str | None = None

    @property
    def successful_repair(self) -> bool:
        """Return True only when all required validation checks pass."""
        return (
            self.patch_applied
            and self.compilation_passed
            and self.triggering_tests_passed
            and self.full_test_suite_passed
        )


class StageError(StrictModel):
    """Controlled error captured without losing the rest of the run record."""

    stage: PipelineStage
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=utc_now)


class PipelineMetrics(StrictModel):
    """Task-specific and end-to-end metrics for one execution."""

    detected_correct_file: bool | None = None
    detected_correct_function: bool | None = None
    line_range_overlap: float | None = Field(default=None, ge=0, le=1)
    patch_application_success: bool = False
    compilation_success: bool = False
    triggering_test_success: bool = False
    full_test_suite_success: bool = False
    workflow_repair_success: bool = False
    human_approved: bool | None = None
    total_execution_time_seconds: float = Field(default=0, ge=0)
    estimated_api_cost: float = Field(default=0, ge=0)
    cost_currency: str = Field(default="GBP", min_length=3, max_length=3)


class PipelineResult(StrictModel):
    """Complete auditable record of a single pipeline run."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    status: RunStatus = RunStatus.CREATED
    bug_case: BugCase
    baseline_test: CommandResult | None = None
    source_context: SourceContext | None = None
    code_review: CodeReviewResult | None = None
    bug_detection: BugDetectionResult | None = None
    fix_generation: FixGenerationResult | None = None
    human_approval: HumanApprovalResult | None = None
    validation: ValidationResult | None = None
    metrics: PipelineMetrics | None = None
    errors: list[StageError] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_completion_timestamp(self) -> "PipelineResult":
        if self.status in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.REJECTED,
        } and self.completed_at is None:
            self.completed_at = utc_now()
        return self
