"""Show a short summary of the latest pipeline result."""

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

from llm_pipeline.ui import build_dashboard_summary  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show the final pipeline result summary.")
    parser.add_argument("--candidate-report", default="results/bugsinpy_candidate_selection.json")
    parser.add_argument("--candidate-index", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_dashboard_summary(args.candidate_report, args.candidate_index)

    print("LLM Code Quality Pipeline - Result Summary")
    print("==========================================")
    print(f"Dataset: {summary.dataset}")
    print(f"Language: {summary.language}")
    print(f"Project: {summary.project}")
    print(f"Bug ID: {summary.bug_id}")
    print(f"Candidate status: {summary.candidate_status}")
    print(f"Baseline failure observed: {summary.baseline_failure_observed}")
    print(f"Bug detected: {summary.bug_found}")
    print(f"Patch applied: {summary.patch_applied}")
    print(f"Compilation passed: {summary.compilation_passed}")
    print(f"Triggering tests passed: {summary.triggering_tests_passed}")
    print(f"Human approval: {summary.human_decision}")
    print(f"Overall status: {summary.overall_status}")
    print(f"Evidence folder: {summary.outputs_dir}")


if __name__ == "__main__":
    main()
