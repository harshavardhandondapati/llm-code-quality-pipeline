# LLM Code Quality Pipeline

This repository contains the implementation used for an MSc dissertation on an LLM-assisted code quality workflow. It supports Python bugs from BugsInPy and Java bugs from Defects4J and can be run from the command line or through the Streamlit interface.

Each benchmark run records the evidence needed to review what happened: the original source, generated repair, prompts and model responses, patch diff, validation results, human review decision, metrics and final report.

## Submitted examples

| Language | Dataset | Project | Bug | Provider | Purpose |
| --- | --- | --- | --- | --- | --- |
| Python | BugsInPy | httpie | 1 | mock | repeatable pipeline validation |
| Java | Defects4J | Chart | 1 | OpenRouter / DeepSeek | real-model evaluation |

The final Java evidence must be generated with local fallback disabled and without benchmark changed-file hints. The benchmark fixed version is retained only as a post-run comparison reference.

## Pipeline stages

1. Check out the selected benchmark bug.
2. Reproduce the baseline failure.
3. Save the original source snapshot.
4. Build source context from the failure, triggering tests and project files.
5. Ask the selected model to localise the defect.
6. Ask the model to generate a repair.
7. Apply the repair.
8. Save the repaired source snapshot.
9. Run compilation and triggering-test validation.
10. Record a human review decision.
11. Write metrics and final evidence reports.

A generated repair is not classified as successful simply because it was produced by a model. The required validation checks must pass and the human review decision must allow the run to progress.

For Defects4J cases that report more than one triggering test, the current adapter validates the first recorded triggering test. This is a scope limitation of the current implementation.

## Research safeguards

The final pipeline runner does not use benchmark changed-file metadata to select prompt context. Local fallback is disabled by default for final evidence:

```text
PIPELINE_ALLOW_LOCAL_FALLBACK=false
PIPELINE_CONTEXT_USE_BENCHMARK_HINTS=false
```

The benchmark fixed source can be saved after validation for comparison, but it is not used to generate a real-model repair when fallback is disabled.

## Main folders

```text
src/llm_pipeline/      pipeline source
scripts/               command-line and background-job entry points
tests/                 automated regression tests
results/               stable candidate-report pointers for submitted evidence
evidence/              compact evidence included with the repository
app.py                 Streamlit dashboard
Dockerfile             Docker/Render deployment definition
```

Runtime folders such as `workspaces/`, `jobs/`, logs, caches, virtual environments and API keys are intentionally excluded from the clean repository.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -r UI_REQUIREMENTS.txt
cp .env.example .env
```

Add an OpenRouter key to `.env` only when running a real model. Do not commit `.env`.

## Automated tests

```bash
python -m pytest -q --color=no
```

The repository should finish with all tests passing. The exact count is not hard-coded because regression coverage can change during final verification.

## Dashboard

```bash
python -m streamlit run app.py
```

Open `http://localhost:8501`.

The dashboard has four tabs:

```text
Run Summary       review submitted evidence and exact runtime runs
Code Comparison   compare original and repaired source
Run Benchmark     start and review background benchmark jobs
File Review       review a standalone Python or Java file
```

On a fresh deployment, submitted evidence whose result report points into `evidence/` is available in Run Summary before any new runtime job is created.

## Web benchmark flow

1. Select the dataset, project and bug ID.
2. Select `mock` or `openrouter`.
3. Choose or enter the model ID.
4. Keep **Disable local fallback** enabled for final evidence.
5. Start the benchmark and refresh status while it runs.
6. After technical validation passes, review the saved evidence.
7. Record **Approve**, **Needs changes** or **Reject**.
8. Load the same run in Run Summary or Code Comparison.

A technically valid run remains `awaiting_review` until a reviewer records a decision.

## Command line

Without an explicit review decision, the CLI records a pending human review. The run is not classified as successful until an approval decision is supplied:

```bash
PIPELINE_ALLOW_LOCAL_FALLBACK=false python scripts/run_pipeline.py   --dataset defects4j   --project Chart   --bug-id 1   --provider openrouter   --model deepseek/deepseek-v4-flash
```

A completed decision must be explicit:

```bash
PIPELINE_ALLOW_LOCAL_FALLBACK=false python scripts/run_pipeline.py   --dataset bugsinpy   --project httpie   --bug-id 1   --provider mock   --approval approved   --reviewer "Reviewer name"
```

For the web workflow, prefer the in-app review step because the repair and validation evidence can be inspected before the decision is recorded.

## Evidence files

A completed workspace normally contains `baseline_reproduction.json`, source-context and prompt files, model results, `validation_result.json`, `human_approval_decision.json`, `evaluation_metrics.json`, `applied_patch.diff`, the final report, and original/repaired/reference source snapshots.

## Deployment

The Docker image installs Python, Java, BugsInPy, Defects4J and the application dependencies. Runtime `jobs/` and `workspaces/` are ephemeral unless persistent storage is configured, while submitted `evidence/` and `results/` are built into the image.

See `CLOUD_HOSTING_GUIDE.md` for deployment details.
