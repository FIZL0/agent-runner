"""F67, F76: the Run page in the terminal: `agent-runner ui`.

The same panels, tabs and keys as the web Run page (round 2, F74's model), in curses (standard library, no new
dependency), in the lazygit layout: numbered boxed panels on the left ([1] Status, [2] Sessions, [3] Queue,
[4] Needs you, [5] Concepts), one main pane on the right with the selected item's tabs, the key hints on the
bottom line. The focused panel takes the spare height; every other panel shows 3 rows. Narrower than
`TWO_COLUMNS`, the panels and the main pane take the whole width in turn (Enter in, Esc out).

Panels and their tabs (F76):
    Status     a status line: log (the quick asks s y w u on its buttons: a new session answers), release,
               controls; the release line: release first; R (only here) opens the release tab
               (F193: with Manage releases off, no release tab, line or R here, nor a release row in the queue)
    Sessions   a control session cN, an idle slot: session; a slot on a task: session, diff. F112: the session
               tab is the real Claude Code session, not a chat view of ours: a tmux pane beside the TUI's pane
               runs `attach NAME` on its socket (F88; `SidePane`: split off when a session row is selected,
               respawned for another, killed for any other row and when the TUI quits; the TUI then draws only
               the panels, full width); l / Enter / Ctrl-l move focus into it, Ctrl-h (or tmux's prefix and an
               arrow) back. With no pane beside (no socket, or the pane closed itself) the session tab says so,
               with its link. Ctrl-f: the session full-screen between the top and bottom bars (the session pane
               between a one-row `ui --bar` pane and the TUI's pane cut to its bottom bar); again: side by side.
               The '+ new chat' row and n start one (`new_control` without waiting for its link, on a thread):
               a 'starting...' row is selected at once and its cN row takes its place once the run lists it.
               o opens the session link, y copies it (OSC 52, the terminal's own clipboard, plus
               wl-copy/xclip/pbcopy when local); over ssh o opens nothing here: it copies the link and shows it
               as a hyperlink (OSC 8) to Cmd-click
    Queue      a task: direct edit, chat edit; the '+ new task' row: chat edit, direct edit; e edit, E chat edit,
               n new, J/K reorder, p priority (cycles), H do it here, d (or D) drop; a parked task: U unpark (no J/K, p);
               F184: the shelved tasks are its last rows: info, chat edit; U brings one back, d (or D) drops it
    Needs you  answer (a button per possible answer: y yes, n no, or a b c … for options; L later; a reply box),
               info. F175b: an item with inputs has no answers: its steps with their link (Open) and command (Copy),
               a field per input (a secret hidden) and one Done (^S); Tab moves over them, Enter opens or types
    Concepts   preview: the K copy inline, its options (the copy's headings) moved through with j/k, Enter goes
               with the selected one, i says what to change, O opens the page in the browser, N starts a new
               control session about it (`concept_chat`); the '+ new concept' row and n
               queue a new concept (plan add K)

F141: the TUI always runs inside tmux. Started outside it (TMUX unset), `main` re-execs itself in the project's
tmux session (`tmux_start`: a new session, or a new window in that session). Without tmux it refuses to start
with the install line; on Windows it refuses with the run page link.

No session has a message box here (F112: the session takes its own typing); a box (a chat edit, an answer, a concept) takes typing after i (or Enter): Enter
sends, Shift+Enter (or Alt+Enter) is a new line, Esc leaves it. Each box keeps its draft across Esc and
refreshes; Ctrl-h / Ctrl-l and Ctrl-j / Ctrl-k still work in a box (F113: they leave it, its draft kept); Ctrl+C
quits. Navigation: h/l previous / next tab (h on the first tab and Esc go back to the panels), Ctrl-h / Ctrl-l
the left / right side, Ctrl-j / Ctrl-k down / up the left side's list (in a box too, F113), 1-5 a panel
(anywhere but in a box), Tab the next panel; in the main pane j/k scroll it (the terminal has no scrollbar), and
move through a concept's options.

F194c: in the example project a walkthrough's card stands over the bottom line (walk.py): the page's steps, worded for
keys; < back, > next, / skips it and shows it again. A step goes to its panel, which is marked.

The bottom line: the mode badge, this place's keys (yellow), a separator, then 1-5 panel, c new chat, ? keys
(blue); never a key the window already shows (on a button, a label, a row), never j/k or Ctrl-h/Ctrl-l.

Colours: F69's `[ui] theme` (theme.py, shared with the web page), mapped to the nearest of the terminal's 256
colours (8 on an older terminal). A key is always drawn in another colour than its label.

What it shows is `ui_model.snapshot()`, read again every `REFRESH` seconds; what it does is `ui_model`'s actions,
so the terminal changes the run as the web page does.
The screen logic (`RunPage`) draws on any object with curses' window calls (`getmaxyx`, `erase`, `addnstr`), so a
test drives it with a stub window; the diff and browser are passed in.
"""

from __future__ import annotations

import json
import os
import re
import subprocess as sp
import sys
import time
from pathlib import Path

from agent_runner import plat
from agent_runner import theme as TH
from agent_runner import ui_model as U
from agent_runner import walk as W

REFRESH = 3.0  # seconds between snapshots (and between reads of a shown diff)
TWO_COLUMNS = 70  # narrower than this: one column, the panels or the main pane
SHORT = 3  # rows an unfocused panel shows
BOX_LINES = 6  # most lines a typing box grows to
DIFF_LINES = 3000  # most lines of a slot's diff shown
RUN_START_WAIT = 10  # s F402c2: a run whose start worked but is not up by then: the panel says Not started
STARTING_WAIT = 60  # s F112: a new chat that started but is not listed by then: its 'starting...' row goes

PANELS = [(1, 'Status', 'status'), (2, 'Sessions', 'sessions'), (3, 'Queue', 'queue'),
          (4, 'Needs you', 'needs'), (5, 'Concepts', 'concepts')]
NEW_TASK = {'id': '+', 'new': True}  # the queue's last row: a new task
NEW_CHAT = {'name': '+', 'new': True}  # Sessions' last row: a new control session
NEW_CONCEPT = {'id': '+', 'new': True}  # F87: Concepts' last row: a new concept (a K task)
PLACE_ENV = 'AGENT_RUNNER_TUI_PLACE'  # F90: where the TUI was, handed to itself across an upgrade restart
EXEC_RESTART = os.name != 'nt'  # F90: a newer run restarts the TUI by exec; Windows has no real exec


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
KIND_WORD, KIND_ROOM = 9, 36  # F195b: the queue's column of kind words, in a panel at least this wide
KINDS = ('B', 'F', 'T', 'D', 'R', 'C', 'K', 'V')  # the direct edit's kind field cycles through these
QUICK_KEYS = {'since': 's', 'yesterday': 'y', 'needs': 'w', 'usage': 'u'}  # F74's quick asks, by key
FIELDS = ('t', 'k', 'p', 'f', 'a', 'e')  # the direct edit's fields, in Tab order
TEXT_FIELDS = {'t': 'text', 'f': 'files', 'a': 'after', 'e': 'needs'}  # the ones typed into
TAIL_TABS = ('log',)  # tabs that show their newest lines, at the bottom
SIDE_SHARE = '64%'  # F112: the width the session's tmux pane takes beside the TUI (the main pane's share)

# F69: the colours a segment can name, each a token of the theme (theme.py); 'accent' is the theme's accent
# (red in ryha). F76: 'hkey' a key of this place (yellow: on a button, a label, the bottom line), 'gkey' a key
# that works everywhere (blue, the bottom line's 1-5 c ?). B112: a selected row draws every segment on its row
# background: each colour gets a pair on the focused row's ('sel:red') and on the unfocused selected row's
COLOURS = ('fg', 'dim', 'line', 'accent', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'key', 'hkey',
           'gkey', 'pkey')
TOKEN = {'hkey': 'yellow', 'gkey': 'bblue', 'pkey': 'accent'}  # a colour name that is not a theme token itself
KEY_COLOURS = ('hkey', 'gkey', 'pkey')  # 'pkey': the key on the primary button (red)


def session_rows(snap: dict) -> list:
    """B112: the Sessions panel's rows: the control sessions, then every slot of the run, an idle one (no task) included, as the
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
    """B113: a control session's row (c6), not a slot's."""
    return isinstance(row, dict) and bool(re.fullmatch(r'c\d+', str(row.get('name', ''))))


def idle_line(row: dict) -> str:
    """B113: what an idle slot's pane says instead of an error: no window is open while it has no task."""
    return f'{row.get("name", "")} is idle: nothing running'


# each indented line: key, label, key, label …, two spaces or more apart (`help_line` colours them)
HELP = """Everywhere (not while typing in a box)
  1-5      focus a panel          Tab      next panel (direct edit: next field)
  j/k      move down / up         l Enter  into the main pane, next tab
  h        previous tab, out      Esc      back out
  ^h ^l    left / right side      c        new chat
  ^j ^k    down / up the left list (these four work in a box too)
  ^f       a session full-screen between the bars (again: side by side)
  i        type in the box        ?        this list
  q ^C     quit                   0        all runs (the pick-a-run screen)
Status [1]
  R        release                s y w u  quick asks (a new session answers)
  + - =    slot +1, -1, set N     P G      pause, go on
  F C      force, caps back on    S        stop (running tasks finish)
  X X      stop now (X again)     U        take the stop back
  V V      upgrade agent-runner   Z Z  B B  suspend, shut down once stopped (again: undo)
  Y Y      restart the run        T        start the run (none is up)
  r        resume a cut-off task  L        release stale claims
  W E      moved-aside edits: show, restore                O O      drop them
Sessions [2]
  t        a slot on a task
  g        a slot's diff in place of its session (again: the session; its pane goes, then back)
  n        new chat               o        open the session link
  y        copy the session link (the terminal's clipboard, so over ssh too)
{task_actions}
{session_actions}
  r        rename a control session cN: the name is yours, so it is never closed when idle
  l ^l     into the session's tmux pane (back: ^h, or tmux's prefix and an arrow)
  Enter    the same; its pane closed: show it beside again
Queue [3]
  e        direct edit            E        chat edit
  n        new task               J/K      move down / up
  R        new release (the release tab; D there drops one that has not started)
{queue_actions}
{shelved_actions}
  ^S       save the direct edit
  t k K   what, kind (cycles, back)        p f a    priority, files, after
Needs you [4]
  a        answer
{need_actions}
  Tab      next link, field        ^S       Done (send what you entered)
Concepts [5]
  j/k      option                 Enter    go with it
  i        what to change         O        open in the browser
{concept_actions}
  n        new concept (queued as a K task)
Typing (a task, an answer, a concept: a session takes its own typing)
  Enter    send                   Shift+Enter  new line (or Alt+Enter)
  Esc      leave the box
Esc closes this."""


ROW_PANELS = {2: 'session', 3: 'queue', 4: 'need', 5: 'concept'}  # C35: the panels whose rows have actions


def action_help(where: str) -> str:
    """C34: the keys list's lines for panel `where`'s row actions (ui_model.RUN_CONTROLS), two to a line."""
    cs = [c for c in U.RUN_CONTROLS if c['where'] == where]
    cells = [(c.get('help_keys') or (f'{c["tui_also"]} {c["tui"]}' if c.get('tui_also') else c['tui']),
              c.get('help') or c['label'].lower()) for c in cs if c.get('help') != '']
    return '\n'.join('  ' + ''.join(f'{k:<9}{v:<23}' if j < len(row) - 1 else f'{k:<9}{v}'
                                    for j, (k, v) in enumerate(row)) for row in
                     (cells[i:i + 2] for i in range(0, len(cells), 2)))


for _w in ('queue', 'shelved', 'need', 'concept', 'task', 'session'):
    HELP = HELP.replace('{%s_actions}' % _w, action_help(_w))


def help_text(releases: bool, walk: bool = False) -> str:
    """The keys list; F193: with Manage releases off (`releases` False), without its R lines; F194c: `walk`, with the
    walkthrough's keys."""
    text = HELP if releases else \
        re.sub(r'(?m)^  R        release +', '  ', re.sub(r'(?m)^  R        new release.*\n', '', HELP))
    if walk:
        text = text.replace('Status [1]\n', f'  {W.BACK} {W.NEXT}      walkthrough back, next   {W.SKIP}        '
                            'skip it, show it again\nStatus [1]\n', 1)
    return text


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
        '\x08': '^H', '\x0c': '^L', '\x7f': 'BS', '\x03': '^C', '\x15': '^U', '\x06': '^F'}
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


