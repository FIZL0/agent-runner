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
import os
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
    check(any(l.startswith('release: V6 Release the next version · waits for 2: F1 Board page for the run, B2 ') for l in snap['status']), 'status has the release line',
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
    rel, = snap['releases']
    eq(snap['release'], 'release: ' + rel['text'] + rel['note'], 'release line: the one row (F185)')
    eq((rel['id'], rel['state'], [w['id'] for w in rel['waits']]), ('V6', 'waits', ['F1', 'B2']), 'one open release')
    eq(q['V6']['release'], rel, 'its queue row carries it')
    with mock.patch.object(U, '_state', lambda up: {'running': {'1': 'V6'}}):
        eq(U.snapshot(up=True, now=NOW, links={}, windows={})['releases'][0]['words'], 'releasing now', 'one running')

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
        eq(sent, ['how is it going?'], 'chat goes through SEND')
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
                    'shelved_back', 'shelved_drop', 'release_wait', 'release_now', 'need_later', 'need_chat', 'need_drop', 'concept_chat',
                    'need_yes', 'need_no', *(f'need_answer{j}' for j in range(1, U.ANSWER_MAX + 1)),  # F180
                    'concept_drop', 'session_close'} - ({'restart'} if windows else set())
            on = ' (Windows)' if windows else ''
            with mock.patch('agent_runner.plat.WINDOWS', windows):
                cs = U.controls()
            eq(sorted(c['key'] for c in cs), sorted(want), f'the list holds every control the task names{on}')
            eq(len({(c['where'], c['tui']) for c in cs if c['tui']}), len([c for c in cs if c['tui']]), f'each has a key of its own in its panel{on}')
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
        check(c.get('argv') or c.get('ask') or c.get('fn') or c.get('answer') or c['key'] == 'start', f'{c["key"]} has an action', c)
        # where its keys work: on the panel and in the main pane, or only one of them (F180: an answer's, in its tab)
        keys = [(p, c['tui']) for p in (('main',) if c.get('tab') else ('panel', 'main') if c.get('tui_main', True)
                                        else ('panel',)) if c['tui']]
        for at in keys + ([('panel', c['tui_also'])] if c.get('tui_also') else []):
            check((c['where'], *at) not in seen, f'{c["key"]}: {at} is no other key of {c["where"]}')
            seen.add((c['where'], *at))
    snap = U.snapshot(up=True, now=NOW, links={})
    acts = {q['id']: q['acts'] for q in snap['queue']}
    eq(acts['F1'], ['queue_priority', 'queue_take', 'queue_drop'], 'a queued task: priority, do it here, drop')
    eq(acts['R8'], ['queue_unpark', 'queue_take', 'queue_drop'], 'a parked task: unpark, not priority')
    eq(snap['release_acts'], ['release_wait', 'release_now'], 'the release tab\'s actions')
    eq({n['id']: n['acts'] for n in snap['needs']}, {'D3': ['need_later', 'need_chat', 'need_drop'],
                                                     'F4': ['need_answer1', 'need_answer2', 'need_answer3', 'need_later', 'need_chat',
                                                            'need_drop']}, 'C35: a Needs you item; F180: its fixed answers first')
    eq([(n['id'], n.get('labels')) for n in snap['needs']],
       [('D3', None), ('F4', {'need_answer1': 'A', 'need_answer2': 'B', 'need_answer3': 'C'})], "F180: the row's own labels")
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


def test_answers_f180(tmp: Path) -> None:
    """F180: a Needs you row's fixed answers are row actions: Yes and No, Done or its options, labelled by the row;
    one runs the plan command only when the row still has the answer pressed, with the words beside it."""
    fake_run(tmp)
    for row, want in (({'label': 'CONFIRM'}, {'need_yes': 'Yes', 'need_no': 'No'}),
                      ({'label': 'DECIDE', 'ask': 'Which port?'}, {}),
                      ({'label': 'BLOCKED'}, {'need_answer1': 'Done'}),
                      ({'label': 'TOOL', 'ask': 'Connect it, yes or no'}, {}),
                      ({'label': 'PITCH', 'options': ['Approve', 'Not this: drop']},
                       {'need_answer1': 'Approve', 'need_answer2': 'Not this: drop'})):
        eq(U.row_labels('need', row), want, f'{row["label"]}: its answers')
        eq([k for k in U.row_acts('need', row) if U.run_control_of(k).get('answer')], list(want), 'and its acts')
    ran = []
    rows = {'B2': {'id': 'B2', 'label': 'CONFIRM'}, 'F1': {'id': 'F1', 'label': 'BLOCKED'}, 'D3': {'id': 'D3', 'label': 'DECIDE'}}
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: rows.get(tid)), \
            mock.patch.object(U, 'need_label', lambda tid: rows.get(tid, {}).get('label', '')):
        r = U.act('run_control', key='need_yes', tid='B2', text='Yes', note='on  wifi')
        eq((r['ok'], r['said'], r['gone']), (True, 'B2 ticked', 'B2'), 'Yes ticks it')
        U.act('run_control', key='need_no', tid='B2', text='No')
        U.act('run_control', key='need_answer1', tid='F1', text='Done')
        eq(ran, [['plan', 'confirm', 'B2', 'Yes: on wifi'], ['plan', 'change', 'B2', 'No: the check failed'],
                 ['plan', 'confirm', 'F1', 'Done']], 'the plan commands')
        ran.clear()
        for key, tid, text in (('need_answer1', 'F1', 'Option A'), ('need_answer1', 'F1', ''), ('need_yes', 'F1', 'Yes'),
                               ('need_answer1', 'D3', 'A'), ('need_yes', 'ZZ9', 'Yes')):
            eq(U.run_control(key, tid=tid, text=text)['code'], 1, f'{key} {text!r} on {tid} is refused')
        eq(U.run_control('need_yes', tid='ZZ9', text='Yes')['out'], 'ZZ9 no longer needs you (answered already?)', 'and says why')
        eq(ran, [], 'and runs nothing')


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


