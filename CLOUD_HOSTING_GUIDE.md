# Cloud hosting guide

This guide describes how to host the LLM Code Quality Pipeline as a Streamlit web application.

## Recommended hosting model

Use one hosted Streamlit application on Render, with the source code stored in GitHub and the runtime prepared by Docker.

```text
GitHub stores the source code
Docker installs Python, Java, BugsInPy, Defects4J and Python packages
Render runs the Streamlit web service and provides one stable public URL
```

## Why Docker is used

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

The Dockerfile installs those items into the image. Benchmark workspaces are not committed. A selected bug is checked out only when a user starts a run.

## Render settings

Create a Render Web Service from the GitHub repository and select Docker as the runtime.

Environment variables:

```text
PIPELINE_ALLOW_LOCAL_FALLBACK=false
APP_RUN_PASSWORD=<optional password for running new benchmarks>
PIPELINE_OPENROUTER_API_KEY=<only needed for real OpenRouter runs>
```

Start command is already defined in the Dockerfile:

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501}
```

Render runs this command automatically. Supervisors and examiners only open the Render URL in a browser.

## App use after deployment

The app has two safe uses:

1. Review the submitted evidence for Python `httpie-1` and Java `Chart-1`.
2. Run a selected benchmark case on demand from the Run Benchmark tab.

For marking, use the included evidence first. New bug runs are supported by the same framework but can fail because older benchmark cases have different dependency and environment requirements.

## Storage note

For repeated online executions, use a Render service with persistent disk. Without persistent storage, generated workspaces can disappear after a restart or redeploy. The submitted evidence remains available because it is included in the repository package under `evidence/`.