def queue_with_releases(snap: dict) -> list:
    """F195c: the queue panel's rows: the queue's, each release at its place, and the auto release's count (no task)
    before the row its `before` names, else after the last one that is not parked."""
    rows = list(snap.get('queue') or [])
    for r in snap.get('releases') or []:
        if r.get('placeholder') and not r.get('id'):
            i = next((i for i, t in enumerate(rows) if r.get('before') and t.get('id') == r['before']),
                     1 + max((i for i, t in enumerate(rows) if t.get('state') != 'parked'), default=-1))
            rows.insert(i, dict(r, new=True, id='release'))
    return rows


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

    def __init__(self, snap: dict, get_snap=None, attrs=None, diff=None, opener=None,
                 read=None, out=None, tmux=None, socket=None, walk=None):
        self.snap = snap
        self.walk = walk  # F194c: the example project's walkthrough (walk.Walk), else None
        self.socket = socket or hidden_terminal  # F88: the session has a socket to attach to
        self.side = SidePane(tmux)  # F112: the selected session in a tmux pane beside this one
        self.full = False  # F112 Ctrl-f with no session pane beside: the main pane between the bars, no panels
        self.bar_only = False  # F112 `ui --bar`: only the top bar (the top pane of tmux's full-screen layout)
        self.repaint = False  # B136: an in-process action may have written to the terminal; clear it next frame
        self.starting: dict | None = None  # F112: the new control session n started, until its row is up
        self.run_start: dict | None = None  # F402c2: the run T starts, until it is up or its start failed
        self.run_failed = ''  # F402c2: why the last start failed, until the next one or a run is up
        self.get_snap = get_snap or (lambda: U.snapshot())
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
        self.typing = ''  # the box taking typed keys ('' none): 'edit:Q2', 'form:Q2:t', …
        self.drafts: dict[str, str] = {}  # each box's text, kept across Esc and refreshes
        self.secrets: dict[str, str] = {}  # F175b: typed secrets, by box; apart from drafts, which a restart hands on
        self.give_at: dict[str, int] = {}  # each Needs you item's place in `give_ring`
        self.give_row, self.give_see = (0, 0), False  # the lines of that place; to be scrolled into view
        self.give_said: dict = {}  # what Done refused: {'id', 'field', 'out'}
        self.give_sure: tuple = ()  # (the item, its question) while Done waits for its key again
        self.forms: dict[str, dict] = {}  # each direct edit's fields, by task id ('+' a new task)
        self.cache: dict[str, tuple[float, object]] = {}  # diffs and concept copies read lately
        self.off: dict[str, int] = {}  # each place's scroll (j/k in the main pane)
        self.opt: dict[str, int] = {}  # each concept's selected option
        self.msg, self.msg_ok = '', True
        self.got = time.time()
        self.window_keys: set[str] = set()  # the keys the last frame showed above the bottom line
        self.confirm = ''  # F82: the run control waiting for its key again (stop now), '' none
        self.confirm_ask, self.confirm_seen = '', ''  # F186: its question, and the open releases a New release names
        self.confirm_id = ''  # F124: what that control works on (a moved-aside branch), '' none
        self.last_result: dict = {}  # C34: the last run control's result
        self.output: list[str] = []  # F124: what the last W showed
        self.restart = False  # F90: the run is on a newer version: start this TUI again on it (`follow_upgrade`)
        self.pick = False  # B153: quit for the pick-a-run screen (0, the project name's key)
        self.followed = ''  # F90: the version the last restart was for (never restart twice for one version)

    # --- what is where --------------------------------------------------------------------------------

    def items(self, n: int) -> list:
        key = PANELS[n - 1][2]
        if key == 'sessions':
            return session_rows(self.snap) + ([self.starting] if self.starting else []) + \
                ([NEW_CHAT] if not self.snap.get('sessions_note') else [])
        rows = list(self.snap.get(key) or [])
        if key == 'concepts':
            return rows + [NEW_CONCEPT]
        return queue_with_releases(self.snap) + [NEW_TASK] + list(self.snap.get('shelved') or []) \
            if key == 'queue' else rows  # F184: the shelved tasks after the queue, which they are not in

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

    def manage_releases(self) -> bool:
        """F193: the snapshot's `[run] releases`; off, nothing about releases shows."""
        return self.snap.get('manage_releases', True)

    def tab_list(self, n: int, it) -> list[str]:
        if n == 1 and not self.manage_releases():
            return ['log', 'controls']
        if it is None:
            return ['log', 'release', 'controls'] if n == 1 else ['info']
        if n == 1:  # F112: no chat tab: a chat is a session row, shown as itself
            return ['release', 'log', 'controls'] if str(it).startswith('release') else \
                ['log', 'release', 'controls']
        if n == 2:
            if it.get('new'):
                return ['info']
            return ['session', 'diff'] if it.get('task') and not is_control(it) else ['session']
        if n == 3:
            if it.get('placeholder'):  # F131, F185: a release that is no open task: the release tab
                return ['release']
            if it.get('state') == 'shelved':  # F184
                return ['info', 'chat edit']
            return ['chat edit', 'direct edit'] if it.get('new') else ['direct edit', 'chat edit']
        if n == 5 and it.get('new'):
            return ['new concept']
        return ['answer', 'info'] if n == 4 else ['preview']

    def _tab_key(self, it) -> str:
        if isinstance(it, dict):
            return f'{self.panel}:{it.get("id") or it.get("name") or ""}'
        if self.panel == 1 and it is not None:  # a status line by its first word: its numbers change
            word = str(it).split(':')[0].split()[0] if str(it).split() else ''
            return '1:run' if str(it).startswith('no run') else f'1:{word}'  # F402c2: one row, its tab kept as a run comes up
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
        """The box of the main pane's tab ('' none): 'edit:Q2', 'answer:D3', 'concept:F4'. F112: a session has
        none: it is shown as itself (a tmux pane beside the TUI)."""
        it, tab = self.sel(), self.tab()[0]
        if it is None:
            return ''
        if tab == 'chat edit':
            return f'edit:{it["id"]}'
        if tab == 'answer':
            return '' if self.give_inputs(it) else f'answer:{it["id"]}'
        if tab in ('preview', 'new concept'):
            return f'concept:{it["id"]}'
        return ''

    def text_of(self, box: str) -> str:
        if box.startswith('form:'):
            _, tid, f = box.split(':')
            return self.forms.get(tid, {}).get(TEXT_FIELDS[f], '')
        return (self.secrets if box.startswith('givesec:') else self.drafts).get(box, '')

    def set_text(self, box: str, text: str) -> None:
        if box.startswith('form:'):
            _, tid, f = box.split(':')
            if tid in self.forms:
                self.forms[tid][TEXT_FIELDS[f]] = text
            return
        kept = self.secrets if box.startswith('givesec:') else self.drafts
        if text:
            kept[box] = text
        else:
            kept.pop(box, None)

    def type_in(self) -> None:
        """i: type into the main pane's box (in a direct edit, its what field)."""
        if self.tab()[0] == 'direct edit':
            self.field('t')
            return
        if self.giving():  # F175b: the first field
            self.main = True
            self.give_go(next(i for i, x in enumerate(self.give_ring(self.sel())) if x[0] == 'field'))
            return
        if box := self.box():
            self.main, self.typing = True, box
        else:
            self.msg, self.msg_ok = 'nothing to type into here', True

    # --- the diff -------------------------------------------------------------------------------------

    def cached(self, key: str, read):
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < REFRESH:
            return hit[1]
        try:
            got = read()
        except Exception as e:  # noqa: BLE001 - a read that fails says why, in the pane
            got = f'(could not read: {e})'
        self.cache[key] = (time.time(), got)
        return got

    def diff(self, name: str) -> str:
        return self.cached(f'diff:{name}', lambda: self.diff_of(name)) or ''

    def kind_of(self, tid: str) -> dict:
        """F195b: the kind of task `tid`: its word and colour (`theme.kind_of`), as the snapshot's project names them."""
        return TH.kind_of(tid, self.snap.get('kinds'))

    def kind_colour(self, tid: str) -> str:
        """F195b: the colour of task `tid`'s kind; a Needs you id that is no task's (a tool, a pitch) is yellow."""
        return TH.kind_token(self.kind_of(tid)) if TH.TASK_ID.match(tid) else 'yellow'

    # --- rows and the main pane, as (text, colour) segments ------------------------------------------------

    def row(self, n: int, it) -> list[tuple[str, str]]:
        if n == 1:
            if it.startswith('no run') and self.off_row(it):
                said = self.off_said()
                return [('● ', 'yellow' if self.run_start else 'red'), (said.splitlines()[0], 'fg')] + \
                    ([] if self.run_start or self.run_failed else [(' · ', 'dim'), ('T', 'hkey'), (' start', 'dim')])
            colour = 'green' if it.startswith('run up') else 'red' if it.startswith('no run') else \
                'yellow' if it.startswith(('usage', U.NO_SETTINGS, '[run] agent', 'Claude login', 'No Claude login')) else 'magenta' if it.startswith('release') else 'dim'
            return [('● ', colour), (it, 'fg')]
        if n == 2:
            if it.get('starting'):  # F112: a new control session on its way up
                return [(f'{it.get("label") or "c…"} ', 'red'), ('starting...', 'dim')]
            if it.get('new'):
                return [('+ ', 'green'), ('new chat ', 'dim'), ('n', 'hkey')]
            if is_control(it):
                return [(f'{it["name"]} ', 'red'), (it.get('title', ''), 'fg'), (' chat', 'dim')]
            if not it.get('task'):
                return [(f'{it["name"]} ', 'dim'), (it.get('state') or 'idle', 'dim')]
            mins = f' {it["minutes"]}m' if it.get('minutes') is not None else ''
            return [(f'{it["name"]} ', 'magenta' if it.get('state') == 'merging' else 'yellow'),
                    (f'{it.get("task", "")} ', self.kind_colour(it.get('task', ''))), (it.get('title', ''), 'fg'),
                    (f'{mins} {it.get("state", "")}', 'dim')]
        if n == 4:
            # B152: the short ask, one line; the full ask shows in the pane beside
            d = it.get('detail') or {}
            said, flat = d.get('summary') or '', ' '.join(str(it.get('ask', '')).split()).casefold()
            if not U.need_detail.ASKS.fullmatch(d.get('question') or '') and \
                    (said in [*d.get('steps', []), *d.get('expect', [])] or said.casefold() in flat):
                said = U.ask_short(said)  # B793b: the ask's own words, whole in detail; a question and an ask file's summary stay
            short = ' '.join(str(said or it.get('ask_short') or it.get('title') or it.get('ask', '')).split())
            return self.news_badge(it) + [(f'{it["id"]} ', self.kind_colour(it['id'])), (short, 'fg'),
                                          (f' {it.get("age", "")}', 'dim')]
        if it.get('new'):
            return [('+ ', 'green'), ('new concept ', 'dim'), ('n', 'hkey')]
        need = self.concept_need(it)  # F197b2: its Needs you item's badge, label and age, as panel 4 shows them
        tail = ' '.join(x for x in (need.get('label', ''), need.get('age', '')) if x)
        return self.news_badge(it) + [('◆ ', 'magenta'), (it.get('title', ''), 'fg')] + \
            ([(f' {tail}', 'dim')] if tail else [])

    def news_badge(self, it) -> list[tuple[str, str]]:
        """F197b2: the New / Updated badge of a Needs you item or a concept (its own or its concept's news_words)."""
        words = it.get('news_words') or self.concept_of(it).get('news_words') or ''
        return [(f'{words} ', 'green')] if words else []

    def concept_of(self, it) -> dict:
        """F197b2: the Concepts row of the same concept as Needs you item `it` ({} none)."""
        return next((c for c in self.snap.get('concepts') or [] if isinstance(c, dict) and it.get('label') == 'CONCEPT'
                     and c.get('id') == it.get('id')), {})

    def concept_need(self, it) -> dict:
        """F197b2: the Needs you item of Concepts row `it` ({} none)."""
        return next((n for n in self.snap.get('needs') or [] if isinstance(n, dict) and n.get('label') == 'CONCEPT'
                     and n.get('id') == it.get('id')), {})

    def queue_tag(self, it) -> tuple[str, str]:
        """A queue row's right tag: 'sN Nm' (yellow) while a slot runs it, 'critical' (red), 'blocked' (red),
        '⧗ after <id title>' (dim) while it waits, '⧗ waits for iPhone 15, …' (dim) while a shared tool keeps it, 'parked' (dim) at level later (B123: a run never starts it),
        'shelved' (dim: F184), 'Split: 2 of 4 parts landed' (dim: B811b), 'high' (yellow: F438), 'ready' (green)."""
        state = str(it.get('state') or '')
        if state in ('parked', 'shelved', 'held'):  # F184, F429
            return state, 'dim'
        if state.startswith('running'):
            return state[len('running'):].strip() or 'running', 'yellow'
        if state == 'blocked' or (not state and it.get('blocked')):
            return 'blocked', 'red'
        if state == 'critical' or (not state and it.get('pri') == 'critical'):
            return 'critical', 'red'
        if state == 'after' or (not state and it.get('after')):
            words = it.get('after_title') or ', '.join(it.get('after') or [])
            return f'⧗ after {words}', 'dim'
        if state == 'tool':  # F168
            return f'⧗ {it.get("tool_wait") or "waits for a tool"}', 'dim'
        if state == 'split' and it.get('split'):  # B811b
            return it['split']['words'], 'dim'
        if it.get('pri') == 'high':  # F438: ready, and tried ahead of the normal ones
            return 'high', 'yellow'
        return 'ready', 'green'

    def kind_word(self, tid: str, width: int) -> str:
        """F195b: task `tid`'s kind word as the queue panel's column; '' in a panel too narrow for it (the selected
        row says it beside its tag)."""
        return self.kind_of(tid)['word'][:KIND_WORD - 1].ljust(KIND_WORD) if width >= KIND_ROOM else ''

    def row_lines(self, n: int, it, width: int, open_: bool) -> list:
        """A row as lines of segments within `width`; the selected row of the focused queue (`open_`) wraps to
        show its whole title and its tag (the after line) under it."""
        if n == 1 and open_ and self.run_failed and self.off_row(it):  # F402c2: why, whole
            return [[('● ' if i == 0 else '  ', 'red')] + l for i, l in enumerate(text_lines(self.off_said(), 'fg', max(width - 2, 4)))]
        if n == 1 and open_ and it.startswith('#'):  # F420: a pull request, its link too
            return wrap(self.row(n, it), max(width, 4))
        if n != 3:
            return [self.row(n, it)]
        rel = it if it.get('placeholder') else it.get('release')
        if rel:  # F185: 'V5 Release · releasing now'; dimmed 'Next release · auto at 10 landed: 6/10'
            text = f'{rel["id"]} {rel["title"]} · {rel["all"]}{rel.get("note", "")}' if open_ and rel.get('all') and it.get('release') else rel['text']
            if it.get('placeholder'):
                lines = wrap([(text, 'dim')], max(width, 4)) if open_ or len(text) <= width else \
                    [[(text[:max(width - 1, 0)] + '…', 'dim')]]
                return lines
            tid = rel['id']  # F195b: the only filled kind
            chip = [(f'{tid.ljust(max(5, len(tid) + 1))}{self.kind_word(tid, width)}', 'kindv'), (' ', '')]
            used, text = len(chip[0][0]) + 1, text.removeprefix(f'{tid} ')
            room = max(width - used, 4)
            if open_:
                return [(chip if i == 0 else [(' ' * used, '')]) + l for i, l in enumerate(wrap([(text, 'fg')], room))]
            return [chip + [(text if len(text) <= room else text[:room - 1] + '…', 'fg')]]
        if it.get('new'):
            return [[('+ ', 'green'), ('new task ', 'dim'), ('n', 'hkey')]]
        tid = it.get('id', '')
        word = self.kind_word(tid, width)
        head = [(tid.ljust(max(5, len(tid) + 1)) + word, self.kind_colour(tid))]
        idw = len(head[0][0])
        tag, colour = self.queue_tag(it)
        title = it.get('title', '')
        if open_:
            lines = [l for l in wrap([(title, 'fg')], max(width - idw, 4))]
            out = [(head if i == 0 else [(' ' * idw, '')]) + l for i, l in enumerate(lines)]
            said = [(f'{self.kind_of(tid)["word"]} · ', self.kind_colour(tid))] if not word and self.kind_of(tid)['word'] else []
            out += [[(' ' * idw, '')] + l for l in wrap([*said, (tag, colour)], max(width - idw, 4))]
            return out
        room = width - idw
        tag = tag if len(tag) <= max(room * 42 // 100, 6) else tag[:max(room * 42 // 100, 6) - 1] + '…'
        tw = max(room - len(tag) - 1, 0)
        t = title if len(title) <= tw else title[:max(tw - 1, 0)] + ('…' if tw else '')
        return [head + [(t.ljust(tw), 'fg'), (' ', ''), (tag, colour)]]

    def concept(self, it) -> dict:
        """The concept page of a Concepts row (or a Needs you CONCEPT item), parsed from its K copy."""
        copy = it.get('copy') or next((c.get('copy') for c in self.snap.get('concepts') or []
                                       if c.get('id') == it.get('id')), '')
        html = self.cached(f'copy:{copy}', lambda: self.read(copy)) if copy else ''
        return U.concept_page(html) if html else {'title': '', 'intro': [], 'options': []}

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
        if tab == 'log':  # F112: the quick asks (each a new session, which answers there) at its foot
            asks = self.snap.get('quick_asks') or U.quick_asks()
            row = buttons(*[button(QUICK_KEYS.get(q['key'], '?'), q['label']) for q in asks])
            return [L((l, 'dim' if l.startswith('===') else 'fg')) for l in self.snap.get('log') or []] or \
                [L(('the run log is empty', 'dim'))], [row], 'end'
        if tab == 'release':
            return self.release_pane(width), [], 0
        if tab == 'controls':
            foot = self.input_lines('slots:n', width, 'how many slots') if self.typing == 'slots:n' else \
                self.input_lines(self.typing, width, 'which one') if self.typing.startswith('ctl:') else []
            return self.controls_pane(width), foot, 0
        if it is None:
            return [L((self.empty_line(self.panel), 'dim'))], [], 0
        if self.panel == 2:
            return self.session_pane(it, tab, width)
        if tab == 'direct edit':
            return self.form_pane(it, width), [], 0
        if tab == 'chat edit':
            if it.get('new'):
                out = [L(('Describe the task in your own words; a new chat writes it, picks the files and queues it.',
                          'dim'))]
                hint = 'e.g. the board should show usage too'
            else:
                out = [L(('Say what to change about ', 'dim'), (it['id'], 'dim'), ('; a new chat rewrites the task.', 'dim')),
                       L()] + [[(f'{it["id"]} ', self.kind_colour(it['id']))] + l
                               for l in wrap([(it.get('title', ''), 'fg')], width - len(it['id']) - 1)]
                hint = 'e.g. also cover openmx'
            return out, self.input_lines(f'edit:{it["id"]}', width, hint), 0
        if tab == 'answer':
            out = self.need_lines(it, width)
            if it.get('url'):
                out += [L(), L((it['url'], 'blue'))]
            if self.give_inputs(it):
                return out, self.give_foot(it, width), 0
            out += [L(), L(('Your reply is the answer: a run starts it.' if it.get('label') == 'DECIDE' else
                            'Your reply goes to a new chat, which settles the item.', 'dim'))]
            fixed = [c for c in self.row_controls(it, 'need') if c.get('tab') == tab]
            row = buttons(*[button(c['tui'], c['shown']) for c in fixed if c['tui']], button('L', 'later'))
            more = ', '.join(c['shown'] for c in fixed if not c['tui']) if it.get('label') == 'DECIDE' else ''
            if more:  # F181c: options past the last key
                out += text_lines(f'More options, typed as the reply: {more}', 'dim', width)
            return out, [row] + self.input_lines(f'answer:{it["id"]}', width, 'or your own reply'), 0
        if tab == 'info' and self.panel == 3:  # F184: a shelved task
            out = [L((f'{it["id"]} ', self.kind_colour(it['id'])), (it.get('title', ''), 'fg')), L(),
                   L(('shelved: off Needs you until you bring it back', 'dim')), L()]
            out += text_lines(it.get('ask', ''), 'fg', width)
            return out, [buttons(*[button(c['tui'], c['label'].lower()) for c in self.row_controls(it, 'shelved')])], 0
        if tab == 'info' and self.panel == 4:
            out = [L((f'{it["id"]} ', self.kind_colour(it['id'])), (it.get('title', ''), 'fg')), L(),
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

    def need_lines(self, it, width: int) -> list:
        """F162: what a Needs you item says, as the run page's popup does: its heading, what is wanted and where, the
        background, the steps, what to see, the notes and the pictures' paths; its ask when it has no detail."""
        L = lambda *segs: list(segs)  # noqa: E731
        d = it.get('detail')
        if not d:
            if it.get('label') == 'DECIDE':  # B223b: what it asks is the heading here too
                return text_lines(it.get('ask', ''), 'fg', width, f'{it["id"]} ', ' ' * (len(it['id']) + 1), self.kind_colour(it['id'])) + \
                    text_lines(it.get('title', ''), 'dim', width)
            return [L((f'{it["id"]} ', self.kind_colour(it['id'])), (it.get('title', ''), 'fg')), L()] + \
                text_lines(it.get('ask', ''), 'fg', width)
        lab = d['said'] + (f' · {d["where"]}' if d.get('where') else '')
        if q := d.get('question'):  # B223b: a DECIDE's heading, its task's title under it
            tid = it['id'] + ' '
            out = text_lines(q, 'fg', width, tid, ' ' * len(tid), self.kind_colour(it['id']))
            if d['title'] not in (it['id'], q):
                out += text_lines(d['title'], 'dim', width)
        else:
            out = [L((f'{it["id"]} ', self.kind_colour(it['id'])), (d['title'], 'fg'))]
        out.append(L((lab, 'yellow'), (f'  {it.get("age", "")}', 'dim')))
        for x in d.get('why') or []:  # B794: why a BLOCKED stopped
            out += [L()] + text_lines(f'Why: {x}', 'fg', width)
        for x in d['lead']:
            out += [L()] + text_lines(x, 'fg', width)
        for head, xs, mark in (('What to do', d['steps'], lambda j: f'{j}. '),
                               ('What you should see', d['expect'], lambda j: '- ')):
            if xs:
                out += [L(), L((head, 'dim'))]
                for j, x in enumerate(xs, 1):
                    out += text_lines(x, 'fg', width, mark(j), ' ' * len(mark(j)))
                    if xs is d['steps']:
                        self.step_lines(it, j - 1, width, out)
        self.give_fields(it, width, out)
        for head, video in (('Videos', True), ('Pictures', False)):  # F445a: a terminal plays none: where it is
            shots = [s for s in d['shots'] if bool(s.get('video')) == video]
            out += [L(), L((head, 'dim'))] if shots else []
            for s in shots:
                out += text_lines(s['path'], 'blue', width)
                out += text_lines(s['caption'], 'dim', width) if s.get('caption') else []
        if d['notes']:
            out.append(L())
            for x in d['notes']:
                if not (self.give_inputs(it) and re.match('reply (done|yes)', x, re.I)):  # as the run page
                    out += text_lines(x, 'dim', width)
        return out

    # --- F175b: what a Needs you item asks the person to give -------------------------------------------------

    @staticmethod
    def give_inputs(it) -> list[dict]:
        return ((it.get('detail') or {}).get('inputs') or []) if isinstance(it, dict) else []

    def giving(self) -> bool:
        """The main pane's tab is the answer of a Needs you item with inputs."""
        return self.panel == 4 and self.tab()[0] == 'answer' and bool(self.give_inputs(self.sel()))

    @staticmethod
    def give_box(it, x: dict) -> str:
        return f'{"givesec" if x["kind"] == "secret" else "give"}:{it["id"]}:{x["key"]}'

    def give_ring(self, it) -> list[tuple]:
        """What Tab goes over on item `it`: ('open' | 'copy', a step's index) and ('field', an input), as drawn."""
        more = (it.get('detail') or {}).get('step_more') or []
        return [(act, j) for j, m in enumerate(more) for act, k in (('open', 'link'), ('copy', 'cmd')) if m.get(k)] + \
            [('field', x) for x in self.give_inputs(it)]

    def give_on(self, it):
        """The one Tab is on, None when the item has none."""
        ring = self.give_ring(it)
        return ring[min(self.give_at.get(it['id'], 0), len(ring) - 1)] if ring else None

    def give_go(self, i: int) -> None:
        """Tab onto the ring's place `i` (round its ends): a field is typed into."""
        it = self.sel()
        ring = self.give_ring(it)
        i %= len(ring)
        self.give_at[it['id']], self.give_see = i, True
        self.typing = self.give_box(it, ring[i][1]) if ring[i][0] == 'field' else ''

    def give_step(self, step: int) -> None:
        it = self.sel()
        n = len(self.give_ring(it))
        self.give_go((min(self.give_at.get(it['id'], 0), n - 1) + step) % n)

    def give_mark(self, on: bool, label: str) -> list:
        """A button of the ring: Enter presses it while Tab is on it."""
        return button('⏎', label, True) if on and self.main and not self.typing else [(f'[{label}]', 'fg' if on else 'dim')]

    def step_lines(self, it, j: int, width: int, out: list) -> None:
        """Step `j`'s link with Open, and its command with the machine to run it on and Copy, added to `out`."""
        more = (it.get('detail') or {}).get('step_more') or []
        m, at = more[j] if j < len(more) else {}, self.give_on(it)
        for act, k, label, colour in (('open', 'link', 'Open', 'blue'), ('copy', 'cmd', 'Copy', 'fg')):
            if not m.get(k):
                continue
            top = len(out)
            if act == 'copy':
                out += text_lines(f'Run on {m.get("on") or "this machine"}', 'dim', width, '   ', '   ')
            out += text_lines(m[k], colour, width, '   ', '   ')
            out.append([('   ', '')] + self.give_mark(at == (act, j), label))
            if at == (act, j):
                self.give_row = (top, len(out) - 1)

    def give_fields(self, it, width: int, out: list) -> None:
        """One field per input, added to `out`: its label, what is typed (a secret as dots), its hint or the refusal."""
        xs, at, said = self.give_inputs(it), self.give_on(it), self.give_said if self.give_said.get('id') == it.get('id') else {}
        if xs:
            out += [[], [('What to enter', 'dim')]]
        for x in xs:
            box, on, top = self.give_box(it, x), at == ('field', x), len(out)
            text, typing = self.text_of(box), self.typing == box
            out += text_lines(x['label'], 'accent' if on and self.main else 'fg', width)
            lines = text_lines('•' * len(text) if x['kind'] == 'secret' else text, 'fg', width - 1, '❯ ', '  ')[-BOX_LINES:]
            if typing:
                lines[-1] = lines[-1] + [('█', 'accent')]
            elif not text:
                lines = [[('❯ ', 'dim')] + self.give_mark(on, 'type')]
            out += lines
            if x['key'] == said.get('field'):
                out += text_lines(said['out'], 'red', width, '  ', '  ')
            if x['hint'] and not (x['key'] == said.get('field') and x['hint'] in said['out']):
                out += text_lines(x['hint'], 'dim', width, '  ', '  ')
            if on:
                self.give_row = (top, len(out) - 1)
            out.append([])
        if xs:
            out.pop()

    def give_foot(self, it, width: int) -> list:
        """Done, under the fields; its question in its place while it waits for its key again."""
        if self.give_sure and self.give_sure[0] == it['id']:
            return text_lines(f'{self.give_sure[1]} ^S again: yes, send it; any other key: no', 'red', width)
        said = self.give_said if self.give_said.get('id') == it['id'] else {}
        loose = said.get('out') and said.get('field') not in [x['key'] for x in self.give_inputs(it)]
        return (text_lines(said['out'], 'red', width) if loose else []) + \
            [buttons(button('^S', 'Done', True), button('L', 'later'))]

    def give(self, confirm: bool = False) -> None:
        """Done: what was entered goes straight to the run (`need_give`). This page is this computer's own terminal,
        so a secret may be sent."""
        it = self.sel()
        xs, tid = self.give_inputs(it), it['id']
        values = {x['key']: self.text_of(self.give_box(it, x)) for x in xs}
        r = self.quiet(U.need_give, tid, values, confirm=confirm, secure=True)
        self.give_said = {}
        if r.get('ok'):
            for kept in (self.drafts, self.secrets):
                for box in [b for b in kept if b.startswith((f'give:{tid}:', f'givesec:{tid}:'))]:
                    del kept[box]
            self.typing, self.main = '', False
            self.give_at.pop(tid, None)
            self.done(r)
            return
        if r.get('confirm'):
            self.typing, self.give_sure = '', (tid, r['confirm'])
            return
        self.give_said = {'id': tid, 'field': r.get('field', ''), 'out': (r.get('out') or 'that was not sent').strip()}
        at = next((i for i, x in enumerate(self.give_ring(it)) if x[0] == 'field' and x[1]['key'] == r.get('field')), -1)
        if at >= 0:
            self.give_go(at)

    def give_key(self, k: str) -> bool:
        """A key on an item with inputs, nothing being typed; True when it was one of its own."""
        it = self.sel()
        if k in ('TAB', 'BTAB'):
            self.give_step(-1 if k == 'BTAB' else 1)
        elif k == '^S':
            self.give()
        elif k == 'ENTER':
            act, x = self.give_on(it)
            if act == 'field':
                self.give_go(self.give_ring(it).index((act, x)))
            elif act == 'open':
                self.open_link(it['detail']['step_more'][x]['link'], 'the step')
            else:
                r = copy_text(it['detail']['step_more'][x]['cmd'], self.out)
                self.msg, self.msg_ok = 'command copied', bool(r.get('ok'))
        else:
            return False
        return True

    def give_typed(self, k: str) -> None:
        """A key in an input's field. One line: Enter stays in it, so the rest of pasted words with a line end in them is
        no plain text in the next field (a secret's), no page key, and sends nothing."""
        it, box = self.sel(), self.typing
        boxes = [self.give_box(it, x) for x in self.give_inputs(it)] if self.giving() else []
        if k == 'ESC':
            self.typing = ''
        elif box not in boxes:  # the item went, or asks for something else now: no key typed on reaches the panels
            self.msg, self.msg_ok = 'what was asked for here changed or was answered: Esc leaves this field', False
        elif k == '^S':
            self.give()
        elif k in ('TAB', 'BTAB'):
            self.give_step(-1 if k == 'BTAB' else 1)
        elif k == 'ENTER':
            self.msg, self.msg_ok = 'one line: Tab goes on, ^S is Done', True
        elif k == 'BS':
            self.set_text(box, self.text_of(box)[:-1])
        elif k == '^U':
            self.set_text(box, '')
        elif len(k) == 1 and k.isprintable():
            self.set_text(box, self.text_of(box) + k)

    def give_forget(self) -> None:
        """A typed secret goes once its item is not the selected one, or no longer asks for it."""
        it = self.sel() if self.panel == 4 else None
        boxes = [self.give_box(it, x) for x in self.give_inputs(it)]
        self.secrets = {b: t for b, t in self.secrets.items() if b in boxes}

    def release_pane(self, width: int) -> list:
        L = lambda *segs: list(segs)  # noqa: E731
        rel = self.snap.get('release') or ''
        out = [L(('V ', 'magenta'), (l, 'fg' if rel else 'dim'))
               for l in (rel or 'no release is queued').splitlines()] + [L(),
               L(('A release waits for everything before it.', 'dim'))]
        running = [s for s in session_rows(self.snap) if s.get('task')]
        if running:
            out += [L(), L(('running now:', 'dim'))]
            out += [L(('  ', ''), (f'{s["task"]} ', 'cyan'), (s.get('title', ''), 'fg'), (f' in {s["name"]}', 'dim'))
                    for s in running]
        said = self.snap.get('release_said') or ''  # F186
        out += [L(), L(('New release', 'fg'), (f': {said}' if said else '', 'yellow')),
                buttons(*[button(c['tui'], c['label'].lower(), i == 0)
                          for i, c in enumerate(self.control_list('release'))])]
        if ts := self.droppable_releases():
            out += [L(), buttons(button('D', f'drop {ts[0]["id"]}' if len(ts) == 1 else 'drop one'))]
        if self.confirm in (*(c['key'] for c in self.control_list('release')), 'queue_drop'):
            c = next(c for c in U.RUN_CONTROLS if c['key'] == self.confirm)
            out += [L()] + text_lines(f'{self.confirm_ask} {c["tui"]} again: yes; any other key: no', 'red', width)
        return out

    def control_list(self, where: str) -> list[dict]:
        return [c for c in self.snap.get('controls') or U.controls() if c['where'] == where]

    def control_buttons(self, where: str) -> list:
        """F82: the run controls of `where` ('run', 'task') as button rows, from ui_model's one list."""
        cs = [c for c in self.snap.get('controls') or U.controls() if c['where'] == where]
        if where == 'task':
            return [buttons(*[button(c['tui'], c['label'].lower()) for c in cs])]
        fix = self.snap.get('fixups') or {}
        shown = U.controls_shown(bool(self.snap.get('up')), self.snap.get('run') or {}, fix)['shown']  # C33
        if self.run_start:  # F402c2: it is starting
            shown = [k for k in shown if k != 'start']
        rows = [[button(c['tui'], c['label'].lower() + (f' ({len(fix[c["fix"]])})' if c.get('fix') else ''))
                 for c in cs if c['key'] in g and c['key'] in shown] for g in U.CONTROL_ROWS]
        return [buttons(*r) for r in rows if r]

    def controls_pane(self, width: int) -> list:
        L = lambda *segs: list(segs)  # noqa: E731
        run = self.snap.get('run') or {}
        up = bool(self.snap.get('up'))
        said = ', '.join(w for k, w in (('paused', 'paused'), ('stopping', 'stopping')) if run.get(k)) or 'running'
        out = [L(('run ', 'dim'), (said, 'fg'), (f' · {self.snap.get("slots", 0)} slots', 'dim')), L()] if up else \
            text_lines(self.off_said(), 'red' if self.run_failed else 'fg', width) + \
            ([] if self.run_start else [L(('No task starts until the run does.', 'dim'))]) + [L()]
        for row in self.control_buttons('run'):
            out += [row, L()]
        if up:
            out.append(L(('A slot on a task: C cancels it, D drops it (Sessions [2]).', 'dim')))
        if self.output:
            out += [L()] + [L((l, 'fg')) for l in self.output]
        if self.confirm:
            c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == self.confirm), {})
            out += [L()] + text_lines(f'{c.get("confirm", "")} {c.get("tui", "")} again: yes; any other key: no',
                                      'red', width)
        return out

    @staticmethod
    def task_controls_on(it) -> bool:
        """A slot's task controls work while it works on a task, not while the task lands (merging)."""
        return U.task_controls_on(it)

    def control_by_tui(self, k: str, where: str) -> dict | None:
        k = '⏎' if k == 'ENTER' else k
        return next((c for c in self.snap.get('controls') or U.controls() if c['where'] == where
                     and (not c.get('tab') or (self.main and self.tab()[0] == c['tab']))  # F180: in its tab only
                     and ((c['tui'] == k and (not self.main or c.get('tui_main', True)))
                          or (c.get('tui_also') == k and not self.main)) and not c['needs'] == 'n'),
                    None)

    def row_controls(self, it, where: str = 'queue') -> list[dict]:
        """C34, C35: the actions of panel `where` allowed on row `it` now: its `acts` (else asked of ui_model)."""
        if not isinstance(it, dict) or it.get('new') or it.get('placeholder'):
            return []
        acts = it['acts'] if 'acts' in it else U.row_acts(where, it)
        labels = it.get('labels', {}) if 'acts' in it else U.row_labels(where, it)  # F180: a label that is the row's own
        said = {a['value']: a['label'] for a in it.get('answers') or U.need_answers(it)} if where == 'need' else {}
        # F181c: 'shown', an answer's button ('Full (recommended)'); its label is what is sent ('Full')
        return [dict(c, label=(l := labels.get(c['key'], c['label'])), shown=said.get(l, l)) for c in self.snap.get('controls') or U.controls()
                if c['key'] in acts and c['where'] == where
                and not (c.get('answer') and where == 'need' and self.give_inputs(it))]  # F175b: Done answers it

    def row_key(self, k: str, it) -> bool:
        """C34, C35: key `k` as one of row `it`'s actions, from ui_model's one list; True when it was one."""
        w = self.row_where(it)
        if not w or not self.row_id(it, w) or not (c := self.control_by_tui(k, w)):
            return False
        c = next((x for x in self.row_controls(it, w) if x['key'] == c['key']), None)
        if c is None:
            return False
        self.run_control(c['key'], tid=self.row_id(it, w), **({'text': c['label']} if c.get('answer') else {}))
        return True

    def row_where(self, it) -> str:
        """The `where` of the selected row's actions: its panel's, or 'shelved' for a shelved task in the queue (F184)."""
        return 'shelved' if self.panel == 3 and (it or {}).get('state') == 'shelved' else ROW_PANELS.get(self.panel, '')

    def row_id(self, it, where: str) -> str:
        """The id the actions of panel `where` take: a concept's, a control session's name, else the row's id."""
        return (it.get('concept') if where == 'concept' else it.get('name') if where == 'session' else '') \
            or self.tid(it)

    def run_control(self, key: str, **args) -> None:
        """F82: one run control by its key; one with a confirm question waits for its TUI key again."""
        c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == key), None)
        if c is None:
            return
        if not c.get('up', True) and self.snap.get('up'):
            self.msg, self.msg_ok = 'a run is up already', True
            return
        if key == 'start':
            self.start_run()
            return
        if c.get('fix') and not c.get('each') and not args.get('tid'):  # F124: which one of those to fix
            ids = [x['id'] for x in (self.snap.get('fixups') or {}).get(c['fix']) or []]
            if not ids:
                self.msg, self.msg_ok = f'{c["label"].lower()}: there is nothing to do', True
                return
            if len(ids) > 1:
                self.panel, self.main = 1, True
                self.set_tab('controls')
                self.typing = f'ctl:{key}'
                self.set_text(self.typing, ids[0])
                self.msg, self.msg_ok = f'{c["label"].lower()}: which one? {", ".join(ids)}', True
                return
            args['tid'] = ids[0]
        row = next((t for t in self.snap.get('queue') or [] if t.get('id') == args.get('tid')), {}) if c['where'] == 'queue' else {}
        asks = (row.get('asks') or {}).get(key, '')  # F186: the row's own confirm, asked here too
        if asks and key == 'queue_drop':
            asks = U.split_ask(row, short=True) or asks  # B811b
        if c['where'] == 'task' and (s := next((s for s in self.snap.get('sessions') or [] if s.get('task') == args.get('tid')), None)):
            asks = U.row_asks('task', s).get(key, '')  # F426d
        if c.get('confirm') and not c.get('tui_sure', True) and not asks:
            args['confirm'] = True  # the page asks; here the key is the answer
        if c.get('confirm') and not args.get('confirm'):
            self.confirm, self.confirm_id = key, args.get('tid', '')
            self.confirm_ask = asks or c['confirm'].replace('{id}', self.confirm_id)
            self.confirm_seen = c.get('seen', '')
            if c['where'] == 'run':
                self.panel, self.main = 1, True
                self.set_tab('controls')
            self.msg, self.msg_ok = f'{self.confirm_ask} {c["tui"]} again: yes', False
            return
        if c['where'] == 'queue':
            args.setdefault('why', 'dropped from agent-runner ui')
        r = self.quiet(U.run_control, key, **args) if c.get('fn') else U.run_control(key, **args)
        if c['where'] == 'release' and self.ask_again(key, r):
            return
        self.control_done(key, r)
        r = self.last_result
        if c['where'] in ('need', 'concept') and c.get('chat') and r.get('ok') and r.get('link'):  # F86
            self.msg = f'new control session about {args["tid"]}: {r["link"]}'
        elif c.get('chat'):
            self.say_new_session(r)
        if c['where'] in ('need', 'shelved') and (r.get('ok') or not c.get('answer')):  # B138: the item is off Needs you; the pane closes
            self.main = False
        if c['where'] == 'queue':  # C34: the selection follows its task, or leaves the pane when the task is gone
            ids = [t.get('id') for t in self.items(3)]
            if args['tid'] in ids:
                self.cur[3] = ids.index(args['tid'])
            else:
                self.main = False

    def ask_again(self, key: str, r: dict) -> bool:
        """F186: a New release refused because a release is open that the last snapshot did not show: ask."""
        if not r.get('seen'):
            return False
        self.refresh()
        self.confirm, self.confirm_ask, self.confirm_seen = key, r['confirm'], r['seen']
        c = next(c for c in U.RUN_CONTROLS if c['key'] == key)
        self.msg, self.msg_ok = f'{self.confirm_ask} {c["tui"]} again: yes', False
        return True

    def droppable_releases(self) -> list[dict]:
        """F186: the open releases that have not started: their Drop works."""
        return [t for t in self.items(3) if t.get('release')
                and any(c['key'] == 'queue_drop' for c in self.row_controls(t))]

    def drop_release(self) -> None:
        """F186 D in the release tab: drop the one that waits; with more, pick its row in the queue panel."""
        ts = self.droppable_releases()
        if not ts:
            self.msg, self.msg_ok = 'no release waits: one that has started cannot be dropped', True
        elif len(ts) == 1:
            self.run_control('queue_drop', tid=ts[0]['id'])
        else:
            self.panel, self.main = 3, False
            self.cur[3] = self.items(3).index(ts[0])
            self.msg, self.msg_ok = 'which release? d drops the selected one', True

    def control_done(self, key: str, r: dict) -> None:
        """A run control's result; what W shows (the files a moved-aside branch holds) stays in the controls pane."""
        self.last_result = r
        self.output = (r.get('out') or '').strip().splitlines() if key == 'wip_show' and r.get('ok') else []
        if self.output:
            self.panel, self.main = 1, True
            self.set_tab('controls')
        self.done(r)

    def session_pane(self, it, tab: str, width: int) -> tuple[list, list, object]:
        L = lambda *segs: list(segs)  # noqa: E731
        name = it.get('name', '')
        if it.get('starting'):  # F112: n started it; its row fills in from the run's state
            return [L((f'{it.get("label") or "a new control session"} is starting...', 'fg')), L(),
                    L(('Its row and link fill in once it is up.', 'dim'))], [], 0
        if it.get('new'):
            return [L(('Starts another control session (control --new) with its claude.ai/code link, so you can',
                       'fg')), L(('talk to it from the Claude app on your phone too.', 'fg')), L(),
                    buttons(button('n', 'start one', True))], [], 0
        if tab == 'diff':
            out = []
            for l in self.diff(name).splitlines()[:DIFF_LINES] or ['no changes yet']:
                colour = 'blue' if l.startswith(('diff --git', '+++', '---')) else 'green' if l.startswith('+') \
                    else 'red' if l.startswith('-') else 'cyan' if l.startswith('@@') else 'fg'
                out.append(L((l, colour)))
            return out, [], 0
        if not it.get('task') and not is_control(it):
            return [L((idle_line(it), 'dim'))], [], 0
        # F141: the session itself is in tmux's pane beside the TUI; with no pane beside (no socket to attach, or
        # its pane closed itself) this says so, with its link and buttons at the foot
        head = [L((f'{name} ', 'red' if is_control(it) else 'yellow'),
                  *([(f'{it["task"]} ', 'cyan')] if it.get('task') else []), (it.get('title', ''), 'fg'))]
        if self.task_controls_on(it):
            head += self.control_buttons('task')
        bs = [button('o', 'open it', True), button('y', 'copy link')]
        if self.socket(name):  # F88: it can be shown: its pane closed itself, or tmux could not split
            bs.append(button('⏎', 'show it beside'))
            said = f'{name} is not shown beside.'
        else:
            said = f'{name} has no terminal to show here; o opens its session link.'
        foot = [buttons(*bs), L(self.link(it['link'])) if it.get('link') else
                L(('no link yet: o asks for one (Remote Control)' if not is_control(it) else 'no link yet', 'dim'))]
        return head + [L(), L((said, 'dim'))], foot, 0

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
                   'pri': it['pri'] if not new and it.get('pri') in ('critical', 'high') else 'normal',
                   'files': '' if new else ','.join(it.get('files') or []),
                   'after': '' if new else ','.join(it.get('after') or []),
                   'needs': '' if new else ','.join(it.get('needs') or [])}
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
        kind = L(*label('k', 'kind', '(cycles, K back)'), ('  ', ''), (f['kind'], self.kind_colour(f['kind'] + '1')),
                 (f' {kind_name}' if kind_name and kind_name != f['kind'] else '', 'fg'))
        k_lines = wrap(kind, width)  # a narrow pane: the run-on indented under the value, never at column 0
        out += k_lines[:1] + [[('    ', '')] + l for k in k_lines[1:] for l in wrap(k, width - 4)]
        out += [L(*label('p', 'priority', '(cycles)'), ('  ', ''),
                  (f['pri'], {'critical': 'red', 'high': 'yellow'}.get(f['pri'], 'fg')))]
        out += [label('f', 'files')] + value('f')
        out += [label('a', 'after')] + value('a')
        out += [L(('    ', ''), (after_hint(f['after'], self.snap.get('queue') or []), 'dim')), L()]
        if names := self.snap.get('tool_names'):  # F168: only in a project with shared tools
            out[-1:] = [label('e', 'needs', f'({", ".join(names)})')] + value('e') + [L()]
        bs = [button('^S', 'save', True)] + ([] if f['new'] else (
            [button('D', 'drop')] if not it.get('started') else []) + [button('H', 'do it here')])
        return out + [buttons(*bs)]

    def preview_pane(self, it, width: int) -> tuple[list, int]:
        """A concept's K copy inline in the run page's style: its title, intro, and each option in a box with its
        heading in the top edge; the selected one yellow, the recommended one red."""
        L = lambda *segs: list(segs)  # noqa: E731
        page = self.concept(it)
        out = [L((page['title'] or it.get('title', ''), 'accent'))]
        if need := self.concept_need(it):  # F197b2: the answers its Needs you item gives, the same words
            said = [a['label'] for a in need.get('answers') or U.need_answers(need)]
            out.append(L(*self.news_badge(it), (need.get('label', ''), 'yellow'), (f'  {need.get("age", "")}', 'dim'),
                         *([('  answers: ', 'dim'), (' · '.join(said), 'fg')] if said else [])))
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
        if self.walk and not self.walk.off:  # F194c: the card takes rows: fewer rows in each, so every panel shows
            for n in (5, 2, 4, 3, 1):
                if n in hs:
                    hs[n] -= min(max(sum(hs.values()) + 3 - body, 0), hs[n] - 3)
        hs[self.panel] = max(3, body - sum(hs.values()))
        return hs

    def draw_panel(self, win, n: int, name: str, y: int, x: int, h: int, w: int) -> None:
        rows, focused = self.items(n), n == self.panel
        on = focused and not self.main
        cur = min(self.cur[n], max(len(rows) - 1, 0))
        n_sh = len(self.snap.get('shelved') or []) if n == 3 else 0  # F184: no part of the queue's count
        queued = len(rows) - n_sh
        count = f'{cur - queued + 1} of {n_sh} shelved' if n_sh and cur >= queued else \
            f'{cur + 1 if rows else 0} of {queued}'
        count += f' · {n} to expand' if not focused and len(rows) > SHORT else ''
        here = self.walk and not self.walk.off and W.PLACE[self.walk.at][0] == n  # F194c: the step points here
        self.edge(win, y, x, h, w, [(f' [{n}] {name} ', 'accent' if on else 'dim')] + ([('◂ ', 'yellow')] if here else []),
                  on, count)
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
            for k, segs in enumerate(lines[i]):
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
        if self.give_see and self.giving():  # F175b: Tab's place in view
            top, end = (sum(len(wrap(l, w - 4)) for l in body[:n]) for n in (self.give_row[0], self.give_row[1] + 1))
            off = self.off[self.place()] = min(max(off, end - inner), top)
        self.give_see = False
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

    # --- F194c: the example project's walkthrough ---------------------------------------------------------

    def walk_lines(self, width: int, room: int) -> list:
        """The walkthrough's card in `width` columns, only its title and keys when its words do not fit `room` rows;
        [] with none to show, or no room."""
        if not self.walk or self.walk.off:
            return []
        s, last, row = self.walk.step, self.walk.last, []
        if self.walk.i:
            row += button(W.BACK, 'back') + [(' ', '')]
        row += button(W.NEXT, 'done') if last else button(W.NEXT, 'next', True) + [(' ', '')] + button(W.SKIP, 'skip')
        up = bool(self.snap.get('up'))
        said = W.words(s, up, sum(bool(r.get('task')) for r in self.snap.get('sessions') or []),
                       len(self.snap.get('needs') or []), len(self.snap.get('lately') or []))
        head = [(s['title'], 'accent'), (f'  {self.walk.i + 1} of {len(self.walk.steps)}', 'dim')]
        lines = wrap(head, width) + wrap([(said, 'fg')], width) + wrap(row, width)
        short = wrap(head + [('  ', '')] + row, width)
        return lines if len(lines) <= room else short if len(short) <= room else []

    def draw_walk(self, win, y: int, w: int, lines: list) -> None:
        self._keys_on = not self.typing
        self.edge(win, y, 0, len(lines) + 2, w, [(' Walkthrough ', 'yellow')], False)
        for i, segs in enumerate(lines):
            self.put(win, y + 1 + i, 2, segs, w - 4)
        self._keys_on = False

    def walk_key(self, k: str) -> bool:
        """A key of the walkthrough; True when it was one. The step's panel is focused, its thing selected."""
        if not self.walk or not self.walk.press(k):
            return False
        if self.walk.off:
            self.msg, self.msg_ok = f'{W.SKIP} shows the walkthrough again', True
            return True
        n, tab = W.PLACE[self.walk.at]
        if not n:
            return True
        self.panel, self.main = n, False
        rows = self.items(n)
        want = {'session': lambda r: r.get('task'), 'chat': lambda r: r is NEW_CHAT}.get(self.walk.at)
        if want:
            self.cur[n] = next((i for i, r in enumerate(rows) if want(r)), self.cur[n])
        if tab in self.tab()[1]:
            self.tabs[self._tab_key(self.sel())] = tab
        return True

    def hint_keys(self) -> list[tuple[str, str]]:
        """F76: this place's keys for the bottom line, never one the window shows (a button, a label, a row's
        own key) and never j/k or Ctrl-h/Ctrl-l."""
        it, (tab, _) = self.sel(), self.tab()
        if self.typing:
            keys = [('Esc', 'leave')]
            if self.typing.startswith(('give:', 'givesec:')):
                return keys + [('Tab/⇧Tab', 'next'), ('^S', 'Done')]
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
            if self.giving():
                if self.give_sure:
                    return [('^S', 'yes, send it')]
                keys = [('⏎', 'open or type'), ('Tab/⇧Tab', 'next')] + keys
            if self.box():
                keys.append(('i', 'type'))
            if tab == 'session' and isinstance(it, dict) and not it.get('new'):
                keys.append(('^F', 'normal size' if self.full else 'full-screen'))
            keys.append(('Esc', 'back'))
            return keys
        if self.panel == 1 and not self.snap.get('up'):  # F402c2: no slot, pause or stop keys
            return [('⏎', 'open'), *([] if self.run_start else [('T', 'start')]),
                    *([('R', 'release')] if self.manage_releases() else [])]
        if self.panel == 1:
            return [('⏎', 'open'), *([('R', 'release')] if self.manage_releases() else []), ('+/-', 'slots'), ('P/G', 'pause, go on'), ('S', 'stop')]
        if self.panel == 2:
            keys = [('⏎', 'open'), ('t', 'busy slot')]
            if isinstance(it, dict) and (it.get('task') or is_control(it)):
                keys += [('o', 'open session'), ('y', 'copy link'),
                         ('^F', 'normal size' if self.full or self.side.full else 'full-screen')]
            if is_control(it):
                keys.append(('r', 'rename'))  # F129
            if isinstance(it, dict) and 'diff' in self.tab_list(2, it):
                keys.append(('g', 'session' if self.tab()[0] == 'diff' else 'diff'))
            if self.task_controls_on(it):
                keys += [('C', 'cancel'), ('d', 'drop')]
            keys += [(c['tui'], c['label'].lower()) for c in self.row_controls(it, 'session')]  # F116
            return keys
        if self.panel == 3:
            if isinstance(it, dict) and it.get('placeholder'):  # F131: the release tab's own keys
                return [('⏎', 'open'), ('R', 'new release')]
            if isinstance(it, dict) and it.get('new'):
                return [('⏎', 'open'), ('E', 'chat edit')]
            if (it or {}).get('state') == 'shelved':  # F184
                return [('⏎', 'open'), ('E', 'chat edit')] + [(c['tui_also'] or c['tui'], c['label'].lower())
                                                              for c in self.row_controls(it, 'shelved')]
            return [('e', 'edit'), ('E', 'chat edit')] + ([('J/K', 'reorder')] if (it or {}).get('state') != 'parked' else []) \
                + [(c['tui_also'] or c['tui'], c['label'].lower()) for c in self.row_controls(it)] \
                + ([('R', 'new release')] if (it or {}).get('release') else [])
        if self.panel == 4:
            return [('⏎', 'open'), ('a', 'answer')] + [(c['tui'], c['label'].lower())
                                                       for c in self.row_controls(it, 'need') if not c.get('tab')]
        if isinstance(it, dict) and it.get('new'):
            return [('⏎', 'type')]
        return [('⏎', 'view'), ('O', 'open in the browser'), ('n', 'new concept')] + \
            [(c['tui'], 'chat about it' if c.get('chat') else c['label'].lower()) for c in self.row_controls(it, 'concept')]

    GLOBAL = [('1-5', 'panel'), ('c', 'new chat'), ('?', 'keys')]

    def footer(self, width: int = 0) -> list[tuple[str, str]]:
        """The bottom line after the mode badge: this place's keys (yellow), a separator, then 1-5 panel, c new chat,
        ? keys (blue; none while typing, when they do not work); this place's last keys left out should `width`
        be too narrow. A message (an action's result) takes the line instead."""
        if self.typing.startswith('rename:'):  # F129: typed on this line, so a tmux pane beside hides nothing
            return [(f'name for {self.typing[7:]}: ', 'hkey'), (self.text_of(self.typing), 'fg'), ('█', 'accent'),
                    ('  ⏎ rename · Esc leave', 'dim')]
        if self.msg:
            return [(self.msg, 'green' if self.msg_ok else 'red')] + \
                ([(' ', ''), self.link(self.msg_link)] if self.msg_link else [])
        keys = [kv for kv in self.hint_keys() if kv[0] not in self.window_keys]
        every = self.GLOBAL + ([(W.SKIP, 'walkthrough')] if self.walk and self.walk.off else [])  # F194c
        glob = [] if self.typing else [kv for kv in every if kv[0] not in self.window_keys]  # a pick's c

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
        ago = int(time.time() - self.got)
        top = [(self.snap.get('project') or 'agent-runner', 'accent'), (' 0', 'gkey'), (' all runs  ', 'dim'),
               ('● ', 'green' if self.snap.get('up') else 'dim'),
               (('live' if self.snap.get('up') else 'no run is up') + f' · updated {"just now" if ago < 5 else f"{ago}s ago"}', 'dim')]
        if self.bar_only:  # F112 `ui --bar`: the top pane of tmux's full-screen layout
            self.put(win, 0, 0, top, w)
            return
        if self.side.full or h <= 2:  # F112: tmux's full-screen layout: this pane is the bottom bar only
            self.draw_bar(win, h, w)
            return
        if h < 8 or w < 24:
            self.put(win, 0, 0, [('too small', 'red')], w)
            return
        self.put(win, 0, 0, top, w)
        body = h - 2
        card = self.walk_lines(w - 4, body - 7)  # F194c: its border, and a panel of 5 rows
        body -= len(card) + 2 if card else 0
        if self.side.pane or self.full:  # F112: the session is in tmux's pane beside this one; Ctrl-f: no panels
            left, mx, mw = (0, 0, w) if self.full else (w, 0, 0)
        elif w >= TWO_COLUMNS:
            left = max(30, w * 36 // 100)
            mx, mw = left, w - left
        else:
            left, mx, mw = (0, 0, w) if self.main else (w, 0, 0)
        if left:
            y, hs = 1, self.heights(body)
            if card and sum(hs.values()) > body:  # F194c: no room for every panel: the focused one
                hs = {n: body if n == self.panel else 0 for n in hs}
            for n, name, _ in PANELS:
                hh = min(hs[n], 1 + body - y)
                if hh >= 2:
                    self.draw_panel(win, n, name, y, 0, hh, left)
                    self._keys_on = False
                y += hs[n]
        if mw:
            self.draw_main(win, 1, mx, body, mw)
        if card:
            self.draw_walk(win, 1 + body, w, card)
        if self.help:
            lines = help_text(self.manage_releases(), bool(self.walk)).splitlines()
            bw, bh = min(w - 2, max(len(l) for l in lines) + 4), min(h - 2, len(lines) + 2)
            by, bx = (h - bh) // 2, (w - bw) // 2
            for r in range(bh):
                self.put(win, by + r, bx, [(' ' * bw, '')], bw)
            self.edge(win, by, bx, bh, bw, [(' Keybindings ', 'accent')], True)
            for i, l in enumerate(lines[:bh - 2]):
                self.put(win, by + 1 + i, bx + 2, help_line(l), bw - 4)
        self.draw_bar(win, h, w)

    def draw_bar(self, win, h: int, w: int) -> None:
        """The bottom bar: the mode badge, then the footer (this place's keys, or a message)."""
        x = self.put(win, h - 1, 0, [(f' {self.mode()} ', '')], w, self.a('mode'))
        self.put(win, h - 1, x + 1, self.footer(w - x - 2), w - x - 2)

    # --- keys and actions ------------------------------------------------------------------------------

    def refresh(self) -> None:
        at = self.sel(4) if self.panel == 4 and self.give_inputs(self.sel(4)) else {}
        was_up, picked = bool(self.snap.get('up')), {n: self.row_name(self.sel(n)) for n in self.cur}
        try:
            self.snap = self.get_snap()
            self.got = time.time()
        except Exception as e:  # noqa: BLE001 - keep the last snapshot on screen, say why it is old
            self.msg, self.msg_ok = f'could not read the run: {e}', False
            return
        if bool(self.snap.get('up')) != was_up:
            self.keep_rows(picked)
        if self.snap.get('up'):
            self.run_failed = ''
        if at:  # F175b: the selection stays on the item whose fields are open
            self.cur[4] = next((i for i, n in enumerate(self.items(4)) if n.get('id') == at['id']), self.cur[4])
        self.give_forget()
        from agent_runner import __version__
        v = str(self.snap.get('version') or '')
        if newer_version(v, __version__) and v != self.followed and EXEC_RESTART and not self.secrets:  # F90; F175b: a typed secret is not handed on
            self.restart = True
        if self.side.pane and not self.side.alive():  # F112: detached or ended: its pane closed itself
            self.side.gone()

    # --- F402c2: the run starts from here ----------------------------------------------------------------------

    def off_row(self, it) -> bool:
        """Is `it` Status's row that says no run is up?"""
        return not self.snap.get('up') and str(it).startswith('no run')

    def off_said(self) -> str:
        """What the panel says while no run is up, in the Start card's words: Not running, Starting the run…, or Not
        started: why."""
        return 'Starting the run…' if self.run_start else f'Not started: {self.run_failed}' if self.run_failed else 'Not running'

    @staticmethod
    def row_name(it) -> str:
        """What a row is found by again after the run came up or stopped: its id or name, a status line's first word."""
        if isinstance(it, dict):
            return str(it.get('id') or it.get('name') or '')
        return 'run' if str(it or '').startswith('no run') else (str(it or '').split() or [''])[0]

    def keep_rows(self, picked: dict) -> None:
        """The run came up or stopped, so rows came and went: each panel's selection stays on the row it was on."""
        for n, name in picked.items():
            names = [self.row_name(it) for it in self.items(n)]
            if name in names and name and name not in names[self.cur[n]:self.cur[n] + 1]:
                self.cur[n] = names.index(name)

    def key_up(self, k: str) -> bool:
        """Can Status's key `k` work now? A run control's can while ui_model shows it, or while a run is up."""
        c = next((c for c in self.control_list('run') if c['tui'] == k), None)
        return bool(self.snap.get('up')) or not c or \
            c['key'] in U.controls_shown(False, self.snap.get('run') or {}, self.snap.get('fixups') or {})['shown'] or \
            bool(c.get('fix'))

    def start_run(self) -> None:
        """T: start the run on a thread, as the start takes seconds; `poll_run_start` says how it went. The view stays."""
        if self.run_start:
            self.msg, self.msg_ok = 'the run is starting already', True
            return
        st: dict = {}
        self.run_start, self.run_failed = st, ''

        def start() -> None:
            try:
                st['r'] = U.run_control('start')
            except Exception as e:  # noqa: BLE001 - said on the panel
                st['r'] = {'ok': False, 'out': str(e)}
        import threading
        st['thread'] = threading.Thread(target=start, daemon=True)
        st['thread'].start()
        self.msg, self.msg_ok = 'Starting the run…', True

    def poll_run_start(self) -> None:
        """The starting run's progress: a failure's reason goes on the panel; it has started once the snapshot says up."""
        st = self.run_start
        r = st.get('r') if st else None
        if st is None or (r is None and not self.snap.get('up')):
            return
        if r and 'until' not in st:
            st['until'] = time.time() + RUN_START_WAIT
            self.refresh()
        if self.snap.get('up'):
            self.run_start = None
            self.msg, self.msg_ok = 'the run is up', True
        elif not r['ok']:
            self.run_start = None
            self.run_failed = (r.get('out') or '').strip() or 'it did not work'
            self.msg, self.msg_ok = f'Not started: {self.run_failed.splitlines()[0]}', False
        elif time.time() > st['until']:
            self.run_start, self.run_failed = None, 'it started, but no run is up: the log says why'
            self.msg, self.msg_ok = f'Not started: {self.run_failed}', False

    # --- F112: the session beside the TUI, a new chat on its way up -------------------------------------------

    def want_side(self) -> str:
        """The session to show in tmux's pane beside the TUI ('' none): the selected Sessions row on its session
        tab, when it has a socket to attach to (F88). F141: `main` runs no TUI outside tmux."""
        if self.bar_only or not in_tmux() or self.panel != 2:
            return ''
        it = self.sel()
        if not isinstance(it, dict) or it.get('new') or not (is_control(it) or it.get('task')):
            return ''
        if self.tab()[0] != 'session':
            return ''
        return it['name'] if self.socket(it['name']) else ''

    def sync(self) -> None:
        """The tmux pane beside follows the selection: `attach NAME` split off beside the TUI's pane (respawned on
        another session), killed on any other row; focus on the right side (l, Enter, Ctrl-l) moves into it. A
        pane that closed itself (Ctrl-b d, the session ended) stays closed until another row is selected."""
        if not self.main:
            self.full = False
        name = self.want_side()
        if name != self.side.closed:
            self.side.closed = ''
        if not name or self.side.closed:
            if self.side.pane:
                self.side.close()
            return
        r = self.side.show(name)
        if not r.get('ok'):
            self.msg, self.msg_ok = r.get('out', f'could not show {name}'), False
            return
        if self.main:
            self.side.focus()
            self.main = False

    def toggle_full(self) -> None:
        """Ctrl-f: the session full-screen between the top and bottom bars, the panels gone; again: side by side.
        The panes are laid out again (`SidePane.toggle_full`); with none beside, the main pane takes the width."""
        if self.side.pane:
            r = self.side.toggle_full()
            if not r.get('ok'):
                self.msg, self.msg_ok = r.get('out', 'could not lay the panes out again'), False
            return
        if self.full:
            self.full = False
            return
        if self.panel == 2 and isinstance(self.sel(), dict) and not self.sel().get('new'):
            self.full = self.main = True
        else:
            self.msg, self.msg_ok = 'Ctrl-f full-screens a session: select one in Sessions [2]', True

    def new_chat(self) -> None:
        """n: a new control session (`new_control`, not waiting for its link), started on a thread so the page
        never waits: a 'starting...' row is selected at once, and `poll_new_chat` puts the session's own row in
        its place once the run's state lists it."""
        if self.starting:
            self.msg, self.msg_ok = 'a new chat is starting already', True
            return
        st: dict = {'name': '', 'label': '', 'title': 'starting...', 'new': True, 'starting': True, 'on': True,
                    'before': {r.get('name') for r in session_rows(self.snap)}, 't': time.time()}
        self.starting = st

        def start() -> None:
            try:
                st['r'] = U.new_control(wait=False)
            except Exception as e:  # noqa: BLE001 - said on the bottom line
                st['r'] = {'ok': False, 'out': f'could not start a new chat: {e}'}
        import threading
        threading.Thread(target=start, daemon=True).start()
        self.panel, self.main = 2, False
        self.cur[2] = next(i for i, r in enumerate(self.items(2)) if r is st)
        self.msg, self.msg_ok = 'starting a new chat...', True

    def say_new_session(self, r: dict) -> None:
        """C32: after a quick ask or H started a new control session: say its name (the result's 'name') and,
        when the run's state lists it, select it in Sessions as n does."""
        name = r.get('name') if r.get('ok') else ''
        if not name:
            return
        self.msg = f'{self.msg}: {name} answers in its session'
        self.refresh()
        rows = self.items(2)
        at = next((i for i, s in enumerate(rows) if s.get('name') == name), None)
        if at is not None:
            self.panel, self.cur[2], self.main = 2, at, False
            self.msg = f'{self.msg} (selected)'

    def poll_new_chat(self) -> None:
        """The new chat's progress: a start that failed says why and its row goes; once its cN is in the run's
        state, that row takes the 'starting...' row's place (selected, when that one was)."""
        st = self.starting
        if not st:
            return
        r = st.get('r')
        if r is not None and not r.get('ok'):
            self.starting = None
            self.cur[2] = min(self.cur[2], max(len(self.items(2)) - 1, 0))
            out = (r.get('out') or '').strip().splitlines()
            self.msg, self.msg_ok = out[0] if out else 'the new chat could not start', False
            return
        if r is not None and r.get('name') and not st['label']:
            st['label'] = r['name']
            self.refresh()
        fresh = [s for s in session_rows(self.snap) if is_control(s) and s.get('name') not in st['before']
                 and (not st['label'] or s.get('name') == st['label'])]
        if fresh:
            self.starting = None
            row = fresh[-1]
            if st['on']:
                rows = self.items(2)
                self.panel, self.cur[2] = 2, next(i for i, s in enumerate(rows) if s.get('name') == row['name'])
            link = row.get('link') or (r or {}).get('link', '')
            self.msg, self.msg_ok = f'new control session {row["name"]}' + (f': {link}' if link else ''), True
        elif r is not None and time.time() - st['t'] > STARTING_WAIT:
            self.starting = None
            self.msg, self.msg_ok = f'{st["label"] or "the new chat"} started but is not listed: see its row later', False
        elif st['on']:  # the selection stays on it while rows above come and go
            self.cur[2] = next(i for i, s in enumerate(self.items(2)) if s is st)

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
        if r.get('ok') and r.get('said'):  # B138: an answer's own words ('R13 ticked')
            self.msg = r['said']
        self.cache = {k: v for k, v in self.cache.items() if k.startswith('copy:')}  # diffs read anew
        self.refresh()
        if r.get('ok') and r.get('gone') and isinstance(self.snap.get('needs'), list):  # B138: off Needs you at once
            self.snap = {**self.snap, 'needs': [n for n in self.snap['needs'] if n.get('id') != r['gone']]}

    def key(self, k: str) -> bool:
        """Handle one key (a character, or a name: UP DOWN LEFT RIGHT ENTER S-ENTER ESC TAB BTAB BS ^S ^H ^L
        ^J ^K ^C ^U ^F); True means quit. F112: then the tmux pane beside follows the selection (`sync`)."""
        quit_ = self.take_key(k)
        if self.starting:
            self.starting['on'] = self.panel == 2 and self.sel() is self.starting
        self.poll_new_chat()
        self.poll_run_start()
        self.give_forget()
        self.sync()
        return quit_

    def take_key(self, k: str) -> bool:
        k = KEYS.get(k, k)
        self.msg, self.msg_link = '', ''
        if self.help:
            self.help = k not in ('ESC', '?', 'q', 'ENTER')
            return False
        if k == '^C':  # F112: no chat to interrupt here any more (the session itself takes its Ctrl+C)
            return True
        if self.give_sure:  # F175b: Done's question: its key again, on what was asked about
            (tid, asked), self.give_sure = self.give_sure, ()
            it = self.sel() if self.giving() else {}
            if k != '^S' or it.get('id') != tid:
                self.msg, self.msg_ok = f'{tid}: not sent', True
            else:
                self.give(confirm=asked == ' '.join(x['confirm'] for x in self.give_inputs(it) if x['confirm']))
            return False
        if k == '^F':  # F112: the session full-screen between the bars, and back
            self.toggle_full()
            return False
        if self.confirm:  # F82: stop now runs only on its key again
            key, self.confirm = self.confirm, ''
            tid, self.confirm_id = self.confirm_id, ''
            seen, self.confirm_seen = self.confirm_seen, ''
            self.confirm_ask = ''
            c = next((c for c in self.snap.get('controls') or U.controls() if c['key'] == key), {})
            if ('⏎' if k == 'ENTER' else k) in (c.get('tui'), c.get('tui_also')):
                more = {'why': 'dropped from agent-runner ui'} if c.get('where') == 'queue' else {}
                r = U.run_control(key, confirm=True, **({'tid': tid} if tid else {}), **({'text': seen} if seen else {}), **more)
                if not self.ask_again(key, r):
                    self.control_done(key, r)
                    if more and self.panel == 3 and tid not in [t.get('id') for t in self.items(3)]:
                        self.main = False
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
        if k == '0':  # B153: the project name's key: back to the pick-a-run screen
            self.pick = True
            return True
        if self.walk_key(k):
            return False
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
        if box.startswith(('give:', 'givesec:')):
            self.give_typed(k)
            return
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
        if kind == 'edit':
            r = U.chat(f'new task: {text}' if rest == '+' else f'change {rest}: {text}')
        elif kind == 'answer':
            r = U.answer(rest, text)
        elif box == 'slots:n':
            r = U.run_control('slots_set', n=text)
        elif kind == 'ctl':  # F124: the one a Fix up control works on
            self.typing = ''
            self.set_text(box, '')
            self.run_control(rest, tid=text)
            return
        elif kind == 'rename':  # F129
            r = U.rename_chat(rest, text)
        elif box == 'concept:+':  # F87: a new concept, queued as a K task
            r = U.plan_add('K', text)
        elif kind == 'concept':
            it = next((c for c in self.snap.get('concepts') or [] if c.get('id') == rest), {'id': rest})
            r = U.chat(f'concept {it.get("concept") or rest} ("{it.get("title", "")}"): {text}')
        else:
            return
        if r.get('ok'):
            self.set_text(box, '')
            self.typing = ''
            if kind in ('edit', 'answer'):
                self.main = False
        self.done(r)

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
            if k in ('t', 'f', 'a') or k == 'e' and self.snap.get('tool_names'):
                self.field(k)
            elif k == 'p':
                f['pri'], f['field'] = U.P.next_pri(f['pri']), 'p'
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
            if self.giving() and self.give_key(k):
                return True
            if self.row_key(k, it):  # F180: before the panels' keys, so c picks the third option
                return True
            if k == 'ENTER':
                self.type_in()
                return True
            return False
        if tab == 'release' and k in ('D', 'd'):  # F186
            self.drop_release()
            return True
        if tab == 'release' and (c := self.control_by_tui(k, 'release')):
            self.run_control(c['key'])
            return True
        if tab == 'session' and k == 'ENTER':  # its pane closed itself: beside again (`sync`); no socket: its link
            if self.want_side():
                self.side.closed = ''
            else:
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
        fs = FIELDS if self.snap.get('tool_names') else FIELDS[:-1]
        i = fs.index(f['field']) if f['field'] in fs else (-1 if step > 0 else 0)
        self.field(fs[(i + step) % len(fs)])

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
                           '' if f['pri'] == 'normal' else f['pri'],
                           **({'needs': f['needs'].strip()} if f['needs'].strip() else {}))
        else:
            was = f['was']
            if f['kind'] != was['kind']:
                self.msg, self.msg_ok = f'{it["id"]} keeps its kind: a new kind is a new task (n)', False
                return
            changed = {k: f[k].strip() for k in ('text', 'files', 'after', 'pri', 'needs') if f[k].strip() != was[k].strip()
                       and f[k].strip()}
            emptied = [k for k in ('files', 'after', 'needs') if was[k].strip() and not f[k].strip()]
            if emptied:  # plan edit sets a field, never clears one
                self.msg, self.msg_ok = f'{" and ".join(emptied)} cannot be emptied here: give the new value', False
                return
            if not changed:
                self.msg, self.msg_ok = 'nothing changed', True
                return
            r = U.plan_change(it['id'], changed.get('text', ''), changed.get('files'), changed.get('after'),
                              changed.get('pri', ''), **({'needs': changed['needs']} if 'needs' in changed else {}))
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
            self.new_chat()
        elif k == 'i':
            self.main = True
            self.type_in()
        elif self.panel in (1, 3) and k == 'R' and self.manage_releases():  # F186: the Queue too, where the releases are listed
            self.panel = 1
            self.release_tab()
        elif self.panel == 1 and (q := next((q for q, c in QUICK_KEYS.items() if c == k), '')):
            self.done(r := U.quick_ask(q))  # B139: a new control session answers
            self.say_new_session(r)
        elif self.panel == 1 and not self.key_up(k):  # F402c2: what needs a run, with none up
            self.msg, self.msg_ok = 'Not running: T starts the run', True
        elif self.panel == 1 and k == '=':
            self.set_tab('controls')
            self.typing = 'slots:n'
        elif self.panel == 1 and (c := self.control_by_tui(k, 'run')):
            self.run_control(c['key'])
        elif self.panel == 2 and self.task_controls_on(it) and (c := self.control_by_tui(k, 'task')):
            self.run_control(c['key'], tid=it['task'])
        elif self.panel == 2 and k == 'r' and is_control(it):  # F129
            self.typing = f'rename:{it["name"]}'
            self.set_text(self.typing, it.get('title', '') if it.get('renamed') else '')
        elif self.panel == 2 and k == 't':
            self.busy_slot()
        elif self.panel == 2 and k == 'g':
            self.diff_toggle()
        elif self.panel == 2 and k == 'n':
            self.new_chat()
        elif self.panel == 2 and k == 'o' and isinstance(it, dict) and not it.get('new'):
            self.open_session(it)
        elif self.panel == 2 and k == 'y' and isinstance(it, dict) and not it.get('new'):
            self.copy_session(it)
        elif self.panel == 3 and k == 'n':
            self.cur[3] = rows.index(NEW_TASK)
            self.set_tab('chat edit')
            self.type_in()
        elif self.panel == 3 and k == 'e' and it is not None and not it.get('placeholder') and it.get('state') != 'shelved':
            self.set_tab('direct edit')
            self.field('t')
        elif self.panel == 3 and k == 'E' and it is not None and not it.get('placeholder'):
            self.set_tab('chat edit')
            self.type_in()
        elif self.row_key(k, it):  # C34, C35: a row's actions, from ui_model's one list
            pass
        elif self.panel == 3 and k in ('J', 'K') and tid and it.get('state') not in ('parked', 'shelved'):
            self.reorder(1 if k == 'J' else -1)
        elif k == '^S' and self.giving():  # F175b: Done is drawn with the panel focused too
            self.main = True
            self.give()
        elif self.panel == 4 and k == 'a' and it is not None:
            self.set_tab('answer')
        elif self.panel == 5 and k == 'n':  # F87: a new concept, in its row's box
            self.cur[5] = len(rows) - 1
            self.set_tab('new concept')
            self.type_in()
        elif self.panel == 5 and k == 'O' and it is not None and not it.get('new'):
            url = it.get('url', '')
            if not url and it.get('copy'):  # F406e: no claude.ai page, so its local copy
                url = Path(it['copy']).as_uri()
            self.open_link(url, it.get('title', 'the concept'))

    def quiet(self, fn, *args, **kw):
        """B136: run an in-process action with its stdout and stderr swallowed (its run-log lines still go to
        run.log), so nothing prints over the curses screen; the next frame repaints every cell."""
        import contextlib
        import io
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return fn(*args, **kw)
        finally:
            self.repaint = True

    def diff_toggle(self) -> None:
        """F127 g: a slot's diff in place of its session, and back. The session pane beside goes while
        the diff shows (`sync` follows the tab) and comes back with the session tab; focus stays on the TUI."""
        it = self.sel()
        tab, ts = self.tab()
        if 'diff' not in ts:
            self.msg, self.msg_ok = 'g shows a slot\'s diff: select a slot on a task', True
            return
        self.tabs[self._tab_key(it)] = 'session' if tab == 'diff' else 'diff'
        self.main = False  # the panels keep focus (not moved into the pane that comes back)

    def release_tab(self) -> None:
        rows = self.items(1)
        self.cur[1] = next((i for i, r in enumerate(rows) if str(r).startswith('release')), self.cur[1])
        self.set_tab('release')

    def busy_slot(self) -> None:
        """t: the selected slot's session; from a control session or the new chat row, the first slot on a task."""
        it = self.sel()
        if not (isinstance(it, dict) and it.get('task')):
            rows = self.items(2)
            busy = [i for i, s in enumerate(rows) if s.get('task')]
            if not busy:
                self.msg, self.msg_ok = self.snap.get('sessions_note') or 'no slot is on a task', True
                return
            self.cur[2] = busy[0]
        self.panel = 2
        self.set_tab('session')

    def reorder(self, step: int) -> None:
        """F70: Shift+J / Shift+K: the selected queued task one place down / up (`plan move ID after|before
        <neighbour>`); the selection follows it."""
        if self.sel(3).get('release'):  # F131
            self.msg, self.msg_ok = f'{self.sel(3)["id"]} is a release: it stays at its place', True
            return
        tasks = [t for t in self.items(3) if not t.get('new') and t.get('state') != 'shelved']
        i = next(j for j, t in enumerate(tasks) if t['id'] == self.sel(3)['id'])
        if not 0 <= i + step < len(tasks):
            self.msg, self.msg_ok = f'{tasks[i]["id"]} is already {"last" if step > 0 else "first"}', True
            return
        if tasks[i + step].get('release'):  # it would no longer wait for the task, or wait for one it did not
            self.msg, self.msg_ok = f'{tasks[i]["id"]} does not move past the release {tasks[i + step]["id"]}', True
            return
        r = U.move(tasks[i]['id'], 'after' if step > 0 else 'before', tasks[i + step]['id'])
        self.done(r)
        if r.get('ok'):  # the task's row in the queue read again, else the row it moved to
            ids = [t.get('id') for t in self.items(3)]
            self.cur[3] = ids.index(tasks[i]['id']) if tasks[i]['id'] in ids else self.cur[3] + step

    def open_link(self, url: str, what: str) -> None:
        if not url:
            self.msg, self.msg_ok = f'{what} has no link yet', False
            return
        r = self.opener(url)
        self.msg, self.msg_ok = (r.get('out') or f'opened {url}'), bool(r.get('ok'))
        self.msg_link = r.get('link', '')  # B125: over ssh, the link to Cmd-click on the message line

    def session_link(self, it) -> str:
        """The session's claude.ai/code link ('' none, the reason on the message line); a slot is opened first
        (`open_session`: under `[run] remote_slots = 'open'` it is listed there only once asked for)."""
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


