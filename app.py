from __future__ import annotations
import urllib.request
import urllib.error
import tempfile
import subprocess
import shutil
import re
import difflib
"""Streamlit dashboard for the multi-language code quality pipeline."""


import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _add_src_to_path() -> None:
    root = Path(__file__).resolve().parent
    src = root / "src"
    if src.exists():
        sys.path.insert(0, str(src))


_add_src_to_path()

try:
    import streamlit as st
except ModuleNotFoundError as exc:  # pragma: no cover - used only when Streamlit is missing
    raise SystemExit("Install Streamlit with: python -m pip install streamlit") from exc

from llm_pipeline.ui import (  # noqa: E402
    build_code_comparison,
    build_dashboard_summary,
    build_review_markdown,
    review_python_source,
    write_interactive_review_artifacts,
)
from llm_pipeline.ui.job_store import (  # noqa: E402
    list_jobs,
    read_job,
    read_log_tail,
    refresh_job_status,
    start_pipeline_job,
)
from llm_pipeline.ui.benchmark_catalog import (  # noqa: E402
    discover_benchmark_catalog,
    option_count,
    project_names,
)


RUN_OPTIONS = {
    "Python — BugsInPy httpie-1": "results/bugsinpy_candidate_selection.json",
    "Java — Defects4J Chart-1": "results/defects4j_candidate_selection.json",
}

DATASET_LABELS = {
    "bugsinpy": "BugsInPy",
    "defects4j": "Defects4J",
}



def _render_job_workspace_artifacts(job_data: dict) -> None:
    """Show validation files produced by a background benchmark job."""
    result = job_data.get("result") or {}
    workspace_value = job_data.get("workspace_path") or result.get("workspace_path")

    if not workspace_value:
        st.info("No workspace path was recorded for this job.")
        return

    workspace = Path(str(workspace_value))
    outputs = workspace / "outputs"

    st.markdown("### Validation evidence")

    if not outputs.exists():
        st.warning(
            "Workspace outputs are not available. "
            "This can happen if the service restarted or the job finished before evidence was written."
        )
        return

    files_to_show = [
        ("Validation result", outputs / "validation_result.json", "json", True),
        ("Evaluation metrics", outputs / "evaluation_metrics.json", "json", True),
        ("Post-patch compile log", outputs / "post_patch_compile.json", "json", False),
        ("Post-patch editable install log", outputs / "post_patch_editable_install.json", "json", False),
        ("Post-patch triggering test log", outputs / "post_patch_triggering_test.json", "json", True),
        ("Post-fix evaluation", outputs / "post_fix_evaluation.json", "json", False),
        ("Applied patch", outputs / "applied_patch.diff", "diff", True),
        ("Clean applied patch", outputs / "applied_patch_clean.diff", "diff", False),
        ("Bug detection response", outputs / "bug_detection_response.json", "json", False),
        ("Fix generation response", outputs / "fix_generation_response.json", "json", False),
        ("Pipeline result", outputs / "workflow_pipeline_result.json", "json", False),
    ]

    shown = False

    for title, file_path, language, expanded in files_to_show:
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8", errors="replace")
        if len(content) > 50000:
            content = content[:50000] + "\n\n... output truncated in UI ..."

        with st.expander(title, expanded=expanded):
            st.caption(str(file_path))
            if language == "json":
                try:
                    st.json(json.loads(content))
                except Exception:
                    st.code(content, language="json")
            else:
                st.code(content, language=language)

        shown = True

    if not shown:
        st.info("No validation artefacts were found in the workspace outputs folder yet.")


st.set_page_config(page_title="Code Quality Review", page_icon="✓", layout="wide")

