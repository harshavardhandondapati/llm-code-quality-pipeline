"""Save model responses and parsed result files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from llm_pipeline.model.mock_client import ModelResponse


def save_model_outputs(response: ModelResponse, output_directory: Path | str, prefix: str) -> tuple[Path, Path, Path, Path]:
    """Save raw and parsed model outputs."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)

    raw_json = output / f"{prefix}_model_response_raw.json"
    raw_txt = output / f"{prefix}_model_response_raw.txt"
    result_json = output / f"{prefix}_result.json"
    result_txt = output / f"{prefix}_result.txt"

    raw_payload = {
        "provider": response.provider,
        "model_name": response.model_name,
        "task": response.task,
        "raw_text": response.raw_text,
    }
    raw_json.write_text(json.dumps(raw_payload, indent=2) + "\n", encoding="utf-8")
    raw_txt.write_text(response.raw_text + "\n", encoding="utf-8")
    result_json.write_text(json.dumps(response.content, indent=2) + "\n", encoding="utf-8")
    result_txt.write_text(_as_text(response.content), encoding="utf-8")
    return raw_json, raw_txt, result_json, result_txt


def _as_text(payload: Mapping[str, Any]) -> str:
    lines = []
    for key, value in payload.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"  {sub_key}: {sub_value}")
        else:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"