TITLE_BACK = '\x1b[23;0t'  # B153: the terminal's window title as it was (the title stack's top, popped)
PICKER_ENV = 'AGENT_RUNNER_FROM_PICKER'  # B153: set by the launcher's t: 0 in the TUI goes back to its picker
PICK_RC = 3  # B153: the TUI's exit code for 0 (back to the pick-a-run screen) when the launcher started it


def window_title(name: str) -> str:
    """B153: the escapes that keep the terminal's window title (pushed on its title stack, `TITLE_BACK` gives
    it back) and show `name` in its place (OSC 0 and 2: the window and the tab)."""
    clean = re.sub(r'[\x00-\x1f\x7f]', '', name)
    return f'\x1b[22;0t\x1b]0;{clean}\x07\x1b]2;{clean}\x07'


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
                'mode': curses.A_REVERSE, 'kindv': curses.A_REVERSE, 'key': curses.A_BOLD, 'hkey': curses.A_BOLD | curses.A_REVERSE,
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
    curses.init_pair(n + 3, bg if bg != -1 else 0, col('magenta'))  # F195b: a release's chip, on every row background
    out['kindv'] = out['sel:kindv'] = out['cur:kindv'] = curses.color_pair(n + 3) | curses.A_BOLD
    n += 4
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


def hidden_terminal(name: str) -> bool:
    """F88: `name` (sN, cN) runs hidden with a terminal to attach to (its shim's socket is up; not Windows)."""
    try:
        from agent_runner.attach import session_socket
        return bool(session_socket(name))
    except Exception:  # noqa: BLE001 - no notes dir (no repo set up): nothing to attach
        return False


