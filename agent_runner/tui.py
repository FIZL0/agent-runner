"""F67, F76: the Run page in the terminal: `agent-runner ui`.

The same panels, tabs and keys as the web Run page (round 2, F74's model), in curses (standard library, no new
dependency), in the lazygit layout: numbered boxed panels on the left ([1] Status, [2] Sessions, [3] Queue,
[4] Needs you, [5] Concepts), one main pane on the right with the selected item's tabs, the key hints on the
bottom line. The focused panel takes the spare height; every other panel shows 3 rows. Narrower than
`TWO_COLUMNS`, the panels and the main pane take the whole width in turn (Enter in, Esc out).

Panels and their tabs (F76):
    Status     a status line: chat (c1, with the quick asks s y w u on its buttons), log; the release line:
               release first; R (only here) opens the release tab
    Sessions   a control session cN: chat, pane, session; a slot: feed, pane, diff, session (an idle slot: feed,
               pane); the '+ new chat' row and N start one (`new_control`) and land on its chat tab, typing;
               a control session's session tab has the chat's message box too (B125); o opens the session
               link, y copies it (OSC 52, the terminal's own clipboard, plus wl-copy/xclip/pbcopy when local);
               over ssh o opens nothing here: it copies the link and shows it as a hyperlink (OSC 8) to
               Cmd-click
    Queue      a task: direct edit, chat edit; the '+ new task' row: chat edit, direct edit; e edit, E chat edit,
               n new, J/K reorder, p priority on/off, H do it here, d (or D) drop; a parked task: U unpark (no J/K, p)
    Needs you  answer (a button per possible answer: y yes, n no, or a b c … for options; L later; a reply box),
               info
    Concepts   preview: the K copy inline, its options (the copy's headings) moved through with j/k, Enter goes
               with the selected one, i says what to change, O opens the page in the browser, N starts a new
               control session about it (`concept_chat`; c stays c1's chat); the '+ new concept' row and n
               queue a new concept (plan add K)

The feed is the agent's words with its tool steps folded as '· N steps' (v shows them); a chat shows the steps,
as a Claude session does. A box takes typing after i (or Enter): Enter sends, Shift+Enter (or Alt+Enter)
is a new line, Esc leaves it (never interrupts), and in a chat Ctrl+C interrupts while the session works (B116;
elsewhere Ctrl+C quits). Each box keeps its draft
across Esc and refreshes; Ctrl-h / Ctrl-l and Ctrl-j / Ctrl-k still work in a box (F113: they leave it, its
draft kept). The pane tab attaches to the session's own terminal (Enter, F88; back with Ctrl-b d). Navigation: h/l previous / next tab (h on the first tab and Esc go back to the
panels), Ctrl-h / Ctrl-l the left / right side, Ctrl-j / Ctrl-k down / up the left side's list (in a box too, F113),
1-5 a panel (anywhere but in a box), Tab the next panel; in the
main pane j/k scroll it (the terminal has no scrollbar), and move through a concept's options.

The bottom line: the mode badge, this place's keys (yellow), a separator, then 1-5 panel, c chat, ? keys
(blue); never a key the window already shows (on a button, a label, a row), never j/k or Ctrl-h/Ctrl-l.

Colours: F69's `[ui] theme` (theme.py, shared with the web page), mapped to the nearest of the terminal's 256
colours (8 on an older terminal). A key is always drawn in another colour than its label.

What it shows is `ui_model.snapshot()`, read again every `REFRESH` seconds, and per session its feed
(`ui_model.feed`); what it does is `ui_model`'s actions, so the terminal changes the run as the web page does.
The screen logic (`RunPage`) draws on any object with curses' window calls (`getmaxyx`, `erase`, `addnstr`), so a
test drives it with a stub window; the feed, diff, attach and browser are passed in.
"""

from __future__ import annotations

import json
import os
import re
import subprocess as sp
import sys
import time
from html.parser import HTMLParser

from agent_runner import theme as TH
from agent_runner import ui_model as U

REFRESH = 3.0  # seconds between snapshots (and between reads of a shown feed or diff)
TWO_COLUMNS = 70  # narrower than this: one column, the panels or the main pane
SHORT = 3  # rows an unfocused panel shows
BOX_LINES = 6  # most lines a typing box grows to
DIFF_LINES = 3000  # most lines of a slot's diff shown

PANELS = [(1, 'Status', 'status'), (2, 'Sessions', 'sessions'), (3, 'Queue', 'queue'),
          (4, 'Needs you', 'needs'), (5, 'Concepts', 'concepts')]
NEW_TASK = {'id': '+', 'new': True}  # the queue's last row: a new task
NEW_CHAT = {'name': '+', 'new': True}  # Sessions' last row: a new control session
NEW_CONCEPT = {'id': '+', 'new': True}  # F87: Concepts' last row: a new concept (a K task)
PLACE_ENV = 'AGENT_RUNNER_TUI_PLACE'  # F90: where the TUI was, handed to itself across an upgrade restart


def newer_version(v: str, than: str) -> bool:
    """F90: version `v` is newer than `than` (dotted numbers; False when either is missing)."""
    num = lambda s: tuple(int(x) for x in re.findall(r'\d+', s or ''))  # noqa: E731
    return bool(v and than) and num(v) > num(than)


def follow_upgrade(page, exec_=None) -> None:
    """F90: start this TUI again on the run's newer version, with the same argv, its place (`saved_place`) in
    PLACE_ENV so it reopens where it was. Call with the terminal restored (curses ended)."""
    env = dict(os.environ, **{PLACE_ENV: json.dumps(page.saved_place())})
    sys.stdout.flush()
    (exec_ or os.execve)(sys.executable, list(getattr(sys, 'orig_argv', None) or [sys.executable] + sys.argv), env)


def taken_place() -> dict:
    """F90: the place an upgrade restart handed on (once), else {}."""
    try:
        place = json.loads(os.environ.pop(PLACE_ENV, '') or '{}')
    except ValueError:
        return {}
    return place if isinstance(place, dict) else {}
KIND_COLOUR = {'B': 'red', 'F': 'green', 'C': 'blue', 'R': 'magenta', 'V': 'yellow', 'K': 'cyan'}
KINDS = ('B', 'F', 'T', 'D', 'R', 'C', 'K', 'V')  # the direct edit's kind field cycles through these
QUICK_KEYS = {'since': 's', 'yesterday': 'y', 'needs': 'w', 'usage': 'u'}  # F74's quick asks, by key
FIELDS = ('t', 'k', 'p', 'f', 'a')  # the direct edit's fields, in Tab order
TEXT_FIELDS = {'t': 'text', 'f': 'files', 'a': 'after'}  # the ones typed into
OPTION_KEYS = 'abcdefg'  # a Needs you item's answers beyond yes / no
TAIL_TABS = ('chat', 'feed', 'log')  # tabs that show their newest lines, at the bottom

# F69: the colours a segment can name, each a token of the theme (theme.py); 'accent' is the theme's accent
# (red in ryha). F76: 'hkey' a key of this place (yellow: on a button, a label, the bottom line), 'gkey' a key
# that works everywhere (blue, the bottom line's 1-5 c ?). B112: a selected row draws every segment on its row
# background: each colour gets a pair on the focused row's ('sel:red') and on the unfocused selected row's
COLOURS = ('fg', 'dim', 'line', 'accent', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'key', 'hkey',
           'gkey', 'pkey')
TOKEN = {'hkey': 'yellow', 'gkey': 'bblue', 'pkey': 'accent'}  # a colour name that is not a theme token itself
KEY_COLOURS = ('hkey', 'gkey', 'pkey')  # 'pkey': the key on the primary button (red)


def session_rows(snap: dict) -> list:
    """B112: the Sessions panel's rows: c1, then every slot of the run, an idle one (no task) included, as the
    design lists them. The slot count is the snapshot's `slots` (F71; the snapshot lists idle slots itself),
    else, from a snapshot without it, the run's status line ('run up: 3 slots, ...')."""
    if snap.get('sessions_note'):  # C23: an older agent-runner's run: no rows, the one line instead
        return []
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
    """B113: what an idle slot's pane says instead of an error: no window is open while it has no task."""
    return f'{row.get("name", "")} is idle: nothing running'


# each indented line: key, label, key, label …, two spaces or more apart (`help_line` colours them)
HELP = """Everywhere (not while typing in a box)
  1-5      focus a panel          Tab      next panel (direct edit: next field)
  j/k      move down / up         l Enter  into the main pane, next tab
  h        previous tab, out      Esc      back out
  ^C       a working chat: interrupt (elsewhere: quit)
  ^h ^l    left / right side      c        chat with c1
  ^j ^k    down / up the left list (these four work in a box too)
  i        type in the box        ?        this list
  q        quit
Status [1]
  R        release                s y w u  quick asks (chat tab)
  + - =    slot +1, -1, set N     P G      pause, go on
  F C      force, caps back on    S        stop (running tasks finish)
  X X      stop now (X again)     U        take the stop back
  V        upgrade agent-runner   Z B      suspend, shut down once stopped (again: undo)
Sessions [2]
  t        feed                   v        tool steps on / off
  N        new chat               o        open the session link
  y        copy the session link (the terminal's clipboard, so over ssh too)
  H        take its task back     d D      drop its task from the slot
  d        close a control session cN (not c1: the run's kept session; its transcript stays)
  Enter    on the pane tab: attach (back: Ctrl-b d)
Queue [3]
  e        direct edit            E        chat edit
  n        new task               J/K      move down / up
  p        priority               H        do it here
  d D      drop                   ^S       save the direct edit
  U        unpark (a parked task: no J/K or p)
  t k K    what, kind (cycles, back)        p f a    priority, files, after
Needs you [4]
  a        answer                 L        later
  d        drop
  y n      yes, no                a b c    a pick's options (answer tab)
Concepts [5]
  j/k      option                 Enter    go with it
  i        what to change         O        open in the browser
  d        drop the concept
  N        chat about it (a new session)
  n        new concept (queued as a K task)
Typing
  Enter    send                   Shift+Enter  new line (or Alt+Enter)
  Esc      leave the box
Esc closes this."""


def help_line(line: str) -> list[tuple[str, str]]:
    """A line of the keys list: a heading in the accent; an indented line's keys yellow, its labels in the text
    colour."""
    if not line.startswith(' '):
        return [(line, 'accent')]
    out, parts = [], re.split(r'(\s{2,})', line)
    words = 0
    for part in parts:
        if not part.strip():
            out.append((part, ''))
            continue
        out.append((part, 'hkey' if words % 2 == 0 else 'fg'))
        words += 1
    return out

# raw characters as RunPage's key names; curses' own keys come named by `key_name`
KEYS = {'\r': 'ENTER', '\n': '^J', '\t': 'TAB', '\x1b': 'ESC', '\x13': '^S', '\x0b': '^K',
        '\x08': '^H', '\x0c': '^L', '\x7f': 'BS', '\x03': '^C', '\x15': '^U'}
SIDE_KEYS = ('^H', '^L', '^J', '^K')  # F113: focus left / right, the left list down / up; in a box too
MOVES = {'DOWN', 'UP', 'j', 'k', 'ENTER', 'LEFT', 'RIGHT', 'h', 'l'}
VI = {'j': 'DOWN', 'k': 'UP'}  # j / k move as Down / Up do, except where a tab gives them a use of its own  # main pane keys never handed on to the panel


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


