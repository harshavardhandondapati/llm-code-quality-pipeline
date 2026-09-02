"""Streamlit dashboard for the multi-language code quality pipeline."""

from __future__ import annotations

import difflib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
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

from llm_pipeline.config import Settings  # noqa: E402
from llm_pipeline.ui import build_code_comparison, build_dashboard_summary  # noqa: E402
from llm_pipeline.ui.job_store import (  # noqa: E402
    list_jobs,
    read_job,
    read_log_tail,
    refresh_job_status,
    start_pipeline_job,
)
from llm_pipeline.ui.run_history import (  # noqa: E402
    candidate_report_for_job,
    format_job_label,
    submitted_evidence_jobs,
)
from llm_pipeline.ui.review_actions import finalize_job_review  # noqa: E402
from llm_pipeline.ui.benchmark_catalog import (  # noqa: E402
    discover_benchmark_catalog,
    option_count,
    project_names,
)


DATASET_LABELS = {
    "bugsinpy": "BugsInPy",
    "defects4j": "Defects4J",
}

OPENROUTER_MODEL_PRESETS = [
    "deepseek/deepseek-v4-flash",
    "openai/gpt-4.1",
    "openai/gpt-4.1-mini",
    "qwen/qwen3-coder",
]



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
        ("Post-fix evaluation", outputs / "post_fix_evaluation_result.json", "json", False),
        ("Applied patch", outputs / "applied_patch.diff", "diff", True),
        ("Clean applied patch", outputs / "applied_patch_clean.diff", "diff", False),
        ("Bug detection response", outputs / "bug_detection_result.json", "json", False),
        ("Fix generation response", outputs / "fix_generation_result.json", "json", False),
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
      <div class="muted">Review generated repairs, validation evidence, and before/after code changes.</div>
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


def _html_text(value: Any, fallback: str = "Not recorded") -> str:
    """Escape dynamic values before inserting them into styled HTML."""
    return html.escape(_short_text(value, fallback), quote=True)


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
        return "true"
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
          <div class="card-label">{_html_text(label)}</div>
          <div class="card-value">{_html_text(value)}</div>
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


def _load_run(candidate_report: str) -> None:
    """Load one exact candidate report into the shared review state."""
    summary = build_dashboard_summary(candidate_report)
    comparison = build_code_comparison(candidate_report)

    summary_data = summary.to_dict()
    comparison_data = comparison.to_dict()

    outputs_dir = Path(
        str(summary_data.get("outputs_dir") or comparison_data.get("outputs_dir") or "")
    )
    metrics = _read_json_file(outputs_dir / "evaluation_metrics.json")
    workflow = _read_json_file(outputs_dir / "workflow_pipeline_result.json")

    # Provider/model come from the run outputs, but the selected candidate
    # report remains authoritative for the workspace being reviewed.
    for key in ["provider", "model_name"]:
        summary_data[key] = workflow.get(key) or metrics.get(key) or summary_data.get(key)

    summary_data["local_fallback_used"] = metrics.get(
        "local_fallback_used",
        summary_data.get("local_fallback_used"),
    )
    summary_data["repair_source"] = metrics.get(
        "repair_source",
        summary_data.get("repair_source"),
    )
    summary_data["target_runtime"] = metrics.get(
        "target_runtime",
        summary_data.get("target_runtime"),
    )
    summary_data["total_known_execution_time_seconds"] = metrics.get(
        "total_known_execution_time_seconds",
        summary_data.get("total_known_execution_time_seconds"),
    )
    summary_data["candidate_report"] = candidate_report

    st.session_state["dashboard_summary"] = summary_data
    st.session_state["code_comparison"] = comparison_data
    st.session_state["candidate_report_path"] = candidate_report


def _clear_review_state() -> None:
    """Clear review data when no exact run is selected."""
    for key in [
        "dashboard_summary",
        "code_comparison",
        "candidate_report_path",
        "review_job_id",
    ]:
        st.session_state.pop(key, None)


