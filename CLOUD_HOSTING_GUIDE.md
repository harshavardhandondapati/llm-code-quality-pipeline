# Cloud hosting guide

This guide describes how to host the LLM Code Quality Pipeline as a Streamlit web application.

## Hosting model

Use one hosted Streamlit application on Render, with the source code stored in GitHub and the runtime prepared by Docker.

```text
GitHub stores the source code
Docker installs Python, Java, BugsInPy, Defects4J and Python packages
Render runs the Streamlit web service and provides one public URL
```

## Why Docker is required

The application is not only a dashboard. It can also run benchmark commands. A cloud server must therefore contain the same supporting tools used locally:

```text
Python
Java JDK
Git
SVN
Perl / make / unzip
BugsInPy
Defects4J
```

The Dockerfile installs these items into the image. Benchmark workspaces are not committed. A selected bug is checked out only when a user starts a run.

## Render settings

Create a Render Web Service from the GitHub repository and select Docker as the runtime.

Environment variables:

```text
PIPELINE_ALLOW_LOCAL_FALLBACK=false
APP_RUN_PASSWORD=<password for running new benchmark jobs>
PIPELINE_OPENROUTER_API_KEY=<only needed for real OpenRouter runs>
```

The Dockerfile already starts Streamlit with:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501} --server.headless true --server.fileWatcherType none
```

Render runs this command automatically. Supervisors and examiners only open the Render URL in a browser.

## Running new benchmark jobs online

The **Run Benchmark** tab starts a background job instead of blocking the browser request. The job writes status files into `jobs/` and evidence into `workspaces/`.

Typical flow:

```text
Select dataset, project, bug ID and model
Click Start benchmark run
Refresh job status while it runs
Load the completed job in Run Summary / Code Comparison
```

This supports more than the submitted examples because the project and bug dropdowns are discovered from the installed BugsInPy and Defects4J metadata.

## Model testing

The app supports:

```text
mock              repeatable, cost-free model used for pipeline validation
openrouter        real LLM call using PIPELINE_OPENROUTER_API_KEY
```

For OpenRouter, enter the model ID in the UI. This allows testing another model without changing the code.

## Evidence and persistence

The submitted evidence under `evidence/` and `results/` is part of the repository. New online runs are generated under `workspaces/` and `jobs/` at runtime.

For long multi-bug experiments, use persistent storage or download the evidence after each successful run. Cloud services can restart or redeploy; runtime-generated folders may be lost unless persistent storage is configured.
