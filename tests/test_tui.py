#!/usr/bin/env python3
"""F67: the Run page in the terminal draws a snapshot in the lazygit layout, and its keys move focus and run
F65's actions.

    python3 tests/test_tui.py        (no curses, no run, no network; well under a second)

curses is stubbed: a window that keeps a grid of characters. A fixed snapshot is drawn at 100x30: the focused
panel takes the spare height and the unfocused queue shows 3 rows; at 60 columns the panels and the main pane
take the width in turn. Keys move focus and the cursor, and each action key, with canned typed answers and
the runner call swapped for a recorder, runs the plan command or c1 message it stands for.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import state as S  # noqa: E402
from agent_runner import tui as T  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402

SNAP = {
    'project': 'proj', 'at': '2026-11-21T10:00:00', 'up': True,
    'status': ['run up: 3 slots', '4 tasks left', 'release: waits on 2 of 2', 'usage: session 42%, week 85%'],
    'sessions': [
        {'name': 'c1', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
         'link': 'https://claude.ai/code/session_c1', 'terminal': ''},
        {'name': 's1', 'task': 'F1', 'title': 'Board page for the run', 'minutes': 14, 'state': 'running',
         'files': ['a.py'], 'link': 'https://claude.ai/code/session_1', 'terminal': ''},
        {'name': 's2', 'task': 'B2', 'title': 'Fix the merge retry', 'minutes': 1, 'state': 'merging',
         'files': ['b.py'], 'link': '', 'terminal': ''}],
    'queue': [{'id': f'Q{i}', 'kind': 'feature', 'title': f'Queued task number {i}', 'files': [f'q{i}.py'],
               'after': [], 'pri': 'normal', 'section': 'Next', 'blocked': False} for i in range(1, 10)],
    'needs': [{'label': 'DECIDE', 'id': 'D3', 'concept': '', 'title': 'Write the guide', 'what': 'which layout',
               'url': 'https://claude.ai/artifact/abc', 'ask': 'Which layout?', 'age': '2h'}],
    'concepts': [{'id': 'F4', 'concept': 'K5', 'title': 'Lazy layout', 'url': 'https://claude.ai/artifact/k5'}],
    'log': [f'=== 10:{i:02d} line {i}' for i in range(20)], 'release': 'release: waits on 2 of 2',
}


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


ATTRS = {'red': 1, 'sel': 1 << 10, 'line': 2}


def page(**kw) -> T.RunPage:
    return T.RunPage(SNAP, get_snap=lambda: SNAP, attrs=ATTRS, **kw)


def queue_ids_shown(win: Win) -> list[str]:
    left = [l[:36] for l in win.lines()]  # the panels' column at 100 wide
    return [f'Q{i}' for i in range(1, 10) if any(f'Q{i} Queued' in l for l in left)]


def test_layout() -> None:
    p, win = page(), Win(30, 100)
    p.key('2')
    p.draw(win)
    txt = win.text()
    for title in ('[1] Status', '[2] Sessions', '[3] Queue', '[4] Needs you', '[5] Concepts'):
        check(title in txt, f'{title} is drawn', txt)
    eq(queue_ids_shown(win), ['Q1', 'Q2', 'Q3'], 'the unfocused queue shows 3 rows')
    check('1 of 10 · 3 to expand' in txt, 'the unfocused queue counts its rows and says how to expand', txt)
    check('agent-runner · proj' in win.lines()[0], 'the top line names the project', win.lines()[0])
    check(win.lines()[-1].startswith(' SESSIONS '), 'the bottom line names the focused panel', win.lines()[-1])
    check('│ s1 F1 Board page for the run 14m │' in txt, 'a slot row: name, task, title, minutes, cut to the box',
          txt)
    p.key('3')
    p.key('2')
    wide = Win(30, 200)
    p.draw(wide)
    check('s1 F1 Board page for the run 14m running' in wide.text(), 'wider, the row shows its state', wide.text())
    row = next(y for y, l in enumerate(win.lines()) if ' c1 control session' in l[:36])
    check(win.colour[row][5] & ATTRS['sel'], 'the cursor row of the focused panel is highlighted')
    check('Sessions' in txt and 'chat' in win.lines()[1], 'the main pane shows the selected item\'s tab', win.lines()[1])

    p.key('3')
    win = Win(30, 100)
    p.draw(win)
    eq(queue_ids_shown(win), [f'Q{i}' for i in range(1, 10)], 'focused, the queue takes the spare height')
    hs = p.heights(28)
    eq((hs[1], hs[2], hs[4], hs[5]), (5, 5, 3, 3), 'unfocused panels: 3 rows or fewer, plus the border')
    eq(sum(hs.values()), 28, 'the panels fill the body')
    check('Queued task number 1' in win.lines()[2][36:], 'the main pane shows the queued task', win.lines()[2])

    p.key('4')
    p.draw(win)
    eq(queue_ids_shown(win), ['Q1', 'Q2', 'Q3'], 'unfocused again, the queue is back to 3 rows')
    check(any('Which layout?' in l[36:] for l in win.lines()), 'the main pane shows the ask', win.text())
    lines = T.wrap([('alpha beta ', 'fg'), ('gamma delta', 'dim')], 12)
    eq([''.join(t for t, _ in l) for l in lines], ['alpha beta ', 'gamma delta'], 'a long pane line wraps at a space')
    eq(lines[1], [('gamma delta', 'dim')], 'and keeps its colours')

    narrow = Win(30, 60)
    p.key('3')
    p.draw(narrow)
    check('[3] Queue' in narrow.text() and 'kind ' not in narrow.text(), 'narrow: the panels take the width',
          narrow.text())
    p.key('ENTER')
    p.draw(narrow)
    check('kind feature' in narrow.text() and '[3] Queue' not in narrow.text(),
          'narrow, Enter: the main pane takes the width', narrow.text())
    p.key('ESC')
    eq(p.main, False, 'Esc backs out of the main pane')

    p.key('?')
    p.draw(win)
    check('Keybindings' in win.text(), '? shows the keys', win.text())
    p.key('ESC')
    eq(p.help, False, 'Esc closes the keys')
    tiny = Win(5, 20)
    p.draw(tiny)
    check('too small' in tiny.text(), 'a tiny terminal is told so', tiny.text())


def test_keys() -> None:
    p = page()
    eq(p.panel, 1, 'starts on Status')
    p.key('l')
    eq(p.panel, 2, 'l: the next panel')
    p.key('TAB')
    eq(p.panel, 3, 'Tab: the next panel')
    p.key('BTAB')
    eq(p.panel, 2, 'Shift-Tab: the previous panel')
    p.key('j')
    p.key('DOWN')
    eq(p.cur[2], 2, 'j and Down move the cursor')
    p.key('j')
    eq(p.cur[2], 2, 'the cursor stops at the last row')
    p.key('k')
    eq(p.cur[2], 1, 'k moves it up')
    p.key('ENTER')
    eq((p.main, p.tab()[0]), (True, 'info'), 'Enter goes into the main pane, on the first tab')
    p.key(']')
    eq(p.tab()[0], 'terminal', '] moves to the next tab')
    p.key('5')
    eq((p.panel, p.main), (5, False), 'a digit focuses its panel')
    eq(p.key('q'), True, 'q quits')


def test_actions() -> None:
    repo = Path(tempfile.mkdtemp()) / 'proj'  # an answer reads the plan for the item's title: an empty one
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / 'plan' / 'TODO.md').write_text('# TODO\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    ran, sent, attached = [], [], []
    real_run, real_send = U.RUN[0], U.SEND[0]
    U.RUN[0] = lambda argv: (ran.append(argv), (0, 'ok: ' + ' '.join(argv)))[1]
    U.SEND[0] = lambda text: (sent.append(text), {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []})[1]
    answers: list = []
    p = page(ask=lambda prompt, default='': answers.pop(0) if answers else None,
             attach=lambda name: (attached.append(name), {'ok': True, 'out': f'back from {name}'})[1])
    try:
        p.key('3')
        p.key('j')
        answers[:] = ['Queued task number 2, sharper', 'q2.py,tests/test_q2.py', '', 'critical']
        p.key('e')
        answers[:] = ['overtaken']
        p.key('D')
        p.key('h')
        answers[:] = ['also cover openmx']
        p.key('E')
        answers[:] = ['B', 'Fix the flicker', 'menu.py,tests/test_menu.py', 'Q1', 'normal']
        p.key('n')
        answers[:] = ['Queued task number 2', 'q2.py', '', 'normal']  # every field as it was
        p.key('e')
        eq(p.msg, 'nothing changed', 'an edit that changes nothing runs nothing')
        answers[:] = [None]
        p.key('D')
        p.key('4')
        answers[:] = ['the lazy one']
        p.key('a')
        p.key('L')
        p.key('5')
        answers[:] = ['go with A']
        p.key('p')
        answers[:] = ['how is it going?']
        p.key('c')
        eq((p.panel, p.cur[2]), (2, 0), 'c focuses c1')
        answers[:] = ['']
        p.key('R')
        answers[:] = ['f']
        p.key('R')
        answers[:] = [None]
        p.key('R')
        p.key('1')
        p.key('t')
        eq((p.panel, p.sel()['name'], p.tab()[0]), (2, 's1', 'terminal'), 't goes to the first slot\'s terminal')
        p.key('j')
        p.key(']')
        eq(p.tab()[0], 'terminal', '] on s2: its terminal tab')
        p.key('ENTER')
        eq(p.msg, 'back from s2', 'the result of an action shows on the bottom line')
        eq(ran, [['plan', 'edit', 'Q2', 'Queued task number 2, sharper', '--files', 'q2.py,tests/test_q2.py', '--pri', 'critical'],
                 ['plan', 'drop', 'Q2', 'overtaken'],
                 ['plan', 'add', 'B', 'Fix the flicker', '--files', 'menu.py,tests/test_menu.py', '--after', 'Q1'],
                 ['plan', 'shelve', 'D3'],
                 ['plan', 'add', 'V'],
                 ['plan', 'add', 'V', '--now']], 'each key runs its plan command')
        eq(sent, ['do Q2 here', 'change Q2: also cover openmx', 'D3: the lazy one',
                  'concept K5 ("Lazy layout"): go with A', 'how is it going?'],
           'take, chat edit, answer, pick and chat go to c1')
        eq(attached, ['s1', 's2'], 't and Enter on the terminal tab attach the slot\'s pane')
        U.RUN[0] = lambda argv: (3, 'looks like Q1\nmore')
        p.key('3')
        answers[:] = ['F', 'Board page', '', '', 'normal']
        p.key('n')
        eq((p.msg, p.msg_ok), ('looks like Q1', False), 'a refused action shows its first line, in red')
    finally:
        U.RUN[0], U.SEND[0] = real_run, real_send


def test_cli() -> None:
    from agent_runner import cli
    eq(cli.COMMANDS.get('ui'), ('tui', 'main'), '`agent-runner ui` runs the terminal Run page')
    check('agent-runner ui' in cli.USAGE, 'the command list names `ui`')
    eq(T.main(['--nope']), 2, 'ui takes no arguments')


if __name__ == '__main__':
    raise SystemExit(report([test_layout, test_keys, test_actions, test_cli]))