st.markdown(
    """
    <style>
    #MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stToolbarActions"],
    [data-testid="stDecoration"], .stDeployButton {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
    }
    .main .block-container {padding-top: 2.2rem; max-width: 1280px;}
    .hero {
        border-radius: 22px;
        padding: 28px 30px;
        background: linear-gradient(135deg, #f6f8ff 0%, #eef9f3 100%);
        border: 1px solid #e7edf8;
        margin-bottom: 18px;
    }
    .hero h1 {margin-bottom: 0.25rem;}
    .muted {color: #667085;}
    .small-muted {color: #667085; font-size: 0.92rem;}
    .card {
        border: 1px solid #e7eaf0;
        border-radius: 16px;
        padding: 18px;
        background: white;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
        min-height: 112px;
    }
    .card-label {color: #667085; font-size: 0.85rem; margin-bottom: 0.35rem;}
    .card-value {font-size: 1.45rem; font-weight: 700; color: #1f2937; line-height: 1.2;}
    .ok-badge, .warn-badge, .bad-badge {
        display: inline-block; padding: 6px 12px; border-radius: 999px; font-weight: 700;
    }
    .ok-badge {background: #eaf8ef; color: #157347;}
    .warn-badge {background: #fff4db; color: #8a5a00;}
    .bad-badge {background: #fdecec; color: #b42318;}
    .soft-panel {border: 1px solid #e7eaf0; border-radius: 16px; padding: 18px; background: #fbfcfe;}
    div[data-testid="stCodeBlock"] {border-radius: 14px;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>Code Quality Review</h1>
      <div class="muted">Review LLM-generated patches, validation evidence, and before/after code changes.</div>
    </div>
    """,
    unsafe_allow_html=True,
)


def _short_text(value: Any, fallback: str = "Not recorded") -> str:
    """Display evidence values safely. False is valid evidence, not missing data."""
    if value is None:
        return fallback
    if value == "":
        return fallback
    if value == []:
        return fallback
    return str(value)



