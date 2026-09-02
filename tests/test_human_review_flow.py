"""Regression tests for the human-review and UI-state batch."""

import json
from pathlib import Path

import llm_pipeline.ui.review_actions as review_actions
from llm_pipeline.approval.approval import create_human_approval
from llm_pipeline.ui.review_actions import is_ready_for_human_review


def test_pending_approval_does_not_allow_progress(tmp_path: Path) -> None:
    approval = create_human_approval(
        candidate_record={"project": "Chart", "bug_id": "1"},
        outputs_dir=tmp_path,
        decision="pending",
        reviewer="unassigned",
        comments="Awaiting review.",
    )

    assert approval["decision"] == "pending"
    assert approval["allows_progress"] is False
    assert approval["decided_at_utc"] is None


def test_ready_for_human_review_requires_all_technical_stages() -> None:
    result = {
        "steps": [
            {"name": "baseline_reproduction", "status": "passed"},
            {"name": "source_context", "status": "passed"},
            {"name": "bug_detection", "status": "passed"},
            {"name": "fix_generation", "status": "passed"},
            {"name": "patch_validation", "status": "passed"},
            {"name": "post_fix_evaluation", "status": "passed"},
            {"name": "human_approval", "status": "blocked"},
            {"name": "metrics", "status": "failed"},
        ]
    }

    assert is_ready_for_human_review(result) is True

    result["steps"][4]["status"] = "failed"
    assert is_ready_for_human_review(result) is False


def test_finalize_job_review_updates_status_and_workflow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspaces" / "run-one"
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True)

    report = outputs / "candidate_selection.json"
    report.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "dataset": "Defects4J",
                        "language": "java",
                        "project": "Chart",
                        "bug_id": "1",
                        "workspace_path": str(workspace),
                        "baseline_failure_observed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (outputs / "workflow_pipeline_result.json").write_text(
        json.dumps(
            {
                "overall_status": "failed",
                "successful": False,
                "steps": [
                    {"name": "patch_validation", "status": "passed", "detail": ""},
                    {"name": "human_approval", "status": "blocked", "detail": ""},
                    {"name": "metrics", "status": "failed", "detail": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(review_actions, "candidate_report_for_job", lambda job, root: report)
    monkeypatch.setattr(
        review_actions,
        "create_human_approval",
        lambda **kwargs: {
            "decision": "approved",
            "reviewer": "Reviewer",
            "allows_progress": True,
            "decided_at_utc": "2026-09-01T17:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        review_actions,
        "create_evaluation_metrics",
        lambda **kwargs: {"overall_status": "successful"},
    )
    monkeypatch.setattr(review_actions, "generate_final_experiment_report", lambda **kwargs: None)
    monkeypatch.setattr(review_actions, "write_job", lambda job, root: job)

    job = {
        "job_id": "job-one",
        "status": "awaiting_review",
        "workspace_path": str(workspace),
        "candidate_report": str(report),
        "result": {},
    }

    updated = review_actions.finalize_job_review(
        job,
        decision="approved",
        reviewer="Reviewer",
        project_root=tmp_path,
    )

    assert updated["status"] == "successful"
    assert updated["successful"] is True

    workflow = json.loads(
        (outputs / "workflow_pipeline_result.json").read_text(encoding="utf-8")
    )
    assert workflow["overall_status"] == "successful"
    statuses = {step["name"]: step["status"] for step in workflow["steps"]}
    assert statuses["human_approval"] == "passed"
    assert statuses["metrics"] == "passed"


def test_app_uses_submission_safe_review_behaviour() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "The LLM patch was applied" not in source
    assert 'caption("LLM patch")' not in source
    assert "Generated repair" in source
    assert "awaiting_review" in source
    assert "finalize_job_review" in source
    assert "file_review_input_signature" in source
    assert "OPENROUTER_MODEL_PRESETS" in source
    assert "st.stop()" not in source


def test_web_worker_waits_for_real_review() -> None:
    source = Path("scripts/run_pipeline_job.py").read_text(encoding="utf-8")

    assert 'approval="pending"' in source
    assert 'status"] = "awaiting_review"' in source
    assert 'approval="approved"' not in source
