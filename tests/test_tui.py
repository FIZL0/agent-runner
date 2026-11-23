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

import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import state as S  # noqa: E402
from agent_runner import tui as T  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

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
               'url': 'https://claude.ai/artifact/k5', 'ask': 'Pick an option for lazy layout', 'age': '1d'},
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

FEEDS = {
    'c1': [{'kind': 'you', 'text': 'status?'}, {'kind': 'tool', 'text': 'Bash(./run status -n 20)'},
           {'kind': 'out', 'text': 'run up: 3 slots'}, {'kind': 'say', 'text': 'Nothing needs you beyond D3.'}],
    'c6': [{'kind': 'you', 'text': 'ideas for themes?'}, {'kind': 'tool', 'text': 'Read(theme.py)'}],
    's1': [{'kind': 'say', 'text': 'I will start with the board.'}, {'kind': 'tool', 'text': 'Read(a.py)'},
           {'kind': 'out', 'text': '120 lines'}, {'kind': 'tool', 'text': 'Edit(a.py)'},
           {'kind': 'say', 'text': 'Edited; running the tests.'}],
}
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
    kw.setdefault('feed', lambda name: {'ok': name in FEEDS, 'name': name, 'entries': list(FEEDS.get(name, [])),
                                        'more': False, 'link': ''})
    kw.setdefault('diff', lambda name: DIFF)
    kw.setdefault('read', lambda path: COPY if path.endswith('K5.html') else '')
    kw.setdefault('opener', lambda url: {'ok': True, 'out': f'opened {url}'})
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
    check('agent-runner · proj' in win.lines()[0], 'the top line names the project', win.lines()[0])
    check('? keys' not in win.lines()[0], 'the top line shows no key (the bottom line has ? keys)', win.lines()[0])
    check(win.lines()[-1].startswith(' SESSIONS '), 'the bottom line starts with the mode badge', win.lines()[-1])
    eq([r['name'] for r in p.items(2)], ['c1', 'c6', 's1', 's2', 's3', '+'],
       'Sessions: c1, the other control sessions, every slot (idle s3 too), then the new chat row')
    check(any('+ new chat N' in l[:36] for l in win.lines()), "Sessions' last row: '+ new chat' with its key", txt)
    eq(colour_at(win, 'new chat N', 9), 'hkey', 'the row shows N in the key colour')
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
    eq(p.tab(), ('chat', ['chat', 'log', 'release', 'controls']), 'a status line: chat, log (and release, controls)')
    p.key('ENTER')
    win = drawn(p)
    for b in ('[s since last look]', '[y since yesterday]', '[w what needs me]', '[u usage]'):
        check(b in win.text(), f'the Status chat shows the quick ask {b}', win.text())
    eq((colour_at(win, '[s since', 1), colour_at(win, '[s since', 3)), ('hkey', 'fg'),
       'a quick ask: its key in the key colour, its label in the text colour')
    check('● Nothing needs you beyond D3.' in win.text(), "c1's words in the chat", win.text())
    check('Bash(./run status -n 20)' in win.text(), 'a chat shows its tool steps, as a Claude session does')
    check('❯ message c1' in win.text(), 'the chat box with its placeholder')
    p.key('l')
    eq(p.tab()[0], 'log', 'l: the next tab')
    check('line 19' in drawn(p).text(), 'the log tab shows the newest lines')
    p.key('h')
    p.key('h')
    eq((p.main, p.tab()[0]), (False, 'chat'), 'h on the first tab goes back to the panels')
    p.key('j')
    p.key('j')
    eq(p.tab(), ('release', ['release', 'chat', 'log', 'controls']), 'the release line: release first')
    p.key('ENTER')
    win = drawn(p)
    check('[⏎ release when the running tasks land]' in win.text() and '[f release now, without them]' in win.text(),
          'the release tab: its two buttons', win.text())
    eq(colour_at(win, '[⏎ release when', 1), 'pkey', 'the primary button: its key red')
    check('F1 Board page for the run in s1' in win.text(), 'it lists the running tasks', win.text())


