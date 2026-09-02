# Cloud hosting guide

This project can be hosted as a Streamlit web service on Render using the supplied Dockerfile.

## Hosting model

```text
GitHub stores the source and submitted evidence
Docker installs Python, Java, BugsInPy, Defects4J and Python packages
Render runs the Streamlit service
```

## Render environment variables

```text
PIPELINE_ALLOW_LOCAL_FALLBACK=false
PIPELINE_CONTEXT_USE_BENCHMARK_HINTS=false
APP_RUN_PASSWORD=<optional password for benchmark runs and File Review model calls>
PIPELINE_OPENROUTER_API_KEY=<required only for real OpenRouter runs>
```

Do not store API keys or passwords in the repository.

## Benchmark workflow

The **Run Benchmark** tab starts a background process:

```text
Select dataset, project, bug and model
Start benchmark run
Refresh status
Technical validation completes
Review the saved repair and validation evidence
Record Approve / Needs changes / Reject
Load the same run in Run Summary or Code Comparison
```

A technically valid background run remains `awaiting_review` until a reviewer records a decision.

## Submitted evidence

The repository contains compact evidence under `evidence/` and stable report pointers under `results/`. Run Summary can display submitted evidence on a fresh deployment when a result report points to a workspace under `evidence/`.

New online executions use `jobs/` and `workspaces/`. These runtime folders are not committed.

## Persistence

Render services can restart or redeploy. Runtime files under `jobs/` and `workspaces/` may disappear unless a persistent disk is configured.

Submitted dissertation evidence is stored under `evidence/` and `results/` in the repository and is rebuilt into the Docker image on deployment. For longer experiment campaigns, use persistent storage or copy/download generated evidence after each run.

## Model providers

```text
mock        deterministic, cost-free pipeline validation
openrouter  real LLM request using PIPELINE_OPENROUTER_API_KEY
```

The OpenRouter model ID can be selected or entered in the UI without changing application code.
