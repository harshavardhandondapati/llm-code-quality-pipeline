"""Final submission polish safeguards."""

from pathlib import Path


def test_ui_uses_current_evidence_filenames() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert "post_fix_evaluation_result.json" in source
    assert "bug_detection_result.json" in source
    assert "fix_generation_result.json" in source
    assert "post_fix_evaluation.json" not in source
    assert "bug_detection_response.json" not in source
    assert "fix_generation_response.json" not in source


def test_file_review_model_call_is_password_protected() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert 'file_review_allowed = _password_ok("file_review_password")' in source
    assert "disabled=not file_review_allowed" in source


def test_blank_review_comments_are_preserved() -> None:
    source = Path("src/llm_pipeline/ui/review_actions.py").read_text(encoding="utf-8")
    assert "comments=comments.strip()," in source
    assert "Reviewed the saved repair and validation evidence." not in source


def test_archived_java_metadata_is_portable() -> None:
    root = Path("evidence/java_chart_1/outputs")
    for name in [
        "final_experiment_report.json",
        "final_experiment_report.md",
        "final_experiment_report.txt",
        "final_experiment_report.html",
        "workflow_pipeline_result.json",
        "workflow_pipeline_result.txt",
        "pipeline_run_manifest.json",
        "source_snapshots.json",
    ]:
        text = (root / name).read_text(encoding="utf-8", errors="replace")
        assert "/mnt/" not in text
        assert "workspaces/run_" not in text
