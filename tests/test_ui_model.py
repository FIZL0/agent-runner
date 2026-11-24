#!/usr/bin/env python3
"""F65: the run page model builds one snapshot of a run, and each action runs the matching command.

    python3 tests/test_ui_model.py        (a temp repo, no agent, no network; about a second)

A fake run (a plan, STATE, run.log) is read into the snapshot: status lines, c1 and each slot with its task,
title, minutes, state, files and links, the queue with kind/title/files/after/pri, Needs you, concepts, the
log tail and the release line. Then each action, with the runner call swapped for a recorder, runs the plan
command it stands for, and chat and answers reach c1.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import tempfile
import time
from pathlib import Path
from unittest import mock

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
    check(any(l.startswith('release: V6 Release the next version · waits for 2 open ahead') for l in snap['status']), 'status has the release line',
          snap['status'])
    eq(snap['status'][-1], 'usage: session 42%, week 85%', 'status ends with usage')

    eq(snap['slots'], 3, "the run's slot count")
    names = [s['name'] for s in snap['sessions']]
    eq(names, ['s1', 's2', 's3'], 'every slot of the 3-slot run in order, the idle s3 too')
    eq(snap['sessions'][2], {'name': 's3', 'task': '', 'title': '', 'minutes': None, 'state': 'idle',
                             'files': [], 'link': '', 'terminal': '', 'task_controls': False, 'acts': []}, 'an idle slot: no task, state idle')
    s1, s2 = snap['sessions'][0], snap['sessions'][1]
    eq((s1['task'], s1['title'], s1['minutes'], s1['state'], s1['files']),
       ('F1', 'Board page for the run', 14, 'running', ['a.py', 'tests/test_a.py']), 'slot 1 row')
    eq(s1['link'], 'https://claude.ai/code/session_1', 'session link')
    eq(s1['terminal'], 'http://127.0.0.1:8765/terminal/s1', 'terminal URL under the base')
    eq((s2['task'], s2['minutes'], s2['state'], s2['link']), ('B2', 1, 'merging', ''), 'slot 2 merging, no link')

    q = {t['id']: t for t in snap['queue']}
    eq(list(q), ['F1', 'B2', 'D3', 'F4', 'T7', 'R8', 'V6'], 'every open task, in plan order, the release last (F131)')
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
                           'url': 'https://claude.ai/artifact/k5', 'copy': '',
                           'acts': ['concept_chat', 'concept_drop']}], 'concept with its page link')
    eq(snap['log'], [f'=== 2026-11-21T10:{i:02d}:00 line {i}' for i in range(25, 30)], 'run log tail')
    eq(snap['release'], 'release: V6 Release the next version · waits for 2 open ahead', 'release line')

    down = U.snapshot(up=False, now=NOW, links={})
    eq(down['status'][0], 'no run is up', 'no run: said so')
    eq([s['name'] for s in down['sessions']], [], 'no run and no chat: no rows')
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
       [('s1', '', 'idle'), ('s2', 'F1', 'running'), ('s3', '', 'idle')],
       'every slot listed, the idle ones with state idle')
    S.C.notes('STATE').write_text(json.dumps({'slots': 1, 'running': {'1': 'F1', '3': 'B2'}}), encoding='utf-8')
    eq([s['name'] for s in U.snapshot(up=True, now=NOW, links={})['sessions']], ['s1', 's3'],
       'a slot past the count still on its task stays listed; no idle s2 past the count')
    S.C.notes('STATE').write_text(json.dumps({'state': '2 slots', 'running': {}}), encoding='utf-8')
    eq(U.snapshot(up=True, now=NOW, links={})['slots'], 2, 'a STATE without slots: the count from its state line')
    S.C.notes('STATE').unlink()
    snap = U.snapshot(up=True, now=NOW, links={})
    eq((snap['slots'], [s['state'] for s in snap['sessions']]), (3, ['idle', 'idle', 'idle']),
       'the run starting, no STATE yet: [run] slots, all idle')


def test_version_f90(tmp: Path) -> None:
    """F90: the run writes its version into STATE and the snapshot carries it as 'version'; '' when STATE has
    none (an older run) or no run is up."""
    from agent_runner import __version__, loop
    fake_run(tmp)
    eq(U.snapshot(up=True, now=NOW, links={})['version'], '', 'a STATE with no version (an older run): empty')
    loop.write_state({})
    eq(json.loads(S.C.notes('STATE').read_text(encoding='utf-8')).get('version'), __version__,
       "write_state puts the run's version in STATE")
    eq(U.snapshot(up=True, now=NOW, links={})['version'], __version__, 'the snapshot carries it')
    S.C.notes('STATE').write_text(json.dumps({'state': '1 slot', 'running': {}, 'version': '9.9.9'}),
                                  encoding='utf-8')
    eq(U.snapshot(up=True, now=NOW, links={})['version'], '9.9.9', "the version from STATE, not this process's")
    eq(U.snapshot(up=False, now=NOW, links={})['version'], '', 'no run up: empty')


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
        eq(ran, [['plan', 'add', 'B', 'Fix X', '--files', 'a.py,tests/test_a.py', '--after', 'F1', '--pri', 'low'],
                 ['plan', 'edit', 'F1', 'Board page, new words', '--files', 'a.py'],
                 ['plan', 'drop', 'B2', 'overtaken']], 'each action runs its plan command')
        U.act('chat', text='how is it going?')
        U.act('answer', tid='D3', text='the lazy one')
        eq(sent, ['how is it going?', 'D3 (Write the guide): the lazy one'], 'chat and answers go through SEND')
        eq(U.act('nope')['ok'], False, 'an unknown action is an error result')
        eq(U.act('drop', tid='B2')['code'], 2, 'a missing argument is an error result')
        U.RUN[0] = lambda argv: (3, 'looks like F1')
        eq(U.plan_add('F', 'Board page')['ok'], False, 'a refused add is not ok')
    finally:
        U.RUN[0], U.SEND[0] = real_run, real_send


RUN_CONTROL_ARGV = {  # F82: each run control and the runner command it must run
    'slot_add': ['slots', '+1'], 'slot_remove': ['slots', '-1'], 'slots_set': ['slots', '4'],
    'pause': ['pause'], 'go_on': ['pause', '--off'], 'force': ['force'], 'caps_on': ['force', '--off'],
    'stop': ['stop'], 'stop_now': ['stop', '--force'], 'stop_undo': ['stop', '--undo'],
    'task_drop': ['plan', 'drop', 'F1', U.TASK_DROP_WHY],
    'upgrade': ['key', 'u'], 'suspend': ['key', 'z'], 'shutdown': ['key', 'x'],  # C26: the run's u, z, x keys
    'restart': ['key', 'restart'], 'start': [], 'resume': ['resume', 'F1'], 'unclaim': ['plan', 'unclaim', 'F1'],  # F124
    'wip_show': ['wip', 'show', 'main-checkout-1'], 'wip_restore': ['wip', 'restore', 'main-checkout-1'],
    'wip_drop': ['wip', 'drop', 'main-checkout-1']}


def test_run_controls(tmp: Path) -> None:
    """F82: one list of run controls, each to its runner command; stop now runs only once confirmed."""
    fake_run(tmp)
    ran, sent = [], []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent',
                                                                             'argv': []})[1]]):
        for windows in (False, True):  # B163: no re-exec on Windows, so no restart there
            want = {*RUN_CONTROL_ARGV, 'task_take', 'queue_take', 'queue_drop', 'queue_priority', 'queue_unpark',
                    'release_wait', 'release_now', 'need_later', 'need_chat', 'need_drop', 'concept_chat',
                    'concept_drop', 'session_close'} - ({'restart'} if windows else set())
            on = ' (Windows)' if windows else ''
            with mock.patch('agent_runner.plat.WINDOWS', windows):
                cs = U.controls()
            eq(sorted(c['key'] for c in cs), sorted(want), f'the list holds every control the task names{on}')
            eq(len({(c['where'], c['tui']) for c in cs}), len(want), f'each has a key of its own in its panel{on}')
        for key, argv in RUN_CONTROL_ARGV.items():
            ran.clear()
            r = U.act('run_control', key=key, n='4', tid='main-checkout-1' if 'wip' in key else 'F1', confirm=True)
            eq((r['ok'], ran), (True, [argv]), f'{key} runs {" ".join(argv)}')
        ran.clear()
        r = U.act('run_control', key='stop_now')
        eq((r['ok'], r['code'], ran, r['confirm'] == U.STOP_NOW_ASK), (False, 3, [], True),
           'stop now without its confirm runs nothing and asks')
        eq(U.run_control('stop_now', confirm='yes')['ok'], False, 'only confirm=true confirms')
        r = U.act('run_control', key='task_take', tid='F1', wait=False)
        eq((r['ok'], sent, ran), (True, [], [['control', '--new', '--no-wait', '--ask', 'do F1 here', '--no-feed']]),
           'B139: take back asks a new control session "do F1 here", not c1')
        ran.clear()
        for bad in ({'key': 'slots_set', 'n': '-2'}, {'key': 'slots_set', 'n': '4; rm'}, {'key': 'slots_set'},
                    {'key': 'task_drop', 'tid': '--force'}, {'key': 'nope'}, {'key': 'resume'},
                    {'key': 'wip_drop', 'tid': 'task/F1', 'confirm': True}):
            r = U.act('run_control', **bad)
            eq((r['ok'], r['code']), (False, 2), f'refused: {bad}')
        eq(ran, [], 'a refused control runs nothing')
        by = {c['key']: c for c in U.controls()}
        eq((by['slots_set']['needs'], by['task_drop']['needs'], by['task_take']['needs'], by['pause']['needs']),
           ('n', 'id', 'id', ''), 'what each needs typed')


def test_row_actions(tmp: Path) -> None:
    """C34: the one list of row actions: each entry has an action and a TUI key of its own on its panel; each
    snapshot row carries the keys allowed on it, and an action runs only on a row it fits, checked again."""
    fake_run(tmp)
    seen = set()
    for c in U.RUN_CONTROLS:
        check(c.get('argv') or c.get('ask') or c.get('fn') or c['key'] == 'start', f'{c["key"]} has an action', c)
        for k in (c['tui'], c.get('tui_also')):
            check(k is None or (c['where'], k) not in seen, f'{c["key"]}: {k} is no other key of {c["where"]}')
            seen.add((c['where'], k))
    snap = U.snapshot(up=True, now=NOW, links={})
    acts = {q['id']: q['acts'] for q in snap['queue']}
    eq(acts['F1'], ['queue_priority', 'queue_take', 'queue_drop'], 'a queued task: priority, do it here, drop')
    eq(acts['R8'], ['queue_unpark', 'queue_take', 'queue_drop'], 'a parked task: unpark, not priority')
    eq(snap['release_acts'], ['release_wait', 'release_now'], 'the release tab\'s actions')
    eq({n['id']: n['acts'] for n in snap['needs']}, {'D3': ['need_later', 'need_chat', 'need_drop'],
                                                     'F4': ['need_later', 'need_chat', 'need_drop']}, 'C35: a Needs you item')
    eq([c['acts'] for c in snap['concepts']], [['concept_chat', 'concept_drop']], 'a concept: chat, drop')
    eq({s['name']: s['acts'] for s in snap['sessions'] if s['acts']}, {n: ['session_close'] for n in
       [s['name'] for s in snap['sessions'] if re.fullmatch(r'c\d+', s['name'])]}, 'only a control session closes')
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
        eq(U.run_control('queue_priority', tid='F1')['ok'], True, 'priority runs')
        eq(U.run_control('queue_unpark', tid='R8')['ok'], True, 'unpark runs')
        eq(ran, [['plan', 'edit', 'F1', '--pri', 'critical'], ['plan', 'edit', 'R8', '--pri', 'normal']],
           'their plan commands')
        ran.clear()
        for key, tid in (('queue_unpark', 'F1'), ('queue_priority', 'R8'), ('queue_drop', 'ZZ9'), ('queue_drop', '')):
            r = U.run_control(key, tid=tid, confirm=True)
            eq((r['ok'], r['code']), (False, 1), f'{key} on {tid or "nothing"} is refused')
        r = U.run_control('queue_drop', tid='F1')
        eq((r['ok'], r['code'], r['confirm'] != '', ran), (False, 3, True, []), 'drop asks first')
        eq(U.run_control('queue_drop', tid='F1', confirm=True)['ok'], True, 'and runs once confirmed')
        eq(ran, [['plan', 'drop', 'F1', 'dropped from the run app']], 'plan drop')
        ran.clear()
        U.run_control('release_now')
        eq(ran, [['plan', 'add', 'V', '--now']], 'release now')
        ran.clear()
        r = U.run_control('need_drop', tid='D3')
        check(not r['ok'] and r['confirm'].startswith('Drop D3?') and not ran, 'C35: a Needs you drop asks first', r)
        r = U.run_control('need_drop', tid='D3', confirm=True)
        eq((r['ok'], r['gone'], ran), (True, 'D3', [['plan', 'drop', 'D3', 'dropped from Needs you']]), 'then drops it')
        ran.clear()
        eq(U.run_control('concept_drop', tid='K5', confirm=True)['ok'], True, 'a concept drops by its concept id too')
        eq(ran, [['plan', 'drop', 'K5', 'dropped from agent-runner ui']], 'plan drop')
        for key, tid in (('need_later', 'ZZ9'), ('need_drop', '--x'), ('concept_drop', 'D3'), ('session_close', 'x')):
            eq(U.run_control(key, tid=tid, confirm=True)['code'], 1, f'{key} on {tid} is refused')
        with mock.patch('agent_runner.control.close_from_tui', lambda n: {'ok': True, 'out': f'c{n} closed'}):
            eq(U.run_control('session_close', tid='c6')['out'], 'c6 closed', 'a control session closes')


def test_real_command(tmp: Path) -> None:
    """One action through the real runner: Later (`plan shelve`) shelves D3 in the fake run's plan."""
    repo = fake_run(tmp)
    r = U.run_control('need_later', tid='D3')
    eq((r.get('said'), r.get('gone')), ('D3 is set aside until you bring it back', 'D3'), 'its toast, and gone')
    check(r['ok'], 'plan shelve ran', r)
    check('BLOCKED: shelved: DECIDE' in (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
          'D3 is shelved in TODO.md', (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'))
    eq([n['id'] for n in U.snapshot(up=False, now=time.time(), links={})['needs']], ['F4'],
       'a shelved item leaves Needs you')


def test_to_new(tmp: Path) -> None:
    """F176: a prompt starts a new control session, also while an older runner's c1 is live."""
    from unittest import mock
    from agent_runner import control as K
    fake_run(tmp)
    typed = []
    with mock.patch.object(K, 'control_live', return_value=4242), \
            mock.patch.object(K, 'control_type', side_effect=lambda n, t: (typed.append((n, t)), True)[1]):
        ran = []
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
            U.to_new('hello')
            U.to_new('again')
    eq(typed, [], 'nothing is typed into a chat')
    eq(ran, [['control', '--new', '--no-wait', '--ask', t, '--no-feed'] for t in ('hello', 'again')], 'each its own')


def test_control_titles(tmp: Path) -> None:
    """C26: the live control sessions, titled from the names kept in state (controlN.title), never from a
    window: every live cN, then s1..s3 from STATE."""
    import subprocess as sp
    repo = fake_run(tmp)
    S.C.notes('STATE').write_text(json.dumps({'state': '3 slots', 'running': {'2': 'F1'}, 'since': {},
                                              'merging': []}), encoding='utf-8')
    live = sp.Popen(['sleep', '60'])
    try:
        named = {1: f'{repo.name} · 1 · Install IPAs row + wider', 3: f'{repo.name} · 3',
                 4: f'{repo.name} · control 4', 6: f'{repo.name} · 6 · Pairing broken: Tailscale logout',
                 7: f'{repo.name} · R43 · site deploy', 9: ''}
        for n, name in named.items():
            S.C.notes(f'control{n}.pid').write_text(f'{live.pid}', encoding='utf-8')
            if name:
                S.C.notes(f'control{n}.title').write_text(name + '\n', encoding='utf-8')
        S.C.notes('control5.pid').write_text('999999999', encoding='utf-8')  # ended: not listed
        S.C.notes('control5.title').write_text(f'{repo.name} · 5 · gone\n', encoding='utf-8')
        eq(U.control_titles(), {1: 'Install IPAs row + wider', 3: 'control session', 4: 'control session',
                                6: 'Pairing broken: Tailscale logout', 7: 'R43 · site deploy', 9: 'control session'},
           'each live one, titled from state; the ended one left out')
        snap = U.snapshot(up=True, now=NOW, links={})
    finally:
        live.kill()
        live.wait()
    eq([(s['name'], s['state']) for s in snap['sessions']],
       [('c1', 'live'), ('c3', 'live'), ('c4', 'live'), ('c6', 'live'), ('c7', 'live'), ('c9', 'live'),
        ('s1', 'idle'), ('s2', 'running'), ('s3', 'idle')], 'each cN, then s1-s3')
    eq(snap['sessions'][0]['title'], 'Install IPAs row + wider', 'c1 titled from state')
    eq(snap['sessions_note'], '', 'no note')


QUEUE_TODO = """# TODO

## Now

### Next
- [ ] **F1** Board page for the run | files: a.py
- [ ] **F66** Run page: lazygit layout on web | files: w.py
- [ ] **B2** Fix the merge retry | files: b.py | after: B109
- [ ] **F67** Terminal pane per slot | files: t.py | after: F66
- [ ] **B3** (follow-up, critical) The gate hangs | files: g.py
- [ ] **B4** Typo in after | files: h.py | after: Z99
- [~] **D5** Write the guide | files: d.md BLOCKED: DECIDE: which layout
- [ ] **V6** Release the next version | after: all
- [~] **R6** Check status on Windows | files: r.md BLOCKED: shelved: CONFIRM: run it on the laptop
- [ ] **V5** Release: bump the version where the project keeps it, tag and publish | files: v.py
- [ ] **F8** After the release | files: f.py | after: V5,R6

### Parked
- [ ] **F83** Big future work for a person to schedule | files: p.py
"""


def test_queue_rows(tmp: Path) -> None:
    """F74: each queue row carries after's title (the open task's title, '(landed)' for a done one, 'all:
    everything above it') and a state: running sN Nm, critical, after, ready."""
    repo = fake_run(tmp)
    (repo / 'plan' / 'TODO.md').write_text(QUEUE_TODO, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n\n- [x] **B109** Take back a task\n', encoding='utf-8')
    S.C.notes('STATE').write_text(json.dumps({'state': '2 slots', 'running': {'2': 'F1'},
                                              'since': {'2': NOW - 6 * 60}}), encoding='utf-8')
    q = {t['id']: t for t in U.snapshot(up=True, now=NOW, links={})['queue']}
    eq({t: q[t]['after_title'] for t in q},
       {'F1': '', 'F66': '', 'B2': 'B109 (landed)', 'F67': 'F66 Run page', 'B3': '',
        'B4': 'Z99 (not in the plan)', 'D5': '', 'V6': 'all: everything above it', 'V5': '',
        'F8': 'V5 Release, R6 Check status on Windows', 'F83': ''},
       "after's title: open (id and short title only, B115), landed (in DONE.md), not in the plan, all")
    check('R6' not in q, 'B115: a shelved task is not in the queue the page gets')
    eq({t: q[t]['state'] for t in q},
       {'F1': 'running s2 6m', 'F66': 'ready', 'B2': 'ready', 'F67': 'after', 'B3': 'critical', 'B4': 'ready',
        'D5': 'blocked', 'V6': 'after', 'V5': 'ready', 'F8': 'after', 'F83': 'parked'},
       'state: running sN Nm, ready, after (an open task ahead), critical, blocked ([~]), parked (B118)')
    eq(q['F83']['pri'], 'later', 'B118: a task under Parked is level later')
    check(all(q[t]['state'].split()[0] in U.QUEUE_STATES for t in q), 'every state is one of QUEUE_STATES')


def fake_transcript(path: Path) -> Path:
    """A Claude Code JSONL transcript: a person's message, the agent's words, a tool call and its result, a
    runner turn, thinking, a subagent's entry and a torn last line."""
    rows = [
        {'type': 'user', 'message': {'role': 'user', 'content': 'status?'}},
        {'type': 'assistant', 'message': {'content': [{'type': 'thinking', 'thinking': 'hm'},
                                                      {'type': 'text', 'text': 'Checking the run.'},
                                                      {'type': 'tool_use', 'name': 'Bash',
                                                       'input': {'command': './run status -n 20'}}]}},
        {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'run up: 3 slots\nl2\nl3\nl4'}]}},
        {'type': 'user', 'isMeta': True, 'message': {'content': 'meta'}},
        {'type': 'user', 'message': {'content': '<command-name>/rename</command-name>'}},
        {'type': 'assistant', 'isSidechain': True, 'message': {'content': [{'type': 'text', 'text': 'sub'}]}},
        {'type': 'system', 'content': 'x'},
        {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Nothing needs you.'}]}},
        {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}},
    ]
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows) + '{"type": "assi', encoding='utf-8')
    return path


