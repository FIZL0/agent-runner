#!/usr/bin/env python3
"""B794: what a BLOCKED under Needs you says: why it stopped, the steps, and what the run does after that.

    python3 tests/test_need_blocked.py        (no agent, no network)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from _check import check, eq, report
from agent_runner import need_detail as N
from agent_runner import plan as P
from agent_runner import tui
from _ui_model import fake_run, in_tmp
from _web import logic_js

R17 = ('the run served to the phone is 0.62.0 without F170; release V5 and run agent-runner upgrade, then this reruns '
       '— back for you: V5 landed')
PUSH = ('Needs a person with the claude.ai mobile app: start a run with [run] remote auto and watch whether a push arrives as c1 and the '
        'control server start, and whether a later concept push still arrives. Claude Code 2.1.329 only sends client/presence pulses for the '
        'presence file; the server decides on the push, and the session-ready push might get there before the first pulse. If it does, add '
        'a line to CHANGELOG.md.')
CI = ('`ci.yml` on main has had {} auto-filed tasks closed in 7 days while it still fails ({})',
      'look at why their fixes did not hold before another agent tries.', '`plan unblock` to let a run try again, or drop it')
NONE: list[str] = []
REAL = [  # real asks, from the plan and its history: (ask, why, steps, notes without the reply)
    ('log in to Copilot: `run login copilot` (device code; unattended it ended exit 124 waiting for approval at github.com/login/device). '
     'Then the Copilot check, the default and the docs follow; findings in docs/research/F106h-harness-end-to-end.md', NONE,
     ['Log in to Copilot: `run login copilot` (device code; unattended it ended exit 124 waiting for approval at github.com/login/device).'],
     ['After that: the Copilot check, the default and the docs follow', 'Findings in docs/research/F106h-harness-end-to-end.md']),
    ('Send the prepared text to an iFizBox control session; a slot here may not add tasks there',
     ['A slot here may not add tasks there'], ['Send the prepared text to an iFizBox control session'], NONE),
    ('Send the text to an iFizBox control session again; no task was found there after Done',
     ['No task was found there after Done'], ['Send the text to an iFizBox control session again'], NONE),
    ('unlock the iPhone 15 Pro and keep it awake; ios lockdown get PasswordProtected still true',
     ['Ios lockdown get PasswordProtected still true'], ['Unlock the iPhone 15 Pro and keep it awake'], NONE),
    *[(f'{CI[0].format(n, ids)}; {CI[1]} {CI[2]}', [CI[0].format(n, ids)], [CI[1][0].upper() + CI[1][1:], CI[2]], NONE)
      for n, ids in ((2, 'B104, B105'), (4, 'B104, B105, B150, B206'))],
    ('update Claude Code on this machine (remote-control has no --settings; new sessions from claude.ai/code start without the control brief)',
     NONE, ['Update Claude Code on this machine (remote-control has no --settings; new sessions from claude.ai/code start without the control brief)'], NONE),
    (PUSH, ['Needs a person with the claude.ai mobile app', PUSH[PUSH.index('Claude Code 2'):PUSH.index(' If it does')]],
     [PUSH[PUSH.index('start a run'):PUSH.index(' Claude Code 2')].capitalize().replace('changelog', 'CHANGELOG'), 'If it does, add a line to CHANGELOG.md'], NONE),
    ("the phone's UI lock was held by B415, reopen when B415 lands", ["The phone's UI lock was held by B415"], NONE,
     ['After that: it reopens when B415 lands']),
    ('wrangler OAuth login cannot change Workers Builds settings: Authentication error',
     ['Wrangler OAuth login cannot change Workers Builds settings: Authentication error'], NONE, NONE)]


def blocked(ask: str) -> dict:
    ask = P.plain_ask('BLOCKED', ask, '')
    eq(''.join(t for _, t in N.blocked_pieces(ask)), ask, f'the pieces joined are the ask: {ask[:40]!r}')
    return N.detail('BLOCKED', 'R17', ask, 'A task', '')


def test_r17(tmp: Path) -> None:
    """R17's ask: the reason is not what to see, the rerun is no step, and the release that landed is said as such."""
    fake_run(tmp)
    d = blocked(R17)
    eq((d['why'], d['summary'], d['steps'], d['expect']),
       (['The run served to the phone is 0.62.0 without F170'], 'Release V5 and run agent-runner upgrade',
        ['Release V5 and run agent-runner upgrade'], []), 'the reason, and the one step, which is the heading')
    eq(d['notes'], ['After that: this reruns', 'V5 has landed', 'Reply done once it is'], 'the rest are notes')
    eq(blocked(R17.replace('V5 landed', 'V5, F2 landed'))['notes'][1], 'V5, F2 have landed', 'two that landed')


def test_real_asks(tmp: Path) -> None:
    """Ten real asks: no reason is what to see, nothing a run does is a step, nothing lost."""
    fake_run(tmp)
    eq(len(REAL), 10, 'ten')
    for ask, why, steps, notes in REAL:
        d = blocked(ask)
        eq((d['why'], d['steps'], d['expect']), (why, steps, []), ask[:50])
        eq(d['notes'], [*notes, 'Reply done once it is'], f'notes: {ask[:50]}')
        eq(d['summary'], (steps or why)[0], f'the heading: {ask[:50]}')


