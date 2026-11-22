"""F67: the Run page in the terminal: `agent-runner ui`.

The same panels, keys and actions as the web Run page, in curses (standard library, no new dependency), in the
lazygit layout: numbered boxed panels on the left ([1] Status, [2] Sessions, [3] Queue, [4] Needs you,
[5] Concepts), one main pane on the right with the selected item's tabs, the key hints on the bottom line.
The focused panel takes the spare height; every other panel shows 3 rows. Narrower than `TWO_COLUMNS`, the
panels and the main pane take the whole width in turn (Enter in, Esc out), as the page does on a phone.

Colours: F69's `[ui] theme` (theme.py, shared with the web page): ryha by default (black ground, red #ef4444
accent, tailwind-ish ANSI), omarchy, terminal (the terminal's own 16 colours and background) or light, each
mapped to the nearest of the terminal's 256 colours (8 on an older terminal). The font is the terminal's own.

What it shows is `ui_model.snapshot()`, read again every `REFRESH` seconds; what it does is `ui_model`'s
actions (plan add, plan edit, drop, shelve, release; chat, answers and take through c1), so the terminal
changes the run exactly as the web page does. The terminal key (`t`) switches to the slot's tmux pane
(`attach sN`): outside tmux Ctrl-b d comes back to this screen, inside tmux Ctrl-b L does.

The screen logic (`RunPage`) draws on any object with curses' window calls (`getmaxyx`, `erase`, `addnstr`),
and asks for typed text through `RunPage.ask`, so a test drives it with a stub window and canned answers.
"""

from __future__ import annotations

import os
import re
import subprocess as sp
import sys
import time

from agent_runner import theme as TH
from agent_runner import ui_model as U

REFRESH = 3.0  # seconds between snapshots
TWO_COLUMNS = 70  # narrower than this: one column, the panels or the main pane
SHORT = 3  # rows an unfocused panel shows

PANELS = [(1, 'Status', 'status'), (2, 'Sessions', 'sessions'), (3, 'Queue', 'queue'),
          (4, 'Needs you', 'needs'), (5, 'Concepts', 'concepts')]
NEW_TASK = {'id': '+', 'new': True}  # the queue's last row: a new task

# F69: the colours a segment can name, each a token of the theme (theme.py); 'accent' is the theme's accent
# (red in ryha), 'key' a key on the hint line (F70: bold, the brightest white). B112: a selected row draws every
# segment on its row background: each colour gets a pair on the focused row's ('sel:red') and on the unfocused
# selected row's ('cur:cyan'); ids keep their colour, dim text turns readable on the lighter ground
COLOURS = ('fg', 'dim', 'line', 'accent', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'key')


def session_rows(snap: dict) -> list:
    """B112: the Sessions panel's rows: c1, then every slot of the run, an idle one (no task) included, as the
    design lists them. The slot count is the snapshot's `slots` (F71; the snapshot lists idle slots itself),
    else, from a snapshot without it, the run's status line ('run up: 3 slots, ...')."""
    rows = list(snap.get('sessions') or [])
    count = snap.get('slots')
    if not isinstance(count, int) or isinstance(count, bool):
        m = re.match(r'run up: (\d+) slots?\b', ((snap.get('status') or ['']) + [''])[0]) if snap.get('up') else None
        count = int(m.group(1)) if m else 0
    have = {r.get('name') for r in rows if isinstance(r, dict)}
    for n in range(1, count + 1):
        if f's{n}' not in have:
            rows.append({'name': f's{n}', 'task': '', 'title': '', 'minutes': None, 'state': 'idle', 'files': [],
                         'link': '', 'terminal': ''})
    slot = lambda r: (not is_control(r), not str(r.get('name', ''))[1:].isdigit(),  # noqa: E731
                      str(r.get('name', ''))[1:].zfill(4))
    return sorted(rows, key=slot)


def is_control(row) -> bool:
    """B113: a control session's row (c1, c6), not a slot's."""
    return isinstance(row, dict) and bool(re.fullmatch(r'c\d+', str(row.get('name', ''))))


def idle_line(row: dict) -> str:
    """B113: what an idle slot's terminal says instead of an error: no window is open while it has no task."""
    return f'{row.get("name", "")} is idle: nothing running'

HELP = """Global
  1-5      focus a panel          h/l Tab  previous / next panel (h on the queue: do it here)
  j/k      move down / up         Enter 0  into the main pane
  [ ]      previous / next tab    Esc      back out
  t        terminal of the slot   c        chat with c1
  i        type in the pane       R        release
  o        the session's link     ?        this list
  q        quit

Queue [3]
  n        new task               e        direct edit
  E        chat edit              D        drop
  h        do it here             J/K      move the task down / up

Needs you [4]
  a        answer                 L        later

Concepts [5]
  p        pick an option

Esc closes this."""

