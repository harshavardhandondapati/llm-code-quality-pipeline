# LLM Code Quality Pipeline

This repository contains a dissertation implementation for an LLM-assisted code quality pipeline. It supports Python bugs from BugsInPy and Java bugs from Defects4J. The same pipeline can be run locally or from the deployed Streamlit app.

The pipeline records each run as evidence: original buggy file, LLM-updated file, optional benchmark fixed reference, prompts, model responses, patch diff, validation result, metrics and final report.

## Validated examples included

| Language | Dataset | Project | Bug | Provider | Result |
| --- | --- | --- | --- | --- | --- |
| Python | BugsInPy | httpie | 1 | OpenRouter / DeepSeek | successful |
| Java | Defects4J | Chart | 1 | OpenRouter / DeepSeek | successful |

The Java evidence has `local_fallback_used: false`. That means the validated patch came from the LLM response, not from copied benchmark fixed code.

## What the pipeline does

1. Checks out the selected benchmark bug.
2. Reproduces the baseline failure.
3. Saves the original buggy source file before patching.
4. Builds source-code context for the selected LLM.
5. Asks the LLM to locate the issue.
6. Asks the LLM to generate a patch.
7. Applies the generated patch.
8. Saves the updated source file after patching.
9. Runs compile and targeted validation tests.
10. Saves the benchmark fixed file separately as reference evidence where available.
11. Writes JSON, text, diff and HTML evidence.

The official benchmark fixed file is captured only after the LLM repair/validation path. It is not sent to the LLM prompt and is not used to generate the patch when fallback is disabled.

## Main folders

```text
src/llm_pipeline/      pipeline source code
scripts/               setup, verification, command-line and background-job scripts
tests/                 automated tests
results/               candidate reports used by the UI
evidence/              compact final evidence for deployment and review
app.py                 Streamlit dashboard
Dockerfile             Render/Docker deployment definition
```

Generated runtime folders such as `.venv`, `workspaces`, `jobs`, caches, logs and API keys are not part of the clean submission package.

## Benchmark tools layout

Local and cloud runs use this structure:

```text
tools/
  BugsInPy/
  defects4j/
```

The ZIP includes the tool folder placeholder and installer script, not the full cloned benchmark repositories. During Docker/Render deployment, `scripts/prepare_benchmark_tools.sh` installs BugsInPy and Defects4J into `/app/tools`. The app then discovers available projects and bug IDs from those installed tools.

## Setup locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install -r UI_REQUIREMENTS.txt
```

Create `.env` from the example file when running a real LLM call:

```bash
cp .env.example .env
```

Add your OpenRouter key only in `.env`. Do not commit `.env`.

## Run automated tests

```bash
python -m pytest -q --color=no
```

Expected result for this package:

```text
119 passed
```

## Open the dashboard locally

```bash
python -m streamlit run app.py
```

Open:

```text
http://localhost:8501
```

The dashboard has four tabs:

```text
Run Summary       review saved evidence
Code Comparison   compare original, LLM-updated and benchmark fixed source
Run Benchmark     start new background benchmark jobs
File Review       lightweight single-file review
```

## Run a benchmark from the web app

Use the **Run Benchmark** tab.

1. Select dataset: BugsInPy or Defects4J.
2. Select project and bug ID from the discovered metadata.
3. Select provider: mock or OpenRouter.
4. Enter the model ID. For OpenRouter, any valid OpenRouter model ID can be entered.
5. Keep **Disable local fallback** enabled for final evidence.
6. Click **Start benchmark run**.
7. Use **Refresh status** while the job runs.
8. When successful, click **Load this run in review tabs**.

Runs execute in a background process so the browser does not need to remain blocked during checkout, dependency setup, LLM calls and validation.

## Command-line examples

Python / BugsInPy with mock provider:

```bash
PIPELINE_ALLOW_LOCAL_FALLBACK=false python scripts/run_pipeline.py \
  --dataset bugsinpy \
  --project httpie \
  --bug-id 1 \
  --provider mock \
  --approval approved \
  --reviewer Hari
```

Python / BugsInPy with OpenRouter:

```bash
PIPELINE_ALLOW_LOCAL_FALLBACK=false python scripts/run_pipeline.py \
  --dataset bugsinpy \
  --project httpie \
  --bug-id 1 \
  --provider openrouter \
  --model deepseek/deepseek-v4-flash \
  --approval approved \
  --reviewer Hari
```

Java / Defects4J with OpenRouter:

```bash
PIPELINE_ALLOW_LOCAL_FALLBACK=false python scripts/run_pipeline.py \
  --dataset defects4j \
  --project Chart \
  --bug-id 1 \
  --provider openrouter \
  --model deepseek/deepseek-v4-flash \
  --approval approved \
  --reviewer Hari
```

## Evidence files

Each run writes files under `outputs/`, including:

```text
baseline_reproduction.json
source_context.json
bug_detection_prompt.json
bug_detection_result.json
fix_generation_prompt.json
fix_generation_result.json
validation_result.json
evaluation_metrics.json
applied_patch.diff
final_experiment_report.html
snapshots/original/...
snapshots/updated/...
snapshots/benchmark_fixed/...
```

These snapshots allow the UI to show the exact original buggy source, the exact LLM-updated source, and the benchmark fixed reference side by side.

## Deployment

For deployment, use GitHub + Render + Docker. The repository contains a Dockerfile that installs the app, Java, BugsInPy, Defects4J and required runtime tools.

See `CLOUD_HOSTING_GUIDE.md` for the deployment steps and environment variables.