def _metrics_for_summary(summary_data: dict[str, Any]) -> dict[str, Any]:
    """Read evaluation metrics for the loaded run, if available."""
    try:
        outputs = Path(str(summary_data.get("outputs_dir") or ""))
        metrics_file = outputs / "evaluation_metrics.json"
        if metrics_file.exists():
            return json.loads(metrics_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {}


def _evidence_bool(value: Any) -> str:
    """Show booleans in evidence-friendly lowercase form."""
    if value is True or str(value).lower() == "true":
        return "false" if False else "true"
    if value is False or str(value).lower() == "false":
        return "false"
    return "Not recorded"


def _friendly_patch_source(summary_data: dict[str, Any], metrics: dict[str, Any] | None = None) -> str:
    metrics = metrics or {}
    provider = str(summary_data.get("provider") or metrics.get("provider") or "").lower()
    repair_source = str(summary_data.get("repair_source") or metrics.get("repair_source") or "").lower()
    fallback = metrics.get("local_fallback_used", summary_data.get("local_fallback_used"))

    if provider == "mock" or repair_source.startswith("mock"):
        return "Deterministic mock repair"
    if fallback is True or str(fallback).lower() == "true":
        return "Local fallback repair"
    return "LLM-generated patch"


def _friendly_repair_source(summary_data: dict[str, Any], metrics: dict[str, Any] | None = None) -> str:
    metrics = metrics or {}
    value = summary_data.get("repair_source") or metrics.get("repair_source")
    if value not in (None, "", "Not recorded"):
        return str(value)
    return _friendly_patch_source(summary_data, metrics)


def _badge(value: Any, success: str, fail: str = "Needs review") -> str:
    if value is True or str(value).lower() in {"successful", "successful_repair", "passed", "approved"}:
        return f"<span class='ok-badge'>{success}</span>"
    if value is False or str(value).lower() in {"failed", "incomplete", "rejected"}:
        return f"<span class='bad-badge'>{fail}</span>"
    return "<span class='warn-badge'>Not recorded</span>"


def _card(label: str, value: Any) -> None:
    st.markdown(
        f"""
        <div class="card">
          <div class="card-label">{label}</div>
          <div class="card-value">{_short_text(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_run(candidate_report: str, candidate_index: int = 0) -> None:
    summary = build_dashboard_summary(candidate_report, candidate_index)
    comparison = build_code_comparison(candidate_report, candidate_index)

    summary_data = summary.to_dict()
    comparison_data = comparison.to_dict()

    outputs_dir = Path(str(summary_data.get("outputs_dir") or comparison_data.get("outputs_dir") or ""))
    metrics = _read_json_file(outputs_dir / "evaluation_metrics.json")
    workflow = _read_json_file(outputs_dir / "workflow_pipeline_result.json")

    # Add model/run identity to the dashboard data so the reviewer can see
    # exactly which model produced the loaded evidence.
    for key in ["provider", "model_name", "workspace_path", "candidate_report"]:
        summary_data[key] = workflow.get(key) or metrics.get(key) or summary_data.get(key)

    summary_data["local_fallback_used"] = metrics.get("local_fallback_used", summary_data.get("local_fallback_used"))
    summary_data["repair_source"] = metrics.get("repair_source", summary_data.get("repair_source"))
    summary_data["target_runtime"] = metrics.get("target_runtime", summary_data.get("target_runtime"))
    summary_data["total_known_execution_time_seconds"] = metrics.get(
        "total_known_execution_time_seconds",
        summary_data.get("total_known_execution_time_seconds"),
    )

    st.session_state["dashboard_summary"] = summary_data
    st.session_state["code_comparison"] = comparison_data
    st.session_state["candidate_report_path"] = candidate_report
    st.session_state["candidate_index"] = candidate_index


def _changed_excerpt(source: str, diff_text: str, *, context: int = 9) -> str:
    """Return a compact excerpt around the changed lines."""
    if not source.strip() or not diff_text.strip():
        return source

    changed_lines: list[int] = []
    old_line = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            try:
                old_part = line.split()[1]
                old_line = max(int(old_part.split(",")[0].replace("-", "")) - 1, 0)
            except Exception:
                old_line = 0
            continue
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            changed_lines.append(max(old_line, 1))
            old_line += 1
        elif line.startswith("+"):
            continue
        else:
            old_line += 1

    if not changed_lines:
        return source

    lines = source.splitlines()
    start = max(min(changed_lines) - context - 1, 0)
    end = min(max(changed_lines) + context, len(lines))
    prefix = "...\n" if start > 0 else ""
    suffix = "\n..." if end < len(lines) else ""
    return prefix + "\n".join(lines[start:end]) + suffix


def _download_button_if_exists(label: str, path: Path, file_name: str, mime: str = "text/plain") -> None:
    if path.exists():
        st.download_button(
            label,
            data=path.read_text(encoding="utf-8", errors="replace"),
            file_name=file_name,
            mime=mime,
            use_container_width=True,
        )


def _friendly_repair_source(summary_data: dict[str, Any]) -> str:
    value = summary_data.get("repair_source")
    if value not in (None, "", "Not recorded"):
        return str(value)

    provider = str(summary_data.get("provider") or "").lower()
    fallback = summary_data.get("local_fallback_used")

    if provider == "mock":
        return "Deterministic mock repair"
    if fallback is False or str(fallback).lower() == "false":
        return "LLM-generated patch"
    return "Not recorded"


def _render_run_identity(summary_data: dict[str, Any], title: str = "Run identity") -> None:
    """Show which model/workspace produced the loaded evidence."""
    if not summary_data:
        return

    provider = _short_text(summary_data.get("provider"))
    model = _short_text(summary_data.get("model_name"))
    workspace = _short_text(summary_data.get("workspace_path"))
    metrics = _metrics_for_summary(summary_data)
    fallback = _evidence_bool(metrics.get("local_fallback_used", summary_data.get("local_fallback_used")))
    repair_source = _friendly_repair_source(summary_data)
    runtime = _short_text(summary_data.get("target_runtime"))

    st.markdown(f"### {title}")
    cols = st.columns(4)
    with cols[0]:
        _card("Provider", provider)
    with cols[1]:
        _card("Model", model)
    with cols[2]:
        _card("Runtime", runtime)
    with cols[3]:
        _card("Fallback used", fallback)

    st.markdown(
        f"""
        <div class="soft-panel">
          <b>Workspace:</b> <code>{workspace}</code><br>
          <b>Repair source:</b> {_short_text(repair_source)}<br>
          <b>Evidence file:</b> <code>{_short_text(summary_data.get('candidate_report'))}</code>
        </div>
        """,
        unsafe_allow_html=True,
    )




@st.cache_data(ttl=300, show_spinner=False)
def _cached_catalog() -> dict[str, Any]:
    catalog = discover_benchmark_catalog(Path.cwd())
    return {
        key: {
            "dataset": value.dataset,
            "label": value.label,
            "projects": value.projects,
            "source": value.source,
            "message": value.message,
        }
        for key, value in catalog.items()
    }


def _run_password_ok() -> bool:
    password = os.environ.get("APP_RUN_PASSWORD", "").strip()
    if not password:
        return True
    entered = st.session_state.get("run_password", "")
    return entered == password


def _report_path_for_dataset(dataset: str) -> str:
    return "results/bugsinpy_candidate_selection.json" if dataset == "bugsinpy" else f"results/{dataset}_candidate_selection.json"


run_tab, comparison_tab, execute_tab, file_tab = st.tabs(["Run Summary", "Code Comparison", "Run Benchmark", "File Review"])

with run_tab:
    st.subheader("Run Summary")
    st.write("Choose a validated run and review the main evidence.")

    left, mid, right = st.columns([2.4, 0.9, 1])
    with left:
        run_label = st.selectbox("Validated run", list(RUN_OPTIONS.keys()), index=0)
        candidate_report = RUN_OPTIONS[run_label]
        st.caption(f"Evidence file: `{candidate_report}`")
    with mid:
        with st.expander("Advanced"):
            candidate_index = st.number_input("Run index", min_value=0, value=0, step=1)
    with right:
        st.write("")
        st.write("")
        if st.button("Load run", type="primary", use_container_width=True):
            try:
                _load_run(candidate_report, int(candidate_index))
            except Exception as exc:  # pragma: no cover - UI guard
                st.error(str(exc))

    summary_data = st.session_state.get("dashboard_summary")
    comparison_data = st.session_state.get("code_comparison")

    if summary_data:
        successful = str(summary_data.get("overall_status") or "").lower() == "successful"
        if successful:
            st.success("Run completed successfully. The LLM patch was applied and the validation checks passed.")
        else:
            st.warning("Run loaded, but one or more validation checks need review.")

        _render_run_identity(summary_data, "Run identity")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _card("Dataset", summary_data.get("dataset"))
        with c2:
            _card("Language", summary_data.get("language"))
        with c3:
            _card("Project / bug", f"{summary_data.get('project')} #{summary_data.get('bug_id')}")
        with c4:
            _card("Status", summary_data.get("overall_status"))

        st.markdown("### Validation checks")
        checks = st.columns(5)
        checks[0].markdown(_badge(summary_data.get("baseline_failure_observed"), "Reproduced", "Not reproduced"), unsafe_allow_html=True)
        checks[0].caption("Original bug")
        checks[1].markdown(_badge(summary_data.get("bug_found"), "Located", "Not located"), unsafe_allow_html=True)
        checks[1].caption("Bug location")
        checks[2].markdown(_badge(summary_data.get("patch_applied"), "Applied", "Not applied"), unsafe_allow_html=True)
        checks[2].caption("LLM patch")
        checks[3].markdown(_badge(summary_data.get("compilation_passed"), "Passed", "Failed"), unsafe_allow_html=True)
        checks[3].caption("Compile check")
        checks[4].markdown(_badge(summary_data.get("triggering_tests_passed"), "Passed", "Failed"), unsafe_allow_html=True)
        checks[4].caption("Targeted test")

        outputs = Path(summary_data["outputs_dir"])
        metrics = {}
        metrics_file = outputs / "evaluation_metrics.json"
        if metrics_file.exists():
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))

        st.markdown("### What changed")
        issue_summary = comparison_data.get("issue_summary") if comparison_data else ""
        st.markdown(
            f"""
            <div class="soft-panel">
            <b>Changed file:</b> {_short_text(summary_data.get('detection_file_path'))}<br>
            <b>Patch source:</b> {_friendly_patch_source(summary_data, metrics)}<br>
            <b>Local fallback used:</b> {_evidence_bool(metrics.get('local_fallback_used', summary_data.get('local_fallback_used')))}<br><br>
            <span class="muted">{_short_text(issue_summary, 'The run evidence contains the bug location, generated patch and validation result.')}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("### Evidence downloads")
        d1, d2, d3, d4 = st.columns(4)
        with d1:
            _download_button_if_exists("Diff", outputs / "applied_patch.diff", "applied_patch.diff")
        with d2:
            _download_button_if_exists("Metrics", outputs / "evaluation_metrics.json", "evaluation_metrics.json", "application/json")
        with d3:
            _download_button_if_exists("Validation", outputs / "validation_result.json", "validation_result.json", "application/json")
        with d4:
            _download_button_if_exists("HTML report", outputs / "final_experiment_report.html", "final_report.html", "text/html")

with comparison_tab:
    st.subheader("Code Comparison")
    st.write("Compare the original buggy file with the LLM-updated file.")

    if "dashboard_summary" not in st.session_state:
        st.info("Load a run from the Run Summary tab first.")
    else:
        summary_data = st.session_state["dashboard_summary"]
        comparison_data = st.session_state.get("code_comparison") or {}
        candidate_report = st.session_state.get("candidate_report_path", RUN_OPTIONS["Python — BugsInPy httpie-1"])
        candidate_index = int(st.session_state.get("candidate_index", 0))

        changed_files = comparison_data.get("files_changed") or [summary_data.get("detection_file_path")]
        changed_files = [item for item in changed_files if item]
        selected_file = st.selectbox("File", changed_files, index=0) if changed_files else summary_data.get("detection_file_path")

        if st.button("Refresh comparison", use_container_width=False):
            try:
                comparison = build_code_comparison(candidate_report, candidate_index, selected_file)
                st.session_state["code_comparison"] = comparison.to_dict()
                comparison_data = st.session_state["code_comparison"]
            except Exception as exc:  # pragma: no cover - UI guard
                st.error(str(exc))

        file_path = _short_text(comparison_data.get("file_path"), selected_file or "Not recorded")
        st.markdown(f"**File under review:** `{file_path}`")
        _render_run_identity(summary_data, "Run identity for this comparison")


        original = comparison_data.get("original_source") or ""
        updated = comparison_data.get("updated_source") or ""
        benchmark_fixed = comparison_data.get("benchmark_fixed_source") or ""
        diff_text = comparison_data.get("diff_text") or ""

        if not original or not updated:
            st.warning("Original or updated file snapshot is missing. Use the technical diff below if available.")
        else:
            show_full = st.toggle("Show complete file", value=False)
            left_code = original if show_full else _changed_excerpt(original, diff_text)
            right_code = updated if show_full else _changed_excerpt(updated, diff_text)
            before_col, after_col = st.columns(2)
            with before_col:
                st.markdown("#### Original buggy file")
                st.code(left_code, language=_short_text(summary_data.get("language"), "python"))
            with after_col:
                st.markdown("#### LLM-updated file")
                st.code(right_code, language=_short_text(summary_data.get("language"), "python"))

            if benchmark_fixed:
                with st.expander("Benchmark fixed file reference"):
                    st.write("This reference is shown only for comparison with the benchmark's known fixed version. It is not used by the LLM during repair.")
                    st.code(benchmark_fixed if show_full else _changed_excerpt(benchmark_fixed, diff_text), language=_short_text(summary_data.get("language"), "python"))

        st.markdown("#### Technical diff")
        st.code(diff_text or "No diff content recorded.", language="diff")

        outputs = Path(comparison_data.get("outputs_dir") or summary_data["outputs_dir"])
        _download_button_if_exists("Download diff", outputs / "applied_patch.diff", "code_change.diff")


with execute_tab:
    st.subheader("Run Benchmark")
    st.write(
        "Select any discovered benchmark case and start a background run. "
        "The page can be refreshed while the job continues."
    )

    catalog = _cached_catalog()
    total_cases = sum(option_count(item["projects"]) for item in catalog.values())
    st.caption(f"Selectable benchmark cases found: {total_cases}")

    dataset_choices = [key for key in ("bugsinpy", "defects4j") if catalog.get(key, {}).get("projects")]
    if not dataset_choices:
        st.error("No benchmark metadata was found. Check the benchmark tools installation.")
        st.stop()

    dataset = st.selectbox(
        "Dataset",
        dataset_choices,
        format_func=lambda key: DATASET_LABELS.get(key, key),
        index=0,
    )

    selected_catalog = catalog[dataset]
    if selected_catalog.get("message"):
        st.caption(selected_catalog["message"])

    projects = selected_catalog["projects"]
    project = st.selectbox("Project", project_names(projects), index=0)
    bug_id = st.selectbox("Bug ID", projects[project], index=0)

    provider = st.selectbox("Model provider", ["mock", "openrouter"], index=0)
    if provider == "mock":
        model_name = st.text_input("Model", value="mock-model")
    else:
        model_presets = [
            "deepseek/deepseek-v4-flash",
            "qwen/qwen3-coder",
            "custom",
        ]
        preset = st.selectbox("Review model", model_presets, index=0)
        model_name = st.text_input(
            "OpenRouter model ID",
            value="deepseek/deepseek-v4-flash" if preset == "custom" else preset,
            help="Paste any OpenRouter model ID here to test another model without changing the code.",
        )

    disable_fallback = st.toggle("Disable local fallback", value=True, key="disable_local_fallback")
    st.caption(
        "Keep this enabled for final evidence. When enabled, the repair must come from the selected model response."
    )

    if os.environ.get("APP_RUN_PASSWORD", "").strip():
        st.text_input("Run password", type="password", key="run_password")

    can_run = _run_password_ok()
    if not can_run:
        st.warning("Enter the run password to start a new benchmark execution.")

    run_col, note_col = st.columns([1, 2])
    with run_col:
        run_clicked = st.button("Start benchmark run", type="primary", disabled=not can_run, use_container_width=True)
    with note_col:
        st.caption(
            "The job runs in the background and writes evidence under a new workspace. "
            "Use Refresh status below while it is running."
        )

    if run_clicked:
        if provider == "openrouter" and not os.environ.get("PIPELINE_OPENROUTER_API_KEY"):
            st.error("OpenRouter is selected, but PIPELINE_OPENROUTER_API_KEY is not configured on this deployment.")
        else:
            job = start_pipeline_job(
                dataset=dataset,
                project=project,
                bug_id=str(bug_id),
                provider=provider,
                model_name=model_name.strip() or ("mock-model" if provider == "mock" else "deepseek/deepseek-v4-flash"),
                allow_local_fallback=not bool(disable_fallback),
                reviewer="web-ui",
                project_root=Path.cwd(),
            )
            st.session_state["selected_job_id"] = job["job_id"]
            st.success(f"Started background job {job['job_id']}.")

    st.markdown("### Job status")
    jobs = list_jobs(Path.cwd(), limit=20)
    if not jobs:
        st.info("No benchmark jobs have been started from this deployment yet.")
    else:
        selected_default = st.session_state.get("selected_job_id") or jobs[0]["job_id"]
        ids = [str(job["job_id"]) for job in jobs]
        if selected_default not in ids:
            selected_default = ids[0]
        selected_job_id = st.selectbox(
            "Recent jobs",
            ids,
            index=ids.index(selected_default),
            format_func=lambda item: next(
                (
                    f"{job.get('dataset')} {job.get('project')}-{job.get('bug_id')} · {job.get('provider')} · {job.get('status')} · {item}"
                    for job in jobs
                    if str(job.get("job_id")) == str(item)
                ),
                item,
            ),
        )
        st.session_state["selected_job_id"] = selected_job_id
        if st.button("Refresh status", use_container_width=False):
            st.rerun()

        job = read_job(selected_job_id, Path.cwd()) or {}
        job = refresh_job_status(job, Path.cwd()) if job else {}
        status = str(job.get("status") or "unknown")
        if status == "successful":
            st.success("Job completed successfully.")
        elif status in {"failed", "interrupted"}:
            st.error("Job did not complete successfully. Review the message and logs below.")
        else:
            st.info("Job is running. Refresh status in a few minutes.")

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            _card("Status", status)
        with c2:
            _card("Dataset", job.get("dataset"))
        with c3:
            _card("Project / bug", f"{job.get('project')} #{job.get('bug_id')}")
        with c4:
            _card("Model", job.get("model_name"))

        st.write(_short_text(job.get("message"), "No job message recorded."))
        if job.get("workspace_path"):
            st.write(f"Workspace: `{job.get('workspace_path')}`")
        if job.get("candidate_report"):
            st.write(f"Evidence report: `{job.get('candidate_report')}`")

        if status == "successful" and job.get("candidate_report"):
            if st.button("Load this run in review tabs", use_container_width=False):
                _load_run(str(job.get("candidate_report")), 0)
                st.success("Loaded. Open Run Summary or Code Comparison to review the evidence.")

        with st.expander("Job result JSON", expanded=status in {"failed", "interrupted"}):
            st.json(job)
            _render_job_workspace_artifacts(job)

        with st.expander("Worker logs"):
            stdout_tail = read_log_tail(job.get("stdout_log"))
            stderr_tail = read_log_tail(job.get("stderr_log"))
            st.markdown("**stdout**")
            st.code(stdout_tail or "No stdout log recorded.", language="text")
            st.markdown("**stderr**")
            st.code(stderr_tail or "No stderr log recorded.", language="text")



def _file_review_language(file_name):
    lower_name = file_name.lower()
    if lower_name.endswith(".py"):
        return "python"
    if lower_name.endswith(".java"):
        return "java"
    return "text"


def _openrouter_key_for_file_review():
    return (
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("PIPELINE_OPENROUTER_API_KEY")
        or os.getenv("OPENROUTER_KEY")
    )


def _call_openrouter_for_file_review(model_name, language, file_name, source_code):
    api_key = _openrouter_key_for_file_review()
    if not api_key:
        raise RuntimeError("OpenRouter API key is missing. Set OPENROUTER_API_KEY in Render environment variables.")

    prompt = f"""
You are reviewing one {language} source file for a production code-quality review.

Review and fix the file.

Requirements:
1. Identify syntax or compilation errors.
2. Identify logic bugs.
3. Identify input validation issues.
4. Identify resource-handling issues.
5. Return the complete corrected source code.
6. Keep the same program purpose and interactive behaviour.
7. If the file is Java, keep the same public class name as the uploaded file.
8. Do not invent external dependencies.

Return exactly in this format:

BUG_REPORT_START
List the bugs with location, severity, reason, and fix.
BUG_REPORT_END

FIXED_CODE_START
Put the complete fixed source code here.
FIXED_CODE_END

File name: {file_name}

Source code:
{source_code}
""".strip()

    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "You are a senior software engineer. Produce a precise bug report and a complete corrected source file.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 7000,
    }

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://llm-code-quality-pipeline.onrender.com",
            "X-Title": "LLM Code Quality Pipeline",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter request failed: HTTP {exc.code}: {body}") from exc

    return data["choices"][0]["message"]["content"]


def _extract_between_markers(text_value, start_marker, end_marker):
    if start_marker in text_value and end_marker in text_value:
        return text_value.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()
    return ""


def _extract_fixed_file_code(response_text):
    fixed = _extract_between_markers(response_text, "FIXED_CODE_START", "FIXED_CODE_END")
    if fixed:
        return fixed.strip() + "\n"

    cleaned = response_text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned)
    return cleaned.strip() + "\n"


