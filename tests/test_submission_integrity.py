"""Regression tests for dissertation experiment integrity."""

import json
from pathlib import Path

from llm_pipeline.prompts.builder import build_bug_detection_prompt
from llm_pipeline.workflow.runner import (
    _build_local_benchmark_repair,
    _write_candidate_reports,
)


def _real_llm_context(*, benchmark_hints_used: bool) -> dict:
    return {
        "project": "httpie",
        "bug_id": "1",
        "language": "python",
        "failure_output": "ImportError inside pytest runner",
        "failing_tests": ["tests/test_downloads.py"],
        "snippets": [
            {
                "file_path": "module.py",
                "start_line": 1,
                "end_line": 2,
                "content": "def value():\n    return 1\n",
            }
        ],
        "additional_context": {
            "selected_files": ["module.py"],
            "benchmark_hints_used": benchmark_hints_used,
            "benchmark_changed_files": ["httpie/downloads.py"],
            "real_llm_candidate_files": ["httpie/downloads.py"],
        },
    }


def test_each_run_keeps_its_own_candidate_report(tmp_path: Path) -> None:
    results = tmp_path / "results"
    first_outputs = tmp_path / "run-one" / "outputs"
    second_outputs = tmp_path / "run-two" / "outputs"

    first = {
        "project": "httpie",
        "bug_id": "1",
        "workspace_path": str(tmp_path / "run-one"),
    }
    second = {
        "project": "httpie",
        "bug_id": "1",
        "workspace_path": str(tmp_path / "run-two"),
    }

    first_report = _write_candidate_reports(
        record=first,
        workspace_outputs=first_outputs,
        results_directory=results,
        dataset="bugsinpy",
    )
    second_report = _write_candidate_reports(
        record=second,
        workspace_outputs=second_outputs,
        results_directory=results,
        dataset="bugsinpy",
    )

    first_saved = json.loads(first_report.read_text(encoding="utf-8"))
    second_saved = json.loads(second_report.read_text(encoding="utf-8"))
    latest = json.loads(
        (results / "bugsinpy_candidate_selection.json").read_text(encoding="utf-8")
    )

    assert first_report != second_report
    assert first_saved["records"][0]["workspace_path"].endswith("run-one")
    assert second_saved["records"][0]["workspace_path"].endswith("run-two")
    assert latest["records"][0]["workspace_path"].endswith("run-two")


def test_real_llm_prompt_hides_benchmark_answer_when_hints_are_disabled() -> None:
    prompt = build_bug_detection_prompt(
        _real_llm_context(benchmark_hints_used=False),
        real_llm=True,
        retry=True,
    )
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "Known benchmark focus" not in text
    assert "filesystem filename-length limits" not in text
    assert "Benchmark candidate file(s) to inspect first" not in text
    assert "httpie/downloads.py" not in text
    assert "This is a retry" in text


def test_real_llm_prompt_ignores_case_specific_benchmark_metadata() -> None:
    prompt = build_bug_detection_prompt(
        _real_llm_context(benchmark_hints_used=True),
        real_llm=True,
    )
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "Known benchmark focus" not in text
    assert "httpie/downloads.py" not in text
    assert "filesystem filename-length limits" not in text


def test_local_benchmark_fallback_is_disabled_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("PIPELINE_ALLOW_LOCAL_FALLBACK", raising=False)

    result = _build_local_benchmark_repair(
        project="httpie",
        bug_id="1",
        project_path=tmp_path,
        bug_detection={
            "file_path": "httpie/downloads.py",
            "explanation": "filename issue",
        },
    )

    assert result is None
