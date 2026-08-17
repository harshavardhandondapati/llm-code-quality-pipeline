"""Prepare a small, traceable source context from a failed test run."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from llm_pipeline.context.file_discovery import FileDiscovery
from llm_pipeline.exceptions import ContextBuildError
from llm_pipeline.schemas import (
    BaselineReproductionResult,
    BugCase,
    CommandResult,
    SourceContext,
    SourceContextBuildResult,
    SourceSnippet,
)


@dataclass(slots=True)
class _Candidate:
    path: Path
    priority: int
    reasons: list[str] = field(default_factory=list)
    line_numbers: set[int] = field(default_factory=set)


class SourceContextBuilder:
    """Select relevant files and keep the resulting context within a fixed budget."""

    _TRACEBACK_PATTERN = re.compile(
        r"File\s+[\"'](?P<path>[^\"']+\.(?:py|java))[\"'],\s+line\s+(?P<line>\d+)",
        re.IGNORECASE,
    )
    _TEST_LOCATION_PATTERN = re.compile(
        r"(?P<path>(?:[A-Za-z]:)?[^\s:\"']*?\.(?:py|java|xml|gradle|kts)):(?P<line>\d+)(?::\d+)?",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        file_discovery: FileDiscovery | None = None,
        max_source_characters: int = 50_000,
        max_files: int = 5,
        context_lines_before: int = 20,
        context_lines_after: int = 20,
        max_failure_output_characters: int = 12_000,
        use_benchmark_hints: bool = False,
    ) -> None:
        if max_source_characters < 1_000:
            raise ValueError("max_source_characters must be at least 1000")
        if max_files < 1:
            raise ValueError("max_files must be at least 1")
        if context_lines_before < 0 or context_lines_after < 0:
            raise ValueError("context line counts cannot be negative")
        if max_failure_output_characters < 500:
            raise ValueError("max_failure_output_characters must be at least 500")

        self.file_discovery = file_discovery or FileDiscovery()
        self.max_source_characters = max_source_characters
        self.max_files = max_files
        self.context_lines_before = context_lines_before
        self.context_lines_after = context_lines_after
        self.max_failure_output_characters = max_failure_output_characters
        self.use_benchmark_hints = use_benchmark_hints

    def build(
        self,
        bug_case: BugCase,
        test_result: CommandResult,
    ) -> SourceContext:
        """Build one context from a checked-out project and its failed test output."""
        project_root = bug_case.workspace_path.expanduser().resolve()
        if not project_root.is_dir():
            raise ContextBuildError(f"Checked-out project folder does not exist: {project_root}")

        complete_failure_output = self._combine_output(test_result)
        failure_output, output_was_truncated = self._limit_failure_output(
            complete_failure_output
        )
        candidates = self._collect_candidates(
            project_root,
            bug_case,
            complete_failure_output,
        )

        snippets: list[SourceSnippet] = []
        selection_reasons: dict[str, list[str]] = {}
        remaining_characters = self.max_source_characters

        ordered_candidates = sorted(
            candidates.values(),
            key=lambda item: (
                item.priority,
                self.file_discovery.relative_path(project_root, item.path),
            ),
        )

        for candidate in ordered_candidates:
            slots_left = self.max_files - len(snippets)
            if slots_left <= 0 or remaining_characters <= 0:
                break

            # For benchmark-guided real-LLM runs, changed source files are the most
            # important context. Give them the remaining budget before secondary
            # files so the relevant function is not accidentally truncated.
            if self.use_benchmark_hints and "listed in benchmark changed-file metadata" in candidate.reasons:
                file_budget = remaining_characters
            else:
                # Sharing the remaining budget prevents the first large fallback file
                # from taking all of the space needed for later files.
                file_budget = max(1, remaining_characters // slots_left)
            snippet = self._create_snippet(
                project_root,
                candidate,
                file_budget,
            )
            if snippet is None:
                continue

            snippets.append(snippet)
            remaining_characters -= len(snippet.content)
            selection_reasons[snippet.file_path] = list(candidate.reasons)

        if not snippets:
            raise ContextBuildError(
                "No readable Python source files or configured source files were found for the selected project."
            )

        total_source_characters = sum(len(snippet.content) for snippet in snippets)
        changed_files = bug_case.metadata.get("changed_files", [])
        if isinstance(changed_files, str):
            changed_files = [changed_files]
        if not isinstance(changed_files, list):
            changed_files = []
        changed_files = [str(item) for item in changed_files if str(item).strip()]
        return SourceContext(
            project=bug_case.project,
            bug_id=bug_case.bug_id,
            language=bug_case.language,
            failure_output=failure_output,
            failing_tests=bug_case.triggering_tests,
            snippets=snippets,
            additional_context={
                "context_version": "1.3-multilanguage",
                "selected_files": [snippet.file_path for snippet in snippets],
                "selection_reasons": selection_reasons,
                "source_character_count": total_source_characters,
                "source_character_limit": self.max_source_characters,
                "failure_output_truncated": output_was_truncated,
                "benchmark_hints_used": self.use_benchmark_hints,
                "benchmark_changed_files": changed_files,
                "real_llm_candidate_files": changed_files if self.use_benchmark_hints else [],
            },
        )

    def build_from_baseline(
        self,
        baseline: BaselineReproductionResult,
        output_directory: Path | str,
    ) -> SourceContextBuildResult:
        """Build and save context directly from a Batch 3 baseline result."""
        if baseline.test_result is None:
            raise ContextBuildError(
                "Source context cannot be built because the baseline test was not run."
            )

        context = self.build(
            baseline.checkout.bug_case,
            baseline.test_result,
        )
        return self.save(context, output_directory)

    def save(
        self,
        context: SourceContext,
        output_directory: Path | str,
    ) -> SourceContextBuildResult:
        """Save a machine-readable file and a simple text file for manual review."""
        output_path = Path(output_directory).expanduser().resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        json_file = output_path / "source_context.json"
        text_file = output_path / "source_context.txt"
        json_file.write_text(
            json.dumps(context.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        text_file.write_text(self._as_text(context), encoding="utf-8")

        return SourceContextBuildResult(
            context=context,
            json_file=json_file,
            text_file=text_file,
        )

    def _collect_candidates(
        self,
        project_root: Path,
        bug_case: BugCase,
        failure_output: str,
    ) -> OrderedDict[str, _Candidate]:
        candidates: OrderedDict[str, _Candidate] = OrderedDict()

        # For real-LLM runs, benchmark changed-file metadata is used as localisation
        # guidance. Add those files first so dependency/test-runner traceback noise
        # cannot consume the source-context budget.
        if self.use_benchmark_hints:
            changed_files = bug_case.metadata.get("changed_files", [])
            if isinstance(changed_files, str):
                changed_files = [changed_files]
            for changed_file in changed_files:
                self._add_candidate(
                    candidates,
                    project_root,
                    str(changed_file),
                    priority=0,
                    reason="listed in benchmark changed-file metadata",
                )

        for triggering_test in bug_case.triggering_tests:
            self._add_candidate(
                candidates,
                project_root,
                triggering_test,
                priority=1,
                reason="listed as a triggering test",
            )
            if bug_case.language.lower() == "java":
                self._add_java_triggering_test_candidate(
                    candidates,
                    project_root,
                    bug_case,
                    triggering_test,
                )

        for raw_path, line_number in self._extract_failure_locations(failure_output):
            self._add_candidate(
                candidates,
                project_root,
                raw_path,
                priority=2,
                reason="referenced in failing-test output",
                line_number=line_number,
            )

        discovered_files = self.file_discovery.discover(project_root)
        for path in sorted(discovered_files, key=self._fallback_sort_key):
            self._add_resolved_candidate(
                candidates,
                project_root,
                path,
                priority=3,
                reason="selected by project file discovery",
            )

        return candidates

    def _add_java_triggering_test_candidate(
        self,
        candidates: OrderedDict[str, _Candidate],
        project_root: Path,
        bug_case: BugCase,
        triggering_test: str,
    ) -> None:
        """Resolve Defects4J Java test selectors such as package.Class::method."""
        if "::" not in triggering_test:
            return

        class_name, method_name = triggering_test.split("::", 1)
        class_name = class_name.strip()
        method_name = method_name.strip()
        if not class_name or not method_name:
            return

        source_dir = str(bug_case.metadata.get("dir.src.tests", "tests")).strip().strip("/")
        relative = f"{source_dir}/{class_name.replace('.', '/')}.java"
        path = self.file_discovery.resolve_project_file(project_root, relative)
        if path is None:
            return

        line_number = self._find_java_method_line(path, method_name)
        self._add_resolved_candidate(
            candidates,
            project_root,
            path,
            priority=0,
            reason="resolved from Defects4J triggering test selector",
            line_number=line_number,
        )

    @staticmethod
    def _find_java_method_line(path: Path, method_name: str) -> int | None:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None

        pattern = re.compile(r"\b" + re.escape(method_name) + r"\s*\(")
        for index, line in enumerate(lines, start=1):
            if pattern.search(line):
                return index
        return None


    def _add_candidate(
        self,
        candidates: OrderedDict[str, _Candidate],
        project_root: Path,
        raw_path: str,
        *,
        priority: int,
        reason: str,
        line_number: int | None = None,
    ) -> None:
        path = self.file_discovery.resolve_project_file(project_root, raw_path)
        if path is None:
            return
        self._add_resolved_candidate(
            candidates,
            project_root,
            path,
            priority=priority,
            reason=reason,
            line_number=line_number,
        )

    def _add_resolved_candidate(
        self,
        candidates: OrderedDict[str, _Candidate],
        project_root: Path,
        path: Path,
        *,
        priority: int,
        reason: str,
        line_number: int | None = None,
    ) -> None:
        key = self.file_discovery.relative_path(project_root, path)
        existing = candidates.get(key)
        if existing is None:
            existing = _Candidate(path=path, priority=priority)
            candidates[key] = existing
        else:
            existing.priority = min(existing.priority, priority)

        if reason not in existing.reasons:
            existing.reasons.append(reason)
        if line_number is not None and line_number > 0:
            existing.line_numbers.add(line_number)

    def _create_snippet(
        self,
        project_root: Path,
        candidate: _Candidate,
        character_budget: int,
    ) -> SourceSnippet | None:
        try:
            lines = candidate.path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return None

        if not lines:
            return None

        if candidate.line_numbers:
            first_reference = min(candidate.line_numbers)
            last_reference = max(candidate.line_numbers)
            start_index = max(0, first_reference - 1 - self.context_lines_before)
            end_index = min(
                len(lines),
                last_reference + self.context_lines_after,
            )
        else:
            start_index = 0
            end_index = len(lines)

        selected_lines = lines[start_index:end_index]
        content_lines: list[str] = []
        used_characters = 0
        for line in selected_lines:
            additional = len(line) + 1
            if content_lines and used_characters + additional > character_budget:
                break
            if not content_lines and additional > character_budget:
                content_lines.append(line[:character_budget])
                used_characters = len(content_lines[0])
                break
            content_lines.append(line)
            used_characters += additional

        if not content_lines:
            return None

        actual_end_line = start_index + len(content_lines)
        return SourceSnippet(
            file_path=self.file_discovery.relative_path(project_root, candidate.path),
            content="\n".join(content_lines),
            start_line=start_index + 1,
            end_line=actual_end_line,
        )

    @classmethod
    def _extract_failure_locations(cls, output: str) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        seen: set[tuple[str, int]] = set()
        for pattern in (cls._TRACEBACK_PATTERN, cls._TEST_LOCATION_PATTERN):
            for match in pattern.finditer(output):
                item = (match.group("path"), int(match.group("line")))
                if item not in seen:
                    seen.add(item)
                    found.append(item)
        return found

    @staticmethod
    def _combine_output(test_result: CommandResult) -> str:
        parts = [part.strip() for part in (test_result.stdout, test_result.stderr) if part.strip()]
        return "\n\n".join(parts) if parts else "No test output was captured."

    def _limit_failure_output(self, output: str) -> tuple[str, bool]:
        if len(output) <= self.max_failure_output_characters:
            return output, False
        tail = output[-self.max_failure_output_characters :]
        return "[Earlier test output was omitted.]\n" + tail, True

    @staticmethod
    def _fallback_sort_key(path: Path) -> tuple[int, str]:
        parts = {part.lower() for part in path.parts}
        is_test = path.name.startswith("test_") or "tests" in parts or "test" in parts
        return (1 if is_test else 0, path.as_posix())

    @staticmethod
    def _as_text(context: SourceContext) -> str:
        lines = [
            f"Project: {context.project}",
            f"Bug ID: {context.bug_id}",
            f"Language: {context.language}",
            "",
            "Failing tests:",
        ]
        lines.extend(f"- {test}" for test in context.failing_tests)
        if not context.failing_tests:
            lines.append("- None recorded")

        lines.extend(["", "Test output:", context.failure_output, "", "Source snippets:"])
        for snippet in context.snippets:
            lines.extend(
                [
                    "",
                    f"--- {snippet.file_path} (lines {snippet.start_line}-{snippet.end_line}) ---",
                    snippet.content,
                ]
            )
        return "\n".join(lines) + "\n"