def text_lines(text: str, colour: str, width: int, first: str = '', rest: str = '', mark: str = 'dim') -> list:
    """`text` (newlines kept) wrapped to `width`, its first line led by `first` (in `mark`), every later one by
    `rest`."""
    out = []
    for para in str(text).split('\n'):
        for l in wrap([(para, colour)], max(width - len(first), 4)):
            out.append([(first if not out else rest, mark)] + l)
    return out or [[(first, mark)]]


def button(key: str, label: str, primary: bool = False) -> list[tuple[str, str]]:
    """A button: its key in the key colour (red on the primary one), its label in the text colour."""
    return [('[', 'dim'), (key, 'pkey' if primary else 'hkey'), (f' {label}', 'fg'), (']', 'dim')]


def buttons(*bs) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for i, b in enumerate(bs):
        out += ([(' ', '')] if i else []) + b
    return out


class _Copy(HTMLParser):
    """A K copy's page as blocks: (level, text), level 1-4 for a heading (an element of class t, ttl or title
    counts as a level 3 one), 0 for a paragraph; scripts and styles left out."""
    HEADS = {'h1': 1, 'h2': 2, 'h3': 3, 'h4': 4}
    BLOCKS = {'p', 'li', 'div', 'section', 'pre', 'td', 'th', 'blockquote', 'tr', 'br', 'ul', 'ol', 'table',
              'article', 'header', 'footer', 'main'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[int, str]] = []
        self.buf: list[str] = []
        self.stack: list[tuple[str, int]] = []  # open elements that make a heading
        self.skip = 0

    def flush(self):
        text = ' '.join(''.join(self.buf).split())
        self.buf = []
        if text:
            self.blocks.append((self.stack[-1][1] if self.stack else 0, text))

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'title', 'head'):
            self.skip += 1
            return
        cls = set((dict(attrs).get('class') or '').split())
        level = self.HEADS.get(tag) or (3 if cls & {'t', 'ttl', 'title'} else 0)
        if level or tag in self.BLOCKS:
            self.flush()
        if level:
            self.stack.append((tag, level))

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'title', 'head'):
            self.skip = max(0, self.skip - 1)
            return
        if tag in self.HEADS or tag in self.BLOCKS:
            self.flush()
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


def concept_page(html: str) -> dict:
    """F76: a concept's K copy as {'title', 'intro': [paragraphs], 'options': [{'name', 'body': [...], 'rec'}]}:
    the options are its headings one level below the title's (the first heading), each with what follows it;
    'rec' marks the one whose heading says it is recommended."""
    p = _Copy()
    try:
        p.feed(html or '')
        p.close()
    except Exception:  # noqa: BLE001 - a broken page shows what parsed
        pass
    p.flush()
    blocks = p.blocks
    heads = [i for i, (lv, _) in enumerate(blocks) if lv]
    title, start = '', 0
    if heads and blocks[heads[0]][0] == min(blocks[i][0] for i in heads):
        title, start = blocks[heads[0]][1], heads[0] + 1
    rest = blocks[start:]
    levels = sorted({lv for lv, _ in rest if lv})
    opt_level = levels[0] if levels else 0
    intro, options = [], []
    for lv, text in rest:
        if opt_level and lv == opt_level:
            options.append({'name': text, 'body': [], 'rec': 'recommend' in text.lower()})
        elif options:
            options[-1]['body'].append(text)
        else:
            intro.append(text)
    return {'title': title, 'intro': intro, 'options': options}


def after_hint(after: str, queue: list) -> str:
    """The direct edit's line under its after field: each id with its task's title, as the queue says it."""
    titles = {t.get('id'): t.get('title', '') for t in queue if isinstance(t, dict)}
    ids = [a for a in re.split(r'[\s,]+', after or '') if a]
    if not ids:
        return 'nothing: it can start when a slot is free'
    if ids == ['all']:
        return 'all: everything above it'
    return ', '.join(f'{a} {titles[a]}'.rstrip() if a in titles else f'{a} (landed)' for a in ids)


