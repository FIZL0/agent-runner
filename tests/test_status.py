#!/usr/bin/env python3
"""F131, F185: the releases as rows (`ui_model.release_rows`) in each of their states, and `status` saying the same.

    python3 tests/test_status.py        (a temp repo; no run, no network)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import autorelease as A  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import status as R  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

NEXT = ['# TODO', '', '### Next', '', '- [ ] **F1** one | files: a.py', '- [ ] **F2** two | files: b.py']
V5 = f'- [ ] **V5** (follow-up, critical) {P.RELEASE_BRIEF} | after: all'
LATER = '- [ ] **F3** queued after it | files: c.py'


def repo(tmp: Path, auto=False) -> None:
    d = tmp / 'proj'
    (d / 'plan').mkdir(parents=True, exist_ok=True)
    (d / 'plan/TODO.md').write_text('\n'.join(NEXT) + '\n', encoding='utf-8')
    (d / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (d / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    if not (d / '.git').exists():
        git(d, 'init', '-q', '-b', 'main')
        git(d, 'add', '-A')
        git(d, 'commit', '-qm', 'start')
    U.LANDED_COUNT[:] = [None, 0.0, None]
    S.init(d)
    S.C.run['auto_release'] = auto


def test_placeholder() -> None:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo(tmp)
        eq((U.release_rows(NEXT), R.release_line(NEXT, {})), ([], ''), 'off and no V: no row, no line')
        repo(tmp, {'every': 10})
        with mock.patch.object(A, 'landed_since_release', lambda b: ['F1'] * 6):
            row, = U.release_rows(NEXT)
            eq(row['text'], 'Next release · auto at 10 landed: 6/10', 'counting')
            eq((row['id'], row['placeholder']), ('', True), 'a placeholder, no task')
            eq(R.release_line(NEXT, {}), 'release: ' + row['text'], 'status: the same words')
            snap = U.snapshot(up=False, links={}, windows={})
            eq(snap['releases'][0]['text'], row['text'], 'the snapshot carries it')
            check('release: ' + row['text'] in snap['status'], 'and its status says it', str(snap['status']))
            eq([q['id'] for q in snap['queue']], ['F1', 'F2'], 'the placeholder is no task in the queue')
        eq(U.release_rows(NEXT, landed=0)[0]['words'], 'auto at 10 landed: 0/10', 'after a release: 0/N')

        def broken(b):
            raise OSError('git')
        U.LANDED_COUNT[:] = [None, 0.0, None]
        with mock.patch.object(A, 'landed_since_release', broken):
            eq(U.release_rows(NEXT)[0]['words'], 'auto at 10 landed', 'it could not be counted: no made-up count')
        shelved = NEXT + ['', '### Parked', '', V5]
        eq(U.release_rows(shelved, landed=1), [], 'a Parked release: none is queued by itself, no placeholder')
        repo(tmp, {'idle': True})
        eq(U.release_rows(NEXT)[0]['text'], 'Next release · when the run goes idle', 'idle')
        repo(tmp, {'every': 10, 'idle': True})
        eq(U.release_rows(NEXT, landed=6)[0]['text'],
           'Next release · auto at 10 landed: 6/10 · when the run goes idle', 'both')


def test_releases() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t), {'every': 10})
        one = lambda ls, st=None: U.release_rows(ls, st)[0]  # noqa: E731
        ls = NEXT + [V5, LATER]
        eq(one(ls)['text'], 'V5 Release · waits for 2: F1 one, F2 two', 'one open: what it waits for, by id and title')
        S.C.run['auto_release'] = False
        eq(R.release_line(ls, {}), 'release: ' + one(ls)['text'], "one 'release:' line, no 'last:'")
        eq((one(NEXT[:4] + [V5])['words'], one(NEXT[:4] + [V5])['state']), ('next', 'next'), 'nothing ahead')
        many = NEXT + [f'- [ ] **F{n}** t{n} | files: f.py' for n in range(3, 9)] + [V5]
        eq(one(many)['words'], 'waits for 8: F1 one, F2 two, F3 t3, F4 t4, F5 t5, and 3 more', 'a long list is cut')
        check(one(many)['all'].endswith('F7 t7, F8 t8') and len(one(many)['waits']) == 8, 'and kept whole beside it')
        V6 = V5.replace('V5', 'V6')
        two = U.release_rows(NEXT + [V5, V6])
        eq([r['text'] for r in two], ['V5 Release · waits for 2: F1 one, F2 two',
                                      'V6 Release · waits for 3: F1 one, F2 two, V5 Release'], 'two open: told apart')
        eq(R.release_line(NEXT + [V5, V6], {}).splitlines(), ['release: ' + r['text'] for r in two], 'one line each')
        eq([r['words'] for r in U.release_rows(NEXT[:4] + [V5, V6])], ['next', 'waits for 1: V5 Release'], 'next, then')
        for st in ({'running': {'2': 'V5'}}, {'merging': ['V5']}):
            eq(one(ls, st)['text'], 'V5 Release · releasing now', f'releasing now: {st}')
            eq(R.release_line(ls, st), 'release: V5 Release · releasing now', 'status too')
        eq([r['id'] for r in U.release_rows(NEXT + [V5, V6], {'running': {'1': 'V6'}})], ['V6', 'V5'], 'it goes first')
        eq(one(ls, {'running': {'1': 'F1'}})['state'], 'waits', 'another task running')
        alone = [l.replace('critical) ', 'critical) (alone) ') for l in ls]
        eq(one(alone)['title'], 'Release', 'its (alone) tag is no title')
        blocked = NEXT + [V5.replace('[ ]', '[~]'), '  BLOCKED: CONFIRM: is it ok?']
        eq(one(blocked)['words'], 'blocked', 'waiting on a person')
        waits = NEXT + ['- [~] **V5** Release: x', '  BLOCKED: (after F1) its code']
        eq(one(waits)['words'], 'waits for 1: F1 one', 'blocked until another task lands')
        q = U.pin_releases(U.queue_rows(ls), U.release_rows(ls))
        eq([x['id'] for x in q], [x['id'] for x in U.queue_rows(ls)], 'F195c: at its place')
        eq([x['id'] for x in q if 'release' in x], ['V5'], 'with its row')


def test_count_beside_f195c() -> None:
    """F195c: the count shows beside an open release that only waits, not beside one that stops it; its place in the queue
    is after as many tasks as it still needs."""
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t), {'every': 3, 'idle': True})
        ids = lambda ls, st=None, n=2: [r['id'] or r['text'] for r in U.release_rows(ls, st, landed=n)]  # noqa: E731
        ph = 'Next release · auto at 3 landed: 2/3'
        ls = NEXT + [V5, LATER]
        eq(ids(ls), ['V5', ph], 'beside one that waits, without idle')
        eq(ids(ls, {'running': {'1': 'V5'}}), ['V5'], 'releasing: no count')
        eq(ids(ls, {'merging': ['V5']}), ['V5'], 'merging: no count')
        eq(ids(NEXT[:4] + [V5]), ['V5'], 'next: no count')
        eq(ids(NEXT + [V5.replace('[ ]', '[~]'), '  BLOCKED: (after F1) its code']), ['V5'], 'blocked: no count')
        eq(ids(ls + ['', '### Parked', '', V5.replace('V5', 'V6')]), ['V5'], 'a Parked one beside it: no count')
        with mock.patch('agent_runner.sched.taken', lambda: {'V5': {}}):
            eq(ids(ls), ['V5'], 'taken by a person: no count')
        S.C.run['auto_release'] = {'idle': True}
        eq(ids(ls), ['V5'], 'idle alone: queues none while one is open')
        S.C.run['auto_release'] = {'every': 3}

        def before(n, ls):
            rows = U.release_rows(ls, landed=n)
            U.pin_releases(U.queue_rows(ls), rows)
            return next(r['before'] for r in rows if r['state'] == 'auto')
        eq([before(n, ls) for n in (0, 1, 2, 3, 9)], ['', 'F3', 'F2', 'F1', 'F1'], 'after the tasks it still needs')
        stuck = NEXT[:4] + ['- [~] **F1** one | files: a.py', '  BLOCKED: CONFIRM: is it ok?', NEXT[5], LATER]
        eq(before(2, stuck), 'F3', 'a blocked task is not one that lands')


def test_released() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t))
        eq((U.release_rows(NEXT), R.release_line(NEXT, {})), ([], ''), 'none open, none released: no row')
        evs = [ev(1, S.EV_LANDED, 'V4'), ev(2, S.EV_RELEASED, text='proj 1.2.0 released: Added: x.'),
               ev(3, S.EV_LANDED, 'F1')]
        S.C.notes('events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in evs), encoding='utf-8')
        at = lambda d: dt.datetime(2026, 11, d, 12).timestamp()  # noqa: E731
        eq(U.last_release(at(23))['text'], 'V4 Release 1.2.0 · released 10:00', 'released when')
        eq(U.last_release(at(24))['words'], 'released 2026-11-23 10:00', 'on another day: the date too')
        rows = U.release_rows(NEXT + [V5], now=at(23))
        eq([(r['id'], r['state'], r['placeholder']) for r in rows], [('V5', 'waits', False), ('V4', 'released', True)],
           'after the open ones')
        eq([l.split(' ')[1] for l in R.release_line(NEXT + [V5], {}).splitlines()], ['V5', 'V4'], 'a status line each')


def test_plan_index() -> None:
    """F185: `plan` opens with the Releases group, and lists an open release only there."""
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t))
        todo = S.C.todo

        def index(ls) -> list[str]:
            Path(todo).write_text('\n'.join(ls) + '\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = P._main([], S.C)
            eq(rc, 0, 'plan')
            return out.getvalue().splitlines()
        with mock.patch.object(P, 'ensure', lambda *a, **k: (todo, S.C.done)):
            eq(index(NEXT)[0], '# TODO', 'no release: no group')
            V6 = V5.replace('V5', 'V6')
            eq(index(NEXT + [V5, V6])[:4], ['## Releases', '[ ] V5 Release · waits for 2: F1 one, F2 two',
                                            '[ ] V6 Release · waits for 3: F1 one, F2 two, V5 Release', ''], 'two open')
            got = index(NEXT + [V5])
            eq(got, ['## Releases', '[ ] V5 Release · waits for 2: F1 one, F2 two', '', '# TODO', '### Next',
                     '[ ] F1', '[ ] F2'], 'one open, shown once')
            with mock.patch.object(U, '_state', lambda up: {'running': {'1': 'V5'}}):
                eq(index(NEXT + [V5])[1], '[ ] V5 Release · releasing now', 'one running')


def ev(s: int, kind: str, tid: str = '', text: str = '') -> dict:
    return {'time': f'2026-11-23T10:00:{s:02d}', 'kind': kind, 'id': tid, 'text': text}


def test_lately() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t))
        titles = {'V5': 'Release: bump the version', 'F1': 'one'}
        rel = ev(3, S.EV_RELEASED, text='proj 1.2.0 released: Added: x.')
        said = [m[2] for m in R.lately_events([ev(1, S.EV_LANDED, 'V5'), rel], titles)]
        eq(said, ['landed: Release 1.2.0 [V5]'], 'a landed release shows its version')
        said = [m[2] for m in R.lately_events([ev(1, S.EV_LANDED, 'V5'), ev(2, S.EV_LANDED, 'F1'), rel], titles)]
        eq(said, ['landed: Release: bump the version [V5]', 'landed: one [F1]'], "not another landing's release")


if __name__ == '__main__':
    raise SystemExit(report([test_placeholder, test_releases, test_count_beside_f195c, test_released, test_plan_index, test_lately]))
