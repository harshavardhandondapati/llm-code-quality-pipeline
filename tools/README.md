# Benchmark Tools

This folder is used by the cloud runner to install benchmark tools during deployment.

The full BugsInPy and Defects4J repositories are not committed to GitHub because they are large external tools.

During Docker/Render deployment, the script below installs them automatically:

scripts/prepare_benchmark_tools.sh
