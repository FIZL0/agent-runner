#!/usr/bin/env python3
"""F65: the run page model builds one snapshot of a run, and each action runs the matching command.

    python3 tests/test_ui_model.py        (a temp repo, no agent, no network; about a second)

A fake run (a plan, STATE, run.log) is read into the snapshot: status lines, c1 and each slot with its task,
title, minutes, state, files and links, the queue with kind/title/files/after/pri, Needs you, concepts, the
log tail and the release line. Then each action, with the runner call swapped for a recorder, runs the plan
command it stands for, and chat, answers and take reach c1.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

TODO = """# TODO

## Now

### Next
- [ ] **F1** Board page for the run | files: a.py, tests/test_a.py
- [ ] **B2** Fix the merge retry | files: b.py | after: F1
- [~] **D3** Write the guide | files: docs/x.md BLOCKED: DECIDE: which layout https://claude.ai/artifact/abc
- [~] **F4** Build the option a person approves on concept K5 page: lazy layout | files: c.py BLOCKED: waiting for your OK on https://claude.ai/artifact/k5
- [ ] **V6** Release the next version | after: F1, B2

### Follow-ups
- [ ] **T7** (follow-up, low) Tidy the gate | files: run

### Parked
- [ ] **R8** Measure the cost | files: notes.md
"""

NOW = 1_800_000_000.0


def fake_run(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / '.gitignore').write_text('.runner/\n')
    (repo / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    U.tmux_panes = lambda: []  # C23: never this machine's tmux (its panes carry no tag of this fake repo)
    S.C.notes('STATE').write_text(json.dumps({
        'state': '3 slots', 'running': {'1': 'F1', '2': 'B2'}, 'since': {'1': NOW - 14 * 60, '2': NOW - 60},
        'merging': ['B2'], 'usage': {'five_hour': 42.0, 'seven_day': 85.0}}), encoding='utf-8')
    S.C.notes('run.log').write_text(''.join(f'=== 2026-11-21T10:{i:02d}:00 line {i}\n' for i in range(30)),
                                    encoding='utf-8')
    return repo


def test_snapshot(tmp: Path) -> None:
    fake_run(tmp)
    snap = U.snapshot(up=True, now=NOW, log_n=5, links={'s1': 'https://claude.ai/code/session_1'},
                      terminal_base='http://127.0.0.1:8765/')
    json.dumps(snap)  # JSON-ready, all of it
    eq(snap['up'], True, 'up as given')
    eq(snap['status'][0], 'run up: 3 slots', 'status opens with the run state')
    check(any('tasks left' in l for l in snap['status']), 'status has the progress line', snap['status'])
    check(any(l.startswith('release: waits on 2 of 2') for l in snap['status']), 'status has the release line',
          snap['status'])
    eq(snap['status'][-1], 'usage: session 42%, week 85%', 'status ends with usage')

    eq(snap['slots'], 3, "the run's slot count")
    names = [s['name'] for s in snap['sessions']]
    eq(names, ['c1', 's1', 's2', 's3'], 'c1, then every slot of the 3-slot run in order, the idle s3 too')
    eq(snap['sessions'][3], {'name': 's3', 'task': '', 'title': '', 'minutes': None, 'state': 'idle',
                             'files': [], 'link': '', 'terminal': ''}, 'an idle slot: no task, state idle')
    eq(snap['sessions'][0]['state'], 'off', 'no c1 runs in a fake run')
    s1, s2 = snap['sessions'][1], snap['sessions'][2]
    eq((s1['task'], s1['title'], s1['minutes'], s1['state'], s1['files']),
       ('F1', 'Board page for the run', 14, 'running', ['a.py', 'tests/test_a.py']), 'slot 1 row')
    eq(s1['link'], 'https://claude.ai/code/session_1', 'session link')
    eq(s1['terminal'], 'http://127.0.0.1:8765/terminal/s1', 'terminal URL under the base')
    eq((s2['task'], s2['minutes'], s2['state'], s2['link']), ('B2', 1, 'merging', ''), 'slot 2 merging, no link')

    q = {t['id']: t for t in snap['queue']}
    eq(list(q), ['F1', 'B2', 'D3', 'F4', 'V6', 'T7', 'R8'], 'every open task, in plan order')
    eq(q['B2']['after'], ['F1'], 'after')
    eq(q['B2']['files'], ['b.py'], 'files')
    check(q['F1']['kind'].startswith('feature'), 'kind from the id letter', q['F1']['kind'])
    eq((q['F1']['pri'], q['T7']['pri'], q['R8']['pri']), ('normal', 'low', 'later'), 'pri from tag and section')
    eq(q['T7']['title'], 'Tidy the gate', 'title without the level tag')
    eq((q['D3']['blocked'], q['F1']['blocked']), (True, False), 'blocked flag')

    needs = {n['id']: n for n in snap['needs']}
    eq(sorted(needs), ['D3', 'F4'], 'Needs you: the decide and the concept')
    eq((needs['D3']['label'], needs['D3']['url']), ('DECIDE', 'https://claude.ai/artifact/abc'), 'decide with link')
    check(needs['D3']['ask'], 'an ask in plain words', needs['D3'])
    eq(snap['concepts'], [{'id': 'F4', 'concept': 'K5', 'title': 'lazy layout',
                           'url': 'https://claude.ai/artifact/k5'}], 'concept with its page link')
    eq(snap['log'], [f'=== 2026-11-21T10:{i:02d}:00 line {i}' for i in range(25, 30)], 'run log tail')
    check(snap['release'].startswith('release: waits on 2 of 2 tasks (V6)'), 'release line', snap['release'])

    down = U.snapshot(up=False, now=NOW, links={})
    eq(down['status'][0], 'no run is up', 'no run: said so')
    eq([s['name'] for s in down['sessions']], ['c1'], 'no run: only c1')
    eq(down['slots'], 0, 'no run: no slots')


def test_idle_slots(tmp: Path) -> None:
    """F71: a 3-slot run on one task lists s1..s3, the idle ones with state idle; the count comes from
    STATE's `slots`, else its state line, else `[run] slots` while the run starts."""
    fake_run(tmp)
    S.C.notes('STATE').write_text(json.dumps({'state': '3 slots, paused', 'slots': 3, 'running': {'2': 'F1'},
                                              'since': {'2': NOW - 60}}), encoding='utf-8')
    snap = U.snapshot(up=True, now=NOW, links={})
    eq(snap['slots'], 3, 'slots from STATE')
    eq([(s['name'], s['task'], s['state']) for s in snap['sessions']],
       [('c1', '', 'off'), ('s1', '', 'idle'), ('s2', 'F1', 'running'), ('s3', '', 'idle')],
       'every slot listed, the idle ones with state idle')
    S.C.notes('STATE').write_text(json.dumps({'slots': 1, 'running': {'1': 'F1', '3': 'B2'}}), encoding='utf-8')
    eq([s['name'] for s in U.snapshot(up=True, now=NOW, links={})['sessions']], ['c1', 's1', 's3'],
       'a slot past the count still on its task stays listed; no idle s2 past the count')
    S.C.notes('STATE').write_text(json.dumps({'state': '2 slots', 'running': {}}), encoding='utf-8')
    eq(U.snapshot(up=True, now=NOW, links={})['slots'], 2, 'a STATE without slots: the count from its state line')
    S.C.notes('STATE').unlink()
    snap = U.snapshot(up=True, now=NOW, links={})
    eq((snap['slots'], [s['state'] for s in snap['sessions']]), (3, ['off', 'idle', 'idle', 'idle']),
       'the run starting, no STATE yet: [run] slots, all idle')


