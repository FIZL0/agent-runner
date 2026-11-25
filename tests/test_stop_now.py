#!/usr/bin/env python3
"""B827: a stop now ends the whole run within seconds: real run processes, with a merge gate that takes minutes, an
on_exit that hangs and a run that does not answer; the next run resumes the session and lands the merge.

    python3 tests/test_stop_now.py          (temp repos, a fake agent; under a minute)
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report, RUN

from agent_runner import freeze, plat, state as S, stop_now  # noqa: E402
from agent_runner import runner as R  # noqa: E402

SOON = 25.0  # s a stop that takes seconds may take on a busy machine (a gate or hook here sleeps for minutes)
CLAUDE = """#!%s
import os, sys, time
with open(%r, 'a') as f:
    f.write(' '.join(a for a in sys.argv[1:] if len(a) < 60).replace('\\n', ' ') + '\\n')
a = sys.argv[1:]
for k in ('--session-id', '--resume'):
    if k in a:
        sid = a[a.index(k) + 1]
        d = os.path.join(os.environ['CLAUDE_CONFIG_DIR'], 'projects', os.getcwd().replace('/', '-').replace('.', '-'))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, sid + '.jsonl'), 'a').write('{"type": "user", "message": {"content": "x"}}\\n')
time.sleep(600)
"""


def until(f, limit: float = 60.0):
    end = time.monotonic() + limit
    while not (got := f()) and time.monotonic() < end:
        time.sleep(0.1)
    return got


class Project:
    """A project with T1 finished on task/T1 (its gate sleeps while `slow` is there) and T2 open for the one slot."""

    def __init__(self, tmp: Path, more: str = ''):
        self.tmp, self.root, self.runs = tmp, tmp / 'proj', []
        self.slow, self.said, self.gated = tmp / 'slow', tmp / 'said', tmp / 'gated'
        (tmp / 'bin').mkdir()
        (tmp / 'home').mkdir()
        fake = tmp / 'bin' / 'claude'
        fake.write_text(CLAUDE % (sys.executable, str(self.said)), encoding='utf-8')
        fake.chmod(0o755)
        (self.root / 'plan').mkdir(parents=True)
        (self.root / 'plan/TODO.md').write_text(
            '# TODO\n\n### Next\n\n- [ ] **T1** one | files: a.py\n- [ ] **T2** two | files: b.py\n', encoding='utf-8')
        (self.root / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        gate = tmp / 'gate.py'
        gate.write_text('import os, sys, time\nopen(sys.argv[1], "a").write(str(os.getpid()) + "\\n")\n'
                        'while os.path.exists(sys.argv[2]):\n    time.sleep(0.1)\n', encoding='utf-8')
        (self.root / 'runner.toml').write_text(
            f"[run]\ntest = '{sys.executable} {gate} {self.gated} {self.slow}'\nremote = false\nweb = false\ncontrol = false\n"
            f'install_skill = false\nmin_free_gb = 0\nauto_upgrade = false\nslots = 1\nrepair_merges = false\n{more}', encoding='utf-8')
        (self.root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(self.root, 'init', '-q', '-b', 'main')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-qm', 'start')
        git(self.root, 'checkout', '-q', '-b', 'task/T1')
        (self.root / 'a.py').write_text('a\n', encoding='utf-8')
        todo = self.root / 'plan/TODO.md'
        todo.write_text(todo.read_text(encoding='utf-8').replace('- [ ] **T1**', '- [x] **T1**'), encoding='utf-8')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-qm', 'T1: one')
        git(self.root, 'checkout', '-q', 'main')
        self.main = git(self.root, 'rev-parse', 'main').strip()
        self.env = {**{k: v for k, v in os.environ.items() if not k.startswith(('AGENT_RUNNER', 'CLAUDE'))},
                    'HOME': str(tmp / 'home'), 'CLAUDE_CONFIG_DIR': str(tmp / 'home/.claude'), 'AGENT_RUNNER_NO_WEB': '1',
                    'AGENT_RUNNER_NO_NOTIFY': '1', 'AGENT_RUNNER_HOME': str(tmp / 'runs'),
                    'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'cfg'),
                    'PATH': str(tmp / 'bin') + os.pathsep + os.environ['PATH']}

    def notes(self, name: str) -> Path:
        return self.root / '.runner' / name

    def log(self) -> str:
        f = self.notes('run.log')
        return f.read_text(encoding='utf-8') if f.exists() else ''

    def start(self) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, str(RUN), 'run', '1'], cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                             stdout=open(self.tmp / 'out', 'ab'), stderr=subprocess.STDOUT, start_new_session=True)
        self.runs.append(p)
        return p

    def session(self) -> int:
        try:
            return int(self.notes('slot1.live').read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return 0

    def busy(self) -> tuple[subprocess.Popen, int, int]:
        """A run with T1's gate and T2's session under way: (it, the gate's pid, the session's)."""
        self.slow.touch()
        p = self.start()
        ok = until(lambda: self.gated.exists() and self.gated.read_text().strip() and self.session()
                   and self.said.exists() and list((self.tmp / 'home').rglob('*.jsonl')))
        check(ok, 'a gate and a session are under way', self.log() + (self.tmp / 'out').read_text())
        return p, int(self.gated.read_text().split()[-1]), self.session()

    def stop(self, *a: str) -> tuple[subprocess.CompletedProcess, float]:
        t0 = time.monotonic()
        r = subprocess.run([sys.executable, str(RUN), 'stop', *a], cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=120)
        return r, time.monotonic() - t0

    def stopped(self, p, gate: int, agent: int) -> None:
        check(until(lambda: p.poll() is not None, 5), 'the process is gone')
        check(until(lambda: not plat.alive(gate) and not plat.alive(agent), 5), 'the gate and the session too',
              (plat.alive(gate), plat.alive(agent)))
        eq(git(self.root, 'rev-parse', 'main').strip(), self.main, 'main did not move')
        eq(git(self.root, 'status', '--porcelain').strip(), '', 'its checkout is clean')
        for d in (self.root, *(self.tmp / 'runs').rglob('merge')):
            r = subprocess.run(['git', 'rev-parse', '-q', '--verify', 'MERGE_HEAD'], cwd=d, capture_output=True)
            check(r.returncode, f'no half merge in {d.name}')
        check(git(self.root, 'branch', '--list', 'task/T1').strip() and not git(self.root, 'branch', '--list', 'wip/*').strip(),
              'task/T1 waits, not parked', git(self.root, 'branch'))
        check(self.notes('T2.resume').exists(), 'the session is queued to resume', self.log())
        check(not self.notes('STOP').exists() and not self.notes('STOP.force').exists(), 'the stop is over')
        check('run stopped (' in self.log(), 'run.log says so', self.log()[-2000:])
        eq(list(self.notes('gates').glob('*.json')), [], 'no gate is left to adopt')

    def goes_on(self) -> None:
        sid = json.loads(self.notes('T2.resume').read_text())['sid']
        self.slow.unlink()
        p = self.start()
        check(until(lambda: 'T1: merged' in self.log()), 'the next run lands the merge', self.log()[-3000:])
        check(until(lambda: f'--resume {sid}' in self.said.read_text(), 60), 'and resumes the session', self.log()[-3000:])
        r, took = self.stop('--force')
        check(r.returncode == 0 and 'run stopped' in r.stdout and took < SOON, 'and stops', r.stdout + r.stderr)
        check(until(lambda: p.poll() is not None, 5) and (self.root / 'a.py').exists(), 'with T1 on main')

    def close(self) -> None:
        for p in self.runs:
            if p.poll() is None:
                os.kill(p.pid, signal.SIGCONT)
                p.kill()
            p.wait(10)
        for f in (self.gated,):
            for pid in f.read_text().split() if f.exists() else []:
                plat.kill_tree(int(pid))
        if (pid := self.session()) and plat.alive(pid):
            plat.terminate(pid)


def project(tmp: Path, more: str = ''):
    p = Project(tmp, more)
    return p


def test_long_gate(tmp: Path) -> None:
    print('stop --force with a merge gate that takes minutes and an on_exit that hangs: gone in seconds')
    it = project(tmp, f"on_exit = 'touch {tmp}/hooked; sleep 500; touch {tmp}/late'\n")
    try:
        p, gate, agent = it.busy()
        r, took = it.stop('--force')
        check(r.returncode == 0 and r.stdout.strip().endswith('run stopped') and took < SOON, 'run stopped', (r, took))
        check('did not stop by itself' not in r.stdout, 'by itself', r.stdout)
        it.stopped(p, gate, agent)
        check(until((tmp / 'hooked').exists, 10), 'on_exit runs')
        left = json.loads(it.notes('on_exit.json').read_text())
        check(plat.alive(left[0]['pid']), 'detached: it outlives the run')
        r, _ = it.stop('--force')
        check(r.returncode == 1 and 'no run is up' in r.stderr and not it.notes('STOP').exists(), 'no run up: said so', r)
        plat.kill_tree(left[0]['pid'])
        it.goes_on()
    finally:
        it.close()


def test_key(tmp: Path) -> None:
    print('s! typed in the run view: the same, with no command waiting')
    it = project(tmp)
    try:
        p, gate, agent = it.busy()
        with open(it.notes('KEYS'), 'a') as f:
            f.write('s!\n')
        check(until(lambda: p.poll() is not None, SOON), 'the run ends')
        it.stopped(p, gate, agent)
        it.goes_on()
    finally:
        it.close()


def test_hung(tmp: Path) -> None:
    print('a run that does not answer is ended by the command, which does the rest itself')
    it = project(tmp)
    try:
        p, gate, agent = it.busy()
        os.kill(p.pid, signal.SIGSTOP)
        reaper = threading.Thread(target=p.wait, daemon=True)
        reaper.start()
        r, took = it.stop('--force')
        check(r.returncode == 0 and 'did not stop by itself' in r.stdout and r.stdout.strip().endswith('run stopped')
              and took < SOON, 'ended, and said so', (r, took))
        it.stopped(p, gate, agent)
        it.goes_on()
    finally:
        it.close()


def test_busy_loop(tmp: Path) -> None:
    print('a loop held by a slow command (before_start) does not hold the stop')
    it = project(tmp, "before_start = 'sleep 300'\n")
    try:
        it.slow.touch()
        p = it.start()
        check(until(lambda: it.gated.exists() and it.gated.read_text().strip()), 'the gate is under way', it.log())
        time.sleep(1)
        r, took = it.stop('--force')
        check(r.returncode == 0 and 'run stopped' in r.stdout and took < SOON, 'run stopped', (r, took, it.log()[-2000:]))
        check(until(lambda: p.poll() is not None, 5), 'gone')
        check(until(lambda: not plat.alive(int(it.gated.read_text().split()[-1])), 5), 'its gate too')
        check('merge' not in git(it.root, 'status').lower() and git(it.root, 'branch', '--list', 'task/T1').strip(), 'main is as it was')
    finally:
        it.close()


def test_landing(tmp: Path) -> None:
    print('a stop while the main checkout moves: that git command ends, and what landed is recorded')
    it = project(tmp)
    try:
        hook = it.root / '.git/hooks/post-merge'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(f'#!/bin/sh\n[ "$(pwd)" = "{it.root}" ] || exit 0\ntouch {tmp}/landing\nsleep 2\n')
        hook.chmod(0o755)
        p = it.start()
        check(until((tmp / 'landing').exists), 'it is landing', it.log())
        r, took = it.stop('--force')
        check(r.returncode == 0 and 'run stopped' in r.stdout and took < SOON, 'run stopped', (r, took))
        check(until(lambda: p.poll() is not None, 5) and (it.root / 'a.py').exists(), 'landed')
        eq(git(it.root, 'status', '--porcelain').strip(), '', 'the checkout is clean')
        check('T1: merged' in it.log() and not git(it.root, 'branch', '--list', 'task/T1').strip()
              and not it.notes('landed.json').exists(), 'and recorded', it.log()[-2000:])
    finally:
        it.close()


def test_gentle(tmp: Path) -> None:
    print('a gentle stop still waits for the merge under way')
    it = project(tmp)
    try:
        todo = it.root / 'plan/TODO.md'
        todo.write_text('\n'.join(l for l in todo.read_text().splitlines() if 'T2' not in l) + '\n')
        git(it.root, 'commit', '-qam', 'no T2')
        it.slow.touch()
        p = it.start()
        check(until(lambda: it.gated.exists() and it.gated.read_text().strip()), 'the gate is under way', it.log())
        r, _ = it.stop()
        check(r.returncode == 0 and 'asked the run to stop' in r.stdout, 'asked', r)
        time.sleep(3)
        check(p.poll() is None, 'it waits')
        it.slow.unlink()
        check(until(lambda: p.poll() is not None), 'then ends')
        check('T1: merged' in it.log(), 'with the merge landed', it.log()[-2000:])
    finally:
        it.close()


def test_half_merge(tmp: Path) -> None:
    print('clear_merges: a half merge that land began is taken back; a person\'s own stays')
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'a').write_text('0\n')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    git(root, 'checkout', '-q', '-b', 'side')
    (root / 'a').write_text('1\n')
    git(root, 'commit', '-qam', 'side')
    git(root, 'checkout', '-q', 'main')
    (root / 'a').write_text('2\n')
    git(root, 'commit', '-qam', 'main')
    R.init(root)
    half = lambda: not S.git('rev-parse', '-q', '--verify', 'MERGE_HEAD').returncode  # noqa: E731
    with mock.patch.object(S, 'log', lambda *a, **k: None):
        S.git('merge', '-q', '-m', 'T1: the tested merge, onto commits main got during the tests', 'side')
        check(half(), 'half done')
        stop_now.clear_merges()
        eq((half(), (root / 'a').read_text(), git(root, 'status', '--porcelain', '-uno').strip()), (False, '2\n', ''), 'taken back')
        S.git('merge', '-q', '-m', 'mine', 'side')
        stop_now.clear_merges()
        check(half(), "a person's stays")
        S.git('merge', '--abort')


def test_freeze() -> None:
    print('freeze: a merge thread stops at its next git command; one in a held part goes to its end, which quiet waits for')
    order, go, inside = [], threading.Event(), threading.Event()

    def holds():
        with freeze.held():
            inside.set()
            go.wait(20)
            with freeze.git_step(('merge',)):
                order.append('landed')
        with freeze.git_step(('branch',)):
            order.append('went on')

    def merges():
        inside.wait(20)
        go.wait(20)
        with freeze.git_step(('merge',)):
            order.append('never')

    def pauses():
        with freeze.held():
            freeze.pause(1.5)
            order.append('paused on')

    ts = [threading.Thread(target=f, name=f'merge:{f.__name__}', daemon=True) for f in (holds, merges, pauses)]
    for t in ts:
        t.start()
    try:
        check(inside.wait(20), 'in its part')
        until(lambda: len(freeze.BUSY) == 1, 10)
        check(freeze.stop(), 'this thread stops')
        eq(freeze.quiet(0.2), False, 'a held part is waited for')
        go.set()
        eq(freeze.quiet(20), True, 'it ends')
        time.sleep(2)
        eq(order, ['landed'], 'and nothing else happened')
        got = []
        t = threading.Thread(target=lambda: got.append(freeze.stop()))
        t.start()
        t.join()
        eq((got, freeze.stop()), ([False], True), 'one thread stops the run')
        with freeze.git_step(('status',)):
            order.append('own git')
        check('own git' in order, 'the stopping thread uses git')
    finally:
        freeze.STOPPER.clear()


def test_page(tmp: Path) -> None:
    print('asked by the run\'s own page: a process of its own does it, and the page is answered at once')
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    R.init(root)
    rec, spawned, said = {'pid': 4242, 'start': None}, [], []
    with mock.patch.object(S, 'run_up', lambda: True), mock.patch.object(stop_now, 'the_run', lambda: rec), \
            mock.patch.object(plat, 'spawn_detached', lambda argv, **k: spawned.append((argv, k))), \
            mock.patch.object(stop_now, 'say', lambda t, err=False: said.append(t)), \
            mock.patch.dict(os.environ, {stop_now.FROM: '4242'}):
        eq(stop_now.command('suspend'), 0, 'answered')
    check(len(spawned) == 1 and spawned[0][0][-3:] == ['stop', '--force', '--suspend'], 'the same command', spawned)
    check(stop_now.FROM not in spawned[0][1]['env'] and not S.forced(), 'which asks and waits', spawned)
    eq(said, ['stopping the run now'], 'said')


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            f(Path(d).resolve())
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    runs = [] if plat.WINDOWS else [test_long_gate, test_key, test_hung, test_busy_loop, test_landing, test_gentle]
    sys.exit(report([test_freeze, *map(in_tmp, [test_half_merge, test_page, *runs])]))