def test_shelved_f184(tmp: Path) -> None:
    """F184: a shelved task, a concept build too, is in the snapshot's own `shelved` list and in none of queue, needs
    and concepts; Bring back is the real plan unshelve, Drop asks first; never Unpark."""
    repo = fake_run(tmp)
    todo = repo / 'plan' / 'TODO.md'
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq(snap['shelved'], [], 'nothing shelved: an empty list')
    had = [q['id'] for q in snap['queue']]
    todo.write_text(TODO.split('### Parked')[0], encoding='utf-8')  # no parked task
    for tid in ('D3', 'F4'):
        check(U.run_control('need_later', tid=tid)['ok'], f'{tid} is shelved')
    place = todo.read_text(encoding='utf-8')
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq([(r['id'], r['state'], r['acts']) for r in snap['shelved']],
       [(t, 'shelved', ['shelved_back', 'shelved_drop']) for t in ('D3', 'F4')], 'both, in plan order, with their actions')
    d3, f4 = snap['shelved']
    eq((d3['title'], d3['ask']), ('Write the guide', U.P.plain_ask('DECIDE', 'which layout', 'Write the guide')),
       'its short title and what it waits for in plain words')
    check('lazy layout' in f4['title'] and f4['ask'].startswith('Pick an option'), 'a concept build says so too', f4)
    eq([q['id'] for q in snap['queue']], [t for t in had if t not in ('D3', 'F4', 'R8')], 'the queue has neither')
    eq((snap['needs'], snap['concepts']), ([], []), 'nor Needs you, nor Concepts')
    for key, tid in (('queue_unpark', 'D3'), ('shelved_back', 'F1'), ('shelved_drop', 'ZZ9')):
        eq(U.run_control(key, tid=tid, confirm=True)['code'], 1, f'{key} on {tid} is refused')
    r = U.run_control('shelved_drop', tid='D3')
    check(not r['ok'] and r['confirm'].startswith('Drop D3?'), 'drop asks first', r)
    eq(todo.read_text(encoding='utf-8'), place, 'and nothing has changed yet')
    r = U.run_control('shelved_back', tid='D3')
    eq((r['ok'], r['argv'], r['said']), (True, ['plan', 'unshelve', 'D3'], 'D3 is under Needs you again'), 'plan unshelve')
    snap = U.snapshot(up=False, now=time.time(), links={})
    eq(([r['id'] for r in snap['shelved']], [n['id'] for n in snap['needs']]), (['F4'], ['D3']), 'under Needs you again')
    r = U.run_control('shelved_drop', tid='F4', confirm=True)
    check(r['ok'] and '**F4**' not in todo.read_text(encoding='utf-8'), 'a confirmed drop takes it out of the plan', r)
    eq(U.snapshot(up=False, now=time.time(), links={})['shelved'], [], 'and off the list')


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


def test_chat_hold_b158(tmp: Path) -> None:
    """B158: a message to a chat that cannot take input yet is not typed: the run page is told to hold it
    (wait False), any other caller waits; a slot's and a new chat's never wait."""
    from unittest import mock
    from agent_runner import control as K, plat, session_now, slots
    fake_run(tmp)
    typed, ready, real = [], [False], U.RUN[0]
    U.RUN[0] = lambda argv: (0, 'control 3 is starting in a hidden terminal\n')
    try:
        with mock.patch.object(U, 'hidden_inbox', return_value=Path('/x/control3.in')), \
                mock.patch.object(plat, 'WINDOWS', False), \
                mock.patch.object(K, 'control_takes_input', side_effect=lambda n: ready[0]), \
                mock.patch.object(slots, 'send_fifo', side_effect=lambda p, x: (typed.append(x), True)[1]):
            for more in ({}, {'force': True}, {'unsent': True}):
                with mock.patch.object(session_now, 'force_send', side_effect=AssertionError('sent')):
                    r = U.act('chat_to', text='hi', to='c3', wait=False, **more)
                eq((r['ok'], r.get('hold'), typed), (False, True, []), f'held, not typed, while the chat starts {more}')
            with mock.patch.object(U, 'START_WAIT', 0.2):
                r = U.act('chat_to', text='hi', to='c3')
            eq((r['ok'], r.get('hold'), typed), (False, None, []), 'a caller that waits: not delivered, and not held')
            check('starting' in r['out'], 'and says why', r)
            eq(U.act('chat_to', text='new', wait=False).get('hold'), None, 'a new chat is never held')
            check(U.act('chat_to', text='slot', to='s3', wait=False)['ok'], 'nor is a slot')
            typed.clear()
            ready[0] = True
            r = U.act('chat_to', text='hi', to='c3', wait=False)
            eq((r['ok'], typed), (True, ['hi']), 'typed once the chat takes input')
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


