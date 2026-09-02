"""Function-aware repair context for large files."""

from __future__ import annotations

from pathlib import Path

from llm_pipeline.prompts.builder import build_fix_generation_prompt
from llm_pipeline.workflow.runner import (
    _add_focused_file_content,
    _find_function_declaration_line,
)


def test_java_function_declaration_beats_incorrect_model_line(tmp_path: Path) -> None:
    source = tmp_path / "Large.java"
    lines = [f"// filler {number}\n" for number in range(1, 2201)]
    lines[1789] = "    public LegendItemCollection getLegendItems() {\n"
    lines[1795] = "        CategoryDataset dataset = this.plot.getDataset(index);\n"
    source.write_text("".join(lines), encoding="utf-8")

    context = {"additional_context": {}}
    _add_focused_file_content(
        context,
        tmp_path,
        "Large.java",
        line_start=1003,
        line_end=1003,
        function_name="getLegendItems",
        max_characters=6000,
        context_lines=20,
    )

    additional = context["additional_context"]
    focused = additional["focused_file_content"]

    assert additional["focused_file_anchor"] == "function_name"
    assert additional["focused_file_line_start"] == 1770
    assert additional["focused_file_line_end"] == 1810
    assert "public LegendItemCollection getLegendItems()" in focused
    assert "this.plot.getDataset(index)" in focused
    assert "// filler 1003" not in focused


def test_function_locator_ignores_comment_and_call_site() -> None:
    lines = [
        " * @see #getLegendItems()\n",
        "LegendItemCollection result = getLegendItems();\n",
        "public LegendItemCollection getLegendItems() {\n",
    ]

    assert _find_function_declaration_line(lines, "getLegendItems", 1) == 3


def test_missing_function_falls_back_to_reported_line(tmp_path: Path) -> None:
    source = tmp_path / "Large.java"
    source.write_text(
        "".join(f"line {number}\n" for number in range(1, 2201)),
        encoding="utf-8",
    )

    context = {"additional_context": {}}
    _add_focused_file_content(
        context,
        tmp_path,
        "Large.java",
        line_start=1003,
        line_end=1004,
        function_name="missingMethod",
        max_characters=6000,
        context_lines=20,
    )

    additional = context["additional_context"]
    assert additional["focused_file_anchor"] == "line_range"
    assert additional["focused_file_line_start"] == 983
    assert additional["focused_file_line_end"] == 1024


def test_repair_prompt_tells_model_to_verify_detection_hypothesis() -> None:
    context = {
        "project": "Chart",
        "bug_id": "1",
        "language": "java",
        "failure_output": "failing test",
        "failing_tests": ["ExampleTest::testCase"],
        "snippets": [],
        "additional_context": {
            "focused_file_path": "Large.java",
            "focused_file_content": (
                "public LegendItemCollection getLegendItems() {\n"
                "    return result;\n"
                "}\n"
            ),
            "focused_file_is_complete": False,
            "focused_file_line_start": 1700,
            "focused_file_line_end": 1900,
            "focused_file_anchor": "function_name",
            "focused_file_function_name": "getLegendItems",
        },
    }
    detection = {
        "bug_found": True,
        "file_path": "Large.java",
        "function_name": "getLegendItems",
        "line_start": 1003,
        "line_end": 1003,
        "explanation": "A detection hypothesis that may be inaccurate.",
    }

    prompt = build_fix_generation_prompt(context, detection, real_llm=True)
    text = "\n".join(message["content"] for message in prompt["messages"])

    assert "around the detected function getLegendItems" in text
    assert "Treat the earlier bug-detection explanation as a hypothesis" in text
    assert "do not invent code that is not present" in text
