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
                           'url': 'https://claude.ai/artifact/k5', 'copy': ''}], 'concept with its page link')
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
    """B113/C23: `tmux list-panes -a` lines (session, window name, @runner, @runner-repo, @runner-run) like
    iFizBox's run, every pane tagged as this version tags it."""
    s = 'agents'
    return [f'{s}\t{name}\t\t{root}\t{root}', f'{s}\trunner-{name}\tboard\t{root}',
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
    """C23: a run whose runner pane (@runner-run this checkout) has no @runner-repo tag (an older agent-runner
    started it): Sessions has no rows, only the one restart line."""
    repo = fake_run(tmp)
    old = [f'ar-{repo.name}\t{repo.name}\t\t\t{repo}', f'ar-{repo.name}\t{repo.name} · 1 · c1\t\t',
           f'ar-{repo.name}\t{repo.name} · control 2\t\t', f'other\tagents-x\ts1\t/elsewhere/x']
    from unittest import mock
    with mock.patch.object(U, 'tmux_panes', return_value=old):
        snap = U.snapshot(up=True, now=NOW, links={})
        down = U.snapshot(up=False, now=NOW, links={})
    eq((snap['sessions'], snap['sessions_note']), ([], U.OLDER_RUN), 'no rows, the one restart line')
    eq(U.OLDER_RUN, 'This run was started by an older agent-runner: restart it to see its sessions.', 'its words')
    eq(([s['name'] for s in down['sessions']], down['sessions_note']), (['c1'], ''), 'no run up: no note')
    eq(U.older_run(True, []), False, 'no tmux panes to read: nothing told')
    eq(U.older_run(True, old[1:]), False, "a hidden run (no runner pane of this checkout), other panes untagged: "
       "not older")
    eq(U.older_run(True, ifizbox_panes(repo, repo.name)), False, 'tagged panes: not older')


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
       {'F1': '', 'F66': '', 'B2': 'B109 (landed)', 'F67': 'F66 Run page: lazygit layout on web', 'B3': '',
        'B4': 'Z99 (not in the plan)', 'D5': '', 'V6': 'all: everything above it'},
       "after's title: open, landed (in DONE.md), not in the plan, all")
    eq({t: q[t]['state'] for t in q},
       {'F1': 'running s2 6m', 'F66': 'ready', 'B2': 'ready', 'F67': 'after', 'B3': 'critical', 'B4': 'ready',
        'D5': 'blocked', 'V6': 'after'},
       'state: running sN Nm, ready, after (an open task ahead), critical, blocked ([~])')
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
    """F74: a session's feed is its transcript as say/you/tool/out entries, newest last; Pi's toolCall and
    toolResult read the same; a session with no transcript says so."""
    from unittest import mock
    fake_run(tmp)
    t = fake_transcript(tmp / 'c2.jsonl')
    with mock.patch.object(U, 'transcript_of', side_effect=lambda n: str(t) if n == 'c2' else ''), \
            mock.patch.object(U, 'session_sid', return_value=''):
        f = U.feed('c2')
        none = U.feed('s3')
        eq(U.feed('c2', limit=2)['entries'], f['entries'][-2:], 'a limit keeps the newest')
        check(U.feed('c2', limit=2)['more'], 'and says older ones were left out')
    eq(f['entries'], [{'kind': 'you', 'text': 'status?'}, {'kind': 'say', 'text': 'Checking the run.'},
                      {'kind': 'tool', 'text': 'Bash(./run status -n 20)'},
                      {'kind': 'out', 'text': 'run up: 3 slots\nl2\nl3\n…'},
                      {'kind': 'say', 'text': 'Nothing needs you.'}, {'kind': 'out', 'text': 'interrupted'}],
       'the feed: you, say, tool, out; meta, runner turns, thinking and subagents left out')
    eq((f['ok'], f['more']), (True, False), 'a whole feed')
    check(not none['ok'] and none['entries'] == [] and 'no transcript' in none['out'], 'no transcript: said', none)
    pi = [{'type': 'assistant', 'message': {'role': 'assistant', 'content': [
              {'type': 'text', 'text': 'Reading it.'},
              {'type': 'toolCall', 'name': 'read', 'arguments': {'path': 'a.py'}}]}},
          {'type': 'user', 'message': {'role': 'toolResult', 'content': [{'type': 'text', 'text': 'def a(): ...'}]}}]
    eq(U.feed_entries(pi), [{'kind': 'say', 'text': 'Reading it.'}, {'kind': 'tool', 'text': 'read(a.py)'},
                            {'kind': 'out', 'text': 'def a(): ...'}], "Pi's entries read the same")
    big = tmp / 'big.jsonl'
    last = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'tail'}]}}) + '\n'
    big.write_text(json.dumps({'type': 'user', 'message': {'content': 'x' * 100}}) + '\n' + last, encoding='utf-8')
    eq([d['type'] for d in U.tail_rows(str(big), nbytes=len(last) + 10)], ['assistant'],
       'a tail read skips the line it cut')


