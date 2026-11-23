#!/usr/bin/env python3
"""C26: `attach` with no name is the run view (its log, live, and its keys, posted to KEYS); `attach sN|cN` a
session's own terminal; `attach feed|board` the TUI. F80: `list` and `attach N` read the hidden sessions'
markers, never a terminal multiplexer.

    python3 tests/test_cmds.py        (no tmux, no agent; a few seconds)
"""
from __future__ import annotations

import io
import tempfile
import time
from pathlib import Path
from unittest import mock

from _check import eq, report

from agent_runner import cmds as M  # noqa: E402
from agent_runner import loop as LP  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import run_view as RV  # noqa: E402

ROOT = Path('/tmp/c26/proj')


def attach(which: str, sock: Path | None = None) -> tuple[int, list]:
    """`attach which` with the run view, the TUI and a session's socket stood in for: (exit code, what ran)."""
    ran: list = []
    with mock.patch.object(M, 'init'), mock.patch.object(M, 'ROOT', ROOT), mock.patch.object(M.plat, 'WINDOWS', False), \
            mock.patch.object(RV, 'run_view', lambda: ran.append('run view') or 0), \
            mock.patch('agent_runner.tui.main', lambda argv: ran.append('tui') or 0), \
            mock.patch.object(M, 'session_socket', lambda name: sock), \
            mock.patch.object(M, 'attach_session', lambda s, name: ran.append(('attach', name, s)) or 0), \
            mock.patch.object(M, 'hidden_attach', lambda _: ''):
        return M.cmd_attach([which] if which else []), ran


def test_attach_routes():
    print('C26: attach, attach run, attach feed|board, attach cN')
    eq(attach(''), (0, ['run view']), 'attach with no name is the run view')
    eq(attach('run'), (0, ['run view']), 'attach run is the run view too')
    eq(attach('feed'), (0, ['tui']), 'attach feed opens the TUI')
    eq(attach('board'), (0, ['tui']), 'attach board opens the TUI')
    sock = Path('/tmp/c26/proj/.runner/control4.sock')
    eq(attach('c4', sock), (0, [('attach', 'c4', sock)]), 'attach c4 goes through its shim\'s socket')
    eq(attach('s9'), (1, []), 'a session that is not up: exit 1, nothing run')


def test_run_view_posts_keys():
    print("C26: the run view shows the log and posts a typed 's!' to KEYS")
    d = Path(tempfile.mkdtemp(prefix='c26-view-'))
    (d / 'run.log').write_text('=== 2026-11-22T10:00:00 run: 2 slots\n', encoding='utf-8')

    class Notes:
        @staticmethod
        def notes(*parts):
            return d.joinpath(*parts)

    out = io.StringIO()
    with mock.patch.object(LP, 'C', Notes), mock.patch.object(RV, 'C', Notes):
        code = RV.run_view(stdin=io.StringIO('s!\nwhat\n\n?\n'), out=out, poll=0.05,
                           until=time.monotonic() + 1.0, check_up=False)
        posted = P.take(Notes, 'KEYS')
    text = out.getvalue()
    eq(code, 0, 'the view ends (here at its deadline) with 0')
    eq(posted, ['s!', 'remote'], "'s!' and the empty line (Remote Control) reach KEYS; '?' and an unknown line do not")
    eq('run: 2 slots' in text, True, 'the log shows')
    eq(text.count('runner keys:'), 2, 'the keys once at the start and again on ?')
    eq('Ctrl-C leaves this view' in text and '\nnow: ' not in text, True,
       'the view says Ctrl-C leaves it, and no state line of its own process')
    eq("unknown key 'what'" in text, True, 'an unknown line says so')
    eq(RV.view_key('slots 4'), 'slots 4', 'slots N is a key')
    eq(RV.view_key('  +  '), '+', 'spaces around a key are dropped')


A = Path('/tmp/f80/alpha')
B = Path('/tmp/f80/beta')
C_ = Path('/tmp/f80/gamma')
HIDDEN = {A: {'feed': 40, 'c1': 41, 's1': 42}, B: {'c2': 50}, C_: {}}
TITLES = {A: {1: 'alpha · 1 · Pairing broken'}}
INFO = {A: {'up': True, 'state': 'running', 'slots': 2, 'running': {'1': 'F80'}, 'since': {'1': 1000.0}},
        B: {'up': False}, C_: {'up': False}}


def test_list_two_projects():
    print('F80: the hidden sessions of two projects give the numbered list')
    ps = M.device_projects(HIDDEN, info=INFO.get, now=1000.0 + 12 * 60, titles=TITLES)
    eq([p['name'] for p in ps], ['alpha', 'beta'], 'each project with sessions, by name; one with none and no run left out')
    eq([(r['n'], r['name'], r['what']) for p in ps for r in p['rows']],
       [(1, 'run', 'the run'), (2, 'feed', 'runner feed'), (3, 'c1', 'Pairing broken'), (4, 's1', 'F80 · 12m'),
        (5, 'c2', 'control session')], 'run, feed, cN with titles from state, sN with task and minutes, 1..N')
    text = M.list_text(ps)
    eq(text.splitlines()[0], f'alpha  run up: running · 2 slots  ({A})', 'the project line says the run and slots')
    eq('no run up' in text and '    4  s1    F80 · 12m' in text, True, 'beta has no run; s1 shows its task')
    eq(M.list_text([]), 'no agent-runner sessions on this device\n', 'nothing to list says so')


def test_attach_number():
    print('F80: attach 3 / attach <project> X run that project\'s attach, from its own checkout')
    ps = M.device_projects(HIDDEN, info=INFO.get, now=2000.0, titles=TITLES)
    for argv, want in ((['3'], (A, 'c1')), (['beta', 'c2'], (B, 'c2')), (['alpha', 'feed'], (A, 'feed')),
                       (['alpha', 'run'], (A, 'run'))):
        went, ran = [], []
        real = M.cmd_attach
        with mock.patch.object(M, 'device_sessions', lambda: ps), mock.patch.object(M.plat, 'WINDOWS', False), \
                mock.patch.object(M.os, 'chdir', went.append), \
                mock.patch.object(M, 'cmd_attach', lambda a: ran.append(a) or 0):
            eq(real(argv), 0, f'attach {" ".join(argv)} succeeds')
        eq((went, ran), ([want[0]], [[want[1]]]), f'attach {" ".join(argv)} is {want[1]} of {want[0].name}')
    with mock.patch.object(M, 'device_sessions', lambda: ps):
        eq(M.cmd_attach(['9']), 1, 'a number not listed fails')
        eq(M.cmd_attach(['beta', 's1']), 1, 'a session the project does not have fails')


def test_windows_hidden_consoles():
    print('F80: Windows lists the hidden slot consoles; attach N shows that console')
    ps = M.device_projects({A: {'s1': 4242}}, info={A: {'up': False}}.get, now=1000.0 + 60)
    eq([(r['n'], r['name'], r['what'], r['pid']) for p in ps for r in p['rows']], [(1, 's1', 'idle', 4242)],
       'the console is listed')
    shown = []
    with mock.patch.object(M, 'device_sessions', lambda: ps), mock.patch.object(M.plat, 'WINDOWS', True), \
            mock.patch.object(M.plat, 'show_console', lambda pid: shown.append(pid) or True):
        eq(M.cmd_attach(['1']), 0, 'attach 1 succeeds')
    eq(shown, [4242], 'it shows that console')


if __name__ == '__main__':
    raise SystemExit(report([test_attach_routes, test_run_view_posts_keys, test_list_two_projects,
                             test_attach_number, test_windows_hidden_consoles]))
