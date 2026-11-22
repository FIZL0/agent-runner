#!/usr/bin/env python3
"""B114: `attach cN` finds a control session by its window name when its pane has no cN tag (an older
agent-runner opened it as '<repo> · N · title' in ar-<repo>), as the ui's Sessions lists it since B113.

    python3 tests/test_cmds.py        (a fake tmux listing, no tmux, no agent; well under a second)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from _check import eq, report

from agent_runner import cmds as M  # noqa: E402
from agent_runner import slots as SL  # noqa: E402

ROOT = Path('/tmp/b114/proj')


def attach(which: str, listing: list[str]) -> tuple[int, list[list[str]]]:
    """`attach which` against a fake `tmux list-panes -a` listing: its exit code and the tmux commands it ran."""
    ran: list[list[str]] = []

    def fake_tmux(*args):
        eq(args[-1].split('\t')[-1], '#{window_name}', 'attach asks tmux for each pane\'s window name too')
        return subprocess.CompletedProcess(list(args), 0, '\n'.join(listing) + '\n', '')

    with mock.patch.object(M, 'init'), mock.patch.object(M, 'ROOT', ROOT), mock.patch.object(M.plat, 'WINDOWS', False), \
            mock.patch.object(M, 'tmux', fake_tmux), mock.patch.object(M.shutil, 'which', lambda _: '/usr/bin/tmux'), \
            mock.patch.object(M, 'hidden_attach', lambda _: ''), \
            mock.patch.object(M.sp, 'run', lambda c, **kw: ran.append(c)), \
            mock.patch.object(M.sp, 'call', lambda c, **kw: ran.append(c) or 0), \
            mock.patch.dict(M.os.environ, {}, clear=False):
        M.os.environ.pop('TMUX', None)
        return M.cmd_attach([which]), ran


def test_attach_untagged_control_window():
    print('B114: attach c4 on an untagged "<repo> · 4 · x" window in ar-<repo> selects that pane')
    listing = ['ar-proj\t%1\t\t\t' + str(ROOT) + '\tproj',                      # the runner
               'ar-proj\t%7\t\t\t\tproj · 4 · x',                              # c4, opened by an older version
               'ar-other\t%8\t\t\t\tproj · 4 · x',                             # same name, another session
               f'ar-proj\t%9\ts1\t{ROOT}\t\tproj · s1']
    code, ran = attach('c4', listing)
    eq(code, 0, 'attach c4 succeeds')
    eq(ran[:2], [['tmux', 'select-window', '-t', '%7'], ['tmux', 'select-pane', '-t', '%7']],
       'it selects the untagged c4 pane in ar-proj, not the one in another session')
    eq(ran[-1], ['tmux', 'attach-session', '-t', 'ar-proj'], 'and attaches to ar-proj')


def test_window_name_forms():
    print('B114: control_window_pane reads each window name form; tags and other repos win or are left out')
    eq(SL.attach_target(['ar-proj\t%2\t\t\t\tproj · control 3'], ROOT, 'c3'), ('ar-proj', '%2'),
       '"<repo> · control N" counts')
    eq(SL.attach_target(['ar-proj\t%2\t\t\t\tproj · 3'], ROOT, 'c3'), ('ar-proj', '%2'), '"<repo> · N" counts')
    eq(SL.attach_target(['elsewhere\t%2\t\t' + str(ROOT) + '\t\tproj · 3 · t'], ROOT, 'c3'), ('elsewhere', '%2'),
       'a pane with this repo tag counts in any session')
    eq(SL.attach_target(['elsewhere\t%2\t\t/other/proj\t\tproj · 3 · t'], ROOT, 'c3'), None,
       'another repository\'s pane of the same name is left out')
    eq(SL.attach_target(['ar-proj\t%2\t\t\t\tproj · 13 · t'], ROOT, 'c3'), None, 'c3 is not c13')
    eq(SL.attach_target(['ar-proj\t%2\ts3\t\t\tproj · 3 · t'], ROOT, 'c3'), None,
       'a tagged pane is found by its tag only')
    eq(SL.attach_target(['ar-proj\t%2\t\t\t'], ROOT, 'c3'), None, 'rows with no window name: as before')
    eq(SL.attach_target(['ar-proj\t%2\t\t\t\tproj · 3'], ROOT, 's3'), None, 'only control sessions fall back')
    tagged = [f'ar-proj\t%5\tc3\t{ROOT}\t\tproj · R43 · deploy', 'ar-proj\t%2\t\t\t\tproj · 3']
    eq(SL.attach_target(tagged, ROOT, 'c3'), ('ar-proj', '%5'), 'a cN tag comes first')


A = Path('/tmp/f80/alpha')
B = Path('/tmp/f80/beta')
DEVICE = [f'ar-alpha\t%1\t\t{A}\t{A}\t\talpha',                                  # alpha's run
          f'ar-alpha\t%2\tboard\t{A}\t\tfeed/run\talpha · feed',                 # its runner feed
          f'ar-alpha\t%3\tc1\t{A}\t\t\talpha · 1 · Pairing broken',               # c1, titled
          f'ar-alpha\t%4\ts1\t{A}\t\t\tagents-alpha',                             # s1 on a task
          f'ar-beta\t%5\tc2\t{B}\t\t\tbeta · 2',                                  # beta: one control session
          'mine\t%6\t\t\t\t\tbeta · 3 · not tagged',                              # untagged: never listed
          'mine\t%7\t\t\t\t\tzsh']
INFO = {A: {'up': True, 'state': 'running', 'slots': 2, 'running': {'1': 'F80'}, 'since': {'1': 1000.0}},
        B: {'up': False}}


def test_list_two_projects():
    print('F80: a fake tmux listing with two projects gives the numbered list')
    ps = M.device_projects(DEVICE, info=INFO.get, now=1000.0 + 12 * 60)
    eq([p['name'] for p in ps], ['alpha', 'beta'], 'each project with sessions, by name')
    eq([(r['n'], r['name'], r['what']) for p in ps for r in p['rows']],
       [(1, 'run', 'the run'), (2, 'feed', 'runner feed'), (3, 'c1', 'Pairing broken'), (4, 's1', 'F80 · 12m'),
        (5, 'c2', 'control session')], 'run, feed, cN with titles, sN with task and minutes, numbered 1..N')
    text = M.list_text(ps)
    eq(text.splitlines()[0], f'alpha  run up: running · 2 slots  ({A})', 'the project line says the run and slots')
    eq('no run up' in text and '    4  s1    F80 · 12m' in text, True, 'beta has no run; s1 shows its task')
    eq(M.list_text([]), 'no agent-runner sessions on this device\n', 'nothing to list says so')


def attach_listed(argv: list[str], inside: bool) -> tuple[int, list[list[str]]]:
    ran: list[list[str]] = []
    env = {'TMUX': '/tmp/tmux-1/default,1,0'} if inside else {}
    with mock.patch.object(M, 'device_sessions', lambda: M.device_projects(DEVICE, info=INFO.get, now=2000.0)), \
            mock.patch.object(M.sp, 'run', lambda c, **kw: ran.append(c)), \
            mock.patch.object(M.sp, 'call', lambda c, **kw: ran.append(c) or 0), \
            mock.patch.object(M, 'init', lambda *a: (_ for _ in ()).throw(AssertionError('no repo needed'))), \
            mock.patch.dict(M.os.environ, env, clear=False):
        if not inside:
            M.os.environ.pop('TMUX', None)
        return M.cmd_attach(argv), ran


def test_attach_number():
    print('F80: attach 3 runs the right tmux command; inside tmux it uses switch-client')
    code, ran = attach_listed(['3'], inside=False)
    eq(code, 0, 'attach 3 succeeds from any folder')
    eq(ran, [['tmux', 'select-window', '-t', '%3'], ['tmux', 'select-pane', '-t', '%3'],
             ['tmux', 'attach-session', '-t', 'ar-alpha']], 'number 3 is alpha c1: tmux attach')
    code, ran = attach_listed(['3'], inside=True)
    eq(ran[-1], ['tmux', 'switch-client', '-t', 'ar-alpha'], 'inside tmux: switch-client')
    code, ran = attach_listed(['beta', 'c2'], inside=False)
    eq((code, ran[0]), (0, ['tmux', 'select-window', '-t', '%5']), 'attach <project> cN')
    code, ran = attach_listed(['alpha', 'feed'], inside=False)
    eq(ran[0], ['tmux', 'select-window', '-t', '%2'], 'attach <project> feed')
    code, ran = attach_listed(['9'], inside=False)
    eq((code, ran), (1, []), 'a number not listed fails and runs nothing')
    code, ran = attach_listed(['beta', 's1'], inside=False)
    eq((code, ran), (1, []), 'a session the project does not have fails')


def test_windows_hidden_consoles():
    print('F80: Windows lists the hidden slot consoles; attach N shows that console')
    ps = M.device_projects([], info=INFO.get, now=1000.0 + 60, hidden={A: {'s1': 4242}})
    eq([(r['n'], r['name'], r['what'], r['pid']) for p in ps for r in p['rows']], [(1, 's1', 'F80 · 1m', 4242)],
       'the console is listed with its task')
    shown = []
    with mock.patch.object(M, 'device_sessions', lambda: ps), \
            mock.patch.object(M.plat, 'show_console', lambda pid: shown.append(pid) or True):
        eq(M.cmd_attach(['1']), 0, 'attach 1 succeeds')
    eq(shown, [4242], 'it shows that console')


if __name__ == '__main__':
    raise SystemExit(report([test_attach_untagged_control_window, test_window_name_forms, test_list_two_projects,
                             test_attach_number, test_windows_hidden_consoles]))