def in_tmux() -> bool:
    """F112: this TUI runs inside tmux (TMUX set), so a session can be shown in a tmux pane beside it."""
    return bool(os.environ.get('TMUX'))


def tmux_run(argv: list[str]) -> tuple[int, str]:
    """One tmux command (the TUI's own tmux server, from TMUX): (exit code, its output)."""
    try:
        r = sp.run(['tmux', *argv], capture_output=True, text=True, timeout=10)
    except (OSError, sp.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout or r.stderr or '').strip()


NO_WINDOWS = 'the terminal UI does not run on Windows: use the run page'
NO_TMUX = ('the terminal UI runs in tmux, which is not installed: '
           'sudo pacman -S tmux / sudo apt install tmux / brew install tmux')


def refusal() -> str:
    """F141: why the TUI does not start on this machine ('' when it can)."""
    import shutil
    if plat.WINDOWS:
        return NO_WINDOWS
    return '' if shutil.which('tmux') else NO_TMUX


def tmux_session() -> str:
    """F141: the project's tmux session name (tmux takes no '.' or ':' in one)."""
    return re.sub(r'[.:]', '_', U.S.project()) or 'agent-runner'


def tmux_start(run=None, exec_=None) -> None:
    """F141: this TUI again inside tmux (an exec): in a new session named for the project, or in a new window of
    that session when it is up. The runner's own variables go along, since a tmux server that is up keeps its
    own environment; not PICKER_ENV: tmux gives no exit code back, so 0 there opens the pick-a-run screen. A
    server this starts keeps the exec's environment for every later window, so PLACE_ENV is not in it."""
    name, root = tmux_session(), str(U.S.ROOT)
    own = [f'{k}={v}' for k, v in sorted(os.environ.items()) if k.startswith('AGENT_RUNNER_') and k != PICKER_ENV]
    env = {k: v for k, v in os.environ.items() if k not in (PICKER_ENV, PLACE_ENV)}
    cmd = [*(['env', *own] if own else []), *U.runner_cmd(), 'ui']
    if (run or tmux_run)(['has-session', '-t', f'={name}'])[0] == 0:
        argv = ['new-window', '-t', f'={name}:', '-c', root, *cmd, ';', 'attach-session', '-t', f'={name}']
    else:
        argv = ['new-session', '-A', '-s', name, '-c', root, *cmd]
    sys.stdout.flush()
    (exec_ or os.execvpe)('tmux', ['tmux', *argv], env)


