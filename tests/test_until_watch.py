#!/usr/bin/env python3
"""F427c: the run reads the until checks by itself, with fake checks and clock.

    python3 tests/test_until_watch.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import plan as P, runner as R, until as U, until_watch as W  # noqa: E402
from agent_runner import land, state as S  # noqa: E402

PLAN = '''# TODO

### Next

- [~] **T1** one BLOCKED: (until check:vm) wait for the vm
- [~] **T2** two BLOCKED: (until check:vm, version:0.1.0) both
- [~] **T3** three BLOCKED: (until check:far) far
- [ ] **T4** open
'''


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(PLAN, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\n[run.checks.vm]\ncmd = "true"\n'
                                      '[run.checks.far]\ncmd = "true"\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


class Fake:
    def __init__(self):
        self.said, self.calls = {}, []

    def __call__(self, c):
        self.calls.append(c)
        return self.said.get(c, (U.NOT_YET, 'not up'))


def boxes(repo: Path) -> dict[str, str]:
    ls = P.lines(repo / 'plan/TODO.md')
    return {t: b for _, b, t, _, _ in P.iter_tasks(ls)}


def test_round(repo: Path):
    print('each check runs once a round, however many wait; a task reopens when all of its pass')
    f, got = Fake(), []
    W.round_('main', now=1000.0, run=f, reopen=lambda b, ids: got.extend(ids) or [])
    eq(sorted(f.calls), ['check:far', 'check:vm', 'version:0.1.0'], 'one run per check')
    eq(got, [], 'nothing passed, nothing reopened')
    f.said['check:vm'] = (U.PASSED, 'up')
    f.calls.clear()
    W.round_('main', now=1100.0, run=f, reopen=lambda b, ids: got.extend(ids) or [])
    eq(got, ['T1'], 'T1 passed; T2 still waits for its version')
    eq(W.read()['check:vm']['tasks'], ['T1', 'T2'], 'the tasks that wait are noted')


def test_reopen(repo: Path):
    print('reopened in the plan and committed, once; left alone with uncommitted edits')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    eq(land.reopen_until('main', ['T1']), [], 'an uncommitted edit holds it')
    eq(boxes(repo)['T1'], '~', 'still blocked')
    git(repo, 'checkout', '-q', '--', 'plan/TODO.md')
    f = Fake()
    f.said['check:vm'] = (U.PASSED, 'up')
    S.MERGE.acquire()
    try:
        eq(W.round_('main', now=1150.0, run=f), [], 'a merge holds the turn: not now')
    finally:
        S.MERGE.release()
    eq(boxes(repo)['T1'], '~', 'still blocked, tried again next round')
    eq(W.round_('main', now=1200.0, run=f), ['T1'], 'reopened')
    eq(boxes(repo)['T1'], ' ', 'open in the plan')
    has(git(repo, 'log', '-1', '--format=%s').strip(), 'reopen T1', 'committed')
    eq(land.reopen_until('main', ['T1']), [], 'a second time does nothing (another machine got it first)')
    check(S.MERGE.acquire(blocking=False), 'MERGE given back')
    S.MERGE.release()
    eq(W.round_('main', now=1300.0, run=f), [], 'nothing left that passes')
    check('check:vm' in W.read(), 'T2 still waits on vm')


def test_asks(repo: Path):
    print('a check that cannot run for 30 min, or has not passed in 3 days, is one Needs you item')
    f = Fake()
    f.said['check:vm'] = (U.CANNOT, 'no route to host')
    W._write({})
    W.round_('main', now=10_000.0, run=f, reopen=lambda b, ids: [])
    eq(W.asks(now=10_000.0 + 29 * 60), [], 'not before 30 min')
    W.round_('main', now=10_000.0 + 31 * 60, run=f, reopen=lambda b, ids: [])
    a = W.asks(now=10_000.0 + 31 * 60)
    eq([x[1] for x in a], ['until-check:vm'], 'one item for the check')
    has(a[0][3], 'no route to host', 'its last words')
    has(a[0][3], 'T2', 'which task it holds')
    has(a[0][3], 'nblock', 'how to free it')
    f.said['check:vm'] = (U.NOT_YET, 'booting')
    W.round_('main', now=20_000.0, run=f, reopen=lambda b, ids: [])
    a = [x for x in W.asks(now=20_000.0) if x[1] == 'until-check:vm']
    check(a and 'booting' in a[0][3], 'it stays, with the latest words, until the check passes')
    f.said['check:vm'] = (U.PASSED, 'up')
    W.round_('main', now=20_001.0, run=f, reopen=lambda b, ids: [])
    eq(W.asks(now=20_002.0), [], 'gone once it passes')
    f.said['check:vm'] = (U.NOT_YET, 'booting')
    W._write({})
    W.round_('main', now=10_000.0, run=f, reopen=lambda b, ids: [])
    eq(sorted(x[1] for x in W.asks(now=10_000.0 + 3 * 86400 + 1)), ['until-check:far', 'until-check:vm', 'until-version:0.1.0'],
       'not passed in 3 days')
    f.said['check:vm'] = (U.PASSED, 'up')
    W.round_('main', now=10_000.0 + 3 * 86400 + 2, run=f, reopen=lambda b, ids: [])
    check('until-check:vm' not in [x[1] for x in W.asks(now=10_000.0 + 3 * 86400 + 3)], 'gone by itself when it passes')


def test_tick(repo: Path):
    print('a round starts on its own thread, every 2 min')
    calls = []
    keep = W.round_
    W.round_ = lambda b, **k: calls.append(b)
    try:
        W._NEXT[0] = 0.0
        check(W.tick('main', now=5000.0), 'due: started')
        W._BUSY.acquire()  # the thread has ended
        W._BUSY.release()
        check(not W.tick('main', now=5000.0 + 60), 'not again within 2 min')
        check(W.tick('main', now=5000.0 + 121), 'again after 2 min')
        W._BUSY.acquire()
        W._BUSY.release()
        eq(calls, ['main', 'main'], 'two rounds')
    finally:
        W.round_ = keep


def test_none(repo: Path):
    print('no check runs with no task waiting')
    todo = repo / 'plan/TODO.md'
    todo.write_text('# TODO\n\n### Next\n\n- [ ] **T4** open\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'none wait')
    f = Fake()
    W.round_('main', now=1.0, run=f)
    eq(f.calls, [], 'none run')
    eq(W.read(), {}, 'nothing noted')


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    repo = make_repo(tmp)
    R.init(repo)
    return report([lambda: test_round(repo), lambda: test_reopen(repo), lambda: test_asks(repo),
                   lambda: test_tick(repo), lambda: test_none(repo)])


if __name__ == '__main__':
    sys.exit(main())
