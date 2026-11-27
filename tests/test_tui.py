#!/usr/bin/env python3
"""F67, F76: the Run page in the terminal draws a snapshot in the lazygit layout, each panel's tabs as round 2
of the web page has them, and its keys move focus and run F74's actions.

    python3 tests/test_tui.py        (no curses, no run, no network; well under a second)

curses is stubbed: a window that keeps a grid of characters and their colours. A fixed snapshot (with F74's
queue states, quick asks and a concept's K copy) is drawn into a fixed-size screen: every tab of every panel,
the queue's tags and its open row, the bottom line's rules. Keys drive the navigation, the boxes (typing,
drafts, Esc), and each action, with the runner call and F74's session actions swapped for recorders.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import state as S  # noqa: E402
from agent_runner import theme as TH  # noqa: E402
from agent_runner import tui as T  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import walk as W  # noqa: E402

COPY = '''<html><head><style>h1{color:red}</style></head><body>
<h1>Lazy layout</h1><p>Three ways to lay out the run page.</p>
<h2>Option A</h2><p>One page the runner republishes.</p>
<h2>Option B</h2><p>A page with a shared database.</p>
<h2>A + B · recommended</h2><p>The page is the hub; the database keeps its rows.</p>
</body></html>'''

SNAP = {
    'project': 'proj', 'at': '2026-11-21T10:00:00', 'up': True, 'slots': 3,
    'status': ['run up: 3 slots', '4 tasks left', 'release: waits on 2 of 2', 'usage: session 42%, week 85%'],
    'sessions': [
        {'name': 'c1', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
         'link': 'https://claude.ai/code/session_c1', 'terminal': ''},
        {'name': 'c6', 'task': '', 'title': 'theme ideas', 'minutes': None, 'state': 'live', 'files': [],
         'link': '', 'terminal': ''},
        {'name': 's1', 'task': 'F1', 'title': 'Board page for the run', 'minutes': 14, 'state': 'running',
         'files': ['a.py'], 'link': 'https://claude.ai/code/session_1', 'terminal': ''},
        {'name': 's2', 'task': 'B2', 'title': 'Fix the merge retry', 'minutes': 1, 'state': 'merging',
         'files': ['b.py'], 'link': '', 'terminal': ''}],
    'queue': [{'id': f'Q{i}', 'kind': 'feature', 'title': f'Queued task number {i}', 'files': [f'q{i}.py'],
               'after': [], 'pri': 'normal', 'section': 'Next', 'blocked': False, 'after_title': '',
               'state': 'ready'} for i in range(1, 10)],
    'needs': [{'label': 'CONFIRM', 'id': 'D3', 'concept': '', 'title': 'Write the guide', 'what': 'is it right',
               'url': 'https://claude.ai/artifact/abc', 'ask': 'Is the guide right? - reply yes/no', 'age': '2h'},
              {'label': 'CONCEPT', 'id': 'F4', 'concept': 'K5', 'title': 'Lazy layout', 'what': '',
               'url': 'https://claude.ai/artifact/k5', 'ask': 'Pick an option for lazy layout', 'age': '1d',
               'answers': [{'label': n, 'value': n} for n in ('Option A', 'Option B', 'A + B · recommended')]},
              {'label': 'DECIDE', 'id': 'D7', 'concept': '', 'title': 'Pick a port', 'what': 'which port',
               'url': '', 'ask': 'Which port? - reply with your answer', 'age': '5m'}],
    'concepts': [{'id': 'F4', 'concept': 'K5', 'title': 'Lazy layout', 'url': 'https://claude.ai/artifact/k5',
                  'copy': '/notes/concepts/K5.html'}],
    'log': [f'=== 10:{i:02d} line {i}' for i in range(20)], 'release': 'release: waits on 2 of 2',
    'quick_asks': U.quick_asks(), 'terminal_mode': 'install',
}
SNAP['queue'][0].update(state='running s1 6m', title='Queued task number 1, which has a long title that runs on '
                        'well past the width of the panel it is listed in')
SNAP['queue'][1].update(id='B2', state='critical', pri='critical')
SNAP['queue'][2].update(id='C3', state='after', after=['Q4'], after_title='Q4 Queued task number 4')

U.queue_row = lambda tid: next((q for q in SNAP['queue'] if q['id'] == tid), None)  # C34: no TODO.md here
U.row_of = lambda where, tid: U.queue_row(tid) if where == 'queue' else {'name': tid} if where == 'session' else next(
    (r for r in SNAP['needs' if where == 'need' else 'concepts'] if tid in (r['id'], r.get('concept') or r['id'])), None)  # C35

DIFF = 'diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-old line\n+new line\n context'


class Win:
    """A stub curses window: a grid of characters (and their colour) of a fixed size."""

    def __init__(self, h: int, w: int):
        self.h, self.w = h, w
        self.erase()

    def getmaxyx(self):
        return self.h, self.w

    def erase(self):
        self.grid = [[' '] * self.w for _ in range(self.h)]
        self.colour = [[0] * self.w for _ in range(self.h)]

    def addnstr(self, y, x, s, n, attr=0):
        for i, c in enumerate(s[:n]):
            if 0 <= y < self.h and 0 <= x + i < self.w:
                self.grid[y][x + i], self.colour[y][x + i] = c, attr

    def lines(self) -> list[str]:
        return [''.join(r) for r in self.grid]

    def text(self) -> str:
        return '\n'.join(self.lines())

    def at(self, s: str) -> tuple[int, int]:
        """Where `s` is first drawn: (row, column); (-1, -1) when it is not."""
        for y, l in enumerate(self.lines()):
            if s in l:
                return y, l.index(s)
        return -1, -1


# each colour a bit of its own, so a cell tells which colour drew it
ATTRS = {name: 1 << i for i, name in enumerate(T.COLOURS + ('sel', 'cur', 'mode'))}


def colour_at(win: Win, s: str, offset: int = 0) -> str:
    y, x = win.at(s)
    a = win.colour[y][x + offset] if y >= 0 else -1
    return next((n for n, v in ATTRS.items() if v == a), '?')


def page(snap=None, **kw) -> T.RunPage:
    snap = snap or SNAP
    kw.setdefault('diff', lambda name: DIFF)
    kw.setdefault('read', lambda path: COPY if path.endswith('K5.html') else '')
    kw.setdefault('opener', lambda url: {'ok': True, 'out': f'opened {url}'})
    kw.setdefault('socket', lambda name: False)  # F112: no session to attach, unless a test says so
    kw.setdefault('tmux', lambda argv: (1, 'no tmux in this test'))
    return T.RunPage(snap, get_snap=lambda: snap, attrs=ATTRS, **kw)


def drawn(p: T.RunPage, h: int = 32, w: int = 120) -> Win:
    win = Win(h, w)
    p.draw(win)
    return win


def queue_ids_shown(win: Win) -> list[str]:
    left = [l[:36] for l in win.lines()]  # the panels' column at 100 wide
    return [q for q in ['Q1', 'B2', 'C3'] + [f'Q{i}' for i in range(4, 10)] if any(f'{q} ' in l for l in left)]


def test_layout() -> None:
    p, win = page(), Win(30, 100)
    p.key('2')
    p.draw(win)
    txt = win.text()
    for title in ('[1] Status', '[2] Sessions', '[3] Queue', '[4] Needs you', '[5] Concepts'):
        check(title in txt, f'{title} is drawn', txt)
    eq(queue_ids_shown(win), ['Q1', 'B2', 'C3'], 'the unfocused queue shows 3 rows')
    check('1 of 10 · 3 to expand' in txt, 'the unfocused queue counts its rows and says how to expand', txt)
    check(win.lines()[0].startswith('proj 0 all runs'), 'B153: the top line names the project first, its key 0',
          win.lines()[0])
    check('agent-runner' not in win.lines()[0], 'B153: not agent-runner', win.lines()[0])
    check('? keys' not in win.lines()[0], 'the top line shows no key (the bottom line has ? keys)', win.lines()[0])
    check(win.lines()[-1].startswith(' SESSIONS '), 'the bottom line starts with the mode badge', win.lines()[-1])
    eq([r['name'] for r in p.items(2)], ['c1', 'c6', 's1', 's2', 's3', '+'],
       'Sessions: c1, the other control sessions, every slot (idle s3 too), then the new chat row')
    check(any('+ new chat n' in l[:36] for l in win.lines()), "Sessions' last row: '+ new chat' with its key", txt)
    eq(colour_at(win, 'new chat n', 9), 'hkey', 'the row shows n in the key colour')
    check('│ c6 theme ideas chat' in txt, 'a control session row: name, title, chat', txt)
    check('Board page for the run' in txt, 'a slot row shows its task', txt)
    hs = p.heights(28)
    eq(sum(hs.values()), 28, 'the panels fill the body')
    p.key('3')
    tall = Win(40, 100)
    p.draw(tall)
    eq(queue_ids_shown(tall), ['Q1', 'B2', 'C3'] + [f'Q{i}' for i in range(4, 10)], 'focused, the queue takes the '
       'spare height')
    narrow = Win(30, 60)
    p.draw(narrow)
    check('[3] Queue' in narrow.text() and 'direct edit' not in narrow.text(), 'narrow: the panels take the width',
          narrow.text())
    p.key('ENTER')
    p.draw(narrow)
    check('direct edit' in narrow.text() and '[3] Queue' not in narrow.text(),
          'narrow, Enter: the main pane takes the width', narrow.text())
    p.key('ESC')
    eq(p.main, False, 'Esc backs out of the main pane')
    p.key('?')
    win = drawn(p)
    check('Keybindings' in win.text(), '? shows the keys')
    eq((colour_at(win, 'J/K'), colour_at(win, 'move down / up')), ('hkey', 'fg'),
       'the keys list: keys yellow, labels in the text colour')
    p.key('ESC')
    eq(p.help, False, 'Esc closes the keys')
    check('too small' in drawn(p, 5, 20).text(), 'a tiny terminal is told so')


def test_status_tabs() -> None:
    p = page()
    eq(p.tab(), ('log', ['log', 'release', 'controls']), 'F112: a status line: log, release, controls (no chat)')
    p.key('ENTER')
    win = drawn(p)
    for b in ('[s since last look]', '[y since yesterday]', '[w what needs me]', '[u usage]'):
        check(b in win.text(), f'the log tab shows the quick ask {b}', win.text())
    eq((colour_at(win, '[s since', 1), colour_at(win, '[s since', 3)), ('hkey', 'fg'),
       'a quick ask: its key in the key colour, its label in the text colour')
    check('line 19' in win.text(), 'the log tab shows the newest lines')
    check('❯ message c1' not in win.text(), 'F112: no chat box')
    p.key('l')
    eq(p.tab()[0], 'release', 'l: the next tab')
    p.key('h')
    p.key('h')
    eq((p.main, p.tab()[0]), (False, 'log'), 'h on the first tab goes back to the panels')
    p.key('j')
    p.key('j')
    eq(p.tab(), ('release', ['release', 'log', 'controls']), 'the release line: release first')
    p.key('ENTER')
    win = drawn(p)
    check('[⏎ release when the running tasks land]' in win.text() and '[f release now, without them]' in win.text(),
          'the release tab: its two buttons', win.text())
    eq(colour_at(win, '[⏎ release when', 1), 'pkey', 'the primary button: its key red')
    check('F1 Board page for the run in s1' in win.text(), 'it lists the running tasks', win.text())


def test_session_tabs() -> None:
    p = page()
    p.key('2')
    eq(p.tab()[1], ['session'], 'F112: a control session: session (no chat tab, no pane tab)')
    p.cur[2] = 2
    eq(p.tab()[1], ['session', 'diff'], 'a slot on a task: session, diff')
    p.key('ENTER')
    win = drawn(p)
    check('s1 has no terminal to show here' in win.text(), 'F141: no socket: it says so, no feed', win.text())
    check('❯ message' not in win.text(), 'F112: no box to message the slot', win.text())
    check('https://claude.ai/code/session_1' in win.text() and '[o open it] [y copy link]' in win.text(),
          'the session tab: its link, o open it, y copy link', win.text())
    check('[⏎ show it beside]' not in win.text(), 'no socket: nothing to show beside', win.text())
    eq([u for *_, u in p.links], ['https://claude.ai/code/session_1'], 'B125: its link is kept for OSC 8')
    p.socket = lambda name: name == 's1'
    win = drawn(p)
    check('[⏎ show it beside]' in win.text(), 'F88: with a socket and no pane, Enter shows it beside', win.text())
    p.socket = lambda name: False
    p.key('l')
    win = drawn(p)
    eq((colour_at(win, '+new line'), colour_at(win, '-old line'), colour_at(win, '@@ -1,2')),
       ('green', 'red', 'cyan'), 'the diff tab: added green, removed red, hunks cyan')
    p.key('l')
    eq(p.tab()[0], 'diff', 'l on the last tab stays there')
    p.cur[2] = 4
    eq(p.tab()[1], ['session'], 'an idle slot: session')
    check('s3 is idle: nothing running' in drawn(p).text(), "an idle slot's session says so")
    p.cur[2] = 5
    eq(p.tab()[1], ['info'], "the '+ new chat' row: info")
    check('[n start one]' in drawn(p).text(), 'it says n starts one')
    p.cur[2] = 1
    win = drawn(p)
    check('c6 has no terminal to show here' in win.text(), 'F141: a cN row draws no feed', win.text())
    check('❯ message c6' not in win.text(), 'F112: no message box for a control session', win.text())


def test_kinds_f195b() -> None:
    """F195b: a queue row has its kind's word and colour, the project's own kinds too; a narrow panel says the word on the selected row."""
    row = {'id': 'M4', 'title': 'Look', 'state': 'ready'}
    p = page(dict(SNAP, kinds=TH.kind_table({'M': 'research: find out', 'Z': 'board work'})))
    eq(p.row_lines(3, row, 60, False)[0][0], ('M4   research ', 'yellow'), 'another letter, the same kind')
    eq(p.row_lines(3, dict(row, id='Z1'), 60, False)[0][0], ('Z1   board    ', 'dim'), "the project's own: gray")
    eq(p.row_lines(3, dict(row, id='T21'), 60, False)[0][0], ('T21  tests    ', 'green'), 'a default')
    eq(p.row_lines(3, row, 26, False)[0][0], ('M4   ', 'yellow'), 'narrow: no word')
    check('research · ready' in ''.join(t for l in p.row_lines(3, row, 26, True) for t, _ in l), 'but when it is selected')


def test_queue() -> None:
    p = page()
    p.key('3')
    win = drawn(p, 32, 100)
    eq(p.tab()[1], ['direct edit', 'chat edit'], 'a task: direct edit, chat edit (no info tab)')
    eq((colour_at(win, 'B2 '), colour_at(win, 'C3 '), colour_at(win, 'Q4 ')), ('red', 'dim', 'dim'),
       "kind-coloured ids: B red, C gray, a kind of the project's own gray")
    y = win.at('B2 ')[0]
    check(win.lines()[y][:36].rstrip().endswith('critical │'), 'critical: a red tag at the right', win.lines()[y])
    eq(colour_at(win, 'critical'), 'red', 'in red')
    eq(colour_at(win, ' ready', 1), 'green', 'ready: green')
    check('⧗ after Q4' in win.text(), "a waiting task: '⧗ after <id title>'", win.text())
    eq(colour_at(win, '⧗ after Q4'), 'dim', 'dim')
    title = 'which has a long title that runs on well past the width of the panel it is listed in'
    left = ' '.join(l[:36].strip('│ ') for l in win.lines())
    check(' '.join(title.split()[:4]) in left and 'listed in' in left, 'the open row wraps to its whole title',
          left)
    check('s1 6m' in left, 'and shows its tag (sN Nm) under it', left)
    eq(colour_at(win, 's1 6m'), 'sel', 'on the focused row ground (yellow off it)')
    p.key('j')
    p.key('j')
    win = drawn(p, 32, 100)
    left = ' '.join(l[:36].strip('│ ') for l in win.lines())
    check('⧗ after Q4 Queued task number 4' in left, 'the open waiting row: its whole after line', left)
    p.key('4')
    win = drawn(p, 32, 100)
    eq(colour_at(win, 's1 6m'), 'yellow', 'unfocused, the running tag is yellow')
    check('which has a long title that runs on well past' not in ' '.join(l[:36] for l in win.lines()),
          'the unfocused queue does not wrap its rows')
    p.key('3')
    p.cur[3] = 9
    eq(p.tab()[1], ['chat edit', 'direct edit'], "the '+ new task' row: chat edit first")
    check(any('+ new task n' in l[:36] for l in drawn(p).lines()), "'+ new task' with its key")


def test_form_pane_v_task() -> None:
    """B128: a V task's edit pane: the text now in the typed text's colour, the kind its short name, any run-on
    indented under the value."""
    p = page()
    it = {'id': 'V3', 'title': 'Release the next version with its notes and tag'}
    for width in (60, 24):
        lines = p.form_pane(it, width)
        now = [l for l in lines if any('now: ' in t for t, _ in l)]
        check(now, f'the text now is shown ({width})', lines)
        start = lines.index(now[0])
        segs = [s for l in lines[start:start + 3] for s in l if s[0].strip() and 'now:' not in s[0]
                and any(w in s[0] for w in ('Release', 'version', 'notes', 'tag'))]
        check(segs and all(c == 'fg' for _, c in segs), f'the text now is fg, not dim ({width})', segs)
        k = next(i for i, l in enumerate(lines) if l and l[0] == ('k', 'hkey'))
        kind_text = ''.join(t for l in lines[k:k + 3] for t, _ in l)
        check('release' in kind_text and 'waits for everything' not in kind_text, 'the kind: its short name only',
              kind_text)
        end = next(i for i, l in enumerate(lines) if l and l[0] == ('p', 'hkey'))
        for l in lines[k + 1:end]:
            check(l[0][0].startswith('    '), f'a kind-line continuation starts indented ({width})', l)
        check(all(sum(len(t) for t, _ in l) <= width for l in lines[k:end]), f'the kind lines fit the pane ({width})',
              lines[k:end])


def test_direct_edit() -> None:
    p = page()
    ran: list = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'edited'))[1]]):
        p.key('3')
        p.key('j')
        p.key('e')
        eq((p.main, p.tab()[0], p.typing), (True, 'direct edit', 'form:B2:t'), 'e: the direct edit, typing in t')
        win = drawn(p)
        for lab in ('t what, why, how to check', 'k kind', 'p priority', 'f files', 'a after'):
            check(lab in win.text(), f'the field "{lab}" is labelled with its key', win.text())
        eq((colour_at(win, 'k kind'), colour_at(win, 'k kind', 2)), ('hkey', 'dim'), 'a label: key yellow, words dim')
        check('[^S save] [D drop] [H do it here]' in win.text() and 'cancel' not in win.text(),
              'buttons ^S save, D drop, H do it here; no cancel', win.text())
        check('nothing: it can start when a slot is free' in win.text(), 'an empty after says so')
        p.key('1')
        eq(p.panel, 3, 'typing in a box, 1 is a character, not a panel')
        for c in ' now':
            p.key(c)
        p.key('ESC')
        eq((p.typing, p.main), ('', True), 'Esc leaves the field, not the edit')
        p.key('k')
        eq(p.form(p.sel())['kind'], 'F', 'k cycles the kind (B to F)')
        p.key('K')
        p.key('K')
        eq(p.form(p.sel())['kind'], 'V', 'K goes back (F, B, round to V)')
        p.key('k')
        p.key('p')
        eq(p.form(p.sel())['pri'], 'high', 'p steps the priority (critical to high)')
        p.key('p')
        eq(p.form(p.sel())['pri'], 'normal', 'then to normal')
        p.key('a')
        for c in 'Q4':
            p.key(c)
        check('Q4 Queued task number 4' in drawn(p).text(), "a after shows its task's title under it")
        p.key('TAB')
        eq(p.typing, 'form:B2:t', 'Tab: the next field (from a, round to t)')
        p.key('BTAB')
        eq(p.typing, 'form:B2:a', 'Shift+Tab: the previous field')
        p.key('BTAB')
        eq((p.typing, p.form(p.sel())['field']), ('form:B2:f', 'f'), 'and again: f')
        p.key('BTAB')
        eq((p.typing, p.form(p.sel())['field']), ('', 'p'), 'priority is toggled, not typed into')
        p.key('5')
        eq((p.panel, p.main), (5, False), '1-5 work in a direct edit, when not typing')
        p.key('3')
        p.key('ENTER')
        eq(p.form(p.sel())['text'].endswith(' now'), True, 'the edit is kept while away')
        p.key('^S')
        eq(ran, [['plan', 'edit', 'B2', '1 now', '--after', 'Q4', '--pri', 'normal']],
           '^S: plan edit with only the changed fields (the files left out)')
        eq((p.main, p.typing, 'B2' in p.forms), (False, '', False), 'saved: back to the panels, the edit done')
        p.key('ENTER')
        win = drawn(p)
        check('now: Queued task number 2' in win.text() and '❯ Queued' not in win.text(),
              "the text field starts empty (the snapshot's title is cut), the text now under it", win.text())
        p.key('k')
        p.key('^S')
        eq((len(ran), p.msg_ok), (1, False), 'a queued task keeps its kind: a new kind is refused, nothing run')
        p.key('K')
        p.key('f')
        for _ in 'q2.py':
            p.key('BS')
        p.key('^S')
        eq((len(ran), p.msg_ok, p.msg.startswith('files cannot be emptied')), (1, False, True),
           'an emptied field is refused, said so (plan edit sets, never clears)')
    p2 = page()
    ran2: list = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran2.append(argv), (0, 'added B10'))[1]]):
        p2.key('3')
        p2.cur[3] = 9
        p2.key('l')
        p2.key('l')
        eq(p2.tab()[0], 'direct edit', 'the new task row has a direct edit too')
        p2.key('^S')
        eq((ran2, p2.msg_ok), ([], False), 'a new task with no text is not saved')
        p2.key('t')
        for c in 'Fix it':
            p2.key(c)
        p2.key('TAB')
        p2.key('k')
        p2.key('TAB')
        p2.key('p')
        p2.key('TAB')
        for c in 'x.py':
            p2.key(c)
        p2.key('^S')
        eq(ran2, [['plan', 'add', 'T', 'Fix it', '--files', 'x.py', '--pri', 'critical']], 'a new task: plan add')
        eq(p2.main, False, 'saved: back to the panels')


def test_navigation() -> None:
    p = page()
    p.key('TAB')
    eq(p.panel, 2, 'Tab: the next panel')
    p.key('BTAB')
    eq(p.panel, 1, 'Shift+Tab: the previous one')
    p.key('2')
    p.key('^L')
    eq(p.main, True, '^l: the right side')
    p.key('^H')
    eq(p.main, False, '^h: the left side')
    p.cur[2] = 2
    p.key('ENTER')
    p.key('l')
    eq(p.tab()[0], 'diff', 'l: next tab')
    p.key('ESC')
    eq(p.main, False, 'Esc: back to the panels')
    tabs = dict(p.tabs)
    p.key(']')
    p.key('[')
    eq((p.tabs, p.main), (tabs, False), 'no [ ] keys')
    p.key('R')
    eq((p.panel, p.main), (2, False), 'R does nothing outside Status')
    p.key('1')
    p.key('R')
    eq((p.panel, p.cur[1], p.tab()[0], p.main), (1, 2, 'release', True), 'R in Status: the release tab')
    for n in '12345':
        p.key(n)
        p.key('ENTER')
        p.key('4' if n != '4' else '3')
        eq((p.panel, p.main), (4 if n != '4' else 3, False), f'1-5 work from panel {n}\'s main pane')
    started = []
    with mock.patch.object(p, 'new_chat', lambda: started.append(1)):
        p.key('c')
    eq((started, p.typing), ([1], ''), 'c: a new chat (F176), as n in Sessions')
    p.key('ESC')
    p.key('2')
    p.cur[2] = 3
    p.key('t')
    eq((p.sel()['name'], p.tab()[0], p.main), ('s2', 'session', True), 't: the slot\'s session')
    p.key('j')
    p.key('j')
    eq((p.sel()['name'], p.main), ('s2', True), 'j/k scroll the pane: the selection stays')
    eq(p.key('q'), True, 'q quits')


def test_no_message_box_f112() -> None:
    """F112: no session has a message box: i and Enter type nothing, nothing is sent, and no '❯ message' line is
    drawn, for any session row on any tab, nor on Status."""
    p = page()
    sent = []
    with mock.patch.object(U, 'chat_to', lambda text, to='c1': (sent.append((to, text)), {'ok': True, 'out': ''})[1]), \
            mock.patch.object(U, 'send', lambda name, text: (sent.append((name, text)), {'ok': True, 'out': ''})[1]):
        p.key('2')
        for i, row in enumerate(p.items(2)):
            p.cur[2] = i
            for tab in p.tab()[1]:
                p.tabs[p._tab_key(p.sel())] = tab
                p.main = True
                eq(p.box(), '', f'{row["name"]} {tab}: no box')
                win = drawn(p)
                check('❯ message' not in win.text() and '⏎ send' not in win.text(),
                      f'{row["name"]} {tab}: no message box drawn', win.text())
                p.key('i')
                eq(p.typing, '', f'{row["name"]} {tab}: i types nowhere')
        p.key('1')
        p.key('ENTER')
        check('❯ message' not in drawn(p).text(), 'Status: no chat box')
        eq(p.key('^C'), True, 'Ctrl+C quits (no chat to interrupt)')
    eq(sent, [], 'nothing was sent to a session')


def test_new_chat_f112() -> None:
    """F112 (1): n does not wait for the session's link: `new_control` runs on a thread without waiting (a
    stand-in that sleeps), a 'starting...' row is selected at once, and the cN row takes its place once the
    run's state lists it."""
    import threading
    more = {**SNAP, 'sessions': SNAP['sessions'][:2] + [
        {'name': 'c7', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
         'link': 'https://claude.ai/code/session_c7', 'terminal': ''}] + SNAP['sessions'][2:]}
    snaps = [SNAP]
    go, calls = threading.Event(), []

    def slow(ask='', wait=True):
        calls.append(wait)
        go.wait(5)
        snaps[0] = more
        return {'ok': True, 'code': 0, 'out': 'control 7 is starting in a hidden terminal', 'argv': [],
                'link': '', 'name': 'c7'}
    p = T.RunPage(SNAP, get_snap=lambda: snaps[0], attrs=ATTRS, socket=lambda name: False, tmux=lambda argv: (1, ''))
    p.key('2')
    with mock.patch.object(U, 'new_control', slow):
        t0 = T.time.time()
        p.key('n')
        took = T.time.time() - t0
        check(took < 1, f'n returns at once ({took:.2f} s) while new_control still runs')
        it = p.sel()
        eq((p.panel, bool(it.get('starting'))), (2, True), "the new 'starting...' row is selected at once")
        check('starting...' in drawn(p).text(), "its row says 'starting...'", drawn(p).text())
        check('Its row and link fill in once it is up.' in drawn(p).text() and '[n start one]' not in drawn(p).text(),
              'the main pane says it is starting (not the new chat row\'s text)', drawn(p).text())
        p.key('n')
        eq(p.msg, 'a new chat is starting already', 'n again while one starts: said, not another')
        go.set()
        for _ in range(50):
            if 'r' in (p.starting or {}):
                break
            T.time.sleep(0.05)
        p.poll_new_chat()
    eq(calls, [False], 'new_control ran once, not waiting for the link (--no-wait)')
    eq((p.starting, p.sel()['name']), (None, 'c7'), 'its cN row takes its place, selected')
    check('https://claude.ai/code/session_c7' in p.msg, 'the link, read from state, on the message line', p.msg)
    with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, 'control 8 is starting in x'))[1]]):
        r = U.new_control(wait=False)
    eq((calls[-1], r['name']), (['control', '--new', '--no-wait'], 'c8'), "U.new_control(wait=False): "
       "control --new --no-wait, the cN it started")
    from agent_runner import feed as FD
    out = io.StringIO()
    with mock.patch.object(FD, 'hidden_control', lambda n, cmd: (4321, '')), \
            mock.patch.object(FD, 'hidden_control_log', lambda n: Path(tempfile.mkdtemp()) / 'control8.log'), \
            mock.patch.object(FD, 'remote_on', lambda: True), contextlib.redirect_stdout(out):
        t0 = T.time.time()
        rc = FD.control_new_hidden(8, ['control', '8'], 'c8', wait=-1)
    check(rc == 0 and T.time.time() - t0 < 1 and 'control 8 is starting' in out.getvalue(),
          '--no-wait (wait -1): back at once, before any link', out.getvalue())


