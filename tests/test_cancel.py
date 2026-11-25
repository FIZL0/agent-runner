#!/usr/bin/env python3
"""F426d: `plan cancel`: a running task's agent is stopped, its work kept on wip/ID and the task parked; unparked, it
starts again and is pointed at that work; refused while it lands.

    python3 tests/test_cancel.py          (temp repos, some seconds)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import ROOT, RUN, check, eq, git, has, report
from _loop_patch import patched

from agent_runner import cancel, loop, loop_requests, sched, state
from agent_runner import plan as P
from agent_runner import runner as R


class Proj:
    """A repo with a remote, whose run this test stands in for (it holds run.lock while in use)."""

    def __init__(self, tmp: Path):
        self.repo, self.origin = tmp / f'proj-{tmp.name}', tmp / 'origin.git'
        git(tmp, 'init', '-q', '--bare', '-b', 'main', str(self.origin))
        self.repo.mkdir(parents=True)
        git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / 'plan').mkdir()
        (self.repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **H1** one thing | files: a.py\n'
                                                '- [ ] **H2** another | files: b.py\n', encoding='utf-8')
        (self.repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (self.repo / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\n')
        (self.repo / '.gitignore').write_text('.runner/\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'start')
        git(self.repo, 'remote', 'add', 'origin', str(self.origin))
        git(self.repo, 'push', '-q', 'origin', 'main')
        R.init(self.repo)
        self.lock = R.plat.lock(R.C.notes('run.lock'))
        self.procs, self.running, self.tried = {}, {}, set()
        self.free_at = {1: dt.datetime.max}
        self.agent = None

    def start(self, commits: int = 1, edits: bool = True) -> Path:
        """Slot 1 runs H1 since 14 min."""
        d = R.worktree(1, 'main')
        git(d, 'checkout', '-q', '-B', 'task/H1', 'main')
        for i in range(commits):
            (d / f'a{i}.py').write_text('x\n')
            git(d, 'add', '-A')
            git(d, 'commit', '-qm', f'H1 part {i}')
        if edits:
            (d / 'half.py').write_text('half\n')
        self.agent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
        self.procs, self.running = {1: (self.agent.pid, 'sid', None)}, {1: ('H1', 'Next', {'a.py'}, set())}
        self.state({'running': {'1': 'H1'}, 'since': {'1': time.time() - 14 * 60 - 5}, 'merging': []})
        return d

    def state(self, st: dict) -> None:
        R.C.notes('STATE').write_text(json.dumps(st), encoding='utf-8')

    def tick(self) -> None:
        with patched(end_orphans=lambda: None):
            loop.halts(self.procs, self.running, self.free_at, self.tried, 'main', 'm', 30, 1)
        if not self.running and R.C.notes('STATE').exists():  # a run writes STATE every tick
            st = json.loads(R.C.notes('STATE').read_text(encoding='utf-8'))
            self.state({**st, 'running': {}})

    def cmd(self, *a: str) -> tuple[int, str, str]:
        """A plan command in a process of its own, the run's ticks beside it."""
        p = subprocess.Popen([sys.executable, str(RUN), 'plan', *a], cwd=str(self.repo), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding='utf-8')
        end = time.monotonic() + 60
        while p.poll() is None and time.monotonic() < end:
            self.tick()
            time.sleep(0.05)
        out, err = p.communicate(timeout=10)
        return p.returncode, out, err

    def todo(self) -> str:
        return git(self.repo, 'show', 'main:plan/TODO.md')

    def branches(self) -> list[str]:
        return git(self.repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/task', 'refs/heads/wip').split()

    def end(self) -> None:
        if self.agent:
            self.agent.kill()
            self.agent.wait()
        self.lock.close()


def in_proj(test):
    def run():
        print(test.__doc__)
        with tempfile.TemporaryDirectory() as tmp:
            p = Proj(Path(tmp))
            try:
                test(p)
            finally:
                p.end()
    return run


def test_asks(p: Proj):
    """without --yes it asks, with the minutes worked, and stops nothing"""
    p.start()
    before = p.todo()
    rc, out, err = p.cmd('cancel', 'H1')
    eq(rc, 3, 'exit 3')
    has(err, r'H1 has worked 14 min in s1\. .*Cancel H1\?', 'the question')
    eq((p.agent.poll(), p.todo() == before, list(p.running)), (None, True, [1]), 'it runs on, not parked')


def test_kept_parked_unparked(p: Proj):
    """the work is kept (commits and edits), the task parked; unparked, it starts again and is told of the work"""
    d = p.start()
    git(d, 'push', '-q', 'origin', 'task/H1')
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq(rc, 0, f'it goes through ({err})')
    has(out, r'cancelled H1; stopped s1; its work is on wip/H1', 'what the run did')
    check(p.agent.wait(10) is not None, 'the agent is stopped')
    eq((p.procs, p.running), ({}, {}), 'the slot runs nothing')
    check(p.free_at[1] <= dt.datetime.now(), 'and is free')
    eq(p.branches(), ['wip/H1'], 'wip/H1 alone: no task/H1 a run would merge')
    eq(git(p.repo, 'ls-tree', '--name-only', 'wip/H1', 'a0.py', 'half.py').split(), ['a0.py', 'half.py'],
       'with its commit and its uncommitted edits')
    eq(git(p.origin, 'for-each-ref', '--format=%(refname:short)').split(), ['main', 'wip/H1'], 'pushed too')
    eq(git(d, 'status', '--porcelain'), '', 'the slot is clean')
    todo = p.todo()
    has(todo, r'### Parked\n+- \[ \] \*\*H1\*\* \(follow-up, later\) one thing.*cancelled after 14 min: its work is on '
        r'wip/H1', 'the task is parked, with a note')
    eq([t[0] for t in sched.tasks('main')], ['H2'], 'so no run takes it')
    eq(sched.parked_attempts(), {}, 'it counts as no failed merge')
    p.tick()
    eq(list(loop_requests.cancelled_marks().iterdir()), [], 'no mark is left')
    check('H1' not in p.tried, 'parked, it is no longer a tried task')
    rc, out, err = p.cmd('edit', 'H1', '--pri', 'normal')
    eq(rc, 0, f'it is unparked ({err})')
    eq({t[0] for t in sched.tasks('main')}, {'H1', 'H2'}, 'a run takes it again')
    h = sched.held({}, 'main')
    eq(sched.holds(next(t for t in sched.tasks('main') if t[0] == 'H1'), p.tried, h), None, 'in this run too')
    git(d, 'checkout', '-q', '-B', 'task/H1', 'main')  # as `start` does
    brief = R.prompt_for('H1', 1, 1, d, 'main')
    check('wip/H1' in brief and 'go on from there' in brief, 'its next agent is pointed at the work')


def test_again(p: Proj):
    """cancelled twice: the second attempt's work has a branch of its own, and the note names it"""
    p.start(edits=False)
    p.cmd('cancel', 'H1', '--yes')
    p.cmd('edit', 'H1', '--pri', 'normal')
    p.start(commits=2, edits=False)
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq((rc, p.branches()), (0, ['wip/H1', 'wip/H1-2']), 'both are kept')
    has(p.todo(), r'its work is on wip/H1-2', 'the note')
    eq(sched.parked_attempts(), {}, 'neither counts as a failed merge')


def test_nothing_done(p: Proj):
    """nothing done yet: no branch is left, and it is parked"""
    p.start(commits=0, edits=False)
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq((rc, p.branches()), (0, []), 'no branch')
    has(p.todo(), r'### Parked\n+- \[ \] \*\*H1\*\*.*nothing had been done yet', 'parked')


def test_uncommittable(p: Proj):
    """edits that cannot be committed stay in the slot, and no task/H1 is left for a run to merge"""
    d = p.start()
    real = loop_requests.git
    fails = lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'no') if a[0] == 'commit' else real(*a, **k)  # noqa: E731
    with mock.patch.object(loop_requests, 'git', fails):
        rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq((rc, p.branches()), (0, ['wip/H1']), 'parked, on wip/H1')
    has(out, r'could not be committed: they are still in s1', 'said')
    eq((d / 'half.py').read_text(), 'half\n', 'and the edits are there')


