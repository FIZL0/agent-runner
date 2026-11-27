#!/usr/bin/env python3
"""F441: what a queued task waits for is set from the Plan page (`set_waits`, `plan edit ID --wait-for`).

    python3 tests/test_plan_wait.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import RUN, check, eq, git, has, report

from agent_runner import plan as P, plan_wait as W, runner as R, sched, status, ui_model as U  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** (follow-up, low) first | files: a.py | after: T2 | test: t | held: yes — a note
- [ ] **T2** second | files: b.py
- [ ] **T3** third | after: T4
- [ ] **T4** fourth
  - [ ] a sub-item
- [ ] **P5** parent
- [ ] **P5a** part
- [ ] **P6** split (split into T7)
- [ ] **T7** named part
- [~] **B1** blocked | files: c.py | after: T2 — old note BLOCKED: (after T2, T4) not merged yet — new note
- [~] **B2** asks BLOCKED: DECIDE: red or blue? [Red / Blue] (asked 2026-11-25 10:00)
- [~] **B3** check later BLOCKED: (after T2) CONFIRM: look at it
- [~] **B4** shelved BLOCKED: shelved: DECIDE: which?
- [~] **B5** stuck BLOCKED: tests flake (asked 2026-11-25 10:00)
- [~] **B6** version BLOCKED: (until version:9.0.0) later
- [~] **B7** twice BLOCKED: (after T4) one BLOCKED: (after T2) two
- [~] **B8** long | after: T4
  more of it BLOCKED: (after T2) why — said
- [ ] **V1** Release | after: all
- [ ] **T8** behind the release
"""
DONE = '# DONE\n\n- [x] **T9** over\n'


def fresh():
    R.C.todo.write_text(TODO, encoding='utf-8')
    R.C.done.write_text(DONE, encoding='utf-8')
    git(R.ROOT, 'commit', '-qam', 'fresh', '--allow-empty')


def line(tid: str) -> str:
    return P.section(R.C.todo, tid)[0]


def block(tid: str) -> str:
    return '\n'.join(P.section(R.C.todo, tid))


def put(tid: str, *ids: str) -> None:
    W.set_waits(R.C, tid, list(ids), R.C.todo, R.C.done)


def refused(tid: str, ids: list[str], why: str) -> None:
    before = R.C.todo.read_text(encoding='utf-8')
    try:
        put(tid, *ids)
        said = 'not refused'
    except SystemExit as e:
        said = str(e)
    eq(said, f'{P.PROG}: waits not changed: {why}', f'{tid} {ids}')
    eq(R.C.todo.read_text(encoding='utf-8'), before, 'nothing changed')


def test_refused():
    print('each refusal, with its reason')
    fresh()
    refused('T1', ['Z9'], 'there is no task Z9')
    refused('T1', ['T2', 'T9'], 'T9 is done')
    refused('Z9', ['T1'], 'there is no task Z9')
    refused('T9', ['T1'], 'T9 is done')
    refused('T1', ['T1'], 'T1 cannot wait for itself')
    refused('P5', ['P5a'], 'P5a is a subtask of P5')
    refused('P5a', ['P5'], 'P5a is a subtask of P5')
    refused('P6', ['T7'], 'T7 is a subtask of P6')
    refused('T7', ['P6'], 'T7 is a subtask of P6')
    refused('V1', ['V1'], 'V1 cannot wait for itself')
    for ids in (['T2'], []):
        refused('B2', ids, 'B2 is waiting for you')
        refused('B4', ids, 'B4 is shelved')
        refused('B5', ids, 'B5 is blocked on something other than a task')
        refused('B6', ids, 'B6 is waiting for version 9.0.0')


def test_circles():
    print('a wait that makes a circle')
    fresh()
    refused('T2', ['T1'], 'that makes a circle: T2 would wait for T1, which waits for T2')
    refused('T4', ['T3'], 'that makes a circle: T4 would wait for T3, which waits for T4')
    put('T2', 'T3')
    refused('T4', ['T1'], 'that makes a circle: T4 would wait for T1, which waits for T2, which waits for T3, which waits for T4')
    fresh()
    refused('T2', ['B1'], 'that makes a circle: T2 would wait for B1, which waits for T2')
    # B868: a task that waits for a release is no longer one the release waits for: no circle
    put('T2', 'V1')
    ls = P.lines(R.C.todo)
    v1 = next(i for i, l in enumerate(ls) if '**V1**' in l)
    eq('T2' in P.before_all(ls, v1), False, 'V1 leaves out T2, which waits for it')
    put('T8', 'V1')
    put('T1', 'T8')
    ls = P.lines(R.C.todo)
    eq('T1' in P.before_all(ls, v1), False, 'and T1, which waits for it down the chain')
    put('T4', 'P5')  # a parent is done once its parts are
    refused('P5a', ['T4'], 'that makes a circle: P5a would wait for T4, which waits for P5, which waits for P5a')
    put('T3', 'T2')  # its own old wait makes none
    put('T4', 'T3')


def test_started():
    print('a task that has started')
    fresh()
    with mock.patch.object(P, 'run_on', lambda c, t: 's2'):
        refused('T2', ['T4'], 'T2 has started: s2 is on it')
    with mock.patch.object(sched, 'taken', lambda: {'T2': Path('x')}):
        refused('T2', [], 'T2 has started: it is taken by hand')