def test_feed(tmp: Path) -> None:
    """F74: a session's feed is its transcript as say/you/tool/out entries, newest last; a session with no transcript says so."""
    from unittest import mock
    fake_run(tmp)
    t = fake_transcript(tmp / 'c2.jsonl')
    with mock.patch.object(U, 'transcript_of', side_effect=lambda n: str(t) if n == 'c2' else ''), \
            mock.patch.object(U, 'session_sid', return_value=''):
        f = U.feed('c2')
        none = U.feed('s3')
        eq(U.feed('c2', limit=2)['entries'], f['entries'][:1] + f['entries'][-2:],
           'a limit keeps the newest, after the latest prompt (B154)')
        check(U.feed('c2', limit=2)['more'], 'and says older ones were left out')
    eq(f['entries'], [{'kind': 'you', 'text': 'status?'}, {'kind': 'say', 'text': 'Checking the run.'},
                      {'kind': 'tool', 'text': 'Bash(./run status -n 20)'},
                      {'kind': 'out', 'text': 'run up: 3 slots\nl2\nl3\n…'},
                      {'kind': 'say', 'text': 'Nothing needs you.'}, {'kind': 'out', 'text': 'interrupted'}],
       'the feed: you, say, tool, out; meta, runner turns, thinking and subagents left out')
    eq((f['ok'], f['more']), (True, False), 'a whole feed')
    check(not none['ok'] and none['entries'] == [] and 'no transcript' in none['out'], 'no transcript: said', none)
    big = tmp / 'big.jsonl'
    last = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'tail'}]}}) + '\n'
    big.write_text(json.dumps({'type': 'user', 'message': {'content': 'x' * 100}}) + '\n' + last, encoding='utf-8')
    eq([d['type'] for d in U.tail_rows(str(big), nbytes=len(last) + 10)], ['assistant'],
       'a tail read skips the line it cut')