def test_not_parked(p: Proj):
    """stopped but never parked (the command died): neither this run nor the next starts it"""
    p.start()
    P.channel(R.C, cancel.KIND).joinpath('H1.json').write_text('{"how": "cancel"}')
    p.tick()
    p.tried = set()  # the next run's
    p.tick()
    check('H1' in p.tried, 'held back')


def test_no_rename(p: Proj):
    """task/H1 that cannot be renamed: said, and the note names where the work is"""
    p.start()
    real = loop_requests.git
    fails = lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'no') if a[:2] == ('branch', '-M') else real(*a, **k)  # noqa: E731
    with mock.patch.object(loop_requests, 'git', fails):
        rc, out, err = p.cmd('cancel', 'H1', '--yes')
    has(out, r'could not be renamed', 'said')
    has(p.todo(), r'its work is on task/H1', 'the note')


def test_queued_resume(p: Proj):
    """a cut-off session that waits to resume: its resume is taken back and its work kept"""
    p.start()
    p.agent.kill()
    p.procs, p.running = {}, {}
    p.state({})
    R.queue_resume('H1', 1, 'sid', 'cut off')
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq((rc, state.queued(), p.branches()), (0, {}, ['wip/H1']), f'kept, and no resume ({err})')
    has(p.todo(), r'### Parked\n+- \[ \] \*\*H1\*\*', 'parked')


