#!/usr/bin/env python3
"""F415: a bug fix waits while an earlier task on the same files awaits the person's check (CONFIRM).

    python3 tests/test_sched_unchecked.py        (no git)
"""
from __future__ import annotations

from types import SimpleNamespace

from _check import eq, report

from agent_runner import sched as S  # noqa: E402

PLAN = '''# TODO

### Next

- [~] **B1** talk fix | files: talk.py BLOCKED: CONFIRM: try a call on the phone
- [~] **B2** other fix | files: other.py BLOCKED: shelved: CONFIRM: check it
- [ ] **B3** next talk fix | files: talk.py
- [ ] **B4** other fix again | files: other.py
- [ ] **F5** talk feature | files: talk.py
- [ ] **B6** unrelated | files: z.py
'''


def todo(ls):
    return [(tid, '', set(S.P.fields(ls[i]).get('files', [])), set())
            for _, box, tid, _, i in S.P.iter_tasks(ls) if box == ' ']


def held(ls, **kw):
    t = todo(ls)
    return S.Held(t, [], set(), set(), set(), {}, set(), unchecked=S.unchecked_holds(ls, t), **kw), t


def test_hold():
    print('a bug task on the files of a CONFIRM task waits; shelved, other kinds and other files do not')
    ls = PLAN.splitlines()
    h, t = held(ls)
    eq(h.unchecked, {'B3': 'B1'}, 'only B3 is held, by B1')
    why = {x[0]: S.holds(x, set(), h) for x in t}
    eq(why['B3'], ('unchecked', 'B1'), 'B3 waits for the check of B1')
    eq(why['B4'], None, 'a shelved CONFIRM holds nothing')
    eq(why['F5'], None, 'a feature is not held')
    eq(why['B6'], None, 'other files are not held')


def test_release_on_confirm():
    print('once the person confirms (the task is ticked), the fix is free')
    ls = PLAN.replace('- [~] **B1** talk fix | files: talk.py BLOCKED: CONFIRM: try a call on the phone',
                      '- [x] **B1** talk fix | files: talk.py').splitlines()
    h, t = held(ls)
    eq(h.unchecked, {}, 'nothing held')


def test_critical_and_high():
    print('critical and high tasks pass the hold')
    ls = PLAN.splitlines()
    for kw in ({'critical': frozenset({'B3'})}, {'high': frozenset({'B3'})}):
        h, t = held(ls, **kw)
        eq(S.holds(next(x for x in t if x[0] == 'B3'), set(), h), None, f'{kw} passes')


if __name__ == '__main__':
    S.C = SimpleNamespace(pr=False)  # holds() reads only C.pr here
    raise SystemExit(report([test_hold, test_release_on_confirm, test_critical_and_high]))