def test_feed_prompt_b154(tmp: Path) -> None:
    """B154: the feed always holds the person's latest prompt, however long the turn after it, and 'more' says the
    tail is cut; a message queued in a turn (an attachment, no user entry) is the person's too; 'at' is when."""
    from unittest import mock
    fake_run(tmp)

    def row(d: dict) -> str:
        return json.dumps(d) + '\n'

    def you(text: str, at: str = '2026-11-23T10:00:00.500Z') -> str:
        return row({'type': 'user', 'timestamp': at, 'message': {'content': text}})

    def say(text: str) -> str:
        return row({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': text}]}})
    t = tmp / 'c3.jsonl'
    long = ''.join(say(f'step {i} ' + 'x' * 500) for i in range(1000))
    t.write_text(you('first') + you('do it') + row({'type': 'user', 'message': {'content': [
        {'type': 'tool_result', 'content': 'not the person'}]}}) + long, encoding='utf-8')
    at = 1795428000.5
    with mock.patch.object(U, 'transcript_of', return_value=str(t)), mock.patch.object(U, 'session_sid', return_value=''):
        f = U.feed('c3', limit=0)
        eq(f['entries'][0], {'kind': 'you', 'text': 'do it', 'at': at}, 'the latest prompt, before the cut tail')
        eq([e['kind'] for e in f['entries']].count('you'), 1, 'only the latest one')
        check(f['more'], "a cut tail says 'more' with no limit reached", f['more'])
        eq(U.feed('c3')['entries'][0]['text'], 'do it', 'with the page\'s limit too')
        with t.open('a', encoding='utf-8') as fh:
            fh.write(you('and now?') + long)
        eq(U.feed('c3')['entries'][0]['text'], 'and now?', 'a later prompt that the tail leaves behind')
        t.write_text(you('fresh') + long, encoding='utf-8')
        eq(U.feed('c3')['entries'][0]['text'], 'fresh', 'a transcript written anew is read anew')
        q = {'type': 'attachment', 'timestamp': '2026-11-23T10:00:00.500Z', 'attachment': {
            'type': 'queued_command', 'commandMode': 'prompt', 'prompt': 'one more thing'}}
        n = {**q, 'attachment': {**q['attachment'], 'commandMode': 'task-notification'}}
        t.write_text(you('go') + say('ok') + row(q) + row(n), encoding='utf-8')
        f = U.feed('c3')
        eq([(e['kind'], e['text']) for e in f['entries']], [('you', 'go'), ('say', 'ok'), ('you', 'one more thing')],
           'a message queued during a turn is in the feed; a queued notification is not')
        check(not f['more'], 'a whole feed has no more')


def test_chat_at_b154(tmp: Path) -> None:
    """B154: new_control and chat_to say when they ran and what was asked, so a page can tell its message's own entry."""
    from unittest import mock
    fake_run(tmp)
    before, ran, real = time.time(), [], U.RUN[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'control 3 is starting in a hidden terminal\n'))[1]
    try:
        n = U.act('new_control', ask='theme ideas', wait=False)
        eq((n['name'], n['ask']), ('c3', 'theme ideas'), 'a new chat says what it was asked')
        check(before <= n['at'] <= time.time(), 'and when', n)
        U.act('quick_ask', key='needs'), U.act('concept_chat', cid='K5')
        r = U.act('chat_to', text='hi')
        eq((r['name'], before <= r['at']), ('c3', True), 'no chat named: the new chat that took the message')
        eq([a[-1] for a in ran], ['--no-feed'] * 4, 'every ask from a page or the TUI skips the feed lookup')
    finally:
        U.RUN[0] = real


def test_chat_and_terminal(tmp: Path) -> None:
    """F74: chat to any control session (none named: SEND; cN typed in through its shim's FIFO), interrupt
    (Escape typed in), a new control session's link, the quick asks to c1, and the terminal view: ttyd,
    install ttyd, or (Windows) the feed only."""
    from unittest import mock
    from agent_runner import plat, slots
    fake_run(tmp)
    sent, typed, raw, ran = [], [], [], []
    real = U.SEND[0], U.RUN[0]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'c3 is open: https://claude.ai/code/session_c3x\n'))[1]
    inboxes = {'c6': Path('/x/control6.in'), 's2': Path('/x/slot2.in')}
    try:
        with mock.patch.object(U, 'hidden_inbox', side_effect=lambda n: inboxes.get(n)), \
                mock.patch.object(plat, 'WINDOWS', False), \
                mock.patch.object(slots, 'send_fifo', side_effect=lambda p, t: (typed.append((p.name, t)), True)[1]), \
                mock.patch.object(slots, 'send_fifo_raw', side_effect=lambda p, b: (raw.append((p.name, b)), True)[1]):
            eq(U.act('chat_to', text='hi c1')['out'], 'sent to c1', 'no chat named: the way chat does')
            eq(U.act('chat_to', text='how is R43?', to='c6')['out'], 'sent to c6', 'c6 too')
            r = U.act('chat_to', text='hello', to='c9')
            eq(U.act('interrupt', session='c6')['out'], 'interrupted c6', 'interrupt c6')
            eq(U.keys('s2', text='yes', key='Enter')['ok'], True, 'keys typed into s2')
            eq(U.keys('s2', key='F13')['ok'], False, 'an unknown key is refused')
            eq(U.act('keys', session='s2', text='x')['ok'], False, "C25: 'keys' is no action: no page types into a session")
        check(not hasattr(U, 'capture') and not hasattr(U, 'CAPTURE_EVERY'),
              'C25: the built-in view\'s capture went with it')
        eq(sent, ['hi c1'], 'through SEND')
        eq(typed, [('control6.in', 'how is R43?')], 'c6 typed in through its FIFO')
        check(not r['ok'] and 'is not up' in r['out'], 'a session that is not up says so', r)
        eq(raw, [('control6.in', b'\x1b'), ('slot2.in', b'yes\r')], 'Escape into c6; text then Enter into s2')

        n = U.act('new_control', ask='')
        eq((n['ok'], n['link'], ran[-1]), (True, 'https://claude.ai/code/session_c3x', ['control', '--new']),
           'a new control session (control --new) and its claude.ai/code link')
        U.act('new_control', ask='theme ideas')
        eq(ran[-1], ['control', '--new', '--ask', 'theme ideas', '--no-feed'], 'with a first message')

        sent.clear()
        ran.clear()
        for k in ('since', 'yesterday', 'needs', 'usage'):
            U.act('quick_ask', key=k)
        eq((sent, [r[-2] for r in ran]), ([], ['what happened since my last look?', 'what happened since yesterday?',
                                             'what needs me?', 'where are the tokens going?']),
           'B139: each quick ask starts a new control session with it (control --new --ask), not c1')
        eq(U.act('quick_ask', key='nope')['ok'], False, 'an unknown quick ask is refused')
        eq([a['key'] for a in U.snapshot(up=False, now=NOW, links={})['quick_asks']],
           ['since', 'yesterday', 'needs', 'usage'], 'the snapshot lists them')
    finally:
        U.SEND[0], U.RUN[0] = real

    which = lambda have: (lambda name: f'/usr/bin/{name}' if name in have else None)  # noqa: E731
    with mock.patch.object(plat, 'WINDOWS', False):
        with mock.patch('shutil.which', side_effect=which({'ttyd'})):
            eq(U.terminal_mode(), 'ttyd', 'ttyd: ttyd')
        with mock.patch('shutil.which', side_effect=which(set())):
            eq(U.terminal_mode(), 'install', 'C25: no ttyd: install ttyd (the built-in view is gone)')
    with mock.patch.object(plat, 'WINDOWS', True), mock.patch('shutil.which', side_effect=which({'ttyd'})):
        eq(U.terminal_mode(), 'ttyd', 'F114: Windows too: the real terminal, no feed mode')
    with mock.patch.object(plat, 'WINDOWS', True), mock.patch('shutil.which', side_effect=which(set())):
        eq(U.terminal_mode(), 'install', 'and without ttyd, how to install it')