def test_actions(tmp: Path) -> None:
    fake_run(tmp)
    ran, sent = [], []
    real_run, real_send = U.RUN[0], U.SEND[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'ok'))[1]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    try:
        r = U.act('plan_add', kind='B', text='Fix X', files=['a.py', 'tests/test_a.py'], after='F1', pri='low')
        eq(r['ok'], True, 'an action that exits 0 is ok')
        U.act('plan_change', tid='F1', text='Board page, new words', files='a.py')
        U.act('drop', tid='B2', why='overtaken')
        U.act('shelve', tid='D3')
        U.act('release')
        U.act('release', now=True)
        eq(ran, [['plan', 'add', 'B', 'Fix X', '--files', 'a.py,tests/test_a.py', '--after', 'F1', '--pri', 'low'],
                 ['plan', 'edit', 'F1', 'Board page, new words', '--files', 'a.py'],
                 ['plan', 'drop', 'B2', 'overtaken'],
                 ['plan', 'shelve', 'D3'],
                 ['plan', 'add', 'V'],
                 ['plan', 'add', 'V', '--now']], 'each action runs its plan command')
        U.act('chat', text='how is it going?')
        U.act('answer', tid='D3', text='the lazy one')
        U.act('take', tid='F1')
        eq(sent, ['how is it going?', 'D3 (Write the guide): the lazy one', 'do F1 here'],
           'chat, answers and take go to c1')
        eq(U.act('nope')['ok'], False, 'an unknown action is an error result')
        eq(U.act('drop', tid='B2')['code'], 2, 'a missing argument is an error result')
        U.RUN[0] = lambda argv: (3, 'looks like F1')
        eq(U.plan_add('F', 'Board page')['ok'], False, 'a refused add is not ok')
    finally:
        U.RUN[0], U.SEND[0] = real_run, real_send