KEYS = {'j': 'DOWN', 'k': 'UP', '0': 'ENTER', '\n': 'ENTER', '\r': 'ENTER', '\t': 'TAB', '\x1b': 'ESC'}


def wrap(segs: list[tuple[str, str]], width: int) -> list[list[tuple[str, str]]]:
    """One line of (text, colour) segments as lines of at most `width` columns, broken at spaces when it can."""
    chars = [(c, colour) for text, colour in segs for c in text.replace('\n', ' ')]
    if width <= 0 or len(chars) <= width:
        return [segs]
    out = []
    while chars:
        cut = width if len(chars) > width else len(chars)
        if cut < len(chars):
            space = max((i for i in range(cut) if chars[i][0] == ' '), default=0)
            cut = space + 1 if space > width // 3 else cut
        line, chars = chars[:cut], chars[cut:]
        run: list[tuple[str, str]] = []
        for c, colour in line:
            if run and run[-1][1] == colour:
                run[-1] = (run[-1][0] + c, colour)
            else:
                run.append((c, colour))
        out.append(run)
    return out


class RunPage:
    """The terminal Run page's state and drawing; `key()` takes one key, `draw()` paints one frame."""

    def __init__(self, snap: dict, get_snap=None, ask=None, attach=None, attrs=None):
        self.snap = snap
        self.get_snap = get_snap or (lambda: U.snapshot())
        self.ask = ask or (lambda prompt, default='': None)  # typed text, None when the person backs out
        self.attach = attach or (lambda name: {'ok': False, 'out': 'no terminal to attach'})
        self.attrs = attrs or {}
        self.panel = 1
        self.cur = {n: 0 for n, _, _ in PANELS}
        self.tabs: dict[str, str] = {}
        self.main = False  # the main pane has focus
        self.help = False
        self.msg, self.msg_ok = '', True
        self.got = time.time()

    # --- what is where --------------------------------------------------------------------------------

    def items(self, n: int) -> list:
        key = PANELS[n - 1][2]
        rows = session_rows(self.snap) if key == 'sessions' else list(self.snap.get(key) or [])
        return rows + [NEW_TASK] if key == 'queue' else rows

    def sel(self):
        rows = self.items(self.panel)
        if not rows:
            return None
        self.cur[self.panel] = max(0, min(self.cur[self.panel], len(rows) - 1))
        return rows[self.cur[self.panel]]

    def tab_list(self, n: int, it) -> list[str]:
        if n == 1:
            return ['status', 'log']
        if it is None:
            return ['info']
        if n == 2:
            return ['chat'] if it.get('name') == 'c1' else ['info', 'terminal']
        if n == 3:
            return ['new task'] if it.get('new') else ['info']
        return ['answer'] if n == 4 else ['preview']

    def _tab_key(self, it) -> str:
        return f'{self.panel}:{(it or {}).get("id") or (it or {}).get("name") or ""}' if isinstance(it, dict) \
            else str(self.panel)

    def tab(self) -> tuple[str, list[str]]:
        it = self.sel()
        ts, k = self.tab_list(self.panel, it), self._tab_key(it)
        if self.tabs.get(k) not in ts:
            self.tabs[k] = ts[0]
        return self.tabs[k], ts

    def a(self, name: str) -> int:
        return self.attrs.get(name, 0)

    # --- rows and the main pane, as (text, colour) segments ------------------------------------------------

    def row(self, n: int, it) -> list[tuple[str, str]]:
        if n == 1:
            colour = 'green' if it.startswith('run up') else 'red' if it.startswith('no run') else \
                'yellow' if it.startswith('usage') else 'magenta' if it.startswith('release') else 'dim'
            return [('● ', colour), (it, 'fg')]
        if n == 2:
            if it.get('name') == 'c1':
                return [('c1 ', 'red'), (it.get('title', ''), 'fg'), (f' {it.get("state", "")}', 'dim')]
            if is_control(it):
                return [(f'{it["name"]} ', 'red'), (it.get('title', ''), 'fg'), (f' {it.get("state", "")}', 'dim')]
            if not it.get('task'):
                return [(f'{it["name"]} ', 'yellow'), (it.get('state') or 'idle', 'dim')]
            mins = f' {it["minutes"]}m' if it.get('minutes') is not None else ''
            return [(f'{it["name"]} ', 'magenta' if it.get('state') == 'merging' else 'yellow'),
                    (f'{it.get("task", "")} ', 'cyan'), (it.get('title', ''), 'fg'),
                    (f'{mins} {it.get("state", "")}', 'dim')]
        if n == 3:
            if it.get('new'):
                return [('+ ', 'green'), ('new task (n)', 'dim')]
            after = f' after {",".join(it["after"])}' if it.get('after') else ''
            return [(f'{it["id"]} ', 'yellow' if it.get('blocked') else 'cyan'), (it.get('title', ''), 'fg'),
                    (after, 'dim')]
        if n == 4:
            return [(f'{it["id"]} ', 'yellow'), (it.get('title') or it.get('ask', ''), 'fg'),
                    (f' {it.get("age", "")}', 'dim')]
        return [('◆ ', 'magenta'), (it.get('title', ''), 'fg')]

    def pane(self) -> list[list[tuple[str, str]]]:
        it, (tab, _) = self.sel(), self.tab()
        L = lambda *segs: list(segs)  # noqa: E731 - one line of segments
        if tab == 'status':
            out = [L((l, 'magenta' if l.startswith('release') else 'fg')) for l in self.snap.get('status') or []]
            return (out or [L(('nothing to show', 'dim'))]) + [L(), L(('R queues a release', 'dim'))]
        if tab == 'log':
            return [L((l, 'dim' if l.startswith('===') else 'fg')) for l in self.snap.get('log') or []] or \
                [L(('the run log is empty', 'dim'))]
        if it is None:
            return [L(('none', 'dim'))]
        if tab == 'chat':
            out = [L(('c1 ', 'red'), ('the run\'s control session · ', 'fg'), (it.get('state', ''), 'dim'))]
            if it.get('link'):
                out.append(L((it['link'], 'blue')))
            return out + [L(), L(('i or c: say something to c1; its reply lands in its session', 'dim'))]
        if tab == 'info' and self.panel == 2:
            mins = f'{it["minutes"]} min · ' if it.get('minutes') is not None else ''
            out = [L((f'{it["name"]} ', 'yellow'), (it.get('task', ''), 'cyan'), (f' {it.get("title", "")}', 'fg')),
                   L((f'{mins}{it.get("state", "")}', 'dim')), L()]
            out += [L(('files ', 'dim'), (f, 'fg')) for f in it.get('files') or []]
            if it.get('link'):
                out += [L(), L(('session ', 'dim'), (it['link'], 'blue'))]
            return out + [L(), L(('t: its terminal (tmux pane)', 'dim'))]
        if tab == 'terminal' and not it.get('task') and not is_control(it):
            return [L((idle_line(it), 'dim'))]
        if tab == 'terminal':
            return [L((f'{it["name"]} runs in a tmux pane of the run.', 'fg')), L(),
                    L(('Enter or t switches to it (attach). ', 'dim')),
                    L(('Back: Ctrl-b d outside tmux, Ctrl-b L inside it.', 'dim'))]
        if tab == 'new task':
            return [L(('n: a new task, written straight to the plan (plan add)', 'fg')),
                    L(('E: say it in your own words; c1 writes and queues it', 'dim'))]
        if tab == 'info':
            out = [L((f'{it["id"]} ', 'cyan'), (it.get('title', ''), 'fg')), L(),
                   L(('kind ', 'dim'), (f'{it.get("kind", "")} · {it.get("pri", "")}', 'fg'))]
            if it.get('blocked'):
                out.append(L(('blocked', 'red')))
            out += [L(('files ', 'dim'), (', '.join(it.get('files') or []) or '-', 'fg')),
                    L(('after ', 'dim'), (', '.join(it.get('after') or []) or '-', 'fg')),
                    L(('section ', 'dim'), (it.get('section', ''), 'fg')), L(),
                    L(('e edit · E chat edit · D drop · h do it here', 'dim'))]
            return out
        if tab == 'answer':
            out = [L((f'{it["id"]} ', 'yellow'), (it.get('title', ''), 'fg')), L(), L((it.get('ask', ''), 'fg'))]
            if it.get('url'):
                out.append(L((it['url'], 'blue')))
            return out + [L(), L((f'waiting {it.get("age", "")}', 'dim')),
                          L(('a: your reply goes to c1, which settles it · L later', 'dim'))]
        out = [L(('◆ ', 'magenta'), (it.get('title', ''), 'fg')), L()]
        if it.get('url'):
            out.append(L(('options page ', 'dim'), (it['url'], 'blue')))
        return out + [L(), L(('p: pick an option, or say what to change', 'dim'))]

    # --- drawing -------------------------------------------------------------------------------------------

    def put(self, win, y: int, x: int, segs, width: int, base: int = 0, ground: str = '') -> int:
        """Write `segs` at y, x within `width` columns; `base` is added to every colour (a box's edge). `ground`
        ('sel', 'cur': the selected row) draws each colour as its pair on that row's background instead."""
        for text, colour in segs:
            if width <= 0:
                break
            text = text.replace('\n', ' ')[:width]
            attr = self.attrs.get(f'{ground}:{colour or "fg"}', self.a(ground)) if ground else \
                self.a(colour) | base if colour or base else self.a('fg')  # B112: no colour is the ground's
            try:
                win.addnstr(y, x, text, width, attr)
            except Exception:  # noqa: BLE001 - curses refuses the bottom-right cell; the rest is drawn
                pass
            x, width = x + len(text), width - len(text)
        return x

    def box(self, win, y: int, x: int, h: int, w: int, title, on: bool, count: str = '') -> None:
        if h < 2 or w < 4:
            return
        edge = self.a('accent') if on else self.a('line')
        self.put(win, y, x, [('┌' + '─' * (w - 2) + '┐', '')], w, edge)
        for r in range(y + 1, y + h - 1):
            self.put(win, r, x, [('│', '')], 1, edge)
            self.put(win, r, x + w - 1, [('│', '')], 1, edge)
        self.put(win, y + h - 1, x, [('└' + '─' * (w - 2) + '┘', '')], w, edge)
        self.put(win, y, x + 2, title, w - 4)
        if count and len(count) + 4 < w:
            self.put(win, y + h - 1, x + w - len(count) - 3, [(f' {count} ', 'dim')], len(count) + 2)

    def heights(self, body: int) -> dict[int, int]:
        """Each panel's box height: SHORT rows (fewer when it has fewer) unfocused, the rest for the focused."""
        hs = {n: min(max(len(self.items(n)), 1), SHORT) + 2 for n, _, _ in PANELS if n != self.panel}
        hs[self.panel] = max(3, body - sum(hs.values()))
        return hs

    def draw_panel(self, win, n: int, name: str, y: int, x: int, h: int, w: int) -> None:
        rows, focused = self.items(n), n == self.panel
        on = focused and not self.main
        cur = min(self.cur[n], max(len(rows) - 1, 0))
        count = f'{cur + 1 if rows else 0} of {len(rows)}' + (f' · {n} to expand' if not focused and
                                                              len(rows) > SHORT else '')
        self.box(win, y, x, h, w, [(f' [{n}] {name} ', 'accent' if on else 'dim')], on, count)
        inner = h - 2
        top = max(0, cur - inner + 1)
        if not rows:
            self.put(win, y + 1, x + 2, [('none', 'dim')], w - 4)
        for i, it in enumerate(rows[top:top + inner]):
            mark = top + i == cur
            ground = ('sel' if on else 'cur') if mark else ''
            if ground:
                self.put(win, y + 1 + i, x + 1, [(' ' * (w - 2), '')], w - 2, ground=ground)
            self.put(win, y + 1 + i, x + 2, self.row(n, it), w - 4, ground=ground)

    def draw_main(self, win, y: int, x: int, h: int, w: int) -> None:
        tab, ts = self.tab()
        title = [(' ', '')]
        for i, t in enumerate(ts):
            title += ([(' - ', 'dim')] if i else []) + [(t, ('accent' if self.main else 'fg') if t == tab else 'dim')]
        self.box(win, y, x, h, w, title + [(' ', '')], self.main)
        lines, inner = [l for segs in self.pane() for l in wrap(segs, w - 4)], h - 2
        if tab == 'log':
            lines = lines[-inner:]
        for i, segs in enumerate(lines[:inner]):
            self.put(win, y + 1 + i, x + 2, segs, w - 4)

    def hint_keys(self) -> list[tuple[str, str]]:
        """F70: the keys of the focused panel (or of the main pane), lazygit style; '? all keys' lists the rest."""
        it = self.sel()
        new = isinstance(it, dict) and it.get('new')
        if self.main:
            keys = [('Esc', 'back'), ('[ ]', 'tab')]
            keys += {2: [('⏎', 'terminal') if self.tab()[0] == 'terminal' else ('t', 'terminal'), ('i', 'type')],
                     3: [('n', 'new'), ('E', 'chat')] if new else
                        [('e', 'edit'), ('E', 'chat'), ('D', 'drop'), ('h', 'here')],
                     4: [('⏎', 'answer'), ('L', 'later')], 5: [('p', 'pick')]}.get(self.panel, [('R', 'release')])
            return keys
        return {1: [('j/k', 'move'), ('⏎', 'open'), ('R', 'release'), ('c', 'chat'), ('q', 'quit')],
                2: [('j/k', 'move'), ('⏎', 'open'), ('t', 'terminal'), ('o', 'link'), ('c', 'chat')],
                3: [('j/k', 'move'), ('n', 'new'), ('E', 'chat')] if new else
                   [('J/K', 'reorder'), ('n', 'new'), ('e', 'edit'), ('E', 'chat'), ('D', 'drop'), ('h', 'here')],
                4: [('j/k', 'move'), ('a', 'answer'), ('L', 'later'), ('⏎', 'open')],
                5: [('j/k', 'move'), ('p', 'pick'), ('⏎', 'open')]}[self.panel]

    def footer(self, width: int = 0) -> list[tuple[str, str]]:
        """The key hint line: keys bold bright white, labels in the normal text colour, only the separators dim;
        always ending in '? all keys', with the panel's last keys left out should `width` be too narrow."""
        if self.msg:
            return [(self.msg, 'green' if self.msg_ok else 'red')]
        keys = self.hint_keys()
        while True:
            out = []
            for i, (k, v) in enumerate(keys + [('?', 'all keys')]):
                out += ([(' · ', 'dim')] if i else []) + [(k, 'key'), (f' {v}', 'fg')]
            if not width or not keys or sum(len(t) for t, _ in out) <= width:
                return out
            keys = keys[:-1]

    def fill(self, win, h: int, w: int) -> None:
        """B112: every cell on the theme background, so nothing of the terminal's earlier screen shows through a
        blank cell: the window's background, erase, then a space in every cell (curses refuses the last cell,
        which the background and erase cover)."""
        if hasattr(win, 'bkgd'):
            try:
                win.bkgd(' ', self.a('fg'))
            except Exception:  # noqa: BLE001
                pass
        win.erase()
        for r in range(h):
            self.put(win, r, 0, [(' ' * w, 'fg')], w)

    def draw(self, win) -> None:
        h, w = win.getmaxyx()
        self.fill(win, h, w)
        if h < 8 or w < 24:
            self.put(win, 0, 0, [('too small', 'red')], w)
            return
        ago = int(time.time() - self.got)
        top = [('agent-runner', 'accent'), (f' · {self.snap.get("project", "")}  ', 'fg'),
               ('● ', 'green' if self.snap.get('up') else 'dim'),
               (('live' if self.snap.get('up') else 'no run is up') + f' · updated {"just now" if ago < 5 else f"{ago}s ago"}', 'dim')]
        self.put(win, 0, 0, top, w)
        hint = 'R release  ? keys'
        if w > len(hint) + 50:
            self.put(win, 0, w - len(hint), [(hint, 'dim')], len(hint))
        body = h - 2
        if w >= TWO_COLUMNS:
            left = max(30, w * 36 // 100)
            mx, mw = left, w - left
        else:
            left, mx, mw = (0, 0, w) if self.main else (w, 0, 0)
        if left:
            y, hs = 1, self.heights(body)
            for n, name, _ in PANELS:
                hh = min(hs[n], 1 + body - y)
                if hh >= 2:
                    self.draw_panel(win, n, name, y, 0, hh, left)
                y += hs[n]
        if mw:
            self.draw_main(win, 1, mx, body, mw)
        tab = self.tab()[0]
        mode = (tab if self.main else PANELS[self.panel - 1][1]).upper()
        x = self.put(win, h - 1, 0, [(f' {mode} ', '')], w, self.a('mode'))
        self.put(win, h - 1, x + 1, self.footer(w - x - 2), w - x - 2)
        if self.help:
            lines = HELP.splitlines()
            bw, bh = min(w - 2, max(len(l) for l in lines) + 4), min(h - 2, len(lines) + 2)
            by, bx = (h - bh) // 2, (w - bw) // 2
            for r in range(bh):
                self.put(win, by + r, bx, [(' ' * bw, '')], bw)
            self.box(win, by, bx, bh, bw, [(' Keybindings ', 'accent')], True)
            for i, l in enumerate(lines[:bh - 2]):
                self.put(win, by + 1 + i, bx + 2, [(l, 'accent' if l and not l.startswith(' ') else 'fg')], bw - 4)

    # --- keys and actions ------------------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            self.snap = self.get_snap()
            self.got = time.time()
        except Exception as e:  # noqa: BLE001 - keep the last snapshot on screen, say why it is old
            self.msg, self.msg_ok = f'could not read the run: {e}', False

    def done(self, r: dict) -> None:
        """Show an action's result on the bottom line and read the run again."""
        out = (r.get('out') or '').strip().splitlines()
        self.msg, self.msg_ok = (out[0] if out else ('done' if r.get('ok') else 'failed')), bool(r.get('ok'))
        self.refresh()

    def _ask(self, prompt: str, default: str = ''):
        text = self.ask(prompt, default)
        return None if text is None else text.strip()

    def key(self, k: str) -> bool:
        """Handle one key (a character, or UP/DOWN/LEFT/RIGHT/ENTER/ESC/TAB/BTAB); True means quit."""
        k = KEYS.get(k, k)
        self.msg = ''
        if self.help:
            self.help = k not in ('ESC', '?', 'q', 'ENTER')
            return False
        if k == 'ESC':
            self.main = False
            return False
        if k in ('q', '\x03'):
            return True
        rows, it = self.items(self.panel), self.sel()
        tid = it.get('id') if isinstance(it, dict) and not it.get('new') else ''
        if k in '12345' and len(k) == 1:
            self.panel, self.main = int(k), False
        elif k == 'DOWN':
            self.cur[self.panel] = min(self.cur[self.panel] + 1, max(len(rows) - 1, 0))
            self.main = False
        elif k == 'UP':
            self.cur[self.panel] = max(self.cur[self.panel] - 1, 0)
            self.main = False
        elif k in ('l', 'TAB', 'RIGHT'):
            self.panel, self.main = self.panel % 5 + 1, False
        elif k in ('BTAB', 'LEFT') or (k == 'h' and self.panel != 3):
            self.panel, self.main = (self.panel + 3) % 5 + 1, False
        elif k == 'ENTER' and self.panel == 2 and self.main and self.tab()[0] == 'terminal':
            self.terminal()
        elif k == 'ENTER':
            if self.panel == 4 and self.main:
                self.answer(it)
            else:
                self.main = True
        elif k in ('[', ']'):
            tab, ts = self.tab()
            self.tabs[self._tab_key(it)] = ts[(ts.index(tab) + (1 if k == ']' else -1)) % len(ts)]
            self.main = True
        elif k == 't':
            self.terminal()
        elif k == 'c':
            self.panel, self.cur[2], self.main = 2, 0, True
            self.say_c1()
        elif k == 'R':
            self.release()
        elif k == '?':
            self.help = True
        elif k == 'o' and self.panel == 2 and it:
            self.msg, self.msg_ok = (it.get('link') or f'{it.get("name")} has no session link yet'), True
        elif k == 'i':
            self.type_in(it)
        elif self.panel == 3 and k == 'n':
            self.new_task()
        elif self.panel == 3 and k == 'e' and tid:
            self.edit(it)
        elif self.panel == 3 and k == 'E' and it:
            self.chat_edit(it)
        elif self.panel == 3 and k == 'D' and tid:
            if (why := self._ask(f'drop {tid}, why: ')) is not None:
                self.done(U.drop(tid, why or 'dropped from the run page'))
        elif self.panel == 3 and k == 'h' and tid:
            self.done(U.take(tid))
        elif self.panel == 3 and k in ('J', 'K') and tid:
            self.reorder(1 if k == 'J' else -1)
        elif self.panel == 4 and k == 'a' and it:
            self.answer(it)
        elif self.panel == 4 and k == 'L' and it:
            self.done(U.shelve(it['id']))
        elif self.panel == 5 and k == 'p' and it:
            self.pick(it)
        return False

    def reorder(self, step: int) -> None:
        """F70: Shift+J / Shift+K: the selected queued task one place down / up (`plan move ID after|before
        <neighbour>`); the selection follows it."""
        tasks = [t for t in self.items(3) if not t.get('new')]
        i = self.cur[3]
        if not 0 <= i + step < len(tasks):
            self.msg, self.msg_ok = f'{tasks[i]["id"]} is already {"last" if step > 0 else "first"}', True
            return
        r = U.call(['plan', 'move', tasks[i]['id'], 'after' if step > 0 else 'before', tasks[i + step]['id']])
        self.done(r)
        if r.get('ok'):  # the task's row in the queue read again, else the row it moved to
            ids = [t.get('id') for t in self.items(3)]
            self.cur[3] = ids.index(tasks[i]['id']) if tasks[i]['id'] in ids else i + step

    def terminal(self) -> None:
        """Switch to the selected slot's (or control session's) tmux pane; on another panel, the first slot on a
        task, else the first slot. An idle slot has no pane: the footer says so (B113), with no attach."""
        if self.panel != 2 or not isinstance(self.sel(), dict) or self.sel().get('name') == 'c1':
            rows = self.items(2)
            slots = [i for i, s in enumerate(rows) if not is_control(s)]
            if not slots:
                self.msg, self.msg_ok = 'the run has no slots', False
                return
            self.panel, self.cur[2] = 2, next((i for i in slots if rows[i].get('task')), slots[0])
        it = self.sel()
        self.tabs[self._tab_key(it)] = 'terminal'
        self.main = True
        if not it.get('task') and not is_control(it):  # B113: an idle slot has no window to attach
            self.msg, self.msg_ok = idle_line(it), True
            return
        self.done(self.attach(it['name']))

    def type_in(self, it) -> None:
        if self.panel == 2 and isinstance(it, dict) and it.get('name') != 'c1':
            self.terminal()
        elif self.panel == 3 and it:
            self.chat_edit(it)
        elif self.panel == 4 and it:
            self.answer(it)
        elif self.panel == 5 and it:
            self.pick(it)
        else:
            self.say_c1()

    def say_c1(self) -> None:
        if text := self._ask('to c1: '):
            self.done(U.chat(text))

    def answer(self, it) -> None:
        if text := self._ask(f'{it["id"]}, your reply: '):
            self.done(U.answer(it['id'], text))

    def pick(self, it) -> None:
        if text := self._ask(f'{it.get("title", "concept")}, your pick: '):
            self.done(U.chat(f'concept {it.get("concept") or it.get("id")} ("{it.get("title", "")}"): {text}'))

    def chat_edit(self, it) -> None:
        if it.get('new'):
            if text := self._ask('new task, in your words: '):
                self.done(U.chat(f'new task: {text}'))
        elif text := self._ask(f'change {it["id"]}: '):
            self.done(U.chat(f'change {it["id"]}: {text}'))

    def new_task(self) -> None:
        kind = self._ask('kind (B F T D R C K): ', 'F')
        text = self._ask('what, why, how to check: ') if kind else None
        if not kind or not text:
            return
        files = self._ask('files: ') or ''
        after = self._ask('after: ') or ''
        pri = self._ask('priority (critical normal low later): ', 'normal') or ''
        self.done(U.plan_add(kind.upper(), text, files or None, after or None, '' if pri == 'normal' else pri))

    def edit(self, it) -> None:
        """Direct edit: each field asked with its value filled in; only the ones changed are sent."""
        # the text is not filled in: the snapshot's title is cut at 200 characters, and sending it back would
        # cut the task; empty keeps the text as it is. An emptied field keeps its value too (plan edit sets, never clears)
        was = {'text': '', 'files': ','.join(it.get('files') or []),
               'after': ','.join(it.get('after') or []), 'pri': it.get('pri', 'normal')}
        now = {}
        for k, prompt in (('text', 'new text (Enter keeps it): '),('files', 'files: '), ('after', 'after: '), ('pri', 'priority: ')):
            got = self._ask(f'{it["id"]} {prompt}', was[k])
            if got is None:
                return
            now[k] = got
        changed = {k: v for k, v in now.items() if v != was[k] and v}
        if not changed:
            self.msg, self.msg_ok = 'nothing changed', True
            return
        self.done(U.plan_change(it['id'], changed.get('text', ''), changed.get('files'), changed.get('after'),
                                changed.get('pri', '')))

    def release(self) -> None:
        got = self._ask('release: Enter queues it behind the running tasks, f releases now: ')
        if got is not None:
            self.done(U.release(now=got.lower().startswith('f')))


# --- curses ----------------------------------------------------------------------------------------------

def curses_attrs(curses, theme: str | dict | None = None) -> dict[str, int]:
    """The theme's colour pairs on this terminal (F69: `[ui] theme` when none is given): 256 colours when it
    has them, else the 8 basic ones; the terminal theme draws in the terminal's own colours and background."""
    if not curses.has_colors():
        return {'red': curses.A_BOLD, 'accent': curses.A_BOLD, 'sel': curses.A_REVERSE, 'cur': curses.A_BOLD,
                'mode': curses.A_REVERSE, 'key': curses.A_BOLD}
    th = theme if isinstance(theme, dict) else TH.get(theme or TH.configured())
    curses.start_color()
    if -1 in (th['bg'], th['fg']):
        try:
            curses.use_default_colors()  # -1: the terminal's own foreground and background
        except Exception:  # noqa: BLE001 - a terminal without them: white on black
            th = {**th, 'bg': 0 if th['bg'] == -1 else th['bg'], 'fg': 7 if th['fg'] == -1 else th['fg']}
    col = lambda token: TH.curses_colour(th, token, curses.COLORS)  # noqa: E731
    bg = col('bg')
    out = {}
    for i, name in enumerate(COLOURS, start=1):
        curses.init_pair(i, col(name), bg)
        out[name] = curses.color_pair(i)
    n = len(COLOURS) + 1
    curses.init_pair(n, col('fg'), col('sel'))
    curses.init_pair(n + 1, bg if bg != -1 else col('selfg'), col('accent'))
    curses.init_pair(n + 2, col('fg'), col('cur'))
    out.update(sel=curses.color_pair(n), mode=curses.color_pair(n + 1) | curses.A_BOLD,
               cur=curses.color_pair(n + 2))
    n += 3
    for ground in ('sel', 'cur'):  # B112: every colour on each row background
        row_bg = col(ground)
        for name in COLOURS:
            fg = col('fg' if name == 'dim' else name)
            if fg == row_bg:  # the row's own colour (red on the terminal theme's red row) would vanish
                fg = col('selfg')
            curses.init_pair(n, fg, row_bg)
            out[f'{ground}:{name}'] = curses.color_pair(n) | (curses.A_BOLD if name in ('red', 'accent') else 0)
            n += 1
    for name in ('red', 'accent', 'key'):
        out[name] |= curses.A_BOLD
    return out


CURSES_KEYS = {'KEY_UP': 'UP', 'KEY_DOWN': 'DOWN', 'KEY_LEFT': 'LEFT', 'KEY_RIGHT': 'RIGHT', 'KEY_ENTER': 'ENTER',
               'KEY_BTAB': 'BTAB'}


def key_name(curses, ch) -> str:
    if isinstance(ch, int):
        return CURSES_KEYS.get(curses.keyname(ch).decode('ascii', 'replace'), '')
    return ch


def line_input(curses, win, attrs, prompt: str, default: str = ''):
    """A one-line editor on the bottom row: Enter takes it, Esc backs out (None)."""
    text = default
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    win.timeout(-1)
    try:
        while True:
            h, w = win.getmaxyx()
            win.move(h - 1, 0)
            win.clrtoeol()
            shown = (prompt + text)[-(w - 1):]
            win.addnstr(h - 1, 0, shown, w - 1, attrs.get('fg', 0))
            win.move(h - 1, min(len(shown), w - 2))
            win.refresh()
            ch = win.get_wch()
            if ch in ('\n', '\r') or (isinstance(ch, int) and ch == curses.KEY_ENTER):
                return text
            if ch == '\x1b':
                return None
            if ch in ('\x7f', '\b') or (isinstance(ch, int) and ch == curses.KEY_BACKSPACE):
                text = text[:-1]
            elif ch == '\x15':  # Ctrl-U: clear
                text = ''
            elif isinstance(ch, str) and ch.isprintable():
                text += ch
    finally:
        win.timeout(1000)
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def attach_slot(curses, win, name: str) -> dict:
    """Leave curses, show the slot's tmux pane (`attach sN`), and come back when it returns."""
    curses.def_prog_mode()
    curses.endwin()
    try:
        r = sp.run(U.runner_cmd() + ['attach', name], cwd=U.S.ROOT, stderr=sp.PIPE, text=True)
    finally:
        curses.reset_prog_mode()
        win.refresh()
    inside = bool(os.environ.get('TMUX'))
    if r.returncode:
        return {'ok': False, 'out': (r.stderr or '').strip() or f'attach {name} failed'}
    return {'ok': True, 'out': f'{name}: back with Ctrl-b L' if inside else f'back from {name}'}


def run_curses(win) -> int:
    import curses
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    attrs = curses_attrs(curses)
    win.bkgd(' ', attrs.get('fg', 0))
    win.clear()  # B112: the first refresh repaints every cell, so the terminal's earlier screen is gone
    win.keypad(True)
    win.timeout(1000)
    page = RunPage(U.snapshot(), attrs=attrs,
                   ask=lambda prompt, default='': line_input(curses, win, attrs, prompt, default),
                   attach=lambda name: attach_slot(curses, win, name))
    while True:
        if time.time() - page.got >= REFRESH:
            page.refresh()
        page.draw(win)
        win.refresh()
        try:
            ch = win.get_wch()
        except curses.error:  # the timeout: draw again ("updated Ns ago"), read the run when it is due
            continue
        except KeyboardInterrupt:
            return 0
        if isinstance(ch, int) and ch == curses.KEY_RESIZE:
            win.clear()  # B112: the next refresh repaints every cell, not only what curses thinks changed
            continue
        if page.key(key_name(curses, ch)):
            return 0


def main(argv: list[str]) -> int:
    """`agent-runner ui`: the Run page in this terminal."""
    if argv and argv[0] in ('-h', '--help'):
        print('agent-runner ui: the Run page in this terminal (the same panels, keys and actions as the web '
              'page). ? lists the keys, q quits.')
        return 0
    if argv:
        print(f'agent-runner ui takes nothing more (got {" ".join(argv)})', file=sys.stderr)
        return 2
    try:
        import curses
    except ImportError:
        print('agent-runner ui needs curses, which this Python lacks (on Windows: pip install windows-curses)',
              file=sys.stderr)
        return 2
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print('agent-runner ui needs a terminal; agent-runner status prints the same run as text', file=sys.stderr)
        return 2
    import locale
    from agent_runner.state import init
    init()
    locale.setlocale(locale.LC_ALL, '')
    os.environ.setdefault('ESCDELAY', '25')  # Esc backs out at once, not after curses' default second
    return curses.wrapper(run_curses)
