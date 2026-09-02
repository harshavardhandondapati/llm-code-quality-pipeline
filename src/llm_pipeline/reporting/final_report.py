"""Generate human-readable reports from saved pipeline evidence.

Report generation does not rerun checkout, testing, LLM prompting or patch
application. The report is deliberately file-based so it can be inspected
without requiring a web server.
"""

from __future__ import annotations

import html
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class FinalExperimentReport:
    """Consolidated report model for one evaluated bug candidate."""

    dataset: str
    language: str
    project: str
    bug_id: str
    candidate_status: str
    target_python: str | None
    target_runtime: str | None
    overall_status: str
    repair_status: str | None
    baseline_failure_observed: bool
    detection_bug_found: bool | None
    detection_file_path: str | None
    detection_confidence: float | None
    patch_applied: bool | None
    compilation_passed: bool | None
    triggering_tests_passed: bool | None
    human_decision: str | None
    human_allows_progress: bool | None
    retry_count: int | None
    total_known_execution_time_seconds: float | None
    source_context_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    evidence_files: dict[str, str] = field(default_factory=dict)
    pipeline_steps: list[dict[str, str]] = field(default_factory=list)
    generated_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required report input is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_candidate_record(candidate_report_path: str | Path, index: int = 0) -> dict[str, Any]:
    """Load one candidate record from candidate-selection evidence."""

    report = _read_json(Path(candidate_report_path))
    records = report.get("records") or []
    if not records:
        raise ValueError(f"Candidate report has no records: {candidate_report_path}")
    if index < 0 or index >= len(records):
        raise IndexError(f"Candidate index {index} is outside available range 0..{len(records)-1}")
    return dict(records[index])


def _source_context_files(source_context: Mapping[str, Any] | None) -> list[str]:
    if not source_context:
        return []
    files: list[str] = []
    for snippet in source_context.get("snippets", []) or []:
        if isinstance(snippet, Mapping):
            value = snippet.get("relative_path") or snippet.get("file_path") or snippet.get("path")
            if value:
                files.append(str(value))
    return files


def _pipeline_steps(e2e_result: Mapping[str, Any] | None) -> list[dict[str, str]]:
    if not e2e_result:
        return []
    steps = []
    for step in e2e_result.get("steps", []) or []:
        if isinstance(step, Mapping):
            steps.append(
                {
                    "name": str(step.get("name", "unknown")),
                    "status": str(step.get("status", "unknown")),
                    "detail": str(step.get("detail", "")),
                }
            )
    return steps


def _evidence_files(outputs: Path) -> dict[str, str]:
    names = [
        "baseline_reproduction.json",
        "source_context.json",
        "bug_detection_result.json",
        "fix_generation_result.json",
        "validation_result.json",
        "post_fix_evaluation_result.json",
        "human_approval_decision.json",
        "evaluation_metrics.json",
        "workflow_pipeline_result.json",
    ]
    return {name: str(outputs / name) for name in names if (outputs / name).exists()}


def generate_final_experiment_report(
    *,
    candidate_report_path: str | Path,
    candidate_index: int = 0,
) -> FinalExperimentReport:
    """Generate final JSON, Markdown, HTML and TXT reports for one candidate."""

    record = load_candidate_record(candidate_report_path, candidate_index)
    workspace = Path(str(record.get("workspace_path", "")))
    if not workspace.exists():
        raise FileNotFoundError(f"Candidate workspace does not exist: {workspace}")
    outputs = workspace / "outputs"

    metrics = _read_json(outputs / "evaluation_metrics.json")
    source_context = _read_json_optional(outputs / "source_context.json")
    validation = _read_json_optional(outputs / "validation_result.json") or {}
    human_decision = _read_json_optional(outputs / "human_approval_decision.json") or {}
    e2e = _read_json_optional(outputs / "workflow_pipeline_result.json")

    changed_files = validation.get("changed_files") or metrics.get("changed_files") or []
    if not isinstance(changed_files, list):
        changed_files = [str(changed_files)]

    report = FinalExperimentReport(
        dataset=str(record.get("dataset", metrics.get("dataset", "unknown"))),
        language=str(record.get("language", metrics.get("language", "unknown"))),
        project=str(record.get("project", metrics.get("project", "unknown"))),
        bug_id=str(record.get("bug_id", metrics.get("bug_id", "unknown"))),
        candidate_status=str(record.get("status", metrics.get("candidate_status", "unknown"))),
        target_python=record.get("target_python") or metrics.get("target_python"),
        target_runtime=record.get("target_runtime") or metrics.get("target_runtime") or record.get("target_python") or metrics.get("target_python"),
        overall_status=str(metrics.get("overall_status", "unknown")),
        repair_status=metrics.get("repair_status"),
        baseline_failure_observed=bool(record.get("baseline_failure_observed", metrics.get("baseline_failure_observed"))),
        detection_bug_found=metrics.get("detection_bug_found"),
        detection_file_path=metrics.get("detection_file_path"),
        detection_confidence=metrics.get("detection_confidence"),
        patch_applied=metrics.get("patch_applied"),
        compilation_passed=metrics.get("compilation_passed"),
        triggering_tests_passed=metrics.get("triggering_tests_passed"),
        human_decision=metrics.get("human_decision") or human_decision.get("decision"),
        human_allows_progress=metrics.get("human_allows_progress") if "human_allows_progress" in metrics else human_decision.get("allows_progress"),
        retry_count=metrics.get("retry_count"),
        total_known_execution_time_seconds=metrics.get("total_known_execution_time_seconds"),
        source_context_files=_source_context_files(source_context),
        changed_files=[str(item) for item in changed_files],
        evidence_files=_evidence_files(outputs),
        pipeline_steps=_pipeline_steps(e2e),
    )

    payload = asdict(report)
    _write_json(outputs / "final_experiment_report.json", payload)
    (outputs / "final_experiment_report.md").write_text(_render_markdown(report), encoding="utf-8")
    (outputs / "final_experiment_report.txt").write_text(_render_text(report), encoding="utf-8")
    (outputs / "final_experiment_report.html").write_text(_render_html(report), encoding="utf-8")
    return report