def test_typed_decide_f181a(tmp: Path) -> None:
    """F181a: the words typed as a DECIDE's reply are its answer (plan confirm, no session); a CONFIRM's and a
    concept's still open a chat."""
    repo = fake_run(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(TODO.replace('- [ ] **B2** Fix the merge retry | files: b.py | after: F1',
                                 '- [~] **B2** Fix the merge retry | files: b.py BLOCKED: CONFIRM: look at it'),
                    encoding='utf-8')
    eq(U.answer_argv('D3', ' the lazy one '), (['plan', 'confirm', 'D3', 'the lazy one'],
                                               'D3 answered (the lazy one): a run starts it'), 'DECIDE: plan confirm')
    for words in ('', '  '):
        eq(U.answer_argv('D3', words), ([], ''), 'no words, no answer')
    eq([U.answer_argv(t, 'looks odd') for t in ('B2', 'F4')], [([], '')] * 2, "a CONFIRM's and a concept's: a chat")
    with mock.patch('agent_runner.brief.has_sheet', lambda tid: tid == 'D3'):
        eq([U.answer_argv('D3', w)[0] for w in ('go', 'D3 picks: a=b', 'neither')],
           [['sheet', 'D3', '--go'], ['sheet', 'D3', '--picks', 'D3 picks: a=b'], ['plan', 'confirm', 'D3', 'neither']],
           "a pick sheet's go and Send line are still the sheet's")
        eq([U.answer_argv('D3', w, True, ' after  Friday')[0] for w in ('go', 'D3 picks: a=b')],
           [['sheet', 'D3', '--go', '--note=after Friday'], ['sheet', 'D3', '--picks', 'D3 picks: a=b', '--note=after Friday']],
           'F162a: the words beside them go with them')
    sent = []
    with mock.patch.object(U, 'SEND', [lambda t: (sent.append(t), {'ok': True, 'code': 0, 'out': 'sent', 'argv': []})[1]]):
        r = U.act('answer', tid='D3', text='the lazy one')  # the real plan confirm
        U.act('answer', tid='B2', text='looks odd')
    eq((r['ok'], r.get('gone')), (True, 'D3'), 'answered at once, off Needs you')
    check('- [ ] **D3**' in todo.read_text(encoding='utf-8') and 'the lazy one' in todo.read_text(encoding='utf-8'),
          'D3 is open again with the words noted', todo.read_text(encoding='utf-8'))
    eq(sent, ['B2 (Fix the merge retry): looks odd'], "only the CONFIRM's words went to a chat")


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


def test_decide_options_f181c(tmp: Path) -> None:
    """F181c: a DECIDE's options are its answers, from the ask file or the bracket that ends its question, never from
    prose; the recommended one is first and marked, and the value sent is the bare name, by plan confirm."""
    repo = fake_run(tmp)
    todo, link = repo / 'plan' / 'TODO.md', 'https://claude.ai/artifact/QCMg'
    plain = todo.read_text(encoding='utf-8')

    def ask(words: str) -> dict:
        todo.write_text(plain.replace('DECIDE: which layout https://claude.ai/artifact/abc', f'DECIDE: {words}'), encoding='utf-8')
        return U.row_of('need', 'D3')
    said = lambda row: [(a['label'], a['value']) for a in row['answers']]  # noqa: E731
    look = [('Full (recommended)', 'Full'), ('Small', 'Small'), ('No change', 'No change')]
    f179 = 'Which look for the chat window: Full (recommended), Small, or no change?'
    eq((said(row := ask(f'{f179} {link}')), row.get('options')), ([], None), "F179's question, options in prose: never guessed")
    row = ask(f'Which look for the chat window? [Full (recommended) / Small / No change] {link}')
    eq((said(row), row['url'], row['what']), (look, link, 'Which look for the chat window?'), "F179's as a bracket: its buttons")
    check('[Full' not in json.dumps([row['ask'], row['ask_short'], row['what'], row['detail']['steps'], row['detail']['summary']]),
          'the bracket is not shown in the question', row)
    eq(U.row_labels('need', row), {'need_answer1': 'Full', 'need_answer2': 'Small', 'need_answer3': 'No change'}, 'what a press sends: the bare names')
    eq(said(ask('Which size? [small / iPhone (Recommended)]')), [('iPhone (recommended)', 'iPhone'), ('small', 'small')],
       'the recommended first, the rest as given, names as written')
    eq(said(ask('Ship it? [Yes / No (recommended)].')), [('No (recommended)', 'No'), ('Yes', 'Yes')], 'Yes and No with one recommended')
    for bad in ('[A]', '[A/B]', '[A / ]', '[ / B]', '[A / a]', '[A (recommended) / B (recommended)]', '[A / B', '[A / B] or so',
                '[A [x] / B]', '[A / -b]', '[A / ' + 'b' * 81 + ']', '[' + ' / '.join(f'o{j}' for j in range(13)) + ']', '[(recommended) / B]'):
        row = ask(f'Which one? {bad}')
        eq((said(row), row['what']), ([], f'Which one? {bad}'), f'{bad[:30]}: no buttons, and it stays in the question')
    f = S.C.notes('uploads', 'x').parent.parent / 'asks' / 'D3.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    opts = [{'name': 'Keep'}, {'name': 'Move [it] / all', 'rec': True}]
    f.write_text(json.dumps({'options': opts}), encoding='utf-8')
    eq(said(ask('Which one, then?')), [('Move [it] / all (recommended)', 'Move [it] / all'), ('Keep', 'Keep')], "the ask file's options")
    row = ask('Which one? [A / B]')
    eq((row['answers'][1]['value'], row['what']), ('Keep', 'Which one?'), 'it wins over a bracket, which is still not shown')
    for bad in ('x', [], [{'name': 'A'}], [{'name': 'A'}, 'B'], [{'name': 'A'}, {'name': 3}], [{'name': 'A'}, {'name': 'B', 'rec': 'yes'}]):
        f.write_text(json.dumps({'options': bad}), encoding='utf-8')
        eq([a['value'] for a in ask('Which one? [C / D]')['answers']], ['C', 'D'], f'{bad}: malformed, so the bracket')
    f.write_text(json.dumps({'options': opts, 'inputs': [{'key': 'a'}]}), encoding='utf-8')
    row = ask('Which one? [C / D]')
    eq((row['answers'], row['what']), ([], 'Which one? [C / D]'), 'an item with inputs: Done answers it, the bracket stays')
    f.unlink()
    row, _ = U.needs_rows([('BLOCKED', 'F2', '', 'Log in [A / B]', '', 'T', False)], dt.datetime.now())
    eq((said(row[0]), row[0]['what']), ([('Done', 'Done')], 'Log in [A / B]'), 'only a DECIDE has them')
    row = ask('Which look? [Full (recommended) / Small]')
    eq(U.need_options(row), ['Full (recommended)', 'Small'], "the chat's text lists them")
    with mock.patch.object(U, 'SEND', [lambda t: check(False, 'no session starts', t)]):
        eq(U.act('run_control', key='need_answer1', tid='D3', text='Full (recommended)')['ok'], False, 'the bare name only')
        r = U.act('run_control', key='need_answer1', tid='D3', text='Full', note='dark  too')  # the real plan confirm
    eq((r['ok'], r['gone'], r['argv'][-3:]), (True, 'D3', ['confirm', 'D3', 'Full: dark too']), 'a press: plan confirm, with the note')
    check('- [ ] **D3**' in (t := todo.read_text(encoding='utf-8')) and '): Full: dark too' in t, 'D3 is open with the answer', t)


ASKS_F162 = {  # real asks, as Needs you showed them
    'B160': ('CONFIRM', 'On an iPhone in Safari, after this lands and the run restarts: 1) reload, open a chat, tap the message box; '
             'the header stays and the box rides up with no grey band. 2) Close the keyboard; it glides back. 3) Same in Talk, '
             'Home, Settings and a sheet. Chat and Home were already seen working on the iPhone 15 Pro - reply yes/no'),
    'F154': ('CONFIRM', "On an iPhone, in a long chat, on Home and in the open drawer's list: scroll up/down and bend sideways (the "
             'drawer must not open or close); swipe the drawer open and closed at a slant (nothing may scroll up or down); taps '
             'still open rows, and holding a chat row still drags it - reply yes/no'),
    'F106h': ('BLOCKED', 'Log in to Copilot: `run login copilot` (device code; unattended it ended exit 124 waiting for approval at '
              'github.com/login/device). Then the Copilot check, the default and the docs follow; findings in '
              'docs/research/F106h-harness-end-to-end.md - reply done once it is'),
    'B163': ('STUCK', 'Stuck: waits for its Windows run - reply with what to do'),
    'B177': ('CONFIRM', 'On the iPhone, reload the run page on Talk, then on a chat, then on Plan: each opens again without Home '
             'flashing, and Talk neither listens nor speaks by itself - reply yes/no'),
    'R6': ('CONFIRM', "Once B79 is released and upgraded on the work Windows machine: in the Claude desktop app open a runner repo in "
           "its Claude Code (no run started from a terminal): (1) does 'status' give the run's status (the control brief)? (2) start "
           'a run from it, close the app: is the run still going? - reply with what you saw - reply yes/no')}


def test_need_detail_f162(tmp: Path) -> None:
    """F162: real asks split into what to do and what to see, nothing lost; <notes>/asks/ID.json stands in for them, a
    broken, odd or oversized one is the fallback; the pictures a task names and the file's are found."""
    from agent_runner import need_detail as N
    got = {}
    for tid, (label, ask) in ASKS_F162.items():
        pieces = N.split_ask(ask, label in ('CONFIRM', 'BLOCKED'))
        eq(''.join(p for _, p in pieces), ask, f'{tid}: the pieces joined are the ask')
        got[tid] = N.detail(label, tid, ask, 'A task', '', U.ask_short)
    for odd in ('', 'x', '  a; b  ', 'Pick: 1) a 2) b', 'Read (a; b: c', 'See https://x.y/z: ok. e.g. This one; then\nthat', '`a; b` then c'):
        eq(''.join(p for _, p in N.split_ask(odd)), odd, f'joined back: {odd!r}')
    b = got['B160']
    eq((b['said'], b['where'], b['summary']), ('Check this', 'iPhone, Safari', 'Reload, open a chat, tap the message box'), 'the card')
    eq(b['steps'], ['Reload, open a chat, tap the message box', 'Close the keyboard', 'Same in Talk, Home, Settings and a sheet.'], 'B160: the steps')
    eq(b['expect'], ['The header stays and the box rides up with no grey band.', 'It glides back.'], 'B160: what to see')
    eq(b['lead'], ['On an iPhone in Safari, after this lands and the run restarts'], 'B160: where and when')
    check('Chat and Home were already seen working on the iPhone 15 Pro' in b['notes'], 'B160: the rest is kept', b['notes'])
    eq((len(got['F154']['steps']), got['F154']['expect'], got['F154']['where']),
       (2, ['Taps still open rows, and holding a chat row still drags it'], 'iPhone'), 'F154')
    eq((got['F106h']['said'], len(got['F106h']['steps']), got['F106h']['expect']), ('Do this', 1, []), 'F106h: code after a colon is the same step')
    check('`run login copilot`' in got['F106h']['steps'][0], 'and it is kept', got['F106h'])
    eq((got['B163']['said'], got['B163']['steps']), ('Stuck', ['Waits for its Windows run']), 'B163')
    eq((len(got['B177']['steps']), len(got['B177']['expect'])), (3, 1), 'B177: then is a step, the colon what to see')
    eq((len(got['R6']['steps']), got['R6']['expect']), (3, ['Is the run still going?']), 'R6: (1) and (2)')
    eq(N.detail('DECIDE', 'F1', 'Which look: Full, Small?', '', '', U.ask_short)['steps'], ['Which look: Full, Small?'], 'a question is one piece')
    for semi, do, see in (  # F162a1: after a colon each piece after a ';' is classed again
            ('Tap Save: it says Saved; tap Undo; the list returns', ['Tap Save', 'Tap Undo'], ['It says Saved', 'The list returns']),
            ('Tap Save: it says Saved; and the list returns; and tap Undo', ['Tap Save', 'And tap Undo'], ['It says Saved', 'And the list returns']),
            ('Tap Save: it says Saved; on Home, the list returns; in Talk, tap Undo', ['Tap Save', 'In Talk, tap Undo'],
             ['It says Saved', 'On Home, the list returns']),
            ('Tap Save: it says Saved; your words are sent; Talk stays quiet', ['Tap Save'], ['It says Saved', 'Your words are sent', 'Talk stays quiet']),
            ('Tap Save: it says Saved; tap Undo: rows come back', ['Tap Save', 'Tap Undo'], ['It says Saved', 'Rows come back'])):
        pieces = N.split_ask(semi)
        eq(''.join(p for _, p in pieces), semi, f'joined back: {semi!r}')
        eq([[N.shown(p) for k, p in pieces if k == kind] for kind in ('do', 'see')], [do, see], f'classed again: {semi!r}')
    repo = fake_run(tmp)
    notes = repo / '.runner'
    for d in ('asks', 'uploads'):
        (notes / d).mkdir(parents=True, exist_ok=True)
    png = b'\x89PNG\r\n\x1a\nfake'
    for f in ('asks/one.png', 'uploads/IMG_1.png', 'uploads/IMG_2.PNG', 'secret.png'):
        (notes / f).write_bytes(png)
    S.C.todo.write_text(TODO.replace('which layout', f'which layout, see {notes}/uploads/IMG_1.png and .runner/uploads/gone.png'), encoding='utf-8')
    d3 = lambda: next(n['detail'] for n in U.snapshot(up=False, now=NOW, links={})['needs'] if n['id'] == 'D3')  # noqa: E731
    plain = d3()
    eq([s['src'] for s in plain['shots']], ['uploads/IMG_1.png'], 'the picture its line names, only one that is there')
    js = notes / 'asks' / 'D3.json'
    js.write_text(json.dumps({'summary': 'Open both', 'where': 'iPad', 'steps': ['Open one', 7, ''], 'expect': ['Two tabs'], 'shots': [
        {'file': 'one.png', 'caption': 'Before'}, {'file': 'uploads/IMG_2.PNG'}, {'file': '../secret.png', 'caption': 'x'},
        {'file': str(notes / 'secret.png')}, 'x', {'caption': 'y'}]}), encoding='utf-8')
    full = d3()
    eq({k: full[k] for k in ('summary', 'where', 'steps', 'expect', 'lead')},
       {'summary': 'Open both', 'where': 'iPad', 'steps': ['Open one'], 'expect': ['Two tabs'], 'lead': []}, 'the file stands in')
    eq([(s['src'], s['caption']) for s in full['shots']], [('asks/one.png', 'Before'), ('uploads/IMG_2.PNG', ''),
                                                           ('uploads/IMG_1.png', 'Picture named in the task')], 'its pictures, none from outside')
    for bad in ('{', '[]', 'null', '"x"', '{"steps": 5, "shots": {}, "expect": null, "summary": []}', '[' * 100000, '{"a": "' + 'x' * N.FILE_MAX + '"}'):
        js.write_text(bad, encoding='utf-8')
        eq(d3(), plain, f'the fallback for {bad[:20]!r}')
    js.write_bytes(b'\xff\xfe\x00')
    eq(d3(), plain, 'and for one that is no text')


def test_old_script_c37a(tmp: Path) -> None:
    """C37a: a BLOCKED item with an old <notes>/wizards/ID.sh shows its steps and links, read as text, nothing run."""
    from agent_runner import need_detail as N
    repo = fake_run(tmp)
    w = repo / '.runner' / 'wizards'
    w.mkdir(parents=True, exist_ok=True)
    mark = repo / 'ran'
    (w / 'D3.sh').write_text(f'#!/bin/bash\nstage() {{ touch {mark}; }}\n# STAGES: author this section.\n'
                             f'stage "Get the key"\nopen_url https://example.com/keys\nsay "Create a key, see https://example.com/help"\n'
                             f'step "Copy it"\ntouch {mark}\n', encoding='utf-8')
    d = N.detail('BLOCKED', 'D3', 'Give the key', 'T', '', U.ask_short)
    eq(d['steps'], ['Get the key', 'Open this', 'Create a key, see https://example.com/help', 'Copy it'], 'its steps')
    eq([m.get('link') for m in d['step_more']], [None, 'https://example.com/keys', 'https://example.com/help', None], 'its links')
    check(not mark.exists(), 'nothing ran')
    check(not any('cmd' in m for m in d['step_more']), 'no run line')
    eq(N.detail('CONFIRM', 'D3', 'Check it', 'T', '', U.ask_short)['steps'], ['Check it'], 'only a BLOCKED item reads it')


F399_ASK = {'summary': 'Give the link of Install Switch', 'steps': [
    {'text': "Add main's copy of Install Switch to Shortcuts", 'link': 'https://example.com/Install%20Switch.shortcut'}, 'Share > Copy iCloud Link'],
    'inputs': [{'key': 'icloud', 'label': 'iCloud link', 'kind': 'link', 'hint': 'It starts with https://www.icloud.com/shortcuts/',
                'match': r'https://www\.icloud\.com/shortcuts/[0-9a-f]+', 'confirm': 'This publishes the shortcut. Send it?'}]}


def test_need_give_f175(tmp: Path) -> None:
    """F175: the asks file's step links, commands and inputs are read; need_give sends them: text and links as quoted
    data in the answer, a secret only in the env file, which goes when its task lands or is dropped."""
    from agent_runner import asks as A, need_detail as N, plan as P
    repo = fake_run(tmp)
    todo, asks = repo / 'plan' / 'TODO.md', repo / '.runner' / 'asks'
    asks.mkdir(exist_ok=True)
    blocked = TODO.replace('- [ ] **B2** Fix the merge retry | files: b.py | after: F1',
                           '- [~] **B2** Fix the merge retry | files: b.py BLOCKED: CONFIRM: look at it')
    plain = None

    def ask(d, tid='D3') -> dict:
        todo.write_text(blocked, encoding='utf-8')
        (asks / f'{tid}.json').write_text(d if isinstance(d, str) else json.dumps(d), encoding='utf-8')
        return next(n for n in U.snapshot(up=False, now=NOW, links={})['needs'] if n['id'] == tid)

    plain = ask('{')
    eq((plain['detail']['inputs'], plain['detail']['step_more']), ([], []), 'a broken file falls back: no inputs')
    good = {'key': 'ok'}
    for odd in (5, {}, [good] * 2, *([good, x] for x in (
            5, {}, {'key': 'a b'}, {'key': 'a', 'kind': 'pin'}, {'key': 'a', 'match': '('}, {'key': 'a', 'match': 'x' * 201},
            {'key': 'a', 'kind': 'secret', 'env': 'A B'}, {'key': 'a', 'kind': ['x']}, {'key': 'a', 'confirm': True}, {'key': 'a', 'env': 'TOK'}))):
        eq(ask({'inputs': odd, 'steps': odd})['detail']['inputs'], [], f'one malformed, so none: {str(odd)[-40:]}')
    row = ask(F399_ASK)
    d = row['detail']
    eq((d['steps'], d['step_more']), (["Add main's copy of Install Switch to Shortcuts", 'Share > Copy iCloud Link'],
                                      [{'link': 'https://example.com/Install%20Switch.shortcut'}, {}]), 'F399: steps and the link')
    eq(d['inputs'], [{**F399_ASK['inputs'][0], 'env': ''}], 'F399: its input')
    eq(row['answers'], plain['answers'], "the plain answers stay F162's")
    more = ask({'steps': [{'cmd': 'gh auth login', 'on': 'rycs'}, {'cmd': 'ls'}, {'text': 'Look', 'link': 'javascript:x'}]})['detail']
    eq(more['steps'], ['Run this', 'Run this', 'Look'], 'steps with no words')
    eq((more['step_more'][0], bool(more['step_more'][1]['on']), more['step_more'][2]),
       ({'cmd': 'gh auth login', 'on': 'rycs'}, True, {}), 'a command and its machine; only web links')

    ask(F399_ASK)
    before, link = todo.read_text(encoding='utf-8'), 'https://www.icloud.com/shortcuts/ab12'
    r = U.need_give('D3', {'icloud': 'https://evil.example/x'}, confirm=True)
    eq((r['ok'], r.get('field'), r['argv']), (False, 'icloud', []), 'a failed match sends nothing')
    check('starts with https://www.icloud.com' in r['out'] and 'evil' not in r['out'], 'and says the hint', r)
    for bad in ('', 'x\ny', 5, 'javascript:alert(1)', link + '\n' + link, 'https://' + 'a' * N.LINK_MAX):
        eq(U.need_give('D3', {'icloud': bad}, confirm=True).get('field'), 'icloud', f'refused: {str(bad)[:20]!r}')
    for vals in ({}, None, {'icloud': link, 'more': 'x'}):
        check(not U.need_give('D3', vals, confirm=True)['ok'], 'only the inputs it has now', vals)
    r = U.need_give('D3', {'icloud': link})
    eq((r['code'], r.get('confirm')), (3, 'This publishes the shortcut. Send it?'), 'asked first')
    eq(todo.read_text(encoding='utf-8'), before, 'nothing was sent so far')
    r = U.need_give('D3', {'icloud': f' {link} '}, confirm=True)
    eq((r['ok'], r.get('gone')), (True, 'D3'), 'sent')
    check('- [ ] **D3**' in todo.read_text(encoding='utf-8') and f'"iCloud link" is "{link}"' in todo.read_text(encoding='utf-8'),
          'the task reopens with the link, quoted', todo.read_text(encoding='utf-8'))
    check('need_give' not in U.ACTIONS, 'a page cannot say it is secure itself')
    check(not U.need_give('D3', {'icloud': link}, confirm=True)['ok'], 'answered: no second time')

    markup = '$(touch x) | files: z.py \u2014 BLOCKED: (after F1) "q" (split into F9)'
    ask({'inputs': [{'key': 'note'}]}, 'B2')
    r = U.need_give('B2', {'note': markup})
    line = next(x for x in todo.read_text(encoding='utf-8').splitlines() if '**B2**' in x)
    check(r['ok'] and line.startswith('- [ ]'), "a CONFIRM's inputs reopen it, not tick it", line)
    check(' | files: z.py' not in line and '(split' not in line and 'BLOCKED:' not in line, 'a value is no plan markup', line)
    eq(json.loads(U.as_data(markup)), markup, 'and reads back as it was')

    secret = "s3cr'et $(x)"
    two = {'inputs': [{'key': 'tok', 'label': 'Token', 'kind': 'secret', 'env': 'MY_TOKEN'}]}
    ask(two)
    env = asks / 'D3.env'
    r = U.need_give('D3', {'tok': secret})
    check(not r['ok'] and r.get('field') == 'tok' and 'http' in r['out'] and not env.exists(), 'plain http: refused, says why', r)
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'no')]):
        check(not U.need_give('D3', {'tok': secret}, secure=True)['ok'] and not env.exists(), 'a failed answer keeps no secret')
    (repo / '.gitignore').write_text('')  # git would track it: excluded here
    r = U.need_give('D3', {'tok': secret}, secure=True)
    check(r['ok'] and env.is_file(), 'kept', r)
    import shlex
    eq(shlex.split(env.read_text(encoding='utf-8')), [f'MY_TOKEN={secret}'], 'in the env file, quoted')
    if os.name != 'nt':
        eq(env.stat().st_mode & 0o777, 0o600, 'owner-only')
    check('asks/' not in git(repo, 'status', '--porcelain', '-uall', '--', '.runner/asks/D3.env'), 'out of git')
    (repo / '.gitignore').write_text('.runner/\n')
    text = todo.read_text(encoding='utf-8')
    check('MY_TOKEN is in ' in text and 'asks/D3.env' in text.replace('\\', '/'), 'the note names it and where', text)
    snap = U.snapshot_json(up=False, now=NOW, links={})
    for f in repo.rglob('*'):
        if f.is_file() and f != env:
            check(b's3cr' not in f.read_bytes(), f'not in {f.relative_to(repo)}')
    check('s3cr' not in snap + json.dumps(r), 'nor in the snapshot or the result')

    ask({'inputs': [{'key': 'b', 'kind': 'secret'}]})
    U.need_give('D3', {'b': 'two'}, secure=True)
    eq(shlex.split(env.read_text(encoding='utf-8')), [f'MY_TOKEN={secret}', 'B=two'], 'a later one is added')
    A.sweep_env('HEAD')
    check(env.exists(), 'an open task keeps them')
    P.tick('D3', todo=todo)
    A.sweep_env('HEAD')
    check(env.exists(), 'one ticked here only, not landed yet, does too')
    git(repo, 'commit', '-qam', 'landed')
    A.sweep_env('HEAD')
    check(not env.exists(), 'gone once it landed')
    ask({'inputs': [{'key': 'b', 'kind': 'secret'}]})
    U.need_give('D3', {'b': 'two'}, secure=True)
    check(env.exists(), 'kept again')
    P.drop('D3', 'not wanted', todo=todo)
    check(not env.exists(), 'gone once dropped')