def test_session_tabs() -> None:
    p = page()
    p.key('2')
    eq(p.tab()[1], ['chat', 'pane', 'session'], 'a control session: chat, pane, session')
    p.cur[2] = 2
    eq(p.tab()[1], ['feed', 'pane', 'diff', 'session'], 'a slot on a task: feed, pane, diff, session')
    p.key('ENTER')
    win = drawn(p)
    check('● I will start with the board.' in win.text(), 'the feed: the agent\'s words', win.text())
    check('· 2 steps' in win.text() and 'Read(a.py)' not in win.text(), "tool steps folded as '· N steps'",
          win.text())
    check('❯ message s1 (it reads it between steps)' in win.text(), 'a box to message the slot', win.text())
    p.key('v')
    win = drawn(p)
    check('Read(a.py)' in win.text() and '⎿ 120 lines' in win.text(), 'v shows the steps', win.text())
    p.key('v')
    p.key('l')
    win = drawn(p)
    check('s1 runs in a tmux pane' in win.text() and '[⏎ attach s1]' in win.text(), 'the pane tab', win.text())
    p.key('l')
    win = drawn(p)
    eq((colour_at(win, '+new line'), colour_at(win, '-old line'), colour_at(win, '@@ -1,2')),
       ('green', 'red', 'cyan'), 'the diff tab: added green, removed red, hunks cyan')
    p.key('l')
    win = drawn(p)
    check('https://claude.ai/code/session_1' in win.text() and '[o open it]' in win.text(), 'the session tab',
          win.text())
    p.key('l')
    eq(p.tab()[0], 'session', 'l on the last tab stays there')
    p.cur[2] = 4
    eq(p.tab()[1], ['feed', 'pane'], 'an idle slot: feed, pane')
    check('s3 is idle: nothing running' in drawn(p).text(), "an idle slot's feed says so")
    p.cur[2] = 5
    eq(p.tab()[1], ['info'], "the '+ new chat' row: info")
    check('[N start one]' in drawn(p).text(), 'it says N starts one')
    p.cur[2] = 1
    p.tabs[p._tab_key(p.sel())] = 'chat'
    win = drawn(p)
    check('❯ ideas for themes?' in win.text(), "c6's chat shows the person's words", win.text())


def test_queue() -> None:
    p = page()
    p.key('3')
    win = drawn(p, 32, 100)
    eq(p.tab()[1], ['direct edit', 'chat edit'], 'a task: direct edit, chat edit (no info tab)')
    eq((colour_at(win, 'B2 '), colour_at(win, 'C3 '), colour_at(win, 'Q4 ')), ('red', 'blue', 'cyan'),
       'kind-coloured ids: B red, C blue')
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
        eq(p.form(p.sel())['pri'], 'normal', 'p toggles the priority (critical to normal)')
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
    p.key('ENTER')
    p.key('l')
    eq(p.tab()[0], 'pane', 'l: next tab')
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
    p.key('c')
    eq((p.panel, p.sel()['name'], p.tab()[0], p.typing), (2, 'c1', 'chat', 'c1:chat'), 'c: c1\'s chat, typing')
    p.key('ESC')
    p.key('2')
    p.cur[2] = 3
    p.key('t')
    eq((p.sel()['name'], p.tab()[0], p.main), ('s2', 'feed', True), 't: the slot\'s feed')
    p.key('j')
    p.key('j')
    eq(p.off.get(p.place()), None or 0, 'j/k scroll the pane (none to scroll here)')
    eq(p.key('q'), True, 'q quits')