def _yes_no(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "Not recorded"


def _render_markdown(report: FinalExperimentReport) -> str:
    lines = [
        f"# Final Experiment Report: {report.project}-{report.bug_id}",
        "",
        "## Summary",
        "",
        f"- Dataset: `{report.dataset}`",
        f"- Language: `{report.language}`",
        f"- Project: `{report.project}`",
        f"- Bug ID: `{report.bug_id}`",
        f"- Candidate status: `{report.candidate_status}`",
        f"- Target runtime: `{report.target_runtime}`",
        f"- Overall status: `{report.overall_status}`",
        f"- Repair status: `{report.repair_status}`",
        "",
        "## Results",
        "",
        f"- Baseline failure observed: {_yes_no(report.baseline_failure_observed)}",
        f"- Bug detected: {_yes_no(report.detection_bug_found)}",
        f"- Detection file: `{report.detection_file_path}`",
        f"- Detection confidence: `{report.detection_confidence}`",
        f"- Patch applied: {_yes_no(report.patch_applied)}",
        f"- Compilation passed: {_yes_no(report.compilation_passed)}",
        f"- Triggering tests passed: {_yes_no(report.triggering_tests_passed)}",
        f"- Human decision: `{report.human_decision}`",
        f"- Human allows progress: {_yes_no(report.human_allows_progress)}",
        "",
        "## Source context files",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report.source_context_files) or lines.append("- None recorded")
    lines.extend(["", "## Changed files", ""])
    lines.extend(f"- `{item}`" for item in report.changed_files) or lines.append("- None recorded")
    lines.extend(["", "## Pipeline steps", ""])
    if report.pipeline_steps:
        for step in report.pipeline_steps:
            detail = f" - {step['detail']}" if step.get("detail") else ""
            lines.append(f"- {step['name']}: `{step['status']}`{detail}")
    else:
        lines.append("- Pipeline manifest not recorded")
    lines.extend(["", "## Evidence files", ""])
    for name, path in report.evidence_files.items():
        lines.append(f"- `{name}`: `{path}`")
    lines.extend([
        "",
        "## Execution metrics",
        "",
        f"- Retry count: `{report.retry_count}`",
        f"- Total known execution time seconds: `{report.total_known_execution_time_seconds}`",
        f"- Generated at UTC: `{report.generated_at_utc}`",
        "",
    ])
    return "\n".join(lines)


def _render_text(report: FinalExperimentReport) -> str:
    return _render_markdown(report).replace("# ", "").replace("## ", "").replace("`", "")


def _render_html(report: FinalExperimentReport) -> str:
    md = _render_markdown(report)
    escaped = html.escape(md)
    return (
        "<!doctype html>\n"
        "<html lang='en'>\n<head>\n<meta charset='utf-8'>\n"
        f"<title>Final Experiment Report {html.escape(report.project)}-{html.escape(report.bug_id)}</title>\n"
        "<style>body{font-family:Arial,sans-serif;max-width:980px;margin:40px auto;line-height:1.5;}"
        "pre{white-space:pre-wrap;background:#f7f7f7;padding:16px;border:1px solid #ddd;}</style>\n"
        "</head>\n<body>\n"
        "<pre>" + escaped + "</pre>\n"
        "</body>\n</html>\n"
    )