def test_part_of_part_b199(tmp: Path) -> None:
    """B199: a part of a part (F162a2) is a task id to every call that takes one; what is no id is still refused."""
    repo = fake_run(tmp)
    todo, asks = repo / 'plan' / 'TODO.md', repo / '.runner' / 'asks'
    todo.write_text(TODO.replace('**D3**', '**F162a2**'), encoding='utf-8')
    asks.mkdir(exist_ok=True)
    (asks / 'F162a2.json').write_text(json.dumps({'inputs': [{'key': 'note'}]}), encoding='utf-8')
    with mock.patch.object(U, 'agent_said', lambda tid: f'{tid} said'):
        eq(U.need_why('F162a2').get('text'), 'F162a2 said', 'Why it waits')
    check('F162a2' in U.task_text('F162a2').get('text', ''), "the task's text")
    with mock.patch.object(U, 'new_control', lambda text, wait: {'ok': True, 'text': text}):
        check('F162a2' in U.need_chat('F162a2').get('text', ''), 'Chat')
    check('F162a2' in U.control_argv('task_drop', tid='F162a2'), 'a run control')
    for bad in ('', None, 'f162a2', 'F', '162', 'F162-a', 'F162 a2', 'F162a2\n', '--F162a2'):
        eq([U.need_why(bad)['ok'], U.need_give(bad, {'note': 'x'}).get('code')], [False, 2], f'no task id: {bad!r}')
    r = U.need_give('F162a2', {'note': 'the top one'})
    eq((r['ok'], r.get('gone')), (True, 'F162a2'), 'its inputs are sent')
    check('- [ ] **F162a2**' in todo.read_text(encoding='utf-8'), 'and it reopens', todo.read_text(encoding='utf-8'))


