"""Interactive single-file review helpers for the Batch 13 UI.

This module deliberately separates the interactive demonstration mode from the
validated BugsInPy experiment. It can produce a suggested fixed file for a
single uploaded Python file, but it does not claim test-validated repair unless
a project-level test suite is also executed outside this mode.
"""

from __future__ import annotations

import ast
import difflib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InteractiveReviewResult:
    """Result produced by the single-file review UI."""

    filename: str
    provider: str
    bug_found: bool
    issue_type: str
    confidence: float
    explanation: str
    fixed_source: str
    patch: str
    changed: bool
    validation_status: str = "file_only_review"
    created_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_download_filename(filename: str, prefix: str = "updated_") -> str:
    """Return a safe fixed-file name without modifying the original upload name."""

    name = Path(filename).name or "uploaded_file.py"
    if not name.endswith(".py"):
        name = f"{name}.py"
    return f"{prefix}{name}"


def build_unified_diff(original: str, fixed: str, filename: str) -> str:
    """Create a unified diff for display and download."""

    fixed_name = build_download_filename(filename)
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile=filename,
            tofile=fixed_name,
        )
    )


def _line_indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _detect_division_by_parameter(source: str) -> tuple[str | None, int | None]:
    """Detect a simple function parameter used as a denominator."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None

    for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
        param_names = {arg.arg for arg in function.args.args}
        for node in ast.walk(function):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Name):
                if node.right.id in param_names:
                    insert_line = function.body[0].lineno if function.body else function.lineno + 1
                    return node.right.id, insert_line
    return None, None


def _insert_zero_guard(source: str, parameter: str, insert_line: int) -> str:
    lines = source.splitlines()
    index = max(insert_line - 1, 0)
    base_indent = _line_indent(lines[index]) if index < len(lines) else "    "
    guard = [
        f"{base_indent}if {parameter} == 0:",
        f'{base_indent}    raise ValueError("{parameter} must not be zero")',
    ]
    updated = lines[:index] + guard + lines[index:]
    return "\n".join(updated) + ("\n" if source.endswith("\n") else "")


def _detect_len_without_none_guard(source: str) -> tuple[str | None, int | None]:
    """Detect a simple len(parameter) use that may fail for None input."""

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, None

    for function in [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]:
        param_names = {arg.arg for arg in function.args.args}
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.Name) and first_arg.id in param_names:
                    insert_line = function.body[0].lineno if function.body else function.lineno + 1
                    return first_arg.id, insert_line
    return None, None


def _insert_none_guard(source: str, parameter: str, insert_line: int) -> str:
    lines = source.splitlines()
    index = max(insert_line - 1, 0)
    base_indent = _line_indent(lines[index]) if index < len(lines) else "    "
    guard = [
        f"{base_indent}if {parameter} is None:",
        f"{base_indent}    return 0",
    ]
    updated = lines[:index] + guard + lines[index:]
    return "\n".join(updated) + ("\n" if source.endswith("\n") else "")


def _syntax_error_result(source: str, filename: str, provider: str, error: SyntaxError) -> InteractiveReviewResult:
    explanation = f"Python syntax error detected at line {error.lineno}: {error.msg}."
    fixed = source
    patch = build_unified_diff(source, fixed, filename)
    return InteractiveReviewResult(
        filename=filename,
        provider=provider,
        bug_found=True,
        issue_type="syntax_error",
        confidence=0.90,
        explanation=explanation,
        fixed_source=fixed,
        patch=patch,
        changed=False,
    )


def review_python_source(source: str, filename: str = "uploaded.py", provider: str = "local-controlled") -> InteractiveReviewResult:
    """Review one Python source file and produce a suggested fixed version.

    The current implementation is deterministic so the dissertation demo remains
    repeatable. It recognises a small set of common runtime-risk patterns and
    returns no issue when those patterns are not found.
    """

    try:
        ast.parse(source)
    except SyntaxError as exc:
        return _syntax_error_result(source, filename, provider, exc)

    divisor, insert_line = _detect_division_by_parameter(source)
    if divisor and insert_line:
        fixed = _insert_zero_guard(source, divisor, insert_line)
        patch = build_unified_diff(source, fixed, filename)
        return InteractiveReviewResult(
            filename=filename,
            provider=provider,
            bug_found=True,
            issue_type="possible_zero_division",
            confidence=0.78,
            explanation=(
                f"The function divides by parameter '{divisor}' without checking whether it is zero. "
                "The suggested fix adds an explicit guard before the division."
            ),
            fixed_source=fixed,
            patch=patch,
            changed=fixed != source,
        )

    name, insert_line = _detect_len_without_none_guard(source)
    if name and insert_line:
        fixed = _insert_none_guard(source, name, insert_line)
        patch = build_unified_diff(source, fixed, filename)
        return InteractiveReviewResult(
            filename=filename,
            provider=provider,
            bug_found=True,
            issue_type="possible_none_len_error",
            confidence=0.72,
            explanation=(
                f"The function calls len({name}) without checking whether '{name}' is None. "
                "The suggested fix adds a None guard before calling len()."
            ),
            fixed_source=fixed,
            patch=patch,
            changed=fixed != source,
        )

    return InteractiveReviewResult(
        filename=filename,
        provider=provider,
        bug_found=False,
        issue_type="no_supported_issue_detected",
        confidence=0.60,
        explanation="No issue was detected by the supported single-file review checks.",
        fixed_source=source,
        patch=build_unified_diff(source, source, filename),
        changed=False,
    )


def build_review_markdown(result: InteractiveReviewResult) -> str:
    """Create a Markdown review report for download."""

    lines = [
        "# File Review Notes",
        "",
        f"- File: `{result.filename}`",
        f"- Provider: `{result.provider}`",
        f"- Bug found: `{result.bug_found}`",
        f"- Issue type: `{result.issue_type}`",
        f"- Confidence: `{result.confidence}`",
        f"- Changed: `{result.changed}`",
        f"- Validation status: `{result.validation_status}`",
        "",
        "## Explanation",
        "",
        result.explanation,
        "",
        "## Recommended update",
        "",
        "```diff",
        result.patch or "No code changes proposed.",
        "```",
        "",
        "## Note",
        "",
        "This file-only check does not run the full project test suite.",
        "",
    ]
    return "\n".join(lines)


def write_interactive_review_artifacts(
    result: InteractiveReviewResult,
    *,
    original_source: str,
    output_dir: str | Path,
) -> dict[str, str]:
    """Write original, fixed, diff and report artifacts for the UI mode."""

    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    original_name = Path(result.filename).name or "uploaded.py"
    fixed_name = build_download_filename(result.filename)

    original_path = base / original_name
    fixed_path = base / fixed_name
    diff_path = base / "suggested_patch.diff"
    json_path = base / "interactive_review_result.json"
    txt_path = base / "interactive_review_result.txt"
    md_path = base / "interactive_review_result.md"

    original_path.write_text(original_source, encoding="utf-8")
    fixed_path.write_text(result.fixed_source, encoding="utf-8")
    diff_path.write_text(result.patch, encoding="utf-8")
    json_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown = build_review_markdown(result)
    md_path.write_text(markdown, encoding="utf-8")
    txt_path.write_text(_markdown_to_text(markdown), encoding="utf-8")

    return {
        "original_file": str(original_path),
        "fixed_file": str(fixed_path),
        "patch_diff": str(diff_path),
        "json_report": str(json_path),
        "txt_report": str(txt_path),
        "markdown_report": str(md_path),
    }


def _markdown_to_text(markdown: str) -> str:
    text = markdown.replace("```diff", "").replace("```", "")
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("# ", "").replace("## ", "")
    return text
