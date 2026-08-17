#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="logs/openrouter_pipeline_${TIMESTAMP}.log"
CURRENT_STEP="initialising"
MODEL_NAME="${1:-openrouter/free}"

log_line() {
  echo "$1" | tee -a "$LOG_FILE"
}

fail() {
  local code="$1"
  echo "" | tee -a "$LOG_FILE"
  echo "FAILED STEP: ${CURRENT_STEP}" | tee -a "$LOG_FILE"
  echo "LOG FILE: ${LOG_FILE}" | tee -a "$LOG_FILE"
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

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run bash scripts/run_backend_check.sh first."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [[ ! -f ".env" ]]; then
  echo "Missing .env. Run cp .env.example .env and add PIPELINE_OPENROUTER_API_KEY."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${PIPELINE_OPENROUTER_API_KEY:-}" || "${PIPELINE_OPENROUTER_API_KEY:-}" == "your_api_key_here" ]]; then
  echo "OpenRouter API key is missing. Add PIPELINE_OPENROUTER_API_KEY to .env."
  exit 1
fi

log_line "LLM Code Quality Pipeline - OpenRouter real LLM run"
log_line "Model: $MODEL_NAME"
log_line "Started: $(date)"
run_step "1/4 Verifying setup" python scripts/verify_wsl_setup.py
run_step "2/4 Running OpenRouter pipeline" python scripts/run_pipeline.py --project httpie --bug-id 1 --provider openrouter --model "$MODEL_NAME" --approval approved --reviewer "Hari"
run_step "3/4 Checking repair status" python scripts/check_latest_pipeline_status.py --candidate-report results/bugsinpy_candidate_selection.json
run_step "4/4 Showing result summary" python scripts/show_results.py --candidate-report results/bugsinpy_candidate_selection.json
log_line ""
log_line "OpenRouter pipeline run completed successfully."
log_line "LOG FILE: $LOG_FILE"
