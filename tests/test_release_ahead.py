#!/usr/bin/env python3
"""F435: an auto release waits only for what was ahead of it when it was queued.

    python3 tests/test_release_ahead.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import autorelease as A, plan as P, release_ahead as H, release_moves as M, runner as R, sched, status, ui_model as U  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** first thing | files: a.py
- [~] **T2** second thing | files: b.py BLOCKED: DECIDE: which?

### Follow-ups

- [ ] **T9** below it

### Parked

- [ ] **T8** (follow-up, later) some day
"""
TOML = '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\nauto_release = { every = 3, idle = true }\n'


def lines() -> list[str]:
    return P.lines(R.C.todo)


def line(tid: str) -> str:
    return next(l for l in lines() if f'**{tid}**' in l)


def waits(tid: str) -> list[str]:
    ls = lines()
    return P.waits_on(ls, P._find(ls, tid))


def ready() -> list[str]:
    git(R.ROOT, 'commit', '-qam', 'plan', '--allow-empty')
    return [t[0] for t in sched.tasks('main')]


def land(*ids):
    f = R.C.notes('events.jsonl')
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, 'a', encoding='utf-8') as out:
        for t in ids:
            out.write(json.dumps({'time': dt.datetime.now().isoformat(timespec='seconds'), 'kind': R.EV_LANDED, 'id': t,
                                  'text': t}) + '\n')


def idle_release(todo: str = TODO) -> str:
    """A fresh plan `todo`, one task landed, and the release the idle run queues."""
    R.C.todo.write_text(todo, encoding='utf-8')
    (R.ROOT / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(R.ROOT, 'commit', '-qam', 'fresh', '--allow-empty')
    R.C.notes('events.jsonl').unlink(missing_ok=True)
    land('F1')
    A.AUTO_RELEASE_SEEN[0] = None
    return A.auto_release('main', idle=True)


def test_later_tasks():
    print('a task queued above an idle release later does not hold it')
    v = idle_release()
    check(P.release(v), 'queued', v)
    eq((P.fields(line(v)).get('after'), P.fields(line(v)).get('ahead')), (['all'], ['T1', 'T2']), line(v))
    eq((waits(v), v in ready()), (['T1'], False), 'it waits for what was ahead')
    new = P.add('F', 'new feature', 'top', todo=R.C.todo)
    crit = P.add('B', 'urgent', pri='critical', todo=R.C.todo)
    P.move('T8', 'top', todo=R.C.todo)  # out of Parked
    check(lines().index(line('T8')) < lines().index(line(v)), 'above it')
    eq(waits(v), ['T1'], 'none of them holds it')
    part = P.add('F', 'part of T1', 'top', todo=R.C.todo)
    R.C.todo.write_text(R.C.todo.read_text(encoding='utf-8').replace(f'**{part}**', '**T1a**'), encoding='utf-8')
    eq(sorted(waits(v)), ['T1', 'T1a'], 'a part of a listed task does')
    P.unblock('T2', 'reopened', todo=R.C.todo)
    eq(sorted(waits(v)), ['T1', 'T1a', 'T2'], 'and one that needed the person, once it reopens')
    ls = lines()
    has('\n'.join(P.last_lines(R.C.todo)), rf'{v} waits for what was ahead when it was queued \(3 open\)', 'plan says so')
    has(status.release_line(ls), r'waits for 3: ', 'status counts them alone')
    row = next(q for q in U.queue_rows(ls, {}) if q['id'] == v)
    check('everything' not in row['after_title'] and 'T1 first thing' in row['after_title'], 'the queue row names them',
          row['after_title'])
    for t in ('T1a', 'T1', 'T2'):
        P.tick(t, R.C.todo, R.ROOT / 'plan/DONE.md')
    check(v in ready(), 'they landed: it may start')
    check({new, crit, 'T8'} <= set(ready()), 'with the later ones still open')


def test_nothing_ahead():
    print('nothing ahead when it was queued: nothing holds it')
    v = idle_release(TODO.replace('- [ ] **T1** first thing | files: a.py\n', '').replace('- [~] **T2** second thing | files: b.py BLOCKED: DECIDE: which?\n', ''))
    eq(P.fields(line(v)).get('ahead'), ['none'], line(v))
    P.add('F', 'new feature', 'top', todo=R.C.todo)
    eq((waits(v), v in ready()), ([], True), 'ready')


def test_person():
    print('a release a person queues or moves, or says what it waits for, waits as they said')
    v = P.add('V', P.RELEASE_BRIEF + ' | ahead: T1 | after: all', 'bottom', todo=R.C.todo)
    check(not H.is_listed(line(v)), 'only auto release writes the list', line(v))
    v = idle_release()
    P.edit(v, 'Release: my words | ahead: T9', todo=R.C.todo)
    eq(P.fields(line(v)).get('ahead'), ['T1', 'T2'], 'an edit of its words keeps it')
    new = P.add('F', 'new feature', 'top', todo=R.C.todo)
    M.rewait(v, R.C.todo)
    eq((H.is_listed(line(v)), waits(v)), (False, [new, 'T1']), 'moved: all above its place')
    v = idle_release()
    P.edit(v, keyed=' | after: T9', todo=R.C.todo)
    eq((H.is_listed(line(v)), waits(v)), (False, ['T9']), 'told what to wait for')


def test_cut():
    print('the count cuts one that waits, as before')
    v = idle_release()
    land('F2', 'F3')
    A.AUTO_RELEASE_SEEN[0] = None
    eq(A.auto_release('main'), v, 'cut')
    check(not H.is_listed(line(v)) and 'after' not in P.fields(line(v)) and v in ready(), 'it waits no more', line(v))


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    for n, text in (('plan/TODO.md', TODO), ('plan/DONE.md', '# DONE\n'), ('runner.toml', TOML), ('.gitignore', '.runner/\n')):
        (repo / n).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_later_tasks, test_nothing_ahead, test_person, test_cut])


if __name__ == '__main__':
    sys.exit(main())
