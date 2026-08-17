"""Recompute metrics/status for the latest run without calling any LLM API."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_pipeline.evaluation.metrics import create_evaluation_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recompute final metrics for the latest pipeline run without API calls.")
    parser.add_argument("--candidate-report", default="results/bugsinpy_candidate_selection.json")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text_result(path: Path, result: dict[str, Any]) -> None:
    lines = ["End-to-end pipeline result", "===========================", ""]
    for key, value in result.items():
        if key == "steps":
            lines.append("steps:")
            for step in value:
                lines.append(f"- {step['name']}: {step['status']}")
        else:
            lines.append(f"{key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    report_path = Path(args.candidate_report)
    report = _load_json(report_path)
    records = report.get("records") or []
    if not records:
        raise SystemExit("No candidate records found.")
    candidate_record = records[0]
    outputs = Path(candidate_record["workspace_path"]) / "outputs"
    result_file = outputs / "workflow_pipeline_result.json"
    if not result_file.exists():
        raise SystemExit(f"Missing workflow result: {result_file}")
    result = _load_json(result_file)
    metrics = create_evaluation_metrics(candidate_record=candidate_record, outputs_dir=outputs)

    steps = result.get("steps") or []
    for step in steps:
        if step.get("name") == "metrics":
            step["status"] = "passed" if metrics.get("overall_status") == "successful" else "failed"

    result["steps"] = steps
    result["overall_status"] = "successful" if all(step.get("status") == "passed" for step in steps) else "failed"
    result["successful"] = result["overall_status"] == "successful"
    result_file.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (outputs / "workflow_pipeline_result.txt").write_text("", encoding="utf-8")
    _write_text_result(outputs / "workflow_pipeline_result.txt", result)
    (outputs / "pipeline_run_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Pipeline status file: {result_file}")
    print(f"metrics overall_status: {metrics.get('overall_status')}")
    print(f"pipeline overall_status: {result.get('overall_status')}")
    print(f"successful: {result.get('successful')}")


if __name__ == "__main__":
    main()
