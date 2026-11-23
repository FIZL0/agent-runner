#!/usr/bin/env python3
"""F131: the release as one row (`ui_model.release_row`) in each of its states, and `status` saying the same.

    python3 tests/test_status.py        (a temp repo; no run, no network)
"""
from __future__ import annotations

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
        eq((U.release_row(NEXT), R.release_line(NEXT, {})), (None, ''), 'off and no V: no row, no line')
        repo(tmp, {'every': 10})
        with mock.patch.object(A, 'landed_since_release', lambda b: ['F1'] * 6):
            row = U.release_row(NEXT)
            eq(row['text'], 'Next release · auto at 10 landed: 6/10', 'counting')
            eq((row['id'], row['placeholder']), ('', True), 'a placeholder, no task')
            eq(R.release_line(NEXT, {}), 'release: ' + row['text'], 'status: the same words')
            snap = U.snapshot(up=False, links={}, windows={})
            eq(snap['release_row']['text'], row['text'], 'the snapshot carries it')
            check('release: ' + row['text'] in snap['status'], 'and its status says it', str(snap['status']))
            eq([q['id'] for q in snap['queue']], ['F1', 'F2'], 'the placeholder is no task in the queue')
        eq(U.release_row(NEXT, landed=0)['words'], 'auto at 10 landed: 0/10', 'after a release: 0/N')

        def broken(b):
            raise OSError('git')
        U.LANDED_COUNT[:] = [None, 0.0, None]
        with mock.patch.object(A, 'landed_since_release', broken):
            eq(U.release_row(NEXT)['words'], 'auto at 10 landed', 'it could not be counted: no made-up count')
        shelved = NEXT + ['', '### Parked', '', V5]
        eq(U.release_row(shelved, landed=1), None, 'a Parked release: none is queued by itself, no placeholder')
        repo(tmp, {'idle': True})
        eq(U.release_row(NEXT)['text'], 'Next release · when the run goes idle', 'idle')
        repo(tmp, {'every': 10, 'idle': True})
        eq(U.release_row(NEXT, landed=6)['text'],
           'Next release · auto at 10 landed: 6/10 · when the run goes idle', 'both')


def test_queued() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo(Path(t), {'every': 10})
        ls = NEXT + [V5, LATER]
        eq(U.release_row(ls)['text'], 'V5 Release · waits for 2 open ahead', 'queued: what is open ahead of it')
        eq(R.release_line(ls, {}), 'release: V5 Release · waits for 2 open ahead', "one 'release:' line, no 'last:'")
        eq(U.release_row(NEXT[:4] + [V5])['words'], 'ready', 'nothing ahead')
        for st in ({'running': {'2': 'V5'}}, {'merging': ['V5']}):
            eq(U.release_row(ls, st)['text'], 'V5 Release · building', f'building: {st}')
            eq(R.release_line(ls, st), 'release: V5 Release · building', 'status too')
        eq(U.release_row(ls, {'running': {'1': 'F1'}})['words'], 'waits for 2 open ahead', 'another task running')
        alone = [l.replace('critical) ', 'critical) (alone) ') for l in ls]
        eq(U.release_row(alone)['title'], 'Release', 'its (alone) tag is no title')
        blocked = NEXT + [V5.replace('[ ]', '[~]'), '  BLOCKED: CONFIRM: is it ok?']
        eq(U.release_row(blocked)['words'], 'blocked', 'waiting on a person')
        waits = NEXT + ['- [~] **V5** Release: x', '  BLOCKED: (after F1) its code']
        eq(U.release_row(waits)['words'], 'waits for 1 open ahead', 'blocked until another task lands')
        q = U.pin_release(U.queue_rows(ls), U.release_row(ls))
        eq([x['id'] for x in q], ['F1', 'F2', 'F3', 'V5'], 'pinned at the end, past a task queued after it')
        eq(q[-1]['release']['words'], 'waits for 2 open ahead', 'with its words')


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
    raise SystemExit(report([test_placeholder, test_queued, test_lately]))
