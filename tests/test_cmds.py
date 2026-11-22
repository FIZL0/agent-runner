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


if __name__ == '__main__':
    raise SystemExit(report([test_attach_untagged_control_window, test_window_name_forms]))
