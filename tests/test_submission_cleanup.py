"""Final regression checks for submission cleanup."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import llm_pipeline.ui.review_actions as review_actions


def test_app_has_one_friendly_repair_source_helper() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    helpers = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_friendly_repair_source"
    ]

    assert len(helpers) == 1
    assert 'return "false" if False else "true"' not in source


def test_catalog_discovery_is_not_duplicated_inside_cache_helper() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    helper = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_cached_catalog"
    )
    helper_source = ast.get_source_segment(source, helper) or ""

    assert helper_source.count("discover_benchmark_catalog(Path.cwd())") == 1


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ("rejected", "rejected"),
        ("needs_changes", "needs_changes"),
    ],
)
def test_non_approval_review_decisions_are_not_successful(
    tmp_path: Path,
    monkeypatch,
    decision: str,
    expected_status: str,
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

    monkeypatch.setattr(
        review_actions,
        "candidate_report_for_job",
        lambda job, root: report,
    )
    monkeypatch.setattr(
        review_actions,
        "create_human_approval",
        lambda **kwargs: {
            "decision": kwargs["decision"],
            "reviewer": kwargs["reviewer"],
            "allows_progress": False,
            "decided_at_utc": "2026-09-01T18:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        review_actions,
        "create_evaluation_metrics",
        lambda **kwargs: {"overall_status": "failed"},
    )
    monkeypatch.setattr(
        review_actions,
        "generate_final_experiment_report",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        review_actions,
        "write_job",
        lambda job, root: job,
    )

    job = {
        "job_id": "job-one",
        "status": "awaiting_review",
        "workspace_path": str(workspace),
        "candidate_report": str(report),
        "result": {},
    }

    updated = review_actions.finalize_job_review(
        job,
        decision=decision,
        reviewer="Reviewer",
        project_root=tmp_path,
    )

    assert updated["status"] == expected_status
    assert updated["successful"] is False


def test_review_decision_requires_awaiting_review_state(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError,
        match="Only jobs awaiting human review",
    ):
        review_actions.finalize_job_review(
            {"status": "successful"},
            decision="approved",
            reviewer="Reviewer",
            project_root=tmp_path,
        )


def test_file_review_clears_results_when_input_signature_changes() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert "file_review_input_signature = hashlib.sha256" in source
    assert (
        'existing_review.get("input_signature") != file_review_input_signature'
        in source
    )
    assert 'st.session_state.pop("file_review_result", None)' in source


def test_previous_batch_installers_are_not_part_of_submission_tree() -> None:
    temporary_paths = [
        Path("apply_dissertation_fixes_batch1.py"),
        Path("apply_dissertation_fixes_batch2.py"),
        Path("apply_dissertation_fixes_batch3.py"),
        Path("BATCH1_LOCAL_TESTING.md"),
        Path("BATCH2_LOCAL_TESTING.md"),
        Path("BATCH3_LOCAL_TESTING.md"),
        Path("batch3_payload"),
    ]

    assert all(not path.exists() for path in temporary_paths)