class RunPage:
    """The terminal Run page's state and drawing; `key()` takes one key, `draw()` paints one frame."""

    def __init__(self, snap: dict, get_snap=None, attach=None, attrs=None, feed=None, diff=None, opener=None,
                 read=None, out=None):
        self.snap = snap
        self.get_snap = get_snap or (lambda: U.snapshot())
        self.attach = attach or (lambda name: {'ok': False, 'out': 'no terminal to attach'})
        self.feed_of = feed or U.feed
        self.diff_of = diff or slot_diff
        self.out = out or term_write  # B125: escape sequences for the terminal itself (OSC 52, OSC 8)
        self.opener = opener or (lambda url: open_url(url, self.out))
        self.links: list[tuple[int, int, str, str]] = []  # B125: the links the last frame drew: y, x, text, url
        self._urls: list[str] = []
        self.msg_link = ''  # a link the message line shows after its words (o over ssh)
        self.read = read or read_file
        self.attrs = attrs or {}
        self.panel = 1
        self.cur = {n: 0 for n, _, _ in PANELS}
        self.tabs: dict[str, str] = {}
        self.main = False  # the main pane has focus
        self.help = False
        self.typing = ''  # the box taking typed keys ('' none): 'c1:chat', 'edit:Q2', 'form:Q2:t', …
        self.drafts: dict[str, str] = {}  # each box's text, kept across Esc and refreshes
        self.forms: dict[str, dict] = {}  # each direct edit's fields, by task id ('+' a new task)
        self.steps = False  # the feed shows its tool steps
        self.cache: dict[str, tuple[float, object]] = {}  # feeds and diffs read lately
        self.off: dict[str, int] = {}  # each place's scroll (j/k in the main pane)
        self.opt: dict[str, int] = {}  # each concept's selected option
        self.msg, self.msg_ok = '', True
        self.got = time.time()
        self.window_keys: set[str] = set()  # the keys the last frame showed above the bottom line
        self.confirm = ''  # F82: the run control waiting for its key again (stop now), '' none
        self.restart = False  # F90: the run is on a newer version: start this TUI again on it (`follow_upgrade`)
        self.followed = ''  # F90: the version the last restart was for (never restart twice for one version)

    # --- what is where --------------------------------------------------------------------------------

    def items(self, n: int) -> list:
        key = PANELS[n - 1][2]
        if key == 'sessions':
            return session_rows(self.snap) + ([NEW_CHAT] if not self.snap.get('sessions_note') else [])
        rows = list(self.snap.get(key) or [])
        if key == 'concepts':
            return rows + [NEW_CONCEPT]
        return rows + [NEW_TASK] if key == 'queue' else rows

    def empty_line(self, n: int) -> str:
        """What panel `n` says with no rows: 'none', or in Sessions the snapshot's `sessions_note` (C23)."""
        return (self.snap.get('sessions_note') if n == 2 else '') or 'none'

    def sel(self, n: int = 0):
        n = n or self.panel
        rows = self.items(n)
        if not rows:
            return None
        self.cur[n] = max(0, min(self.cur[n], len(rows) - 1))
        return rows[self.cur[n]]

    def tab_list(self, n: int, it) -> list[str]:
        if it is None:
            return ['chat', 'log', 'release', 'controls'] if n == 1 else ['info']
        if n == 1:
            return ['release', 'chat', 'log', 'controls'] if str(it).startswith('release') else \
                ['chat', 'log', 'release', 'controls']
        if n == 2:
            if it.get('new'):
                return ['info']
            if is_control(it):
                return ['chat', 'pane', 'session']
            return ['feed', 'pane', 'diff', 'session'] if it.get('task') else ['feed', 'pane']
        if n == 3:
            return ['chat edit', 'direct edit'] if it.get('new') else ['direct edit', 'chat edit']
        if n == 5 and it.get('new'):
            return ['new concept']
        return ['answer', 'info'] if n == 4 else ['preview']

    def _tab_key(self, it) -> str:
        if isinstance(it, dict):
            return f'{self.panel}:{it.get("id") or it.get("name") or ""}'
        if self.panel == 1 and it is not None:  # a status line by its first word: its numbers change
            return f'1:{str(it).split(":")[0].split()[0] if str(it).split() else ""}'
        return str(self.panel)

    def tab(self) -> tuple[str, list[str]]:
        it = self.sel()
        ts, k = self.tab_list(self.panel, it), self._tab_key(it)
        if self.tabs.get(k) not in ts:
            self.tabs[k] = ts[0]
        return self.tabs[k], ts

    def set_tab(self, name: str) -> bool:
        tab, ts = self.tab()
        if name not in ts:
            return False
        self.tabs[self._tab_key(self.sel())] = name
        self.main = True
        return True

    def place(self) -> str:
        """Where the main pane is: panel, item and tab (a scroll is kept per place)."""
        return f'{self._tab_key(self.sel())}:{self.tab()[0]}'

    def a(self, name: str) -> int:
        return self.attrs.get(name, 0)

    def tid(self, it) -> str:
        return it.get('id', '') if isinstance(it, dict) and not it.get('new') else ''

    # --- the boxes typed into -----------------------------------------------------------------------------

    def box(self) -> str:
        """The box of the main pane's tab ('' none): 'status:chat', 'c6:chat', 's2:feed', 'edit:Q2', 'answer:D3',
        'concept:F4'."""
        it, tab = self.sel(), self.tab()[0]
        if it is None:
            return ''
        if tab == 'chat':
            return 'status:chat' if self.panel == 1 else f'{it["name"]}:chat'
        if tab == 'session' and is_control(it):  # B125: the session tab types into the same session as chat
            return f'{it["name"]}:chat'
        if tab == 'feed' and it.get('task'):
            return f'{it["name"]}:feed'
        if tab == 'chat edit':
            return f'edit:{it["id"]}'
        if tab == 'answer':
            return f'answer:{it["id"]}'
        if tab in ('preview', 'new concept'):
            return f'concept:{it["id"]}'
        return ''

    def chat_name(self) -> str:
        """The control session the main pane chats with ('' none): c1 on Status, the selected cN in Sessions."""
        box = self.box()
        if box == 'status:chat':
            return 'c1'
        return box.split(':')[0] if box.endswith(':chat') else ''

    def text_of(self, box: str) -> str:
        if box.startswith('form:'):
            _, tid, f = box.split(':')
            return self.forms.get(tid, {}).get(TEXT_FIELDS[f], '')
        return self.drafts.get(box, '')

    def set_text(self, box: str, text: str) -> None:
        if box.startswith('form:'):
            _, tid, f = box.split(':')
            if tid in self.forms:
                self.forms[tid][TEXT_FIELDS[f]] = text
            return
        if text:
            self.drafts[box] = text
        else:
            self.drafts.pop(box, None)

    def type_in(self) -> None:
        """i: type into the main pane's box (in a direct edit, its what field)."""
        if self.tab()[0] == 'direct edit':
            self.field('t')
            return
        if box := self.box():
            self.main, self.typing = True, box
        else:
            self.msg, self.msg_ok = 'nothing to type into here', True

    # --- the feed and the diff ------------------------------------------------------------------------

    def cached(self, key: str, read):
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < REFRESH:
            return hit[1]
        try:
            got = read()
        except Exception as e:  # noqa: BLE001 - a read that fails says why, in the pane
            got = {'ok': False, 'entries': [], 'out': str(e)} if key.startswith('feed:') else f'(could not read: {e})'
        self.cache[key] = (time.time(), got)
        return got

    def feed(self, name: str) -> dict:
        return self.cached(f'feed:{name}', lambda: self.feed_of(name)) or {}

    def working(self, name: str) -> bool:
        """The control session `name` is mid-turn: its feed's newest entry is the person's words, a tool step or
        its output (not an interruption), so Ctrl+C interrupts it."""
        ents = self.feed(name).get('entries') or []
        return bool(ents) and ents[-1].get('kind') in ('you', 'tool', 'out') and ents[-1].get('text') != 'interrupted'

    def feed_lines(self, name: str, width: int, steps: bool) -> list:
        """A session's feed as pane lines: the agent's words (●), the person's (❯, blue), and its tool steps (a
        green ●, the output under ⎿); with `steps` off, each run of steps is one '· N steps' line."""
        f = self.feed(name)
        ents = f.get('entries') or []
        if not ents:
            return [[(f.get('out') or f'{name} has said nothing yet', 'dim')]]
        out: list = []
        fold = 0

        def flush():
            nonlocal fold
            if fold:
                out.append([(f'· {fold} step{"s" if fold > 1 else ""}', 'dim')])
                fold = 0
        if f.get('more'):
            out.append([('… older entries left out', 'dim')])
        for e in ents:
            kind, text = e.get('kind'), str(e.get('text', ''))
            if kind in ('tool', 'out') and not steps:
                fold += kind == 'tool'
                continue
            flush()
            if out:
                out.append([])
            if kind == 'say':
                out += text_lines(text, 'fg', width, '● ', '  ', 'fg')
            elif kind == 'you':
                out += text_lines(text, 'blue', width, '❯ ', '  ')
            elif kind == 'tool':
                out += [[('● ', 'green')] + l[1:] for l in text_lines(text, 'dim', width, '● ', '  ')]
            elif text == 'interrupted':
                out.append([('  ⎿ ', 'dim'), ('Interrupted · say what to do instead', 'red')])
            else:
                out += text_lines(text, 'dim', width, '  ⎿ ', '    ')
        flush()
        return out

    def diff(self, name: str) -> str:
        return self.cached(f'diff:{name}', lambda: self.diff_of(name)) or ''

    # --- rows and the main pane, as (text, colour) segments ------------------------------------------------

    def row(self, n: int, it) -> list[tuple[str, str]]:
        if n == 1:
            colour = 'green' if it.startswith('run up') else 'red' if it.startswith('no run') else \
                'yellow' if it.startswith('usage') else 'magenta' if it.startswith('release') else 'dim'
            return [('● ', colour), (it, 'fg')]
        if n == 2:
            if it.get('new'):
                return [('+ ', 'green'), ('new chat ', 'dim'), ('N', 'hkey')]
            if is_control(it):
                return [(f'{it["name"]} ', 'red'), (it.get('title', ''), 'fg'), (' chat', 'dim')]
            if not it.get('task'):
                return [(f'{it["name"]} ', 'dim'), (it.get('state') or 'idle', 'dim')]
            mins = f' {it["minutes"]}m' if it.get('minutes') is not None else ''
            return [(f'{it["name"]} ', 'magenta' if it.get('state') == 'merging' else 'yellow'),
                    (f'{it.get("task", "")} ', 'cyan'), (it.get('title', ''), 'fg'),
                    (f'{mins} {it.get("state", "")}', 'dim')]
        if n == 4:
            return [(f'{it["id"]} ', 'yellow'), (it.get('title') or it.get('ask', ''), 'fg'),
                    (f' {it.get("age", "")}', 'dim')]
        if it.get('new'):
            return [('+ ', 'green'), ('new concept ', 'dim'), ('n', 'hkey')]
        return [('◆ ', 'magenta'), (it.get('title', ''), 'fg')]

    def queue_tag(self, it) -> tuple[str, str]:
        """A queue row's right tag: 'sN Nm' (yellow) while a slot runs it, 'critical' (red), 'blocked' (red),
        '⧗ after <id title>' (dim) while it waits, 'parked' (dim) at level later (B123: a run never starts it),
        'ready' (green)."""
        state = str(it.get('state') or '')
        if state == 'parked':
            return 'parked', 'dim'
        if state.startswith('running'):
            return state[len('running'):].strip() or 'running', 'yellow'
        if state == 'blocked' or (not state and it.get('blocked')):
            return 'blocked', 'red'
        if state == 'critical' or (not state and it.get('pri') == 'critical'):
            return 'critical', 'red'
        if state == 'after' or (not state and it.get('after')):
            words = it.get('after_title') or ', '.join(it.get('after') or [])
            return f'⧗ after {words}', 'dim'
        return 'ready', 'green'

    def row_lines(self, n: int, it, width: int, open_: bool) -> list:
        """A row as lines of segments within `width`; the selected row of the focused queue (`open_`) wraps to
        show its whole title and its tag (the after line) under it."""
        if n != 3:
            return [self.row(n, it)]
        if it.get('new'):
            return [[('+ ', 'green'), ('new task ', 'dim'), ('n', 'hkey')]]
        tid = it.get('id', '')
        idw = max(5, len(tid) + 1)
        head = [(tid.ljust(idw), KIND_COLOUR.get(tid[:1], 'cyan'))]
        tag, colour = self.queue_tag(it)
        title = it.get('title', '')
        if open_:
            lines = [l for l in wrap([(title, 'fg')], max(width - idw, 4))]
            out = [(head if i == 0 else [(' ' * idw, '')]) + l for i, l in enumerate(lines)]
            out += [[(' ' * idw, '')] + l for l in wrap([(tag, colour)], max(width - idw, 4))]
            return out
        room = width - idw
        tag = tag if len(tag) <= max(room * 42 // 100, 6) else tag[:max(room * 42 // 100, 6) - 1] + '…'
        tw = max(room - len(tag) - 1, 0)
        t = title if len(title) <= tw else title[:max(tw - 1, 0)] + ('…' if tw else '')
        return [head + [(t.ljust(tw), 'fg'), (' ', ''), (tag, colour)]]

    def answers(self, it) -> list[tuple[str, str]]:
        """F76: a Needs you item's possible answers as (key, answer): y yes / n no for a yes-or-no ask, the
        concept's options (a, b, c …) for a pick, 'done' for a block; [] when only a reply fits."""
        label = it.get('label', '')
        said = f'{it.get("ask", "")} {it.get("what", "")}'.lower()
        if label == 'CONFIRM' or re.search(r'\byes\s*(/|or)\s*no\b', said):
            return [('y', 'yes'), ('n', 'no')]
        if label == 'CONCEPT':
            names = [o['name'] for o in self.concept(it)['options']] or ['A', 'B', 'C']
            return list(zip(OPTION_KEYS, names))
        if label == 'BLOCKED':
            return [('a', 'done')]
        return []

    def concept(self, it) -> dict:
        """The concept page of a Concepts row (or a Needs you CONCEPT item), parsed from its K copy."""
        copy = it.get('copy') or next((c.get('copy') for c in self.snap.get('concepts') or []
                                       if c.get('id') == it.get('id')), '')
        html = self.cached(f'copy:{copy}', lambda: self.read(copy)) if copy else ''
        return concept_page(html) if html else {'title': '', 'intro': [], 'options': []}

    def option(self, it) -> int:
        opts = self.concept(it)['options']
        if not opts:
            return 0
        i = self.opt.get(it['id'])
        if i is None:
            i = next((j for j, o in enumerate(opts) if o['rec']), 0)
        self.opt[it['id']] = max(0, min(i, len(opts) - 1))
        return self.opt[it['id']]

    def input_lines(self, box: str, width: int, placeholder: str) -> list:
        """A box as lines: '❯ ' and its draft (a cursor block while typing), else its placeholder (dim); while
        typing in it, a '⏎ send' button at the right of its last line (else Enter is the tab's own key)."""
        text, on = self.text_of(box), self.typing == box
        if not text and not on:
            lines = [[('❯ ', 'dim'), (placeholder, 'dim')]]
        else:
            lines = text_lines(text, 'fg', width - 9, '❯ ', '  ')[-BOX_LINES:]
            if on:
                lines[-1] = lines[-1] + [('█', 'accent')]
        if not on:
            return lines
        used = sum(len(t) for t, _ in lines[-1])
        send = button('⏎', 'send')
        pad = width - used - sum(len(t) for t, _ in send)
        if pad > 0:
            lines[-1] = lines[-1] + [(' ' * pad, '')] + send
        return lines

    def pane(self, width: int) -> tuple[list, list, object]:
        """The main pane: (lines, the lines at its foot (buttons, a box), where it shows from: 'end' for the
        newest lines, else the line to keep in view)."""
        it, (tab, _) = self.sel(), self.tab()
        L = lambda *segs: list(segs)  # noqa: E731 - one line of segments
        if tab == 'log':
            return [L((l, 'dim' if l.startswith('===') else 'fg')) for l in self.snap.get('log') or []] or \
                [L(('the run log is empty', 'dim'))], [], 'end'
        if tab == 'release':
            return self.release_pane(width), [], 0
        if tab == 'controls':
            foot = self.input_lines('slots:n', width, 'how many slots') if self.typing == 'slots:n' else []
            return self.controls_pane(width), foot, 0
        if tab == 'chat' and self.panel == 1:
            asks = self.snap.get('quick_asks') or U.quick_asks()
            row = buttons(*[button(QUICK_KEYS.get(q['key'], '?'), q['label']) for q in asks])
            foot = [row] + self.input_lines('status:chat', width, 'message c1')
            return self.chat_head('c1') + self.feed_lines('c1', width, True), foot, 'end'
        if it is None:
            return [L((self.empty_line(self.panel), 'dim'))], [], 0
        if self.panel == 2:
            return self.session_pane(it, tab, width)
        if tab == 'direct edit':
            return self.form_pane(it, width), [], 0
        if tab == 'chat edit':
            if it.get('new'):
                out = [L(('Describe the task in your own words; c1 writes it, picks the files and queues it.',
                          'dim'))]
                hint = 'e.g. the board should show usage too'
            else:
                out = [L(('Say what to change about ', 'dim'), (it['id'], 'dim'), ('; c1 rewrites the task.', 'dim')),
                       L()] + [[(f'{it["id"]} ', KIND_COLOUR.get(it['id'][:1], 'cyan'))] + l
                               for l in wrap([(it.get('title', ''), 'fg')], width - len(it['id']) - 1)]
                hint = 'e.g. also cover openmx'
            return out, self.input_lines(f'edit:{it["id"]}', width, hint), 0
        if tab == 'answer':
            out = [L((f'{it["id"]} ', 'yellow'), (it.get('title', ''), 'fg')), L()] + \
                text_lines(it.get('ask', ''), 'fg', width)
            if it.get('url'):
                out += [L(), L((it['url'], 'blue'))]
            out += [L(), L(('Your reply goes to c1, which settles the item.', 'dim'))]
            row = buttons(*[button(k, v) for k, v in self.answers(it)], button('L', 'later'))
            return out, [row] + self.input_lines(f'answer:{it["id"]}', width, 'or your own reply'), 0
        if tab == 'info' and self.panel == 4:
            out = [L((f'{it["id"]} ', 'yellow'), (it.get('title', ''), 'fg')), L(),
                   L(('kind of ask ', 'dim'), (it.get('label', ''), 'fg'))]
            out += text_lines(it.get('what') or it.get('ask', ''), 'fg', width)
            if it.get('url'):
                out += [L(), L(('page ', 'dim'), (it['url'], 'blue'))]
            return out + [L(), L((f'waiting {it.get("age", "")}', 'dim'))], [], 0
        if tab == 'new concept':
            out = [L(('Say what the concept is about; it is queued as a K task (plan add K), and its options page ',
                      'dim'), ('lists here once a run writes it.', 'dim'))]
            return out, self.input_lines('concept:+', width, 'e.g. a dark mode for the run app'), 0
        if tab == 'preview':
            lines, anchor = self.preview_pane(it, width)
            return lines, self.input_lines(f'concept:{it["id"]}', width, 'say what to change'), anchor
        return [L(('nothing to show', 'dim'))], [], 0

    def chat_head(self, name: str) -> list:
        return [[(f'{name} ', 'red'), ('a control session: what you send is typed into it, as in the app', 'dim')],
                []]

    def release_pane(self, width: int) -> list:
        L = lambda *segs: list(segs)  # noqa: E731
        rel = self.snap.get('release') or ''
        out = [L(('V ', 'magenta'), (rel or 'no release is queued', 'fg' if rel else 'dim')), L(),
               L(('A release waits for everything before it.', 'dim'))]
        running = [s for s in session_rows(self.snap) if s.get('task')]
        if running:
            out += [L(), L(('running now:', 'dim'))]
            out += [L(('  ', ''), (f'{s["task"]} ', 'cyan'), (s.get('title', ''), 'fg'), (f' in {s["name"]}', 'dim'))
                    for s in running]
        return out + [L(), buttons(button('⏎', 'release when the running tasks land', True),
                                   button('f', 'release now, without them'))]

    def control_buttons(self, where: str) -> list:
        """F82: the run controls of `where` ('run', 'task') as button rows, from ui_model's one list."""
        cs = [c for c in self.snap.get('controls') or U.controls() if c['where'] == where]
        if where == 'task':
            return [buttons(*[button(c['tui'], c['label'].lower()) for c in cs])]
        groups = (('slot_add', 'slot_remove', 'slots_set'), ('pause', 'go_on'), ('force', 'caps_on'),
                  ('stop', 'stop_now', 'stop_undo'), ('upgrade', 'suspend', 'shutdown'))
        return [buttons(*[button(c['tui'], c['label'].lower()) for c in cs if c['key'] in g]) for g in groups]

    def controls_pane(self, width: int) -> list:
        L = lambda *segs: list(segs)  # noqa: E731
        run = self.snap.get('run') or {}
        said = 'no run is up' if not self.snap.get('up') else ', '.join(
            w for k, w in (('paused', 'paused'), ('stopping', 'stopping')) if run.get(k)) or 'running'
        out = [L(('run ', 'dim'), (said, 'fg'), (f' · {self.snap.get("slots", 0)} slots', 'dim')), L()]
        for row in self.control_buttons('run'):
            out += [row, L()]
        out.append(L(('A slot on a task: H takes it back, D drops it (Sessions [2]).', 'dim')))
        if self.confirm:
            c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == self.confirm), {})
            out += [L()] + text_lines(f'{c.get("confirm", "")} {c.get("tui", "")} again: yes; any other key: no',
                                      'red', width)
        return out

    @staticmethod
    def task_controls_on(it) -> bool:
        """A slot's task controls work while it works on a task, not while the task lands (merging)."""
        return isinstance(it, dict) and bool(it.get('task')) and not is_control(it) and it.get('state') != 'merging'

    def control_by_tui(self, k: str, where: str) -> dict | None:
        return next((c for c in self.snap.get('controls') or U.controls() if c['tui'] == k and c['where'] == where
                     and not c['needs'] == 'n'), None)

    def run_control(self, key: str, **args) -> None:
        """F82: one run control by its key; one with a confirm question waits for its TUI key again."""
        c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == key), None)
        if c is None:
            return
        if c.get('confirm') and not args.get('confirm'):
            self.confirm = key
            self.panel, self.main = 1, True
            self.set_tab('controls')
            self.msg, self.msg_ok = f'{c["confirm"]} {c["tui"]} again: yes', False
            return
        self.done(U.run_control(key, **args))

    def session_pane(self, it, tab: str, width: int) -> tuple[list, list, object]:
        L = lambda *segs: list(segs)  # noqa: E731
        name = it.get('name', '')
        if it.get('new'):
            return [L(('Starts another control session (control --new) with its claude.ai/code link, so you can',
                       'fg')), L(('talk to it from the Claude app on your phone too.', 'fg')), L(),
                    buttons(button('N', 'start one', True))], [], 0
        if tab == 'chat':
            return self.chat_head(name) + self.feed_lines(name, width, True), \
                self.input_lines(f'{name}:chat', width, f'message {name}'), 'end'
        if tab == 'feed':
            if not it.get('task'):
                return [L((idle_line(it), 'dim'))], [], 0
            head = [L((f'{name} ', 'yellow'), (f'{it["task"]} ', 'cyan'), (it.get('title', ''), 'fg')),
                    *(self.control_buttons('task') if self.task_controls_on(it) else []), L()]
            return head + self.feed_lines(name, width, self.steps), \
                self.input_lines(f'{name}:feed', width, f'message {name} (it reads it between steps)'), 'end'
        if tab == 'pane':
            if not it.get('task') and not is_control(it):
                return [L((idle_line(it), 'dim'))], [], 0
            if hidden_terminal(name):  # F88: its own terminal, through its shim's socket
                return [L((f'{name} runs hidden, in a terminal of its own.', 'fg')), L(),
                        buttons(button('⏎', f'attach {name}', True)), L(),
                        L((f'Back: {DETACH_KEY}.', 'dim'))], [], 0
            if self.snap.get('terminal_mode') == 'feed':  # Windows: a hidden console
                return [L((f'{name} runs in a hidden console (Windows): ⏎ shows it; its feed and session link '
                           f'work too.', 'dim')), L(), buttons(button('⏎', f'attach {name}', True))], [], 0
            return [L((f'{name} is not up, so it has no terminal to attach: its feed and session link work.',
                       'dim'))], [], 0
        if tab == 'diff':
            out = []
            for l in self.diff(name).splitlines()[:DIFF_LINES] or ['no changes yet']:
                colour = 'blue' if l.startswith(('diff --git', '+++', '---')) else 'green' if l.startswith('+') \
                    else 'red' if l.startswith('-') else 'cyan' if l.startswith('@@') else 'fg'
                out.append(L((l, colour)))
            return out, [], 0
        what = it.get('task') or it.get('title', '')
        out = [L((f'{name} is a Claude Code session you can open on its own, in the app or on your phone.', 'fg')),
               L()]
        out.append(L(self.link(it['link'])) if it.get('link') else
                   L(('no link yet: o asks for one (Remote Control)' if not is_control(it) else 'no link yet', 'dim')))
        out += [L(), L((f'{name} · {what}', 'dim')), L(), buttons(button('o', 'open it', True),
                                                                   button('y', 'copy link'))]
        if is_control(it):  # B125: the same message box as the chat tab
            return out, self.input_lines(f'{name}:chat', width, f'message {name}'), 0
        return out, [], 0

    def link(self, url: str) -> tuple[str, str]:
        """B125: `url` as a segment drawn as a terminal hyperlink (OSC 8, after curses' refresh)."""
        self._urls.append(url)
        return url, 'link'

    def form(self, it) -> dict:
        tid = it.get('id', '+')
        if tid not in self.forms:
            new = bool(it.get('new'))
            # the text starts empty (empty keeps it): the snapshot's title is cut at 200 characters, and sending
            # it back would cut the task; the title shows under the field instead
            was = {'text': '',
                   'kind': 'F' if new else tid[:1],
                   'pri': 'normal' if new or it.get('pri') != 'critical' else 'critical',
                   'files': '' if new else ','.join(it.get('files') or []),
                   'after': '' if new else ','.join(it.get('after') or [])}
            self.forms[tid] = {**was, 'was': was, 'new': new, 'field': ''}
        return self.forms[tid]

    def form_pane(self, it, width: int) -> list:
        f, tid = self.form(it), it.get('id', '+')
        L = lambda *segs: list(segs)  # noqa: E731

        def label(k, words, more=''):
            on = f['field'] == k
            return L((k, 'hkey'), (f' {words}', 'accent' if on else 'dim'), *([(f' {more}', 'dim')] if more else []))

        def value(k):
            box = f'form:{tid}:{k}'
            text = f[TEXT_FIELDS[k]]
            lines = text_lines(text, 'fg', width - 2, '  ❯ ', '    ')
            if self.typing == box:
                lines[-1] = lines[-1] + [('█', 'accent')]
            if k == 't' and not f['new'] and not text:  # the task's text now; empty keeps it
                # B128: the text in the typed text's colour; only the 'now:' word dim
                lines += [[('    ', '')] + l for l in wrap([('now: ', 'dim'), (it.get('title', ''), 'fg')], width - 4)]
            return lines
        out = [L(('New task: written straight to the plan (plan add).' if f['new'] else
                  f'Changes go straight to the plan (plan edit {tid}).', 'dim')), L()]
        out += [label('t', 'what, why, how to check')] + value('t')
        try:
            kind_name = U.task_kind(f['kind'] + '1', U._kind_names()) if f['kind'] else ''
        except Exception:  # noqa: BLE001 - no plan to name the kinds: the letter alone
            kind_name = ''
        kind_name = kind_name.split(':', 1)[0].strip()  # B128: the short name, not V's whole release description
        kind = L(*label('k', 'kind', '(cycles, K back)'), ('  ', ''), (f['kind'], KIND_COLOUR.get(f['kind'], 'cyan')),
                 (f' {kind_name}' if kind_name and kind_name != f['kind'] else '', 'fg'))
        k_lines = wrap(kind, width)  # a narrow pane: the run-on indented under the value, never at column 0
        out += k_lines[:1] + [[('    ', '')] + l for k in k_lines[1:] for l in wrap(k, width - 4)]
        out += [L(*label('p', 'priority', '(on / off)'), ('  ', ''),
                  (f['pri'], 'red' if f['pri'] == 'critical' else 'fg'))]
        out += [label('f', 'files')] + value('f')
        out += [label('a', 'after')] + value('a')
        out += [L(('    ', ''), (after_hint(f['after'], self.snap.get('queue') or []), 'dim')), L()]
        bs = [button('^S', 'save', True)] + ([] if f['new'] else [button('D', 'drop'), button('H', 'do it here')])
        return out + [buttons(*bs)]

    def preview_pane(self, it, width: int) -> tuple[list, int]:
        """A concept's K copy inline in the run page's style: its title, intro, and each option in a box with its
        heading in the top edge; the selected one yellow, the recommended one red."""
        L = lambda *segs: list(segs)  # noqa: E731
        page = self.concept(it)
        out = [L((page['title'] or it.get('title', ''), 'accent'))]
        if not page['options'] and not page['intro']:
            out += [L(), L(('no local copy of this page (done --artifact keeps one)', 'dim'))]
        for p in page['intro']:
            out += text_lines(p, 'dim', width)
        sel, anchor = self.option(it), 0
        for i, o in enumerate(page['options']):
            edge = 'yellow' if i == sel else 'red' if o['rec'] else 'line'
            out.append(L())
            if i == sel:
                anchor = len(out)
            name = o['name'][:max(width - 6, 4)]
            out.append(L(('┌─ ', edge), (name, edge if i == sel or o['rec'] else 'dim'),
                         (' ' + '─' * max(width - len(name) - 4, 0), edge)))
            for b in o['body']:
                out += [[('│ ', edge)] + l for l in wrap([(b, 'fg')], max(width - 2, 4))]
            out.append(L(('└' + '─' * max(width - 1, 0), edge)))
        out += [L(), L(('served from the K task\'s own copy · ', 'dim'), *button('O', 'open in the browser'))]
        return out, anchor

    # --- drawing -------------------------------------------------------------------------------------------

    def put(self, win, y: int, x: int, segs, width: int, base: int = 0, ground: str = '') -> int:
        """Write `segs` at y, x within `width` columns; `base` is added to every colour (a box's edge). `ground`
        ('sel', 'cur': the selected row) draws each colour as its pair on that row's background instead."""
        for text, colour in segs:
            if width <= 0:
                break
            text = text.replace('\n', ' ')[:width]
            if colour == 'link':  # B125: blue, and kept to be written again as an OSC 8 hyperlink
                colour = 'blue'
                url = next((u for u in self._urls if text and text in u), '')
                if url:
                    self.links.append((y, x, text, url))
            attr = self.attrs.get(f'{ground}:{colour or "fg"}', self.a(ground)) if ground else \
                self.a(colour) | base if colour or base else self.a('fg')  # B112: no colour is the ground's
            if colour in KEY_COLOURS and self._keys_on and text.strip():
                self.window_keys.add(text.strip())
            try:
                win.addnstr(y, x, text, width, attr)
            except Exception:  # noqa: BLE001 - curses refuses the bottom-right cell; the rest is drawn
                pass
            x, width = x + len(text), width - len(text)
        return x

    _keys_on = False  # while the focused side is drawn: the keys it shows are kept off the bottom line

    def edge(self, win, y: int, x: int, h: int, w: int, title, on: bool, count: str = '') -> None:
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
        self.edge(win, y, x, h, w, [(f' [{n}] {name} ', 'accent' if on else 'dim')], on, count)
        inner = h - 2
        if not rows:
            self.put(win, y + 1, x + 2, [(self.empty_line(n), 'dim')], w - 4)
            return
        lines = [self.row_lines(n, it, w - 4, on and i == cur) for i, it in enumerate(rows)]
        top = cur
        used = len(lines[cur])
        while top > 0 and used + len(lines[top - 1]) <= inner:
            top -= 1
            used += len(lines[top])
        r = y + 1
        self._keys_on = on
        for i in range(top, len(rows)):
            for segs in lines[i]:
                if r >= y + 1 + inner:
                    return
                ground = ('sel' if on else 'cur') if i == cur else ''
                if ground:
                    self.put(win, r, x + 1, [(' ' * (w - 2), '')], w - 2, ground=ground)
                self.put(win, r, x + 2, segs, w - 4, ground=ground)
                r += 1

    def draw_main(self, win, y: int, x: int, h: int, w: int) -> None:
        tab, ts = self.tab()
        title = [(' ', '')]
        for i, t in enumerate(ts):
            title += ([(' - ', 'dim')] if i else []) + [(t, ('accent' if self.main else 'fg') if t == tab else 'dim')]
        self.edge(win, y, x, h, w, title + [(' ', '')], self.main)
        body, foot, anchor = self.pane(w - 4)
        lines = [l for segs in body for l in wrap(segs, w - 4)]
        foot = [l for segs in foot for l in wrap(segs, w - 4)]
        inner = h - 2 - (len(foot) + 1 if foot else 0)
        if inner < 1:
            foot, inner = foot[-max(h - 3, 0):], 1
        off = self.off.get(self.place(), 0)
        if anchor == 'end':
            off = max(0, min(off, len(lines) - inner))
            start = max(0, len(lines) - inner - off)
        else:
            start = max(0, min(anchor - 1, len(lines) - inner)) if isinstance(anchor, int) and anchor else 0
            start = max(0, min(start + off, len(lines) - inner))
        for i, segs in enumerate(lines[start:start + inner]):
            self._keys_on = self.main
            self.put(win, y + 1 + i, x + 2, segs, w - 4)
            self._keys_on = False
        if foot:
            fy = y + h - 1 - len(foot)
            self.put(win, fy - 1, x + 1, [('─' * (w - 2), 'line')], w - 2)
            for i, segs in enumerate(foot):
                self._keys_on = self.main
                self.put(win, fy + i, x + 2, segs, w - 4)
                self._keys_on = False

    def hint_keys(self) -> list[tuple[str, str]]:
        """F76: this place's keys for the bottom line, never one the window shows (a button, a label, a row's
        own key) and never j/k or Ctrl-h/Ctrl-l."""
        it, (tab, _) = self.sel(), self.tab()
        if self.typing:
            keys = [('Esc', 'leave')]
            if self.chat_working():
                keys.insert(0, ('Ctrl+C', 'interrupts'))
            if self.typing.startswith('form:'):
                keys.append(('Tab/⇧Tab', 'field'))
            if not self.typing.startswith(('form:', 'answer:', 'edit:', 'concept:')) or \
                    self.typing.endswith(':t'):
                keys.append(('⇧⏎', 'new line'))
            return keys
        if self.main:
            if tab == 'direct edit':
                return [('Tab/⇧Tab', 'field'), ('h/l', 'tab'), ('Esc', 'back')]
            if tab == 'preview':
                return [('⏎', 'go with it'), ('i', 'what to change'), ('h/l', 'tab'), ('Esc', 'back')]
            keys = [('h/l', 'tab')]
            if self.box():
                keys.append(('i', 'type'))
            if tab == 'feed' and isinstance(it, dict) and it.get('task'):
                keys.append(('v', 'steps'))
            if tab == 'session':
                keys += [('o', 'open'), ('y', 'copy link')]
            if tab in ('chat', 'session') and self.chat_working():
                keys.append(('Ctrl+C', 'interrupts'))
            keys.append(('Esc', 'back'))
            return keys
        if self.panel == 1:
            return [('⏎', 'open'), ('R', 'release'), ('+/-', 'slots'), ('P/G', 'pause, go on'), ('S', 'stop')]
        if self.panel == 2:
            keys = [('⏎', 'open'), ('t', 'feed'), ('v', 'steps')]
            if isinstance(it, dict) and (it.get('task') or is_control(it)):
                keys += [('o', 'open session'), ('y', 'copy link')]
            if self.task_controls_on(it):
                keys += [('H', 'take back'), ('d', 'drop')]
            elif is_control(it) and it.get('name') != 'c1':
                keys.append(('d', 'close'))  # F116
            return keys
        if self.panel == 3:
            if isinstance(it, dict) and it.get('new'):
                return [('⏎', 'open'), ('E', 'chat edit')]
            if isinstance(it, dict) and it.get('state') == 'parked':
                return [('e', 'edit'), ('E', 'chat edit'), ('U', 'unpark'), ('H', 'do it here'), ('d', 'drop')]
            return [('e', 'edit'), ('E', 'chat edit'), ('J/K', 'reorder'), ('p', 'priority'), ('H', 'do it here'),
                    ('d', 'drop')]
        if self.panel == 4:
            return [('⏎', 'open'), ('a', 'answer'), ('L', 'later')] + ([('d', 'drop')] if it is not None else [])
        if isinstance(it, dict) and it.get('new'):
            return [('⏎', 'type')]
        return [('⏎', 'view'), ('O', 'open in the browser'), ('N', 'chat about it'), ('n', 'new concept'),
                ('d', 'drop')]

    GLOBAL = [('1-5', 'panel'), ('c', 'chat'), ('?', 'keys')]

    def footer(self, width: int = 0) -> list[tuple[str, str]]:
        """The bottom line after the mode badge: this place's keys (yellow), a separator, then 1-5 panel, c chat,
        ? keys (blue; none while typing, when they do not work); this place's last keys left out should `width`
        be too narrow. A message (an action's result) takes the line instead."""
        if self.msg:
            return [(self.msg, 'green' if self.msg_ok else 'red')] + \
                ([(' ', ''), self.link(self.msg_link)] if self.msg_link else [])
        keys = [kv for kv in self.hint_keys() if kv[0] not in self.window_keys]
        glob = [] if self.typing else [kv for kv in self.GLOBAL if kv[0] not in self.window_keys]  # a pick's c

        def line(keys):
            out = []
            for i, (k, v) in enumerate(keys):
                out += ([(' · ', 'dim')] if i else []) + [(k, 'hkey'), (f' {v}', 'fg')]
            if glob:
                out.append((' │ ', 'line'))
                for i, (k, v) in enumerate(glob):
                    out += ([(' · ', 'dim')] if i else []) + [(k, 'gkey'), (f' {v}', 'dim')]
            return out
        while True:
            out = line(keys)
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

    def mode(self) -> str:
        return 'INSERT' if self.typing else (self.tab()[0] if self.main else PANELS[self.panel - 1][1]).upper()

    def draw(self, win) -> None:
        h, w = win.getmaxyx()
        self.window_keys = set()
        self.links, self._urls = [], []
        self.fill(win, h, w)
        if h < 8 or w < 24:
            self.put(win, 0, 0, [('too small', 'red')], w)
            return
        ago = int(time.time() - self.got)
        top = [('agent-runner', 'accent'), (f' · {self.snap.get("project", "")}  ', 'fg'),
               ('● ', 'green' if self.snap.get('up') else 'dim'),
               (('live' if self.snap.get('up') else 'no run is up') + f' · updated {"just now" if ago < 5 else f"{ago}s ago"}', 'dim')]
        self.put(win, 0, 0, top, w)
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
                    self._keys_on = False
                y += hs[n]
        if mw:
            self.draw_main(win, 1, mx, body, mw)
        if self.help:
            lines = HELP.splitlines()
            bw, bh = min(w - 2, max(len(l) for l in lines) + 4), min(h - 2, len(lines) + 2)
            by, bx = (h - bh) // 2, (w - bw) // 2
            for r in range(bh):
                self.put(win, by + r, bx, [(' ' * bw, '')], bw)
            self.edge(win, by, bx, bh, bw, [(' Keybindings ', 'accent')], True)
            for i, l in enumerate(lines[:bh - 2]):
                self.put(win, by + 1 + i, bx + 2, help_line(l), bw - 4)
        x = self.put(win, h - 1, 0, [(f' {self.mode()} ', '')], w, self.a('mode'))
        self.put(win, h - 1, x + 1, self.footer(w - x - 2), w - x - 2)

    # --- keys and actions ------------------------------------------------------------------------------

    def refresh(self) -> None:
        try:
            self.snap = self.get_snap()
            self.got = time.time()
        except Exception as e:  # noqa: BLE001 - keep the last snapshot on screen, say why it is old
            self.msg, self.msg_ok = f'could not read the run: {e}', False
            return
        from agent_runner import __version__
        v = str(self.snap.get('version') or '')
        if newer_version(v, __version__) and v != self.followed and os.name != 'nt':  # F90; Windows: no real exec
            self.restart = True

    def saved_place(self) -> dict:
        """F90: the focused panel, the selection, tabs and focus, for `restore_place` after a restart; F92: and
        the typing boxes' drafts."""
        it = self.sel()
        sel = (it.get('id') or it.get('name') or '') if isinstance(it, dict) else ''
        return {'panel': self.panel, 'cur': {str(n): c for n, c in self.cur.items()}, 'sel': sel,
                'tabs': self.tabs, 'main': self.main, 'drafts': dict(self.drafts),
                'for': str(self.snap.get('version') or '')}

    def restore_place(self, place: dict) -> None:
        """F90: reopen where `saved_place` was (the selected item by its id or name, else by its row)."""
        if not place:
            return
        try:
            self.panel = int(place.get('panel', self.panel))
            if self.panel not in self.cur:
                self.panel = 1
            for n, c in (place.get('cur') or {}).items():
                if int(n) in self.cur:
                    self.cur[int(n)] = int(c)
        except (TypeError, ValueError):
            self.panel = 1
        rows = self.items(self.panel)
        ids = [(r.get('id') or r.get('name')) if isinstance(r, dict) else None for r in rows]
        if place.get('sel') and place['sel'] in ids:
            self.cur[self.panel] = ids.index(place['sel'])
        self.tabs.update({str(k): str(v) for k, v in (place.get('tabs') or {}).items()})
        self.main = bool(place.get('main'))
        drafts = place.get('drafts')
        if isinstance(drafts, dict):  # F92: a draft typed here is kept; the saved one fills only empty boxes
            for box, text in drafts.items():
                if isinstance(text, str) and text and not self.drafts.get(str(box)):
                    self.drafts[str(box)] = text
        self.followed = str(place.get('for') or '')

    def done(self, r: dict) -> None:
        """Show an action's result on the bottom line and read the run again."""
        out = (r.get('out') or '').strip().splitlines()
        self.msg, self.msg_ok = (out[0] if out else ('done' if r.get('ok') else 'failed')), bool(r.get('ok'))
        self.cache = {k: v for k, v in self.cache.items() if k.startswith('copy:')}  # feeds and diffs read anew
        self.refresh()

    def key(self, k: str) -> bool:
        """Handle one key (a character, or a name: UP DOWN LEFT RIGHT ENTER S-ENTER ESC TAB BTAB BS ^S ^H ^L
        ^J ^K ^C ^U); True means quit."""
        k = KEYS.get(k, k)
        self.msg, self.msg_link = '', ''
        if self.help:
            self.help = k not in ('ESC', '?', 'q', 'ENTER')
            return False
        if k == '^C':  # B116: Ctrl+C interrupts a working chat (Esc never does); elsewhere it quits
            if self.main and self.chat_working():
                self.interrupt(self.chat_name())
                return False
            return True
        if self.confirm:  # F82: stop now runs only on its key again
            key, self.confirm = self.confirm, ''
            c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == key), {})
            if k == c.get('tui'):
                self.done(U.run_control(key, confirm=True))
            else:
                self.msg, self.msg_ok = f'{c.get("label", key)}: not done', True
            return False
        if k in SIDE_KEYS:
            self.side_key(k)
            return False
        if self.typing:
            self.typed(k)
            return False
        if k == 'q':
            return True
        if k == 'ESC':  # B116: back out only, never an interrupt
            self.main = False
            return False
        if len(k) == 1 and k in '12345':
            self.panel, self.main = int(k), False
            return False
        if k == 'BS':
            self.main = False
            return False
        if k == '?':
            self.help = True
            return False
        if self.main and (handled := self.main_key(k)):
            return handled == 'quit'
        if self.main and k in MOVES:
            return False
        self.panel_key(k)
        return False

    def side_key(self, k: str) -> None:
        """F113: Ctrl-h / Ctrl-l focus the left / right side, Ctrl-j / Ctrl-k move down / up the left side's list
        (focus stays where it is), in a box too: Ctrl-h and Ctrl-j / Ctrl-k leave it with its draft kept (the box
        is the old row's); Ctrl-l in a box on the right side stays in it."""
        if k == '^L':
            if not (self.typing and self.main):
                self.typing, self.main = '', True
            return
        self.typing = ''
        if k == '^H':
            self.main = False
            return
        main = self.main
        self.panel_key('DOWN' if k == '^J' else 'UP')
        self.main = main

    def typed(self, k: str) -> None:
        """A key while typing in a box."""
        box = self.typing
        form = box.startswith('form:')
        if k == 'ESC':  # B116: leave the box only, never an interrupt
            self.typing = ''
            return
        if form and k in ('TAB', 'BTAB'):
            self.next_field(-1 if k == 'BTAB' else 1)
            return
        if form and k == '^S':
            self.save()
            return
        if k == 'ENTER' and not (form and box.endswith(':t')):
            if form:
                self.save()
            else:
                self.send(box)
            return
        if k in ('S-ENTER', 'ENTER'):
            self.set_text(box, self.text_of(box) + '\n')
        elif k == 'BS':
            self.set_text(box, self.text_of(box)[:-1])
        elif k == '^U':
            self.set_text(box, '')
        elif len(k) == 1 and k.isprintable():
            self.set_text(box, self.text_of(box) + k)

    def send(self, box: str) -> None:
        """Enter in a box: its text to where the box goes; the draft is cleared once it went."""
        text = self.text_of(box).strip()
        if not text:
            return
        kind, _, rest = box.partition(':')
        if box == 'status:chat':
            r = U.chat_to(text, 'c1')
        elif rest == 'chat':
            r = U.chat_to(text, kind)
        elif rest == 'feed':
            r = U.send(kind, text)
        elif kind == 'edit':
            r = U.chat(f'new task: {text}' if rest == '+' else f'change {rest}: {text}')
        elif kind == 'answer':
            r = U.answer(rest, text)
        elif box == 'slots:n':
            r = U.run_control('slots_set', n=text)
        elif box == 'concept:+':  # F87: a new concept, queued as a K task
            r = U.plan_add('K', text)
        elif kind == 'concept':
            it = next((c for c in self.snap.get('concepts') or [] if c.get('id') == rest), {'id': rest})
            r = U.chat(f'concept {it.get("concept") or rest} ("{it.get("title", "")}"): {text}')
        else:
            return
        if r.get('ok'):
            self.set_text(box, '')
            if not box.endswith((':chat', ':feed')):  # a chat keeps the box, as a Claude session does
                self.typing = ''
                if kind in ('edit', 'answer'):
                    self.main = False
        self.done(r)

    def chat_working(self) -> bool:
        """The main pane's chat is with a control session that is mid-turn, so Ctrl+C interrupts it (B116)."""
        name = self.chat_name()
        return bool(name) and self.working(name)

    def interrupt(self, name: str) -> None:
        self.done(U.interrupt(name))

    def main_key(self, k: str):
        """A key in the main pane; a true result when it was this tab's (or 'quit')."""
        it, (tab, ts) = self.sel(), self.tab()
        if k in ('h', 'LEFT', 'l', 'RIGHT'):
            i = ts.index(tab) + (1 if k in ('l', 'RIGHT') else -1)
            if i < 0:
                self.main = False
            else:
                self.tabs[self._tab_key(it)] = ts[min(i, len(ts) - 1)]
            return True
        if tab == 'direct edit' and it is not None and k in ('k', 'K'):
            f = self.form(it)
            i = KINDS.index(f['kind']) if f['kind'] in KINDS else -1
            f['kind'], f['field'] = KINDS[(i + (1 if k == 'k' else -1)) % len(KINDS)], 'k'
            return True
        k = VI.get(k, k)
        if tab == 'preview' and it is not None and k in ('DOWN', 'UP'):
            self.opt[it['id']] = self.option(it) + (1 if k == 'DOWN' else -1)
            self.option(it)
            return True
        if k in ('DOWN', 'UP'):
            p = self.place()
            tail = tab in TAIL_TABS
            step = 1 if (k == 'UP') == tail else -1
            self.off[p] = max(0, self.off.get(p, 0) + step)
            return True
        if k == 'i':
            self.type_in()
            return True
        if tab == 'direct edit' and it is not None:
            f = self.form(it)
            if k in ('t', 'f', 'a'):
                self.field(k)
            elif k == 'p':
                f['pri'], f['field'] = ('normal' if f['pri'] == 'critical' else 'critical'), 'p'
            elif k == 'TAB' or k == 'BTAB':
                self.next_field(-1 if k == 'BTAB' else 1)
            elif k == '^S':
                self.save()
            elif k in ('D', 'H') and not it.get('new'):
                return False  # the queue's own D and H
            elif k == 'ENTER':
                self.field(f['field'] or 't')
            else:
                return False
            return True
        if tab == 'preview' and it is not None:
            if k == 'ENTER':
                opts = self.concept(it)['options']
                if not opts:
                    self.msg, self.msg_ok = 'no options to go with: i says what to change', False
                else:
                    name = opts[self.option(it)]['name']
                    self.done(U.chat(f'concept {it.get("concept") or it["id"]} ("{it.get("title", "")}"): '
                                     f'go with {name}'))
                return True
            return False
        if tab == 'answer' and it is not None:
            for key, answer in self.answers(it):
                if k == key:
                    r = U.answer(it['id'], answer)
                    if r.get('ok'):
                        self.main = False
                    self.done(r)
                    return True
            if k == 'ENTER':
                self.type_in()
                return True
            return False
        if tab == 'chat' and self.panel == 1:
            key = next((q for q, c in QUICK_KEYS.items() if c == k), '')
            if key:
                self.done(U.quick_ask(key))
                return True
        if tab == 'release' and k in ('ENTER', 'f'):
            self.done(U.release(now=k == 'f'))
            return True
        if tab == 'pane' and k == 'ENTER':
            self.pane_attach()
            return True
        if tab == 'session' and k == 'ENTER' and not self.box():  # a control session's: Enter types (B125)
            self.open_session(it)
            return True
        if tab == 'info' and self.panel == 2 and k == 'ENTER':
            self.new_chat()
            return True
        if k == 'ENTER' and self.box():
            self.type_in()
            return True
        return False

    def field(self, k: str) -> None:
        """The direct edit's field `k` focused (typing into it, for the text ones)."""
        it = self.sel()
        if not isinstance(it, dict) or self.tab()[0] != 'direct edit':
            return
        f, self.main = self.form(it), True
        f['field'] = k
        self.typing = f'form:{it.get("id", "+")}:{k}' if k in TEXT_FIELDS else ''

    def next_field(self, step: int) -> None:
        f = self.form(self.sel())
        i = FIELDS.index(f['field']) if f['field'] in FIELDS else (-1 if step > 0 else 0)
        self.field(FIELDS[(i + step) % len(FIELDS)])

    def save(self) -> None:
        """^S: the direct edit to the plan: a new task by `plan add`, a queued one by `plan edit` with only the
        fields changed."""
        it = self.sel()
        if not isinstance(it, dict) or not it.get('id'):
            return
        f = self.form(it)
        text = f['text'].strip()
        if f['new']:
            if not text:
                self.msg, self.msg_ok = 'write what the task is first (t)', False
                return
            r = U.plan_add(f['kind'], text, f['files'].strip() or None, f['after'].strip() or None,
                           '' if f['pri'] == 'normal' else f['pri'])
        else:
            was = f['was']
            if f['kind'] != was['kind']:
                self.msg, self.msg_ok = f'{it["id"]} keeps its kind: a new kind is a new task (n)', False
                return
            changed = {k: f[k].strip() for k in ('text', 'files', 'after', 'pri') if f[k].strip() != was[k].strip()
                       and f[k].strip()}
            emptied = [k for k in ('files', 'after') if was[k].strip() and not f[k].strip()]
            if emptied:  # plan edit sets a field, never clears one
                self.msg, self.msg_ok = f'{" and ".join(emptied)} cannot be emptied here: give the new value', False
                return
            if not changed:
                self.msg, self.msg_ok = 'nothing changed', True
                return
            r = U.plan_change(it['id'], changed.get('text', ''), changed.get('files'), changed.get('after'),
                              changed.get('pri', ''))
        if r.get('ok'):
            self.forms.pop(it['id'], None)
            self.typing, self.main = '', False
        self.done(r)

    def panel_key(self, k: str) -> None:
        """A key with the panels focused (or one the main pane's tab left alone)."""
        rows, it = self.items(self.panel), self.sel()
        tid = self.tid(it)
        k = VI.get(k, k)
        if k == 'DOWN':
            self.cur[self.panel] = min(self.cur[self.panel] + 1, max(len(rows) - 1, 0))
            self.main = False
        elif k == 'UP':
            self.cur[self.panel] = max(self.cur[self.panel] - 1, 0)
            self.main = False
        elif k == 'TAB':
            self.panel, self.main = self.panel % 5 + 1, False
        elif k == 'BTAB':
            self.panel, self.main = (self.panel + 3) % 5 + 1, False
        elif k == 'ENTER' and self.tab()[0] == 'new concept' and self.box():
            self.main = True  # F111: one Enter lands in a new concept's box ('preview' keeps Enter = go with it)
            self.type_in()
        elif k in ('ENTER', 'l', 'RIGHT'):
            self.main = True
        elif k == 'c':
            self.chat_c1()
        elif k == 'i':
            self.main = True
            self.type_in()
        elif self.panel == 1 and k == 'R':
            self.release_tab()
        elif self.panel == 1 and k == '=':
            self.set_tab('controls')
            self.typing = 'slots:n'
        elif self.panel == 1 and (c := self.control_by_tui(k, 'run')):
            self.run_control(c['key'])
        elif self.panel == 2 and self.task_controls_on(it) and (c := self.control_by_tui(k, 'task')):
            self.run_control(c['key'], tid=it['task'])
        elif self.panel == 2 and k == 'd' and not self.main and self.task_controls_on(it):
            self.run_control('task_drop', tid=it['task'])  # F116: d drops a slot's task, as D does
        elif self.panel == 2 and k == 'd' and not self.main and is_control(it):
            self.close_control(it)
        elif self.panel == 2 and k == 't':
            self.feed_tab()
        elif self.panel == 2 and k == 'v':
            self.steps = not self.steps
            self.msg, self.msg_ok = f'tool steps {"shown" if self.steps else "folded"}', True
        elif self.panel == 2 and k == 'N':
            self.new_chat()
        elif self.panel == 2 and k == 'o' and isinstance(it, dict) and not it.get('new'):
            self.open_session(it)
        elif self.panel == 2 and k == 'y' and isinstance(it, dict) and not it.get('new'):
            self.copy_session(it)
        elif self.panel == 3 and k == 'n':
            self.cur[3] = len(rows) - 1
            self.set_tab('chat edit')
            self.type_in()
        elif self.panel == 3 and k == 'e' and it is not None:
            self.set_tab('direct edit')
            self.field('t')
        elif self.panel == 3 and k == 'E' and it is not None:
            self.set_tab('chat edit')
            self.type_in()
        elif self.panel == 3 and (k == 'D' or (k == 'd' and not self.main)) and tid:
            self.done(U.drop(tid, 'dropped from agent-runner ui'))
            self.main = False
        elif self.panel == 3 and k == 'H' and tid:
            self.done(U.take(tid))
        elif self.panel == 3 and k == 'U' and tid and it.get('state') == 'parked':
            r = U.unpark(tid)
            self.done(r)
            ids = [t.get('id') for t in self.items(3)]
            if r.get('ok') and tid in ids:  # the selection follows the task to its new place in the queue
                self.cur[3] = ids.index(tid)
        elif self.panel == 3 and k == 'p' and tid and it.get('state') != 'parked':
            self.done(U.plan_change(tid, pri='normal' if it.get('pri') == 'critical' else 'critical'))
        elif self.panel == 3 and k in ('J', 'K') and tid and it.get('state') != 'parked':
            self.reorder(1 if k == 'J' else -1)
        elif self.panel == 4 and k == 'a' and it is not None:
            self.set_tab('answer')
        elif self.panel == 4 and k == 'L' and it is not None:
            self.done(U.shelve(it['id']))
            self.main = False
        elif self.panel == 4 and k == 'd' and not self.main and it is not None:  # F116: a pick's d stays its option
            self.done(U.drop(it['id'], 'dropped from agent-runner ui'))
        elif self.panel == 5 and k == 'd' and not self.main and it is not None and not it.get('new'):
            self.done(U.drop(it.get('concept') or it['id'], 'dropped from agent-runner ui'))
        elif self.panel == 5 and k == 'n':  # F87: a new concept, in its row's box
            self.cur[5] = len(rows) - 1
            self.set_tab('new concept')
            self.type_in()
        elif self.panel == 5 and k == 'O' and it is not None and not it.get('new'):
            self.open_link(it.get('url', ''), it.get('title', 'the concept'))
        elif self.panel == 5 and k == 'N' and it is not None and not it.get('new'):
            self.concept_chat(it)

    def close_control(self, it: dict) -> None:
        """F116: d on control session cN (N > 1): close it (`control.close_from_tui`); on c1 only a message."""
        n = int(str(it.get('name', 'c1'))[1:])
        if n <= 1:
            self.msg, self.msg_ok = "c1 is the run's kept session: d leaves it open", False
            return
        from agent_runner import control as K
        self.done(K.close_from_tui(n))

    def concept_chat(self, it: dict) -> None:
        """F86: N on a concept: a new control session about it (`concept_chat`), its link in the message line."""
        r = U.concept_chat(it.get('concept') or it.get('id', ''), it.get('title', ''), it.get('url', ''),
                             it.get('copy', ''))
        self.done(r)
        if r.get('ok') and r.get('link'):
            self.msg = f'new control session about {it.get("concept") or it.get("id")}: {r["link"]}'

    def chat_c1(self) -> None:
        """c: c1's chat, typing: in Sessions when c1 is listed there, else Status's chat with it."""
        rows = self.items(2)
        at = next((i for i, r in enumerate(rows) if r.get('name') == 'c1'), None)
        if at is None:
            self.panel = 1
            self.set_tab('chat')
        else:
            self.panel, self.cur[2] = 2, at
            self.set_tab('chat')
        self.type_in()

    def release_tab(self) -> None:
        rows = self.items(1)
        self.cur[1] = next((i for i, r in enumerate(rows) if str(r).startswith('release')), self.cur[1])
        self.set_tab('release')

    def feed_tab(self) -> None:
        """t: the selected slot's feed; from a control session or the new chat row, the first slot on a task."""
        it = self.sel()
        if not (isinstance(it, dict) and it.get('task')):
            rows = self.items(2)
            busy = [i for i, s in enumerate(rows) if s.get('task')]
            if not busy:
                self.msg, self.msg_ok = self.snap.get('sessions_note') or 'no slot is on a task', True
                return
            self.cur[2] = busy[0]
        self.set_tab('feed')

    def reorder(self, step: int) -> None:
        """F70: Shift+J / Shift+K: the selected queued task one place down / up (`plan move ID after|before
        <neighbour>`); the selection follows it."""
        tasks = [t for t in self.items(3) if not t.get('new')]
        i = self.cur[3]
        if not 0 <= i + step < len(tasks):
            self.msg, self.msg_ok = f'{tasks[i]["id"]} is already {"last" if step > 0 else "first"}', True
            return
        r = U.move(tasks[i]['id'], 'after' if step > 0 else 'before', tasks[i + step]['id'])
        self.done(r)
        if r.get('ok'):  # the task's row in the queue read again, else the row it moved to
            ids = [t.get('id') for t in self.items(3)]
            self.cur[3] = ids.index(tasks[i]['id']) if tasks[i]['id'] in ids else i + step

    def pane_attach(self) -> None:
        """Enter on the pane tab: the session's own terminal (F88), with `attach NAME`; an idle slot has none."""
        it = self.sel()
        if not isinstance(it, dict) or it.get('new'):
            return
        if not it.get('task') and not is_control(it):  # B113: an idle slot has no window to attach
            self.msg, self.msg_ok = idle_line(it), True
            return
        self.done(self.attach(it['name']))

    def open_link(self, url: str, what: str) -> None:
        if not url:
            self.msg, self.msg_ok = f'{what} has no link yet', False
            return
        r = self.opener(url)
        self.msg, self.msg_ok = (r.get('out') or f'opened {url}'), bool(r.get('ok'))
        self.msg_link = r.get('link', '')  # B125: over ssh, the link to Cmd-click on the message line

    def session_link(self, it) -> str:
        """The session's claude.ai/code link ('' none, the reason on the message line); a slot is opened first
        (`open_session`: under `[run] sessions = 'one'` it is listed there only once asked for)."""
        if not isinstance(it, dict) or it.get('new'):
            return ''
        if is_control(it):
            if not it.get('link'):
                self.msg, self.msg_ok = f'{it["name"]} has no link yet', False
            return it.get('link', '')
        if not it.get('task'):
            self.msg, self.msg_ok = idle_line(it), True
            return ''
        r = U.open_session(it['name'])
        if not r.get('ok'):
            self.done(r)
            return ''
        return r.get('out', '').strip()

    def open_session(self, it) -> None:
        """o: the session's claude.ai/code link in the browser (over ssh: copied, and a hyperlink to Cmd-click)."""
        if url := self.session_link(it):
            self.open_link(url, it['name'])

    def copy_session(self, it) -> None:
        """B125 y: the session's link on the clipboard (OSC 52, so over ssh it lands on the person's machine)."""
        if url := self.session_link(it):
            r = copy_text(url, self.out)
            self.msg, self.msg_ok = r['out'], bool(r.get('ok'))

    def new_chat(self) -> None:
        """N: a new control session (`new_control`); it is selected, on its chat tab, typing (B125)."""
        before = {r.get('name') for r in self.items(2)}
        r = U.new_control()
        self.done(r)
        if r.get('ok') and r.get('link'):
            self.msg = f'new control session: {r["link"]}'
        rows = self.items(2)
        fresh = [i for i, s in enumerate(rows) if is_control(s) and s.get('name') not in before]
        if fresh:
            self.panel, self.cur[2] = 2, fresh[-1]
            self.set_tab('chat')
            self.type_in()


