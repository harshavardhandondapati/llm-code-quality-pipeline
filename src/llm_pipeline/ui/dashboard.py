"""Dashboard data loading for the Streamlit and CLI review UI."""

from __future__ import annotations

import json
import difflib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class DashboardSummary:
    """Compact summary of the validated run evidence."""

    dataset: str
    language: str
    project: str
    bug_id: str
    candidate_status: str
    target_python: str | None
    target_runtime: str | None
    workspace_path: str
    baseline_failure_observed: bool
    source_snippet_count: int
    bug_found: bool | None
    detection_file_path: str | None
    detection_confidence: float | None
    files_modified: list[str]
    patch_applied: bool | None
    compilation_passed: bool | None
    triggering_tests_passed: bool | None
    repair_status: str | None
    human_decision: str | None
    human_allows_progress: bool | None
    overall_status: str | None
    final_report_available: bool
    outputs_dir: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeComparison:
    """Before-and-after source view for the file changed by the run."""

    file_path: str
    original_source: str
    updated_source: str
    benchmark_fixed_source: str
    diff_text: str
    issue_summary: str | None
    files_changed: list[str]
    original_available: bool
    updated_available: bool
    outputs_dir: str

    @property
    def has_change(self) -> bool:
        return bool(self.diff_text.strip() or self.original_source != self.updated_source)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["has_change"] = self.has_change
        return payload


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_candidate_outputs(candidate_report_path: str | Path, candidate_index: int = 0) -> tuple[dict[str, Any], Path, dict[str, dict[str, Any]]]:
    """Load the selected candidate and commonly used output JSON files."""

    report_path = Path(candidate_report_path)
    if not report_path.exists():
        raise FileNotFoundError(f"Candidate report not found: {report_path}")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = report.get("records") or []
    if not records:
        raise ValueError(f"Candidate report has no records: {report_path}")
    if candidate_index < 0 or candidate_index >= len(records):
        raise IndexError(f"Candidate index {candidate_index} is outside available record range 0..{len(records)-1}")

    record = dict(records[candidate_index])
    workspace_path = record.get("workspace_path")
    if not workspace_path:
        raise ValueError("Selected candidate record does not contain workspace_path.")

    outputs = Path(workspace_path) / "outputs"
    data = {
        "source_context": _read_json(outputs / "source_context.json"),
        "bug_detection": _read_json(outputs / "bug_detection_result.json"),
        "fix_generation": _read_json(outputs / "fix_generation_result.json"),
        "validation": _read_json(outputs / "validation_result.json"),
        "post_fix": _read_json(outputs / "post_fix_evaluation_result.json"),
        "human_approval": _read_json(outputs / "human_approval_decision.json"),
        "metrics": _read_json(outputs / "evaluation_metrics.json"),
        "workflow": _read_json(outputs / "workflow_pipeline_result.json"),
        "final_report": _read_json(outputs / "final_experiment_report.json"),
        "local_repair_fallback": _read_json(outputs / "local_repair_fallback_result.json"),
    }
    return record, outputs, data


