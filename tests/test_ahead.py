#!/usr/bin/env python3
"""A merge built ahead never checks out merge2 under a gate still running there.

    python3 tests/test_ahead.py          (a temp repo, a few seconds)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from _check import check, git, report

from agent_runner import runner as R  # noqa: E402
from agent_runner import plat  # noqa: E402


def make(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'a.py').write_text('# a\n')
    (repo / '.gitignore').write_text('.runner/\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def record(cwd: Path, pid: int) -> Path:
    gates = R.C.notes(R.GATES)
    gates.mkdir(parents=True, exist_ok=True)
    rec = gates / f'{cwd.name}-{pid}.json'
    rec.write_text(json.dumps({'tid': 'T1', 'pid': pid, 'start': plat.started(pid), 'cwd': str(cwd),
                               'out': str(rec.with_suffix('.out'))}), encoding='utf-8')
    return rec


def test_ahead(tmp: Path):
    repo = make(tmp)
    R.init(repo)
    R.log = lambda _: None
    merge2 = R.SLOTS_DIR / 'merge2'

    print('a gate left running in merge2')
    gate = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        rec = record(merge2, gate.pid)
        check(R.ahead_gate_running(), 'reads as running')
        built: list[list[str]] = []
        real, R._build_ahead = R._build_ahead, lambda branch, base, cands: built.append(cands)
        real_poll, R.AHEAD_POLL = R.AHEAD_POLL, 0.05
        R.WAITING.add('T2')
        done = threading.Event()
        t = threading.Thread(target=R.build_ahead, args=('main', 'HEAD', done, set()))
        t.start()
        t.join(0.5)
        check(t.is_alive() and not built, 'a finished task waiting does not build ahead over it')
        done.set()
        t.join(5)
        check(not t.is_alive() and not built, 'and when the turn ends, nothing was built there')

        print('that gate ended')
        gate.kill()
        gate.wait()
        check(not R.ahead_gate_running(), 'a dead gate does not hold merge2')
        done = threading.Event()
        t = threading.Thread(target=R.build_ahead, args=('main', 'HEAD', done, set()))
        t.start()
        t.join(5)
        check(built == [['T2']], 'the merge is built ahead')
        done.set()
        t.join(5)
        rec.unlink()

        print('a gate running in the merge worktree')
        gate2 = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        try:
            rec = record(R.SLOTS_DIR / 'merge', gate2.pid)
            check(not R.ahead_gate_running(), 'does not hold merge2')
            rec.unlink()
        finally:
            gate2.kill()
            gate2.wait()
    finally:
        R._build_ahead, R.AHEAD_POLL = real, real_poll
        R.WAITING.discard('T2')
        if gate.poll() is None:
            gate.kill()
            gate.wait()


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        return report([lambda: test_ahead(Path(t))])


if __name__ == '__main__':
    sys.exit(main())