def test_replace():
    print('the waits are replaced, the rest stays')
    fresh()
    put('T1', 'T3', 'T4')
    eq(line('T1'), '- [ ] **T1** (follow-up, low) first | files: a.py | after: T3, T4 | test: t | held: yes — a note', 'T1')
    put('T2', 'T4')
    eq(line('T2'), '- [ ] **T2** second | files: b.py | after: T4', 'none before')
    put('T4', 'P6')
    eq(block('T4'), '- [ ] **T4** fourth | after: P6\n  - [ ] a sub-item', 'no field before, sub-items stay')
    P.note('P5', 'n', todo=R.C.todo)
    put('P5', 'T7')
    eq(P.fields(line('P5')), {'after': ['T7']}, 'with a note')
    check('— n' in line('P5'), 'the note stays', line('P5'))
    eq([t for _, _, t, _, _ in P.iter_tasks(P.lines(R.C.todo))], [t for _, _, t, _, _ in P.iter_tasks(TODO.splitlines())], 'places')


def test_clear():
    print('an empty list clears them')
    fresh()
    put('T1')
    eq(line('T1'), '- [ ] **T1** (follow-up, low) first | files: a.py | test: t | held: yes — a note', 'T1')
    put('T2')
    eq(line('T2'), '- [ ] **T2** second | files: b.py', 'none before')
    put('V1', 'T1')
    eq(line('V1'), '- [ ] **V1** Release | after: T1', 'B870: a release waits for the list, its all replaced')


def test_blocked():
    print('a task blocked on tasks has that wait replaced, not doubled')
    fresh()
    put('B1', 'T3')
    eq(line('B1'), '- [~] **B1** blocked | files: c.py — old note BLOCKED: (after T3) not merged yet — new note', 'replaced')
    put('B3', 'T4')
    eq(line('B3'), '- [~] **B3** check later BLOCKED: (after T4) CONFIRM: look at it', 'its check stays')
    put('B7', 'T3')
    eq(line('B7'), '- [~] **B7** twice BLOCKED: one BLOCKED: (after T3) two', 'the old one is read no more')
    put('B8', 'T3')
    eq(block('B8'), '- [~] **B8** long\n  more of it BLOCKED: (after T3) why — said', 'over two lines')
    for t in ('B1', 'B7', 'B8'):
        put(t)
    eq(line('B1'), '- [ ] **B1** blocked | files: c.py — old note — new note', 'cleared: open, its notes kept')
    eq(line('B7'), '- [ ] **B7** twice', 'twice')
    eq(block('B8'), '- [ ] **B8** long\n  more of it — said', 'over two lines')
    put('B3')
    has(line('B3'), r'\[~\] \*\*B3\*\* check later BLOCKED: CONFIRM: look at it \(asked ', 'a check goes back to the person')
    eq(P.asks(R.C.todo)[0][0] != '' and any(r[1] == 'B3' for r in P.asks(R.C.todo)), True, 'under Needs you')
    eq(P.reopen(R.C.todo), [], 'nothing reopens')


def waits_shown(tid: str) -> str:
    row = next(r for r in U.queue_rows(P.lines(R.C.todo), {}) if r['id'] == tid)
    return f"{row['state']} {','.join(row['after'])}: {row['after_title']}"


def test_shown_and_sent():
    print('the action, and plan, status and the page say the same')
    fresh()
    r = U.act('set_waits', tid='T2', ids=['T4', 'P5'])
    eq((r['ok'], r['out'].splitlines()[0]), (True, 'T2 waits for T4, P5'), 'done')
    has(line('T2'), r'after: T4, P5$', 'plan')
    has(waits_shown('T2'), r'^after T4,P5: ', 'the page')
    check('T2' not in [t[0] for t in sched.tasks('main')], 'no run starts it')
    eq(git(R.ROOT, 'status', '--porcelain').strip(), '', 'committed')
    r = U.act('set_waits', tid='B1', ids=['P5'])
    has(waits_shown('B1'), r'^after P5: ', 'a blocked one, only that')
    has(waits_shown('B2'), r'^blocked : ', 'one that asks the person')
    P.add('F', 'Release the thing | after: T3', todo=R.C.todo)
    U.act('set_waits', tid='F1', ids=['T2', 'P5'])
    has(status.release_line(P.lines(R.C.todo), {}, []), r'waits on 2 of 2 tasks \(F1\)', 'status')
    P.block('F1', 'later', after=['T3'], todo=R.C.todo)
    U.act('set_waits', tid='F1', ids=['T2', 'P5'])
    has(status.release_line(P.lines(R.C.todo), {}, []), r'waits on 2 of 2 tasks \(F1\)', 'status, blocked')
    has(waits_shown('F1'), r'^after T2,P5: ', 'the page, blocked')
    r = U.act('set_waits', tid='T2', ids=[])
    eq((r['ok'], P.fields(line('T2')).get('after')), (True, None), 'cleared')
    check('T2' in [t[0] for t in sched.tasks('main')], 'a run may start it')
    r = U.act('set_waits', tid='T2', ids=['T1'])
    eq((r['ok'], r['out']), (False, 'that makes a circle: T2 would wait for T1, which waits for T2'), 'the plain reason')
    for tid, ids in (('--x', []), ('T2', 'T4'), ('T2', ['none']), ('T2', ['T4,P5']), ('T2', [3]), (None, [])):
        eq(U.act('set_waits', tid=tid, ids=ids)['code'], 2, f'{tid!r} {ids!r}')
    r = subprocess.run([sys.executable, str(RUN), 'plan', 'edit', 'T2', 'words', '--wait-for', 'T4'], cwd=R.ROOT,
                       capture_output=True, text=True, encoding='utf-8', env={**os.environ, 'AGENT_RUNNER_REPO': str(R.ROOT)})
    eq(r.returncode, 2, 'the flag stands alone')


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    for n, text in (('plan/TODO.md', TODO), ('plan/DONE.md', DONE), ('.gitignore', '.runner/\n'),
                    ('runner.toml', '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\n')):
        (repo / n).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_refused, test_circles, test_started, test_replace, test_clear, test_blocked, test_shown_and_sent])


if __name__ == '__main__':
    sys.exit(main())