def _extract_bug_report(response_text):
    report = _extract_between_markers(response_text, "BUG_REPORT_START", "BUG_REPORT_END")
    if report:
        return report
    if "FIXED_CODE_START" in response_text:
        return response_text.split("FIXED_CODE_START", 1)[0].strip()
    return response_text.strip()


def _validate_file_review_code(file_name, language, source_code):
    if language == "python":
        try:
            compile(source_code, file_name, "exec")
            return True, "Python syntax validation passed."
        except SyntaxError as exc:
            return False, f"Python syntax error at line {exc.lineno}: {exc.msg}"

    if language == "java":
        javac = shutil.which("javac")
        if not javac:
            return None, "Java validation skipped because javac is not installed."

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            java_path = tmp_path / file_name
            java_path.write_text(source_code, encoding="utf-8")

            result = subprocess.run(
                [javac, java_path.name],
                cwd=tmp_path,
                text=True,
                capture_output=True,
                timeout=60,
            )

            if result.returncode == 0:
                return True, "Java compilation validation passed."

            return False, result.stderr or result.stdout or "Java compilation failed."

    return None, "Validation is available only for Python and Java files."


def _file_review_diff(file_name, original_code, fixed_code):
    return "\n".join(
        difflib.unified_diff(
            original_code.splitlines(),
            fixed_code.splitlines(),
            fromfile=f"original/{file_name}",
            tofile=f"fixed/{file_name}",
            lineterm="",
        )
    )



