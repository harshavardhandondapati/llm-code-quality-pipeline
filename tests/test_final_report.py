import json
from pathlib import Path

import pytest

from llm_pipeline.reporting import generate_final_experiment_report, load_candidate_record


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_report_fixture(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    outputs = workspace / "outputs"
    candidate_report = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    write_json(
        candidate_report,
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
                {"relative_path": "tests/test_downloads.py"},
                {"relative_path": "httpie/downloads.py"},
            ]
        },
    )
    write_json(
        outputs / "validation_result.json",
        {
            "patch_applied": True,
            "compilation_passed": True,
            "triggering_tests_passed": True,
            "changed_files": ["httpie/downloads.py"],
        },
    )
    write_json(
        outputs / "human_approval_decision.json",
        {
            "decision": "approved",
            "allows_progress": True,
            "reviewer": "Hari",
        },
    )
    write_json(
        outputs / "workflow_pipeline_result.json",
        {
            "steps": [
                {"name": "candidate_selection", "status": "completed", "detail": "httpie-1 accepted"},
                {"name": "metrics", "status": "completed"},
            ]
        },
    )
    write_json(
        outputs / "evaluation_metrics.json",
        {
            "project": "httpie",
            "bug_id": "1",
            "candidate_status": "accepted",
            "target_python": "3.8.20",
            "overall_status": "successful",
            "repair_status": "successful_repair",
            "baseline_failure_observed": True,
            "detection_bug_found": True,
            "detection_file_path": "httpie/downloads.py",
            "detection_confidence": 0.82,
            "patch_present": True,
            "patch_applied": True,
            "compilation_passed": True,
            "triggering_tests_passed": True,
            "human_decision": "approved",
            "human_allows_progress": True,
            "retry_count": 0,
            "total_known_execution_time_seconds": 12.5,
            "changed_files": ["httpie/downloads.py"],
        },
    )
    return candidate_report, outputs


def test_load_candidate_record(tmp_path: Path):
    candidate_report, _ = create_report_fixture(tmp_path)

    record = load_candidate_record(candidate_report)

    assert record["project"] == "httpie"
    assert record["bug_id"] == "1"


def test_load_candidate_record_rejects_empty_report(tmp_path: Path):
    report = tmp_path / "empty.json"
    write_json(report, {"records": []})

    with pytest.raises(ValueError):
        load_candidate_record(report)


def test_generate_final_experiment_report_writes_all_formats(tmp_path: Path):
    candidate_report, outputs = create_report_fixture(tmp_path)

    report = generate_final_experiment_report(candidate_report_path=candidate_report)

    assert report.project == "httpie"
    assert report.overall_status == "successful"
    assert report.repair_status == "successful_repair"
    assert report.source_context_files == ["tests/test_downloads.py", "httpie/downloads.py"]
    assert report.changed_files == ["httpie/downloads.py"]
    assert report.pipeline_steps[0]["name"] == "candidate_selection"

    assert (outputs / "final_experiment_report.json").exists()
    assert (outputs / "final_experiment_report.md").exists()
    assert (outputs / "final_experiment_report.txt").exists()
    assert (outputs / "final_experiment_report.html").exists()


def test_report_json_contains_evidence_paths(tmp_path: Path):
    candidate_report, outputs = create_report_fixture(tmp_path)

    generate_final_experiment_report(candidate_report_path=candidate_report)
    payload = json.loads((outputs / "final_experiment_report.json").read_text(encoding="utf-8"))

    assert "evaluation_metrics.json" in payload["evidence_files"]
    assert "validation_result.json" in payload["evidence_files"]
    assert payload["human_decision"] == "approved"


def test_markdown_report_contains_key_summary(tmp_path: Path):
    candidate_report, outputs = create_report_fixture(tmp_path)

    generate_final_experiment_report(candidate_report_path=candidate_report)
    markdown = (outputs / "final_experiment_report.md").read_text(encoding="utf-8")

    assert "Final Experiment Report: httpie-1" in markdown
    assert "successful_repair" in markdown
    assert "httpie/downloads.py" in markdown


def test_generate_report_requires_metrics(tmp_path: Path):
    workspace = tmp_path / "workspace"
    report = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    write_json(
        report,
        {
            "records": [
                {
                    "project": "httpie",
                    "bug_id": "1",
                    "workspace_path": str(workspace),
                }
            ]
        },
    )

    with pytest.raises(FileNotFoundError):
        generate_final_experiment_report(candidate_report_path=report)