def _list_value(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def build_dashboard_summary(candidate_report_path: str | Path, candidate_index: int = 0) -> DashboardSummary:
    """Create the UI dashboard summary from evidence files."""

    record, outputs, data = load_candidate_outputs(candidate_report_path, candidate_index)
    source_context = data["source_context"]
    bug_detection = data["bug_detection"]
    fix_generation = data["fix_generation"]
    validation = data["validation"]
    post_fix = data["post_fix"]
    approval = data["human_approval"]
    metrics = data["metrics"]
    final_report = data["final_report"]

    snippets = source_context.get("snippets") or []
    overall_status = metrics.get("overall_status") or final_report.get("overall_status") or data["workflow"].get("overall_status")

    return DashboardSummary(
        dataset=str(record.get("dataset", metrics.get("dataset", "unknown"))),
        language=str(record.get("language", metrics.get("language", "unknown"))),
        project=str(record.get("project", "unknown")),
        bug_id=str(record.get("bug_id", "unknown")),
        candidate_status=str(record.get("status", "unknown")),
        target_python=record.get("target_python"),
        target_runtime=record.get("target_runtime") or metrics.get("target_runtime") or record.get("target_python"),
        workspace_path=str(record.get("workspace_path", "")),
        baseline_failure_observed=bool(record.get("baseline_failure_observed")),
        source_snippet_count=len(snippets),
        bug_found=bug_detection.get("bug_found"),
        detection_file_path=bug_detection.get("file_path"),
        detection_confidence=bug_detection.get("confidence"),
        files_modified=_list_value(fix_generation, "files_modified"),
        patch_applied=validation.get("patch_applied"),
        compilation_passed=validation.get("compilation_passed"),
        triggering_tests_passed=validation.get("triggering_tests_passed"),
        repair_status=post_fix.get("repair_status") or metrics.get("repair_status") or final_report.get("repair_status"),
        human_decision=approval.get("decision") or metrics.get("human_decision"),
        human_allows_progress=approval.get("allows_progress") if approval else metrics.get("human_allows_progress"),
        overall_status=overall_status,
        final_report_available=bool(final_report) or (outputs / "final_experiment_report.html").exists(),
        outputs_dir=str(outputs),
    )



def _normalise_relative_path(path: str | None) -> str:
    value = str(path or "").strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def _same_path(left: str | None, right: str | None) -> bool:
    return _normalise_relative_path(left) == _normalise_relative_path(right)


def _changed_files(data: Mapping[str, Mapping[str, Any]]) -> list[str]:
    files: list[str] = []
    for section, keys in (
        ("validation", ("changed_files",)),
        ("fix_generation", ("files_modified",)),
        ("local_repair_fallback", ("files_modified",)),
        ("metrics", ("files_modified", "changed_files")),
    ):
        payload = data.get(section) or {}
        for key in keys:
            for item in _list_value(payload, key):
                normalised = _normalise_relative_path(item)
                if normalised and normalised not in files:
                    files.append(normalised)
    return files


def _select_comparison_file(data: Mapping[str, Mapping[str, Any]], requested_file: str | None = None) -> str:
    requested = _normalise_relative_path(requested_file)
    if requested:
        return requested
    detection_file = _normalise_relative_path((data.get("bug_detection") or {}).get("file_path"))
    if detection_file:
        return detection_file
    changed = _changed_files(data)
    if changed:
        return changed[0]
    snippets = (data.get("source_context") or {}).get("snippets") or []
    for snippet in snippets:
        if isinstance(snippet, Mapping):
            candidate = _normalise_relative_path(snippet.get("file_path") or snippet.get("relative_path") or snippet.get("path"))
            if candidate:
                return candidate
    return ""


def _source_context_file_content(source_context: Mapping[str, Any], file_path: str) -> str:
    target = _normalise_relative_path(file_path)
    additional = source_context.get("additional_context") or {}
    if isinstance(additional, Mapping) and _same_path(additional.get("focused_file_path"), target):
        focused = additional.get("focused_file_content")
        if isinstance(focused, str) and focused.strip():
            return focused
    for snippet in source_context.get("snippets", []) or []:
        if not isinstance(snippet, Mapping):
            continue
        snippet_path = snippet.get("file_path") or snippet.get("relative_path") or snippet.get("path")
        if _same_path(snippet_path, target):
            content = snippet.get("content")
            if isinstance(content, str):
                return content
    return ""


def _fixed_files_content(payload: Mapping[str, Any], file_path: str) -> str:
    target = _normalise_relative_path(file_path)
    fixed_files = payload.get("fixed_files") or {}
    if not isinstance(fixed_files, Mapping):
        return ""
    for key, value in fixed_files.items():
        if _same_path(str(key), target) and isinstance(value, str):
            return value
    return ""


def _snapshot_content(outputs: Path, stage: str, file_path: str) -> str:
    """Read a saved source snapshot for original, updated or benchmark_fixed."""
    target = _normalise_relative_path(file_path)
    if not target:
        return ""

    nested = outputs / "snapshots" / stage / target
    if nested.is_file():
        return nested.read_text(encoding="utf-8", errors="replace")

    # Backwards-compatible flat snapshot files, for example
    # original_AbstractCategoryItemRenderer.java.
    suffix = Path(target).name
    flat = outputs / f"{stage}_{suffix}"
    if flat.is_file():
        return flat.read_text(encoding="utf-8", errors="replace")

    return ""


def _read_updated_project_file(record: Mapping[str, Any], file_path: str) -> str:
    target = _normalise_relative_path(file_path)
    for root_key in ("project_path", "workspace_path"):
        raw_root = record.get(root_key)
        if not raw_root:
            continue
        root = Path(str(raw_root))
        if root_key == "workspace_path" and (root / "outputs").exists():
            # workspace_path points to the run folder, not the checked-out project.
            continue
        candidate = root / target
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return ""


def _read_diff(outputs: Path, original: str, updated: str, file_path: str) -> str:
    patch_file = outputs / "applied_patch.diff"
    if patch_file.exists():
        text = patch_file.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            return text
    if original or updated:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                updated.splitlines(keepends=True),
                fromfile=f"original/{file_path}",
                tofile=f"updated/{file_path}",
            )
        )
    return ""


def build_code_comparison(
    candidate_report_path: str | Path,
    candidate_index: int = 0,
    file_path: str | None = None,
) -> CodeComparison:
    """Build a clean code-comparison view from existing evidence files."""

    record, outputs, data = load_candidate_outputs(candidate_report_path, candidate_index)
    selected_file = _select_comparison_file(data, file_path)
    source_context = data.get("source_context") or {}
    original = (
        _snapshot_content(outputs, "original", selected_file)
        or _source_context_file_content(source_context, selected_file)
    )

    updated = (
        _snapshot_content(outputs, "updated", selected_file)
        or _fixed_files_content(data.get("local_repair_fallback") or {}, selected_file)
        or _fixed_files_content(data.get("fix_generation") or {}, selected_file)
        or _read_updated_project_file(record, selected_file)
    )
    benchmark_fixed = _snapshot_content(outputs, "benchmark_fixed", selected_file)

    diff_text = _read_diff(outputs, original, updated, selected_file)
    return CodeComparison(
        file_path=selected_file,
        original_source=original,
        updated_source=updated,
        benchmark_fixed_source=benchmark_fixed,
        diff_text=diff_text,
        issue_summary=(
            (data.get("fix_generation") or {}).get("explanation")
            or (data.get("bug_detection") or {}).get("explanation")
        ),
        files_changed=_changed_files(data),
        original_available=bool(original),
        updated_available=bool(updated),
        outputs_dir=str(outputs),
    )