def runner_line(*args: str) -> str:
    """`agent-runner ARGS` as one shell command line (what a tmux pane runs)."""
    import shlex
    return shlex.join([*U.runner_cmd(), *args])


class SidePane:
    """F112: inside tmux, the selected session in a tmux pane of its own beside the TUI's pane, running
    `agent-runner attach NAME` (F88's socket), so tmux keeps mouse selection and copy inside it. Ctrl-f lays the
    panes out again: the session between a one-row top bar pane (`ui --bar`) and the TUI's pane cut down to its
    bottom bar. In the TUI's window, Ctrl-h in the session pane goes back to the TUI and Ctrl-f reaches the TUI
    from either pane (root-table bindings that act only where the window options this sets say so, made only
    when the person has no binding of their own on those keys). `run` runs one tmux command: (code, output)."""

    WIN_TUI = '@agent_runner_tui'  # window option: the TUI's pane id
    WIN_SIDE = '@agent_runner_side'  # window option: the session pane's id

    def __init__(self, run=None):
        self.run = run or tmux_run
        self.pane = ''  # the session pane's id ('' none)
        self.name = ''  # the session it attaches
        self.bar = ''  # full-screen: the top bar pane's id
        self.full = False
        self.closed = ''  # a session whose pane closed itself: not opened again until another row
        self.bound: list[str] = []  # the root-table keys this bound (and unbinds on close)

    @staticmethod
    def me() -> str:
        return os.environ.get('TMUX_PANE', '')

    def tmux(self, *argv: str) -> tuple[int, str]:
        try:
            return self.run(list(argv))
        except Exception as e:  # noqa: BLE001 - a broken tmux says why on the bottom line
            return 1, str(e)

    def show(self, name: str) -> dict:
        """`attach NAME` in the session pane: split off beside the TUI's pane, or respawned in it."""
        if self.pane and name == self.name:
            return {'ok': True}
        cmd, root = runner_line('attach', name), str(U.S.ROOT)
        if self.pane:
            code, out = self.tmux('respawn-pane', '-k', '-t', self.pane, '-c', root, cmd)
        else:
            code, out = self.tmux('split-window', '-d', '-h', '-l', SIDE_SHARE, '-t', self.me(), '-c', root,
                                  '-P', '-F', '#{pane_id}', cmd)
            if not code:
                self.pane = out.strip().splitlines()[-1] if out.strip() else ''
        if code or not self.pane:  # a respawn that failed: the pane is gone; the next show splits a new one
            self.pane = self.name = ''
            return {'ok': False, 'out': f'could not show {name} beside: {out or "tmux said nothing"}'}
        self.name = name
        self.bind()
        return {'ok': True}

    def focus(self) -> None:
        if self.pane:
            self.tmux('select-pane', '-t', self.pane)

    def alive(self) -> bool:
        return bool(self.pane) and self.tmux('display-message', '-p', '-t', self.pane, '#{pane_id}')[0] == 0

    def toggle_full(self) -> dict:
        """Full-screen: the session pane joined above the TUI's pane, a top bar pane split above it, the TUI's pane
        cut to one row (its bottom bar), focus in the session. Again: the bar killed, the session pane joined back
        beside the TUI's pane, focus in the TUI."""
        if not self.pane:
            return {'ok': False, 'out': 'no session is shown beside'}
        me = self.me()
        if self.full:
            if self.bar:
                self.tmux('kill-pane', '-t', self.bar)
            self.bar, self.full = '', False
            code, out = self.tmux('join-pane', '-d', '-h', '-l', SIDE_SHARE, '-s', self.pane, '-t', me)
            self.tmux('select-pane', '-t', me)
            return {'ok': not code, 'out': out}
        code, out = self.tmux('join-pane', '-d', '-v', '-b', '-s', self.pane, '-t', me)
        if code:
            return {'ok': False, 'out': f'could not lay the panes out again: {out}'}
        code, out = self.tmux('split-window', '-d', '-v', '-b', '-l', '1', '-t', self.pane, '-c', str(U.S.ROOT),
                              '-P', '-F', '#{pane_id}', runner_line('ui', '--bar'))
        self.bar = out.strip().splitlines()[-1] if not code and out.strip() else ''
        self.tmux('resize-pane', '-t', me, '-y', '1')
        self.tmux('select-pane', '-t', self.pane)
        self.full = True
        return {'ok': True}

    def bind(self) -> None:
        """The window options naming both panes, and once: Ctrl-f (both panes: to the TUI) and Ctrl-h (the session
        pane: back to the TUI), each only in a window with those options and left alone when already bound."""
        me = self.me()
        self.tmux('set-option', '-w', '-t', me, self.WIN_TUI, me)
        self.tmux('set-option', '-w', '-t', me, self.WIN_SIDE, self.pane)
        keys = {'C-f': (f'#{{{self.WIN_TUI}}}', f'run-shell -C "send-keys -t #{{{self.WIN_TUI}}} C-f"'),
                'C-h': (f'#{{==:#{{pane_id}},#{{{self.WIN_SIDE}}}}}', f'run-shell -C "select-pane -t #{{{self.WIN_TUI}}}"')}
        for key, (cond, then) in keys.items():
            if key in self.bound:
                continue
            code, out = self.tmux('list-keys', '-T', 'root', key)
            if not code and self.WIN_TUI in out:  # another TUI's, the same window-gated binding: shared
                self.bound.append(key)
                continue
            if not code and out.strip():  # the person's own binding: kept (prefix arrows still move)
                continue
            if not self.tmux('bind-key', '-n', key, 'if-shell', '-F', cond, then, f'send-keys {key}')[0]:
                self.bound.append(key)

    def unbind(self) -> None:
        """This window's options unset; the bindings undone unless another TUI's window still uses them."""
        me = self.me()
        for opt in (self.WIN_TUI, self.WIN_SIDE):
            self.tmux('set-option', '-w', '-u', '-t', me, opt)
        code, out = self.tmux('list-windows', '-a', '-F', f'#{{{self.WIN_TUI}}}')
        if not code and out.strip():  # another TUI shows a session: its window still needs them
            self.bound = []
            return
        for key in self.bound:
            self.tmux('unbind-key', '-n', key)
        self.bound = []

    def close(self) -> None:
        """The session pane (and the top bar pane) killed, the bindings undone: the TUI's pane alone again."""
        for p in (self.bar, self.pane):
            if p:
                self.tmux('kill-pane', '-t', p)
        self.bar = ''
        self.gone(itself=False)

    def gone(self, itself: bool = True) -> None:
        """The session pane is no more: killed by `close`, or closed `itself` (Ctrl-b d, the session ended), when
        it is not opened again until another row is selected (`closed`)."""
        if self.bar:
            self.tmux('kill-pane', '-t', self.bar)
        if itself and self.pane:
            self.closed = self.name
        self.pane = self.name = self.bar = ''
        self.full = False
        self.unbind()


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


