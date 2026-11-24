#!/usr/bin/env bash
# agent-runner's demo: make the example project (`run demo`) in a scratch folder and show what the runner sees.
# With --run it then does one real task with Claude Code (`run run once`).
set -euo pipefail
run="$(cd "$(dirname "$0")" && pwd)/../run"
dir="$(mktemp -d "${TMPDIR:-/tmp}/agent-runner-demo.XXXXXX")/hello"
"$run" demo "$dir"
cd "$dir"
echo
echo '== run plan                  (the index: every heading and task id)'
"$run" plan
echo
echo '== run plan brief F5         (what a session for F5 starts from)'
"$run" plan brief F5
echo
echo '== run run --dry-run 3       (what three free slots would start now)'
"$run" run --dry-run 3
if [[ "${1:-}" == "--run" ]]; then
  echo
  echo '== run run once              (one real task, in this checkout)'
  "$run" run once
  git log --oneline -3
fi
