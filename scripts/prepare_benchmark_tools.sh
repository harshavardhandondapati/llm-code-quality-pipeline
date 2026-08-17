#!/usr/bin/env bash
set -euo pipefail

TOOLS_DIR="${1:-${PIPELINE_TOOLS_DIRECTORY:-tools}}"
TOOLS_DIR="$(mkdir -p "$TOOLS_DIR" && cd "$TOOLS_DIR" && pwd)"

echo "Using benchmark tools directory: $TOOLS_DIR"

if [ ! -d "$TOOLS_DIR/BugsInPy/.git" ]; then
  rm -rf "$TOOLS_DIR/BugsInPy"
  git clone --depth 1 https://github.com/soarsmu/BugsInPy.git "$TOOLS_DIR/BugsInPy"
else
  echo "BugsInPy already exists."
fi

if [ ! -d "$TOOLS_DIR/defects4j/.git" ]; then
  rm -rf "$TOOLS_DIR/defects4j"
  git clone https://github.com/rjust/defects4j.git "$TOOLS_DIR/defects4j"
else
  echo "Defects4J already exists."
fi

cd "$TOOLS_DIR/defects4j"

echo "Installing Defects4J Perl dependencies..."
cpanm --notest --installdeps .
cpanm --notest DBI DBD::CSV JSON DateTime List::MoreUtils

echo "Initialising Defects4J project repositories..."
./init.sh

echo "Verifying Defects4J Chart metadata..."
"$TOOLS_DIR/defects4j/framework/bin/defects4j" info -p Chart >/tmp/defects4j_chart_info.txt

echo "Verifying Defects4J available projects..."
"$TOOLS_DIR/defects4j/framework/bin/defects4j" pids >/tmp/defects4j_pids.txt

cat <<EOF2
Benchmark tools are ready.

BugsInPy:
$TOOLS_DIR/BugsInPy

Defects4J:
$TOOLS_DIR/defects4j

Defects4J verification:
$(head -20 /tmp/defects4j_chart_info.txt)
EOF2