class Tmux:
    """A stand-in tmux runner: records each command; split-window answers with a new pane id."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.n = 10

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[0] == 'split-window':
            self.n += 1
            return 0, f'%{self.n}'
        if argv[0] == 'list-keys':
            return 1, 'unknown key'
        return 0, ''

    def did(self, verb: str) -> list[list[str]]:
        return [c for c in self.calls if c[0] == verb]


def test_new_chat_key_f153() -> None:
    """F153: n starts a new chat in Sessions, from any row and its main pane; N does not. An n that answers a
    Needs you item or a confirm starts none."""
    started = []
    for row in range(len(page().items(2))):
        for main in (False, True):
            p = page()
            with mock.patch.object(T.RunPage, 'new_chat', lambda self: started.append(row)):
                p.key('2')
                p.cur[2], p.main = row, main
                p.key('N')
                eq(started, [], f'N on row {row} (main {main}): no new chat')
                p.key('n')
                eq(started, [row], f'n on row {row} (main {main}): a new chat')
            started.clear()
    with mock.patch.object(T.RunPage, 'new_chat', lambda self: started.append('n')):
        p = page()
        p.panel, p.confirm = 2, 'need_drop'
        p.key('n')
        eq((started, p.confirm), ([], ''), 'n at a run control question: only no')
        p.panel, p.main = 4, False
        said = []
        with mock.patch.object(U, 'answer', lambda *a, **k: (said.append(a[1]), {'ok': True, 'out': ''})[1]):
            p.key('ENTER')
            p.key('n')
        eq((said, started), (['No'], []), 'n in Needs you answers no and starts no chat')
    sessions = T.HELP.split('Sessions [2]')[1].split('Queue [3]')[0]
    check('  n        new chat' in sessions, 'the keys list names n under Sessions', sessions)
    check('  N ' not in sessions, 'and not N', sessions)


def test_side_pane_f112() -> None:
    """F112 (2): inside tmux, selecting a session row with a socket splits a tmux pane beside the TUI's pane
    running `attach NAME`; another session respawns it; a task row kills it. Focus moves into it with l / ^l.
    The TUI then draws only the panels, full width, and no message box."""
    tm = Tmux()
    p = page(tmux=tm, socket=lambda name: name in ('c1', 'c6', 's1'))
    with mock.patch.dict(os.environ, {'TMUX': '/tmp/tmux-1/default,1,0', 'TMUX_PANE': '%3'}), \
            mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']):
        p.key('1')
        eq(tm.calls, [], 'Status: no pane beside')
        p.key('2')
        split = tm.did('split-window')
        check(len(split) == 1 and split[0][-1] == '/x/run attach c1' and '-h' in split[0] and
              split[0][split[0].index('-t') + 1] == '%3', 'selecting c1 splits a pane beside the TUI\'s pane with '
              "'attach c1'", tm.calls)
        eq(p.side.pane, '%11', 'the pane id is kept')
        check(['set-option', '-w', '-t', '%3', '@agent_runner_tui', '%3'] in tm.calls and
              any(c[:3] == ['bind-key', '-n', 'C-f'] for c in tm.calls) and
              any(c[:3] == ['bind-key', '-n', 'C-h'] for c in tm.calls),
              'Ctrl-f and Ctrl-h are bound, for the TUI\'s window only (its window option)', tm.calls)
        win = drawn(p)
        check('session' not in win.lines()[1] and win.at('[2] Sessions')[0] > 0 and
              win.lines()[1].rstrip().endswith('┐') and len(win.lines()[1].rstrip()) == 120,
              'the TUI draws only the panels, full width', win.text())
        check('❯ message' not in win.text(), 'no message box', win.text())
        p.key('j')
        eq(tm.did('respawn-pane'), [['respawn-pane', '-k', '-t', '%11', '-c', str(U.S.ROOT), '/x/run attach c6']],
           "another session: respawn-pane -k with 'attach c6'")
        p.key('l')
        eq((tm.did('select-pane')[-1], p.main), (['select-pane', '-t', '%11'], False), 'l: focus into its pane')
        p.key('j')
        p.key('j')
        eq(p.sel()['name'], 's2', 's2 (no socket)')
        eq(tm.did('kill-pane'), [['kill-pane', '-t', '%11']], 'a session with no socket: the pane is killed')
        check('s2 has no terminal to show here' in drawn(p).text(), 'F141: it says so instead, no feed')
        p.key('k')
        eq(len(tm.did('split-window')), 2, 's1 (a socket): a pane again')
        p.key('3')
        eq(tm.did('kill-pane')[-1], ['kill-pane', '-t', '%12'], 'a task row kills that pane')
        eq(p.side.pane, '', 'none beside now')
        check(['unbind-key', '-n', 'C-f'] in tm.calls, 'the bindings go with it')
    shared = Tmux()  # another TUI bound the same window-gated keys: shared, kept while its window uses them
    shared_keys = lambda argv: (0, 'bind-key -T root C-f if-shell -F #{@agent_runner_tui} ...') \
        if argv[0] == 'list-keys' else (0, '%5') if argv[0] == 'list-windows' else shared(argv)  # noqa: E731
    s = T.SidePane(shared_keys)
    with mock.patch.dict(os.environ, {'TMUX_PANE': '%3'}), mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']):
        s.show('c1')
        s.close()
    check(not shared.did('bind-key') and not shared.did('unbind-key'), 'two TUIs: the second neither binds again '
          'nor unbinds while the other window still uses the keys', shared.calls)
    p2 = page(tmux=tm, socket=lambda name: True)
    with mock.patch.dict(os.environ, {'TMUX': '/tmp/tmux-1/default,1,0', 'TMUX_PANE': '%3'}), \
            mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']):
        p2.key('2')
        check(p2.side.pane, 'c1 beside')
        p2.side.gone()  # Ctrl-b d in it: its pane closed itself
        p2.sync()
        eq(p2.side.pane, '', 'a pane that closed itself stays closed')
        check('c1 is not shown beside.' in drawn(p2).text(), 'F141: it says so', drawn(p2).text())
        p2.key('l')
        n = len(tm.did('split-window'))
        p2.key('ENTER')
        eq((len(tm.did('split-window')), p2.side.name), (n + 1, 'c1'), 'F141: Enter shows it beside again')


def test_always_tmux_f141() -> None:
    """F141: outside tmux the TUI re-execs in the project's tmux session (a new window when that is up); no tmux:
    it refuses with the install line; Windows: it refuses with the run page link. Nothing draws a feed."""
    class Exec(Exception):
        pass
    tty = mock.Mock(isatty=lambda: True)
    execs, asked = [], []

    def exec_(file, argv, env):
        execs.append((file, argv, env))
        raise Exec

    def start(up: bool) -> None:
        def run(argv):
            asked.append(argv)
            return (0 if up else 1), ''
        with mock.patch.dict(os.environ, {T.PICKER_ENV: '1', T.PLACE_ENV: '{}'}), \
                mock.patch.dict(sys.modules, {'curses': mock.Mock()}), \
                mock.patch.object(T.plat, 'WINDOWS', False), mock.patch('shutil.which', lambda n: f'/usr/bin/{n}'), \
                mock.patch.object(sys, 'stdin', tty), mock.patch.object(sys, 'stdout', tty), \
                mock.patch('agent_runner.state.init', lambda *a: None), \
                mock.patch.object(S, 'ROOT', Path('/x/my.proj')), mock.patch.object(T, 'tmux_run', run), \
                mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']), mock.patch.object(os, 'execvpe', exec_):
            os.environ.pop('TMUX', None)
            for k in [k for k in os.environ if k.startswith('AGENT_RUNNER_') and k not in (T.PICKER_ENV, T.PLACE_ENV)]:
                os.environ.pop(k)
            try:
                T.main([])
                check(False, 'main went on without its exec')
            except Exec:
                pass
    start(False)
    file, argv, env = execs[-1]
    cmd = ['env', f'{T.PLACE_ENV}={{}}', '/x/run', 'ui']
    root = str(Path('/x/my.proj'))
    eq((file, argv), ('tmux', ['tmux', 'new-session', '-A', '-s', 'my_proj', '-c', root, *cmd]),
       "no session yet: new-session -A with the project's name")
    check(T.PICKER_ENV not in env and T.PLACE_ENV not in env, 'the tmux server keeps neither for later windows')
    start(True)
    eq(execs[-1][1], ['tmux', 'new-window', '-t', '=my_proj:', '-c', root, *cmd, ';', 'attach-session', '-t',
                      '=my_proj'], 'the session is up: a new window in it, then attached')
    eq(asked, [['has-session', '-t', '=my_proj']] * 2, 'the exact session is looked for')

    def refused(**patches):
        err = io.StringIO()
        with mock.patch.object(T.plat, 'WINDOWS', patches['windows']), mock.patch('shutil.which', lambda n: None), \
                mock.patch('agent_runner.state.init', lambda *a: None), \
                mock.patch('agent_runner.web.page_line', lambda: patches.get('line', '')), \
                mock.patch.object(os, 'execvpe', exec_), contextlib.redirect_stderr(err):
            return T.main([]), err.getvalue()
    n = len(execs)
    rc, said = refused(windows=False)
    check(rc and 'sudo pacman -S tmux' in said and 'brew install tmux' in said, 'no tmux: the install line', said)
    rc, said = refused(windows=True, line='run page: http://127.0.0.1:8770/?t=x')
    check(rc and 'http://127.0.0.1:8770/?t=x' in said and 'Windows' in said, 'Windows: the run page link', said)
    rc, said = refused(windows=True)
    check(rc and 'start the run first' in said, 'Windows with no run up: it says to start one', said)
    eq(len(execs), n, 'a refusal execs nothing')
    with mock.patch.object(U, 'feed', lambda *a: check(False, 'a feed was read')):
        p = page(socket=lambda name: name == 'c1')
        p.key('2')
        for p.cur[2] in (0, 1):
            txt = drawn(p).text()
            check('❯' not in txt and '⎿' not in txt, f'{p.sel()["name"]}: no feed in the right pane', txt)
    check('steps' not in T.HELP and 'outside tmux' not in T.HELP, 'HELP lost the feed and the fallback', T.HELP)


def test_diff_key_f127() -> None:
    """F127: inside tmux a slot's session is the pane beside, so h/l never reach its diff tab: g on s1 kills the
    pane and draws the diff; g again brings the pane back. HELP lists g."""
    tm = Tmux()
    p = page(tmux=tm, socket=lambda name: True)
    with mock.patch.dict(os.environ, {'TMUX': '/tmp/tmux-1/default,1,0', 'TMUX_PANE': '%3'}), \
            mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']):
        p.key('2')
        while p.sel().get('name') != 's1':
            p.key('j')
        eq(p.side.name, 's1', "s1's session in the pane beside")
        pane = p.side.pane
        check(('g', 'diff') in p.hint_keys(), 'the bottom line offers g diff', p.hint_keys())
        p.key('g')
        eq((tm.did('kill-pane')[-1:], p.side.pane, p.tab()[0]), ([['kill-pane', '-t', pane]], '', 'diff'),
           'g: the pane is killed, the diff tab is on')
        txt = drawn(p).text()
        check('+new line' in txt and '-old line' in txt, 'the diff is drawn', txt)
        check(('g', 'session') in p.hint_keys(), 'the bottom line offers g session', p.hint_keys())
        n = len(tm.did('split-window'))
        p.key('g')
        eq((len(tm.did('split-window')), p.side.name, p.tab()[0]), (n + 1, 's1', 'session'),
           'g again: the pane comes back with s1')
        check(not tm.did('select-pane') or tm.did('select-pane')[-1] != ['select-pane', '-t', p.side.pane],
              'focus stays on the TUI', tm.calls)
        p.cur[2] = 0
        p.key('g')
        check(p.tab()[0] == 'session' and 'g shows' in p.msg, 'g on c1 (no diff): a message only', p.msg)
    check(any(l.strip().startswith('g ') for l in T.HELP.splitlines()), 'HELP lists g')


def test_full_screen_f112() -> None:
    """F112 Ctrl-f: in tmux the panes are laid out again (the session pane above the TUI's pane cut to its bottom
    bar, a `ui --bar` pane for the top bar above it), and back; with no session pane beside the main pane takes the
    width between both bars."""
    tm = Tmux()
    p = page(tmux=tm, socket=lambda name: True)
    with mock.patch.dict(os.environ, {'TMUX': '/tmp/tmux-1/default,1,0', 'TMUX_PANE': '%3'}), \
            mock.patch.object(U, 'runner_cmd', lambda: ['/x/run']):
        p.key('2')
        n = len(tm.calls)
        p.key('\x06')
        did = tm.calls[n:]
        eq(did[0], ['join-pane', '-d', '-v', '-b', '-s', '%11', '-t', '%3'], 'Ctrl-f: the session pane above the '
           "TUI's pane")
        check(did[1][0] == 'split-window' and did[1][-1] == '/x/run ui --bar' and '-b' in did[1] and
              did[1][did[1].index('-l') + 1] == '1', 'a one-row top bar pane above it runs ui --bar', did)
        check(['resize-pane', '-t', '%3', '-y', '1'] in did, "the TUI's pane cut to its bottom bar", did)
        eq(p.side.full, True, 'full-screen')
        win = drawn(p, 1, 120)
        check(win.lines()[0].startswith(' SESSIONS ') and '1-5' in win.lines()[0], 'the TUI\'s one-row pane: the '
              'bottom bar', win.text())
        win = drawn(p)
        check(win.lines()[-1].startswith(' SESSIONS ') and '[2] Sessions' not in win.text(),
              'the bottom bar is still drawn, the panels are not', win.text())
        bar = page()
        bar.bar_only = True
        check(drawn(bar, 1, 120).lines()[0].startswith('proj 0 all runs'), 'ui --bar draws the top bar')
        n = len(tm.calls)
        p.key('\x06')
        did = tm.calls[n:]
        eq(did[:2], [['kill-pane', '-t', '%12'], ['join-pane', '-d', '-h', '-l', '64%', '-s', '%11', '-t', '%3']],
           'Ctrl-f again: the bar pane killed, the session joined back beside')
        eq(p.side.full, False, 'side by side again')
        check('[2] Sessions' in drawn(p).text(), 'the panels are back')
        p.key('\x06')
        p.key('3')
        check(['kill-pane', '-t', '%13'] in tm.calls and p.side.pane == '' and not p.side.full,
              'full-screen, a task row: both panes go', tm.calls[-8:])
    q = page()
    q.key('2')
    q.key('j')
    q.key('\x06')
    win = drawn(q)
    eq((q.full, q.main), (True, True), 'no pane beside, Ctrl-f: the session tab full-screen')
    check(win.lines()[0].startswith('proj 0 all runs') and win.lines()[-1].startswith(' SESSION ') and
          '[2] Sessions' not in win.text() and 'c6 has no terminal' in win.text(),
          'both bars drawn, the session tab between them, no panels', win.text())
    q.key('\x06')
    check(not q.full and '[2] Sessions' in drawn(q).text(), 'Ctrl-f again: side by side')
    q.key('3')
    q.key('\x06')
    eq(q.full, False, 'Ctrl-f on a task row: nothing to full-screen')


def test_actions() -> None:
    repo = Path(tempfile.mkdtemp()) / 'proj'  # an answer reads the plan for the item's title: an empty one
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    ran, sent, opened, calls = [], [], [], []
    ok = lambda out: {'ok': True, 'code': 0, 'out': out, 'argv': []}  # noqa: E731
    p = page(opener=lambda url: (opened.append(url), {'ok': True, 'out': f'opened {url}'})[1])
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok: ' + ' '.join(argv)))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), ok('sent to c1'))[1]]), \
            mock.patch.object(U, 'need_label', lambda tid: {n['id']: n['label'] for n in SNAP['needs']}.get(tid, '')), \
            mock.patch.object(U, 'send', lambda name, text: (calls.append(('send', name, text)), ok('sent'))[1]), \
            mock.patch.object(U, 'quick_ask', lambda key: (calls.append(('quick_ask', key)), ok('asked'))[1]), \
            mock.patch.object(U, 'new_control', lambda ask='', wait=True: (calls.append(('new_control', wait)),
                                                                {**ok('started c7'), 'link': '', 'name': 'c7'})[1]), \
            mock.patch.object(U, 'open_session', lambda slot: (calls.append(('open_session', slot)),
                                                               ok(f'https://claude.ai/code/{slot}'))[1]):
        p.key('3')
        p.key('j')
        p.key('p')
        p.key('H')
        p.key('D')
        p.key('E')
        for c in 'also cover openmx':
            p.key(c)
        p.key('ENTER')
        eq((p.typing, p.main), ('', False), 'a chat edit sent: back to the panels')
        p.key('n')
        eq((p.sel(), p.tab()[0], p.typing), (T.NEW_TASK, 'chat edit', 'edit:+'), 'n: chat edit for a new task')
        for c in 'show usage too':
            p.key(c)
        p.key('ENTER')
        p.cur[3] = 0
        p.key('J')
        p.key('4')
        p.key('ENTER')
        win = drawn(p)
        check('[y Yes] [n No] [L later]' in win.text(), 'a yes/no ask: y yes, n no, L later buttons', win.text())
        check('❯ or your own reply' in win.text(), 'and the free reply box', win.text())
        p.key('y')
        eq(p.main, False, 'an answer sent: back to the panels')
        eq([n['id'] for n in p.snap['needs']], ['F4', 'D7'], 'B138: D3 answered is off Needs you at once')
        p.snap = SNAP  # the rest of this test walks the full list
        p.key('j')
        p.key('ENTER')
        win = drawn(p)
        check('[a Option A] [b Option B] [c A + B · recommended]' in win.text(), "a pick: the concept's options as "
              'a b c', win.text())
        p.key('c')
        eq([n['id'] for n in p.snap['needs']], ['D3', 'D7'], 'B149: F4 approved is off Needs you at once')
        p.snap = SNAP
        p.key('j')
        p.key('ENTER')
        p.key('i')
        for c in 'port 8770':
            p.key(c)
        p.key('ENTER')
        eq([n['id'] for n in p.snap['needs'] if n['id'] == 'D7'], [], 'F181a: the DECIDE answered by words is gone at once')
        p.snap = SNAP
        p.key('j')
        p.key('j')
        p.key('L')
        p.key('5')
        p.key('ENTER')
        win = drawn(p)
        check('┌─ A + B · recommended' in win.text(), 'the preview: each option in a box', win.text())
        eq(colour_at(win, '┌─ A + B'), 'yellow', 'the recommended option is selected first (yellow)')
        p.key('k')
        eq(colour_at(drawn(p), '┌─ Option B'), 'yellow', 'k selects the option above')
        p.key('ENTER')
        p.key('i')
        for c in 'smaller':
            p.key(c)
        p.key('ENTER')
        p.key('O')
        p.key('1')
        p.key('ENTER')
        p.key('s')
        p.key('u')
        p.key('R')
        p.key('ENTER')
        p.key('f')
        p.key('2')
        p.cur[2] = 2
        p.key('o')
        p.key('ENTER')
        p.key('i')
        eq(p.typing, '', 'F112: nothing to type into on the session tab')
        p.key('ESC')
        p.cur[2] = 0
        p.key('o')
        c7 = {'name': 'c7', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
              'link': 'https://claude.ai/code/x', 'terminal': ''}
        p.get_snap = lambda: dict(SNAP, sessions=SNAP['sessions'][:2] + [c7] + SNAP['sessions'][2:]) \
            if ('new_control', False) in calls else SNAP
        p.key('n')
        for _ in range(100):
            if 'r' in (p.starting or {}):
                break
            T.time.sleep(0.02)
        p.poll_new_chat()
        eq(p.sel()['name'], 'c7', 'n selects the new control session')
        eq((p.msg, p.main, p.tab()[0], p.typing), ('new control session c7: https://claude.ai/code/x', False,
                                                   'session', ''),
           'n: the new control session selected on its session tab, its link said; no typing')
        p.key('ESC')
    eq(ran, [['plan', 'edit', 'B2', '--pri', 'high'],
             ['plan', 'drop', 'B2', 'dropped from agent-runner ui'],
             ['plan', 'move', 'Q1', 'after', 'B2'],
             ['plan', 'confirm', 'D3', 'Yes'],
             ['plan', 'approve', 'F4', 'A + B · recommended'],
             ['plan', 'confirm', 'D7', 'port 8770'],
             ['plan', 'shelve', 'D7'],
             ['plan', 'add', 'V'],
             ['plan', 'add', 'V', '--now']], 'p, D, J, L and the release buttons run their plan commands')
    eq(sent, ['change B2: also cover openmx', 'new task: show usage too',
              'concept K5 ("Lazy layout"): go with Option B',
              'concept K5 ("Lazy layout"): smaller'],
       'chat edits, the concept pick and its change go to a new chat')
    eq(calls, [('new_control', True), ('quick_ask', 'since'), ('quick_ask', 'usage'), ('open_session', 's1'),
               ('new_control', False)],
       'H starts a new control session (B139); o, the quick asks and n run F74\'s actions (n without waiting)')
    eq(opened, ['https://claude.ai/artifact/k5', 'https://claude.ai/code/s1', 'https://claude.ai/code/session_c1'],
       'O and o open the browser')


def test_session_tab_b125() -> None:
    """B125: y copies the link with OSC 52; o over ssh opens no browser here: it copies and shows the link to
    Cmd-click (OSC 8). F112: the session tab has no message box."""
    import base64
    wrote, popen = [], []
    ok = lambda out: {'ok': True, 'code': 0, 'out': out, 'argv': []}  # noqa: E731
    c7 = {'name': 'c7', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
          'link': 'https://claude.ai/code/c7', 'terminal': ''}
    p = page(dict(SNAP, sessions=SNAP['sessions'] + [c7]), out=wrote.append)
    p.opener = lambda url: T.open_url(url, p.out)
    with mock.patch.object(U, 'open_session', lambda slot: ok(f'https://claude.ai/code/{slot}')), \
            mock.patch.object(T.sp, 'Popen', lambda *a, **k: popen.append(a)), \
            mock.patch.dict(T.os.environ, {'SSH_CONNECTION': '10.0.0.2 5000 10.0.0.1 22'}), \
            mock.patch.object(T.os, 'startfile', lambda url: popen.append(url), create=True):
        p.key('2')
        p.cur[2] = 2
        eq((p.sel()['name'], p.tab()[0]), ('c7', 'session'), 'c7 on its session tab')
        win = drawn(p)
        check('❯ message c7' not in win.text(), 'F112: the session tab has no message box', win.text())
        check('[y copy link]' in win.text(), 'and a y copy link button', win.text())
        p.key('y')
        b64 = base64.b64encode(b'https://claude.ai/code/c7').decode()
        check(any(f'\x1b]52;c;{b64}\x07' in w for w in wrote), 'y writes an OSC 52 sequence with the link', wrote)
        eq(p.msg, 'link copied', 'y says the link is copied')
        wrote.clear()
        p.key('o')
        eq(popen, [], 'o over ssh runs no xdg-open (nor any other program)')
        check(any('\x1b]52;c;' in w for w in wrote), 'o over ssh copies the link with OSC 52', wrote)
        eq((p.msg, p.msg_link), ('link copied, Cmd-click to open', 'https://claude.ai/code/c7'),
           'o over ssh says to Cmd-click the link')
        win = drawn(p)
        check('link copied, Cmd-click to open https://claude.ai/code/c7' in win.text(), 'the message line shows it',
              win.lines()[-1])
        seq = T.links_over(p.links)
        check(T.osc8('https://claude.ai/code/c7', 'https://claude.ai/code/c7') in seq, 'drawn as an OSC 8 link',
              repr(seq))
        p.cur[2] = [r.get('name') for r in p.items(2)].index('s1')  # a slot on a task: o and y work there too
        wrote.clear()
        p.key('y')
        check(any(base64.b64encode(b'https://claude.ai/code/s1').decode() in w for w in wrote),
              "y on a slot copies its session's link", wrote)
    with mock.patch.dict(T.os.environ, {'SSH_CONNECTION': '', 'SSH_TTY': ''}), \
            mock.patch.object(T.sys, 'platform', 'linux'), \
            mock.patch.object(T.sp, 'Popen', lambda argv, **k: popen.append(argv)):
        r = T.open_url('https://claude.ai/code/c7', wrote.append)
    eq((popen, r.get('link')), ([['xdg-open', 'https://claude.ai/code/c7']], None), 'locally o stays xdg-open')


def test_footer() -> None:
    """F76: the bottom line: the mode badge, this place's keys (yellow), a separator, then only 1-5 panel, c
    chat, ? keys (blue); never a key the window shows, never j/k or ^h/^l; keys and labels in other colours."""
    places = []
    for n in range(1, 6):
        for main in (False, True):
            for row in range(3):
                p = page()
                p.key(str(n))
                p.cur[n] = row
                if main:
                    p.key('l')  # F111: Enter on a new concept row types; l only focuses the main pane
                for t in range(len(p.tab()[1]) if main else 1):
                    places.append((n, main, row, t, p))
                    win = drawn(p)
                    segs = p.footer()
                    keys = [s for s, c in segs if c == 'hkey']
                    glob = [s for s, c in segs if c == 'gkey']
                    where = f'panel {n} row {row}{" " + p.tab()[0] if main else ""}'
                    eq(glob, [g for g in ('1-5', 'c', '?') if g not in p.window_keys],
                       f'{where}: the global keys, blue (c not where a pick\'s option c shows)')
                    check(not set(keys) & {'j', 'k', 'j/k', '^h', '^l', '1-5', 'c', '?', '[', ']', '[ ]'},
                          f'{where}: no j/k, ^h/^l, [ ] or global key among this place\'s', keys)
                    check(not set(keys) & p.window_keys, f'{where}: no key the window already shows', (keys, p.window_keys))
                    last = win.lines()[-1]
                    check(last.startswith(f' {p.mode()} ') and ' │ ' in last and last.rstrip().endswith('? keys'),
                          f'{where}: badge, keys, separator, globals', last)
                    eq(colour_at(win, f' {p.mode()} '), 'mode', f'{where}: the badge in the mode colour')
                    labels = {c for s, c in segs if s.startswith(' ') and s.strip() and s != ' · ' and s != ' │ '}
                    check(labels and not labels & {'hkey', 'gkey'}, f'{where}: labels not in a key colour', labels)
                    p.key('l')
    check(len(places) > 40, 'every panel, row and tab was looked at', len(places))
    p = page()
    p.key('3')
    check('J/K' in [s for s, c in p.footer()], 'the queue lists J/K reorder')
    p.key('e')
    drawn(p)
    eq([s for s, c in p.footer() if c in ('hkey', 'gkey')], ['Esc', 'Tab/⇧Tab', '⇧⏎'], 'typing: no global keys')
    eq(p.mode(), 'INSERT', 'typing: the badge says INSERT')
    p.key('ESC')
    drawn(p)
    keys = [s for s, c in p.footer() if c == 'hkey']
    check('^S' not in keys and 'D' not in keys and 't' not in keys, 'the direct edit shows ^S, D and its field '
          'keys on screen, so the bottom line does not', keys)
    eq(p.mode(), 'DIRECT EDIT', 'the badge names the tab')
    p = page()
    p.key('2')
    p.key('ENTER')
    drawn(p)
    check('o' not in p.footer() and 'Esc' in [s for s, c in p.footer()], "c1's chat: Esc", p.footer())
    narrow = page()
    narrow.key('3')
    drawn(narrow)
    short = narrow.footer(40)
    check(sum(len(t) for t, _ in short) <= 40 and [s for s, c in short if c == 'gkey'] == ['1-5', 'c', '?'],
          'too narrow: this place\'s last keys go, the globals stay', short)


def test_concept_page() -> None:
    page_ = U.concept_page(COPY)
    eq((page_['title'], page_['intro']), ('Lazy layout', ['Three ways to lay out the run page.']), 'title, intro')
    eq([(o['name'], o['rec']) for o in page_['options']],
       [('Option A', False), ('Option B', False), ('A + B · recommended', True)], 'the options: its headings')
    eq(page_['options'][0]['body'], ['One page the runner republishes.'], 'each with what follows it')
    styled = '<style>.t{}</style><h1>Live run page</h1><p>Four options.</p><div class="o"><div class="t">Option A' \
             '</div>The runner republishes.</div><div class="o r"><div class="t">A + C · recommended</div>Hub.</div>'
    eq([o['name'] for o in U.concept_page(styled)['options']], ['Option A', 'A + C · recommended'],
       "the run page's own style: an option's title in a .t element")
    eq(U.concept_page('')['options'], [], 'no page: no options')
    p = page()
    p.key('5')
    p.key('ENTER')
    eq(p.option(p.sel()), 2, 'the recommended option is selected first')
    p.key('j')
    eq(p.option(p.sel()), 2, 'j stops at the last option')
    p.key('k')
    p.key('k')
    p.key('k')
    eq(p.option(p.sel()), 0, 'k stops at the first')


def test_concept_chat() -> None:
    """F86: N on a concept starts a new control session (control --new --ask) whose first message names the
    concept, its page link and local copy, and says to follow guide concepts; the keys list and footer name N."""
    from unittest import mock
    from agent_runner import status
    ran = []
    p = page()
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'c7 is open: https://claude.ai/code/x\n'))[1]]), \
            mock.patch.object(status, 'waiting_ok', lambda: [('CONCEPT', 'F4', 'K5', '', 'https://claude.ai/artifact/k5', 'Lazy layout', False)]), \
            mock.patch.object(U, 'concept_copy', lambda k: f'/notes/concepts/{k}.html'):
        p.key('5')
        check(('N', 'chat about it') in p.hint_keys(), 'the Concepts footer names N', p.hint_keys())
        p.key('N')
    eq(ran[-1][:3], ['control', '--new', '--ask'], 'N: a new control session with a first message')
    ask = ran[-1][3]
    for want in ("concept K5 'Lazy layout'", 'https://claude.ai/artifact/k5', '/notes/concepts/K5.html',
                 'guide concepts'):
        check(want in ask, f'the first message says {want!r}', ask)
    eq(p.msg, 'new control session about K5: https://claude.ai/code/x', 'its link in the message line')
    check('N        chat about it' in T.HELP, 'the keys list names N under Concepts')


def test_new_concept() -> None:
    """F87: Concepts ends with a '+ new concept' row; n on Concepts opens its box, and Enter queues what was typed
    as a K task (plan add K TEXT), the result on the message line; the keys list and footer name n."""
    ran = []
    p = page()
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'added K9 dark mode\n'))[1]]):
        p.key('5')
        rows = p.items(5)
        eq((rows[-1].get('new'), len(rows)), (True, 2), "the concept, then the '+ new concept' row")
        check('+ new concept n' in drawn(p, 40, 100).text(), "the row reads '+ new concept n'")
        check(('n', 'new concept') in p.hint_keys(), 'the Concepts footer names n', p.hint_keys())
        p.key('n')
        eq((p.sel().get('new'), p.tab()[0], p.typing), (True, 'new concept', 'concept:+'),
           'n: the new concept row, its box typing')
        for c in 'dark mode':
            p.key(c)
        p.key('ENTER')
    eq(ran, [['plan', 'add', 'K', 'dark mode']], 'Enter: plan add K with the words typed')
    eq((p.msg, p.msg_ok, p.typing), ('added K9 dark mode', True, ''), 'it says it is queued; the box closes')
    check('n        new concept' in T.HELP, 'the keys list names n under Concepts')


def test_enter_on_concept() -> None:
    """F111: Enter from the panels on the '+ new concept' row lands in its box at once (typing 'concept:+');
    Enter on a concept (its 'preview' tab) only focuses the main pane, where Enter is 'go with it'."""
    p = page()
    p.key('5')
    eq(p.tab()[0], 'preview', 'the first concept opens on its preview tab')
    p.key('ENTER')
    eq((p.main, p.typing), (True, ''), 'Enter on a preview item: the main pane, not typing')
    p.key('ESC')
    p.key('DOWN')
    eq((p.sel().get('new'), p.tab()[0], p.main), (True, 'new concept', False), "the '+ new concept' row")
    check(('⏎', 'type') in p.hint_keys(), 'the footer says Enter types', p.hint_keys())
    p.key('ENTER')
    eq((p.main, p.typing), (True, 'concept:+'), 'Enter on a new concept item: typing in its box')


def test_concept_as_need_f197b2() -> None:
    """F197b2: a Concepts row shows its Needs you item's badge word, label and answers; Needs you the same badge."""
    snap = dict(SNAP, concepts=[dict(SNAP['concepts'][0], news_words='Updated')])
    p = page(snap)
    row = ''.join(t for t, _ in p.row(5, p.items(5)[0]))
    check(row.startswith('Updated ◆ Lazy layout') and 'CONCEPT 1d' in row, 'the concept row', row)
    need = ''.join(t for t, _ in p.row(4, snap['needs'][1]))
    check(need.startswith('Updated F4'), 'the Needs you row has the same badge', need)
    p.key('5')
    lines, _ = p.preview_pane(p.sel(), 80)
    head = ''.join(t for t, _ in lines[1])
    check('CONCEPT' in head and 'Option A · Option B · A + B · recommended' in head, 'its answers', head)


