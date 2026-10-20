#!/usr/bin/env bash
# agent-runner's demo: copy examples/hello into a scratch repo (with a bare repo as its "origin") and show
# what the runner sees. With --run it then does one real task with Claude Code (`run run once`).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
run="$here/../run"
dir="$(mktemp -d "${TMPDIR:-/tmp}/agent-runner-demo.XXXXXX")"
git init -q --bare -b main "$dir/origin.git"
cp -r "$here/hello" "$dir/hello"
cd "$dir/hello"
git init -q -b main
git add -A
git -c user.name=demo -c user.email=demo@example.invalid commit -qm "hello: the example repo"
git remote add origin "$dir/origin.git"
git push -q -u origin main
echo "== demo repo: $dir/hello"
echo
echo '== run plan                  (the index: every heading and task id)'
"$run" plan
echo
echo '== run plan brief F2         (what a session for F2 starts from)'
"$run" plan brief F2
echo
echo '== run run --dry-run 3       (what three free slots would start now)'
"$run" run --dry-run 3
if [[ "${1:-}" == "--run" ]]; then
  echo
  echo '== run run once              (one real task, in this checkout)'
  "$run" run once
  git log --oneline -3
fi
