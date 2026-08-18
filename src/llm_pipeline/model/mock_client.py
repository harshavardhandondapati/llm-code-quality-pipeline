"""A deterministic model client used for repeatable dissertation testing."""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from llm_pipeline.utils.official_fixes import checkout_bugsinpy_fixed_project


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model_name: str
    task: str
    content: dict[str, Any]
    raw_text: str


class MockLLMClient:
    """Return stable responses without calling an external API."""

    def __init__(self, model_name: str = "mock-model") -> None:
        self.model_name = model_name

    def complete(self, prompt: Mapping[str, Any]) -> ModelResponse:
        task = str(prompt.get("task", ""))
        if task == "bug_detection":
            content = self._bug_detection(prompt)
        elif task == "fix_generation":
            content = self._fix_generation(prompt)
        else:
            content = {"message": "Unsupported mock task", "task": task}
        return ModelResponse(
            provider="mock",
            model_name=self.model_name,
            task=task,
            content=content,
            raw_text=json.dumps(content, indent=2),
        )

    def _bug_detection(self, prompt: Mapping[str, Any]) -> dict[str, Any]:
        text = self._prompt_text(prompt)
        project = prompt.get("metadata", {}).get("project")

        if project == "httpie" and "downloads.py" in text:
            return {
                "bug_found": True,
                "file_path": "httpie/downloads.py",
                "function_name": "get_unique_filename",
                "line_start": None,
                "line_end": None,
                "explanation": (
                    "The download filename is taken from the Content-Disposition header "
                    "without keeping it inside the filesystem filename length limit."
                ),
                "confidence": 0.82,
            }

        if project == "Chart" and str(prompt.get("metadata", {}).get("bug_id")) == "1":
            return {
                "bug_found": True,
                "file_path": "source/org/jfree/chart/renderer/category/AbstractCategoryItemRenderer.java",
                "function_name": "getLegendItems",
                "line_start": None,
                "line_end": None,
                "explanation": (
                    "The renderer legend-item generation does not correctly handle the indexed dataset/series "
                    "case used by the triggering AbstractCategoryItemRenderer test."
                ),
                "confidence": 0.80,
            }

        if "return a / b" in text:
            return {
                "bug_found": True,
                "file_path": prompt.get("metadata", {}).get("file_path", "uploaded_file.py"),
                "function_name": "divide",
                "line_start": None,
                "line_end": None,
                "explanation": "The function can raise ZeroDivisionError when b is zero.",
                "confidence": 0.76,
            }

        return {
            "bug_found": False,
            "file_path": None,
            "function_name": None,
            "line_start": None,
            "line_end": None,
            "explanation": "No clear bug pattern was found by the deterministic mock provider.",
            "confidence": 0.55,
        }

    def _fix_generation(self, prompt: Mapping[str, Any]) -> dict[str, Any]:
        text = self._prompt_text(prompt)
        project = prompt.get("metadata", {}).get("project")

        if project == "httpie" and str(prompt.get("metadata", {}).get("bug_id")) == "1" and "downloads.py" in text:
            return self._fix_bugsinpy_httpie_1(prompt)

        if project == "Chart" and str(prompt.get("metadata", {}).get("bug_id")) == "1":
            return self._fix_defects4j_chart_1(prompt)

        if "return a / b" in text:
            original = self._extract_uploaded_code(text)
            fixed = original.replace("return a / b", "return None if b == 0 else a / b")
            patch = self._diff("uploaded_file.py", original, fixed)
            return {
                "patch": patch,
                "explanation": "Guard the division so a zero denominator does not raise an exception.",
                "files_modified": ["uploaded_file.py"],
                "fixed_files": {"uploaded_file.py": fixed},
            }

        return {
            "patch": "",
            "explanation": "No fix was generated because no clear bug was detected.",
            "files_modified": [],
            "fixed_files": {},
        }

    @staticmethod
    def _prompt_text(prompt: Mapping[str, Any]) -> str:
        return "\n".join(str(message.get("content", "")) for message in prompt.get("messages", []))

    @staticmethod
    def _extract_snippet(text: str, file_path: str) -> str:
        marker = f"--- {file_path}"
        start = text.find(marker)
        if start == -1:
            return ""
        after_header = text.find("---\n", start)
        if after_header == -1:
            after_header = text.find("\n", start)
        else:
            after_header += 4
        rest = text[after_header:] if after_header != -1 else text[start:]
        next_marker = rest.find("\n--- ")
        return rest[:next_marker].rstrip() + "\n" if next_marker != -1 else rest.rstrip() + "\n"

    @staticmethod
    def _extract_uploaded_code(text: str) -> str:
        marker = "Uploaded code:\n"
        if marker in text:
            return text.split(marker, 1)[1].rstrip() + "\n"
        return text.rstrip() + "\n"

    def _fix_bugsinpy_httpie_1(self, prompt: Mapping[str, Any]) -> dict[str, Any]:
        """Use the official BugsInPy fixed version as deterministic mock repair evidence."""
        relative_path = "httpie/downloads.py"
        project_path = Path(str(prompt.get("metadata", {}).get("project_path", ""))).expanduser()
        original_file = project_path / relative_path
        if not original_file.is_file():
            return {
                "patch": "",
                "explanation": "BugsInPy httpie-1 source file was not found in the checked-out project.",
                "files_modified": [],
                "fixed_files": {},
            }

        fixed_project, message = checkout_bugsinpy_fixed_project(
            buggy_project_path=project_path,
            project="httpie",
            bug_id="1",
            timeout_seconds=1200,
        )
        if fixed_project is None:
            return {
                "patch": "",
                "explanation": "Could not checkout official fixed BugsInPy httpie-1 version for mock repair. " + message,
                "files_modified": [],
                "fixed_files": {},
            }

        fixed_file = fixed_project / relative_path
        if not fixed_file.is_file():
            return {
                "patch": "",
                "explanation": f"Official fixed BugsInPy httpie-1 file was missing: {fixed_file}",
                "files_modified": [],
                "fixed_files": {},
            }

        original = original_file.read_text(encoding="utf-8", errors="replace")
        fixed = fixed_file.read_text(encoding="utf-8", errors="replace")
        patch = self._diff(relative_path, original, fixed)

        return {
            "patch": patch,
            "explanation": (
                "Deterministic Python mock repair for BugsInPy httpie-1. The mock uses the official fixed "
                "benchmark version to validate checkout, patch application, compile, triggering-test, metrics "
                "and reporting stages without calling OpenRouter."
            ),
            "files_modified": [relative_path],
            "fixed_files": {relative_path: fixed},
            "repair_source": "mock_bugsinpy_official_fixed_version",
        }

    def _fix_defects4j_chart_1(self, prompt: Mapping[str, Any]) -> dict[str, Any]:
        """Use the official Defects4J fixed version as deterministic mock repair evidence."""
        relative_path = "source/org/jfree/chart/renderer/category/AbstractCategoryItemRenderer.java"
        project_path = Path(str(prompt.get("metadata", {}).get("project_path", ""))).expanduser()

        original_file = project_path / relative_path
        if not original_file.is_file():
            return {
                "patch": "",
                "explanation": "Chart 1 source file was not found in the checked-out project.",
                "files_modified": [],
                "fixed_files": {},
            }

        fixed_root = project_path.parent / "_mock_official_fixed_Chart_1"
        fixed_file = fixed_root / relative_path

        if not fixed_file.is_file():
            defects4j = self._defects4j_command()
            if not defects4j:
                return {
                    "patch": "",
                    "explanation": "Defects4J command was not available for mock fixed-version checkout.",
                    "files_modified": [],
                    "fixed_files": {},
                }

            shutil.rmtree(fixed_root, ignore_errors=True)
            completed = subprocess.run(
                [defects4j, "checkout", "-p", "Chart", "-v", "1f", "-w", str(fixed_root)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
            if completed.returncode != 0 or not fixed_file.is_file():
                return {
                    "patch": "",
                    "explanation": "Could not checkout official fixed Chart 1 version for mock repair. " + completed.stdout[-800:],
                    "files_modified": [],
                    "fixed_files": {},
                }

        original = original_file.read_text(encoding="utf-8", errors="replace")
        fixed = fixed_file.read_text(encoding="utf-8", errors="replace")
        patch = self._diff(relative_path, original, fixed)

        return {
            "patch": patch,
            "explanation": (
                "Deterministic Java mock repair for Defects4J Chart 1. The mock uses the official fixed "
                "benchmark version to validate the Java checkout, patch, compile, triggering-test, metrics "
                "and reporting stages without calling OpenRouter."
            ),
            "files_modified": [relative_path],
            "fixed_files": {relative_path: fixed},
            "repair_source": "mock_defects4j_official_fixed_version",
        }

    @staticmethod
    def _defects4j_command() -> str | None:
        configured_dir = os.environ.get("PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY", "").strip()
        if configured_dir:
            candidate = Path(configured_dir) / "defects4j"
            if candidate.exists():
                return str(candidate)

        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("PIPELINE_DEFECTS4J_EXECUTABLE_DIRECTORY="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    candidate = Path(value) / "defects4j"
                    if candidate.exists():
                        return str(candidate)

        found = shutil.which("defects4j")
        return found

    @staticmethod
    def _diff(path: str, original: str, fixed: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                fixed.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
