"""Build prompts from the saved source context."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


PROMPT_VERSION = "final-1.3-multilanguage-source-focused"

_ENVIRONMENT_NOISE_PATTERNS = (
    "_pytest/",
    "_pytest\\",
    "importerror",
    "mutablemapping",
    "userdict",
    "python 3.10",
    "site-packages",
    "pytest runner",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _snippet_text(source_context: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for snippet in source_context.get("snippets", []):
        path = snippet.get("file_path", "unknown")
        start = snippet.get("start_line", 1)
        end = snippet.get("end_line", start)
        content = snippet.get("content", "")
        parts.append(f"--- {path} lines {start}-{end} ---\n{content}")
    return "\n\n".join(parts)


def _list_text(items: Sequence[Any] | None) -> str:
    values = [str(item) for item in items or [] if str(item).strip()]
    return "\n".join(f"- {item}" for item in values) if values else "- None supplied"


def _additional_context(source_context: Mapping[str, Any]) -> Mapping[str, Any]:
    data = source_context.get("additional_context") or {}
    return data if isinstance(data, Mapping) else {}


def _selected_files(source_context: Mapping[str, Any]) -> list[str]:
    context = _additional_context(source_context)
    selected = context.get("selected_files") or []
    if isinstance(selected, str):
        selected = [selected]
    if not isinstance(selected, list):
        selected = []
    return [str(item) for item in selected if str(item).strip()]



_PYTHON_MODULE_REFERENCE = re.compile(
    r"<module\s+['\"](?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)['\"]>",
    re.IGNORECASE,
)

_FAILURE_SIGNAL_PATTERN = re.compile(
    r"(?:\b[A-Za-z_]\w*(?:Error|Exception)\b|"
    r"does not have the attribute|"
    r"failing tests?:|"
    r"assert(?:ion)?\s*error|"
    r"\bexpected\b|\bactual\b|"
    r"java\.lang\.)",
    re.IGNORECASE,
)


def _failure_signal_lines(output: str, *, limit: int = 16) -> list[str]:
    """Keep concise defect signals from otherwise noisy benchmark output."""
    selected: list[str] = []
    seen: set[str] = set()

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not (
            _PYTHON_MODULE_REFERENCE.search(line)
            or _FAILURE_SIGNAL_PATTERN.search(line)
        ):
            continue
        if line not in seen:
            seen.add(line)
            selected.append(line)
        if len(selected) >= limit:
            break

    for match in _PYTHON_MODULE_REFERENCE.finditer(output):
        module_name = match.group("module")
        probable_path = module_name.replace(".", "/") + ".py"
        note = (
            f"Observed Python module reference: {module_name} "
            f"(probable project source path: {probable_path})"
        )
        if note not in seen:
            seen.add(note)
            selected.append(note)
        if len(selected) >= limit:
            break

    return selected[:limit]


def _file_localisation_paths(source_context: Mapping[str, Any]) -> list[str]:
    additional = _additional_context(source_context)
    files = additional.get("file_localisation_guidance") or []
    if isinstance(files, str):
        files = [files]
    if not isinstance(files, list):
        return []
    return [str(item).strip() for item in files if str(item).strip()]


def _file_localisation_for_prompt(source_context: Mapping[str, Any]) -> str:
    """Render the file-level scope and bounded candidate source for real LLMs."""
    additional = _additional_context(source_context)
    files = _file_localisation_paths(source_context)
    sources = additional.get("file_localisation_source") or {}
    if not files:
        return ""

    lines = [
        "File-level repair scope:",
        "The benchmark supplies the following candidate application source file path(s):",
    ]
    lines.extend(f"- {path}" for path in files)
    lines.extend(
        [
            "Use these paths as the repair scope and return one of them in file_path.",
            "Determine the defective function, faulty logic and repair yourself from the buggy source and failing-test evidence.",
            "No method name, faulty line, expected code change, official patch or fixed source is supplied as guidance.",
        ]
    )

    if isinstance(sources, Mapping):
        for path in files:
            content = str(sources.get(path) or "")
            if not content:
                continue
            lines.extend(
                [
                    "",
                    f"--- candidate buggy source: {path} ---",
                    content,
                    f"--- end candidate buggy source: {path} ---",
                ]
            )
    return "\n".join(lines)


def _failure_output_for_prompt(source_context: Mapping[str, Any], *, real_llm: bool) -> str:
    """Return concise failure evidence plus optional file-level repair scope."""
    output = str(source_context.get("failure_output", ""))
    if not real_llm:
        return output

    lowered = output.lower()
    noisy = any(pattern in lowered for pattern in _ENVIRONMENT_NOISE_PATTERNS)

    if noisy:
        message = (
            "The full baseline output is saved in the evidence files. Verbose test-runner "
            "or dependency output has been reduced below while retaining concise signals "
            "from the reproduced buggy execution."
        )
        signals = _failure_signal_lines(output)
        if signals:
            message += "\n\nObserved failure signal(s):\n" + "\n".join(
                f"- {signal}" for signal in signals
            )
    else:
        message = output[:4000]

    file_scope = _file_localisation_for_prompt(source_context)
    if file_scope:
        message = (message.rstrip() + "\n\n" + file_scope).strip()

    return message.strip()



def _benchmark_guidance(
    source_context: Mapping[str, Any],
    *,
    retry: bool = False,
    forced_focus: bool = False,
) -> str:
    selected = _selected_files(source_context)
    language = str(source_context.get("language", "source-code"))
    guidance = [
        "Benchmark and validation guidance:",
        f"- The baseline failure has already been accepted as a reproducible {language} benchmark application bug.",
        "- The raw test output may include test-runner, dependency, Python, Java, Maven or Gradle noise; do not use that as the final diagnosis when project source indicates an application defect.",
        "- Do not classify the issue as a pytest, Python-version, Java-version, dependency, Maven, Gradle, or test-runner problem unless supplied project source proves there is no application defect.",
        "- Do not propose fixes to test frameworks, virtual environments, build tools or dependency versions unless supplied project source proves there is no application defect.",
        "- Focus on the checked-out project source code and the triggering test behaviour.",
        "- A generated repair will be accepted only if it applies to project files and passes the triggering tests.",
    ]
    file_scope = _file_localisation_paths(source_context)
    if file_scope:
        guidance.append(
            "- File-level benchmark scope is supplied for this repair task; "
            "return file_path as one of the listed candidate files and localise the defective logic within it."
        )
        guidance.extend(f"  - {item}" for item in file_scope)
    if selected:
        guidance.append("- Source-context file(s) supplied to you:")
        guidance.extend(f"  - {item}" for item in selected)
    if retry:
        guidance.extend(
            [
                "- This is a retry because the previous response treated the failure as environment noise.",
                "- Reconsider the application source snippets and return the most likely project-code defect.",
            ]
        )
    if forced_focus:
        guidance.extend(
            [
                "- This final guided attempt must localise the application defect, not the environment noise.",
                "- Return bug_found as true for the benchmark application defect and identify the candidate project file.",
            ]
        )
    return "\n".join(guidance)


def build_bug_detection_prompt(
    source_context: Mapping[str, Any],
    *,
    real_llm: bool = False,
    retry: bool = False,
    forced_focus: bool = False,
) -> dict[str, Any]:
    """Create the bug-detection prompt payload."""
    instructions = [
        "Review the source snippets and benchmark guidance. Return a structured bug-detection result.",
        "Identify the application source-code defect that explains the benchmark failure.",
    ]
    if real_llm:
        instructions.append(_benchmark_guidance(source_context, retry=retry, forced_focus=forced_focus))
    failure_output = _failure_output_for_prompt(source_context, real_llm=real_llm)
    user_content = (
        "\n\n".join(instructions)
        + "\n\n"
        f"Project: {source_context.get('project')}\n"
        f"Bug ID: {source_context.get('bug_id')}\n\n"
        "Failing tests:\n"
        + _list_text(source_context.get("failing_tests", []))
        + "\n\nFailure output / prompt-safe summary:\n"
        + failure_output
        + "\n\nSource snippets:\n"
        + _snippet_text(source_context)
        + _focused_file_block(source_context)
        + _validation_feedback_block(source_context)
    )
    language = str(source_context.get("language", "source-code"))
    system = (
        f"You are reviewing a reproducible {language} application bug from a benchmark dataset. "
        "The benchmark has already accepted that the buggy project version fails. "
        "Your task is to localise the application source-code defect, not to diagnose the test environment. "
        "Return only valid JSON and no markdown."
    )
    return {
        "task": "bug_detection",
        "prompt_version": PROMPT_VERSION,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "metadata": {
            "project": source_context.get("project"),
            "bug_id": source_context.get("bug_id"),
            "language": source_context.get("language", "python"),
            "real_llm": real_llm,
            "retry": retry,
            "forced_focus": forced_focus,
        },
    }


def _validation_feedback_block(source_context: Mapping[str, Any]) -> str:
    additional = source_context.get("additional_context", {})
    if not isinstance(additional, Mapping):
        return ""
    feedback = additional.get("previous_validation_feedback")
    if not feedback:
        return ""
    return (
        "\n\nPrevious patch validation feedback. The next patch must fix this failure.\n"
        f"{feedback}\n"
    )


def _focused_file_block(source_context: Mapping[str, Any]) -> str:
    additional = source_context.get("additional_context", {})
    if not isinstance(additional, Mapping):
        return ""

    path = additional.get("focused_file_path")
    content = additional.get("focused_file_content")
    if not path or not content:
        return ""

    if additional.get("focused_file_is_complete", True):
        heading = (
            "Complete affected source file for repair. If you use fixed_files, return the "
            "complete corrected content for this same relative path."
        )
    else:
        start = additional.get("focused_file_line_start")
        end = additional.get("focused_file_line_end")
        function_name = str(additional.get("focused_file_function_name") or "").strip()
        anchor = additional.get("focused_file_anchor")

        if anchor == "function_name" and function_name:
            focus = f" around the detected function {function_name}"
        else:
            focus = ""

        heading = (
            f"Focused affected source excerpt for repair{focus} (lines {start}-{end}). "
            "This is not the complete file, so return a unified diff rather than fixed_files. "
            "Treat the earlier bug-detection explanation as a hypothesis: verify it against "
            "this source and the failing test, and do not invent code that is not present."
        )

    return (
        f"\n\n{heading}\n"
        f"--- {path} ---\n{content}\n--- end {path} ---"
    )


def build_fix_generation_prompt(
    source_context: Mapping[str, Any],
    bug_detection: Mapping[str, Any],
    *,
    real_llm: bool = False,
    retry: bool = False,
) -> dict[str, Any]:
    """Create the fix-generation prompt payload."""
    affected_path = str(bug_detection.get("file_path") or "").strip()
    fix_instructions = [
        "Generate a minimal repair for the detected application bug.",
        "Only modify project source files. Do not modify tests, test frameworks, virtual environments, build tools, or dependency versions unless the bug evidence explicitly requires it.",
        "Return one valid JSON object only. Do not use markdown. The assistant message content must not be null.",
        "The JSON must contain patch, explanation, files_modified and fixed_files.",
        "Use fixed_files only when the complete affected file is provided. When the repair context is an excerpt, return a unified diff instead.",
        "If you provide a patch, it must be a unified diff that can be applied with git apply, using paths like a/path/to/File.ext and b/path/to/File.ext.",
    ]
    if affected_path:
        fix_instructions.append(f"The affected relative file path is {affected_path}. Do not modify another path.")
    if real_llm:
        fix_instructions.append(_benchmark_guidance(source_context, forced_focus=True))
    if retry:
        fix_instructions.append(
            "This is a retry because the previous provider response did not include a usable patch. "
            "Return a non-empty fixed_files object with the complete corrected affected file content."
        )
    failure_output = _failure_output_for_prompt(source_context, real_llm=real_llm)
    user_content = (
        "\n".join(fix_instructions)
        + "\n\n"
        f"Project: {source_context.get('project')}\n"
        f"Bug ID: {source_context.get('bug_id')}\n"
        f"Bug found: {bug_detection.get('bug_found')}\n"
        f"Affected file: {bug_detection.get('file_path')}\n"
        f"Function: {bug_detection.get('function_name')}\n"
        f"Explanation: {bug_detection.get('explanation')}\n\n"
        "Failure output / prompt-safe summary:\n"
        + failure_output
        + "\n\nSource snippets:\n"
        + _snippet_text(source_context)
        + _focused_file_block(source_context)
        + _validation_feedback_block(source_context)
    )
    language = str(source_context.get("language", "source-code"))
    system = (
        f"You generate small, reviewable patches for {language} benchmark application bugs. "
        "Return only valid JSON and no markdown. "
        "Do not return an empty patch when benchmark guidance identifies an application source-code defect."
    )
    return {
        "task": "fix_generation",
        "prompt_version": PROMPT_VERSION,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "metadata": {
            "project": source_context.get("project"),
            "bug_id": source_context.get("bug_id"),
            "language": source_context.get("language", "python"),
            "real_llm": real_llm,
            "retry": retry,
        },
    }


def save_prompt(prompt: Mapping[str, Any], output_directory: Path | str, name: str) -> tuple[Path, Path]:
    """Save a prompt as JSON and readable text."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / f"{name}.json"
    text_path = output / f"{name}.txt"
    json_path.write_text(json.dumps(prompt, indent=2) + "\n", encoding="utf-8")
    lines = [f"Task: {prompt.get('task')}", f"Version: {prompt.get('prompt_version')}", ""]
    for message in prompt.get("messages", []):
        lines.append(f"[{message.get('role')}]\n{message.get('content')}\n")
    text_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, text_path


def load_source_context(path: Path | str) -> dict[str, Any]:
    return _read_json(Path(path))