def test_concept_copy(tmp: Path) -> None:
    """F74: `done --artifact` keeps a copy of a K task's page (--page FILE, else the .html the worktree changed)
    at <notes>/concepts/<ID>.html, and the snapshot's concept row gives its path."""
    from types import SimpleNamespace
    from agent_runner import done as D
    repo = fake_run(tmp)
    page = tmp / 'page.html'
    page.write_text('<title>K5 options</title><h1>Option A</h1>', encoding='utf-8')
    c = SimpleNamespace(root=repo, notes=S.C.notes)
    kept = D.keep_page(c, 'K5', str(page))
    eq(kept, S.C.notes('concepts', 'K5.html'), 'kept at <notes>/concepts/K5.html')
    eq(kept.read_text(encoding='utf-8'), page.read_text(encoding='utf-8'), 'a copy of the page')
    snap = U.snapshot(up=False, now=NOW, links={})
    eq(snap['concepts'][0]['copy'], str(kept), "the concept row gives the copy's path")
    eq(U.concept_copy('../K5'), '', 'an id that is not one finds nothing')
    (repo / 'journal').mkdir()
    (repo / 'journal' / 'k7.html').write_text('<h1>K7</h1>', encoding='utf-8')
    eq(D.keep_page(c, 'K7').read_text(encoding='utf-8'), '<h1>K7</h1>', 'no --page: the .html the worktree changed')
    eq(D.keep_page(c, 'K8', str(tmp / 'missing.html')), None, 'a --page that is not a file: no copy')


