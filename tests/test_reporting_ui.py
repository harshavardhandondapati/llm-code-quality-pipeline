import json
from pathlib import Path

from llm_pipeline.ui import (
    build_code_comparison,
    build_dashboard_summary,
    build_download_filename,
    build_review_markdown,
    build_unified_diff,
    review_python_source,
    write_interactive_review_artifacts,
)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_validated_outputs(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    report_path = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    write_json(
        report_path,
        {
            "records": [
                {
                    "project": "httpie",
                    "bug_id": "1",
                    "status": "accepted",
                    "target_python": "3.8.20",
                    "baseline_failure_observed": True,
                    "workspace_path": str(workspace),
                }
            ]
        },
    )
    write_json(
        outputs / "source_context.json",
        {
            "snippets": [
                {
                    "file_path": "httpie/downloads.py",
                    "content": "def get_unique_filename(filename):\n    return filename\n",
                    "start_line": 1,
                    "end_line": 2,
                }
            ]
        },
    )
    write_json(
        outputs / "bug_detection_result.json",
        {"bug_found": True, "file_path": "httpie/downloads.py", "confidence": 0.82},
    )
    write_json(
        outputs / "fix_generation_result.json",
        {
            "files_modified": ["httpie/downloads.py"],
            "patch": "diff --git a/httpie/downloads.py b/httpie/downloads.py",
            "fixed_files": {"httpie/downloads.py": "def get_unique_filename(filename):\n    return filename[:255]\n"},
        },
    )
    (outputs / "applied_patch.diff").write_text(
        "--- a/httpie/downloads.py\n+++ b/httpie/downloads.py\n@@ -1,2 +1,2 @@\n def get_unique_filename(filename):\n-    return filename\n+    return filename[:255]\n",
        encoding="utf-8",
    )
    write_json(
        outputs / "validation_result.json",
        {"patch_applied": True, "compilation_passed": True, "triggering_tests_passed": True},
    )
    write_json(outputs / "post_fix_evaluation_result.json", {"repair_status": "successful_repair", "improved": True})
    write_json(outputs / "human_approval_decision.json", {"decision": "approved", "allows_progress": True})
    write_json(outputs / "evaluation_metrics.json", {"overall_status": "successful", "repair_status": "successful_repair"})
    write_json(outputs / "final_experiment_report.json", {"overall_status": "successful", "repair_status": "successful_repair"})
    (outputs / "final_experiment_report.html").write_text("<html><body>ok</body></html>", encoding="utf-8")
    return report_path


def test_dashboard_summary_reads_validated_evidence(tmp_path):
    report_path = create_validated_outputs(tmp_path)

    summary = build_dashboard_summary(report_path)

    assert summary.project == "httpie"
    assert summary.bug_id == "1"
    assert summary.baseline_failure_observed is True
    assert summary.source_snippet_count == 1
    assert summary.bug_found is True
    assert summary.patch_applied is True
    assert summary.triggering_tests_passed is True
    assert summary.human_decision == "approved"
    assert summary.overall_status == "successful"
    assert summary.final_report_available is True


def test_code_comparison_reads_original_and_updated_file(tmp_path):
    report_path = create_validated_outputs(tmp_path)

    comparison = build_code_comparison(report_path)

    assert comparison.file_path == "httpie/downloads.py"
    assert "return filename" in comparison.original_source
    assert "return filename[:255]" in comparison.updated_source
    assert "filename[:255]" in comparison.diff_text
    assert comparison.has_change is True


def test_review_python_source_detects_division_by_zero_risk():
    source = "def divide(a, b):\n    return a / b\n"

    result = review_python_source(source, filename="sample_bug.py")

    assert result.bug_found is True
    assert result.issue_type == "possible_zero_division"
    assert result.changed is True
    assert "if b == 0" in result.fixed_source
    assert "updated_sample_bug.py" in result.patch


def test_review_python_source_detects_len_none_risk():
    source = "def item_count(items):\n    return len(items)\n"

    result = review_python_source(source, filename="sample_bug.py")

    assert result.bug_found is True
    assert result.issue_type == "possible_none_len_error"
    assert result.changed is True
    assert "if items is None" in result.fixed_source


def test_review_python_source_returns_no_issue_for_clean_supported_input():
    source = "def add(a, b):\n    return a + b\n"

    result = review_python_source(source, filename="clean.py")

    assert result.bug_found is False
    assert result.changed is False
    assert result.fixed_source == source


def test_build_download_filename_preserves_py_extension():
    assert build_download_filename("sample_bug.py") == "updated_sample_bug.py"
    assert build_download_filename("sample_bug") == "updated_sample_bug.py"


def test_write_interactive_review_artifacts_creates_downloadable_files(tmp_path):
    source = "def divide(a, b):\n    return a / b\n"
    result = review_python_source(source, filename="sample_bug.py")

    artifacts = write_interactive_review_artifacts(result, original_source=source, output_dir=tmp_path / "review")

    for path in artifacts.values():
        assert Path(path).exists()
    assert "if b == 0" in Path(artifacts["fixed_file"]).read_text(encoding="utf-8")
    assert "possible_zero_division" in Path(artifacts["json_report"]).read_text(encoding="utf-8")


def test_build_review_markdown_contains_limitation_note():
    result = review_python_source("def divide(a, b):\n    return a / b\n", filename="sample_bug.py")

    markdown = build_review_markdown(result)

    assert "File Review Notes" in markdown
    assert "file_only_review" in markdown
    assert "does not run the full project test suite" in markdown


def test_build_unified_diff_for_changed_file():
    original = "def divide(a, b):\n    return a / b\n"
    fixed = "def divide(a, b):\n    if b == 0:\n        raise ValueError('b')\n    return a / b\n"

    diff = build_unified_diff(original, fixed, "sample_bug.py")

    assert "--- sample_bug.py" in diff
    assert "+++ updated_sample_bug.py" in diff
    assert "+    if b == 0:" in diff


def test_code_comparison_prefers_saved_source_snapshots(tmp_path):
    report_path = create_validated_outputs(tmp_path)
    outputs = tmp_path / "workspace" / "outputs"
    snapshot_original = outputs / "snapshots" / "original" / "httpie" / "downloads.py"
    snapshot_updated = outputs / "snapshots" / "updated" / "httpie" / "downloads.py"
    snapshot_original.parent.mkdir(parents=True, exist_ok=True)
    snapshot_updated.parent.mkdir(parents=True, exist_ok=True)
    snapshot_original.write_text("def get_unique_filename(filename):\n    return filename\n", encoding="utf-8")
    snapshot_updated.write_text("def get_unique_filename(filename):\n    return filename[:255]\n", encoding="utf-8")

    comparison = build_code_comparison(report_path)

    assert comparison.original_source == snapshot_original.read_text(encoding="utf-8")
    assert comparison.updated_source == snapshot_updated.read_text(encoding="utf-8")