def test_next(tmp: Path) -> None:
    """What the run or an agent does afterwards is a note in each wording; what the person does stays a step."""
    fake_run(tmp)
    for after, note in (('then this reruns', 'this reruns'), ('then I continue', 'I continue'), ('reopens after V5', 'it reopens after V5'),
                        ('and R48 opens the page there', 'R48 opens the page there'), ('then the agent checks it', 'the agent checks it')):
        d = blocked(f'the login expired; log in on the Mac, {after}')
        eq((d['why'], d['steps'], d['notes'][0]), (['The login expired'], ['Log in on the Mac'], f'After that: {note}'), after)
    d = blocked('Log in on the Mac, then reply. The agent then checks the name, and asks once more')
    eq((d['steps'], d['notes'][0]), (['Log in on the Mac', 'Reply.'], 'After that: the agent then checks the name, and asks once more'), 'the agent then')
    d = blocked('Log in on the Mac, the run will then continue')
    eq((d['steps'], d['notes'][0]), (['Log in on the Mac'], 'After that: the run will then continue'), 'will then')
    d = blocked('Renew the login, after that the run continues')
    eq((d['steps'], d['notes'][0]), (['Renew the login'], 'After that: the run continues'), 'after that')
    for ask, why in (('the login expired. This reruns', 'The login expired.'), ('V5 not released. Reopens after V5', 'V5 not released.'),
                     ('disk full; after you free it, this reruns', 'Disk full')):
        d = blocked(ask)
        eq((d['why'], d['steps'], d['notes'][0][:12]), ([why], [], 'After that: '), ask)
    for ask, why, step in (('disk full; free 5 GB', 'Disk full', 'Free 5 GB'),
                           ('Xcode license not accepted: run `x`', 'Xcode license not accepted', 'Run `x`'),
                           ('the login expired; log in — back for you: V5 landed; then tap Done', 'The login expired', 'Log in')):
        d = blocked(ask)
        eq((d['why'], d['summary'], d['expect']), ([why], step, []), ask)
    d = blocked('Open Home: the list shows; tap Undo, then restart the app')
    eq((d['why'], d['steps'], d['expect']), ([], ['Open Home', 'Tap Undo', 'Restart the app'], ['The list shows']), "what follows a step's colon is still to see")
    for odd in ('', 'x', '  a; b  ', ' — back for you: V5 landed', 'Read (a; b: c', '`a; b`, then c — no d', '1) a. 2) the b failed: c'):
        eq(''.join(t for _, t in N.blocked_pieces(odd)), odd, f'joined back: {odd!r}')


def test_others_unchanged(tmp: Path) -> None:
    """A CONFIRM keeps its expect and a DECIDE its question, with no why; a BLOCKED's ask file wins."""
    repo = fake_run(tmp)
    plain = P.plain_ask('CONFIRM', R17, '')
    d = N.detail('CONFIRM', 'R17', plain, 'T', '')
    eq((d['why'], d['expect'][0]), ([], 'The run served to the phone is 0.62.0 without F170'), 'a CONFIRM, split as before')
    eq(N.split_ask('The list returns; tap Undo, then this reruns'),
       [('see', 'The list returns; '), ('do', 'tap Undo, '), ('do', 'then this reruns')], 'split_ask itself')
    d = N.detail('DECIDE', 'R17', 'The port is taken. Which port?', 'T', '')
    eq((d['why'], d['question'], d['lead'], d['steps'], d['expect']), ([], 'Which port?', ['The port is taken.'], [], []), 'a DECIDE')
    f = repo / '.runner' / 'asks' / 'R17.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'summary': 'Upgrade', 'steps': ['Upgrade it'], 'expect': ['0.63.0']}), encoding='utf-8')
    d = N.detail('BLOCKED', 'R17', R17, 'T', '')
    eq((d['why'], d['summary'], d['steps'], d['expect']), ([], 'Upgrade', ['Upgrade it'], ['0.63.0']), 'its ask file')


def test_shown(tmp: Path) -> None:
    """The page's popup and the terminal's pane say why above What to do; a reason that is the heading is not repeated."""
    fake_run(tmp)
    row = {'id': 'R17', 'label': 'BLOCKED', 'detail': blocked(R17), 'age': '1m', 'ask': ''}
    why = 'The run served to the phone is 0.62.0 without F170'
    lone = dict(row, detail=blocked('the login failed'))
    if shutil.which('node'):
        old = {k: v for k, v in row['detail'].items() if k != 'why'}
        html, one, was = logic_js([['needBody', row, ''], ['needBody', lone, ''], ['needBody', dict(row, detail=old), '']])
        check(f'<section><h3>Why</h3><p>{why}</p></section>' in html and html.index('Why') < html.index('What to do'), 'the page', html)
        check('What you should see' not in html, 'nothing to see', html)
        check('Why' not in one, 'the heading says it', one)
        check('What to do' in was, "an older run's row has no why", was)
    lines = [''.join(t for t, _ in x) for x in tui.RunPage.need_lines(type('T', (), {
        'step_lines': lambda *a: None, 'give_fields': lambda *a: None, 'give_inputs': lambda *a: []})(), row, 90)]
    check(lines.index(f'Why: {why}') < lines.index('What to do'), 'the terminal', lines)


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(t) for t in (test_r17, test_real_asks, test_next, test_others_unchanged, test_shown)]))