class FakeTmux:
    """tmux, faked: records each argv; capture-pane answers with a screen."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(argv)
        return (0, '❯ status?\n● run up\n') if argv[0] == 'capture-pane' else (0, '')


def test_chat_and_terminal(tmp: Path) -> None:
    """F74: chat to any control session (c1 through SEND, cN typed into its pane), interrupt (Escape into its
    pane), a new control session's link, the quick asks to c1, and the terminal view: ttyd, built-in
    (capture-pane, send-keys) or the feed only."""
    from unittest import mock
    from agent_runner import plat, slots
    fake_run(tmp)
    sent, typed, ran = [], [], []
    tm = FakeTmux()
    real = U.SEND[0], U.TMUX[0], U.RUN[0]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    U.TMUX[0] = tm
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'c3 is open: https://claude.ai/code/session_c3x\n'))[1]
    panes = {'c1': '%1', 'c6': '%6', 's2': '%12'}
    try:
        with mock.patch.object(U, 'session_pane', side_effect=lambda n: panes.get(n, '')), \
                mock.patch.object(slots, 'send_to_pane', side_effect=lambda p, t: (typed.append((p, t)), True)[1]):
            eq(U.act('chat_to', text='hi c1')['out'], 'sent to c1', 'c1 gets it the way chat does')
            eq(U.act('chat_to', text='how is R43?', to='c6')['out'], 'sent to c6', 'c6 too')
            r = U.act('chat_to', text='hello', to='c9')
            eq(U.act('interrupt', session='c6')['out'], 'interrupted c6', 'interrupt c6')
            eq(U.act('keys', session='s2', text='yes', key='Enter')['ok'], True, 'keys typed into s2')
            eq(U.act('keys', session='s2', key='F13')['ok'], False, 'an unknown key is refused')
            cap = U.capture('s2')
            nocap = U.capture('s9')
        eq(sent, ['hi c1'], 'c1 through SEND')
        eq(typed, [('%6', 'how is R43?')], "c6 typed into its own pane")
        check(not r['ok'] and 'no tmux pane' in r['out'], 'a session with no pane says so', r)
        eq(tm.calls[:3], [['send-keys', '-t', '%6', 'Escape'], ['send-keys', '-t', '%12', '-l', 'yes'],
                          ['send-keys', '-t', '%12', 'Enter']], 'Escape into c6; text then Enter into s2')
        eq((cap['ok'], cap['text'], cap['every']), (True, '❯ status?\n● run up\n', 0.5),
           'the built-in view captures the pane every 0.5 s')
        eq(tm.calls[-1], ['capture-pane', '-p', '-J', '-t', '%12'], 'by tmux capture-pane')
        check(not nocap['ok'], 'no pane: nothing to capture', nocap)

        n = U.act('new_control', ask='')
        eq((n['ok'], n['link'], ran[-1]), (True, 'https://claude.ai/code/session_c3x', ['control', '--new']),
           'a new control session (control --new) and its claude.ai/code link')
        U.act('new_control', ask='theme ideas')
        eq(ran[-1], ['control', '--new', '--ask', 'theme ideas'], 'with a first message')

        sent.clear()
        for k in ('since', 'yesterday', 'needs', 'usage'):
            U.act('quick_ask', key=k)
        eq(sent, ['what happened since my last look?', 'what happened since yesterday?', 'what needs me?',
                  'where are the tokens going?'], 'the quick asks go to c1')
        eq(U.act('quick_ask', key='nope')['ok'], False, 'an unknown quick ask is refused')
        eq([a['key'] for a in U.snapshot(up=False, now=NOW, links={})['quick_asks']],
           ['since', 'yesterday', 'needs', 'usage'], 'the snapshot lists them')
    finally:
        U.SEND[0], U.TMUX[0], U.RUN[0] = real

    which = lambda have: (lambda name: f'/usr/bin/{name}' if name in have else None)  # noqa: E731
    with mock.patch.object(plat, 'WINDOWS', False):
        with mock.patch('shutil.which', side_effect=which({'tmux', 'ttyd'})):
            eq(U.terminal_mode(), 'ttyd', 'tmux and ttyd: ttyd')
        with mock.patch('shutil.which', side_effect=which({'tmux'})):
            eq(U.terminal_mode(), 'builtin', 'tmux, no ttyd: the built-in view')
        with mock.patch('shutil.which', side_effect=which(set())):
            eq(U.terminal_mode(), 'feed', 'no tmux: the feed only')
    with mock.patch.object(plat, 'WINDOWS', True), mock.patch('shutil.which', side_effect=which({'tmux', 'ttyd'})):
        eq(U.terminal_mode(), 'feed', 'Windows: the feed only')


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


def in_tmp(f):
    def go():
        print(f.__name__)
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_snapshot), in_tmp(test_idle_slots), in_tmp(test_actions), in_tmp(test_real_command),
                         in_tmp(test_to_c1_by_tag), in_tmp(test_control_windows), in_tmp(test_older_run),
                         in_tmp(test_queue_rows), in_tmp(test_feed), in_tmp(test_chat_and_terminal),
                         in_tmp(test_concept_copy)]))
