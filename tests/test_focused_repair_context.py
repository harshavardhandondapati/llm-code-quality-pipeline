"""Tests for repair context selected after model fault localisation."""

from __future__ import annotations

from pathlib import Path

from llm_pipeline.prompts.builder import build_fix_generation_prompt
from llm_pipeline.workflow.runner import _add_focused_file_content


def test_large_focused_file_uses_detected_line_window(tmp_path: Path) -> None:
    source = tmp_path / "Large.java"
    lines = [f"line {number}\n" for number in range(1, 2201)]
    lines[1798] = "TARGET_DEFECT_LINE\n"
    source.write_text("".join(lines), encoding="utf-8")

    context = {"additional_context": {}}
    _add_focused_file_content(
        context,
        tmp_path,
        "Large.java",
        line_start=1799,
        line_end=1800,
        max_characters=6000,
        context_lines=20,
    )

    additional = context["additional_context"]
    assert additional["focused_file_is_complete"] is False
    assert additional["focused_file_line_start"] == 1779
    assert additional["focused_file_line_end"] == 1820
    assert "TARGET_DEFECT_LINE" in additional["focused_file_content"]
    assert "line 1\n" not in additional["focused_file_content"]


def test_small_focused_file_remains_complete(tmp_path: Path) -> None:
    source = tmp_path / "Small.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8")

    context = {"additional_context": {}}
    _add_focused_file_content(
        context,
        tmp_path,
        "Small.py",
        line_start=2,
        line_end=2,
    )

    additional = context["additional_context"]
    assert additional["focused_file_is_complete"] is True
    assert additional["focused_file_line_start"] == 1
    assert additional["focused_file_line_end"] == 2
    assert additional["focused_file_content"] == "def value():\n    return 1\n"


def test_fix_prompt_labels_excerpt_and_requests_unified_diff() -> None:
    context = {
        "project": "Chart",
        "bug_id": "1",
        "language": "java",
        "failure_output": "failing test",
        "failing_tests": ["ExampleTest::testCase"],
        "snippets": [],
        "additional_context": {
            "focused_file_path": "Large.java",
            "focused_file_content": "before\\nTARGET_DEFECT_LINE\\nafter\\n",
            "focused_file_is_complete": False,
            "focused_file_line_start": 1700,
            "focused_file_line_end": 1900,
        },
    }
    detection = {
        "bug_found": True,
        "file_path": "Large.java",
        "function_name": "targetMethod",
        "line_start": 1799,
        "line_end": 1800,
        "explanation": "The detected branch is incorrect.",
    }

    prompt = build_fix_generation_prompt(context, detection, real_llm=True)
    text = "\\n".join(message["content"] for message in prompt["messages"])

    assert "Focused affected source excerpt for repair (lines 1700-1900)" in text
    assert "This is not the complete file" in text
    assert "return a unified diff rather than fixed_files" in text
    assert "TARGET_DEFECT_LINE" in text
    assert "Complete affected source file for repair" not in text
