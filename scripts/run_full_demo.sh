#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p logs
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="logs/full_demo_${TIMESTAMP}.log"
STREAMLIT_LOG="logs/streamlit_${TIMESTAMP}.log"
CURRENT_STEP="initialising"

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

log_line "LLM Code Quality Pipeline - full demo"
log_line "Started: $(date)"
log_line "Project folder: $ROOT_DIR"

run_step "1/4 Running backend check" bash scripts/run_backend_check.sh
# shellcheck disable=SC1091
source .venv/bin/activate
run_step "2/4 Installing UI requirements" python -m pip install -r UI_REQUIREMENTS.txt

CURRENT_STEP="3/4 Starting Streamlit"
log_line ""
log_line "[$CURRENT_STEP] STARTED"
nohup streamlit run app.py --server.headless true --server.port 8501 > "$STREAMLIT_LOG" 2>&1 &
echo $! > logs/streamlit.pid
sleep 5
if ! ps -p "$(cat logs/streamlit.pid)" > /dev/null 2>&1; then
  echo "Streamlit did not start. See: $STREAMLIT_LOG" | tee -a "$LOG_FILE"
  fail 1
fi
log_line "[$CURRENT_STEP] PASSED"

CURRENT_STEP="4/4 Opening browser"
log_line ""
log_line "[$CURRENT_STEP] STARTED"
if command -v powershell.exe > /dev/null 2>&1; then
  powershell.exe -NoProfile -Command "Start-Process 'http://localhost:8501'" >> "$LOG_FILE" 2>&1 || true
elif command -v xdg-open > /dev/null 2>&1; then
  xdg-open "http://localhost:8501" >> "$LOG_FILE" 2>&1 || true
fi
log_line "[$CURRENT_STEP] PASSED"

log_line ""
log_line "Full demo completed successfully"
log_line "Streamlit URL: http://localhost:8501"
log_line "Backend log: $LOG_FILE"
log_line "Streamlit log: $STREAMLIT_LOG"
log_line "Stop Streamlit later with: kill \$(cat logs/streamlit.pid)"