def test_escape_tail() -> None:
    def more_of(s):
        it = iter(s)
        return lambda: next(it, '')
    eq(T.escape_tail('\x1b', more_of('')), ['ESC'], 'a lone Esc')
    eq(T.escape_tail('\x1b', more_of('[13;2u')), ['S-ENTER'], "kitty's Shift+Enter")
    eq(T.escape_tail('\x1b', more_of('[27;2;13~')), ['S-ENTER'], "xterm's Shift+Enter")
    eq(T.escape_tail('\x1b', more_of('\r')), ['S-ENTER'], 'Alt+Enter')
    eq(T.escape_tail('\x1b', more_of('2')), ['ESC', '2'], 'Esc, then a fast key: both, none lost')
    eq(T.escape_tail('\x1b', more_of('[1;5P')), [], 'another sequence: nothing')
    eq(T.escape_tail('j', more_of('')), ['j'], 'any other key as it is')


class FakeCurses:
    """A stub curses module: enough for the colours and the key names."""
    A_BOLD, A_REVERSE, COLORS, KEY_UP = 1 << 16, 1 << 17, 256, 259

    def __init__(self):
        self.pairs = {}

    def has_colors(self):
        return True

    def start_color(self):
        pass

    def init_pair(self, n, fg, bg):
        self.pairs[n] = (fg, bg)

    def use_default_colors(self):
        self.defaults = True

    def color_pair(self, n):
        return n << 8

    def keyname(self, ch):
        return b'KEY_UP' if ch == self.KEY_UP else b'x'