def test_chat_box() -> None:
    p = page()
    sent, stopped = [], []
    with mock.patch.object(U, 'chat_to', lambda text, to='c1': (sent.append((to, text)), {'ok': True, 'out': f'sent to {to}'})[1]), \
            mock.patch.object(U, 'interrupt', lambda name='c1': (stopped.append(name), {'ok': True, 'out': f'interrupted {name}'})[1]):
        p.key('2')
        p.key('j')  # c6, mid-turn: its newest entry is a tool step
        p.key('i')
        eq((p.typing, p.mode()), ('c6:chat', 'INSERT'), 'i: typing in c6\'s chat box, the badge says INSERT')
        for c in 'hello':
            p.key(c)
        p.key('S-ENTER')
        for c in 'there':
            p.key(c)
        win = drawn(p)
        check('❯ hello' in win.text() and '  there█' in win.text(), 'Shift+Enter: a new line in the box', win.text())
        check(('Ctrl+C', 'interrupts') in p.hint_keys(), 'the hint while it works: '
              'Ctrl+C interrupts', p.hint_keys())
        eq(p.key('^C'), False, 'Ctrl+C in a working chat does not quit')
        eq((stopped, p.typing), (['c6'], 'c6:chat'), 'Ctrl+C interrupts while it works (the box stays)')
        p.key('ESC')
        eq((stopped, p.typing, p.drafts.get('c6:chat')), (['c6'], '', 'hello\nthere'), 'B116: Esc in a working chat '
           'leaves the box and sends no interrupt; the draft stays')
        p.key('ESC')
        eq((stopped, p.main), (['c6'], False), 'B116: Esc on the working chat tab goes back, no interrupt')
        p.key('ENTER')
        eq(p.tab()[0], 'chat', 'Enter: back on c6\'s chat tab')
        eq(p.key('^C'), False, 'Ctrl+C on the working chat tab does not quit')
        eq(stopped, ['c6', 'c6'], 'Ctrl+C on the working chat tab interrupts')
        FEEDS['c6'].append({'kind': 'say', 'text': 'Three to start.'})
        p.cache.clear()
        p.refresh()
        p.key('k')
        p.key('j')
        p.key('i')
        eq(p.text_of('c6:chat'), 'hello\nthere', 'the draft is kept across Esc, a move and a refresh')
        p.key('ENTER')
        eq((sent, p.drafts.get('c6:chat'), p.typing), ([('c6', 'hello\nthere')], None, 'c6:chat'),
           'Enter sends to c6 and clears the box; a chat keeps typing')
        p.key('ESC')
        p.key('1')
        p.key('ENTER')
        p.key('i')
        for c in 'hi':
            p.key(c)
        eq(p.drafts.get('c6:chat'), None, 'each box keeps its own draft')
        p.key('ENTER')
        eq(sent[-1], ('c1', 'hi'), "Status's chat goes to c1")
    FEEDS['c6'].pop()