def test_concept_chat(tmp: Path) -> None:
    """F86: `concept_chat` starts a new control session (control --new --ask) whose first message names the
    concept, its page link and local copy, and says to follow guide concepts; the run page's Concepts card has
    its button."""
    from types import SimpleNamespace
    from agent_runner import done as D
    repo = fake_run(tmp)
    page = tmp / 'page.html'
    page.write_text('<h1>Option A</h1>', encoding='utf-8')
    kept = D.keep_page(SimpleNamespace(root=repo, notes=S.C.notes), 'K5', str(page))
    ran = []
    real = U.RUN[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'c3 is open: https://claude.ai/code/session_c3x\n'))[1]
    try:
        for cid in ('K5', 'F4'):
            r = U.act('concept_chat', cid=cid)
            eq((r['ok'], r['link']), (True, 'https://claude.ai/code/session_c3x'), f'{cid}: the new session link')
            eq(ran[-1][:3], ['control', '--new', '--ask'], f'{cid}: control --new --ask')
            ask = ran[-1][3]
            for want in ("concept K5 'lazy layout'", 'https://claude.ai/artifact/k5', str(kept), 'guide concepts',
                         'Artifact tool', 'open it inline', 'plain go'):
                check(want in ask, f'{cid}: the first message says {want!r}', ask)
        U.act('concept_chat', cid='K9', title='Dark theme', url='https://claude.ai/artifact/k9')
        check("concept K9 'Dark theme'" in ran[-1][3] and 'https://claude.ai/artifact/k9' in ran[-1][3]
              and 'no local copy' in ran[-1][3], 'a concept no longer listed: the given title and link', ran[-1])
        n = len(ran)
        eq(U.act('concept_chat', cid='../K5')['ok'], False, 'an id that is not one is refused')
        eq(len(ran), n, 'and runs nothing')
    finally:
        U.RUN[0] = real