# --- what the page reads and opens --------------------------------------------------------------------------

def read_file(path: str) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return ''


def slot_diff(name: str) -> str:
    """Slot `name`'s (s2) work: its worktree against where it left the main branch, uncommitted changes too
    (the web page's diff tab, `web.slot_diff`); why not, in brackets, when there is none."""
    from agent_runner import web
    r = web.slot_diff(name)
    return r['text'] if r.get('ok') else f'({r.get("out", "no diff")})'


def term_write(seq: str) -> None:
    """Write an escape sequence straight to the terminal, past curses (OSC 52, OSC 8: nothing curses draws)."""
    try:
        os.write(sys.__stdout__.fileno(), seq.encode('utf-8'))
    except (OSError, AttributeError, ValueError):
        pass


def over_ssh() -> bool:
    """B125: this page runs over ssh (SSH_CONNECTION or SSH_TTY set): a browser opened here is not on the
    person's screen."""
    return bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'))


def osc52(text: str) -> str:
    """B125: the terminal's own clipboard set to `text` (OSC 52): over ssh it lands on the person's machine in
    iTerm2, Ghostty, kitty. Inside the person's own tmux (C26: agent-runner runs none of its own) it goes out
    through that one's passthrough too."""
    import base64
    seq = f'\x1b]52;c;{base64.b64encode(text.encode("utf-8")).decode("ascii")}\x07'
    if os.environ.get('TMUX'):
        seq += '\x1bPtmux;' + seq.replace('\x1b', '\x1b\x1b') + '\x1b\\'
    return seq


