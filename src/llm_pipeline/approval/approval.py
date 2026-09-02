"""Record a simple human review decision."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def create_human_approval(
    *,
    candidate_record: Mapping[str, Any],
    outputs_dir: Path | str,
    decision: str = "pending",
    reviewer: str = "",
    comments: str = "",
) -> dict[str, Any]:
    """Save human review request and decision files."""
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    detection = _safe_json(outputs / "bug_detection_result.json")
    fix = _safe_json(outputs / "fix_generation_result.json")
    validation = _safe_json(outputs / "validation_result.json")

    review = {
        "project": candidate_record.get("project"),
        "bug_id": candidate_record.get("bug_id"),
        "bug_found": detection.get("bug_found"),
        "bug_file_path": detection.get("file_path"),
        "bug_confidence": detection.get("confidence"),
        "files_modified": fix.get("files_modified", []),
        "patch_preview": str(fix.get("patch", ""))[:4000],
        "validation_summary": validation,
        "required_checks": [
            "Confirm the detected bug matches the failing test output.",
            "Check the generated patch changes only intended files.",
            "Confirm post-fix tests pass before approving the result.",
        ],
    }
    (outputs / "approval_request.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
    (outputs / "approval_request.txt").write_text(_as_text(review), encoding="utf-8")

    normalised = decision.strip().lower()
    if normalised not in {"pending", "approved", "rejected", "needs_changes"}:
        raise ValueError("decision must be pending, approved, rejected, or needs_changes")
    if normalised != "pending" and not reviewer.strip():
        raise ValueError("reviewer is required for a completed review decision")

    approval = {
        "project": candidate_record.get("project"),
        "bug_id": candidate_record.get("bug_id"),
        "decision": normalised,
        "reviewer": reviewer.strip(),
        "comments": comments.strip(),
        "allows_progress": normalised == "approved",
        "decided_at_utc": (
            None
            if normalised == "pending"
            else datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        ),
    }
    (outputs / "human_approval_decision.json").write_text(json.dumps(approval, indent=2) + "\n", encoding="utf-8")
    (outputs / "human_approval_decision.txt").write_text(_as_text(approval), encoding="utf-8")
    return approval


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _as_text(payload: Mapping[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in payload.items()) + "\n"
