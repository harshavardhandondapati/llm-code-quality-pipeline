"""Exit non-zero when the latest pipeline run did not repair the bug."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check latest pipeline run status from candidate report.")
    parser.add_argument("--candidate-report", default="results/bugsinpy_candidate_selection.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_path = Path(args.candidate_report)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    records = report.get("records") or []
    if not records:
        raise SystemExit("No candidate records were found.")
    workspace = Path(records[0]["workspace_path"])
    result_file = workspace / "outputs" / "workflow_pipeline_result.json"
    result = json.loads(result_file.read_text(encoding="utf-8"))

    print(f"Pipeline status file: {result_file}")
    print(f"dataset: {result.get('dataset')}")
    print(f"language: {result.get('language')}")
    print(f"provider: {result.get('provider')}")
    print(f"model_name: {result.get('model_name')}")
    print(f"overall_status: {result.get('overall_status')}")
    print(f"successful: {result.get('successful')}")
    if result.get("successful") is not True:
        print("failed_steps:")
        for step in result.get("steps", []):
            if step.get("status") != "passed":
                print(f"- {step.get('name')}: {step.get('status')}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
