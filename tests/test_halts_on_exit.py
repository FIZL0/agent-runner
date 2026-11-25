#!/usr/bin/env python3
"""B801: `[run] on_exit` runs once each time a slot's session ends, stopped or by itself, and its slot starts nothing
before it has ended.

    python3 tests/test_halts_on_exit.py          (a temp repo, some seconds)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import exit_hook, loop, state
from agent_runner import runner as R

HOOK = """import os, sys, time
from pathlib import Path
here = Path(__file__).parent
time.sleep(0.3)
while (here / 'hold').exists():
    time.sleep(0.05)
with open(here / 'ran', 'a') as f:
    f.write(' '.join([os.environ.get('AGENT_SLOT', '-'), os.environ.get('PHONE', '-'), Path.cwd().name,
                      str(Path('work.txt').exists())]) + '\\n')
"""


class Hook:
    """A project whose on_exit writes a line: the slot, the slot_env variable, its folder, the work still there."""

    def __init__(self, tmp: Path):
        self.dir, self.repo = tmp / 'hook', tmp / 'proj'
        self.dir.mkdir()
        (self.dir / 'hook.py').write_text(HOOK, encoding='utf-8')
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / 'plan').mkdir()
        (self.repo / 'plan/TODO.md').write_text('# TODO\n\n### Later\n\n- [ ] **H1** one thing | files: a.py\n',
                                                encoding='utf-8')
        (self.repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        cmd = f'"{Path(sys.executable).as_posix()}" "{(self.dir / "hook.py").as_posix()}"'
        (self.repo / 'runner.toml').write_text(
            f'[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\nslot_env = ["PHONE=p{{n}}"]\n'
            f"on_exit = '{cmd}'\n", encoding='utf-8')
        (self.repo / '.gitignore').write_text('.runner/\n')
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', 'start')
        R.init(self.repo)

    def ran(self) -> list[str]:
        f = self.dir / 'ran'
        return f.read_text().splitlines() if f.exists() else []

    def fresh(self) -> Path:
        """Slot 1 on task/H1, with uncommitted work; nothing has run yet."""
        (self.dir / 'ran').unlink(missing_ok=True)
        d = R.worktree(1, 'main')
        git(d, 'checkout', '-q', '-B', 'task/H1', 'main')
        (d / 'work.txt').write_text('x\n')
        return d

    def hold(self, on: bool) -> None:
        (self.dir / 'hold').touch() if on else (self.dir / 'hold').unlink()


def settle() -> None:
    check(exit_hook.wait(1, 60), 'the hook ends')


def halt(hook: Hook, how: str, starts: list, queued: bool = False, tried: set | None = None):
    """The run is asked to stop H1 in slot 1 (or its queued resume); (its free_at, its tried)."""
    agent = None if queued else subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    procs = {} if queued else {1: (agent.pid, '', None)}
    running = {} if queued else {1: ('H1', 'Later', {'a.py'}, set())}
    if queued:
        R.queue_resume('H1', 1, 'sid', 'cut off')
    (R.P.halt_dir(R.C) / 'H1.json').write_text(json.dumps({'how': how}), encoding='utf-8')
    free_at, tried = {1: dt.datetime.max}, {'H1'} if tried is None else tried

    def start(n, task, *a, **k):
        starts.append((task[0], len(hook.ran())))
        return None

    try:
        with mock.patch.object(loop, 'end_orphans', lambda: None), mock.patch.object(loop, 'start', start), \
                mock.patch.object(loop, 'agent_held', lambda: False):
            loop.halts(procs, running, free_at, tried, 'main', 'm', 30, 1)
        if agent:
            check(agent.wait(15) is not None, 'the session is ended')
    finally:
        if agent:
            agent.kill()
            agent.wait()
    eq((procs, running, loop.halt_requests()), ({}, {}, {}), 'the request is answered')
    check(free_at[1] <= dt.datetime.now(), 'and the slot is given back')
    return free_at, tried


def test_stopped(hook: Hook):
    print('drop, change --restart and take back: on_exit runs once, in the worktree, with the slot\'s env')
    for how in ('drop', 'change', 'take'):
        d, starts = hook.fresh(), []
        with mock.patch.object(exit_hook, 'SOON', 60):
            halt(hook, how, starts)
        eq(hook.ran(), ['1 p1 s1 True'], f'{how}: once, before the work is thrown away')
        eq(starts, [('H1', 1)] if how == 'change' else [], f'{how}: a restart comes after it')
        eq(git(d, 'status', '--porcelain'), '', f'{how}: then the worktree is clean')
        eq(exit_hook.busy(), set(), f'{how}: and nothing is left running')


def test_queued(hook: Hook):
    print('a queued resume that is taken back, dropped or changed runs it once too')
    for how in ('take', 'drop', 'change'):
        hook.fresh()
        with mock.patch.object(exit_hook, 'SOON', 60):
            halt(hook, how, starts := [], queued=True)
        eq(hook.ran(), ['1 p1 s1 True'], f'{how}: once')
        eq(starts, [('H1', 1)] if how == 'change' else [], f'{how}: a restart comes after it')
        eq(loop.queued(), {}, f'{how}: the resume is gone')


def new_run() -> loop.Run:
    return loop.Run(argparse.Namespace(force=False), 1, False, 'main', 'm', 30, 600, 0)


def test_slow(hook: Hook):
    print('one that runs long freezes nothing: its slot is held, and a changed task starts later')
    hook.fresh()
    hook.hold(True)
    starts, filled = [], []
    run = new_run()
    with mock.patch.object(exit_hook, 'SOON', 0.2):
        run.free_at, run.tried = halt(hook, 'change', starts)
    eq((starts, hook.ran()), ([], []), 'no restart while it runs')
    check('H1' not in run.tried, 'the task may start again')
    run.waiting = {}
    with mock.patch.object(loop.Run, 'fill', lambda self, n: filled.append((n, len(hook.ran())))), \
            mock.patch.object(loop.Run, 'resume_queued', lambda self, n: filled.append('resumed')), \
            mock.patch.object(type(loop.MUX), 'panes', lambda self: {}):
        run.slot(1)
        run.waiting = {1: ('H1', 'sid', 'cut off')}
        run.slot(1)
        eq(filled, [], 'the slot takes neither a new task nor a resume')
        with mock.patch.object(loop, 'stopping', lambda: True), mock.patch.object(loop, 'forced', lambda: False):
            run.waiting = {}
            eq(run.end(), None, 'and a stop waits for it')
        hook.hold(False)
        settle()
        run.slot(1)
        eq(filled, [(1, 1)], 'then the slot is filled')
    eq(hook.ran(), ['1 p1 s1 False'], 'it ran once (the work is thrown away without waiting for it)')


def test_reap(hook: Hook):
    print('a session that ends by itself runs it once, and its slot waits for it')
    hook.fresh()
    hook.hold(True)
    run, filled = new_run(), []
    run.procs, run.running = {1: (999999, 'sid', 0)}, {1: ('H1', 'Later', {'a.py'}, set())}
    with ExitStack() as st:
        for k, v in dict(end_orphans=None, stats='1 min', last_words=None, take_end={}, cut_off=None,
                         drop_session_tmp=None, save_leftovers=False, not_attempt=False).items():
            st.enter_context(mock.patch.object(loop, k, mock.Mock(return_value=v)))
        st.enter_context(mock.patch.object(loop.plat, 'alive', lambda p: False))
        st.enter_context(mock.patch.object(loop.Run, 'merge_in', lambda *a: None))
        st.enter_context(mock.patch.object(loop.Run, 'fill', lambda self, n: filled.append((n, len(hook.ran())))))
        st.enter_context(mock.patch.object(type(loop.MUX), 'panes', lambda self: {}))
        run.slot(1)
        run.free_at[1] = dt.datetime.min
        run.slot(1)
        eq((run.procs, filled), ({}, []), 'reaped, and not refilled while on_exit runs')
        hook.hold(False)
        settle()
        run.slot(1)
        eq(filled, [(1, 1)], 'refilled after it')
        run.slot(1)
    eq([l.rsplit(' ', 1)[0] for l in hook.ran()], ['1 p1 s1'], 'it ran once, with the slot\'s env')


def test_timeout(hook: Hook):
    print('one past command_timeout is stopped and logged, and its slot is free')
    hook.fresh()
    hook.hold(True)
    said = []
    with mock.patch.dict(state.C.run, {'command_timeout': 0.5}), \
            mock.patch.object(state, 'log', lambda m, *a, **k: said.append(m)):
        exit_hook.start(1)
        p = exit_hook.GOING[0][1]
        eq(exit_hook.busy(), {1}, 'it runs')
        settle()
    check(p.poll() is not None, 'stopped')
    check(len(said) == 1 and 'ran past [run] command_timeout' in said[0], 'and said once', said)
    hook.hold(False)
    time.sleep(0.5)
    eq(hook.ran(), [], 'what it started is stopped with it')


def test_none(hook: Hook):
    print('no on_exit, or no worktree: nothing runs')
    with mock.patch.dict(state.C.run, {'on_exit': ''}):
        exit_hook.start(1)
    exit_hook.start(77)
    eq(exit_hook.GOING, [], 'nothing')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        hook = Hook(Path(tmp))
        return report([lambda: test_stopped(hook), lambda: test_queued(hook), lambda: test_slow(hook),
                       lambda: test_reap(hook), lambda: test_timeout(hook), lambda: test_none(hook)])


if __name__ == '__main__':
    sys.exit(main())