def run_curses(win, box: dict | None = None, bar: bool = False) -> int:
    """The Run page's loop; F90: on a newer run it returns with the page in `box['restart']` (curses.wrapper
    then restores the terminal, and `main` starts the TUI again). F112: the session pane beside is closed when
    it ends; `bar` (`ui --bar`) draws only the top bar and takes no keys."""
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
    page = RunPage(U.snapshot(), attrs=attrs, walk=None if bar else W.of(U.S.ROOT, U.S.C.notes()))
    page.bar_only = bar
    if not bar:
        page.restore_place(taken_place())
    try:
        return page_loop(curses, win, page, box)
    finally:
        if page.side.pane:  # F112: the session pane goes with the TUI (its session keeps running)
            page.side.close()


def page_loop(curses, win, page: RunPage, box: dict | None) -> int:
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
            if not page.bar_only:
                page.sync()  # F112: the selected row may have gone, or its pane closed itself
        page.poll_run_start()
        if page.starting:
            page.poll_new_chat()
            page.sync()
        if page.restart and box is not None and not page.bar_only:
            box['restart'] = page
            return 0
        if page.repaint:  # B136: an in-process action may have printed; repaint every cell
            page.repaint = False
            win.clear()
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
        if page.bar_only:
            continue
        for name in escape_tail(key_name(curses, ch), more):
            if page.key(name):
                if page.pick and box is not None:
                    box['pick'] = True
                return 0


