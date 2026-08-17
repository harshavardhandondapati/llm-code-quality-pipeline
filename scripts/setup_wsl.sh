#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

mkdir -p tools workspaces results logs

if [ ! -d tools/BugsInPy ]; then
  git clone https://github.com/soarsmu/BugsInPy.git tools/BugsInPy
fi

if command -v dos2unix >/dev/null 2>&1; then
  find tools/BugsInPy/framework/bin -type f -maxdepth 1 -print0 | xargs -0 dos2unix >/dev/null 2>&1 || true
fi
chmod +x tools/BugsInPy/framework/bin/* || true

if [ ! -f .env ]; then
  cp .env.example .env
fi

BUGSINPY_BIN="$ROOT/tools/BugsInPy/framework/bin"
python - <<PY
from pathlib import Path
path = Path('.env')
lines = path.read_text(encoding='utf-8').splitlines()
values = {
    'PIPELINE_BUGSINPY_EXECUTABLE_DIRECTORY': r'$BUGSINPY_BIN',
    'PIPELINE_TEST_TIMEOUT_SECONDS': '2400',
}
seen = set()
new_lines = []
for line in lines:
    key = line.split('=', 1)[0] if '=' in line else None
    if key in values:
        new_lines.append(f'{key}={values[key]}')
        seen.add(key)
    else:
        new_lines.append(line)
for key, value in values.items():
    if key not in seen:
        new_lines.append(f'{key}={value}')
path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
PY

echo "WSL setup completed. BugsInPy bin: $BUGSINPY_BIN"