def osc8(url: str, text: str = '') -> str:
    """B125: `text` (the url itself when empty) as a terminal hyperlink (OSC 8): Cmd-click (or click) opens it
    where the terminal runs, so on the person's Mac over ssh."""
    return f'\x1b]8;;{url}\x1b\\{text or url}\x1b]8;;\x1b\\'


def copy_text(text: str, out=None) -> dict:
    """B125: `text` on the clipboard: OSC 52 always (written with `out`, the terminal by default), and on this
    machine's own clipboard too when not over ssh (wl-copy, xclip or pbcopy, the first there is)."""
    import shutil
    (out or term_write)(osc52(text))
    if not over_ssh():
        tools = ([['wl-copy']] if os.environ.get('WAYLAND_DISPLAY') else []) + \
            ([['xclip', '-selection', 'clipboard']] if os.environ.get('DISPLAY') else []) + \
            ([['pbcopy']] if sys.platform == 'darwin' else [])
        for argv in tools:
            if shutil.which(argv[0]):
                try:
                    p = sp.Popen(argv, stdin=sp.PIPE, stdout=sp.DEVNULL, stderr=sp.DEVNULL, start_new_session=True)
                    p.stdin.write(text.encode('utf-8'))
                    p.stdin.close()
                except OSError:
                    continue
                break
    return {'ok': True, 'out': 'link copied'}


