"""Tests for exact run selection in the review UI."""

import json
from pathlib import Path

from llm_pipeline.ui.run_history import candidate_report_for_job, format_job_label


def _write_report(path: Path, workspace: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"records": [{"workspace_path": str(workspace)}]}, indent=2),
        encoding="utf-8",
    )


def test_candidate_report_prefers_exact_workspace_evidence(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "run-one"
    exact = workspace / "outputs" / "candidate_selection.json"
    latest = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    _write_report(exact, workspace)
    _write_report(latest, tmp_path / "workspaces" / "run-two")

    job = {
        "job_id": "job-one",
        "workspace_path": str(workspace),
        "candidate_report": str(latest),
    }

    assert candidate_report_for_job(job, tmp_path) == exact.resolve()


def test_candidate_report_rejects_shared_report_for_another_run(tmp_path: Path) -> None:
    first = tmp_path / "workspaces" / "run-one"
    second = tmp_path / "workspaces" / "run-two"
    latest = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    _write_report(latest, second)

    job = {
        "job_id": "job-one",
        "workspace_path": str(first),
        "candidate_report": str(latest),
    }

    assert candidate_report_for_job(job, tmp_path) is None


def test_matching_legacy_report_can_still_be_loaded_safely(tmp_path: Path) -> None:
    workspace = tmp_path / "workspaces" / "run-one"
    latest = tmp_path / "results" / "bugsinpy_candidate_selection.json"
    _write_report(latest, workspace)

    job = {
        "job_id": "job-one",
        "workspace_path": str(workspace),
        "candidate_report": str(latest),
    }

    assert candidate_report_for_job(job, tmp_path) == latest.resolve()


def test_repeated_same_bug_and_model_have_distinct_labels() -> None:
    common = {
        "dataset": "bugsinpy",
        "project": "httpie",
        "bug_id": "1",
        "provider": "openrouter",
        "model_name": "openai/gpt-4.1",
        "status": "successful",
    }
    first = {
        **common,
        "job_id": "job_20260901_120000_aaaa",
        "created_at_utc": "2026-09-01T12:00:00+00:00",
    }
    second = {
        **common,
        "job_id": "job_20260901_123000_bbbb",
        "created_at_utc": "2026-09-01T12:30:00+00:00",
    }

    assert format_job_label(first) != format_job_label(second)
    assert "job_20260901_120000_aaaa" in format_job_label(first)
    assert "job_20260901_123000_bbbb" in format_job_label(second)


def test_app_no_longer_uses_static_run_options_or_candidate_index() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "RUN_OPTIONS" not in source
    assert "candidate_index" not in source
    assert "review_job_id" in source
    assert "Select a run..." in source