def test_colours() -> None:
    c = FakeCurses()
    attrs = T.curses_attrs(c)
    pair = lambda name: c.pairs[(attrs[name] & 0xff00) >> 8]  # noqa: E731
    eq(pair('red'), (203, 16), 'the accent: the 256-colour red nearest #ef4444, on black')
    eq(pair('fg')[1], 16, 'text sits on the black ground')
    eq(pair('mode'), (16, 203), 'the mode tag: black on red')
    eq(pair('hkey')[0], 214, "this place's keys: yellow (#f59e0b)")
    eq(pair('gkey')[0], 75, 'the global keys: blue (#60a5fa)')
    eq(pair('pkey')[0], 203, "the primary button's key: the accent")
    check(attrs['hkey'] & c.A_BOLD and attrs['gkey'] & c.A_BOLD, 'keys are bold')
    check(len({pair(n)[0] for n in ('hkey', 'gkey', 'pkey')} & {pair('fg')[0], pair('dim')[0]}) == 0,
          'no key is in a label colour')
    c.COLORS = 8
    eq(c.pairs[(T.curses_attrs(c)['red'] & 0xff00) >> 8], (1, 0), '8 colours: plain red on black')
    eq((T.key_name(c, c.KEY_UP), T.key_name(c, 'j')), ('UP', 'j'), 'curses keys get their names')


def test_row_ground_and_fill() -> None:
    """B112: an unfocused panel's selected row carries the row background in every cell, a full redraw writes
    every cell."""
    c = FakeCurses()
    attrs = T.curses_attrs(c)
    bg = lambda a: c.pairs[(a & 0xff00) >> 8][1]  # noqa: E731 - the background of a cell's colour pair
    p, win = T.RunPage(SNAP, get_snap=lambda: SNAP, attrs=attrs), Win(30, 100)
    p.key('3')  # Sessions is unfocused; its selected row is c1
    p.draw(win)
    row = next(y for y, l in enumerate(win.lines()) if ' c1 control session' in l[:36])
    cells = range(1, 35)  # inside the box's edges, 36 wide
    eq([x for x in cells if bg(win.colour[row][x]) != 235], [], 'every cell of the unfocused selected row is '
       'on #262626 (235)')
    check(c.pairs[(win.colour[row][2] & 0xff00) >> 8][0] == 203, 'its id keeps its colour (red c1)')
    p.key('2')
    p.draw(win)
    row = next(y for y, l in enumerate(win.lines()) if ' c1 control session' in l[:36])
    eq([x for x in cells if bg(win.colour[row][x]) != 88], [], 'focused, every cell is on the focused row\'s red')

    class OldScreen(Win):  # erase that leaves the earlier screen: only what draw writes covers it
        def erase(self):
            if not hasattr(self, 'grid'):
                self.grid = [['\0'] * self.w for _ in range(self.h)]
                self.colour = [[0] * self.w for _ in range(self.h)]
    old = OldScreen(30, 100)
    p.draw(old)
    eq(sum(r.count('\0') for r in old.lines()), 0, 'a full redraw writes every cell')
    eq([(y, x) for y in range(30) for x in range(100) if not old.colour[y][x]], [],
       'and every cell gets a theme colour (the black ground)')
    eq([r['name'] for r in T.session_rows(dict(SNAP, up=False, slots=None))], ['c1', 'c6', 's1', 's2'],
       'no run up: no idle slots are made up')


def test_start_run_f402c2() -> None:
    """With no run up: Status names T and says Not running, with no slot keys; starting, failing and coming up show
    on the panel and the view stays; a task is added and a chat started."""
    off = dict(SNAP, up=False, slots=0, run={}, status=['no run is up'] + SNAP['status'][1:],
               sessions=[s for s in SNAP['sessions'] if s['name'].startswith('c')], shown=['start'], card=['start'])
    off['queue'] = [{**off['queue'][8], 'state': 'tool', 'tool_wait': 'waits for the run to start', 'waits_run': True}]
    now = [off]
    ran: list = []
    go, answer = threading.Event(), [(1, 'the gate is red\nsecond line')]

    def run(argv):
        ran.append(argv)
        go.wait(10)
        return answer[0]

    def fresh() -> T.RunPage:
        p = page(off)
        p.get_snap = lambda: now[0]
        return p

    def ended(p) -> None:
        go.set()
        p.run_start['thread'].join(10)
        p.poll_run_start()
        go.clear()

    with mock.patch.object(U, 'RUN', [run]):
        p = fresh()
        text = drawn(p).text()
        check('Not running · T start' in text, 'Status says Not running and names T', text)
        foot = ''.join(t for t, _ in p.footer())
        check(not any(w in foot for w in ('slots', 'pause', 'stop')), 'no slot, pause or stop keys', foot)
        eq([k for k, _ in p.hint_keys()], ['⏎', 'T', 'R'], 'its keys')
        p.set_tab('controls')
        text = drawn(p).text()
        check('[T start the run]' in text and 'No task starts until the run does.' in text and 'slot' not in text.split('Sessions')[0]
              and '[P pause]' not in text and '[S stop' not in text and 'C cancels it' not in text, 'the controls tab has Start alone', text)
        for k in '+-=PGSXUZBVY':
            p.key(k)
            check('T starts the run' in p.msg and not (ran or p.typing or p.confirm), f'{k} does nothing but say so', p.msg)
        p.key('T')
        text = drawn(p).text()
        check('Starting the run…' in text and '[T start' not in text and 'Not running' not in text, 'T: starting', text)
        p.key('T')
        check('starting already' in p.msg and ran == [[]], 'T again starts nothing more', (p.msg, ran))
        ended(p)
        win = drawn(p)
        check('Not started: the gate is red' in win.text() and 'second line' in win.text() and '[T start the run]' in win.text(),
              'a failure: why, on the panel, and T again', win.text())
        check(not p.msg_ok and 'the gate is red' in p.msg and p.tab()[0] == 'controls' and p.main, 'the view stays', p.msg)
        p.main, p.msg = False, ''
        text = drawn(p).text()
        check('Not started: the gate is red' in text and 'T start' in text, 'the panel alone says it, T in its keys', text)

        answer[0] = (0, 'started 3 slots')
        p.set_tab('controls')
        p.cur[2] = 2  # new chat, after c1 and c6
        eq(p.sel(2), T.NEW_CHAT, 'Sessions is on new chat')
        p.key('T')
        eq((p.run_failed, p.off_said()), ('', 'Starting the run…'), 'a retry clears the failure')
        now[0] = SNAP
        ended(p)
        eq((p.run_start, p.msg, p.panel, p.main, p.tab()[0]), (None, 'the run is up', 1, True, 'controls'),
           'up: the panel, focus and tab stay')
        eq(p.sel(2), T.NEW_CHAT, 'and each selection, though slot rows came in above it')
        check('[P pause]' in drawn(p).text(), 'the slot controls are back')

        now[0] = off
        p = fresh()
        p.key('T')
        ended(p)
        check(p.run_start is not None, 'started but not up yet: still starting')
        with mock.patch.object(T, 'RUN_START_WAIT', -1):
            p = fresh()
            p.key('T')
            ended(p)
            eq((p.run_start, p.off_said()), (None, 'Not started: it started, but no run is up: the log says why'), 'not up in time: it says so')

        go.set()
        ran.clear()
        answer[0] = (0, 'added B10')
        p = fresh()
        p.key('3')
        check('waits for the run to start' in drawn(p, w=140).text(), 'a queued task says it waits for the run to start',
              drawn(p, w=140).text())
        p.cur[3] = len(p.items(3)) - 1
        p.key('e')
        for c in 'Fix it':
            p.key(c)
        p.key('^S')
        eq((ran[0][:2], ran[0][3], p.msg_ok), (['plan', 'add'], 'Fix it', True), 'a task is added with no run up')
        sent: list = []
        with mock.patch.object(U, 'SEND', [lambda t: (sent.append(t), {'ok': True, 'code': 0, 'out': 'sent', 'argv': []})[1]]):
            p.cur[3] = 0
            p.key('E')
            for c in 'hello':
                p.key(c)
            p.key('ENTER')
        eq(sent, ['change Q9: hello'], 'a message goes to a new chat with no run up')
        p = fresh()
        p.socket = lambda name: name == 'c1'
        p.key('2')
        with mock.patch.object(T, 'in_tmux', lambda: True):
            eq((p.sel()['name'], p.want_side()), ('c1', 'c1'), 'an open chat still shows as itself, to type in')
    with mock.patch.object(U.sp, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as sp_run, \
            mock.patch.object(U.S, 'ROOT', Path('.')), mock.patch.object(U, 'runner_cmd', lambda: ['runner']):
        U._run([])
    eq(sp_run.call_args.kwargs.get('stdin'), U.sp.DEVNULL, "a start asks nothing on the TUI's terminal")


def test_reorder() -> None:
    """F70: Shift+J on the second queue row runs plan move ID after <third>, and the cursor moves with it;
    Shift+K moves it back up; the first and last task go no further."""
    ran, snap = [], dict(SNAP)

    def run(argv):
        ran.append(argv)
        q = [t for t in snap['queue'] if t['id'] != argv[2]]
        moved = next(t for t in snap['queue'] if t['id'] == argv[2])
        at = [t['id'] for t in q].index(argv[4]) + (1 if argv[3] == 'after' else 0)
        snap['queue'] = q[:at] + [moved] + q[at:]
        return 0, f'moved {argv[2]} {argv[3]} {argv[4]}'
    with mock.patch.object(U, 'RUN', [run]):
        p = T.RunPage(snap, get_snap=lambda: dict(snap), attrs=ATTRS)
        p.key('3')
        p.key('j')
        p.key('J')
        eq(ran, [['plan', 'move', 'B2', 'after', 'C3']], 'J on the second row: plan move B2 after C3')
        eq((p.cur[3], p.sel()['id']), (2, 'B2'), 'the cursor moves with it')
        p.key('K')
        eq(ran[-1], ['plan', 'move', 'B2', 'before', 'C3'], 'K: plan move B2 before C3')
        eq((p.cur[3], p.sel()['id']), (1, 'B2'), 'and the cursor follows it up')
        p.key('k')
        p.key('K')
        eq((len(ran), p.cur[3]), (2, 0), 'K on the first task runs nothing')
        p.key('j')
    with mock.patch.object(U, 'RUN', [lambda argv: (3, 'no such task')]):
        p.key('J')
        eq((p.cur[3], p.msg_ok), (1, False), 'a refused move leaves the cursor where it was, the reason in red')


def test_parked() -> None:
    """B123: a state 'parked' queue row (level later, from ui_model since B118) gets the tag 'parked' (dim),
    never 'ready'; U unparks it (`plan edit ID --pri normal`), and J/K and p do nothing on it."""
    p = page()
    eq(p.queue_tag({'id': 'F83', 'title': 'Big later work', 'state': 'parked'}), ('parked', 'dim'),
       "a parked row: 'parked', dim")
    eq(p.queue_tag({'id': 'F84', 'title': 'Big later work', 'state': 'parked', 'pri': 'later'}),
       ('parked', 'dim'), 'never ready')
    ran, snap = [], dict(SNAP)
    snap['queue'] = list(SNAP['queue']) + [{'id': 'F83', 'title': 'Parked big work', 'state': 'parked',
                                            'pri': 'later'}]
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'queue_row', lambda tid: next((q for q in snap['queue'] if q['id'] == tid), None)):
        p = T.RunPage(snap, get_snap=lambda: dict(snap), attrs=ATTRS)
        p.key('3')
        p.cur[3] = len(snap['queue']) - 1
        eq(p.sel()['id'], 'F83', 'the parked row selected')
        check(' parked' in drawn(p, 32, 100).text(), "the open parked row shows its 'parked' tag")
        p.key('k')  # off the selected row's ground, so the tag draws in its own colour
        win = drawn(p, 40, 100)
        check(' parked' in win.text() and colour_at(win, ' parked', 1) == 'dim', "unfocused, the tag is dim",
              win.text())
        row = next(l for l in win.lines() if 'F83' in l)[:36].rstrip(' │')
        check(row.endswith('parked') and 'ready' not in row, "the drawn row: 'parked', never 'ready'", row)
        p.cur[3] = len(snap['queue']) - 1
        check(('U', 'unpark') in p.hint_keys() and not any(k == 'J/K' for k, _ in p.hint_keys()),
              'the hints name U unpark, not J/K', p.hint_keys())
        p.key('J')
        p.key('K')
        p.key('p')
        eq(ran, [], 'J/K and p run nothing on a parked row')
        p.key('U')
        eq(ran, [['plan', 'edit', 'F83', '--pri', 'normal']], 'U: plan edit F83 --pri normal')
        p.cur[3] = 0
        p.key('U')
        eq(len(ran), 1, 'U on a task that is not parked runs nothing')


