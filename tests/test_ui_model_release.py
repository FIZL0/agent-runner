#!/usr/bin/env python3
"""F65, C44: the run page model: the releases of a snapshot and its release actions.

    python3 tests/test_ui_model_release.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import json
import re
import threading
import time
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,TODO, NOW, fake_run  # noqa: E402


def test_manage_releases_f193(tmp: Path) -> None:
    """F193: `[run] releases` off: nothing of releases in the snapshot (an open V task is an ordinary queue row), nor in
    status; a stale page's New release is refused, a typed `plan add V` is not."""
    from agent_runner import plan as P
    from agent_runner.status import release_line
    repo = fake_run(tmp)
    todo, notes = repo / 'plan' / 'TODO.md', S.C.notes('events.jsonl')
    was = notes.read_text(encoding='utf-8') if notes.exists() else ''
    notes.write_text(was + json.dumps({'time': '2026-01-01T10:00:00', 'kind': S.EV_LANDED, 'id': 'V1', 'text': 'V1: merged'}) + '\n',
                     encoding='utf-8')  # a landed release
    v6 = next(l for l in TODO.splitlines() if '**V6**' in l)
    todo.write_text(TODO.replace(v6, '- [ ] **V5** ' + P.RELEASE_BRIEF + ' | after: all\n- [ ] **T9** Release by hand | after: F1\n' + v6), encoding='utf-8')
    S.C.run['auto_release'] = {'every': 10, 'idle': True}
    snap = lambda: U.snapshot(up=True, now=NOW, links={})  # noqa: E731
    parts = lambda s: (s['manage_releases'], s['releases'], s['release'], s['release_acts'], s['release_said'])  # noqa: E731
    on = snap()
    eq((on['manage_releases'], {r['id'] for r in on['releases']}), (True, {'V5', 'V6', 'V1'}), 'on: the rows')
    eq({q['id'] for q in on['queue'] if 'release' in q}, {'V5', 'V6'}, 'on: pinned with their rows')
    check('V1' in on['release'] and any(l.startswith('release: ') for l in on['status']), 'on: status says them', on['status'])
    S.C.run['releases'] = False
    off = snap()
    eq(parts(off), (False, [], '', [], ''), 'off: none of it')
    check(not any('release: ' in l for l in off['status']), 'off: nor a status line', off['status'])
    eq(release_line(P.lines(todo), {}), '', "nor in `status`, for a release that is no V task either")
    eq([q['id'] for q in off['queue']], [q['id'] for q in U.queue_rows(P.lines(todo), {}, NOW)], 'V tasks keep their place')
    for q in off['queue']:
        if q['id'] in ('V5', 'V6'):
            check('release' not in q and 'started' not in q and 'asks' not in q, 'an ordinary row', q)
            eq(q['acts'], ['queue_priority', 'queue_take', 'queue_drop'], 'with its actions')
    with mock.patch.object(U, '_state', lambda up: {'running': {'1': 'V6'}}):
        check('queue_drop' in U.row_acts('queue', U.queue_row('V6')), 'running too, as any task')
    todo.write_text('\n'.join(l for l in todo.read_text(encoding='utf-8').splitlines() if '**V' not in l) + '\n', encoding='utf-8')
    eq(parts(snap()), (False, [], '', [], ''), 'off, no V: no placeholder, no landed release')
    S.C.run['releases'] = True
    eq([(r['state']) for r in snap()['releases']], ['auto', 'released'], 'back on: both')
    S.C.run['releases'] = False
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
        for key in ('release_wait', 'release_now'):
            r = U.act('run_control', key=key, confirm=True, text='V6')
            eq((r['ok'], r['out'], ran), (False, 'Manage releases is off in Settings: no release was queued', []), f'{key}: refused')
    toml = repo / 'runner.toml'
    old = toml.read_text(encoding='utf-8') if toml.exists() else ''
    toml.write_text(old.replace('[run]\n', '[run]\nreleases = false\n', 1) if '[run]\n' in old else old + '\n[run]\nreleases = false\n',
                    encoding='utf-8')
    code, out = U._run(['plan', 'add', 'V'])
    check(code == 0 and '**V' in todo.read_text(encoding='utf-8'), 'plan add V typed works', out)
    code, out = U._run(['plan'])
    check(code == 0 and '## Releases' not in out and re.search(r'\bV\d+', out), '`plan` lists it as a task', out)


