#!/usr/bin/env bash
# Runs test files of this worktree (its commits and its uncommitted changes) on a Windows VM this machine
# already has: a Docker container with Windows, sshd, Python and git inside. It never creates or changes a VM.
#
#   tools/windows_vm.sh [--keep] [test file ...]        (default: tests/test_windows.py)
#   tools/windows_vm.sh [--keep] --all                  (every tests/test_*.py)
#
#   --keep   leave the container up when this script started it
#   --all    say how long each file took, and end with one line that names the failed files
#
# Exit code: the first failing test file's; 2 for a setup problem (no VM, no key, no such file), said in one line.
# Environment, with the defaults:
#   WINDOWS_VM              windows-vm                        the container
#   WINDOWS_VM_KEY          ~/.local/share/windows-vm/key     the ssh key
#   WINDOWS_VM_KNOWN_HOSTS  known_hosts beside the key
#   WINDOWS_VM_LOCK         lock beside the key               one caller at a time
#   WINDOWS_VM_USER, WINDOWS_VM_HOST, WINDOWS_VM_PORT         runner, 127.0.0.1, 2222
#   WINDOWS_VM_PYTHON       python                            Python on the VM
#   WINDOWS_VM_WAIT         300                               seconds to wait for ssh
set -uo pipefail

vm=${WINDOWS_VM:-windows-vm}
key=${WINDOWS_VM_KEY:-$HOME/.local/share/windows-vm/key}
known=${WINDOWS_VM_KNOWN_HOSTS:-$(dirname "$key")/known_hosts}
lock=${WINDOWS_VM_LOCK:-$(dirname "$key")/lock}
host=${WINDOWS_VM_USER:-runner}@${WINDOWS_VM_HOST:-127.0.0.1}
port=${WINDOWS_VM_PORT:-2222}
python=${WINDOWS_VM_PYTHON:-python}
wait_s=${WINDOWS_VM_WAIT:-300}

say() { echo "windows_vm: $*" >&2; }
die() { say "$*"; exit 2; }

keep='' all='' files=()
for a in "$@"; do
  case $a in
    --keep) keep=1 ;;
    --all) all=1 ;;
    -h|--help) sed -n '2,/^set /{/^#/s/^# \{0,1\}//p}' "$0"; exit 0 ;;
    -*) die "unknown option $a" ;;
    *) files+=("$a") ;;
  esac