def test_actions() -> None:
    repo = Path(tempfile.mkdtemp()) / 'proj'  # an answer reads the plan for the item's title: an empty one
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    ran, sent, attached, opened, calls = [], [], [], [], []
    ok = lambda out: {'ok': True, 'code': 0, 'out': out, 'argv': []}  # noqa: E731
    p = page(attach=lambda name: (attached.append(name), {'ok': True, 'out': f'back from {name}'})[1],
             opener=lambda url: (opened.append(url), {'ok': True, 'out': f'opened {url}'})[1])
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok: ' + ' '.join(argv)))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), ok('sent to c1'))[1]]), \
            mock.patch.object(U, 'send', lambda name, text: (calls.append(('send', name, text)), ok('sent'))[1]), \
            mock.patch.object(U, 'quick_ask', lambda key: (calls.append(('quick_ask', key)), ok('asked'))[1]), \
            mock.patch.object(U, 'new_control', lambda ask='': (calls.append(('new_control',)),
                                                                {**ok('started c7'), 'link': 'https://claude.ai/code/x'})[1]), \
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
        check('[y yes] [n no] [L later]' in win.text(), 'a yes/no ask: y yes, n no, L later buttons', win.text())
        check('❯ or your own reply' in win.text(), 'and the free reply box', win.text())
        p.key('y')
        eq(p.main, False, 'an answer sent: back to the panels')
        p.key('j')
        p.key('ENTER')
        win = drawn(p)
        check('[a Option A] [b Option B] [c A + B · recommended]' in win.text(), "a pick: the concept's options as "
              'a b c', win.text())
        p.key('c')
        p.key('j')
        p.key('ENTER')
        p.key('i')
        for c in 'port 8770':
            p.key(c)
        p.key('ENTER')
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
        p.key('l')
        p.key('ENTER')
        p.key('i')
        eq(p.typing, '', 'nothing to type into on the pane tab')
        p.key('h')
        p.key('i')
        for c in 'use the cache':
            p.key(c)
        p.key('ENTER')
        p.key('ESC')
        p.key('ESC')
        p.cur[2] = 0
        p.key('o')
        c7 = {'name': 'c7', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
              'link': 'https://claude.ai/code/x', 'terminal': ''}
        p.get_snap = lambda: dict(SNAP, sessions=SNAP['sessions'][:2] + [c7] + SNAP['sessions'][2:]) \
            if ('new_control',) in calls else SNAP
        p.key('N')
        eq(p.sel()['name'], 'c7', 'N selects the new control session')
        eq((p.msg, p.main, p.tab()[0]), ('new control session: https://claude.ai/code/x', True, 'session'),
           'N: a new control session, its link said')
    eq(ran, [['plan', 'edit', 'B2', '--pri', 'normal'],
             ['plan', 'drop', 'B2', 'dropped from agent-runner ui'],
             ['plan', 'move', 'Q1', 'after', 'B2'],
             ['plan', 'shelve', 'D7'],
             ['plan', 'add', 'V'],
             ['plan', 'add', 'V', '--now']], 'p, D, J, L and the release buttons run their plan commands')
    eq(sent, ['do B2 here', 'change B2: also cover openmx', 'new task: show usage too', 'D3: yes', 'F4: A + B · recommended',
              'D7: port 8770', 'concept K5 ("Lazy layout"): go with Option B',
              'concept K5 ("Lazy layout"): smaller'],
       'H, chat edits, answers (a button, a reply), the concept pick and its change go to c1')
    eq(calls, [('quick_ask', 'since'), ('quick_ask', 'usage'), ('open_session', 's1'), ('send', 's1', 'use the cache'),
               ('new_control',)], 'o, the quick asks, the slot\'s box and N run F74\'s actions')
    eq(opened, ['https://claude.ai/artifact/k5', 'https://claude.ai/code/s1', 'https://claude.ai/code/session_c1'],
       'O and o open the browser')
    eq(attached, ['s1'], 'Enter on the pane tab attaches the slot\'s pane')


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
                    p.key('ENTER')
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
    page_ = T.concept_page(COPY)
    eq((page_['title'], page_['intro']), ('Lazy layout', ['Three ways to lay out the run page.']), 'title, intro')
    eq([(o['name'], o['rec']) for o in page_['options']],
       [('Option A', False), ('Option B', False), ('A + B · recommended', True)], 'the options: its headings')
    eq(page_['options'][0]['body'], ['One page the runner republishes.'], 'each with what follows it')
    styled = '<style>.t{}</style><h1>Live run page</h1><p>Four options.</p><div class="o"><div class="t">Option A' \
             '</div>The runner republishes.</div><div class="o r"><div class="t">A + C · recommended</div>Hub.</div>'
    eq([o['name'] for o in T.concept_page(styled)['options']], ['Option A', 'A + C · recommended'],
       "the run page's own style: an option's title in a .t element")
    eq(T.concept_page('')['options'], [], 'no page: no options')
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
            mock.patch.object(status, 'waiting_ok', lambda: []):
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
    p, win = T.RunPage(SNAP, get_snap=lambda: SNAP, attrs=attrs, feed=lambda n: {'entries': []}), Win(30, 100)
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
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'ok'))[1]]):
        p = T.RunPage(snap, get_snap=lambda: dict(snap), attrs=ATTRS)
        p.key('3')
        p.cur[3] = len(snap['queue']) - 1
        eq(p.sel()['id'], 'F83', 'the parked row selected')
        check(' parked' in drawn(p, 32, 100).text(), "the open parked row shows its 'parked' tag")
        p.key('k')  # off the selected row's ground, so the tag draws in its own colour
        win = drawn(p, 40, 100)
        check(' parked' in win.text() and colour_at(win, ' parked', 1) == 'dim', "unfocused, the tag is dim",
              win.text())
        check('F83  Parked big work  ready' not in win.text(), 'never ready')
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
        p, win = T.RunPage(SNAP, get_snap=lambda: SNAP, attrs=attrs, feed=lambda n: {'entries': []}), Win(30, 100)
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
    """B113: an idle 5-slot run (iFizBox's: no slot windows, control session windows named by title) lists c1,
    c6 and c9 with their titles and s1-s5 idle; an idle slot's pane says so instead of attaching."""
    repo = Path(tempfile.mkdtemp()) / 'iFizBox'
    repo.mkdir(parents=True)
    git(repo, 'init', '-q')
    S.init(repo)
    s = 'ar-iFizBox'
    listing = [f'{s}\trunner-iFizBox\t\t', f'{s}\tboard-iFizBox\tboard\t{repo}', f'{s}\tiFizBox\t\t',
               f'{s}\tiFizBox · 9 · iOS 26 native glass +\tc9\t{repo}', f'{s}\tiFizBox\t\t',
               f'{s}\tiFizBox · 1 · Install IPAs row + wider\tc1\t{repo}',
               f'{s}\tiFizBox · 6 · Pairing broken: Tailscale logout\tc6\t{repo}']
    S.C.notes('STATE').write_text('{"state": "5 slots, usage caps off (f)", "running": {}, "idle": true}',
                                  encoding='utf-8')
    with mock.patch.object(U, 'tmux_panes', return_value=listing):
        snap = U.snapshot(up=True, links={})
    attached = []
    p = page(snap, attach=lambda name: (attached.append(name), {'ok': False, 'out': 'no pane'})[1])
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
    p.key('l')
    eq(p.tab()[0], 'pane', "s2's pane tab")
    check('s2 is idle: nothing running' in drawn(p).text(), 'it says s2 is idle')
    p.key('ENTER')
    eq((attached, p.msg), ([], 's2 is idle: nothing running'), 'Enter on an idle slot: the idle line, no attach')
    p.key('ESC')
    p.cur[2] = 1  # c6
    p.key('ENTER')
    p.key('l')
    p.key('ENTER')
    eq(attached, ['c6'], 'Enter on a control session\'s pane tab attaches it')


