#!/usr/bin/env python3
"""tools/windows_vm.sh against a stand-in docker, ssh and scp: no VM, no network. Its "VM" is this machine.

    python3 tests/test_windows_vm.py
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _check import ROOT, check, eq, git, has, report

SCRIPT = ROOT / 'tools/windows_vm.sh'
DOCKER = '''#!/bin/sh
echo "docker $*" >> "$FAKE/calls"
case "$*" in
  "container inspect -f"*) cat "$FAKE/running" ;;
  "container inspect $FAKE_VM") exit 0 ;;
  "container inspect"*) exit 1 ;;
  start*) echo true > "$FAKE/running" ;;
  stop*) echo false > "$FAKE/running" ;;
esac
'''
# skips ssh's options, then runs the command here
SSH = '''#!/bin/sh
echo "ssh $*" >> "$FAKE/calls"
[ -e "$FAKE/ssh-down" ] && { echo "Connection refused" >&2; exit 255; }
while [ $# -gt 0 ]; do case "$1" in -i|-o|-p) shift 2 ;; *) break ;; esac; done
shift
exec sh -c "$*"
'''
SCP = '''#!/bin/sh
echo "scp $*" >> "$FAKE/calls"
while [ $# -gt 0 ]; do case "$1" in -i|-o|-P) shift 2 ;; -q) shift ;; *) break ;; esac; done
for to; do :; done
while [ $# -gt 1 ]; do cp "$1" "${to#*:}" || exit 1; shift; done
'''


class Vm:
    def __init__(self, running='true'):
        self.d = Path(tempfile.mkdtemp(prefix='vm-'))
        bin_ = self.d / 'bin'
        bin_.mkdir()
        for n, t in (('docker', DOCKER), ('ssh', SSH), ('scp', SCP)):
            (bin_ / n).write_text(t, encoding='utf-8')
            (bin_ / n).chmod(0o755)
        (self.d / 'running').write_text(running + '\n')
        (self.d / 'key').write_text('no key')
        self.vmtmp = self.d / 'vmtmp'
        self.vmtmp.mkdir()
        self.repo = self.d / 'proj'
        (self.repo / 'tools').mkdir(parents=True)
        (self.repo / 'tests').mkdir()
        shutil.copy(SCRIPT, self.repo / 'tools')
        (self.repo / 'tests/test_windows.py').write_text('print("committed")\n')
        git(self.repo, 'init', '-q')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'start')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('WINDOWS_VM')}
        self.env.update(PATH=f'{bin_}{os.pathsep}{os.environ["PATH"]}', FAKE=str(self.d), FAKE_VM='windows-vm',
                        TMPDIR=str(self.vmtmp), WINDOWS_VM_KEY=str(self.d / 'key'),
                        WINDOWS_VM_PYTHON=sys.executable)

    def cmd(self, *a):
        return [str(self.repo / 'tools/windows_vm.sh'), *a]

    def run(self, *a, **env):
        return subprocess.run(self.cmd(*a), env={**self.env, **env}, capture_output=True, text=True, timeout=120)

    def calls(self) -> str:
        f = self.d / 'calls'
        return f.read_text() if f.exists() else ''

    def clean(self, what):
        eq([p.name for p in self.vmtmp.iterdir()], [], f'{what}: the temp folders are gone')


def test_missing():
    print('no VM: one line, non-zero, nothing started')
    vm = Vm()
    for what, env, pat in (('no container', {'WINDOWS_VM': 'other'}, 'no Docker container other'),
                           ('no key', {'WINDOWS_VM_KEY': str(vm.d / 'nokey')}, 'no ssh key at .*nokey')):
        r = vm.run(**env)
        eq(r.returncode, 2, f'{what}: exit 2')
        has(r.stderr, pat, f'{what}: says so')
        eq(len(r.stderr.splitlines()), 1, f'{what}: in one line')
    r = vm.run('tests/nope.py')
    eq(r.returncode, 2, 'a test file that is not there: exit 2')
    check(not any(w in vm.calls() for w in ('docker start', 'docker run', 'docker create', 'ssh ')),
          'nothing was started, created or connected to', vm.calls())


def test_run():
    print('a running VM: committed, changed and new files go over, the exit code comes back')
    vm = Vm()
    r = vm.run()
    eq(r.returncode, 0, 'the default file passes')
    has(r.stdout, '^== tests/test_windows.py\ncommitted$', 'its output is printed')
    calls = vm.calls()
    known = vm.d / 'known_hosts'
    has(calls, rf'^ssh -i {vm.d}/key .*-o UserKnownHostsFile={known} .*-p 2222 runner@127\.0\.0\.1 exit 0$', 'ssh line')
    has(calls, rf'^scp -q -i {vm.d}/key .*-P 2222 .* runner@127\.0\.0\.1:{vm.vmtmp}/windows-vm-\w+/$', 'scp line')
    has(calls, r'python\S* -X utf8 "\S+/run\.py"$', 'Python in UTF-8 mode')
    check('docker start' not in calls and 'docker stop' not in calls, 'a VM that was up is left up')
    vm.clean('pass')

    (vm.repo / 'tests/test_windows.py').write_text('print("changed")\n')
    (vm.repo / 'tests/test_new.py').write_text(
        'import os, sys\nprint("utf8", sys.flags.utf8_mode, os.environ["PYTHONUTF8"], "→")\nsys.exit(7)\n',
        encoding='utf-8')
    before = git(vm.repo, 'status', '--porcelain')
    r = vm.run('tests/test_new.py', 'tests/test_windows.py', WINDOWS_VM_PORT='99', WINDOWS_VM_USER='u',
               WINDOWS_VM_HOST='h')
    eq(r.returncode, 7, "the failing file's exit code")
    has(r.stdout, '^utf8 1 1 →$', 'an uncommitted new file runs, in UTF-8 mode')
    has(r.stdout, '^changed$', 'the uncommitted change is there, and the file after a failure still runs')
    has(vm.calls(), r'-p 99 u@h exit 0$', 'port, user and host from the environment')
    eq(git(vm.repo, 'status', '--porcelain'), before, "the worktree's index is untouched")
    vm.clean('fail')


def test_start_stop():
    print('a stopped VM is started, and stopped again unless --keep')
    vm = Vm('false')
    r = vm.run()
    eq(r.returncode, 0, 'passes')
    has(vm.calls(), '(?s)docker start windows-vm$.*docker stop -t 120 windows-vm$', 'started, then stopped')
    vm = Vm('false')
    vm.run('--keep')
    check('docker start' in vm.calls() and 'docker stop' not in vm.calls(), '--keep leaves it up', vm.calls())
    vm = Vm('false')
    (vm.d / 'ssh-down').touch()
    r = vm.run(WINDOWS_VM_WAIT='0')
    eq(r.returncode, 2, 'no ssh in time: exit 2')
    has(r.stderr, 'no ssh to windows-vm after 0s: Connection refused', 'and says why')
    has(vm.calls(), 'docker stop', 'and stops what it started')


def until(ok, what):
    end = time.monotonic() + 60
    while not ok() and time.monotonic() < end:
        time.sleep(0.05)
    check(ok(), what)


def test_lock_and_signal():
    print('two callers: the second waits; a signal cleans up')
    vm = Vm('false')
    (vm.repo / 'tests/test_windows.py').write_text(
        'import os, time\nopen(os.environ["FAKE"] + "/in", "w").close()\n'
        'while os.path.exists(__file__): time.sleep(0.1)  # until its folder is removed\n')
    (vm.repo / 'tests/test_ok.py').write_text('print("ok")\n')
    first = subprocess.Popen(vm.cmd(), env=vm.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    until(lambda: (vm.d / 'in').exists(), 'the first caller is in its tests')
    n = vm.calls().count('docker container inspect -f')
    err = vm.d / 'err'
    with err.open('w') as f:
        second = subprocess.Popen(vm.cmd('tests/test_ok.py'), env=vm.env, stdout=subprocess.DEVNULL, stderr=f)
    until(lambda: 'waiting' in err.read_text(), 'the second says it waits')
    eq(vm.calls().count('docker container inspect -f'), n, 'and does not look at the VM yet')
    first.send_signal(signal.SIGTERM)
    eq(first.wait(60), 143, 'a TERM ends the first at once')
    eq(second.wait(60), 0, 'then the second runs')
    eq(vm.calls().count('docker stop'), 2, 'each stopped the VM it started')


def main() -> int:
    if os.name == 'nt' or not shutil.which('flock'):
        print('skipped: windows_vm.sh runs on a Linux machine that has the VM')
        return 0
    return report([test_missing, test_run, test_start_stop, test_lock_and_signal])


if __name__ == '__main__':
    sys.exit(main())
