#!/usr/bin/env python3
"""Worker process used by the Streamlit app to run benchmark cases."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path


def _add_src_to_path() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


_add_src_to_path()

from llm_pipeline.ui.job_store import read_job, write_job, utc_now  # noqa: E402
from llm_pipeline.workflow import run_final_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one pipeline job from a job file.")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    job = read_job(args.job_id)
    if not job:
        raise SystemExit(f"Job file was not found for {args.job_id}")

    job["status"] = "running"
    job["message"] = "Running benchmark checkout, baseline reproduction, LLM repair and validation."
    job["updated_at_utc"] = utc_now()
    write_job(job)

    try:
        result = run_final_pipeline(
            dataset=str(job["dataset"]),
            project=str(job["project"]),
            bug_id=str(job["bug_id"]),
            provider=str(job["provider"]),
            model_name=str(job["model_name"]),
            approval="approved",
            reviewer=str(job.get("reviewer") or "web-ui"),
        )
        job["result"] = result
        job["successful"] = bool(result.get("successful"))
        job["status"] = "successful" if result.get("successful") else "failed"
        job["workspace_path"] = result.get("workspace_path")
        job["candidate_report"] = result.get("candidate_report")
        job["message"] = "Run completed successfully." if result.get("successful") else "Run completed with failed checks."
        job["updated_at_utc"] = utc_now()
        write_job(job)
        return 0 if result.get("successful") else 2
    except Exception as exc:  # pragma: no cover - subprocess guard
        job["status"] = "failed"
        job["successful"] = False
        job["message"] = str(exc)
        job["traceback"] = traceback.format_exc()
        job["updated_at_utc"] = utc_now()
        write_job(job)
        print(job["traceback"], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