def test_real_command(tmp: Path) -> None:
    """One action through the real runner: `plan shelve` shelves D3 in the fake run's plan."""
    repo = fake_run(tmp)
    r = U.shelve('D3')
    check(r['ok'], 'plan shelve ran', r)
    check('BLOCKED: shelved: DECIDE' in (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
          'D3 is shelved in TODO.md', (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'))
    eq([n['id'] for n in U.snapshot(up=False, now=time.time(), links={})['needs']], ['F4'],
       'a shelved item leaves Needs you')


def test_to_c1_by_tag(tmp: Path) -> None:
    """B111: called from inside tmux ($TMUX_PANE is the caller's own pane), to_c1 types into the c1-tagged pane."""
    import os
    import subprocess as sp
    from unittest import mock
    from agent_runner import control as K, slots
    rows = (f'run\t%7\tc1\t{S.ROOT}\t\t4242\n'      # c1 of this repository
            f'run\t%3\t\t\t{S.ROOT}\t4100\n')       # the runner's own pane
    typed = []
    with mock.patch.dict(os.environ, {'TMUX_PANE': '%3'}), \
            mock.patch.object(K, 'control_live', return_value=4242), \
            mock.patch.object(K.shutil, 'which', return_value='/usr/bin/tmux'), \
            mock.patch.object(K, 'tmux', return_value=sp.CompletedProcess([], 0, rows, '')), \
            mock.patch.object(slots, 'send_to_pane', side_effect=lambda p, t: (typed.append((p, t)), True)[1]):
        r = U.to_c1('how is it going?')
    eq(r['out'], 'sent to c1', 'c1 got it')
    eq(typed, [('%7', 'how is it going?')], "typed into c1's tagged pane, not $TMUX_PANE")


def ifizbox_panes(root: Path, name: str) -> list[str]:
    """B113/C23: `tmux list-panes -a` lines (session, window name, @runner, @runner-repo) like iFizBox's run,
    every pane tagged as this version tags it."""
    s = 'agents'
    return [f'{s}\trunner-{name}\t\t{root}', f'{s}\tboard-{name}\tboard\t{root}',
            f'{s}\tagents-{name}\ts2\t{root}',
            f'{s}\t{name} · 9 · iOS 26 native glass +\tc9\t{root}',
            f'{s}\t{name} · 1 · Install IPAs row + wider\tc1\t{root}',
            f'{s}\t{name} · 6 · Pairing broken: Tailscale logout\tc6\t{root}',
            f'{s}\t{name} · R43 · site deploy\tc7\t{root}',           # a task-named control session
            f'{s}\t{name} · 3\tc3\t{root}', f'{s}\t{name} · control 4\tc4\t{root}',  # untitled
            f'{s}\t{name} · 8 · no tags\t\t',                          # untagged: never read by its name
            f'other\t{name} · 5 · another checkout\tc5\t/elsewhere/{name}']


def test_control_windows(tmp: Path) -> None:
    """C23: control session windows are read only by their tags (@runner cN, @runner-repo this checkout): c1,
    every other cN with its title, then s1..s3 from STATE; a window name alone never makes one."""
    repo = fake_run(tmp)
    S.C.notes('STATE').write_text(json.dumps({'state': '3 slots', 'running': {'2': 'F1'}, 'since': {},
                                              'merging': []}), encoding='utf-8')
    wins = U.control_windows(ifizbox_panes(repo, repo.name))
    eq(wins, {1: 'Install IPAs row + wider', 3: 'control session', 4: 'control session',
              6: 'Pairing broken: Tailscale logout', 7: 'R43 · site deploy', 9: 'iOS 26 native glass +'},
       "control windows by tag; another checkout's and the untagged one left out")
    eq(U.control_windows([f'ar-{repo.name}\t{repo.name} · control 3\t\t',
                          f'ar-{repo.name}\t{repo.name} · 2 · old\t\t']), {},
       "no tags: no window, whatever its name ('<repo> · control N', '<repo> · N · title')")
    from unittest import mock
    with mock.patch.object(U, 'tmux_panes', return_value=ifizbox_panes(repo, repo.name)):
        snap = U.snapshot(up=True, now=NOW, links={})
    eq([(s['name'], s['state']) for s in snap['sessions']],
       [('c1', 'live'), ('c3', 'live'), ('c4', 'live'), ('c6', 'live'), ('c7', 'live'), ('c9', 'live'),
        ('s1', 'idle'), ('s2', 'running'), ('s3', 'idle')], 'c1, each cN, then s1-s3')
    eq(snap['sessions'][0]['title'], 'Install IPAs row + wider', "c1 titled by its window")
    eq(snap['sessions_note'], '', 'a tagged run: no note')


def test_older_run(tmp: Path) -> None:
    """C23: a run that is up with no pane tagged for this checkout (an older agent-runner started it): Sessions
    has no rows, only the one restart line."""
    repo = fake_run(tmp)
    old = [f'ar-{repo.name}\trunner-{repo.name}\t\t', f'ar-{repo.name}\t{repo.name} · 1 · c1\t\t',
           f'ar-{repo.name}\t{repo.name} · control 2\t\t', f'other\tagents-x\ts1\t/elsewhere/x']
    from unittest import mock
    with mock.patch.object(U, 'tmux_panes', return_value=old):
        snap = U.snapshot(up=True, now=NOW, links={})
        down = U.snapshot(up=False, now=NOW, links={})
    eq((snap['sessions'], snap['sessions_note']), ([], U.OLDER_RUN), 'no rows, the one restart line')
    eq(U.OLDER_RUN, 'This run was started by an older agent-runner: restart it to see its sessions.', 'its words')
    eq(([s['name'] for s in down['sessions']], down['sessions_note']), (['c1'], ''), 'no run up: no note')
    eq(U.older_run(True, []), False, 'no tmux panes to read: nothing told')
    eq(U.older_run(True, ifizbox_panes(repo, repo.name)), False, 'tagged panes: not older')


def in_tmp(f):
    def go():
        print(f.__name__)
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_snapshot), in_tmp(test_idle_slots), in_tmp(test_actions), in_tmp(test_real_command),
                         in_tmp(test_to_c1_by_tag), in_tmp(test_control_windows), in_tmp(test_older_run)]))
