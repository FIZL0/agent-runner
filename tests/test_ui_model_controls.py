#!/usr/bin/env python3
"""F65, C44: the run page model: the run controls and the row actions.

    python3 tests/test_ui_model_controls.py        (a temp repo, no agent, no network)

The fake run and the helpers are in tests/_ui_model.py.
"""
from __future__ import annotations
import re
from pathlib import Path
from unittest import mock
from _check import check, eq, report
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp,NOW, fake_run, chat  # noqa: E402


RUN_CONTROL_ARGV = {  # F82: each run control and the runner command it must run
    'slot_add': ['slots', '+1'], 'slot_remove': ['slots', '-1'], 'slots_set': ['slots', '4'],
    'pause': ['pause'], 'go_on': ['pause', '--off'], 'force': ['force'], 'caps_on': ['force', '--off'],
    'stop': ['stop'], 'stop_now': ['stop', '--force'], 'stop_undo': ['stop', '--undo'],
    'task_drop': ['plan', 'drop', 'F1', U.TASK_DROP_WHY], 'task_cancel': ['plan', 'cancel', 'F1', '--yes'],  # F426d
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
            want = {*RUN_CONTROL_ARGV, 'queue_take', 'queue_drop', 'queue_priority', 'queue_unpark',
                    'menu_hold', 'menu_unhold', 'menu_top', 'menu_remove', 'menu_restore',  # F429b
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
        r = U.act('run_control', key='queue_take', tid='F1', wait=False)
        eq((r['ok'], sent, ran), (True, [], [['control', '--new', '--no-wait', '--ask', 'do F1 here', '--no-feed']]),
           'B139: Do it here asks a new control session "do F1 here", not c1')
        ran.clear()
        with mock.patch.object(U.S, 'run_up', lambda: True), mock.patch.object(U.time, 'time', lambda: NOW):
            r = U.run_control('task_cancel', tid='F1')
            eq((r['ok'], r['code'], ran), (False, 3, []), 'F426d: Cancel asks first')
            check(r['confirm'].startswith('F1 has worked 14 min in s1. ') and r['confirm'].endswith('Cancel F1?'),
                  'with the minutes worked', r['confirm'])
            r = U.run_control('task_cancel', tid='B2', confirm=True)
            eq((r['ok'], r['code'], ran), (False, 1, []), 'and is refused while the task lands')
            r = U.run_control('task_cancel', tid='F1', confirm=True)
            eq((r['ok'], ran), (True, [['plan', 'cancel', 'F1', '--yes']]), 'then runs')
        r = U.run_control('task_take', tid='F1', confirm=True)
        eq(r['ok'], False, 'Take back is gone')
        ran.clear()
        for bad in ({'key': 'slots_set', 'n': '-2'}, {'key': 'slots_set', 'n': '4; rm'}, {'key': 'slots_set'},
                    {'key': 'task_drop', 'tid': '--force'}, {'key': 'nope'}, {'key': 'resume'},
                    {'key': 'wip_drop', 'tid': 'task/F1', 'confirm': True}):
            r = U.act('run_control', **bad)
            eq((r['ok'], r['code']), (False, 2), f'refused: {bad}')
        eq(ran, [], 'a refused control runs nothing')
        by = {c['key']: c for c in U.controls()}
        eq((by['slots_set']['needs'], by['task_drop']['needs'], by['task_cancel']['needs'], by['pause']['needs']),
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
        eq(ran, [['plan', 'edit', 'F1', '--pri', 'high'], ['plan', 'edit', 'R8', '--pri', 'normal']],
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
        r = U.run_control('release_now', confirm=True, text='V6')
        eq((r['ok'], ran), (True, [['plan', 'add', 'V', '--now']]), 'release now, V6 named in the Yes (F186)')
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


def test_no_run_f402c1(tmp: Path) -> None:
    """F402c1: with no run up the queue's actions stay on and run, the slot controls are hidden, and an added task says
    that it waits for the run to start."""
    fake_run(tmp)
    snap = U.snapshot(up=False, now=NOW, links={})
    eq((snap['shown'], snap['card']), (['start'], ['start']), 'Start alone: no pause, slots or stop')
    acts = {q['id']: q['acts'] for q in snap['queue']}
    eq((acts['T7'], acts['R8']), (['queue_priority', 'queue_take', 'queue_drop'], ['queue_unpark', 'queue_take', 'queue_drop']), "a row's actions")
    ran: list = []
    with mock.patch.object(U.S, 'run_up', lambda: False), \
            mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'added T7 (low)\nnote'))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: {'ok': True, 'code': 0, 'out': 'sent', 'argv': []}]):
        eq(U.run_control('queue_priority', tid='T7')['ok'], True, 'Priority runs')
        eq(U.run_control('queue_drop', tid='T7', confirm=True)['ok'], True, 'Drop runs')
        eq(U.act('chat', text='hello')['ok'], True, 'a message goes')
        r = U.act('plan_add', kind='T', text='Tidy')
        eq((r['said'], r['out']), ('added T7: waits for the run to start', 'added T7: waits for the run to start (low)\nnote'), 'an added task says so')
    with mock.patch.object(U.S, 'run_up', lambda: False), mock.patch.object(U, 'RUN', [lambda argv: (0, 'added R8')]):
        check('said' not in U.plan_add('R', 'Later'), 'not a parked one')
    with mock.patch.object(U.S, 'run_up', lambda: True), mock.patch.object(U, 'RUN', [lambda argv: (0, 'added T7')]):
        check('said' not in U.plan_add('T', 'Tidy'), 'nor with a run up')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_run_controls), in_tmp(test_row_actions), in_tmp(test_no_run_f402c1)]))
