"""B220: a run that starts with Remote Control off ends the control server it finds, also one under its own key."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

os.environ.pop('CLAUDE_CODE_SESSION_ID', None)  # not the session running this

from agent_runner import control as K, runner as R  # noqa: E402


def repo() -> Path:
    d = Path(tempfile.mkdtemp(prefix='agent-runner-remote-off-'))
    git(d, 'init', '-q')
    (d / '.gitignore').write_text('.runner/\n')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def test_start_ends_server():
    print("B220: a restart in place keeps the run's key; its start ends a recorded control server when remote or "
          'control is off, and keeps it when both are on. A control session stays up')
    R.init(repo())
    gone = subprocess.Popen([sys.executable, '-c', 'pass'])
    gone.wait()
    was = R.C.run['control']
    for run_pid, key in ((os.getpid(), "this run's key"), (gone.pid, "an earlier run's key")):
        for remote, control in ((False, True), (True, False), (True, True)):
            what = f'{key}, remote {remote}, control {control}'
            procs = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(2)]
            for p in procs:  # reaped when they end
                threading.Thread(target=p.wait, daemon=True).start()
            server, session = procs
            recs = [R.rc_record('server', 'demo · control', server.pid, run_pid),
                    R.rc_record('control', 'demo · control 1', session.pid, run_pid)]
            try:
                R.C.run['control'] = control
                with mock.patch.object(K, 'remote_on', lambda: remote):
                    R.rc_sweep_start()
                    end = time.monotonic() + 30
                    while any(t.name == 'remote-sweep' for t in threading.enumerate()) and time.monotonic() < end:
                        time.sleep(0.05)
                keep = remote and control
                eq(R.plat.alive(server.pid), keep, f'{what}: the server is {"kept" if keep else "ended"}')
                eq(recs[0].exists(), keep, f'{what}: its record is {"kept" if keep else "dropped"}')
                check(R.plat.alive(session.pid), f"{what}: the person's control session stays up")
            finally:
                R.C.run['control'] = was
                for p in procs:
                    if p.poll() is None:
                        p.kill()
                for f in recs:
                    f.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(report([test_start_ends_server]))
