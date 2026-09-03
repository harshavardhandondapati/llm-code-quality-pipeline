"""Apply a generated patch and run post-fix checks."""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from llm_pipeline.datasets.base import DatasetAdapter
from llm_pipeline.datasets.bugsinpy import classify_bugsinpy_test_result
from llm_pipeline.schemas import CommandResult, DatasetCheckoutResult


def apply_generated_patch(
    *,
    checkout: DatasetCheckoutResult,
    fix_result: Mapping[str, Any],
    adapter: DatasetAdapter,
    outputs_dir: Path | str,
    allowed_files: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Apply the LLM-generated change and rerun the benchmark checks.

    Source snapshots are saved before and after patching so the UI can compare
    the exact buggy file with the exact LLM-updated file. These snapshots are
    evidence only; they are not used to generate or repair the patch.
    """
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    project_root = checkout.bug_case.workspace_path

    patch_text = _normalise_patch_text(str(fix_result.get("patch", "")))
    target_files = _changed_file_candidates(fix_result, patch_text)
    _save_source_snapshots(project_root, target_files, outputs, "original")

    raw_patch_file = outputs / "model_patch_raw.diff"
    raw_patch_file.write_text(patch_text, encoding="utf-8")

    clean_patch_text = _clean_llm_patch_text(patch_text) or patch_text
    patch_file = outputs / "applied_patch.diff"
    patch_file.write_text(clean_patch_text, encoding="utf-8")

    scope_violation = _repair_scope_violation(
        fix_result=fix_result,
        patch_text=clean_patch_text,
        allowed_files=allowed_files,
    )
    if scope_violation:
        validation = {
            "patch_applied": False,
            "patch_strategy": None,
            "already_applied": False,
            "compilation_passed": False,
            "triggering_tests_passed": False,
            "validation_scope": "triggering_tests",
            "changed_files": target_files,
            "failure_reason": scope_violation,
        }
        (outputs / "post_patch_compile.json").write_text(
            json.dumps(
                {"skipped": True, "reason": scope_violation},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        write_validation(outputs, validation)
        return validation

    patch_applied = _apply_fixed_files(project_root, fix_result)
    patch_strategy = "fixed_files" if patch_applied else None

    if (
        not patch_applied
        and clean_patch_text.strip()
        and _diff_targets_are_existing_files(project_root, clean_patch_text)
    ):
        patch_applied = _apply_git_patch(project_root, patch_file)
        patch_strategy = "git_apply" if patch_applied else None

    if not patch_applied and clean_patch_text.strip():
        patch_applied = _apply_llm_patch_by_search(project_root, clean_patch_text)
        patch_strategy = "llm_diff_search_apply" if patch_applied else None

    _save_source_snapshots(project_root, target_files, outputs, "updated")
    if patch_applied:
        _write_clean_evidence_diff(outputs, target_files)

    if not patch_applied:
        (outputs / "post_patch_compile.json").write_text(
            json.dumps(
                {"skipped": True, "reason": "Patch was not applied; compile was not run."},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        validation = {
            "patch_applied": False,
            "patch_strategy": patch_strategy,
            "already_applied": False,
            "compilation_passed": False,
            "triggering_tests_passed": False,
            "validation_scope": "triggering_tests",
            "changed_files": target_files,
            "failure_reason": "Patch could not be applied.",
        }
        write_validation(outputs, validation)
        return validation

    compile_result = _compile_after_patch(
        checkout=checkout,
        adapter=adapter,
        project_root=project_root,
        target_files=target_files,
    )
    test_result = adapter.run_triggering_tests(checkout) if compile_result.succeeded else None

    compile_log = outputs / "post_patch_compile.json"
    compile_log.write_text(
        json.dumps(compile_result.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    if test_result:
        (outputs / "post_patch_triggering_test.json").write_text(
            json.dumps(test_result.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )

    validation = {
        "patch_applied": True,
        "patch_strategy": patch_strategy,
        "already_applied": False,
        "compilation_passed": compile_result.succeeded,
        "triggering_tests_passed": bool(
            test_result and _test_output_passed(test_result, dataset=checkout.bug_case.dataset)
        ),
        "validation_scope": "triggering_tests",
        "changed_files": target_files,
        "failure_reason": None,
    }
    if not validation["patch_applied"]:
        validation["failure_reason"] = "Patch could not be applied."
    elif not validation["compilation_passed"]:
        validation["failure_reason"] = "Project did not compile after the patch."
    elif not validation["triggering_tests_passed"]:
        validation["failure_reason"] = "Triggering tests still failed after the patch."

    write_validation(outputs, validation)
    return validation

def write_validation(outputs: Path, validation: Mapping[str, Any]) -> None:
    """Persist the validation result after optional local retries/enrichment."""
    (outputs / "validation_result.json").write_text(
        json.dumps(validation, indent=2) + "\n",
        encoding="utf-8",
    )
    (outputs / "validation_result.txt").write_text(_validation_text(validation), encoding="utf-8")



def _repair_scope_violation(
    *,
    fix_result: Mapping[str, Any],
    patch_text: str,
    allowed_files: Sequence[str] | None,
) -> str | None:
    """Reject real-model repairs that leave the supplied file-level scope."""
    if not allowed_files:
        return None

    allowed = {
        _clean_relative_path(str(value))
        for value in allowed_files
        if _clean_relative_path(str(value))
    }
    if not allowed:
        return None

    actionable: list[str] = []
    fixed_files = fix_result.get("fixed_files") or {}
    if isinstance(fixed_files, Mapping):
        for value in fixed_files:
            path = _clean_relative_path(str(value))
            if path and path not in actionable:
                actionable.append(path)

    for value in _files_from_unified_diff(patch_text):
        path = _clean_relative_path(str(value))
        if path and path not in actionable:
            actionable.append(path)

    if not actionable:
        for value in fix_result.get("files_modified") or []:
            path = _clean_relative_path(str(value))
            if path and path not in actionable:
                actionable.append(path)

    outside = [path for path in actionable if path not in allowed]
    if outside:
        return (
            "Generated repair targeted file(s) outside the benchmark candidate scope: "
            + ", ".join(outside)
        )
    return None


def _changed_file_candidates(fix_result: Mapping[str, Any], patch_text: str) -> list[str]:
    """Return changed source files mentioned by the LLM result."""
    files: list[str] = []

    for value in fix_result.get("files_modified") or []:
        path = _clean_relative_path(str(value))
        if path and path not in files:
            files.append(path)

    fixed_files = fix_result.get("fixed_files") or {}
    if isinstance(fixed_files, Mapping):
        for value in fixed_files:
            path = _clean_relative_path(str(value))
            if path and path not in files:
                files.append(path)

    for path in _files_from_unified_diff(patch_text):
        if path and path not in files:
            files.append(path)

    return files


def _files_from_unified_diff(patch_text: str) -> list[str]:
    """Extract target file paths from a unified diff."""
    files: list[str] = []
    cleaned = _clean_llm_patch_text(patch_text) or patch_text
    for line in cleaned.splitlines():
        if line.startswith("+++ "):
            path = _clean_relative_path(line[4:].strip())
            if path and path != "/dev/null" and path not in files:
                files.append(path)
    return files


def _clean_relative_path(value: str) -> str:
    """Normalise a project-relative path from diff or model output."""
    path = value.strip().strip('"').replace("\\", "/")
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    while path.startswith("./"):
        path = path[2:]
    return path


def _safe_snapshot_name(relative_path: str) -> str:
    return _clean_relative_path(relative_path).replace("/", "__")


def _save_source_snapshots(project_root: Path, files: list[str], outputs: Path, stage: str) -> None:
    """Copy current source files into outputs/snapshots/<stage>."""
    if not files:
        return

    root = project_root.resolve()
    snapshot_root = outputs / "snapshots" / stage
    manifest: dict[str, str] = {}

    for relative_path in files:
        clean_path = _clean_relative_path(relative_path)
        if not clean_path:
            continue
        source = (project_root / clean_path).resolve()
        if root not in source.parents and source != root:
            continue
        if not source.is_file():
            continue

        destination = snapshot_root / clean_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

        # Legacy flat files keep the Streamlit app simple and readable.
        flat_name = f"{stage}_{Path(clean_path).name}"
        (outputs / flat_name).write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        manifest[clean_path] = str(destination)

    if manifest:
        manifest_file = outputs / "source_snapshots.json"
        existing = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
        existing[stage] = manifest
        manifest_file.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def _write_clean_evidence_diff(outputs: Path, files: list[str]) -> None:
    """Write a readable diff from the saved original and updated snapshots."""
    chunks: list[str] = []
    for relative_path in files:
        clean_path = _clean_relative_path(relative_path)
        original = outputs / "snapshots" / "original" / clean_path
        updated = outputs / "snapshots" / "updated" / clean_path
        if not original.is_file() or not updated.is_file():
            continue
        before = original.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        after = updated.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if before == after:
            continue
        chunks.append(
            "".join(
                difflib.unified_diff(
                    before,
                    after,
                    fromfile=f"a/{clean_path}",
                    tofile=f"b/{clean_path}",
                    n=6,
                )
            )
        )

    if chunks:
        diff_text = "\n".join(chunk.rstrip() for chunk in chunks).rstrip() + "\n"
        (outputs / "applied_patch.diff").write_text(diff_text, encoding="utf-8")
        (outputs / "applied_patch_clean.diff").write_text(diff_text, encoding="utf-8")

def _apply_fixed_files(project_root: Path, fix_result: Mapping[str, Any]) -> bool:
    fixed_files = fix_result.get("fixed_files") or {}
    if not isinstance(fixed_files, Mapping):
        return False

    changed = False
    root = project_root.resolve()
    for relative_path, raw_content in fixed_files.items():
        path_text = str(relative_path).strip()
        if path_text.startswith("a/") or path_text.startswith("b/"):
            path_text = path_text[2:]
        target = (project_root / path_text).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Refusing to write outside project root: {target}")
        if not target.exists():
            continue
        content = _extract_fixed_file_content(raw_content)
        if not content.strip():
            continue
        # Avoid replacing a source module with an explanation or a tiny partial snippet.
        if not _looks_like_supported_source(target, content):
            continue
        target.write_text(content, encoding="utf-8")
        changed = True
    return changed


def _extract_fixed_file_content(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("content", "source", "code", "text"):
            if key in value:
                value = value[key]
                break
    content = str(value)
    content = _strip_code_fence(content)
    return content.rstrip() + "\n"


def _looks_like_supported_source(target: Path, content: str) -> bool:
    """Guard against replacing source files with short prose responses."""
    suffix = target.suffix.lower()
    if suffix == ".py":
        return _looks_like_python_source(content)
    if suffix == ".java":
        return _looks_like_java_source(content)
    return True


def _looks_like_python_source(content: str) -> bool:
    stripped = content.lstrip()
    if stripped.startswith(("import ", "from ", "#", '"""', "'''")):
        return True
    return bool(re.search(r"^\s*def\s+\w+\s*\(", content, flags=re.MULTILINE))


def _looks_like_java_source(content: str) -> bool:
    stripped = content.lstrip()
    if stripped.startswith(("package ", "import ", "//", "/*")):
        return True
    return bool(
        re.search(
            r"^\s*(public|protected|private|abstract|final|static|class|interface|enum)\b",
            content,
            flags=re.MULTILINE,
        )
    )


def _normalise_patch_text(patch_text: str) -> str:
    patch = _strip_code_fence(patch_text).replace("\r\n", "\n")
    # Some models return a JSON string containing escaped newlines as the patch.
    if "\\n" in patch and "\n" not in patch.strip("\n"):
        try:
            patch = json.loads(f'"{patch}"')
        except json.JSONDecodeError:
            pass
    return patch.rstrip() + "\n" if patch.strip() else ""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


def _diff_targets_are_existing_files(project_root: Path, patch_text: str) -> bool:
    """Allow unified diffs only for existing files inside the checkout.

    Benchmark repair tasks modify existing application files. Blocking file
    creation prevents a hallucinated new file from surviving in a reused
    prepared checkout.
    """
    targets = _files_from_unified_diff(patch_text)
    if not targets:
        return False

    root = project_root.resolve()
    for relative in targets:
        target = (project_root / _clean_relative_path(relative)).resolve()
        if root not in target.parents and target != root:
            return False
        if not target.is_file():
            return False
    return True


def _compile_after_patch(
    *,
    checkout: DatasetCheckoutResult,
    adapter: DatasetAdapter,
    project_root: Path,
    target_files: list[str],
) -> CommandResult:
    """Compile a repair without rebuilding a prepared BugsInPy environment.

    ``bugsinpy-compile`` recreates the virtual environment and reinstalls every
    dependency. Once the baseline environment has been prepared and verified,
    Python repairs only need a syntax compilation before the benchmark test is
    rerun. This keeps validation fast and avoids dependency drift.
    """
    if checkout.bug_case.dataset.lower() != "bugsinpy":
        return adapter.compile_project(checkout)

    env_python = project_root / "env" / "bin" / "python"
    python_files: list[str] = []
    root = project_root.resolve()
    for relative in target_files:
        clean = _clean_relative_path(relative)
        target = (project_root / clean).resolve()
        if (
            clean.lower().endswith(".py")
            and root in target.parents
            and target.is_file()
        ):
            python_files.append(str(target))

    if not env_python.is_file() or not python_files:
        return adapter.compile_project(checkout)

    command = [str(env_python), "-m", "py_compile", *python_files]
    completed = subprocess.run(
        command,
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return CommandResult(
        command=command,
        working_directory=project_root,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        execution_time_seconds=0,
    )


def _apply_git_patch(project_root: Path, patch_file: Path) -> bool:
    if not patch_file.read_text(encoding="utf-8", errors="replace").strip():
        return False

    command_sets = [
        ["git", "apply", "--check", str(patch_file)],
        ["git", "apply", "--check", "--whitespace=fix", str(patch_file)],
    ]
    apply_sets = [
        ["git", "apply", str(patch_file)],
        ["git", "apply", "--whitespace=fix", str(patch_file)],
    ]

    for check_cmd, apply_cmd in zip(command_sets, apply_sets):
        check = subprocess.run(
            check_cmd,
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode == 0:
            applied = subprocess.run(
                apply_cmd,
                cwd=project_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if applied.returncode == 0:
                return True

    # Last resort for simple unified diffs produced without exact git headers.
    patch_cmd = ["patch", "-p1", "-i", str(patch_file)]
    patched = subprocess.run(
        patch_cmd,
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return patched.returncode == 0


def _apply_llm_patch_by_search(project_root: Path, patch_text: str) -> bool:
    """Apply LLM unified diffs by matching source context instead of hunk line numbers.

    This uses only the LLM-generated patch text. It does not use official benchmark
    fixed files and does not use local fallback repair.
    """
    cleaned_patch = _clean_llm_patch_text(patch_text)
    hunks_by_file = _parse_unified_diff_hunks(cleaned_patch)
    if not hunks_by_file:
        return False

    root = project_root.resolve()
    changed_any = False

    for relative_path, hunks in hunks_by_file.items():
        clean_path = relative_path.strip()
        if clean_path.startswith("a/") or clean_path.startswith("b/"):
            clean_path = clean_path[2:]

        target = (project_root / clean_path).resolve()
        if root not in target.parents and target != root:
            return False
        if not target.is_file():
            return False

        content = target.read_text(encoding="utf-8", errors="replace")
        original_content = content

        for old_block, new_block in hunks:
            old_block = _normalise_patch_block(old_block)
            new_block = _normalise_patch_block(new_block)

            if old_block == new_block:
                continue

            if old_block in content:
                content = content.replace(old_block, new_block, 1)
                changed_any = True
                continue

            if _apply_single_line_change_with_context(target, old_block, new_block):
                content = target.read_text(encoding="utf-8", errors="replace")
                changed_any = True
                continue

            return False

        if content != original_content:
            target.write_text(content, encoding="utf-8")

    return changed_any


def _clean_llm_patch_text(patch_text: str) -> str:
    """Clean raw LLM patch text that may contain escaped newlines or JSON fragments."""
    text = patch_text.strip()

    text = text.replace('\\"', '"')

    lines = text.splitlines()
    cleaned: list[str] = []
    in_diff = False

    for line in lines:
        stripped = line.lstrip()

        if line.startswith("--- ") or line.startswith("+++ ") or line.startswith("@@ "):
            in_diff = True
            cleaned.append(line)
            continue

        if not in_diff:
            continue

        if stripped.startswith('"explanation"') or stripped.startswith('"files_modified"') or stripped.startswith('"fixed_files"') or stripped.startswith('"repair_source"'):
            break

        if stripped in {"}", "},"}:
            break

        if line.startswith((" ", "+", "-")):
            cleaned.append(line)

    return "\n".join(cleaned) + "\n"


def _normalise_patch_block(block: str) -> str:
    """Return parsed source blocks unchanged.

    JSON/string cleanup happens before unified-diff parsing in
    ``_clean_llm_patch_text``. Mutating individual source lines here is unsafe
    because removing a trailing quote can corrupt valid Python docstrings.
    """
    return block


def _apply_single_line_change_with_context(target: Path, old_block: str, new_block: str) -> bool:
    """Apply one changed line using surrounding hunk context to disambiguate matches."""
    content = target.read_text(encoding="utf-8", errors="replace")
    file_lines = content.splitlines(keepends=True)

    old_lines = old_block.splitlines(keepends=True)
    new_lines = new_block.splitlines(keepends=True)

    if len(old_lines) != len(new_lines):
        return False

    changed_indexes = [
        index for index, (old_line, new_line) in enumerate(zip(old_lines, new_lines))
        if old_line != new_line
    ]

    if len(changed_indexes) != 1:
        return False

    changed_index = changed_indexes[0]
    old_line = old_lines[changed_index]
    new_line = new_lines[changed_index]

    candidate_indexes = [
        index for index, line in enumerate(file_lines)
        if line == old_line
    ]

    if not candidate_indexes:
        return False

    for candidate_index in candidate_indexes:
        before_ok = True
        for offset in range(1, changed_index + 1):
            patch_line = old_lines[changed_index - offset]
            file_index = candidate_index - offset
            if file_index < 0 or file_lines[file_index] != patch_line:
                before_ok = False
                break

        after_ok = True
        for offset in range(1, len(old_lines) - changed_index):
            patch_line = old_lines[changed_index + offset]
            file_index = candidate_index + offset
            if file_index >= len(file_lines) or file_lines[file_index] != patch_line:
                after_ok = False
                break

        if before_ok and after_ok:
            file_lines[candidate_index] = new_line
            target.write_text("".join(file_lines), encoding="utf-8")
            return True

    return False


def _parse_unified_diff_hunks(patch_text: str) -> dict[str, list[tuple[str, str]]]:
    """Parse unified diff hunks into old/new source blocks grouped by target file."""
    result: dict[str, list[tuple[str, str]]] = {}

    current_file: str | None = None
    old_lines: list[str] = []
    new_lines: list[str] = []
    in_hunk = False

    def flush_hunk() -> None:
        nonlocal old_lines, new_lines, current_file, in_hunk
        if current_file and in_hunk and (old_lines or new_lines):
            result.setdefault(current_file, []).append(("".join(old_lines), "".join(new_lines)))
        old_lines = []
        new_lines = []
        in_hunk = False

    for raw_line in patch_text.splitlines(keepends=True):
        line = raw_line.rstrip("\n")

        if line.startswith("diff --git "):
            flush_hunk()
            current_file = None
            continue

        if line.startswith("--- "):
            flush_hunk()
            continue

        if line.startswith("+++ "):
            path_text = line[4:].strip()
            if path_text.startswith("b/"):
                path_text = path_text[2:]
            current_file = path_text
            continue

        if line.startswith("@@ "):
            flush_hunk()
            in_hunk = True
            continue

        if not in_hunk or current_file is None:
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            old_lines.append(raw_line[1:])
        elif raw_line.startswith("+") and not raw_line.startswith("+++"):
            new_lines.append(raw_line[1:])
        elif raw_line.startswith(" "):
            old_lines.append(raw_line[1:])
            new_lines.append(raw_line[1:])
        elif raw_line.strip() == "\\ No newline at end of file":
            continue

    flush_hunk()
    return result






def _install_python_project_editable(project_root: Path, outputs: Path) -> None:
    """Reinstall a patched BugsInPy project in editable mode before validation tests.

    Some BugsInPy compile scripts prepare the virtual environment before the
    patch is applied. Reinstalling after the patch ensures triggering tests use
    the patched checkout, not a previously installed copy.
    """
    env_python = project_root / "env" / "bin" / "python"
    log_file = outputs / "post_patch_editable_install.json"

    if not env_python.exists():
        log_file.write_text(
            json.dumps(
                {"skipped": True, "reason": f"No BugsInPy virtualenv python found at {env_python}"},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return

    completed = subprocess.run(
        [str(env_python), "-m", "pip", "install", "--no-deps", "-e", "."],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    result = CommandResult(
        command=[str(env_python), "-m", "pip", "install", "--no-deps", "-e", "."],
        working_directory=project_root,
        return_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        execution_time_seconds=0,
    )
    log_file.write_text(json.dumps(result.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")


def _test_output_passed(result: CommandResult, *, dataset: str | None = None) -> bool:
    """Return True only when the benchmark validation test passed.

    BugsInPy runs Python tests where the process return code is the reliable
    post-patch pass/fail signal. The output may contain generic words like
    "error" in warnings or package messages, so do not reject a successful
    BugsInPy run using broad text matching. Defects4J reports failing test
    counts in output, so keep that check when present.
    """
    if result.timed_out:
        return False

    output = f"{result.stdout}\n{result.stderr}".lower()
    dataset_name = (dataset or "").lower()

    defects4j_match = re.search(r"failing tests:\s*(\d+)", output)
    if defects4j_match:
        return int(defects4j_match.group(1)) == 0

    if dataset_name == "bugsinpy":
        return classify_bugsinpy_test_result(result) == "passed"

    if result.succeeded:
        return True

    failure_markers = [
        "assertionerror",
        "traceback",
        "failures:",
        "errors:",
        " failed",
        "= failed",
        " failure",
        " error",
    ]
    if any(marker in output for marker in failure_markers):
        return False

    return (
        "all tests passed" in output
        or " passed" in output
        or "failing tests: 0" in output
    )

def _validation_text(validation: Mapping[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in validation.items()) + "\n"
