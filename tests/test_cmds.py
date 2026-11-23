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
    eq((RV.view_key('p on'), RV.view_key('s off'), RV.view_key('u on')), ('p on', 's off', None),
       'a key with on/off goes as the run reads it; u takes none')


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


C = Path('/tmp/f80/gamma')
RUNS = [{'root': A, 'name': 'alpha', 'run': {'up': True, 'slots': 2}, 'rows': []},
        {'root': B, 'name': 'beta', 'run': {'up': False}, 'rows': []},                # sessions, no run: left out
        {'root': C, 'name': 'gamma', 'run': {'up': True, 'slots': 1}, 'rows': []}]
FACTS = {A: {'left': 4, 'stopping': False, 'link': 'http://alpha:8770/?t=x'},
         B: {'left': 2, 'stopping': False, 'link': ''},
         C: {'left': 0, 'stopping': True, 'link': 'http://gamma:8770/?t=y'}}


def keys(*ks):
    it = iter(ks)
    return lambda: next(it)


def rows(here):
    return M.picker_rows(RUNS, here, info=lambda r: {'up': False}, facts=lambda r, run: FACTS.get(r, {}))


def test_picker_rows():
    print('F91: the run picker lists runs only; the current folder\'s project is row 1, marked here')
    eq([r['name'] for r in rows(None)], ['alpha', 'gamma'], 'outside a project: each run, no sessions-only project')
    rs = rows(C)
    eq([(r['name'], r['here']) for r in rs], [('gamma', True), ('alpha', False)], 'here is row 1')
    rs = rows(B)
    eq([(r['name'], r['here'], r['run'].get('up')) for r in rs][0], ('beta', True, False),
       'a project whose run is not up still shows when it is here')
    text = M.picker_text(rs, 0)
    eq('(not running)' in text.splitlines()[2] and 'here' in text.splitlines()[2], True, 'row 1 says not running, here')
    eq('> 1  beta' in text, True, 'row 1 is selected')
    eq('stopping' in M.picker_text(rows(None), 0), True, 'a stopping run says so instead of its tasks left')


def test_picker_keys():
    print('F91: j/k, the arrows, digits and Enter pick the right run; q and Esc quit')
    rs = rows(None) + rows(None)  # four rows
    shown = []
    eq(M.pick_run(rs, keys('enter'), shown.append), 0, 'Enter at once picks row 1')
    eq('> 1' in shown[0], True, 'row 1 is selected first')
    eq(M.pick_run(rs, keys('j', 'j', 'k', 'enter'), shown.append), 1, 'j j k Enter picks row 2')
    eq(M.pick_run(rs, keys('down', 'down', 'down', 'down', 'down', 'enter'), shown.append), 3, 'down stops at the end')
    eq(M.pick_run(rs, keys('up', 'enter'), shown.append), 0, 'up stops at the top')
    eq(M.pick_run(rs, keys('3'), shown.append), 2, 'a digit picks that row')
    eq(M.pick_run(rs, keys('9', 'q'), shown.append), None, 'a digit past the list does nothing; q quits')
    eq(M.pick_run(rs, keys('esc'), shown.append), None, 'Esc quits')


def test_launcher_actions():
    print('F91: in the launcher, w, t and c call their action; q goes back to the picker, Enter is done')
    called = []
    acts = {'w': lambda u: called.append(('w', u)) or 'opened', 'c': lambda u: called.append(('c', u)) or 'copied',
            't': lambda root: called.append(('t', root)) or ''}
    shown = []
    row = rows(None)[0]
    eq(M.launch(row, keys('w', 't', 'c', 'enter'), shown.append, acts), 'done', 'Enter ends')
    eq(called, [('w', FACTS[A]['link']), ('t', A), ('c', FACTS[A]['link'])], 'w opens, t the ui, c copies')
    eq('● run up · 2 slots · 4 tasks left' in shown[0] and FACTS[A]['link'] in shown[0], True,
       'the launcher shows the status and the link')
    eq('copied' in shown[-1] and 'control: agent-runner --help' in shown[-1], True, 'what c said, and the footer')
    seen = []
    code = M.cmd_pick(None, keys('2', 'q', 'enter', 'enter'), seen.append, acts,
                      sessions=lambda: RUNS)
    eq(code, 0, 'q in the launcher goes back, Enter picks again, Enter is done')
    eq([s.splitlines()[0] for s in seen if 'pick a run' not in s][:2], ['\x1b[1mgamma\x1b[0m  ' + str(C),
       '\x1b[1malpha\x1b[0m  ' + str(A)], 'row 2 (gamma) first, then back on row 1 (alpha)')
    started = []
    with mock.patch.object(M, 'run_info', lambda r: {'up': False}), \
            mock.patch.object(M, 'run_facts', lambda r, run: FACTS.get(r, {})), \
            mock.patch.object(M, 'cmd_background', lambda argv: started.append(argv) or 7):
        eq(M.cmd_pick(B, keys('enter'), seen.append, acts, sessions=lambda: RUNS), 7,
           'picking here when its run is not up starts it')
    eq(started, [[]], 'with cmd_background')


def test_bare_not_a_tty():
    print('F91: bare agent-runner with no terminal (or in a slot) starts the run as before, no picker')
    from agent_runner import cli, runner
    for tty, slot in ((False, ''), (True, '1')):
        got = []
        with mock.patch.object(M.sys.stdin, 'isatty', lambda: tty, create=True), \
                mock.patch.object(M.sys.stdout, 'isatty', lambda: tty, create=True), \
                mock.patch.dict(M.os.environ, {'AGENT_RUNNER_SLOT': slot} if slot else {}), \
                mock.patch('agent_runner.config.toplevel', lambda *a: ROOT), \
                mock.patch.object(cli, 'skill', lambda: None), mock.patch.object(cli, 'user_hook', lambda: None), \
                mock.patch.object(M, 'cmd_pick', lambda *a, **k: got.append('pick') or 0), \
                mock.patch.object(runner, 'cmd_background', lambda argv: got.append('background') or 0):
            eq(M.picker_wanted(), False, f'no picker (tty {tty}, slot {slot or "unset"})')
            eq((cli.main([]), got), (0, ['background']), 'bare starts the run, as today')
    with mock.patch.object(M.sys.stdin, 'isatty', lambda: True, create=True), \
            mock.patch.object(M.sys.stdout, 'isatty', lambda: True, create=True), mock.patch.dict(M.os.environ):
        M.os.environ.pop('AGENT_RUNNER_SLOT', None)
        eq(M.picker_wanted(), True, 'at a terminal, not a slot: the picker')


if __name__ == '__main__':
    raise SystemExit(report([test_attach_routes, test_run_view_posts_keys, test_list_two_projects,
                             test_attach_number, test_windows_hidden_consoles, test_picker_rows, test_picker_keys,
                             test_launcher_actions, test_bare_not_a_tty]))