done
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || die 'not in a git checkout'
if [ -n "$all" ]; then
  [ ${#files[@]} -eq 0 ] || die '--all takes no test files'
  for f in "$root"/tests/test_*.py; do files+=("${f#"$root/"}"); done
fi
[ ${#files[@]} -gt 0 ] || files=(tests/test_windows.py)
for f in "${files[@]}"; do
  case $f in /*|*..*) die "test files are named from the repo's root: $f" ;; esac
  [ -f "$root/$f" ] || die "no such test file: $f"
done
for c in docker flock ssh scp; do
  command -v "$c" >/dev/null || die "no $c on this machine, so no Windows VM to use"
done
[ -f "$key" ] || die "no ssh key at $key (WINDOWS_VM_KEY): no Windows VM to use"
docker version >/dev/null 2>&1 || die 'Docker does not answer (docker version fails): no Windows VM to use'
docker container inspect "$vm" >/dev/null 2>&1 || die "no Docker container $vm (WINDOWS_VM): no Windows VM to use"

opts=(-i "$key" -o IdentitiesOnly=yes -o BatchMode=yes -o "UserKnownHostsFile=$known"
      -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 -o ServerAliveInterval=15 -o LogLevel=ERROR)
# 9>&-: the lock is this script's alone, so nothing it leaves running can hold it
vm_ssh() { ssh "${opts[@]}" -p "$port" "$host" "$@" 9>&-; }

started='' tmp='' dir='' child='' last=''
cleanup() {
  code=$?
  trap - EXIT
  trap '' INT TERM HUP
  [ -z "$child" ] || kill "$child" 2>/dev/null
  if [ -n "$dir" ]; then
    # the folder is named on stdin's first lines of code, so no shell on the VM reads it; a run cut off here
    # may still hold files open, so its process tree is ended first
    vm_ssh "$python -X utf8 -" <<PY || say "could not remove $dir on the VM"
import os, shutil, stat, subprocess, time
d = r'''$dir'''
pid = os.path.join(d, 'pid')
if os.name == 'nt' and os.path.exists(pid):
    subprocess.run(['taskkill', '/T', '/F', '/PID', open(pid).read()], capture_output=True)
def writable(fn, path, _):
    os.chmod(path, stat.S_IRWXU)  # git's object files are read-only
    fn(path)
for i in range(5):
    try:
        shutil.rmtree(d, onerror=writable)
        break
    except OSError:
        if i == 4:
            raise
        time.sleep(1)
PY
  fi
  [ -z "$tmp" ] || rm -rf -- "$tmp"
  if [ -n "$started" ] && [ -z "$keep" ]; then
    say "stopping $vm"
    docker stop -t 120 "$vm" >/dev/null || say "could not stop $vm"
  fi
  [ -z "$last" ] || echo "$last"
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

exec 9>"$lock" || die "cannot write the lock $lock"
if ! flock -n 9; then
  say "another caller is using $vm: waiting"
  flock 9 & child=$!
  wait "$child" || die "cannot lock $lock"
  child=''
fi

if [ "$(docker container inspect -f '{{.State.Running}}' "$vm")" != true ]; then
  say "starting $vm"
  started=1
  docker start "$vm" >/dev/null || die "could not start $vm"
fi
end=$((SECONDS + wait_s))
until err=$(vm_ssh 'exit 0' 2>&1 </dev/null); do
  [ "$SECONDS" -lt "$end" ] || die "no ssh to $vm after ${wait_s}s: ${err##*$'\n'}"
  sleep 2
done

tmp=$(mktemp -d) || die 'cannot make a temp folder'
git -C "$root" bundle create -q "$tmp/repo.bundle" HEAD || die 'git bundle failed'
# the uncommitted diff, new files too: staged in a copy of the index, so the real one is left alone
cp "$(git -C "$root" rev-parse --path-format=absolute --git-path index)" "$tmp/index" || die 'no git index'
GIT_INDEX_FILE=$tmp/index git -C "$root" add -A || die 'git add failed'
GIT_INDEX_FILE=$tmp/index git -C "$root" diff --cached --binary --no-color --no-ext-diff --no-textconv HEAD \
  >"$tmp/work.diff" || die 'git diff failed'
printf '%s\n' "${files[@]}" >"$tmp/files.txt"
cat >"$tmp/run.py" <<'PY'
import os, pathlib, subprocess, sys, time
here = pathlib.Path(__file__).resolve().parent
(here / 'pid').write_text(str(os.getpid()))
src, temp = here / 'repo', here / 'temp'
src.mkdir()
temp.mkdir()
def git(*a):
    if subprocess.run(['git', *a], cwd=src).returncode:
        print('windows_vm: git ' + a[0] + ' failed on the VM', file=sys.stderr)
        sys.exit(2)
git('init', '-q')
git('config', 'core.autocrlf', 'false')  # so the diff applies whatever git on the VM is set to
git('fetch', '-q', str(here / 'repo.bundle'), 'HEAD')
git('checkout', '-q', '-B', 'work', 'FETCH_HEAD')
if (here / 'work.diff').stat().st_size:
    git('apply', '--whitespace=nowarn', str(here / 'work.diff'))
env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1', **dict.fromkeys(('TEMP', 'TMP', 'TMPDIR'), str(temp)))
code = 0
files, failed = (here / 'files.txt').read_text(encoding='utf-8').splitlines(), []
for f in files:
    print('== ' + f, flush=True)
    t = time.monotonic()
    c = subprocess.run([sys.executable, '-X', 'utf8', f], cwd=src, env=env, stdin=subprocess.DEVNULL).returncode
    code = code or (c if 0 <= c < 255 else 1)  # ssh's own failure is 255
    if c:
        failed.append(f)
    if 'all' in sys.argv:
        print(f"-- {f}: {'failed' if c else 'passed'}, {time.monotonic() - t:.1f}s", flush=True)
(here / 'last').write_text(f'{len(failed)} of {len(files)} files failed: ' + ' '.join(failed) if failed
                           else f'all {len(files)} files passed')
sys.exit(code)
PY

out=$(vm_ssh "$python -X utf8 -" <<'PY'
import pathlib, tempfile
print(pathlib.Path(tempfile.mkdtemp(prefix='windows-vm-')).resolve().as_posix())
PY
) || die "no working $python on $vm (WINDOWS_VM_PYTHON)"
out=${out//$'\r'/}
out=${out##*$'\n'}
# cleanup deletes this folder, so only a name of our own is taken
[[ $out =~ ^[^\']*/windows-vm-[A-Za-z0-9_]+$ ]] || die "unexpected temp folder on $vm: $out"
dir=$out
scp -q "${opts[@]}" -P "$port" "$tmp/repo.bundle" "$tmp/work.diff" "$tmp/files.txt" "$tmp/run.py" "$host:$dir/" 9>&- \
  || die "could not copy the worktree to $vm"
# in the background: a signal to this script is then handled at once, not when the tests end
vm_ssh "$python -X utf8 \"$dir/run.py\"${all:+ all}" </dev/null & child=$!
wait "$child"
code=$?
child=''
if [ -n "$all" ]; then  # printed at the very end, by cleanup
  last=$(vm_ssh "$python -X utf8 -" <<PY
print(open(r'''$dir/last''').read())
PY
  ) || last="did not finish: see the output above"
  last="windows_vm: ${last//$'\r'/}"
fi
exit "$code"
