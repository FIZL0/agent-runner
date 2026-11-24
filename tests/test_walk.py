#!/usr/bin/env python3
"""F194c: the walkthrough in the terminal UI (agent_runner/walk.py): the page's list of steps, worded for keys; where
the person is, and that they skipped it, are kept. Drawing and keys in the TUI are in test_tui.py.

    python3 tests/test_walk.py
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from agent_runner import demo as D  # noqa: E402
from agent_runner import walk as W  # noqa: E402
from _web import in_tmp, logic_js  # noqa: E402


def test_steps() -> None:
    print('one list of steps for the page and the terminal UI')
    ss = W.steps()
    eq([s['id'] for s in ss], ['queue', 'start', 'session', 'needs', 'land', 'chat', 'own'], 'the steps in order')
    eq(set(W.PLACE), {s['id'] for s in ss}, 'each has its place in the terminal UI')
    for s in ss:
        own = [v for k, v in s.items() if k.startswith('page')]
        for up in (False, True):
            for n in (0, 1):
                said = W.words(s, up, n, n, n)
                check(said and 'None' not in said, f'{s["id"]}: has words', said)
                check(not any(v in said for v in own), f'{s["id"]}: none of them the page\'s own', said)
    check('T on Status [1]' in W.words(ss[1]) and 'Nothing starts until' in W.words(ss[1]), 'Start run: its key')
    check('S on Status [1]' in W.words(ss[1], up=True), 'a run up: the stop key')
    check('Nothing has landed yet' in W.words(ss[4]) and 'Nothing has' not in W.words(ss[4], landed=2), 'what landed')
    check('Start the run to see one' in W.words(ss[4]) and 'Start the run' not in W.words(ss[4], up=True), 'no run up: how to see one')
    check('agent-runner setup' in W.words(ss[6]), 'the last one: their own project')
    if shutil.which('node'):
        x = {'off': False, 'up': True, 'working': 1, 'needs': 1, 'landed': 1, 'home': False}
        page = logic_js([['walkStep', s['id'], x] for s in ss])
        eq([(p['id'], p['title']) for p in page], [(s['id'], s['title']) for s in ss], 'the page reads the same list')
        check(all('keys' not in p and '[1]' not in p['text'] and 'undefined' not in p['text'] for p in page), 'without the keys', page)


def test_kept(tmp: Path) -> None:
    print('where the person is, and skipped, are kept')
    f = tmp / '.runner' / 'walk.json'
    w = W.Walk(f)
    eq((w.at, w.off, f.exists()), ('queue', False, False), 'the first step at first')
    check(w.press('<') and w.at == 'queue', 'back on the first stays')
    check(w.press('>') and w.at == 'start' and W.Walk(f).at == 'start', 'next, kept')
    check(not w.press('x'), 'another key is not its own')
    w.press('/')
    check(w.off and W.Walk(f).off, 'skipped, kept')
    check(not w.press('>') and w.at == 'start', 'skipped: next is no key of its')
    w.press('/')
    eq((w.at, w.off), ('start', False), 'shown again where it was')
    for _ in range(5):
        w.press('>')
    check(w.at == 'own' and w.last, 'the last')
    w.press('>')
    eq((w.at, w.off), ('queue', True), 'done: shown again from the first')
    for text in ('x{', '[]', '{"at": "gone"}', ''):
        f.write_text(text, encoding='utf-8')
        eq((W.Walk(f).at, W.Walk(f).off), ('queue', False), f'nothing of use kept ({text!r})')


def test_where(tmp: Path) -> None:
    print('only in the example project')
    with mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME': str(tmp / 'runs' / '{repo}')}):
        root = D.make(tmp / 'ex')
    check(W.of(root, root / '.runner') is not None, 'there')
    (tmp / 'other').mkdir()
    eq(W.of(tmp / 'other', tmp / 'other'), None, 'not in another project')


if __name__ == '__main__':
    raise SystemExit(report([test_steps, in_tmp(test_kept), in_tmp(test_where)]))
