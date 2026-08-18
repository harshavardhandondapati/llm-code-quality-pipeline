"""Small file-based job store for running benchmark cases outside the Streamlit request."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TERMINAL_STATUSES = {"successful", "failed", "interrupted"}


def utc_now() -> str:
    """Return an ISO timestamp for job metadata."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def jobs_root(project_root: Path | str | None = None) -> Path:
    """Return the local job store folder."""
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    path = root / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_file(job_id: str, project_root: Path | str | None = None) -> Path:
    """Return the JSON status file for one job."""
    return jobs_root(project_root) / f"{job_id}.json"


def write_job(job: dict[str, Any], project_root: Path | str | None = None) -> dict[str, Any]:
    """Write one job status document."""
    job.setdefault("updated_at_utc", utc_now())
    path = job_file(str(job["job_id"]), project_root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return job


def read_job(job_id: str, project_root: Path | str | None = None) -> dict[str, Any] | None:
    """Read one job status document."""
    path = job_file(job_id, project_root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_jobs(project_root: Path | str | None = None, *, limit: int = 25) -> list[dict[str, Any]]:
    """Return recent jobs, newest first."""
    jobs: list[dict[str, Any]] = []
    for path in sorted(jobs_root(project_root).glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        jobs.append(refresh_job_status(payload, project_root))
        if len(jobs) >= limit:
            break
    return sorted(jobs, key=lambda item: str(item.get("created_at_utc", "")), reverse=True)


def _process_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def refresh_job_status(job: dict[str, Any], project_root: Path | str | None = None) -> dict[str, Any]:
    """Mark stale running jobs as interrupted when their process disappeared."""
    status = str(job.get("status") or "").lower()
    if status not in {"queued", "running"}:
        return job

    pid_value = job.get("pid")
    try:
        pid = int(pid_value) if pid_value is not None else None
    except (TypeError, ValueError):
        pid = None

    if pid is not None and _process_is_running(pid):
        return job

    # The worker might have finished and updated the file between listing and now.
    latest = read_job(str(job.get("job_id")), project_root)
    if latest and str(latest.get("status") or "").lower() not in {"queued", "running"}:
        return latest

    job["status"] = "interrupted"
    job["successful"] = False
    job["updated_at_utc"] = utc_now()
    job["message"] = "The worker process stopped before writing a final result. Check deployment logs and rerun the job."
    write_job(job, project_root)
    return job


def start_pipeline_job(
    *,
    dataset: str,
    project: str,
    bug_id: str,
    provider: str,
    model_name: str,
    allow_local_fallback: bool,
    reviewer: str = "web-ui",
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Start a benchmark run in a background Python process."""
    root = Path(project_root or Path.cwd()).expanduser().resolve()
    job_id = datetime.now(timezone.utc).strftime("job_%Y%m%d_%H%M%S_") + uuid4().hex[:8]
    root_jobs = jobs_root(root)
    stdout_file = root_jobs / f"{job_id}.stdout.log"
    stderr_file = root_jobs / f"{job_id}.stderr.log"

    job = {
        "job_id": job_id,
        "status": "queued",
        "successful": None,
        "dataset": dataset,
        "project": project,
        "bug_id": str(bug_id),
        "provider": provider,
        "model_name": model_name,
        "allow_local_fallback": bool(allow_local_fallback),
        "reviewer": reviewer,
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "stdout_log": str(stdout_file),
        "stderr_log": str(stderr_file),
        "message": "Queued for execution.",
    }
    write_job(job, root)

    command = [
        sys.executable,
        "scripts/run_pipeline_job.py",
        "--job-id",
        job_id,
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PIPELINE_ALLOW_LOCAL_FALLBACK"] = "true" if allow_local_fallback else "false"

    out_handle = stdout_file.open("w", encoding="utf-8")
    err_handle = stderr_file.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=env,
            stdout=out_handle,
            stderr=err_handle,
            text=True,
            start_new_session=True,
        )
    finally:
        out_handle.close()
        err_handle.close()

    job["pid"] = process.pid
    job["status"] = "running"
    job["message"] = "Benchmark run started in the background."
    write_job(job, root)
    return job


def read_log_tail(path_value: str | None, *, max_chars: int = 6000) -> str:
    """Read the last part of a job log file."""
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-max_chars:]
