"""Run the full pipeline for one benchmark bug."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _add_src_to_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


_add_src_to_path()

from llm_pipeline.datasets.factory import SUPPORTED_DATASETS  # noqa: E402
from llm_pipeline.workflow import run_final_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the full dissertation pipeline.")
    parser.add_argument("--dataset", default="bugsinpy", choices=SUPPORTED_DATASETS)
    parser.add_argument("--project", default="httpie")
    parser.add_argument("--bug-id", default="1")
    parser.add_argument("--provider", default="mock", choices=["mock", "openrouter"])
    parser.add_argument("--model", default=None, help="Model name, for example mock-model or openrouter/free")
    parser.add_argument(
        "--approval",
        default="pending",
        choices=["pending", "approved", "rejected", "needs_changes"],
        help="Human review decision. Omit this option to leave the run awaiting review.",
    )
    parser.add_argument("--reviewer", default="", help="Reviewer name for a completed decision.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_final_pipeline(
        dataset=args.dataset,
        project=args.project,
        bug_id=args.bug_id,
        provider=args.provider,
        model_name=args.model,
        approval=args.approval,
        reviewer=args.reviewer,
    )
    print("Pipeline run completed")
    print(f"dataset: {result.get('dataset')}")
    print(f"language: {result.get('language')}")
    print(f"project: {result['project']}")
    print(f"bug_id: {result['bug_id']}")
    print(f"provider: {result.get('provider')}")
    print(f"model_name: {result.get('model_name')}")
    print(f"overall_status: {result['overall_status']}")
    print(f"successful: {result['successful']}")
    print(f"workspace_path: {result['workspace_path']}")
    print(f"candidate_report: {result['candidate_report']}")
    if not result["successful"]:
        print("failed_steps:")
        for step in result.get("steps", []):
            if step.get("status") != "passed":
                print(f"- {step.get('name')}: {step.get('status')}")


if __name__ == "__main__":
    main()