def open_url(url: str, out=None) -> dict:
    """A link in this machine's browser: xdg-open on Linux, open on macOS, the default handler on Windows.
    B125: over ssh no browser here would reach the person: the link is copied (OSC 52) and shown as a terminal
    hyperlink to Cmd-click instead (`link` in the result)."""
    if over_ssh():
        copy_text(url, out)
        return {'ok': True, 'out': 'link copied, Cmd-click to open', 'link': url}
    try:
        if sys.platform.startswith('win'):
            os.startfile(url)  # noqa: S606 - the person's own link, in their own browser
        else:
            sp.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', url], stdout=sp.DEVNULL,
                     stderr=sp.DEVNULL, start_new_session=True)
    except (OSError, AttributeError) as e:
        return {'ok': False, 'out': f'could not open {url}: {e}'}
    return {'ok': True, 'out': f'opened {url}'}


# --- curses ----------------------------------------------------------------------------------------------

def curses_attrs(curses, theme: str | dict | None = None) -> dict[str, int]:
    """The theme's colour pairs on this terminal (F69: `[ui] theme` when none is given): 256 colours when it
    has them, else the 8 basic ones; the terminal theme draws in the terminal's own colours and background."""
    if not curses.has_colors():
        return {'red': curses.A_BOLD, 'accent': curses.A_BOLD, 'sel': curses.A_REVERSE, 'cur': curses.A_BOLD,
                'mode': curses.A_REVERSE, 'key': curses.A_BOLD, 'hkey': curses.A_BOLD | curses.A_REVERSE,
                'gkey': curses.A_BOLD}
    th = theme if isinstance(theme, dict) else TH.get(theme or TH.configured())
    curses.start_color()
    if -1 in (th['bg'], th['fg']):
        try:
            curses.use_default_colors()  # -1: the terminal's own foreground and background
        except Exception:  # noqa: BLE001 - a terminal without them: white on black
            th = {**th, 'bg': 0 if th['bg'] == -1 else th['bg'], 'fg': 7 if th['fg'] == -1 else th['fg']}
    col = lambda token: TH.curses_colour(th, TOKEN.get(token, token), curses.COLORS)  # noqa: E731
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
    for name in ('red', 'accent', 'key', 'hkey', 'gkey'):
        out[name] |= curses.A_BOLD
    return out