def test_refused(p: Proj):
    """while it lands, or with nothing running, it is refused and nothing changes"""
    before = p.todo()
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq(rc, 1, 'a queued task')
    has(err, r'H1 is not running', 'said')
    p.start(edits=False)
    running = {'running': {'1': 'H1'}, 'since': {}}
    for st in ({**running, 'merging': ['H1']}, {'running': {}, 'merging': ['H1']}):
        p.state(st)
        rc, out, err = p.cmd('cancel', 'H1', '--yes')
        eq(rc, 1, 'merging')
        has(err, r'H1 is landing, so it cannot be cancelled', 'said')
    p.state({**running, 'merging': []})
    mark = R.finished_mark(1, R.C)
    mark.write_text('x')
    eq(p.cmd('cancel', 'H1', '--yes')[0], 1, 'its done has passed')
    mark.unlink()
    git(p.repo, 'update-ref', loop_requests.TESTED + 'H1', 'task/H1')  # the command does not see this: the run does
    rc, out, err = p.cmd('cancel', 'H1', '--yes')
    eq(rc, 1, 'the run refuses it')
    has(err, r'finished and lands', 'said')
    git(p.repo, 'update-ref', '-d', loop_requests.TESTED + 'H1')
    gone = threading.Event()
    t = threading.Thread(target=gone.wait, args=(60,), name='merge:H1')
    t.start()
    try:
        rc, out, err = p.cmd('cancel', 'H1', '--yes')
        eq(rc, 1, 'its merge thread is up')
    finally:
        gone.set()
        t.join()
    eq((p.agent.poll(), p.todo() == before, p.branches()), (None, True, ['task/H1']), 'nothing changed')
    eq(p.cmd('cancel', 'H1', '--now')[0], 2, 'an unknown word is refused')


def test_unanswered(p: Proj):
    """a run that does not answer in time: parked all the same, and the run stops it when it looks"""
    p.start()
    code = "import sys; from agent_runner import plan as P; P.HALT_WAIT = 0; sys.exit(P.main(['cancel', 'H1', '--yes']))"
    r = subprocess.run([sys.executable, '-c', code], cwd=str(p.repo), env={**os.environ, 'PYTHONPATH': str(ROOT)},
                       capture_output=True, text=True, encoding='utf-8', timeout=60)
    eq(r.returncode, 0, r.stderr)
    has(r.stdout, r'asked the run to stop s1', 'said')
    has(p.todo(), r'### Parked\n+- \[ \] \*\*H1\*\*', 'parked')
    p.tick()
    eq((p.running, p.branches()), ({}, ['wip/H1']), 'then stopped, its work kept')
    eq(P.requests(R.C, cancel.KIND), {}, 'and the request is gone')


if __name__ == '__main__':
    sys.exit(report([in_proj(t) for t in (test_asks, test_kept_parked_unparked, test_again, test_nothing_done,
                                          test_uncommittable, test_not_parked, test_no_rename, test_queued_resume, test_refused, test_unanswered)]))