def test_hidden_send(tmp: Path) -> None:
    """F89: a hidden session is reached through its shim's FIFO, found from its .live marker:
    send writes a bracketed paste then CR, interrupt writes a raw ESC, and a FIFO nobody reads gives ok False."""
    import os
    from agent_runner import plat
    if plat.WINDOWS:
        return
    fake_run(tmp)
    readers, typed = [], []

    def hidden(stem: str, reader: bool = True) -> None:
        S.C.notes(f'{stem}.live').write_text(str(os.getpid()), encoding='utf-8')
        os.mkfifo(S.C.notes(f'{stem}.in'))
        if reader:
            readers.append(os.open(S.C.notes(f'{stem}.in'), os.O_RDONLY | os.O_NONBLOCK))

    def drain(fd: int) -> bytes:
        try:
            return os.read(fd, 65536)
        except BlockingIOError:
            return b''

    hidden('slot2')
    hidden('control3')
    hidden('slot4', reader=False)
    try:
        with mock.patch.object(plat, 'WINDOWS', False):
            r = U.send('s2', 'hello s2')
            eq((r['ok'], r['out']), (True, 'sent to s2'), 'send to a hidden slot')
            eq(drain(readers[0]), b'\x1b[200~hello s2\x1b[201~\r', 'a bracketed paste, then CR')
            r = U.interrupt('c3')
            eq((r['ok'], r['out']), (True, 'interrupted c3'), 'interrupt a hidden control session')
            eq(drain(readers[1]), b'\x1b', 'a raw ESC, no paste')
            eq(U.keys('s2', text='y', key='Enter')['ok'], True, 'keys: text and a key, raw')
            eq(drain(readers[0]), b'y\r', 'y then CR')
            r = U.send('s4', 'anyone?')
            check(not r['ok'], 'a FIFO with no reader: ok False', r)
            check(not U.interrupt('s4')['ok'], 'nor an interrupt')
            r = U.send('s9', 'hi')
            check(not r['ok'] and 'is not up' in r['out'], 'no marker: not up', r)
        S.C.notes('slot5.live').write_text(str(os.getpid()), encoding='utf-8')  # no slot5.in: a hidden console
        with mock.patch.object(plat, 'WINDOWS', True):
            for r in (U.send('s5', 'hi'), U.interrupt('s5')):
                check(not r['ok'] and 'cannot be typed into' in r['out'], 'Windows hidden console: no typing', r)
            with mock.patch('agent_runner.slots.pipe_send', lambda i, c, p=0: typed.append((i.name, c)) or True):
                check(U.send('s2', 'hi')['ok'] and U.interrupt('c3')['ok'], 'F145: Windows ConPTY takes typed text')
            eq(typed, [('slot2.in', [b'\x1b[200~hi\x1b[201~', b'\r']), ('control3.in', [b'\x1b'])],
               'a bracketed paste then CR, and a raw ESC, through the pipe')
    finally:
        for fd in readers:
            os.close(fd)


def test_delete_chats(tmp: Path) -> None:
    """F118: delete_chats ends each named control session (its process, controlN.pid and .title go, so it leaves
    the chat list and no run start reopens it), an older runner's c1 too (F176)."""
    import subprocess as sp
    fake_run(tmp)
    procs = {n: sp.Popen(['sleep', '60']) for n in (1, 3, 4)}
    try:
        for n, p in procs.items():
            S.C.notes(f'control{n}.pid').write_text(f'{p.pid} sid-{n}', encoding='utf-8')
            S.C.notes(f'control{n}.title').write_text(f'proj · {n} · chat {n}\n', encoding='utf-8')
        with mock.patch('agent_runner.control.control_live', lambda n: procs[n].pid if n in procs and
                        procs[n].poll() is None and S.C.notes(f'control{n}.pid').exists() else 0):
            eq(U.act('delete_chats', names=[])['ok'], False, 'no names: refused')
            eq(U.act('delete_chats', names=['s2'])['ok'], False, 'a slot is not a chat')
            r = U.act('delete_chats', names=['c3', 'c9'])
            eq((r['ok'], r['deleted']), (True, ['c3']), 'c3 deleted, c9 was not there')
            procs[3].wait(timeout=10)
            check(not S.C.notes('control3.pid').exists() and not S.C.notes('control3.title').exists(),
                  'its pid file and title are gone')
            eq(sorted(U.control_titles()), [1, 4], 'the chat list keeps c1 and c4')
            check(procs[1].poll() is None and procs[4].poll() is None, 'the others still run')
            eq(U.act('delete_chats', names=['c1'])['deleted'], ['c1'], 'c1 is a chat like any other')
    finally:
        for p in procs.values():
            p.kill()
            p.wait()


def test_chat_list_f133(tmp: Path) -> None:
    """F133: the run app's Chats order (web.chat_list): pins first in their saved order, then chats the saved order
    does not know (new ones, just under the pins), then the saved order; a deleted chat drops out; nothing saved
    keeps the snapshot's order."""
    from agent_runner import web as W
    names = ['c1', 'c3', 'c4', 'c6']
    eq(W.chat_list(names, {}), names, 'nothing saved: the snapshot order')
    eq(W.chat_list(names, None), names, 'no file: the snapshot order')
    eq(W.chat_list(names, {'order': ['c6', 'c3', 'c1', 'c4'], 'pins': []}), ['c6', 'c3', 'c1', 'c4'], 'the saved order')
    eq(W.chat_list(names, {'order': ['c6', 'c3', 'c1', 'c4'], 'pins': ['c1', 'c4']}), ['c1', 'c4', 'c6', 'c3'],
       'pins first, in the saved order')
    eq(W.chat_list(names, {'order': ['c3', 'c1'], 'pins': ['c1']}), ['c1', 'c4', 'c6', 'c3'],
       'new chats just under the pins')
    eq(W.chat_list(['c1', 'c3'], {'order': ['c9', 'c3', 'c4', 'c1'], 'pins': ['c9', 'c1']}), ['c1', 'c3'],
       'deleted chats (pinned or not) drop out')
    eq(W.chat_list(names, {'order': ['c4'], 'pins': ['c6']}), ['c6', 'c1', 'c3', 'c4'],
       'a pin missing from the order is still first')
    eq(W.chat_list(names, {'order': 'junk', 'pins': [3, 'c3']}), ['c3', 'c1', 'c4', 'c6'], 'junk in the file is skipped')