def test_shelved_f184() -> None:
    """F184: the shelved tasks are the queue panel's last rows, not in its count; U is Bring back, d asks first,
    and e, p, J/K do nothing on one."""
    row = {'id': 'D8', 'title': 'Look at it on the laptop', 'state': 'shelved', 'ask': 'Run it there - reply yes/no'}
    snap, ran = dict(SNAP, shelved=[row]), []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: row if (where, tid) == ('shelved', 'D8') else None):
        p = T.RunPage(snap, get_snap=lambda: dict(snap), attrs=ATTRS)
        p.key('3')
        check(f'1 of {len(SNAP["queue"]) + 1}' in drawn(p, 40, 100).text(), 'the queue count leaves it out')
        p.key('n')
        check(p.sel().get('new'), 'n is still the new task row')
        p.key('ESC')
        p.key('ESC')
        p.cur[3] = len(p.items(3)) - 1
        eq(p.sel()['id'], 'D8', 'the last row')
        eq(p.queue_tag(row), ('shelved', 'dim'), 'its tag')
        text = drawn(p, 40, 120).text()
        check('1 of 1 shelved' in text and 'Run it there' in text, 'its place and what it waits for', text)
        check(('U', 'bring back') in p.hint_keys() and not any(k in ('J/K', 'e') for k, _ in p.hint_keys()), 'the hints', p.hint_keys())
        for k in ('e', 'p', 'H', 'J', 'K'):
            p.key(k)
        eq((ran, p.tab()[0]), ([], 'info'), 'e, p, H, J and K do nothing')
        p.key('d')
        eq((ran, 'again: yes' in p.msg), ([], True), 'd asks first')
        p.key('d')
        p.key('U')
        eq(ran, [['plan', 'drop', 'D8', 'dropped from Parked'], ['plan', 'unshelve', 'D8']], 'drop, then bring back')


OMARCHY_SAMPLE = '''mode = "dark"
accent = "#89b4fa"
selection = "#45475a"
background = "#1e1e2e"
foreground = "#cdd6f4"
red = "#f38ba8"
green = "#a6e3a1"
bright_blue = "#74c7ec"
color4 = "#89b4fa"
'''


def test_themes() -> None:
    """F69: the page draws in each [ui] theme; omarchy reads a colors.toml, ryha when it is missing; terminal
    draws in the terminal's own colours and background."""
    from agent_runner import theme as TH
    pair = lambda c, a: c.pairs[(a & 0xff00) >> 8]  # noqa: E731
    for name in TH.NAMES:
        c = FakeCurses()
        attrs = T.curses_attrs(c, name)
        p, win = T.RunPage(SNAP, get_snap=lambda: SNAP, attrs=attrs), Win(30, 100)
        p.draw(win)
        check('[3] Queue' in win.text() and '? keys' in win.text(), f'{name}: the page draws')
        check(all(f'{g}:{n}' in attrs for g in ('sel', 'cur') for n in T.COLOURS), f'{name}: every row pair')
        eq([n for n in T.COLOURS for g in ('sel', 'cur') if pair(c, attrs[f'{g}:{n}'])[0] == pair(c, attrs[g])[1]],
           [], f'{name}: no colour vanishes on a selected row')
    c = FakeCurses()
    attrs = T.curses_attrs(c, 'light')
    eq(pair(c, attrs['fg']), (TH.xterm256('#171717'), 231), 'light: dark text on white')
    c = FakeCurses()
    attrs = T.curses_attrs(c, 'terminal')
    check(getattr(c, 'defaults', False), "terminal: the terminal's own colours are turned on")
    eq(pair(c, attrs['fg']), (-1, -1), "terminal: its own foreground on its own background")
    eq(pair(c, attrs['red'])[0], 1, 'terminal: red is ANSI 1, whatever the terminal makes of it')
    eq(pair(c, attrs['sel:red']), (15, 1), 'terminal: red on the red focused row turns bright white')
    eq(pair(c, attrs['hkey'])[0], 3, 'terminal: a key is ANSI yellow')
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'colors.toml'
        f.write_text(OMARCHY_SAMPLE, encoding='utf-8')
        th = TH.get('omarchy', f)
        eq((th['bg'], th['fg'], th['accent'], th['red'], th['sel'], th['bblue']),
           ('#1e1e2e', '#cdd6f4', '#89b4fa', '#f38ba8', '#45475a', '#74c7ec'), 'omarchy reads colors.toml')
        with mock.patch.dict(T.TH.os.environ, {'OMARCHY_COLORS': str(f)}):
            c = FakeCurses()
            attrs = T.curses_attrs(c, 'omarchy')
            eq(pair(c, attrs['accent']), (TH.xterm256('#89b4fa'), TH.xterm256('#1e1e2e')),
               'the terminal page draws the Omarchy accent on its background')
        eq(TH.get('omarchy', Path(d) / 'missing.toml'), TH.THEMES['ryha'], 'no colors.toml: ryha')


def test_idle_run_of_another_project() -> None:
    """B113: an idle 5-slot run (iFizBox's: no slot sessions, control sessions titled in state) lists c1, c6 and
    c9 with their titles and s1-s5 idle; an idle slot's pane says so instead of attaching."""
    repo = Path(tempfile.mkdtemp()) / 'iFizBox'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q')
    S.init(repo)
    titles = {9: 'iOS 26 native glass +', 1: 'Install IPAs row + wider', 6: 'Pairing broken: Tailscale logout'}
    S.C.notes('STATE').write_text('{"state": "5 slots, usage caps off (f)", "running": {}, "idle": true}',
                                  encoding='utf-8')
    snap = U.snapshot(up=True, links={}, windows=titles)
    tm = Tmux()
    p = page(snap, tmux=tm)
    eq([r['name'] for r in p.items(2)], ['c1', 'c6', 'c9', 's1', 's2', 's3', 's4', 's5', '+'],
       'c1, c6, c9, then every slot, idle, then the new chat row')
    win = Win(30, 120)
    p.key('2')
    p.draw(win)
    left = [l[:44] for l in win.lines()]
    for want in ('c6 Pairing broken', 'c9 iOS 26 native', 's2 idle'):
        check(any(want in l for l in left), f'Sessions shows "{want}"', win.text())
    p.cur[2] = 4  # s2
    p.key('ENTER')
    eq(p.tab()[0], 'session', "s2's session tab")
    check('s2 is idle: nothing running' in drawn(p).text(), 'it says s2 is idle')
    p.key('ENTER')
    eq((tm.calls, p.msg), ([], 's2 is idle: nothing running'), 'Enter on an idle slot: the idle line, no pane')


def test_run_key_binds() -> None:
    """C26: V, Z and B in Status [1] post the run's u, z and x keys (upgrade, suspend and shut down once
    stopped) to KEYS, through ui_model's run controls (`key u|z|x`), as the run view posts typed ones."""
    from agent_runner import cmds as M, loop as LP, plan as PL
    d = Path(tempfile.mkdtemp(prefix='c26-keys-'))

    class Notes:
        command = 'agent-runner'

        @staticmethod
        def notes(*parts):
            return d.joinpath(*parts)

    def run_in_process(argv):  # what the subprocess would do: `agent-runner key u` in a repo with a run up
        out = io.StringIO()
        with mock.patch.object(M, 'init'), mock.patch.object(M, 'run_up', lambda: True), \
                mock.patch.object(M, 'C', Notes), contextlib.redirect_stdout(out):
            return M.cmd_key(argv[1:], prog='agent-runner key'), out.getvalue()

    posted: list[str] = []
    with mock.patch.object(U, 'RUN', [run_in_process]), mock.patch.object(LP, 'C', Notes):
        for k in ('V', 'Z', 'B'):
            p = page()
            p.key(k)
            check(p.confirm and not PL.take(Notes, 'KEYS'), f'F124: {k} asks first', p.msg)
            p.key(k)
            posted += PL.take(Notes, 'KEYS')
    eq(posted, ['u', 'z', 'x'], 'V, Z and B post u, z and x to KEYS')
    check(all(b in HELP_TEXT() for b in ('V V      upgrade agent-runner', 'Z Z  B B  suspend, shut down once stopped', 'Y Y      restart the run',
                                     'r        resume a cut-off task', 'W E      moved-aside edits')),
          'HELP lists them', HELP_TEXT())


def HELP_TEXT() -> str:
    return T.HELP


def test_run_controls() -> None:
    """F82: each run control's key in Status [1] (a slot's task controls in Sessions [2]) runs its runner command
    through ui_model's one list; stop now (X) runs only on X again."""
    ran, sent = [], []
    want = {'+': ['slots', '+1'], '-': ['slots', '-1'], 'P': ['pause'], 'G': ['pause', '--off'], 'F': ['force'],
            'C': ['force', '--off'], 'S': ['stop'], 'U': ['stop', '--undo'],
            'V': ['key', 'u'], 'Z': ['key', 'z'], 'B': ['key', 'x'],  # C26: upgrade, suspend, shut down
            'Y': ['key', 'restart'], 'T': [], 'r': ['resume', 'F8'], 'L': ['plan', 'unclaim', 'F9'],  # F124
            'W': ['wip', 'show', 'main-checkout-1'], 'E': ['wip', 'restore', 'main-checkout-1'],
            'O': ['wip', 'drop', 'main-checkout-1']}
    fix = {'resume': [{'id': 'F8', 'label': 'cut off'}], 'unclaim': [{'id': 'F9', 'label': 'bob'}],
           'wip': [{'id': 'main-checkout-1', 'label': '3 files'}]}
    lists = {}
    for windows in (False, True):
        with mock.patch('agent_runner.plat.WINDOWS', windows):
            lists[windows] = U.controls()
    double = {c['tui'] for c in lists[False] if c['confirm'] and c['where'] == 'run'}
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'sent to the run'))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent',
                                                                             'argv': []})[1]]):
        eq({c['tui'] for c in U.controls() if c['where'] == 'run'} - set(want), {'=', 'X'},
           'every run control has its key here (= and X tested below)')
        for k, argv in want.items():
            p = page()
            p.snap = {**p.snap, 'controls': lists[False], 'fixups': fix, **({'up': False} if k == 'T' else {})}
            p.get_snap = lambda s=p.snap: s
            ran.clear()
            with mock.patch.object(U, 'fixups', lambda st, ls: fix):
                p.key(k)
                if p.run_start:  # F402c2: T starts it on a thread
                    p.run_start['thread'].join(10)
                if k in double:
                    eq(ran, [], f'F124: {k} asks first')
                    p.key(k)
            eq(ran, [argv], f'{k} runs {" ".join(argv)}')
        p = page()  # B163: no re-exec on Windows, so no restart there
        p.snap = {**p.snap, 'controls': lists[True], 'fixups': fix}
        p.get_snap = lambda s=p.snap: s
        ran.clear()
        p.key('Y')
        p.key('Y')
        eq((ran, p.confirm), ([], ''), 'Y on Windows does nothing')
        two = {**fix, 'wip': fix['wip'] + [{'id': 'main-checkout-2', 'label': '1 file'}]}
        p = page()
        p.snap = {**p.snap, 'fixups': two}
        p.get_snap = lambda s=p.snap: s
        ran.clear()
        p.key('W')
        check(ran == [] and p.typing == 'ctl:wip_show' and 'main-checkout-2' in p.msg, 'F124: two of them: which one?',
              (ran, p.typing, p.msg))
        p.key('^U')
        for ch in 'main-checkout-2':
            p.key(ch)
        p.key('ENTER')
        eq(ran, [['wip', 'show', 'main-checkout-2']], 'the one typed is shown')
        check('sent to the run' in drawn(p).text() and p.output == ['sent to the run'], 'its whole output stays in the pane', p.output)
        p = page()
        ran.clear()
        p.key('r')
        check(ran == [] and 'nothing to do' in p.msg, 'F124: nothing cut off: r says so', (ran, p.msg))
        p.key('T')
        check(ran == [] and 'up already' in p.msg, 'F124: T with a run up says so', (ran, p.msg))
        p = page()
        p.key('ENTER')
        p.key('l')
        p.key('l')
        p.key('l')
        eq(p.tab()[0], 'controls', 'Status has a controls tab')
        win = drawn(p, w=140)
        for b in ('[+ slot +1]', '[- slot -1]', '[= set slots]', '[P pause]', '[G go on]', '[F force past the caps]',
                  '[S stop (running tasks finish)]', '[X stop now]', '[U take the stop back]',
                  '[V upgrade agent-runner]', '[Z suspend once stopped]', '[B shut down once stopped]'):
            check(b in win.text(), f'the controls tab shows {b}', win.text())
        p.key('ESC')
        ran.clear()
        p.key('=')
        eq(p.typing, 'slots:n', '= types the slot count')
        for c in '4':
            p.key(c)
        p.key('ENTER')
        eq((ran, p.typing), ([['slots', '4']], ''), '= 4 Enter runs slots 4')
        ran.clear()
        p.main = False
        p.key('X')
        eq((ran, p.confirm), ([], 'stop_now'), 'X alone runs nothing: it asks first')
        check('X again: yes' in drawn(p, w=140).text(), 'the controls tab shows the question')
        p.key('n')
        eq((ran, p.confirm), ([], ''), 'any other key: not stopped')
        p.main = False
        p.key('X')
        p.key('X')
        eq(ran, [['stop', '--force']], 'X X runs stop --force')
        ran.clear()
        p = page()
        p.key('2')
        p.cur[2] = 2  # s1 on F1
        p.key('ENTER')
        win = drawn(p)
        check('[C cancel]' in win.text() and 'take back' not in win.text() and '[D drop]' in win.text(), "a slot's feed shows its task controls",
              win.text())
        p.key('D')
        eq(ran, [['plan', 'drop', 'F1', U.TASK_DROP_WHY]], 'D on a slot drops its task from the slot')
        ran.clear()
        p.key('H')
        eq((sent, ran), ([], []), 'F426d: H on a slot does nothing: Take back is gone')
        p.key('C')
        check(ran == [] and p.msg.startswith('F1 has worked ') and p.msg.endswith('Cancel F1? C again: yes'),
              'C on a slot asks, with the minutes worked', p.msg)
        p.key('x')
        eq(ran, [], 'any other key: no')
        p.key('C')
        p.key('C')
        eq(ran, [['plan', 'cancel', 'F1', '--yes']], 'C C cancels its task')
        ran.clear()
        p.cur[2] = 0  # c1: no task controls
        p.key('D')
        eq(ran, [], 'D on a control session does nothing')
        p.cur[2] = 3  # s2 lands B2 (merging)
        p.key('D')
        eq(ran, [], 'D on a slot whose task is landing does nothing')
        p.key('ENTER')
        check('[D drop]' not in drawn(p).text(), "a landing slot's feed shows no task controls")


