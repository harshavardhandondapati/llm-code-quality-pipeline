"""Create simple metrics from the pipeline evidence files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def create_post_fix_evaluation(
    *,
    candidate_record: Mapping[str, Any],
    validation: Mapping[str, Any],
    outputs_dir: Path | str,
) -> dict[str, Any]:
    """Classify the before/after repair outcome."""
    improved = bool(
        candidate_record.get("baseline_failure_observed")
        and validation.get("patch_applied")
        and validation.get("compilation_passed")
        and validation.get("triggering_tests_passed")
    )
    result = {
        "dataset": candidate_record.get("dataset"),
        "language": candidate_record.get("language"),
        "project": candidate_record.get("project"),
        "bug_id": candidate_record.get("bug_id"),
        "baseline_failure_observed": bool(candidate_record.get("baseline_failure_observed")),
        "patch_applied": bool(validation.get("patch_applied")),
        "compilation_passed": bool(validation.get("compilation_passed")),
        "triggering_tests_passed": bool(validation.get("triggering_tests_passed")),
        "changed_files": list(validation.get("changed_files", [])),
        "improved": improved,
        "repair_status": "successful_repair" if improved else "unsuccessful_repair",
    }
    output = Path(outputs_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "post_fix_evaluation_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (output / "post_fix_evaluation_result.txt").write_text(_as_text(result), encoding="utf-8")
    return result


def create_evaluation_metrics(
    *,
    candidate_record: Mapping[str, Any],
    outputs_dir: Path | str,
) -> dict[str, Any]:
    """Collect the final metrics used in the dissertation report."""
    outputs = Path(outputs_dir)
    detection = _safe_json(outputs / "bug_detection_result.json")
    fix = _safe_json(outputs / "fix_generation_result.json")
    validation = _safe_json(outputs / "validation_result.json")
    post_fix = _safe_json(outputs / "post_fix_evaluation_result.json")
    approval = _safe_json(outputs / "human_approval_decision.json")

    local_fallback = _safe_json(outputs / "local_repair_fallback_result.json")
    repair_source = validation.get("repair_source") or fix.get("repair_source") or local_fallback.get("repair_source")
    patch_present = bool(
        str(fix.get("patch") or "").strip()
        or _has_fixed_files(fix)
        or str(local_fallback.get("patch") or "").strip()
        or _has_fixed_files(local_fallback)
        or validation.get("patch_applied")
    )
    files_modified = _first_non_empty_list(
        fix.get("files_modified"),
        validation.get("changed_files"),
        local_fallback.get("files_modified"),
    )

    successful = bool(
        candidate_record.get("baseline_failure_observed")
        and detection.get("bug_found")
        and patch_present
        and validation.get("patch_applied")
        and validation.get("compilation_passed")
        and validation.get("triggering_tests_passed")
        and post_fix.get("improved")
        and approval.get("allows_progress")
    )

    metrics = {
        "dataset": candidate_record.get("dataset"),
        "language": candidate_record.get("language"),
        "project": candidate_record.get("project"),
        "bug_id": candidate_record.get("bug_id"),
        "candidate_status": candidate_record.get("status"),
        "target_python": candidate_record.get("target_python"),
        "target_runtime": candidate_record.get("target_runtime") or candidate_record.get("target_python"),
        "overall_status": "successful" if successful else "incomplete",
        "baseline_failure_observed": bool(candidate_record.get("baseline_failure_observed")),
        "detection_bug_found": bool(detection.get("bug_found")),
        "detection_file_path": detection.get("file_path"),
        "detection_confidence": detection.get("confidence"),
        "patch_present": patch_present,
        "files_modified": files_modified,
        "repair_source": repair_source,
        "local_fallback_used": bool(local_fallback),
        "patch_applied": bool(validation.get("patch_applied")),
        "compilation_passed": bool(validation.get("compilation_passed")),
        "triggering_tests_passed": bool(validation.get("triggering_tests_passed")),
        "post_fix_improved": bool(post_fix.get("improved")),
        "repair_status": post_fix.get("repair_status"),
        "human_decision": approval.get("decision"),
        "reviewer": approval.get("reviewer"),
        "human_allows_progress": bool(approval.get("allows_progress")),
        "retry_count": 0,
        "total_known_execution_time_seconds": _known_time(outputs),
        "failure_reason": validation.get("failure_reason"),
    }

    (outputs / "evaluation_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (outputs / "evaluation_metrics.txt").write_text(_as_text(metrics), encoding="utf-8")
    return metrics


def _has_fixed_files(payload: Mapping[str, Any]) -> bool:
    fixed_files = payload.get("fixed_files") if isinstance(payload, Mapping) else None
    return isinstance(fixed_files, Mapping) and any(str(value).strip() for value in fixed_files.values())


def _first_non_empty_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list) and value:
            return list(value)
    return []


def _safe_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _known_time(outputs: Path) -> float:
    total = 0.0
    for name in ["baseline_reproduction.json", "post_patch_compile.json", "post_patch_triggering_test.json"]:
        data = _safe_json(outputs / name)
        if "execution_time_seconds" in data:
            total += float(data.get("execution_time_seconds") or 0)
        if "compile_result" in data:
            total += float(data.get("compile_result", {}).get("execution_time_seconds") or 0)
        if "test_result" in data and data["test_result"]:
            total += float(data["test_result"].get("execution_time_seconds") or 0)
    return round(total, 3)


def _as_text(payload: Mapping[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in payload.items()) + "\n"