def main(argv: list[str]) -> int:
    """`agent-runner ui`: the Run page in this terminal."""
    if argv and argv[0] in ('-h', '--help'):
        print('agent-runner ui: the Run page in this terminal (the same panels, keys and actions as the web '
              'page). ? lists the keys, q quits.')
        return 0
    bar = argv == ['--bar']  # F112: the top bar alone (tmux's full-screen layout runs it in a one-row pane)
    if argv and not bar:
        print(f'agent-runner ui takes nothing more (got {" ".join(argv)})', file=sys.stderr)
        return 2
    if why := refusal():  # F141: no fallback
        if plat.WINDOWS:
            from agent_runner.state import init
            from agent_runner.web import page_line
            init()
            why = f'{why}\n{page_line() or "no run page yet: start the run first"}'
        print(why, file=sys.stderr)
        return 2
    try:
        import curses
    except ImportError:
        print('agent-runner ui needs curses, which this Python lacks', file=sys.stderr)
        return 2
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print('agent-runner ui needs a terminal; agent-runner status prints the same run as text', file=sys.stderr)
        return 2
    import locale
    from agent_runner.state import init
    init()
    if not in_tmux():
        tmux_start()
        return 0  # only a stand-in exec comes back
    locale.setlocale(locale.LC_ALL, '')
    os.environ.setdefault('ESCDELAY', '25')  # Esc backs out at once, not after curses' default second
    box: dict = {}
    if not bar:  # B153: the project's name as the terminal's window title, the old one back on the way out
        term_write(window_title(f'{U.S.project()} · runner'))
    try:
        rc = curses.wrapper(run_curses, box, bar)
    finally:
        if not bar:
            term_write(TITLE_BACK)
    if box.get('restart'):  # F90: the terminal is restored; this process becomes the new version's TUI
        follow_upgrade(box['restart'])
    if box.get('pick'):  # B153: 0 goes back to the pick-a-run screen: the launcher's, or a new one here
        if os.environ.get(PICKER_ENV):
            return PICK_RC
        from agent_runner.cmds import cmd_pick
        return cmd_pick(U.S.ROOT)
    return rc
