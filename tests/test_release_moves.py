#!/usr/bin/env python3
"""F429a: releases moved and removed, and the same for the Next release row.

    python3 tests/test_release_moves.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import RUN, check, eq, git, has, report

from agent_runner import autorelease as A, plan as P, release_moves as M, row_hold as H, runner as R, sched, ui_model as U  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** first thing | files: a.py
- [ ] **T2** second thing | files: b.py
- [ ] **T3** third thing | files: c.py

### Parked
"""
DONE = '# DONE\n'
TOML = '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\nauto_release = { every = 3 }\n'


def cmd(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN), 'plan', *args], cwd=R.ROOT, capture_output=True, text=True,
                          env={**os.environ, 'AGENT_RUNNER_REPO': str(R.ROOT)}, encoding='utf-8')


def ok(*args) -> str:
    r = cmd(*args)
    eq(r.returncode, 0, f'plan {" ".join(args)}: {r.stderr}')
    return r.stdout


def events() -> Path:
    return R.C.notes('events.jsonl')


def land(*ids, ago: int = 60):
    stamp = (dt.datetime.now() - dt.timedelta(seconds=ago)).isoformat(timespec='seconds')
    with open(events(), 'a', encoding='utf-8') as f:
        for t in ids:
            f.write(json.dumps({'time': stamp, 'kind': R.EV_LANDED, 'id': t, 'text': t}) + '\n')


def fresh(*rows, landed=()):
    """TODO.md with `rows` (releases) at the top; `landed` landed a minute ago."""
    todo = TODO.replace('### Next\n\n', '### Next\n\n' + ''.join(r + '\n' for r in rows))
    R.C.todo.write_text(todo, encoding='utf-8')
    (R.ROOT / 'plan/DONE.md').write_text(DONE, encoding='utf-8')
    git(R.ROOT, 'commit', '-qam', 'fresh', '--allow-empty')
    events().parent.mkdir(parents=True, exist_ok=True)
    events().write_text('', encoding='utf-8')
    land(*landed)


def line(tid: str) -> str:
    return next(l for l in P.lines(R.C.todo) if f'**{tid}**' in l)


def order() -> list[str]:
    return [tid for _, _, tid, _, _ in P.iter_tasks(P.lines(R.C.todo))]


def auto(idle: bool = False) -> str:
    A.AUTO_RELEASE_SEEN[0] = None
    return A.auto_release('main', idle=idle)


def count() -> int:
    return len(A.landed_since_release('main'))


def ready() -> list[str]:
    return [t[0] for t in sched.tasks('main')]


def test_moved_cut():
    print('a moved cut waits for the tasks above it; no other is cut beside it; the next is cut as ever')
    fresh(landed=('F1', 'F2', 'F3'))
    v = auto()
    check(v and v in ready(), 'cut', v)
    has(ok('move', v, 'after', 'T2'), 'waits for the tasks above it', 'said')
    eq(order(), ['T1', 'T2', v, 'T3'], 'its place')
    eq((P.fields(line(v)).get('after'), 'critical' in line(v)), (['all'], False), line(v))
    has(line(v), rf'^- \[ \] \*\*{v}\*\* \S', 'the line is in shape')
    ls = P.lines(R.C.todo)
    eq(P.waits_on(ls, P._find(ls, v)), ['T1', 'T2'], 'the tasks above')
    check(v not in ready(), 'it waits')
    eq((auto(), auto(idle=True)), ('', ''), 'that cut stands, no other beside it')
    check(not U._counts_on(ls, U.release_tasks(ls, {})), 'and its row says so')
    ok('move', 'T3', 'top')
    eq(P.waits_on(P.lines(R.C.todo), P._find(P.lines(R.C.todo), v)), ['T3', 'T1', 'T2'], 'a task moved above it too')
    ok('move', v, 'top')
    check(v in ready(), 'nothing above: it may start')
    P.tick(v, R.C.todo, R.ROOT / 'plan/DONE.md')
    git(R.ROOT, 'commit', '-qam', 'landed')
    land(v, ago=30)
    land('F4', 'F5', ago=10)
    eq(auto(), '', 'the count starts at its landing')
    land('F6', ago=10)
    check(auto(), 'and the next is cut at three, as the setting says')


def test_moved_other():
    print('a release a person wrote: what it waits for is its place; the count goes on beside one that waited')
    fresh('- [ ] **V8** My release | after: T3', landed=('F1', 'F2', 'F3'))
    ok('move', 'V8', 'after', 'T1')
    eq((P.fields(line('V8')).get('after'), M.is_moved(line('V8'))), (['all'], False), line('V8'))
    v = auto()
    check(v and v != 'V8', 'the count cuts beside it, as before', v)
    fresh('- [ ] **V8** My release now', landed=('F1', 'F2', 'F3'))
    eq(auto(), '', 'one that may start is the next cut')
    ok('move', 'V8', 'after', 'T1')
    eq(auto(), '', 'and is, moved')
    fresh(f'- [ ] **V8** {P.RELEASE_BRIEF} | after: all', landed=('F1', 'F2', 'F3'))
    ok('move', 'V8', 'after', 'T1')
    eq((auto(), P.fields(line('V8')).get('after')), ('', ['all']), 'a default one moved is not cut early')
    tid = P.add('V', 'words | moved: yes', todo=R.C.todo)
    P.edit(tid, 'words | moved: yes', todo=R.C.todo)
    check(not M.is_moved(line(tid)), 'only a move writes the field')
    ok('move', 'T3', 'top')
    check('after' not in P.fields(line('T3')), 'a task moved waits for nothing new')