@mock.patch.object(T, 'EXEC_RESTART', True)  # the restart test holds on Windows too, where it is off
def test_follow_upgrade_f90() -> None:
    """F90: a snapshot from a newer run makes the TUI start again (a stub exec) with the same argv and its place
    in AGENT_RUNNER_TUI_PLACE; an equal, older or missing version does not; the new TUI reopens there."""
    from agent_runner import __version__
    major, rest = __version__.split('.', 1)
    newer = f'{int(major) + 1}.{rest}'
    for v, why in ((__version__, 'an equal version'), ('0.0.1', 'an older version'), ('', 'no version'),
                   (None, 'a snapshot without the key')):
        snap = dict(SNAP, version=v) if v is not None else dict(SNAP)
        p = page(snap)
        p.refresh()
        check(not p.restart, f'{why}: no restart')
    p = page(dict(SNAP, version=newer))
    p.key('3')
    p.key('DOWN')
    p.key('ENTER')  # the main pane on B2
    check(p.set_tab('chat edit'), "B2's second tab")
    p.set_text('status:chat', 'half a message\nline two')  # F92: a draft survives the restart
    p.refresh()
    check(p.restart, 'a newer run version: restart')
    got = []
    with mock.patch.object(sys, 'orig_argv', ['/usr/bin/python3', '/x/run', 'ui'], create=True):
        T.follow_upgrade(p, exec_=lambda path, argv, env: got.append((path, argv, env)))
    eq(len(got), 1, 'exec called once')
    path, argv, env = got[0]
    eq((path, argv), (sys.executable, ['/usr/bin/python3', '/x/run', 'ui']), 'the same interpreter and argv')
    place = json.loads(env[T.PLACE_ENV])
    eq((place['panel'], place['sel'], place['main'], place['for']), (3, 'B2', True, newer),
       'the place: the focused panel, the selection, the main pane, the version it restarts for')
    q = page(dict(SNAP, version=newer))
    with mock.patch.dict(os.environ, {T.PLACE_ENV: env[T.PLACE_ENV]}):
        q.restore_place(T.taken_place())
        check(T.PLACE_ENV not in os.environ, 'the place is taken once')
    eq((q.panel, q.sel().get('id'), q.main, q.tab()[0]), (3, 'B2', True, 'chat edit'),
       'the new TUI reopens where it was: panel, selection, main pane, tab')
    eq(q.text_of('status:chat'), 'half a message\nline two', 'F92: the typing box keeps its draft')
    r = page(dict(SNAP, version=newer))
    r.restore_place({'drafts': {'status:chat': 7, 'c2:chat': ''}})
    eq(r.drafts, {}, 'F92: a draft that is not text, or empty, is left out')
    q.refresh()
    check(not q.restart, 'never a second restart for the version it restarted for')
    check(T.newer_version('0.60.0', '0.59.9') and not T.newer_version('0.59.0', '0.59.0')
          and T.newer_version('0.100.0', '0.99.0') and not T.newer_version('', '0.1.0'), 'newer_version')


def test_cli() -> None:
    from agent_runner import cli
    eq(cli.COMMANDS.get('ui'), ('tui', 'main'), '`agent-runner ui` runs the terminal Run page')
    check('agent-runner ui' in cli.USAGE, 'the command list names `ui`')
    eq(T.main(['--nope']), 2, 'ui takes no arguments')


def test_side_keys_in_box_f113() -> None:
    p = page()  # F112: no chat box any more: Needs you's reply box
    p.key('4')
    p.key('a')
    p.key('i')
    eq((p.panel, p.sel()['id'], p.typing), (4, 'D3', 'answer:D3'), 'typing in D3\'s reply box')
    for c in 'abc':
        p.key(c)
    p.key('\x7f')
    eq(p.text_of('answer:D3'), 'ab', 'Backspace (\\x7f) still deletes a character')
    p.key('\x08')
    eq((p.typing, p.main, p.drafts.get('answer:D3')), ('', False, 'ab'), 'Ctrl-h in a box: the panels, the draft kept')
    p.key('\x0c')
    eq((p.typing, p.main), ('', True), 'Ctrl-l: the right side')
    p.key('i')
    p.key('\x0c')
    eq(p.typing, 'answer:D3', 'Ctrl-l in a box on the right side stays in it')
    row = p.cur[4]
    p.key('\n')
    eq((p.cur[4], p.typing, p.main, p.drafts.get('answer:D3')), (row + 1, '', True, 'ab'),
       'Ctrl-j in a box: the next row of the left list (no new line), focus kept, the draft kept')
    p.key('\x0b')
    eq((p.cur[4], p.sel()['id']), (row, 'D3'), 'Ctrl-k: the row above')
    p.key('i')
    eq(p.text_of('answer:D3'), 'ab', 'back in D3\'s box, the draft is there')
    p.key('ESC')
    p.key('ESC')
    p.key('\n')
    eq((p.cur[4], p.main), (row + 1, False), 'Ctrl-j on the panels moves down too')


def test_d_drops_f116() -> None:
    """F116: d drops the selected row in panels 2-5 (with the panels focused): a slot's task, a queued task, a
    Needs you item, a concept; on cN it closes the control session (`control.close_from_tui`, logged as
    'control N: closed from the TUI'). The bottom line shows d where it works."""
    from agent_runner import control as K
    ran, ended, logged = [], [], []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(K, 'end_control', lambda n, why: (ended.append(n), True)[1]), \
            mock.patch.object(K, 'log', logged.append):
        p = page()
        p.key('2')
        p.cur[2] = 1  # c6
        check(('d', 'close') in p.hint_keys(), 'c6: d close on the bottom line', p.hint_keys())
        p.key('d')
        eq(ended, [6], 'd on c6 ends control 6')
        eq(logged, ['control 6: closed from the TUI'], 'and logs it')
        p.cur[2] = 2  # s1 on F1
        check(('d', 'drop') in p.hint_keys(), 'a slot on a task: d drop on the bottom line', p.hint_keys())
        p.key('d')
        eq(ran, [['plan', 'drop', 'F1', U.TASK_DROP_WHY]], 'd on a slot drops its task from the slot')
        ran.clear()
        p.cur[2] = 3  # s2 lands B2
        p.key('d')
        eq(ran, [], 'd on a slot whose task is landing does nothing')
        p.key('3')
        p.cur[3] = 1  # B2
        check(('d', 'drop') in p.hint_keys(), 'the queue: d drop on the bottom line', p.hint_keys())
        p.key('d')
        eq(ran, [['plan', 'drop', 'B2', 'dropped from agent-runner ui']], 'd on a queued task drops it')
        ran.clear()
        p.key('4')
        p.cur[4] = 2  # D7
        check(('D', 'drop') in p.hint_keys(), 'F110: Needs you: D drop on the bottom line', p.hint_keys())
        p.key('d')
        check(ran == [] and 'Drop D7?' in p.msg and 'D again' in p.msg, 'd on a Needs you item asks first', (ran, p.msg))
        p.key('x')
        check(ran == [] and 'not done' in p.msg, 'any other key keeps it', (ran, p.msg))
        p.key('D')
        p.key('D')
        eq(ran, [['plan', 'drop', 'D7', 'dropped from Needs you']], 'D, then D again, drops it')
        check('D7' not in [n['id'] for n in p.snap['needs']], 'and the item leaves the list', p.snap['needs'])
        check('d D      drop' in T.HELP, 'HELP lists it')
        ran.clear()
        p.key('5')
        p.cur[5] = 0  # K5
        check(('d', 'drop') in p.hint_keys(), 'Concepts: d drop on the bottom line', p.hint_keys())
        p.key('d')
        eq(ran, [['plan', 'drop', 'K5', 'dropped from agent-runner ui']], 'd on a concept drops it')
        ran.clear()
        p.cur[5] = 1  # + new concept
        p.key('d')
        eq(ran, [], 'd on the new concept row drops nothing')
        p.key('1')
        p.key('d')
        eq((ran, ended), ([], [6]), 'Status has nothing to drop')


def test_rename_f129() -> None:
    """F129: r on a cN row takes the person's own name on the bottom line and runs control --rename N NAME."""
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 6 is renamed'))[1]]):
        for at, n in ((0, '1'), (1, '6')):
            p = page()
            p.key('2')
            p.cur[2] = at
            check(('r', 'rename') in p.hint_keys(), f'c{n}: r rename on the bottom line', p.hint_keys())
            p.key('r')
            check(p.typing == f'rename:c{n}', 'r types a name', p.typing)
            for ch in 'Login':
                p.key(ch)
            check('Login' in ''.join(t for t, _ in p.footer()), 'the name shows on the bottom line', p.footer())
            p.key('ENTER')
            eq(ran[-1], ['control', '--rename', n, 'Login'], f'Enter renames c{n}')
            eq(p.typing, '', 'and leaves the box')
        p = page()
        p.key('2')
        p.cur[2] = 1
        ran.clear()
        p.key('r')
        p.key('x')
        p.key('ESC')
        eq((ran, p.typing), ([], ''), 'Esc keeps the old name')
        p.cur[2] = 2  # s1, a slot
        p.key('r')
        eq((ran, p.typing), ([], ''), 'r on a slot renames nothing')
    check('r        rename a control session' in T.HELP, 'HELP lists it')


def test_close_control_quiet_b136() -> None:
    """B136: d on cN runs `control.close_from_tui` in-process, whose run-log lines print to stdout: the TUI
    swallows them (nothing written over the curses screen) and asks for a full repaint on the next frame."""
    from agent_runner import control as K
    logged = []

    def end(n, why):
        print(f'control {n}: ended ({why})')
        return True

    def log(line):
        logged.append(line)
        print(line)
    out = io.StringIO()
    with mock.patch.object(K, 'end_control', end), mock.patch.object(K, 'log', log), \
            mock.patch.object(sys, 'stdout', out):
        p = page()
        p.repaint = False
        p.run_control('session_close', tid='c6')
    eq(out.getvalue(), '', 'close_control writes nothing to sys.stdout')
    eq(logged, ['control 6: closed from the TUI'], 'the line still goes to the run log')
    eq((p.repaint, p.msg_ok), (True, True), 'and the next frame repaints every cell')


def answer_repo() -> Path:
    """B138: a project whose plan asks F1 to CONFIRM, F2 to DECIDE and F3 BLOCKED."""
    from agent_runner import plan as P
    repo = Path(tempfile.mkdtemp()) / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    for text in ('push notices | files: a.py', 'pick a database | files: b.py', 'deploy key | files: c.py'):
        P.add('F', text, todo=S.C.todo)
    P.block('F1', 'CONFIRM: check the push reached your phone', todo=S.C.todo)
    P.block('F2', 'DECIDE: Postgres or SQLite, yes or no?', todo=S.C.todo)
    P.block('F3', 'BLOCKED: add the deploy key on the server', todo=S.C.todo)
    return repo


def no_send(text):
    raise AssertionError(f'an answer button reached an AI session: {text!r}')


def test_answer_direct_b138() -> None:
    """B138: a Needs you button runs the plan command itself, never an AI session (SEND fails if called): Yes on
    a CONFIRM is plan confirm, No is plan change "No: the check failed", a DECIDE's pick is plan confirm, a
    block's done is plan confirm; typed words go to a new chat, a DECIDE's are its answer (F181a)."""
    answer_repo()
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'SEND', [no_send]):
        r = U.answer('F1', 'Yes', button=True)
        eq((r['ok'], r.get('said'), r.get('gone')), (True, 'F1 ticked', 'F1'), 'Yes: ticked, off Needs you')
        U.answer('F1', 'No', button=True)
        U.answer('F2', 'Yes', button=True)
        U.answer('F3', 'done', button=True)
    eq(ran, [['plan', 'confirm', 'F1', 'Yes'], ['plan', 'change', 'F1', 'No: the check failed'],
             ['plan', 'confirm', 'F2', 'Yes'], ['plan', 'confirm', 'F3', 'done']],
       'each button runs its plan command')
    sent = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (1, 'plan: no such task'))[1]]), \
            mock.patch.object(U, 'SEND', [lambda t: (sent.append(t), {'ok': True, 'out': 'sent to c1'})[1]]):
        r = U.answer('F1', 'Yes', button=True)
        eq((r['ok'], r['out'], 'gone' in r), (False, 'plan: no such task', False), 'a failure says why; the item stays')
        U.answer('F1', 'it came late')
        U.answer('F2', 'SQLite, it is one file')
    eq(sent, ['F1 (push notices): it came late'], "a CONFIRM's typed words go to a new chat, a DECIDE's do not")
    eq(ran[-1], ['plan', 'confirm', 'F2', 'SQLite, it is one file'], "a DECIDE's typed words are its answer")
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), \
            mock.patch.object(U, 'SEND', [no_send]), \
            mock.patch('agent_runner.brief.has_sheet', lambda tid: tid == 'F2'):
        ran.clear()
        r = U.answer('F9', 'Yes', button=True)
        eq((r['ok'], r['out'], ran), (False, 'F9 no longer needs you (answered already?)', []),
           'a button for something that needs nothing here fails saying so, with no AI session')
        U.answer('F2', 'go', button=True)
        U.answer('F2', 'F2 picks: db=sqlite', button=True)
    eq(ran, [['sheet', 'F2', '--go'], ['sheet', 'F2', '--picks', 'F2 picks: db=sqlite']],
       'a pick sheet keeps sheet ID --go / --picks')


def test_answer_tab_b138() -> None:
    """B138: y in the answer tab of a CONFIRM runs plan confirm (no AI session), says 'F1 ticked', and the item
    leaves Needs you at once even before the run's next snapshot drops it."""
    answer_repo()
    need = {'label': 'CONFIRM', 'id': 'F1', 'concept': '', 'title': 'push notices', 'what': 'push',
            'url': '', 'ask': 'Check the push reached your phone - reply yes or no', 'age': '1m'}
    p = page(dict(SNAP, needs=[need] + SNAP['needs'][2:]))
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'confirmed and ticked F1'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch.object(U, 'SEND', [no_send]):
        p.key('4')
        check(not any(k in ('y', 'n') for k, _ in p.hint_keys()), 'F180: no answer key while the panel has focus', p.hint_keys())
        p.key('y')
        eq((ran, p.main), ([], False), 'F180: y answers in the answer tab only')
        p.key('ENTER')
        check('[y Yes] [n No] [L later]' in drawn(p).text(), 'F180: its answers are buttons there', drawn(p).text())
        p.key('y')
    eq(ran, [['plan', 'confirm', 'F1', 'Yes']], 'y runs plan confirm')
    eq((p.msg, p.msg_ok), ('F1 ticked', True), 'the bottom line says what was done')
    eq([n['id'] for n in p.snap['needs']], ['D7'], 'F1 is off Needs you at once')
    p = page(dict(SNAP, needs=[need]))
    with mock.patch.object(U, 'RUN', [lambda argv: (1, 'plan: F1 is not waiting')]), \
            mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch.object(U, 'SEND', [no_send]):
        p.key('4')
        p.key('ENTER')
        p.key('n')
    eq((p.msg, p.msg_ok, p.main, [n['id'] for n in p.snap['needs']]), ('plan: F1 is not waiting', False, True, ['F1']),
       'a failure says why and the item stays, its pane open')


def test_decide_options_f181c() -> None:
    """F181c: a DECIDE's options are buttons in the answer tab, the recommended one marked; a key sends the bare name by
    plan confirm, with no session. One past the last key is typed as the reply."""
    answer_repo()
    names = ['Full', 'Small', 'No change'] + [f'Size {j}' for j in range(4, 9)]
    need = {'label': 'DECIDE', 'id': 'F2', 'concept': '', 'title': 'the look', 'what': 'Which look?', 'url': '', 'ask': 'Which look?',
            'age': '1m', 'options': [{'name': n, 'rec': n == 'Full'} for n in names]}
    p = page(dict(SNAP, needs=[need]))
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'open again'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch.object(U, 'need_label', lambda tid: 'DECIDE'), \
            mock.patch.object(U, 'SEND', [no_send]):
        p.key('4')
        p.key('ENTER')
        text = drawn(p).text()
        check('[a Full (recommended)] [b Small] [c No change]' in text, 'its options are buttons', text)
        check('More options, typed as the reply: Size 8' in ' '.join(text.split()), 'one with no key is named', text)
        p.key('a')
    eq(ran, [['plan', 'confirm', 'F2', 'Full']], 'a press: the bare name, plan confirm')
    eq([n['id'] for n in p.snap['needs']], [], 'F2 is off Needs you at once')