def ran_by(out: list, text: str = 'ok'):
    return mock.patch.object(U, 'RUN', [lambda argv: (out.append(argv), (0, text))[1]])


def test_status_f124(tmp: Path) -> None:
    """F124: the snapshot holds what the Status view shows: the state pill's words, usage, what landed lately, and
    what the Fix up controls would work on."""
    fake_run(tmp)
    for st, want in (({}, 'Running'), ({'paused': True}, 'Paused'), ({'forced': True}, 'Caps forced'),
                     ({'stopping': True, 'paused': True}, 'Stopping')):
        eq(U.run_state(True, st), want, f'{st}: {want}')
    eq(U.run_state(False, {'paused': True}), 'Not up', 'no run: Not up')
    S.C.notes('events.jsonl').write_text(json.dumps({'time': '2026-11-21T10:00:00', 'kind': 'landed', 'id': 'F1'}) + '\n',
                                         encoding='utf-8')
    snap = U.snapshot(up=True, now=NOW, links={})
    json.dumps(snap)
    eq((snap['run']['state'], snap['run']['forced']), ('Running', False), 'the run state in the snapshot')
    eq(snap['usage'], [{'name': 'session', 'pct': 42}, {'name': 'week', 'pct': 85}], 'usage, each with its percent')
    check(any('F1' in x['text'] and x['at'].startswith('2026-11-21T10:00') for x in snap['lately']), 'what landed lately',
          snap['lately'])
    eq(snap['fixups'], {'resume': [], 'unclaim': [], 'wip': []}, 'nothing to fix')
    git(S.ROOT, 'branch', 'wip/main-checkout-2026-11-20-101010')
    git(S.ROOT, 'branch', 'wip/T7')
    U.FIXUPS[0] = float('-inf')
    from agent_runner import slots, watch
    with mock.patch.object(watch, 'last_session', lambda tid: (1, 'sid')), \
            mock.patch.object(slots, 'transcript', lambda sid: '/x.jsonl'):
        fix = U.snapshot(up=True, now=NOW, links={})['fixups']
    eq([x['id'] for x in fix['wip']], ['main-checkout-2026-11-20-101010'], 'the edits a merge moved aside')
    eq([x['id'] for x in fix['resume']], ['T7'], 'a cut-off task with its work kept, running nowhere')
    ran = []
    two = {'resume': [], 'unclaim': [{'id': 'F1', 'label': ''}, {'id': 'B2', 'label': ''}], 'wip': []}
    with ran_by(ran), mock.patch.object(U, 'fixups', lambda st, ls: two):
        eq(U.run_control('unclaim')['ok'], True, 'release stale claims')
    eq(ran, [['plan', 'unclaim', 'F1'], ['plan', 'unclaim', 'B2']], 'every stale claim is released')
    by = {c['key']: c for c in U.controls()}
    for key in ('stop_now', 'suspend', 'shutdown', 'upgrade'):
        check(by[key]['confirm'] and by[key]['group'], f'{key} asks first, from the sheet', by[key])
    eq([by[k]['group'] for k in ('slot_add', 'pause', 'stop', 'force', 'upgrade', 'resume', 'wip_drop')],
       ['', '', '', 'Run', 'Run', 'Fix up', 'Fix up'], "the sheet's groups; the everyday ones are on the card")


def chat(n: int, sid: str, rows: list) -> str:
    S.C.notes(f'control{n}.pid').write_text(f'1 {sid}', encoding='utf-8')
    f = S.C.notes(f'{sid}.jsonl')
    f.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
    return str(f)


def said(who: str, text: str, at: str) -> dict:
    return {'type': who, 'timestamp': at, 'message': {'content': [{'type': 'text', 'text': text}] if who == 'assistant'
                                                      else text}}


def test_chat_rows_f128(tmp: Path) -> None:
    """F128, F129: each chat's row says who spoke last and when, whether an open question waits for the person, and the
    name the person gave it."""
    fake_run(tmp)
    from agent_runner import control as K, slots
    at = '2026-11-21T10:00:00.000Z'
    paths = {'s2': chat(2, 's2', [said('user', 'hi', at), said('assistant', 'Which one do you want?', at)]),
             's3': chat(3, 's3', [said('user', 'hi', at), said('assistant', 'Done.', '2026-11-21T10:05:00.000Z')]),
             's4': chat(4, 's4', [said('assistant', 'Hm?', at), said('user', 'go', at)]),
             's5': chat(5, 's5', [said('assistant', 'Done.', at), {'type': 'custom-title', 'customTitle': 'Mine'}])}
    ents = lambda sid, skip_bad=False: [json.loads(l) for l in open(paths[sid], encoding='utf-8')]  # noqa: E731
    with mock.patch.object(slots, 'transcript', lambda sid: paths.get(sid)), mock.patch.object(slots, 'entries', ents), \
            mock.patch.object(K, 'control_live', lambda n: n in (2, 3, 4, 5)):
        rows = {r['name']: r for r in U.control_rows({2: 'two', 3: 'three', 4: 'four', 5: 'five'})}
        eq([(rows[n]['last'], rows[n]['needs_reply']) for n in ('c2', 'c3', 'c4')],
           [('claude', True), ('claude', False), ('person', False)], 'who spoke last; an open question needs a reply')
        eq(rows['c3']['at'] - rows['c2']['at'], 300, 'the last activity, in seconds')
        eq((rows['c5']['title'], rows['c5']['renamed'], rows['c3']['title']), ('Mine', True, 'three'),
           "a chat the person renamed shows their name; another keeps the runner's")
        S.C.notes('control3.name').write_text(json.dumps({'name': 'Login', 'was': ''}), encoding='utf-8')
        r3 = {r['name']: r for r in U.control_rows({3: 'three'})}['c3']
        eq((r3['title'], r3['renamed']), ('Login', True), 'a rename shows before its turn has typed it')
    eq(U.chat_quiet(), 6 * 3600, 'chat_quiet: 6 hours')
    with mock.patch.dict(S.C.raw['ui'], {'chat_quiet': False}):
        eq(U.chat_quiet(), 0, 'false turns it off')
    ran = []
    with ran_by(ran):
        eq(U.act('rename_chat', chat='c3', title='  Login  woes ')['ok'], True, 'rename_chat')
        eq(U.act('rename_chat', chat='s1', title='x')['ok'], False, 'a slot is not a chat')
        eq(U.act('rename_chat', chat='c3', title='  ')['ok'], False, 'a name, please')
    eq(ran, [['control', '--rename', '3', 'Login woes']], 'control --rename N NAME')