CURSES_KEYS = {'KEY_UP': 'UP', 'KEY_DOWN': 'DOWN', 'KEY_LEFT': 'LEFT', 'KEY_RIGHT': 'RIGHT', 'KEY_ENTER': 'ENTER',
               'KEY_BTAB': 'BTAB', 'KEY_BACKSPACE': 'BS'}
# what a terminal sends after Esc for Shift+Enter (kitty's and xterm's modifyOtherKeys) and Alt+Enter
SHIFT_ENTER = ('[13;2u', '[27;2;13~', '\r', '\n')


def key_name(curses, ch) -> str:
    if isinstance(ch, int):
        return CURSES_KEYS.get(curses.keyname(ch).decode('ascii', 'replace'), '')
    return ch


def escape_tail(name: str, more) -> list[str]:
    """The keys a key read from curses stands for: after Esc, ['S-ENTER'] when what follows is a Shift+Enter
    (or Alt+Enter) sequence, ['ESC'] when nothing follows, ['ESC', c] for Esc and then a fast plain key, [] for
    any other escape sequence (a key this page has no use for). `more()` gives the next character at once, or
    '' when there is none."""
    if name != '\x1b':
        return [name] if name else []
    seq = ''
    while len(seq) < 12 and (c := more()):
        seq += c
        if seq in SHIFT_ENTER:
            return ['S-ENTER']
        if len(seq) == 1 and c not in '[O':
            return ['ESC', c]
        if not (c.isdigit() or c in '[;O'):
            break
    return ['ESC'] if not seq else []