def test_sheet_buttons_f181b() -> None:
    """F181b: a pick sheet's easy answers are buttons in the answer tab; a key runs sheet ID --go or --picks, with no
    session."""
    answer_repo()
    opts = [{'name': U.SHEET_GO_LABEL, 'rec': False}, {'name': 'SQLite', 'rec': True}, {'name': 'Postgres', 'rec': False}]
    need = {'label': 'DECIDE', 'id': 'F2', 'concept': '', 'title': 'the store', 'what': 'Which store', 'url': 'https://claude.ai/x',
            'ask': 'Which store', 'age': '1m', 'options': opts,
            'picks': {U.SHEET_GO_LABEL: 'go', 'SQLite': 'F2 picks: db=a', 'Postgres': 'F2 picks: db=b'}}
    ran = []
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'open again'))[1]]), \
            mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch('agent_runner.brief.has_sheet', lambda tid: True), \
            mock.patch.object(U, 'SEND', [no_send]):
        for k in 'ac':
            p = page(dict(SNAP, needs=[need]))
            p.key('4')
            p.key('ENTER')
            text = ' '.join(drawn(p).text().split())
            check('[a Go with the recommended picks]' in text and 'b SQLite (recommended)' in text and 'c Postgres' in text,
                  'its easy answers are buttons', text)
            p.key(k)
            eq([n['id'] for n in p.snap['needs']], [], 'F2 is off Needs you at once')
    eq(ran, [['sheet', 'F2', '--go'], ['sheet', 'F2', '--picks', 'F2 picks: db=b']], 'what each key runs')


def test_concept_answer_b149() -> None:
    """B149: a concept's option key (a b c) in the answer tab runs plan approve with that option, never an AI
    session, and the item leaves Needs you at once."""
    from agent_runner import plan as P
    answer_repo()
    P.add('K', 'menu layout | files: m.py', todo=S.C.todo)
    bid = P.concept_done('K1', 'https://x.invalid/k1', todo=S.C.todo)
    eq(U.need_label(bid), 'CONCEPT', 'the build task waits on the concept')
    need = {'label': 'CONCEPT', 'id': bid, 'concept': 'K1', 'title': 'menu layout', 'what': '',
            'url': 'https://x.invalid/k1', 'ask': 'Pick an option on the concept page', 'age': '1m',
            'answers': [{'label': n, 'value': n} for n in ('Option A', 'Option B', 'Option C', 'Option D')]}
    p = page(dict(SNAP, needs=[need] + SNAP['needs'][2:]))
    ran = []
    for k, opt in (('c', 'Option C'), ('d', 'Option D')):  # F180: not a new chat, not Drop, in the answer tab
        q = page(dict(SNAP, needs=[need]))
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'approved'))[1]]), \
                mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch.object(U, 'SEND', [no_send]):
            for x in ('4', 'ENTER', k):
                q.key(x)
        eq(ran, [['plan', 'approve', bid, opt]], f'{k} picks {opt}')
        ran.clear()
    with mock.patch.object(U, 'row_of', lambda where, tid: need), mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'approved'))[1]]), \
            mock.patch.object(U, 'SEND', [no_send]):
        p.key('4')
        p.key('ENTER')
        p.key('b')
    eq(ran, [['plan', 'approve', bid, 'Option B']], 'b runs plan approve with option B')
    eq((p.msg, p.msg_ok), (f'{bid} approved (Option B): a run starts its build', True), 'the bottom line says so')
    eq([n['id'] for n in p.snap['needs']], ['D7'], 'the concept is off Needs you at once')
    with mock.patch.object(U, 'SEND', [no_send]):
        r = U.answer(bid, 'Option A: one list', button=True)
    check(r['ok'], 'the real plan approve runs', r)
    eq(U.need_label(bid), '', 'the build task no longer waits')


LONG_ASK = ('Sign in to Chariz on the iPhone 15 Pro (iFizBox > Sources > Chariz > Glint > Sign In, then pick the '
            'Apple ID)\nand check that Glint downloads. Notes are in .runner/journal/R45.md - reply yes/no')


def test_short_ask_b152() -> None:
    """B152: needs_rows adds ask_short (first sentence, no asides or paths, ~120 chars) beside the full ask, and
    a Needs you panel row shows it on one line, even for an ask of several lines with a long title."""
    import datetime as dt
    needs, _ = U.needs_rows([('CONFIRM', 'R45', '', LONG_ASK, '', 'Check the Chariz sign-in on a real iPhone ' * 3,
                              False, '')], dt.datetime(2026, 11, 23))
    n = needs[0]
    eq(n['ask_short'], 'Sign in to Chariz on the iPhone 15 Pro and check that Glint downloads.',
       'the short ask: first sentence, without the aside')
    check('R45.md' in n['ask'] and '(iFizBox' in n['ask'], 'the full ask keeps the path and the aside', n['ask'])
    check(len(U.ask_short('word ' * 80)) <= U.ASK_SHORT, 'a long sentence is cut to ASK_SHORT', '')
    eq(U.ask_short('Which port? - reply with your answer'), 'Which port? - reply with your answer',
       'a short one-sentence ask stays as it is')
    eq(U.ask_short('Use TCP/IP on iOS 17/18 - reply yes/no'), 'Use TCP/IP on iOS 17/18 - reply yes/no',
       'words with a slash are not paths')
    eq(U.ask_short('Look at ~/x/y and docs/a.md and /etc/hosts now'), 'Look at and and now',
       'paths go from the short ask')
    p = page(dict(SNAP, needs=[n, dict(SNAP['needs'][2])]))
    row = p.row(4, n)
    check(all('\n' not in t for t, _ in row) and 'Glint downloads.' in ''.join(t for t, _ in row),
          'the panel row is the short ask on one line', row)
    eq(row[1][0], n['ask_short'], 'B793b: the row is short though its detail is whole')
    for label, what in (('DECIDE', 'The log (done.log) is old. Pick one'), ('CONFIRM', 'Open the log (done.log); tap Undo')):
        m = U.needs_rows([(label, 'R45', '', what, '', 'T', False, '')], dt.datetime(2026, 11, 23))[0][0]
        check('(done.log)' in m['detail']['summary'] and 'log' in p.row(4, m)[1][0] and '(' not in p.row(4, m)[1][0],
              f'B793b: {label}: the row drops the aside its detail keeps', (m['detail']['summary'], p.row(4, m)))
    own = dict(n, detail=dict(n['detail'], summary='Try it (on the phone)'))
    eq(p.row(4, own)[1][0], 'Try it (on the phone)', "an ask file's summary stays as written")
    check('(iFizBox' in n['detail']['summary'], 'and the detail keeps the aside', n['detail']['summary'])
    lines = drawn(p).lines()
    at = [i for i, l in enumerate(lines) if 'R45 ' in l and 'Sign in to Chariz' in l]
    eq(len(at), 1, 'R45 shows on one panel line')
    check('D7 ' in lines[at[0] + 1], 'the next item is on the very next line', lines[at[0]:at[0] + 2])


def test_need_detail_f162() -> None:
    """F162: Needs you's main pane shows the steps, what to see and the pictures' paths, as the run page's popup."""
    d = {'said': 'Check this', 'where': 'iPhone', 'title': 'The keyboard', 'summary': 'Open it', 'lead': ['On an iPhone'], 'steps': ['Open it', 'Close it'],
         'expect': ['It glides'], 'notes': ['Reply yes/no'], 'shots': [{'src': 'uploads/a.png', 'path': '/n/uploads/a.png', 'caption': 'The band'}]}
    p = page(dict(SNAP, needs=[dict(SNAP['needs'][0], detail=d)]))
    p.key('4')
    said = [l.strip() for l in (''.join(t for t, _ in x) for x in p.pane(80)[0])]
    for want in ('D3 The keyboard', 'On an iPhone', 'What to do', '1. Open it', '2. Close it', 'What you should see', '- It glides',
                 'Pictures', '/n/uploads/a.png', 'The band', 'Reply yes/no'):
        check(want in said, f'the pane shows {want!r}', said)
    check(any(l.startswith('Check this · iPhone') for l in said), 'and what is wanted, where', said)
    check('Open it' in ''.join(t for t, _ in p.row(4, p.snap['needs'][0])), 'the row says what to do', p.row(4, p.snap['needs'][0]))


def test_need_question_b223b() -> None:
    """B223b: a DECIDE's pane is its question, its task's title under it and its background, with What to do only for
    the steps of its ask file."""
    from agent_runner import need_detail as N
    ask = 'The port is taken. Both work. Which port do we use?'
    d = N.detail('DECIDE', 'D3', ask, 'On the 15 Pro with Tailscale selected as the VPN, check the port', '')
    row = dict(SNAP['needs'][0], label='DECIDE', detail=d)
    said = lambda row, w=80: [''.join(t for t, _ in x).rstrip() for x in page(SNAP).need_lines(row, w)]  # noqa: E731
    lines = said(row)
    eq((lines[0], lines[1]), ('D3 Which port do we use?', d['title']), 'the question, then the title')
    check(lines[2].startswith('Choose') and lines[4] == 'The port is taken. Both work.', 'then its background', lines)
    check('What to do' not in lines, 'no steps', lines)
    eq(said(row, 20)[:2], ['D3 Which port do we', '   use?'], 'a long question wraps whole')
    check('What to do' in said(dict(row, detail=dict(d, steps=['Open it']))), 'the ask file\'s steps show')
    eq(said(dict(row, detail=dict(d, title='D3')))[1][:6], 'Choose', 'no title of its own: none')


F399_ASK = {'summary': 'Give the link of Install Switch', 'steps': [
    {'text': "Add main's copy of Install Switch to Shortcuts", 'link': 'https://example.com/Install%20Switch.shortcut'},
    'Share > Copy iCloud Link'],
    'inputs': [{'key': 'icloud', 'label': 'iCloud link', 'kind': 'link', 'hint': 'It starts with https://www.icloud.com/shortcuts/',
                'match': r'https://www\.icloud\.com/shortcuts/[0-9a-f]+', 'confirm': 'This publishes the shortcut. Send it?'}]}


def give_page(ask: dict, tid: str = 'F2', **kw):
    """F175b: answer_repo's item `tid` with the asks file `ask`, its answer tab open: (the page, its repo)."""
    from agent_runner import need_detail as N
    repo = answer_repo()
    f = S.C.notes('uploads', 'x').parent.parent / 'asks' / f'{tid}.json'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(ask), encoding='utf-8')
    row = {'label': 'DECIDE', 'id': tid, 'concept': '', 'title': 'pick a database', 'what': '', 'url': '', 'ask': 'yes or no?',
           'age': '1m', 'detail': N.detail('DECIDE', tid, 'yes or no?', 'pick a database', '')}
    row['answers'] = U.need_answers(row)
    row.update(acts=U.row_acts('need', row), labels=U.row_labels('need', row))
    p = page(dict(SNAP, needs=[row, SNAP['needs'][2]]), **kw)
    p.key('4')
    p.key('ENTER')
    return p, repo


def keys(p, *ks) -> None:
    for k in ks:
        for c in ([k] if k.isupper() or k[0] == '^' else k):  # a key's name, else words typed
            p.key(c)


def test_need_give_f175b() -> None:
    """F175b: the Needs you pane draws an item's steps (Open), its field and one Done, no plain answers; a failed match
    sends nothing and says the hint at the field; the confirm question is asked first."""
    opened, ran = [], []
    link = 'https://www.icloud.com/shortcuts/ab12'
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), mock.patch.object(U, 'SEND', [no_send]):
        p, _ = give_page(F399_ASK, opener=lambda url: (opened.append(url), {'ok': True, 'out': 'opened'})[1])
        text = drawn(p).text()
        for want in ('1. Add main', 'https://example.com/Install%20Switch.shortcut', '[⏎ Open]', '2. Share > Copy iCloud Link',
                     'What to enter', 'iCloud link', '[^S Done] [L later]'):
            check(want in text, f'shows {want!r}', text)
        for no in ('[y Yes]', 'your own reply', 'Your reply', 'nothing is entered'):
            check(no not in text, f'no {no!r}', text)
        check(not any(c.get('answer') for c in p.row_controls(p.sel(), 'need')), 'no plain answers')
        keys(p, 'y', 'ENTER')
        eq((opened, ran), ([F399_ASK['steps'][0]['link']], []), 'y answers nothing, Enter opens the link')
        keys(p, 'TAB')
        eq(p.typing, 'give:F2:icloud', 'Tab types into the field')
        keys(p, 'https://evil.example/Lq', '^S')
        text = drawn(p).text()
        check('iCloud link: It starts with https://www.icloud.com/shortcuts/' in text and p.typing, 'the hint, at the field', text)
        eq((ran, [n['id'] for n in p.snap['needs']][0]), ([], 'F2'), 'a failed match sends nothing')
        keys(p, '^U', link, 'ENTER')
        eq((p.typing, ran), ('give:F2:icloud', []), 'Enter stays in the field and sends nothing')
        keys(p, 'ESC', 'ESC', '^S')
        check('This publishes the shortcut. Send it? ^S again' in drawn(p).text(), 'asked first', drawn(p).text())
        keys(p, 'q')
        eq((ran, p.msg, p.give_sure), ([], 'F2: not sent', ()), 'any other key: no')
        keys(p, '^S', '^S')
    eq([a[:3] for a in ran], [['plan', 'confirm', 'F2']], 'sent once')
    check(link in ran[0][3], 'with the link', ran)
    eq((p.msg, p.main, [n['id'] for n in p.snap['needs']], p.drafts), ('F2 has what you gave: a run starts it', False, ['D7'], {}),
       'it is off Needs you, its words gone')


def test_need_give_secret_f175b() -> None:
    """F175b: a secret is dots as typed, goes to asks/ID.env only, and is on no screen, log or restart; a command names
    its machine."""
    secret, ran, wrote = 's3cr-et', [], []
    ask = {'steps': [{'text': 'Log in', 'cmd': 'gh auth login', 'on': 'rycs'}],
           'inputs': [{'key': 'who', 'label': 'Account'}, {'key': 'tok', 'label': 'Token', 'kind': 'secret', 'env': 'MY_TOKEN'}]}
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]), mock.patch.object(U, 'SEND', [no_send]), \
            mock.patch.dict(os.environ, {'SSH_CONNECTION': 'x'}):
        p, repo = give_page(ask, out=wrote.append)
        for h, w in ((32, 120), (12, 40)):
            text = drawn(p, h, w).text()
            check('[^S Done]' in text, f'Done shows at {w}x{h}', text)
        text = drawn(p).text()
        check('Run on rycs' in text and 'gh auth login' in text and '[⏎ Copy]' in text, 'the command and its machine', text)
        keys(p, 'ENTER')
        eq((p.msg, any(T.osc52('gh auth login') in x for x in wrote)), ('command copied', True), 'Enter copies it')
        keys(p, 'TAB', 'me', 'TAB', 'ab', 'ENTER', 'qL')
        eq((p.typing, p.secrets, p.drafts), ('givesec:F2:tok', {'givesec:F2:tok': 'abqL'}, {'give:F2:who': 'me'}),
           'a pasted line end: the rest stays hidden')
        keys(p, '^U')
        keys(p, secret)
        win = drawn(p, 12, 40).text()
        check('•' * len(secret) + '█' in win and secret not in win, 'hidden as typed, its field scrolled into view', win)
        check(secret not in json.dumps(p.saved_place()), 'a restart is handed no secret')
        with mock.patch.object(T, 'EXEC_RESTART', True):
            p.snap['version'] = '999.0'
            p.refresh()
            check(not p.restart, 'and waits for it')
        rows = p.snap['needs']
        p.get_snap = lambda: dict(p.snap, needs=[rows[1], rows[0]])
        p.refresh()
        eq((p.sel()['id'], p.secrets), ('F2', {'givesec:F2:tok': secret}), 'the item moved: still selected')
        p.get_snap = lambda: dict(p.snap, needs=[rows[1]])
        p.refresh()
        keys(p, 'dLq')
        eq((p.secrets, ran, p.typing, 'changed' in p.msg), ({}, [], 'givesec:F2:tok', True), 'it went: the secret goes, no key reaches a panel')
        keys(p, 'ESC')
        p.get_snap = lambda: dict(p.snap, needs=rows)
        p.refresh()
        p.cur[4], p.main = 0, True
        keys(p, '^S')
        eq((p.typing, p.give_said['field'], ran), ('givesec:F2:tok', 'tok', []), 'every field is needed')
        keys(p, secret, '^J')
        eq(p.secrets, {}, 'another item selected: forgotten')
        keys(p, '^K', 'i', 'TAB', secret, '^S')
    eq([a[:3] for a in ran], [['plan', 'confirm', 'F2']], 'sent')
    env = S.C.notes('asks', 'F2.env')
    eq(env.read_text(encoding='utf-8').strip(), f'MY_TOKEN={secret}', 'kept in the env file')
    for f in repo.rglob('*'):
        check(not f.is_file() or f == env or secret.encode() not in f.read_bytes(), f'not in {f}')
    check(secret not in drawn(p).text() + json.dumps(ran) + json.dumps(p.saved_place()) + ''.join(wrote) + p.msg + str(p.secrets), 'nor on the screen after sending')


def test_quick_ask_names_session_c32() -> None:
    """C32: a quick ask (and H) says the new session's name and selects its row, not 'c1 answers'."""
    c7 = {'name': 'c7', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
          'link': '', 'terminal': ''}
    more = dict(SNAP, sessions=SNAP['sessions'][:2] + [c7] + SNAP['sessions'][2:])
    p = page(SNAP)
    p.get_snap = lambda: more
    res = {'ok': True, 'code': 0, 'out': 'started c7', 'argv': [], 'name': 'c7', 'link': ''}
    with mock.patch.object(U, 'quick_ask', lambda key: res):
        p.key('1')
        p.key('s')
    check('c7 answers in its session' in p.msg and 'c1' not in p.msg, 'the message names c7', p.msg)
    eq((p.panel, p.sel().get('name')), (2, 'c7'), 'c7 is selected in Sessions')


