"""Run-selection helpers for runtime and submitted evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


DATASET_LABELS = {
    "bugsinpy": "BugsInPy",
    "defects4j": "Defects4J",
}


def _project_path(
    value: str | Path,
    project_root: Path | str | None = None,
) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        root = Path(project_root or Path.cwd()).expanduser().resolve()
        path = root / path
    return path.resolve(strict=False)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _report_workspace(
    report_path: Path,
    project_root: Path | str | None = None,
) -> Path | None:
    payload = _read_json(report_path)
    records = payload.get("records") or []
    if len(records) != 1 or not isinstance(records[0], Mapping):
        return None

    workspace = records[0].get("workspace_path")
    if not workspace:
        return None
    return _project_path(str(workspace), project_root)


def _job_workspace(
    job: Mapping[str, Any],
    project_root: Path | str | None = None,
) -> Path | None:
    result = job.get("result") or {}
    value = job.get("workspace_path") or result.get("workspace_path")
    if not value:
        return None
    return _project_path(str(value), project_root)


def candidate_report_for_job(
    job: Mapping[str, Any],
    project_root: Path | str | None = None,
) -> Path | None:
    """Return a report only when it belongs to the selected workspace."""
    workspace = _job_workspace(job, project_root)
    if workspace is None:
        return None

    result = job.get("result") or {}
    candidates = [
        workspace / "outputs" / "candidate_selection.json",
        job.get("candidate_report"),
        result.get("candidate_report"),
    ]

    seen: set[Path] = set()
    for value in candidates:
        if not value:
            continue

        path = _project_path(str(value), project_root)
        if path in seen or not path.is_file():
            continue
        seen.add(path)

        if _report_workspace(path, project_root) == workspace:
            return path

    return None


def _dataset_key(value: Any) -> str:
    return str(value or "").strip().lower()


def submitted_evidence_jobs(
    project_root: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return repository evidence that can be reviewed on a fresh deployment."""
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    results_dir = root / "results"
    evidence_root = (root / "evidence").resolve(strict=False)
    if not results_dir.is_dir() or not evidence_root.is_dir():
        return []

    jobs: list[dict[str, Any]] = []
    for report in sorted(results_dir.glob("*_candidate_selection.json")):
        payload = _read_json(report)
        records = payload.get("records") or []
        if len(records) != 1 or not isinstance(records[0], Mapping):
            continue

        record = dict(records[0])
        workspace_value = record.get("workspace_path")
        if not workspace_value:
            continue

        workspace = _project_path(str(workspace_value), root)
        if workspace != evidence_root and evidence_root not in workspace.parents:
            continue

        outputs = workspace / "outputs"
        if not outputs.is_dir():
            continue

        metrics = _read_json(outputs / "evaluation_metrics.json")
        workflow = _read_json(outputs / "workflow_pipeline_result.json")
        status = str(
            workflow.get("overall_status")
            or metrics.get("overall_status")
            or "available"
        )

        jobs.append(
            {
                "job_id": f"submitted::{report.stem}",
                "source": "submitted",
                "status": status,
                "successful": status.lower() == "successful",
                "dataset": _dataset_key(record.get("dataset")),
                "project": record.get("project"),
                "bug_id": str(record.get("bug_id") or ""),
                "provider": workflow.get("provider") or metrics.get("provider"),
                "model_name": workflow.get("model_name") or metrics.get("model_name"),
                "workspace_path": str(workspace),
                "candidate_report": str(report.resolve()),
                "created_at_utc": workflow.get("created_at_utc"),
                "message": "Submitted repository evidence.",
            }
        )

    return jobs


def _timestamp(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return parsed.strftime("%Y-%m-%d %H:%M UTC")


def format_job_label(job: Mapping[str, Any]) -> str:
    """Build a readable label and keep runtime runs distinguishable."""
    dataset_key = _dataset_key(job.get("dataset"))
    dataset = DATASET_LABELS.get(dataset_key, str(job.get("dataset") or "Unknown"))
    project = str(job.get("project") or "unknown")
    bug_id = str(job.get("bug_id") or "?")
    provider = str(job.get("provider") or "unknown")
    model = str(job.get("model_name") or "unknown")
    status = str(job.get("status") or "unknown")

    parts = [dataset, f"{project}-{bug_id}", provider, model, status]
    if str(job.get("source") or "") == "submitted":
        return " · ".join(["Submitted evidence", *parts])

    created = _timestamp(job.get("created_at_utc"))
    if created:
        parts.append(created)
    parts.append(str(job.get("job_id") or "unknown-job"))
    return " · ".join(parts)