def test_need_chat_f143(tmp: Path) -> None:
    """F143: a Needs you item's Chat starts a control session whose first message holds the ask and the options; a bad
    id, or one that no longer needs the person, is refused."""
    fake_run(tmp)
    ran = []
    ask = {'title': 'Layout', 'summary': 'Pick a layout', 'groups': [{'heading': 'h', 'questions': [
        {'id': 'lay', 'q': 'Which layout?', 'answers': ['Tabs', 'Drawer'], 'recommended': 1}]}]}
    with ran_by(ran, 'control 7 is starting'):
        r = U.act('need_chat', tid='D3', wait=False)
        eq((r['ok'], r['name']), (True, 'c7'), 'a new chat')
        eq(ran[-1][:4], ['control', '--new', '--no-wait', '--ask'], 'control --new --ask, not waiting')
        text = ran[-1][4]
        check(text == r['ask'] and 'D3' in text and "'Write the guide'" in text and 'hich layout' in text
              and 'wait for my reply' in text, 'its first message: the id, the title and what was asked', text)
        S.C.notes('sheets', 'D3.json').write_text(json.dumps(ask), encoding='utf-8')
        U.act('need_chat', tid='D3')
        check('Possible answers:' in ran[-1][3] and 'Which layout?: Tabs / Drawer (recommended)' in ran[-1][3],
              "a pick sheet's questions and answers are in it", ran[-1])
        eq(U.need_options({'label': 'CONFIRM'}), ['Yes', 'No'], 'a CONFIRM: Yes, No')
        eq(U.need_options({'label': 'DECIDE', 'options': ['a', 'b']}), ['A', 'B'], "an item's own options")
        path = chat(9, 'sx', [said('assistant', 'I looked at both. Tabs cost a day, the drawer two.', '2026-11-21T10:00:00Z')])
        from agent_runner import slots, watch
        with mock.patch.object(watch, 'last_session', lambda tid: (1, 'sx')), mock.patch.object(slots, 'transcript', lambda sid: path):
            U.act('need_chat', tid='D3')
        check('Tabs cost a day, the drawer two.' in ran[-1][3], "the agent's full last message is in it", ran[-1])
        n = len(ran)
        for bad in ('', 'D3; rm', '--force', 'F1'):
            eq(U.act('need_chat', tid=bad)['ok'], False, f'refused: {bad!r}')
        eq(len(ran), n, 'a refused one starts nothing')


def test_feed_ids_b134(tmp: Path) -> None:
    """B134: a feed entry carries its transcript entry's id, the same in every later feed."""
    rows = [{'type': 'user', 'uuid': 'u1', 'message': {'content': 'hi'}},
            {'type': 'assistant', 'uuid': 'u2', 'message': {'content': [
                {'type': 'text', 'text': 'a'}, {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls'}}]}},
            {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'no id'}]}}]
    es = U.feed_entries(rows)
    eq([e.get('id', '') for e in es], ['u1:0', 'u2:0', 'u2:1', ''], 'the uuid and the block')
    eq([e.get('id', '') for e in U.feed_entries(rows[1:])][0], 'u2:0', 'the same from a later, shorter tail')


def in_tmp(f):
    def go():
        print(f.__name__)
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


def test_need_answers_c33(tmp: Path) -> None:
    """C33: every needs row carries its answers; one rule for both pages and the chat text."""
    copy = tmp / 'K1.html'
    copy.write_text('<h1>Menu</h1><h2>Tabs</h2><p>a</p><h2>Drawer · recommended</h2><p>b</p>', encoding='utf-8')
    names = lambda row: [a['label'] for a in U.need_answers(row)]  # noqa: E731
    eq(names({'label': 'CONFIRM'}), ['Yes', 'No'], 'CONFIRM: Yes, No')
    eq(names({'label': 'DECIDE', 'ask': 'Ship it? yes or no'}), ['Yes', 'No'], 'a yes/no ask: Yes, No')
    eq(names({'label': 'DECIDE', 'ask': 'Which port?'}), [], 'DECIDE with no pick: reply only')
    eq(names({'label': 'BLOCKED'}), ['Done'], 'BLOCKED: Done, on both pages')
    eq(names({'label': 'CONCEPT', 'copy': str(copy)}), ['Tabs', 'Drawer · recommended'], "CONCEPT: the copy's options")
    eq(names({'label': 'CONCEPT'}), ['A', 'B', 'C'], 'CONCEPT without a copy: A, B, C')
    eq(names({'label': 'PITCH', 'options': ['Approve', 'Not this: drop']}), ['Approve', 'Not this: drop'], 'PITCH')
    rows, _ = U.needs_rows([('CONFIRM', 'F1', '', 'ok?', '', 'T', False), ('BLOCKED', 'F2', '', 'log in', '', 'T', False)],
                           dt.datetime.now())
    eq([[a['value'] for a in r['answers']] for r in rows], [['Yes', 'No'], ['Done']], 'the snapshot rows carry them')
    eq(U.need_options(rows[1]), ['Done'], 'the chat text uses the same')
    run, fix = {'forced': False}, {'unclaim': [{'id': 'F1'}]}
    on = U.controls_shown(True, run, fix)
    check('force' in on['shown'] and 'caps_on' not in on['shown'] and 'unclaim' in on['shown'], 'shown now', on)
    eq(U.controls_shown(False, run, fix)['card'], ['start'], 'no run: Start the run')
    check('pause' not in U.controls_shown(False, run, fix)['shown'], 'no run: no Pause')
    check(U.task_controls_on({'name': 's1', 'task': 'F1'}) and not U.task_controls_on({'name': 's1', 'task': 'F1',
          'state': 'merging'}) and not U.task_controls_on({'name': 'c1', 'task': 'F1'}), 'task controls')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_snapshot), in_tmp(test_idle_slots), in_tmp(test_version_f90),
                         in_tmp(test_actions), in_tmp(test_run_controls), in_tmp(test_row_actions),
                         in_tmp(test_real_command),
                         in_tmp(test_to_new), in_tmp(test_control_titles),
                         in_tmp(test_queue_rows), in_tmp(test_feed), in_tmp(test_feed_prompt_b154), in_tmp(test_chat_at_b154),
                         in_tmp(test_chat_and_terminal),
                         in_tmp(test_concept_copy), in_tmp(test_concept_chat), in_tmp(test_hidden_send),
                         in_tmp(test_delete_chats), in_tmp(test_chat_list_f133),
                         in_tmp(test_status_f124), in_tmp(test_chat_rows_f128), in_tmp(test_need_chat_f143),
                         in_tmp(test_feed_ids_b134), in_tmp(test_need_answers_c33)]))
