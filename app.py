"""Streamlit dashboard for the multi-language code quality pipeline."""

from __future__ import annotations

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
from llm_pipeline.ui.benchmark_catalog import (  # noqa: E402
    discover_benchmark_catalog,
    option_count,
    project_names,
)
from llm_pipeline.workflow import run_final_pipeline  # noqa: E402


RUN_OPTIONS = {
    "Python — BugsInPy httpie-1": "results/bugsinpy_candidate_selection.json",
    "Java — Defects4J Chart-1": "results/defects4j_candidate_selection.json",
}

DATASET_LABELS = {
    "bugsinpy": "BugsInPy",
    "defects4j": "Defects4J",
}


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
    text = str(value or "").strip()
    return text if text else fallback


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


def _load_run(candidate_report: str, candidate_index: int = 0) -> None:
    summary = build_dashboard_summary(candidate_report, candidate_index)
    comparison = build_code_comparison(candidate_report, candidate_index)
    st.session_state["dashboard_summary"] = summary.to_dict()
    st.session_state["code_comparison"] = comparison.to_dict()
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
            <b>Patch source:</b> LLM-generated patch<br>
            <b>Local fallback used:</b> {str(metrics.get('local_fallback_used', False)).lower()}<br><br>
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
    st.write("Select a benchmark case and run the pipeline on demand. The selected project is checked out only when you start the run.")
    st.info("Additional bug cases are supported by the framework, but only the submitted examples are guaranteed to pass. New cases depend on benchmark setup, dependencies, and the LLM patch quality.")

    catalog = _cached_catalog()
    total_cases = sum(option_count(item["projects"]) for item in catalog.values())
    st.caption(f"Selectable benchmark cases found: {total_cases}")

    dataset_choices = [key for key in ("bugsinpy", "defects4j") if catalog.get(key, {}).get("projects")]
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
    model_default = "mock-model" if provider == "mock" else "deepseek/deepseek-v4-flash"
    model_name = st.text_input("Model", value=model_default)

    st.toggle("Disable local fallback", value=True, key="disable_local_fallback")
    st.caption("Keep fallback disabled for final evidence so the patch must come from the LLM response.")

    if os.environ.get("APP_RUN_PASSWORD", "").strip():
        st.text_input("Run password", type="password", key="run_password")

    can_run = _run_password_ok()
    if not can_run:
        st.warning("Enter the run password to start a new benchmark execution.")

    run_col, note_col = st.columns([1, 2])
    with run_col:
        run_clicked = st.button("Run selected bug", type="primary", disabled=not can_run, use_container_width=True)
    with note_col:
        st.caption("Mock runs are repeatable and cost-free. OpenRouter runs use your configured API key and may take several minutes.")

    if run_clicked:
        if provider == "openrouter" and not os.environ.get("PIPELINE_OPENROUTER_API_KEY"):
            st.error("OpenRouter is selected, but PIPELINE_OPENROUTER_API_KEY is not configured on this deployment.")
        else:
            previous_fallback = os.environ.get("PIPELINE_ALLOW_LOCAL_FALLBACK")
            os.environ["PIPELINE_ALLOW_LOCAL_FALLBACK"] = "false" if st.session_state.get("disable_local_fallback", True) else "true"
            try:
                with st.spinner("Running checkout, LLM analysis, patching, and validation..."):
                    result = run_final_pipeline(
                        dataset=dataset,
                        project=project,
                        bug_id=bug_id,
                        provider=provider,
                        model_name=model_name,
                        approval="approved",
                        reviewer="web-ui",
                    )
                st.session_state["last_pipeline_result"] = result
                st.success("Pipeline run completed." if result.get("successful") else "Pipeline run finished with failed checks.")
                st.json(result)
            except Exception as exc:  # pragma: no cover - UI guard
                st.error(f"Pipeline run could not complete: {exc}")
            finally:
                if previous_fallback is None:
                    os.environ.pop("PIPELINE_ALLOW_LOCAL_FALLBACK", None)
                else:
                    os.environ["PIPELINE_ALLOW_LOCAL_FALLBACK"] = previous_fallback

    last_result = st.session_state.get("last_pipeline_result")
    if last_result:
        st.markdown("### Latest run")
        st.write(f"Status: **{last_result.get('overall_status')}**")
        st.write(f"Workspace: `{last_result.get('workspace_path')}`")
        report = _report_path_for_dataset(str(last_result.get("dataset", dataset)).lower())
        if st.button("Load latest run in review tabs", use_container_width=False):
            _load_run(report, 0)
            st.success("Latest run loaded. Open the Run Summary or Code Comparison tab.")


with file_tab:
    st.subheader("File Review")
    st.write("Upload a Python file for a quick local review. This is separate from the full benchmark pipeline.")

    uploaded = st.file_uploader("Upload a Python file", type=["py"])

    if uploaded is not None:
        source = uploaded.getvalue().decode("utf-8", errors="replace")
        st.markdown("#### Uploaded file")
        st.code(source, language="python")

        if st.button("Run file review", type="primary"):
            result = review_python_source(source, filename=uploaded.name, provider="Rule-based local review")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path("interactive_reviews") / f"review_{timestamp}_{Path(uploaded.name).stem}"
            artifacts = write_interactive_review_artifacts(result, original_source=source, output_dir=output_dir)
            st.session_state["interactive_result"] = result.to_dict()
            st.session_state["interactive_artifacts"] = artifacts

    result_data = st.session_state.get("interactive_result")
    artifacts = st.session_state.get("interactive_artifacts")
    if result_data and artifacts:
        st.markdown("### Review result")
        cols = st.columns(3)
        cols[0].metric("Issue found", str(result_data["bug_found"]))
        cols[1].metric("Issue type", result_data["issue_type"])
        cols[2].metric("Changed", str(result_data["changed"]))
        st.write(result_data["explanation"])

        before_col, after_col = st.columns(2)
        with before_col:
            st.markdown("#### Original upload")
            st.code(Path(artifacts["original_file"]).read_text(encoding="utf-8"), language="python")
        with after_col:
            st.markdown("#### Suggested update")
            st.code(result_data["fixed_source"], language="python")

        st.markdown("#### Diff")
        st.code(result_data["patch"] or "No code changes proposed.", language="diff")

        st.download_button(
            "Download updated file",
            data=Path(artifacts["fixed_file"]).read_text(encoding="utf-8"),
            file_name=Path(artifacts["fixed_file"]).name,
            mime="text/x-python",
        )
        st.download_button(
            "Download review notes",
            data=build_review_markdown(type("Result", (), result_data)()),
            file_name="file_review_notes.md",
            mime="text/markdown",
        )