def test_new_release_f186(tmp: Path) -> None:
    """F186: New release queues one when none is open; with one open it says so and asks, and a Yes counts only for the
    releases open then, so no double press queues another unasked."""
    todo = fake_run(tmp) / 'plan' / 'TODO.md'
    v6 = next(l for l in TODO.splitlines() if '**V6**' in l)
    todo.write_text(TODO.replace(v6 + '\n', ''), encoding='utf-8')
    ran, ids = [], iter(('V6', 'V7', 'V8'))

    def run(argv):
        ran.append(argv)
        ls = todo.read_text(encoding='utf-8')
        todo.write_text(ls.replace('### Follow-ups', f'- [ ] **{next(ids)}** Release it | after: all\n### Follow-ups'), encoding='utf-8')
        return 0, 'added'
    rel = lambda: {c['key']: (c['confirm'], c['seen']) for c in U.snapshot(up=True, now=NOW, links={})['controls']  # noqa: E731
                   if c['where'] == 'release'}
    with mock.patch.object(U, 'RUN', [run]):
        eq(rel(), {'release_wait': ('', ''), 'release_now': ('', '')}, 'none open: nothing to ask')
        eq((U.act('run_control', key='release_wait')['ok'], ran), (True, [['plan', 'add', 'V']]), 'add: queued at once')
        for key in ('release_wait', 'release_now'):
            r = U.act('run_control', key=key)
            eq((r['ok'], r['code'], r['confirm'], r['seen'], len(ran)),
               (False, 3, 'V6 is already queued. Queue another release?', 'V6', 1), f'{key} again: no silent duplicate')
        eq(U.snapshot(up=True, now=NOW, links={})['release_said'], 'V6 is already queued', 'the snapshot says so')
        eq(rel()['release_wait'], ('V6 is already queued. Queue another release?', 'V6'), 'and its action asks')
        eq(U.run_control('release_wait', confirm=True)['ok'], False, 'a Yes that names no release is asked again')
        eq((U.run_control('release_wait', confirm=True, text='V6')['ok'], len(ran)), (True, 2), 'confirmed: a second')
        r = U.run_control('release_wait', confirm=True, text='V6')
        eq((r['ok'], r['seen'], len(ran)), (False, 'V6 V7', 2), 'the same Yes sent twice asks again')
        with mock.patch.object(U, '_state', lambda up: {'running': {'1': 'V6'}}):
            eq(U.run_control('release_now')['confirm'], 'V6 is releasing now; V7 is already queued. Queue another release?',
               'one that runs is named too')
        with mock.patch('agent_runner.sched.taken', lambda: {'V6': tmp}):
            check(U.run_control('release_now')['confirm'].startswith('V6 is taken by a person; V7 is already queued'), 'and one taken')
        from agent_runner import plat
        with plat.lock(S.C.notes('release.lock')), mock.patch.object(U, 'RELEASE_WAIT', 0.1):
            r = U.run_control('release_now', confirm=True, text='V6 V7')
            eq((r['code'], len(ran)), (1, 2), 'while another page or TUI queues one, this one adds nothing')
    todo.write_text(TODO.replace(v6 + '\n', ''), encoding='utf-8')
    ran.clear()
    ids = iter(('V6', 'V7', 'V8'))
    with mock.patch.object(U, 'RUN', [run]):
        ts = [threading.Thread(target=U.run_control, args=('release_now',)) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
    eq(len(ran), 1, 'pressed at once from three places: one release')


def test_drop_release_f186(tmp: Path) -> None:
    """F186: a release not started drops on its confirm; one a slot runs, that merges or that a person took does not."""
    fake_run(tmp)
    ran = []
    v6 = lambda: next(q for q in U.snapshot(up=True, now=NOW, links={})['queue'] if q['id'] == 'V6')  # noqa: E731
    ask = 'Drop V6? It leaves the plan, and nothing is released.'
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
        eq((v6()['asks'], 'queue_drop' in v6()['acts']), ({'queue_drop': ask}, True), 'its row has Drop and its question')
        eq((U.run_control('queue_drop', tid='V6')['confirm'], ran), (ask, []), 'asked first')
        eq(U.run_control('queue_drop', tid='V6', confirm=True)['ok'], True, 'then dropped')
        eq(ran, [['plan', 'drop', 'V6', 'dropped from the run app']], 'plan drop')
        ran.clear()
        for what, st in (('running', {'running': {'1': 'V6'}}), ('merging', {'merging': ['V6']}), ('taken', {})):
            with mock.patch.object(U, '_state', lambda up, st=st: st), \
                    mock.patch('agent_runner.sched.taken', lambda: {'V6': tmp} if what == 'taken' else {}):
                check('queue_drop' not in v6()['acts'] and 'asks' not in v6(), f'{what}: no Drop', v6())
                r = U.run_control('queue_drop', tid='V6', confirm=True)
                eq((r['ok'], r['out'], ran), (False, 'V6 has started: a running release cannot be dropped', []), f'{what}: refused')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_manage_releases_f193), in_tmp(test_new_release_f186), in_tmp(test_drop_release_f186)]))
