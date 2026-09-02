"""OpenRouter model client using the OpenAI-compatible chat completions API."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping, Sequence

from llm_pipeline.model.mock_client import ModelResponse

Transport = Callable[[dict[str, Any], dict[str, str], float], dict[str, Any]]


class OpenRouterLLMClient:
    """Call OpenRouter and normalise the response into the pipeline schema."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "openrouter/free",
        base_url: str = "https://openrouter.ai/api/v1/chat/completions",
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
        timeout_seconds: int = 120,
        transport: Transport | None = None,
    ) -> None:
        if not api_key or api_key.strip() in {"your_api_key_here", "replace_me"}:
            raise ValueError("OpenRouter API key is required. Set PIPELINE_OPENROUTER_API_KEY in .env.")
        self.api_key = api_key.strip()
        self.model_name = model_name
        self.base_url = base_url
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def complete(self, prompt: Mapping[str, Any]) -> ModelResponse:
        """Send one prompt to OpenRouter and return a normalised model response."""
        task = str(prompt.get("task", ""))
        messages = self._build_messages(prompt)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_output_tokens,
        }
        if task in {"bug_detection", "fix_generation"}:
            # Ask OpenRouter for a final JSON answer and avoid saving reasoning-only
            # responses as the final assistant content. OpenRouter documents JSON
            # response_format and a reasoning.exclude flag for supported providers.
            payload["response_format"] = {"type": "json_object"}
            payload["reasoning"] = {"exclude": True}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/llm-code-quality-pipeline",
            "X-Title": "LLM Code Quality Pipeline",
        }

        started = time.perf_counter()
        response_payload = self._transport(payload, headers, self.timeout_seconds) if self._transport else self._post(payload, headers)
        elapsed = time.perf_counter() - started

        raw_text = self._extract_message_text(response_payload)
        content = self._parse_task_content(raw_text, task)
        content.setdefault("model_execution_time_seconds", round(elapsed, 3))

        return ModelResponse(
            provider="openrouter",
            model_name=self.model_name,
            task=task,
            content=content,
            raw_text=raw_text,
        )

    def _post(self, payload: Mapping[str, Any], headers: Mapping[str, str]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base_url, data=data, headers=dict(headers), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - user supplied API endpoint is controlled by settings
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenRouter API request failed with HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenRouter API request failed: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"OpenRouter returned non-JSON response: {body[:500]}") from exc

    @staticmethod
    def _extract_message_text(payload: Mapping[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, Sequence) or not choices:
            raise RuntimeError(f"OpenRouter response did not contain choices: {payload}")
        first = choices[0]
        if not isinstance(first, Mapping):
            raise RuntimeError(f"OpenRouter choice had unexpected format: {first}")
        message = first.get("message", {})
        if not isinstance(message, Mapping):
            raise RuntimeError(f"OpenRouter message had unexpected format: {message}")
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, Mapping) and "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(str(item))
            joined = "\n".join(parts).strip()
            if joined:
                return joined
        elif content not in (None, ""):
            return str(content)

        # Some OpenRouter providers can return null final content and place useful
        # text in reasoning fields. Preserve that text when present; otherwise save
        # the full provider payload instead of the misleading string "None".
        for key in ("reasoning", "reasoning_content"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        details = message.get("reasoning_details")
        if isinstance(details, Sequence):
            parts = []
            for item in details:
                if isinstance(item, Mapping):
                    text = item.get("text") or item.get("summary")
                    if text:
                        parts.append(str(text))
            if parts:
                return "\n".join(parts).strip()

        return json.dumps(payload, indent=2)

    def _build_messages(self, prompt: Mapping[str, Any]) -> list[dict[str, str]]:
        task = str(prompt.get("task", ""))
        original_messages = prompt.get("messages", [])
        messages: list[dict[str, str]] = []
        for message in original_messages if isinstance(original_messages, list) else []:
            if isinstance(message, Mapping):
                role = str(message.get("role", "user"))
                content = str(message.get("content", ""))
                messages.append({"role": role, "content": content})

        schema_instruction = self._schema_instruction(task)
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] = messages[0]["content"].rstrip() + "\n\n" + schema_instruction
        else:
            messages.insert(0, {"role": "system", "content": schema_instruction})
        return messages

    @staticmethod
    def _schema_instruction(task: str) -> str:
        if task == "bug_detection":
            return (
                "Return only one valid JSON object. Do not use markdown. "
                "Use exactly these keys: bug_found, file_path, function_name, line_start, line_end, "
                "explanation, confidence. file_path/function_name/line_start/line_end may be null. "
                "confidence must be a number from 0 to 1. "
                "Do not set bug_found to false only because the failure output contains pytest, import, "
                "dependency, or Python-version noise; inspect the supplied application source snippets first."
            )
        if task == "fix_generation":
            return (
                "Return only one valid JSON object. Do not use markdown outside JSON. "
                "Use exactly these keys: patch, explanation, files_modified, fixed_files. "
                "patch must be a unified diff that can be applied with git apply, using paths such as "
                "a/httpie/downloads.py and b/httpie/downloads.py. files_modified must be a list of paths. "
                "fixed_files may be an empty object unless a complete replacement file is supplied. "
                "Do not return an empty patch if an application source-code defect is indicated."
            )
        return "Return only one valid JSON object. Do not use markdown."

    def _parse_task_content(self, text: str, task: str) -> dict[str, Any]:
        parsed = self._extract_json_object(text)
        if isinstance(parsed, Mapping) and isinstance(parsed.get("result"), Mapping):
            parsed = parsed["result"]
        if not isinstance(parsed, Mapping):
            if task == "fix_generation" and self._looks_like_diff(text):
                return {
                    "patch": self._clean_diff(text),
                    "explanation": "OpenRouter returned a unified diff without JSON wrapping.",
                    "files_modified": self._files_from_diff(text),
                    "fixed_files": {},
                }
            return self._parse_failure(task, text)

        if task == "bug_detection":
            return self._normalise_bug_detection(parsed)
        if task == "fix_generation":
            return self._normalise_fix_generation(parsed, text)
        return dict(parsed)

    @classmethod
    def _extract_json_object(cls, text: str) -> Any:
        cleaned = cls._strip_code_fence(text).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = cleaned[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines)
        return stripped

    @staticmethod
    def _normalise_bug_detection(payload: Mapping[str, Any]) -> dict[str, Any]:
        file_path = payload.get("file_path")
        function_name = payload.get("function_name")
        explanation = str(payload.get("explanation") or payload.get("reasoning") or "No explanation returned.")
        bug_found = payload.get("bug_found")
        if bug_found is None:
            bug_found = bool(file_path or payload.get("bug") or payload.get("issue"))
        return {
            "bug_found": bool(bug_found),
            "file_path": str(file_path) if file_path not in (None, "") else None,
            "function_name": str(function_name) if function_name not in (None, "") else None,
            "line_start": OpenRouterLLMClient._optional_int(payload.get("line_start")),
            "line_end": OpenRouterLLMClient._optional_int(payload.get("line_end")),
            "explanation": explanation,
            "confidence": OpenRouterLLMClient._confidence(payload.get("confidence")),
        }

    @staticmethod
    def _normalise_fix_generation(payload: Mapping[str, Any], raw_text: str) -> dict[str, Any]:
        patch = payload.get("patch") or payload.get("diff") or ""
        patch_text = OpenRouterLLMClient._clean_diff(str(patch)) if patch else ""
        fixed_files = payload.get("fixed_files") or {}
        if not isinstance(fixed_files, Mapping):
            fixed_files = {}
        files_modified = payload.get("files_modified") or payload.get("changed_files") or []
        if isinstance(files_modified, str):
            files_modified = [files_modified]
        if not isinstance(files_modified, list):
            files_modified = []
        if not files_modified and patch_text:
            files_modified = OpenRouterLLMClient._files_from_diff(patch_text)
        if not patch_text and OpenRouterLLMClient._looks_like_diff(raw_text):
            patch_text = OpenRouterLLMClient._clean_diff(raw_text)
            if not files_modified:
                files_modified = OpenRouterLLMClient._files_from_diff(patch_text)
        return {
            "patch": patch_text,
            "explanation": str(payload.get("explanation") or "OpenRouter generated a candidate repair."),
            "files_modified": [str(item) for item in files_modified],
            "fixed_files": {str(key): str(value) for key, value in fixed_files.items()},
        }

    @staticmethod
    def _parse_failure(task: str, text: str) -> dict[str, Any]:
        if task == "bug_detection":
            return {
                "bug_found": False,
                "file_path": None,
                "function_name": None,
                "line_start": None,
                "line_end": None,
                "explanation": "OpenRouter response could not be parsed as the required JSON schema.",
                "confidence": 0.0,
                "parse_error": True,
                "raw_preview": text[:1000],
            }
        if task == "fix_generation":
            return {
                "patch": "",
                "explanation": "OpenRouter response could not be parsed as the required JSON schema.",
                "files_modified": [],
                "fixed_files": {},
                "parse_error": True,
                "raw_preview": text[:1000],
            }
        return {"parse_error": True, "raw_preview": text[:1000]}

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, "", "null"):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, parsed))

    @staticmethod
    def _looks_like_diff(text: str) -> bool:
        return "--- a/" in text and "+++ b/" in text and "@@" in text

    @classmethod
    def _clean_diff(cls, text: str) -> str:
        cleaned = cls._strip_code_fence(text).strip()
        if cleaned.startswith("diff"):
            return cleaned + "\n"
        marker = cleaned.find("--- a/")
        if marker != -1:
            return cleaned[marker:].strip() + "\n"
        return cleaned + ("\n" if cleaned else "")

    @staticmethod
    def _files_from_diff(text: str) -> list[str]:
        files: list[str] = []
        for match in re.finditer(r"^\+\+\+\s+b/(.+)$", text, flags=re.MULTILINE):
            path = match.group(1).strip()
            if path and path not in files:
                files.append(path)
        return files