def test_project_name_b153() -> None:
    """B153: 0 (the project name's key) quits for the pick-a-run screen: the launcher's (PICK_RC) when it started
    the TUI, else a new picker; the terminal's window title is the project's name, and given back on the way out."""
    p = page()
    eq((p.key('0'), p.pick), (True, True), '0 quits for the pick-a-run screen')
    check('0        all runs' in T.HELP, 'the keys list has 0')
    t = T.window_title('proj · runner')
    check(t.startswith('\x1b[22;0t') and '\x1b]2;proj · runner\x07' in t, 'the title kept, then the name', t)
    eq(T.window_title('a\x07b\x1b'), '\x1b[22;0t\x1b]0;ab\x07\x1b]2;ab\x07', 'control characters dropped')
    wrote, picked = [], []

    def wrapper(fn, box, bar):
        box['pick'] = True
        return 0
    tty = mock.Mock(isatty=lambda: True)
    from agent_runner import cmds
    os_ = mock.patch.dict(os.environ, {'TMUX': '/tmp/tmux-1/default,1,0'})  # F141: it runs inside tmux
    curses = mock.Mock(wrapper=wrapper)  # Windows' Python has none
    with os_, mock.patch.object(T, 'refusal', lambda: ''), \
            mock.patch.dict(sys.modules, {'curses': curses}), mock.patch.object(T, 'term_write', wrote.append), \
            mock.patch.object(sys, 'stdin', tty), mock.patch.object(sys, 'stdout', tty), \
            mock.patch('agent_runner.state.init', lambda *a: None), mock.patch.object(S, 'ROOT', Path('/x/proj')), \
            mock.patch('locale.setlocale', lambda *a: None), \
            mock.patch.object(cmds, 'cmd_pick', lambda here: picked.append(here) or 5):
        with mock.patch.dict(os.environ, {T.PICKER_ENV: '1'}):
            eq(T.main([]), T.PICK_RC, 'started by the launcher: PICK_RC, its launcher goes back to the picker')
        eq(wrote, [T.window_title('proj · runner'), T.TITLE_BACK], 'the window title set, then given back')
        with mock.patch.dict(os.environ, {T.PICKER_ENV: ''}):
            eq(T.main([]), 5, 'on its own: a pick-a-run screen here')
        eq(picked, [Path('/x/proj')], 'for this project')


def test_release_row_f131() -> None:
    """F131, F185, F195c: the releases are rows of the queue panel at their place: dimmed while auto release
    counts (its tab is release), in the row's own words once queued; J and K move no task past one."""
    words = 'Next release · auto at 10 landed: 6/10'
    last = page(dict(SNAP, releases=[{'id': '', 'placeholder': True, 'text': words, 'before': ''}])).items(3)
    eq(last[len(SNAP['queue'])].get('text'), words, "the placeholder at the queue's end")
    parked = dict(SNAP['queue'][0], id='Q99', state='parked')
    last = page(dict(SNAP, queue=SNAP['queue'] + [parked], releases=[{'id': '', 'placeholder': True, 'text': words, 'before': ''}])).items(3)
    eq([t.get('id') for t in last[-3:-1]], ['release', 'Q99'], 'before the parked tasks, as on the run page')
    p = page(dict(SNAP, releases=[{'id': '', 'placeholder': True, 'text': words, 'before': SNAP['queue'][1]['id']}]))
    eq(p.items(3)[1].get('text'), words, 'or before the task its place names')
    eq(p.row_lines(3, p.items(3)[1], 60, False), [[(words, 'dim')]], 'dimmed')
    p.key('3')
    p.cur[3] = 1
    text = '\n'.join(drawn(p).lines())
    check(words[:20] in text and 'Releases' not in text, 'no group heading', text)
    eq(p.tab()[1], ['release'], 'its tab is release')
    with mock.patch.object(U, 'RUN', [lambda argv: check(False, 'no task action on the placeholder', str(argv))]):
        for k in 'eEdDHpJKU':
            p.key(k)
    eq((p.typing, p.main), ('', False), 'no edit box opens for it')

    def row(tid: str, said: str) -> dict:
        return {'id': tid, 'title': 'Release', 'placeholder': False, 'words': said, 'all': said + ', F9 nine',
                'text': f'{tid} Release · {said}'}
    rows = [row('V5', 'releasing now'), row('V6', 'waits for 1: V5 Release')]
    vs = [dict(SNAP['queue'][8], id=r['id'], title='Release: bump the version', release=r) for r in rows]
    done = {'id': 'V4', 'title': 'Release 1.2.0', 'placeholder': True, 'text': 'V4 Release 1.2.0 · released 10:00'}
    q = SNAP['queue']
    p = page(dict(SNAP, queue=q[:1] + vs[:1] + q[1:] + vs[1:], releases=rows + [done]))
    items = p.items(3)
    ids = [t['id'] for t in items if t.get('id')]
    eq((ids[:3], ids.count('V5'), ids.count('V6'), 'V4' in ids, 'released' in ids), ([q[0]['id'], 'V5', q[1]['id']], 1, 1, False, False),
       'each at its place, once; a landed one is past')
    v5, v6 = ids.index('V5'), ids.index('V6')
    eq([[s for s, _ in p.row_lines(3, items[i], 60, False)[0]] for i in (v5, v6)],
       [[f'{r["id"]}   release  ', ' ', r['text'][3:]] for r in rows], "in the rows' words, after the chip")
    eq([p.row_lines(3, items[v5], w, False)[0][0] for w in (60, 26)], [('V5   release  ', 'kindv'), ('V5   ', 'kindv')], 'the one filled kind; no word with no room')
    check('F9 nine' in ''.join(s for l in p.row_lines(3, items[v6], 200, True) for s, _ in l), 'selected: every task')
    p.key('3')
    with mock.patch.object(U, 'RUN', [lambda argv: check(False, 'nothing moves', str(argv))]):
        p.cur[3] = 0
        p.key('J')
        eq(p.msg, f'{q[0]["id"]} does not move past the release V5', 'J moves no task past a release')
        p.cur[3] = 2
        p.key('K')
        eq(p.msg, f'{q[1]["id"]} does not move past the release V5', 'nor K')
        p.cur[3] = v5
        p.key('K')
        eq(p.msg, 'V5 is a release: it stays at its place', 'the release stays there')
    p.key('ENTER')
    eq((p.main, p.sel()['id'], p.tab()[0]), (True, 'V5', 'direct edit'), 'Enter opens its details')


def test_new_drop_release_f186() -> None:
    """F186: the release tab's New release names the open one and asks; D drops a release that has not started, after
    its confirm, there and on its row; R in the Queue opens the tab."""
    ask, drop = 'V6 is already queued. Queue another release?', 'Drop V6? It leaves the plan, and nothing is released.'

    def rel(tid: str, started: bool) -> dict:
        r = {'id': tid, 'title': 'Release', 'placeholder': False, 'words': 'next', 'all': 'next', 'text': f'{tid} Release · next'}
        return dict(SNAP['queue'][0], id=tid, title='Release', release=r, started=started,
                    acts=['queue_take'] if started else ['queue_take', 'queue_drop'],
                    asks={} if started else {'queue_drop': drop.replace('V6', tid)})

    def page_of(*vs, said=ask):
        return page(dict(SNAP, queue=SNAP['queue'] + list(vs), releases=[v['release'] for v in vs], release_said=said.split('.')[0],
                         controls=U.controls({'ask': said, 'seen': ' '.join(v['id'] for v in vs)} if said else None)))
    ran = []

    def control(key, **kw):
        ran.append((key, kw))
        return {'ok': True, 'out': 'ok'}
    with mock.patch.object(U, 'run_control', control):
        p = page_of(rel('V6', False))
        p.key('3')
        p.cur[3] = len(SNAP['queue'])
        eq(('R', 'new release') in p.hint_keys(), True, 'its row says how to make one')
        p.key('R')
        eq((p.panel, p.tab()[0]), (1, 'release'), 'R in the Queue: the release tab')
        text = '\n'.join(drawn(p).lines())
        check('New release: V6 is already queued' in text and '[D drop V6]' in text, 'it says so, and has Drop', text)
        p.key('ENTER')
        eq((p.msg, ran), (f'{ask} ⏎ again: yes', []), 'a press asks')
        check('Queue another release?' in '\n'.join(drawn(p).lines()), 'in the tab too')
        p.key('x')
        eq(ran, [], 'any other key: no')
        p.key('ENTER')
        p.key('ENTER')
        eq(ran, [('release_wait', {'confirm': True, 'text': 'V6'})], 'again: a second, the open one named')
        ran.clear()
        p.key('D')
        eq((p.msg, ran), (f'{drop} D again: yes', []), 'D asks')
        p.key('D')
        eq(ran, [('queue_drop', {'confirm': True, 'tid': 'V6', 'why': 'dropped from agent-runner ui'})], 'then drops it')
        ran.clear()
        p.key('ESC')
        p.key('3')
        p.cur[3] = len(SNAP['queue'])
        p.key('d')
        eq((p.msg, ran), (f'{drop} D again: yes', []), 'd on its row asks')
        p.key('d')
        eq([k for k, _ in ran], ['queue_drop'], 'then drops it')
        ran.clear()
        p = page_of(rel('V5', True))
        p.key('3')
        p.cur[3] = len(SNAP['queue'])
        p.key('d')
        p.key('d')
        p.key('R')
        p.key('D')
        eq((ran, p.msg), ([], 'no release waits: one that has started cannot be dropped'), 'a running one has no Drop')
        p = page_of(rel('V6', False), rel('V7', False))
        p.key('3')
        p.key('R')
        p.key('D')
        eq((p.panel, p.sel()['id'], ran), (3, 'V6', []), 'two wait: pick its row')
    stale = iter(({'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'seen': 'V6'}, {'ok': True, 'out': 'added V7'}))
    with mock.patch.object(U, 'run_control', lambda key, **kw: (ran.append((key, kw)), next(stale))[1]):
        p = page_of(said='')
        p.key('R')
        p.key('f')
        eq(p.msg, f'{ask} f again: yes', 'one the snapshot did not show yet: asked too')
        p.key('f')
        eq(ran, [('release_now', {}), ('release_now', {'confirm': True, 'text': 'V6'})], 'then queued')


def test_manage_releases_f193() -> None:
    """F193: with the snapshot's `manage_releases` off: no release tab, line, group or hint, R does nothing and is not in
    the keys list; an open V task is an ordinary row of the queue. On, or without the flag: all of it."""
    r = {'id': 'V5', 'title': 'Release', 'placeholder': False, 'words': 'next', 'all': 'next', 'text': 'V5 Release · next'}
    v5 = dict(SNAP['queue'][8], id='V5', title='Release: bump the version', acts=['queue_priority', 'queue_take', 'queue_drop'])
    q = SNAP['queue']
    off = dict(SNAP, manage_releases=False, releases=[], release='', release_acts=[], release_said='', queue=[q[0], v5] + q[1:],
               status=[l for l in SNAP['status'] if not l.startswith('release')])
    on = dict(SNAP, manage_releases=True, releases=[r], queue=q + [dict(v5, release=r)])
    for snap, has in ((off, False), (on, True), ({k: v for k, v in on.items() if k != 'manage_releases'}, True)):
        said = f'manage_releases {snap.get("manage_releases")}: '
        p = page(snap)
        for i, l in enumerate(p.items(1)):
            p.cur[1] = i
            eq('release' in p.tab()[1], has, f'{said}the release tab of {l!r}')
        eq('release' in p.tab_list(1, None), has, said + 'the release tab with no status line')
        eq(('R', 'release') in p.hint_keys(), has, said + 'the hint in Status')
        p.key('?')
        text = drawn(p, 90, 160).text()
        eq(('R        release' in text, 'new release' in text), (has, has), said + 'the keys list')
        check('s y w u  quick asks' in text and 'U        take the stop back' in text, said + 'its other keys stay', text)
        p.key('ESC')
        eq('release' in drawn(page(dict(snap, queue=q))).text().lower(), has, said + 'a word of it, with no V task')
        for panel in ('1', '3'):
            p = page(snap)
            p.key(panel)
            was = (p.panel, p.main, p.tab()[0], dict(p.cur), p.msg)
            p.key('R')
            eq((p.panel, p.main, p.tab()[0]) == (1, True, 'release'), has, f'{said}R in panel {panel}')
            if not has:
                eq((p.panel, p.main, p.tab()[0], dict(p.cur), p.msg), was, f'{said}R in panel {panel} does nothing')
        p = page(snap)
        p.key('3')
        ids = [t['id'] for t in p.items(3) if t.get('id')]
        eq((ids.index('V5'), ids.count('V5')), (len(q) if has else 1, 1), said + 'where V5 is')
        p.cur[3] = ids.index('V5')
        text = drawn(p).text()
        eq(re.search(r'V5 +(release +)?Release · next', text) is not None, has, said + 'the row in its own words')
        eq('Release: bump the version' in text, True, said + 'V5 shows')
        eq(('R', 'new release') in p.hint_keys(), has, said + 'the hint on V5')
        eq(p.tab()[1], ['direct edit', 'chat edit'], said + 'its tabs')
        with mock.patch.object(U, 'move', lambda *a: {'ok': True, 'out': 'moved'}):
            p.key('J')
        eq(p.msg == 'V5 is a release: it stays at its place', has, said + 'J')
    live = dict(on)  # turned off while its tab is open
    p = page(live)
    p.key('R')
    eq(p.tab()[0], 'release', 'the tab is open')
    live.clear()
    live.update(off)
    eq(p.tab()[0], 'log', 'off: back to the log')
    ran = []
    with mock.patch.object(U, 'run_control', lambda key, **kw: (ran.append(key), {'ok': True, 'out': ''})[1]):
        for k in ('ENTER', 'f', 'D'):
            p.key(k)
    eq([k for k in ran if k.startswith('release')], [], 'and no key makes one')


def test_walk_f194c() -> None:
    """The example project's walkthrough: its card, its keys, the panel it points at; nowhere else."""
    print('F194c: the walkthrough')
    f = Path(tempfile.mkdtemp(prefix='f194c-')) / 'walk.json'
    other = page()
    check('Walkthrough' not in drawn(other).text() and not other.walk, 'not in another project')
    for k in '<>/':
        other.key(k)
        check(not other.msg and other.panel == 1, f'{k} does nothing there')
    check('walkthrough' not in T.help_text(True), 'nor in its keys list')
    p = page(walk=W.Walk(f))
    win = drawn(p, 40)
    txt = win.text()
    check('Walkthrough' in txt and 'The queue  1 of 7' in txt and 'side by side' in txt, 'the first card', txt)
    check('[> next]' in txt and '[/ skip]' in txt and '[< back]' not in txt, 'its keys', txt)
    check('[3] Queue ◂' in txt and txt.count('◂') == 1, 'its panel is marked', txt)
    eq(colour_at(win, '/ skip'), 'hkey', 'the key in the key colour')
    seen = []
    for _ in range(6):
        p.key('>')
        p.draw(win := Win(40, 120))
        seen.append((p.walk.at, p.panel, p.main, p.tab()[0]))
        check(f'  {p.walk.i + 1} of 7' in win.text(), f'{p.walk.at}: its card', win.text())
        for name in ('[1]', '[2]', '[3]', '[4]', '[5]'):
            check(f' {name} ' in win.text(), f'{p.walk.at}: panel {name} still shows', win.text())
    eq(seen, [('start', 1, False, 'controls'), ('session', 2, False, 'session'), ('needs', 4, False, 'answer'),
              ('land', 1, False, 'log'), ('chat', 2, False, 'info'), ('own', 2, False, 'info')], 'each goes to its place')
    check('[> done]' in win.text() and '[/ skip]' not in win.text(), 'the last is Done', win.text())
    p.key('<')
    eq(p.sel(), T.NEW_CHAT, 'back; the chat step is on the new chat row')
    eq(page(walk=W.Walk(f)).walk.at, 'chat', 'kept for the next time')
    p.key('/')
    check('again' in p.msg and 'Walkthrough' not in drawn(p, 40).text(), 'skipped', p.msg)
    p.key('1')
    check('/ walkthrough' in drawn(p, 40).lines()[-1], 'the bottom line has its key', drawn(p, 40).lines()[-1])
    check('walkthrough' in T.help_text(True, True), 'and the keys list')
    check(page(walk=W.Walk(f)).walk.off, 'skipped the next time too')
    p.key('/')
    check('6 of 7' in drawn(p, 40).text() and p.panel == 2, 'shown again where it was')
    p.key('3')
    p.key('n')
    p.key('/')
    check(p.typing and p.text_of(p.typing) == '/' and not p.walk.off, 'in a box it is typed')
    p.key('ESC')
    for h, w in ((24, 80), (24, 40), (12, 80), (8, 24), (3, 30)):
        for at in p.walk.ids:
            p.walk.at = at
            p.panel, p.main = W.PLACE[at][0] or 1, False
            win = drawn(p, h, w)
            if h == 24:
                last = W.words(p.walk.step, True, 2, 3).split()[-1]
                check(f'[{p.panel}]' in win.text() and last in win.text() and f'[> {"done" if p.walk.last else "next"}]' in win.text(),
                      f'{w}x{h}: {at}: its panel, its words, its keys', win.text())


if __name__ == '__main__':
    raise SystemExit(report([test_start_run_f402c2, test_walk_f194c, test_manage_releases_f193, test_always_tmux_f141, test_rename_f129, test_release_row_f131, test_new_drop_release_f186, test_project_name_b153, test_need_detail_f162, test_need_question_b223b, test_need_give_f175b, test_need_give_secret_f175b, test_quick_ask_names_session_c32,test_decide_options_f181c, test_sheet_buttons_f181b, test_concept_answer_b149, test_short_ask_b152,test_d_drops_f116, test_answer_direct_b138, test_answer_tab_b138, test_close_control_quiet_b136,test_layout, test_status_tabs, test_session_tabs, test_queue, test_kinds_f195b, test_form_pane_v_task,
                               test_direct_edit,
                               test_navigation, test_no_message_box_f112, test_new_chat_f112, test_new_chat_key_f153, test_side_pane_f112,
                               test_diff_key_f127, test_full_screen_f112, test_side_keys_in_box_f113, test_actions, test_session_tab_b125, test_footer,
                               test_concept_page,
                               test_concept_chat, test_new_concept, test_enter_on_concept, test_concept_as_need_f197b2,
                               test_escape_tail, test_colours, test_row_ground_and_fill, test_reorder, test_parked, test_shelved_f184,
                               test_themes,
                               test_idle_run_of_another_project, test_run_key_binds, test_run_controls,
                               test_follow_upgrade_f90, test_cli]))
