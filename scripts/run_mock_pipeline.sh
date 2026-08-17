#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing .venv. Run bash scripts/run_backend_check.sh first."
  exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate
COMMAND=(python scripts/run_pipeline.py --project httpie --bug-id 1 --provider mock --model mock-model --approval approved --reviewer "Hari")
echo "Command: ${COMMAND[*]}"
"${COMMAND[@]}"
python scripts/check_latest_pipeline_status.py --candidate-report results/bugsinpy_candidate_selection.json
