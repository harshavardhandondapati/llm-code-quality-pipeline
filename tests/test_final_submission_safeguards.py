"""Final submission safeguards."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from llm_pipeline.approval.approval import create_human_approval
from llm_pipeline.prompts.builder import build_bug_detection_prompt
from llm_pipeline.ui.run_history import candidate_report_for_job, format_job_label, submitted_evidence_jobs
from llm_pipeline.workflow.runner import run_final_pipeline


def _prompt_context() -> dict:
    return {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "AssertionError",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [{"file_path": "module.py", "start_line": 1, "end_line": 2, "content": "def value():\n    return 1\n"}],
        "additional_context": {
            "selected_files": ["module.py"],
            "benchmark_hints_used": True,
            "benchmark_changed_files": ["httpie/downloads.py"],
            "real_llm_candidate_files": ["httpie/downloads.py"],
        },
    }


def test_prompt_builder_has_no_case_specific_benchmark_answers() -> None:
    source = Path("src/llm_pipeline/prompts/builder.py").read_text(encoding="utf-8")
    for item in [
        "_known_benchmark_focus",
        "Known benchmark focus",
        "filesystem filename-length limits",
        "getLegendItems(), not the singular",
        "benchmark_changed_files",
        "real_llm_candidate_files",
    ]:
        assert item not in source

    prompt = build_bug_detection_prompt(_prompt_context(), real_llm=True)
    text = "\n".join(message["content"] for message in prompt["messages"])
    assert "httpie/downloads.py" not in text
    assert "Known benchmark focus" not in text


def test_final_runner_disables_benchmark_changed_file_hints() -> None:
    source = Path("src/llm_pipeline/workflow/runner.py").read_text(encoding="utf-8")
    assert "use_benchmark_hints=False" in source
    assert "use_benchmark_hints=settings.context_use_benchmark_hints" not in source
    assert "if real_llm and settings.context_use_benchmark_hints" not in source


def test_pipeline_and_approval_default_to_pending(tmp_path: Path) -> None:
    approval_signature = inspect.signature(create_human_approval)
    pipeline_signature = inspect.signature(run_final_pipeline)
    assert approval_signature.parameters["decision"].default == "pending"
    assert approval_signature.parameters["reviewer"].default == ""
    assert pipeline_signature.parameters["approval"].default == "pending"
    assert pipeline_signature.parameters["reviewer"].default == ""

    result = create_human_approval(
        candidate_record={"project": "Example", "bug_id": "1"},
        outputs_dir=tmp_path,
    )
    assert result["decision"] == "pending"
    assert result["reviewer"] == ""
    assert result["allows_progress"] is False
    assert result["decided_at_utc"] is None


def test_cli_does_not_default_to_approved() -> None:
    source = Path("scripts/run_pipeline.py").read_text(encoding="utf-8")
    assert 'default="pending"' in source
    assert 'choices=["pending", "approved", "rejected", "needs_changes"]' in source
    assert 'parser.add_argument("--reviewer", default=""' in source


def test_submitted_evidence_is_discovered_only_under_evidence(tmp_path: Path) -> None:
    submitted = tmp_path / "evidence" / "python_case"
    outputs = submitted / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "evaluation_metrics.json").write_text(
        json.dumps({"overall_status": "successful", "provider": "mock", "model_name": "mock-model"}),
        encoding="utf-8",
    )
    (outputs / "workflow_pipeline_result.json").write_text(
        json.dumps({"overall_status": "successful", "provider": "mock", "model_name": "mock-model"}),
        encoding="utf-8",
    )

    results = tmp_path / "results"
    results.mkdir()
    report = results / "bugsinpy_candidate_selection.json"
    report.write_text(
        json.dumps({"records": [{"dataset": "BugsInPy", "project": "httpie", "bug_id": "1", "workspace_path": "evidence/python_case"}]}),
        encoding="utf-8",
    )
    (results / "defects4j_candidate_selection.json").write_text(
        json.dumps({"records": [{"dataset": "Defects4J", "project": "Chart", "bug_id": "1", "workspace_path": "workspaces/runtime_case"}]}),
        encoding="utf-8",
    )

    jobs = submitted_evidence_jobs(tmp_path)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["source"] == "submitted"
    assert job["dataset"] == "bugsinpy"
    assert job["provider"] == "mock"
    assert candidate_report_for_job(job, tmp_path) == report.resolve()
    assert format_job_label(job).startswith("Submitted evidence · BugsInPy · httpie-1")


def test_app_escapes_dynamic_html_and_loads_submitted_evidence() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert "import html" in source
    assert "def _html_text" in source
    assert "html.escape(" in source
    assert "submitted_evidence_jobs(Path.cwd())" in source
    assert "build_review_markdown" not in source
    assert "review_python_source" not in source
    assert "write_interactive_review_artifacts" not in source

def test_selected_candidate_report_keeps_workspace_identity() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'for key in ["provider", "model_name"]:' in source
    assert (
        'for key in ["provider", "model_name", "workspace_path", "candidate_report"]:'
        not in source
    )
    assert 'summary_data["candidate_report"] = candidate_report' in source