def test_older_run() -> None:
    """C23: a run an older agent-runner started (no tagged panes): Sessions has no rows, the one restart line."""
    snap = {'up': True, 'status': ['run up: 3 slots'], 'slots': 3, 'sessions': [],
            'sessions_note': U.OLDER_RUN, 'queue': [], 'needs': [], 'concepts': [], 'log': []}
    p = page(snap, attach=lambda name: {'ok': False, 'out': ''})
    eq(p.items(2), [], 'no rows, not even the idle slots or the new chat row')
    win = Win(30, 140)
    p.key('2')
    p.draw(win)
    check('started by an older agent-runner' in win.text(), 'Sessions shows the restart line', win.text())


def test_run_controls() -> None:
    """F82: each run control's key in Status [1] (a slot's task controls in Sessions [2]) runs its runner command
    through ui_model's one list; stop now (X) runs only on X again."""
    ran, sent = [], []
    want = {'+': ['slots', '+1'], '-': ['slots', '-1'], 'P': ['pause'], 'G': ['pause', '--off'], 'F': ['force'],
            'C': ['force', '--off'], 'S': ['stop'], 'U': ['stop', '--undo']}
    with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'sent to the run'))[1]]), \
            mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent',
                                                                             'argv': []})[1]]):
        eq({c['tui'] for c in U.controls() if c['where'] == 'run'} - set(want), {'=', 'X'},
           'every run control has its key here (= and X tested below)')
        for k, argv in want.items():
            p = page()
            ran.clear()
            p.key(k)
            eq(ran, [argv], f'{k} runs {" ".join(argv)}')
        p = page()
        p.key('ENTER')
        p.key('l')
        p.key('l')
        p.key('l')
        eq(p.tab()[0], 'controls', 'Status has a controls tab')
        win = drawn(p, w=140)
        for b in ('[+ slot +1]', '[- slot -1]', '[= set slots]', '[P pause]', '[G go on]', '[F force past the caps]',
                  '[C caps back on]', '[S stop (running tasks finish)]', '[X stop now]', '[U take the stop back]'):
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
        check('[H take back]' in win.text() and '[D drop]' in win.text(), "a slot's feed shows its task controls",
              win.text())
        p.key('D')
        eq(ran, [['plan', 'drop', 'F1', U.TASK_DROP_WHY]], 'D on a slot drops its task from the slot')
        p.key('H')
        eq(sent, ['do F1 here'], 'H on a slot takes its task back (c1 does it here)')
        ran.clear()
        p.cur[2] = 0  # c1: no task controls
        p.key('D')
        eq(ran, [], 'D on a control session does nothing')
        p.cur[2] = 3  # s2 lands B2 (merging)
        p.key('D')
        eq(ran, [], 'D on a slot whose task is landing does nothing')
        p.key('ENTER')
        check('[D drop]' not in drawn(p).text(), "a landing slot's feed shows no task controls")


def test_cli() -> None:
    from agent_runner import cli
    eq(cli.COMMANDS.get('ui'), ('tui', 'main'), '`agent-runner ui` runs the terminal Run page')
    check('agent-runner ui' in cli.USAGE, 'the command list names `ui`')
    eq(T.main(['--nope']), 2, 'ui takes no arguments')


if __name__ == '__main__':
    raise SystemExit(report([test_layout, test_status_tabs, test_session_tabs, test_queue, test_direct_edit,
                               test_navigation, test_chat_box, test_actions, test_footer, test_concept_page,
                               test_concept_chat,
                               test_escape_tail, test_colours, test_row_ground_and_fill, test_reorder, test_parked,
                               test_themes,
                               test_idle_run_of_another_project, test_older_run, test_run_controls, test_cli]))