def _load_job_run(job: dict[str, Any]) -> None:
    """Load evidence that belongs to exactly one background job."""
    report = candidate_report_for_job(job, Path.cwd())
    if report is None:
        raise FileNotFoundError(
            "Exact per-run evidence is not available for this job. "
            "Older jobs created before immutable run evidence was added may need to be rerun."
        )

    _load_run(str(report))

    summary_data = st.session_state["dashboard_summary"]
    summary_data["job_id"] = str(job.get("job_id") or "")
    summary_data["created_at_utc"] = job.get("created_at_utc")
    summary_data["job_status"] = job.get("status")
    summary_data["candidate_report"] = str(report)
    st.session_state["review_job_id"] = str(job.get("job_id") or "")


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
          <b>Workspace:</b> <code>{_html_text(workspace)}</code><br>
          <b>Repair source:</b> {_html_text(repair_source)}<br>
          <b>Evidence file:</b> <code>{_html_text(summary_data.get('candidate_report'))}</code>
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


def _openrouter_api_key() -> str:
    """Read the OpenRouter key using the same configuration as the pipeline."""
    settings = Settings()
    secret = settings.openrouter_api_key or settings.api_key
    if secret is not None:
        return secret.get_secret_value().strip()

    # Keep compatibility with older File Review environment names.
    return (
        os.getenv("OPENROUTER_API_KEY", "").strip()
        or os.getenv("OPENROUTER_KEY", "").strip()
    )


def _password_ok(session_key: str) -> bool:
    """Check the optional password used to protect model-execution actions."""
    password = os.environ.get("APP_RUN_PASSWORD", "").strip()
    if not password:
        return True
    entered = st.session_state.get(session_key, "")
    return entered == password


pending_review_job = st.session_state.pop("requested_review_job_id", None)
if pending_review_job:
    st.session_state["run_summary_job_choice"] = str(pending_review_job)

if "run_summary_job_choice" not in st.session_state:
    st.session_state["run_summary_job_choice"] = str(
        st.session_state.get("review_job_id") or ""
    )


run_tab, comparison_tab, execute_tab, file_tab = st.tabs(["Run Summary", "Code Comparison", "Run Benchmark", "File Review"])