with file_tab:
    st.subheader("File Review")
    st.write(
        "Upload a Python or Java file, select a real LLM model, and generate a reviewed fixed version. "
        "This is separate from the full benchmark pipeline."
    )

    uploaded = st.file_uploader(
        "Upload a Python or Java file",
        type=["py", "java"],
        key="llm_file_review_upload",
    )

    st.markdown("### Model selection")

    model_preset = st.selectbox(
        "Review model",
        [
            "deepseek/deepseek-v4-flash",
            "openai/gpt-4.1",
            "openai/gpt-4.1-mini",
            "qwen/qwen3-coder",
            "custom",
        ],
        key="file_review_model_preset",
    )

    if model_preset == "custom":
        model_name = st.text_input(
            "Custom OpenRouter model name",
            value="openai/gpt-4.1",
            key="file_review_custom_model",
        ).strip()
    else:
        model_name = model_preset

    st.caption(f"Selected model: `{model_name}`")

    if uploaded is not None:
        file_name = uploaded.name
        language = _file_review_language(file_name)
        original_code = uploaded.getvalue().decode("utf-8", errors="replace")

        st.markdown("### Uploaded file")
        cols = st.columns(3)
        cols[0].metric("File", file_name)
        cols[1].metric("Language", language)
        cols[2].metric("Model", model_name)

        original_ok, original_msg = _validate_file_review_code(file_name, language, original_code)
        if original_ok is True:
            st.info("Initial scan: No syntax or compilation issues were detected.")
        elif original_ok is False:
            st.warning("Initial scan: Issues were detected in the uploaded file. Run review to generate recommendations and a corrected version.")
        else:
            st.info("Initial scan: Automated validation is not available in this environment.")

        with st.expander("Technical details", expanded=False):
            st.code(original_msg, language="text")

        with st.expander("Show uploaded source", expanded=False):
            st.code(original_code, language=language)

        if st.button("Run code review", type="primary", use_container_width=True):
            if not model_name:
                st.error("Please select or enter a model name.")
            else:
                with st.spinner(f"Reviewing {file_name} with {model_name}..."):
                    try:
                        llm_response = _call_openrouter_for_file_review(
                            model_name=model_name,
                            language=language,
                            file_name=file_name,
                            source_code=original_code,
                        )
                        bug_report = _extract_bug_report(llm_response)
                        fixed_code = _extract_fixed_file_code(llm_response)

                        st.session_state["file_review_result"] = {
                            "file_name": file_name,
                            "language": language,
                            "provider": "openrouter",
                            "model_name": model_name,
                            "original_code": original_code,
                            "bug_report": bug_report,
                            "fixed_code": fixed_code,
                            "raw_response": llm_response,
                        }
                    except Exception as exc:
                        st.error(str(exc))

    result = st.session_state.get("file_review_result")

    if result:
        st.markdown("---")
        st.markdown("## Review results")

        cols = st.columns(4)
        cols[0].metric("Provider", result["provider"])
        cols[1].metric("Model", result["model_name"])
        cols[2].metric("Language", result["language"])
        cols[3].metric("File", result["file_name"])

        st.markdown("### Bug report")
        st.markdown(result.get("bug_report") or "No bug report returned.")

        fixed_code = result.get("fixed_code") or ""
        original_code = result.get("original_code") or ""
        file_name = result.get("file_name") or "fixed_file"
        language = result.get("language") or "text"

        fixed_ok, fixed_msg = _validate_file_review_code(file_name, language, fixed_code)
        if fixed_ok is True:
            st.success("Validation check: Suggested code passed syntax or compilation checks.")
        elif fixed_ok is False:
            st.error("Validation check: Suggested code still requires attention.")
        else:
            st.info("Validation check: Automated validation is not available in this environment.")

        with st.expander("Validation details", expanded=False):
            st.code(fixed_msg, language="text")

        st.markdown("### Suggested fixed code")
        st.code(fixed_code, language=language)

        st.markdown("### Diff")
        diff = _file_review_diff(file_name, original_code, fixed_code)
        st.code(diff if diff else "No code changes detected.", language="diff")

        suffix = Path(file_name).suffix
        stem = Path(file_name).stem
        download_name = f"{stem}_fixed{suffix}"

        st.download_button(
            "Download fixed file",
            data=fixed_code,
            file_name=download_name,
            mime="text/plain",
            use_container_width=True,
        )

        review_json = json.dumps(result, indent=2)
        st.download_button(
            "Download review report",
            data=review_json,
            file_name=f"{stem}_file_review.json",
            mime="application/json",
            use_container_width=True,
        )

        with st.expander("Raw model response", expanded=False):
            st.text(result.get("raw_response") or "")

