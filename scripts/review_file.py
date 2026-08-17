"""Review one Python file and write a suggested fixed version."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


def _add_src_to_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


_add_src_to_path()

from llm_pipeline.ui import review_python_source, write_interactive_review_artifacts  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run single-file code review.")
    parser.add_argument("file", help="Python file to review.")
    parser.add_argument("--output-root", default="interactive_reviews")
    parser.add_argument("--provider", default="local-controlled")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    review_path = Path(args.file)
    source = review_path.read_text(encoding="utf-8")

    result = review_python_source(source, filename=review_path.name, provider=args.provider)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_root) / f"review_{timestamp}_{review_path.stem}"
    artifacts = write_interactive_review_artifacts(result, original_source=source, output_dir=output_dir)

    print("Interactive Code Review")
    print("=======================")
    print(f"File: {result.filename}")
    print(f"Bug found: {result.bug_found}")
    print(f"Issue type: {result.issue_type}")
    print(f"Changed: {result.changed}")
    print(f"Fixed file: {artifacts['fixed_file']}")
    print(f"Patch diff: {artifacts['patch_diff']}")
    print(f"Review report: {artifacts['markdown_report']}")


if __name__ == "__main__":
    main()
