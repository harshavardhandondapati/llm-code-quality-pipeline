#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="logs/backend_check_${TIMESTAMP}.log"
SUMMARY_FILE="logs/backend_check_summary_${TIMESTAMP}.txt"
CURRENT_STEP="initialising"

log_line() {
  echo "$1" | tee -a "$LOG_FILE"
}

fail() {
  local code="$1"
  echo "" | tee -a "$LOG_FILE"
  echo "FAILED STEP: ${CURRENT_STEP}" | tee -a "$LOG_FILE"
  echo "LOG FILE: ${LOG_FILE}" | tee -a "$LOG_FILE"
  {
    echo "Backend check failed"
    echo "Failed step: ${CURRENT_STEP}"
    echo "Log file: ${LOG_FILE}"
    echo "Exit code: ${code}"
  } > "$SUMMARY_FILE"
  exit "$code"
}
trap 'fail $?' ERR

run_step() {
  CURRENT_STEP="$1"
  shift
  log_line ""
  log_line "[$CURRENT_STEP] STARTED"
  "$@" 2>&1 | tee -a "$LOG_FILE"
  local status=${PIPESTATUS[0]}
  if [[ "$status" -ne 0 ]]; then
    fail "$status"
  fi
  log_line "[$CURRENT_STEP] PASSED"
}

log_line "LLM Code Quality Pipeline - backend check"
log_line "Started: $(date)"
log_line "Project folder: $ROOT_DIR"

run_step "1/10 Checking Python version" python -c "import sys; print(sys.version); raise SystemExit(0 if sys.version_info[:2] == (3, 10) else 1)"

if [[ ! -x ".venv/bin/python" ]]; then
  run_step "2/10 Creating virtual environment" python -m venv .venv
else
  log_line ""
  log_line "[2/10 Creating virtual environment] SKIPPED - .venv already exists"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

run_step "3/10 Upgrading pip" python -m pip install --upgrade pip
run_step "4/10 Installing project" python -m pip install -e ".[dev]"

if [[ ! -f ".env" ]]; then
  run_step "5/10 Creating .env" cp .env.example .env
else
  log_line ""
  log_line "[5/10 Creating .env] SKIPPED - .env already exists"
fi

run_step "6/10 Setting up BugsInPy" bash scripts/setup_wsl.sh
run_step "7/10 Verifying WSL and BugsInPy setup" python scripts/verify_wsl_setup.py
run_step "8/10 Running unit tests" python -m pytest -q --color=no
run_step "9/10 Running full mock pipeline" bash scripts/run_mock_pipeline.sh
run_step "10/10 Showing result summary" python scripts/show_results.py --candidate-report results/bugsinpy_candidate_selection.json

{
  echo "Backend check completed successfully"
  echo "Project folder: $ROOT_DIR"
  echo "Log file: $LOG_FILE"
  echo "Candidate report: results/bugsinpy_candidate_selection.json"
  echo "Run Streamlit with: streamlit run app.py"
} > "$SUMMARY_FILE"

log_line ""
log_line "Backend check completed successfully"
log_line "SUMMARY FILE: $SUMMARY_FILE"