with run_tab:
    st.subheader("Run Summary")
    st.write("Select a benchmark execution to review its exact saved evidence.")

    summary_jobs = list_jobs(Path.cwd(), limit=100) + submitted_evidence_jobs(Path.cwd())
    jobs_by_id = {str(job["job_id"]): job for job in summary_jobs}

    stored_choice = str(st.session_state.get("run_summary_job_choice") or "")
    if stored_choice and stored_choice not in jobs_by_id:
        st.session_state["run_summary_job_choice"] = ""

    selected_review_job = st.selectbox(
        "Benchmark run",
        [""] + list(jobs_by_id),
        key="run_summary_job_choice",
        format_func=lambda job_id: (
            "Select a run..."
            if not job_id
            else format_job_label(jobs_by_id[job_id])
        ),
    )

    current_review_job = str(st.session_state.get("review_job_id") or "")
    if not selected_review_job:
        if current_review_job:
            _clear_review_state()
        st.info("Select a run to review its summary and code changes.")
    elif selected_review_job != current_review_job:
        try:
            _load_job_run(jobs_by_id[selected_review_job])
        except Exception as exc:  # pragma: no cover - UI guard
            _clear_review_state()
            st.warning(str(exc))

    selected_job = (
        jobs_by_id.get(selected_review_job)
        if selected_review_job
        else None
    )
    if selected_job:
        exact_report = candidate_report_for_job(selected_job, Path.cwd())
        if exact_report:
            st.caption(f"Evidence file: `{exact_report}`")
        else:
            st.caption("Exact per-run evidence is not available for this job.")

    summary_data = st.session_state.get("dashboard_summary")
    comparison_data = st.session_state.get("code_comparison")

    if summary_data:
        successful = str(summary_data.get("overall_status") or "").lower() == "successful"
        if successful:
            st.success("Run completed successfully. The generated repair was applied and the validation checks passed.")
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
        checks = st.columns(6)
        checks[0].markdown(_badge(summary_data.get("baseline_failure_observed"), "Reproduced", "Not reproduced"), unsafe_allow_html=True)
        checks[0].caption("Original bug")
        checks[1].markdown(_badge(summary_data.get("bug_found"), "Located", "Not located"), unsafe_allow_html=True)
        checks[1].caption("Bug location")
        checks[2].markdown(_badge(summary_data.get("patch_applied"), "Applied", "Not applied"), unsafe_allow_html=True)
        checks[2].caption("Generated repair")
        checks[3].markdown(_badge(summary_data.get("compilation_passed"), "Passed", "Failed"), unsafe_allow_html=True)
        checks[3].caption("Compile check")
        checks[4].markdown(_badge(summary_data.get("triggering_tests_passed"), "Passed", "Failed"), unsafe_allow_html=True)
        checks[4].caption("Targeted test")

        human_decision = str(summary_data.get("human_decision") or "pending").lower()
        if human_decision == "approved":
            review_badge = "<span class='ok-badge'>Approved</span>"
        elif human_decision == "rejected":
            review_badge = "<span class='bad-badge'>Rejected</span>"
        elif human_decision == "needs_changes":
            review_badge = "<span class='warn-badge'>Needs changes</span>"
        else:
            review_badge = "<span class='warn-badge'>Pending</span>"
        checks[5].markdown(review_badge, unsafe_allow_html=True)
        checks[5].caption("Human review")

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
            <b>Changed file:</b> {_html_text(summary_data.get('detection_file_path'))}<br>
            <b>Patch source:</b> {_html_text(_friendly_patch_source(summary_data, metrics))}<br>
            <b>Local fallback used:</b> {_html_text(_evidence_bool(metrics.get('local_fallback_used', summary_data.get('local_fallback_used'))))}<br><br>
            <span class="muted">{_html_text(issue_summary, 'The run evidence contains the bug location, generated patch and validation result.')}</span>
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
    st.write("Compare the original buggy file with the repaired file.")

    if "dashboard_summary" not in st.session_state:
        st.info("Select or load a run in Run Summary first.")
    else:
        summary_data = st.session_state["dashboard_summary"]
        comparison_data = st.session_state.get("code_comparison") or {}
        candidate_report = st.session_state["candidate_report_path"]

        changed_files = comparison_data.get("files_changed") or [
            summary_data.get("detection_file_path")
        ]
        changed_files = [item for item in changed_files if item]
        selected_file = (
            st.selectbox("File", changed_files, index=0)
            if changed_files
            else summary_data.get("detection_file_path")
        )

        if st.button("Refresh comparison", use_container_width=False):
            try:
                comparison = build_code_comparison(
                    candidate_report,
                    file_path=selected_file,
                )
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
                st.markdown("#### Repaired file")
                st.code(right_code, language=_short_text(summary_data.get("language"), "python"))

            if benchmark_fixed:
                with st.expander("Benchmark fixed file reference"):
                    st.write("This reference is shown only for comparison with the benchmark's known fixed version. It is not used by the LLM during repair.")
                    st.code(benchmark_fixed if show_full else _changed_excerpt(benchmark_fixed, diff_text), language=_short_text(summary_data.get("language"), "python"))

        st.markdown("#### Technical diff")
        st.code(diff_text or "No diff content recorded.", language="diff")

        outputs = Path(comparison_data.get("outputs_dir") or summary_data["outputs_dir"])
        _download_button_if_exists("Download diff", outputs / "applied_patch.diff", "code_change.diff")