def test_plan_facts_f150(tmp: Path) -> None:
    """F150: what All projects says of any project's plan: titles, the next tasks, what landed today."""
    import datetime as dt
    from agent_runner.config import Config
    repo = fake_run(tmp)
    c = Config(repo)
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n### Next\n- [ ] **F1** First\n- [~] **B2** Stuck\n- [x] **F3** Done\n'
                                           '### Parked\n- [ ] **F9** Later\n', encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n- [x] **F4** Old\n', encoding='utf-8')
    log = c.notes('events.jsonl')
    ev = lambda at, kind, tid: json.dumps({'time': at, 'kind': kind, 'id': tid, 'text': ''}) + '\n'
    log.write_text(ev('2026-11-23T10:00:00', 'landed', 'F0') + ev('2026-11-24T09:00:00', 'landed', 'F4') + 'half a li\n'
                   + ev('2026-11-24T09:30:00', 'started', 'F1') + ev('2026-11-24T10:00:00', 'landed', 'F3'), encoding='utf-8')
    day = dt.datetime(2026, 11, 24, 12)
    f = U.plan_facts(c, day)
    eq(f['titles'], {'F1': 'First', 'B2': 'Stuck', 'F9': 'Later'}, 'the open tasks by title')
    eq(f['queue'], [{'id': 'F1', 'title': 'First'}], 'the next ones: not stuck, not parked')
    eq(f['landed'], ['Done', 'Old'], 'what landed today, newest first')
    check(U.plan_facts(c, day) is f, 'kept while no file changes')
    log.write_text(log.read_text(encoding='utf-8') + ev('2026-11-24T11:00:00', 'landed', 'F1'), encoding='utf-8')
    eq(U.plan_facts(c, day)['landed'], ['First', 'Done', 'Old'], 'and read again when one does')
    eq(U.plan_facts(c, day + dt.timedelta(days=1))['landed'], [], 'nothing yet the next day')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_decide_options_f181c), in_tmp(test_plan_facts_f150), in_tmp(test_part_of_part_b199), in_tmp(test_need_give_f175), in_tmp(test_old_script_c37a), in_tmp(test_need_detail_f162), in_tmp(test_snapshot), in_tmp(test_idle_slots), in_tmp(test_version_f90),
                         in_tmp(test_actions), in_tmp(test_run_controls), in_tmp(test_row_actions),
                         in_tmp(test_real_command), in_tmp(test_shelved_f184),
                         in_tmp(test_to_new), in_tmp(test_control_titles),
                         in_tmp(test_queue_rows), in_tmp(test_feed), in_tmp(test_feed_prompt_b154), in_tmp(test_chat_at_b154), in_tmp(test_chat_hold_b158),
                         in_tmp(test_chat_and_terminal),
                         in_tmp(test_concept_copy), in_tmp(test_concept_chat), in_tmp(test_hidden_send),
                         in_tmp(test_delete_chats), in_tmp(test_chat_list_f133),
                         in_tmp(test_status_f124), in_tmp(test_chat_rows_f128), in_tmp(test_need_chat_f143),
                         in_tmp(test_feed_ids_b134), in_tmp(test_need_answers_c33), in_tmp(test_answers_f180), in_tmp(test_typed_decide_f181a)]))