DETACH_KEY = 'Ctrl-b d'  # attach.DETACH_KEY: what leaves a hidden session's terminal


def hidden_terminal(name: str) -> bool:
    """F88: `name` (sN, cN) runs hidden with a terminal to attach to (its shim's socket is up; not Windows)."""
    try:
        from agent_runner.attach import session_socket
        return bool(session_socket(name))
    except Exception:  # noqa: BLE001 - no notes dir (no repo set up): nothing to attach
        return False


def attach_slot(curses, win, name: str) -> dict:
    """Leave curses, show the session's own terminal (F88, `attach NAME`), and come back when it returns."""
    curses.def_prog_mode()
    curses.endwin()
    try:
        r = sp.run(U.runner_cmd() + ['attach', name], cwd=U.S.ROOT, stderr=sp.PIPE, text=True)
    finally:
        curses.reset_prog_mode()
        win.refresh()
    if r.returncode:
        return {'ok': False, 'out': (r.stderr or '').strip() or f'attach {name} failed'}
    return {'ok': True, 'out': f'back from {name}'}


def link_sgr(curses, theme: str | dict | None = None) -> str:
    """B125: the SGR that draws as curses' 'blue' pair does (the theme's blue on its background), for the links
    written again past curses; '' on a terminal without colours."""
    if not curses.has_colors():
        return ''
    th = theme if isinstance(theme, dict) else TH.get(theme or TH.configured())
    fg, bg = (TH.curses_colour(th, t, curses.COLORS) for t in ('blue', 'bg'))
    part = lambda n, base: f'{base + 9}' if n < 0 else f'{base + 8};5;{n}'  # noqa: E731 - 39/49: the default
    return f'\x1b[0;{part(fg, 30)};{part(bg, 40)}m'


def links_over(links: list, sgr: str = '') -> str:
    """B125: the frame's links written again over what curses drew, each as an OSC 8 hyperlink at its place
    (the cursor saved and put back), so Cmd-click opens it on the person's machine; '' when there are none."""
    if not links:
        return ''
    out = '\x1b7'
    for y, x, text, url in links:
        out += f'\x1b[{y + 1};{x + 1}H{sgr}' + osc8(url, text) + ('\x1b[0m' if sgr else '')
    return out + '\x1b8'


def run_curses(win, box: dict | None = None) -> int:
    """The Run page's loop; F90: on a newer run it returns with the page in `box['restart']` (curses.wrapper
    then restores the terminal, and `main` starts the TUI again)."""
    import curses
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    curses.raw()  # ^S, ^H, ^L and ^C reach the page (no flow control, no signal)
    curses.nonl()  # Enter is '\r', Ctrl-J '\n' (down the left list, F113)
    attrs = curses_attrs(curses)
    win.bkgd(' ', attrs.get('fg', 0))
    win.clear()  # B112: the first refresh repaints every cell, so the terminal's earlier screen is gone
    win.keypad(True)
    win.timeout(1000)
    page = RunPage(U.snapshot(), attrs=attrs, attach=lambda name: attach_slot(curses, win, name))
    page.restore_place(taken_place())
    sgr = link_sgr(curses)

    def more() -> str:
        win.nodelay(True)
        try:
            c = win.get_wch()
            return c if isinstance(c, str) else ''
        except curses.error:
            return ''
        finally:
            win.nodelay(False)
            win.timeout(1000)
    while True:
        if time.time() - page.got >= REFRESH:
            page.refresh()
        if page.restart and box is not None:
            box['restart'] = page
            return 0
        page.draw(win)
        win.refresh()
        page.out(links_over(page.links, sgr))
        try:
            ch = win.get_wch()
        except curses.error:  # the timeout: draw again ("updated Ns ago"), read the run when it is due
            continue
        except KeyboardInterrupt:
            return 0
        if isinstance(ch, int) and ch == curses.KEY_RESIZE:
            win.clear()  # B112: the next refresh repaints every cell, not only what curses thinks changed
            continue
        for name in escape_tail(key_name(curses, ch), more):
            if page.key(name):
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
    box: dict = {}
    rc = curses.wrapper(run_curses, box)
    if box.get('restart'):  # F90: the terminal is restored; this process becomes the new version's TUI
        follow_upgrade(box['restart'])
    return rc
