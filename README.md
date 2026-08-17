# LLM Code Quality Pipeline

This repository contains a dissertation implementation for an LLM-assisted code quality pipeline. It supports a validated Python repair case from BugsInPy and a validated Java repair case from Defects4J.

The pipeline records every run as file-based evidence. The Streamlit app loads those evidence files and presents the result in a simple review dashboard.

## Final validated examples

| Language | Dataset | Project | Bug | Provider | Result |
| --- | --- | --- | --- | --- | --- |
| Python | BugsInPy | httpie | 1 | OpenRouter / DeepSeek | successful |
| Java | Defects4J | Chart | 1 | OpenRouter / DeepSeek | successful |

The Java final evidence has `local_fallback_used: false`, so the validated patch came from the LLM response and was not copied from the official Defects4J fixed version.

## What the pipeline does

1. Checks out a benchmark bug.
2. Reproduces the original failing test.
3. Builds source-code context for the LLM.
4. Asks the LLM to locate the issue.
5. Asks the LLM to generate a patch.
6. Saves the original buggy file before patching.
7. Applies the generated patch.
8. Saves the updated file after patching.
9. Runs compile and targeted validation tests.
10. Writes JSON, text, diff and HTML evidence.

## Main folders

```text
src/llm_pipeline/      pipeline source code
scripts/               setup, verification and run commands
tests/                 automated tests
results/               candidate reports used by the UI
evidence/              compact final evidence for deployment and review
app.py                 Streamlit dashboard
```

Generated runtime folders such as `.venv`, `workspaces`, caches, logs and API keys are not part of the clean submission package.

## Benchmark tools layout

Local and cloud runs use the same clear tools structure:

```text
tools/
  BugsInPy/
  defects4j/
```

The ZIP includes the tool folder placeholder and the installer script, not the full cloned tool repositories. During Docker/Render deployment, `scripts/prepare_benchmark_tools.sh` installs BugsInPy and Defects4J into `/app/tools`. The app then discovers available projects and bug IDs from those installed tools.

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

Use the dropdown to select either:

```text
Python — BugsInPy httpie-1
Java — Defects4J Chart-1
```

## Run the Python pipeline

Mock provider:

```bash
python scripts/run_pipeline.py \
  --dataset bugsinpy \
  --project httpie \
  --bug-id 1 \
  --provider mock \
  --approval approved \
  --reviewer Hari
```

Real LLM provider:

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

## Run the Java pipeline

Install Java/JDK and Defects4J first, then verify:

```bash
python scripts/verify_java_setup.py
```

Real LLM provider:

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
bug_detection_result.json
fix_generation_result.json
validation_result.json
evaluation_metrics.json
applied_patch.diff
final_experiment_report.html
source_snapshots.json
snapshots/original/...
snapshots/updated/...
```

The snapshots are used by the UI to compare the exact original buggy file with the exact LLM-updated file.

## Deployment

For deployment, use the Streamlit app as an evidence review dashboard. The deployed UI can show the validated Python and Java runs without requiring an examiner to install WSL, BugsInPy or Defects4J.

See `CLOUD_HOSTING_GUIDE.md` for the Render/Docker deployment process.

## Online benchmark selection

The Streamlit app includes a **Run Benchmark** tab. When BugsInPy or Defects4J tools are installed, the tab discovers available projects and bug IDs and presents them as dropdowns. The app checks out the selected bug on demand, so individual bug workspaces do not need to be committed to the repository.

For final marking, use the included validated evidence first:

- Python: BugsInPy `httpie` bug `1`
- Java: Defects4J `Chart` bug `1`

Additional bugs can be selected and executed, but they are experimental because each benchmark case depends on dependency setup, test reproducibility, and LLM patch quality.