def _render_benchmark_tab() -> None:
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
        return

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
        model_presets = OPENROUTER_MODEL_PRESETS + ["custom"]
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

    can_run = _password_ok("run_password")
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
        if provider == "openrouter" and not _openrouter_api_key():
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
        elif status == "awaiting_review":
            st.warning(
                "Technical validation passed. A human review decision is required "
                "before this run can be accepted."
            )
        elif status in {"rejected", "needs_changes"}:
            st.warning("This run has a recorded human review decision.")
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

        exact_report = candidate_report_for_job(job, Path.cwd())

        if status == "awaiting_review" and exact_report:
            st.markdown("### Human review")
            st.caption("Review the generated repair and validation evidence before recording a decision.")
            reviewer_name = st.text_input(
                "Reviewer name",
                key=f"human_reviewer_{selected_job_id}",
            ).strip()
            review_comments = st.text_area(
                "Review comments (optional)",
                key=f"human_review_comments_{selected_job_id}",
            ).strip()

            approve_col, changes_col, reject_col = st.columns(3)
            review_decision = None
            if approve_col.button("Approve", type="primary", key=f"approve_{selected_job_id}", use_container_width=True):
                review_decision = "approved"
            if changes_col.button("Needs changes", key=f"needs_changes_{selected_job_id}", use_container_width=True):
                review_decision = "needs_changes"
            if reject_col.button("Reject", key=f"reject_{selected_job_id}", use_container_width=True):
                review_decision = "rejected"

            if review_decision:
                if not reviewer_name:
                    st.error("Enter the reviewer name before recording a decision.")
                else:
                    try:
                        finalize_job_review(
                            job,
                            decision=review_decision,
                            reviewer=reviewer_name,
                            comments=review_comments,
                            project_root=Path.cwd(),
                        )
                        _clear_review_state()
                        st.rerun()
                    except Exception as exc:  # pragma: no cover - UI guard
                        st.error(str(exc))

        if exact_report:
            if st.button("Load this run in review tabs", use_container_width=False):
                st.session_state["requested_review_job_id"] = str(job["job_id"])
                st.rerun()
        elif status in {
            "successful",
            "failed",
            "interrupted",
            "awaiting_review",
            "rejected",
            "needs_changes",
        }:
            st.caption(
                "This job does not have exact per-run review evidence. "
                "Rerun older jobs if you need a safely reviewable record."
            )

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



with execute_tab:
    _render_benchmark_tab()

def _file_review_language(file_name):
    lower_name = file_name.lower()
    if lower_name.endswith(".py"):
        return "python"
    if lower_name.endswith(".java"):
        return "java"
    return "text"


def _openrouter_key_for_file_review():
    return _openrouter_api_key()


def _call_openrouter_for_file_review(model_name, language, file_name, source_code):
    api_key = _openrouter_key_for_file_review()
    if not api_key:
        raise RuntimeError("OpenRouter API key is missing. Set PIPELINE_OPENROUTER_API_KEY in the environment or .env file.")

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
        "Upload a Python or Java source file and select a review model to generate findings and suggested fixes."
    )

    uploaded = st.file_uploader(
        "Upload a Python or Java file",
        type=["py", "java"],
        key="llm_file_review_upload",
    )

    if uploaded is None:
        st.session_state.pop("file_review_result", None)

    st.markdown("### Model selection")

    model_preset = st.selectbox(
        "Review model",
        OPENROUTER_MODEL_PRESETS + ["custom"],
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

    if os.environ.get("APP_RUN_PASSWORD", "").strip():
        st.text_input(
            "Run password",
            type="password",
            key="file_review_password",
        )

    file_review_allowed = _password_ok("file_review_password")
    if not file_review_allowed:
        st.warning("Enter the run password to use the OpenRouter File Review action.")

    if uploaded is not None:
        file_name = uploaded.name
        language = _file_review_language(file_name)
        original_code = uploaded.getvalue().decode("utf-8", errors="replace")
        file_review_input_signature = hashlib.sha256(
            (file_name + "\0" + model_name + "\0" + original_code).encode("utf-8")
        ).hexdigest()

        existing_review = st.session_state.get("file_review_result")
        if existing_review and existing_review.get("input_signature") != file_review_input_signature:
            st.session_state.pop("file_review_result", None)

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

        if st.button(
            "Run code review",
            type="primary",
            disabled=not file_review_allowed,
            use_container_width=True,
        ):
            if not model_name:
                st.error("Please select or enter a model name.")
            else:
                st.session_state.pop("file_review_result", None)
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
                            "input_signature": file_review_input_signature,
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