def test_running():
    print('a running release or task cannot be moved')
    fresh('- [ ] **V8** My release')
    for t in ('T2', 'V8'):
        (note := R.C.notes(f'{t}.resume')).write_text('{"slot": 2, "sid": "x", "why": "cut off"}', encoding='utf-8')
        before = R.C.todo.read_text(encoding='utf-8')
        r = cmd('move', t, 'bottom')
        eq((r.returncode, R.C.todo.read_text(encoding='utf-8')), (1, before), 'nothing moved')
        has(r.stderr, f'{t} cannot be moved: it waits to resume', 'in words')
        note.unlink()
    with mock.patch.object(P, 'run_on', lambda c, t: 's2'), mock.patch('sys.stderr') as err:
        eq(P._p_move(P._parse_command(['move', 'T2', 'bottom']), mock.Mock(c=R.C, todo=R.C.todo)), 1, 'in a slot')
        has(''.join(c.args[0] for c in err.write.call_args_list), 'T2 cannot be moved: s2 is on it', 'in words')
    r = cmd('move', 'Z9', 'top')
    check(r.returncode and 'no task' in r.stderr, 'no such task', r.stderr)


def test_removed():
    print('a removed automatic release skips that cut; restored, the count is as before')
    fresh(landed=('F1', 'F2', 'F3'))
    v = auto()
    has(ok('drop', v, 'not now'), 'count starts from zero', 'said')
    eq((count(), auto(), auto(idle=True)), (0, '', ''), 'skipped, counted from zero')
    land('F4', 'F5', ago=-5)
    eq((count(), auto()), (2, ''), 'what lands after it counts')
    ok('restore', v)
    eq((count(), v in order()), (5, True), 'restored: as before')
    eq(auto(), '', 'it is the next cut again')
    ok('drop', v, 'again')
    eq(count(), 2, 'removed again')
    land('F6', ago=-5)
    check(auto(), 'the third since cuts')
    fresh('- [ ] **V8** My release | after: all', landed=('F1', 'F2'))
    ok('drop', 'V8', 'no')
    eq(count(), 2, "a person's own release: the count is unchanged")


def test_next_row():
    print('the Next release row is held, removed and restored by name')
    fresh(landed=('F1', 'F2', 'F3'))
    ok('hold', M.NEXT)
    has(ok('hold', M.NEXT), 'held already', 'twice')
    eq((auto(), auto(idle=True)), ('', ''), 'held: not cut, whatever lands')
    R.C.run['auto_release'] = {'idle': True}
    eq(auto(idle=True), '', 'nor when the run goes idle')
    R.C.run['auto_release'] = {'every': 3}
    ok('drop', M.NEXT, 'skip it')
    eq((count(), auto(), M.cuts().held), (0, '', False), 'removed, its hold too')
    ok('restore', M.NEXT)
    eq((count(), auto(), M.cuts().held), (3, '', True), 'undone: the count and the hold are back')
    ok('unhold', M.NEXT)
    has(ok('unhold', M.NEXT), 'is not held', 'twice')
    v = auto()
    check(v, 'unheld: cut')
    for words in (('hold', M.NEXT), ('drop', M.NEXT, 'x'), ('move', M.NEXT, 'top')):
        r = cmd(*words)
        check(r.returncode and f'{v} is the next release' in r.stderr, 'the cut is queued: name it', r.stderr)
    r = cmd('restore', M.NEXT)
    check(r.returncode and 'nothing to restore' in r.stderr, 'nothing removed', r.stderr)
    (R.ROOT / 'runner.toml').write_text(TOML.replace('auto_release', '#'), encoding='utf-8')
    r = cmd('hold', M.NEXT)
    check(r.returncode and 'auto_release' in r.stderr, 'auto release off', r.stderr)
    (R.ROOT / 'runner.toml').write_text(TOML, encoding='utf-8')


def test_next_moved():
    print('the Next release row moved is a release at that place, that cut only')
    fresh(landed=('F1',))
    ok('hold', M.NEXT)
    has(ok('move', M.NEXT, 'after', 'T2'), r'it is V\d+ now', 'said')
    v = next(t for t in order() if P.release(t))
    eq(order(), ['T1', 'T2', v, 'T3'], 'its place')
    eq((H.is_held(line(v)), M.cuts().held), (True, False), 'its hold goes with it')
    ok('unhold', v)
    land('F2', 'F3', ago=-5)
    eq((auto(), v in ready()), ('', False), 'the count cuts no other, and it waits for its place')
    has(git(R.ROOT, 'log', '-3', '--format=%s'), f'move {M.NEXT} after T2', 'committed')
    ok('drop', v, 'not this one')
    check(M.skipped_at(), 'automatic: removed, that cut is skipped')
    r = cmd('move', M.NEXT, 'after', 'Z9')
    check(r.returncode and not any(P.release(t) for t in order()), 'a wrong place files nothing', r.stderr)


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    for n, text in (('plan/TODO.md', TODO), ('plan/DONE.md', DONE), ('runner.toml', TOML), ('.gitignore', '.runner/\n')):
        (repo / n).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_moved_cut, test_moved_other, test_running, test_removed, test_next_row, test_next_moved])


if __name__ == '__main__':
    sys.exit(main())
