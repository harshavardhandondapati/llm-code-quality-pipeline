"""Human-review actions for completed benchmark jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from llm_pipeline.approval.approval import create_human_approval
from llm_pipeline.evaluation.metrics import create_evaluation_metrics
from llm_pipeline.reporting.final_report import generate_final_experiment_report
from llm_pipeline.ui.job_store import utc_now, write_job
from llm_pipeline.ui.run_history import candidate_report_for_job


REVIEWABLE_STAGES = (
    "baseline_reproduction",
    "source_context",
    "bug_detection",
    "fix_generation",
    "patch_validation",
    "post_fix_evaluation",
)


def is_ready_for_human_review(result: Mapping[str, Any]) -> bool:
    """Return True when technical validation passed and only review remains."""
    statuses = {
        str(step.get("name")): str(step.get("status"))
        for step in result.get("steps", [])
        if isinstance(step, Mapping)
    }
    return all(statuses.get(name) == "passed" for name in REVIEWABLE_STAGES)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(dict(payload), indent=2) + "\n", encoding="utf-8")


def _workflow_text(payload: Mapping[str, Any]) -> str:
    lines = ["End-to-end pipeline result", "===========================", ""]
    for key, value in payload.items():
        if key == "steps":
            lines.append("steps:")
            for step in value or []:
                if isinstance(step, Mapping):
                    lines.append(f"- {step.get('name')}: {step.get('status')}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def _update_steps(
    steps: list[dict[str, Any]],
    *,
    approval_passed: bool,
    metrics_passed: bool,
) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    seen: set[str] = set()

    for step in steps:
        item = dict(step)
        name = str(item.get("name") or "")
        if name == "human_approval":
            item["status"] = "passed" if approval_passed else "blocked"
        elif name == "metrics":
            item["status"] = "passed" if metrics_passed else "failed"
        if name:
            seen.add(name)
        updated.append(item)

    if "human_approval" not in seen:
        updated.append({
            "name": "human_approval",
            "status": "passed" if approval_passed else "blocked",
            "detail": "",
        })
    if "metrics" not in seen:
        updated.append({
            "name": "metrics",
            "status": "passed" if metrics_passed else "failed",
            "detail": "",
        })
    return updated


def finalize_job_review(
    job: Mapping[str, Any],
    *,
    decision: str,
    reviewer: str,
    comments: str = "",
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Record a human decision and refresh the run's final evidence."""
    if str(job.get("status") or "") != "awaiting_review":
        raise ValueError(
            "Only jobs awaiting human review can receive a review decision."
        )

    normalised = decision.strip().lower()
    if normalised not in {"approved", "rejected", "needs_changes"}:
        raise ValueError("decision must be approved, rejected, or needs_changes")
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")

    root = Path(project_root or Path.cwd()).expanduser().resolve()
    report = candidate_report_for_job(job, root)
    if report is None:
        raise FileNotFoundError(
            "Exact per-run evidence is required before recording a review decision."
        )

    payload = json.loads(report.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    if len(records) != 1 or not isinstance(records[0], Mapping):
        raise ValueError("The candidate report must contain exactly one run record.")

    record = dict(records[0])
    workspace = Path(str(record["workspace_path"])).expanduser().resolve()
    outputs = workspace / "outputs"

    approval = create_human_approval(
        candidate_record=record,
        outputs_dir=outputs,
        decision=normalised,
        reviewer=reviewer.strip(),
        comments=comments.strip(),
    )
    metrics = create_evaluation_metrics(candidate_record=record, outputs_dir=outputs)

    workflow_path = outputs / "workflow_pipeline_result.json"
    workflow = _read_json(workflow_path)
    previous_steps = [
        dict(step) for step in workflow.get("steps", []) if isinstance(step, Mapping)
    ]
    successful = metrics.get("overall_status") == "successful"
    workflow["overall_status"] = "successful" if successful else "failed"
    workflow["successful"] = successful
    workflow["steps"] = _update_steps(
        previous_steps,
        approval_passed=bool(approval.get("allows_progress")),
        metrics_passed=successful,
    )
    workflow["human_reviewed_at_utc"] = approval.get("decided_at_utc")

    _write_json(workflow_path, workflow)
    (outputs / "workflow_pipeline_result.txt").write_text(
        _workflow_text(workflow), encoding="utf-8"
    )
    _write_json(outputs / "pipeline_run_manifest.json", workflow)
    generate_final_experiment_report(candidate_report_path=report)

    updated_job = dict(job)
    updated_result = dict(updated_job.get("result") or {})
    updated_result.update(workflow)
    updated_job["result"] = updated_result
    updated_job["successful"] = successful
    updated_job["human_review"] = approval
    updated_job["updated_at_utc"] = utc_now()

    if normalised == "approved":
        updated_job["status"] = "successful" if successful else "failed"
        updated_job["message"] = (
            "Human review approved the run and all validation checks passed."
            if successful
            else "Human review was approved, but one or more required checks are incomplete."
        )
    elif normalised == "rejected":
        updated_job["status"] = "rejected"
        updated_job["message"] = "Human review rejected this run."
    else:
        updated_job["status"] = "needs_changes"
        updated_job["message"] = "Human review requested changes before this run can be accepted."

    return write_job(updated_job, root)
