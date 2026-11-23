"""F65: the run page model: one snapshot of the run (JSON) for the web page, the terminal UI and the claude.ai
copy, and the actions they share.

`snapshot()` reads what `status` reads (STATE, the plan, the run log, Needs you) and returns one plain dict:

    status    the status lines: run up or not, its state, progress, release, no-gate warning, usage
    slots     the run's slot count (0 when no run is up; while it starts, [run] slots)
    sessions  c1 and every other control session window (cN, its title), then each slot s1..s<slots> and any past the count still on a task: task, title, minutes,
              state (running, merging, idle: no task), files, session link, terminal URL; none when an older
              agent-runner started the run (its panes carry no tags: `older_run`)
    sessions_note  '' or, with no sessions for that reason, the one line Sessions shows instead (`OLDER_RUN`)
    queue     every open task in TODO.md: id, kind, title, files, after, pri, section, blocked, after_title
              (what it waits on in words: 'F66 Run page: …', 'B109 (landed)', 'all: everything above it') and
              state ('running s2 6m', 'critical', 'after', 'ready')
    needs     what waits on the person (not the shelved ones): label, id, ask in plain words, link, age
    concepts  concept pages waiting for an OK: build id, concept id, title, page link, copy (the local copy
              of the page `done --artifact` kept, <notes>/concepts/<ID>.html; '' for none)
    log       the run log's last lines
    release   the release line ('' when no release is queued)
    quick_asks  the Status chat's quick asks sent to c1: key, label, text
    terminal_mode  how a session's terminal shows: 'ttyd', 'install' (tmux, no ttyd yet), 'feed'

F74 adds, outside the snapshot (read on demand, per session): `feed(name)` (its transcript as say/you/tool/out
entries); and the actions `chat_to` (any control session), `interrupt`, `new_control` and `quick_ask`; F86
`concept_chat` (a new control session about one concept).

Each action calls what the CLI already does, as a subprocess of the runner (`runner_cmd()`), so a page and a
terminal change the run exactly as a person typing the command would; `chat`, `answer` and `take` hand a
message to c1 the way the runner feed hands one on (typed into c1's pane, else a new control session with
it as its first message). Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess as sp
import time
from pathlib import Path

from agent_runner import plan as P
from agent_runner import state as S
from agent_runner.config import runner_cmd

LOG_TAIL = 20  # run log lines a snapshot carries


# --- the snapshot -------------------------------------------------------------------------------------------

def _state(up: bool) -> dict:
    try:
        return json.loads(S.C.notes('STATE').read_text(encoding='utf-8')) if up else {}
    except (OSError, ValueError):
        return {}


def _kind_names() -> dict[str, str]:
    try:
        return P.kinds()[0]
    except (OSError, SystemExit, KeyError, AttributeError):
        return dict(P.KINDS)


def task_kind(tid: str, names: dict[str, str]) -> str:
    """The kind a task id's letters name ('F65' -> its `plan kinds` line), else the letters themselves."""
    letters = re.match(r'[A-Za-z]+', tid)
    k = letters.group(0) if letters else ''
    return str(names.get(k, k))


def task_pri(rest: str, section: str) -> str:
    """A queued task's level: its `(follow-up, LEVEL)` tag; under Parked (where `--pri later` files) 'later';
    else 'normal'."""
    if t := P.PRI_TAG.search(rest):
        return t.group(1)
    return 'later' if section.startswith(P.PARKED) else 'normal'


def queue_rows(ls: list[str], st: dict | None = None, now: float | None = None) -> list[dict]:
    """Every open task ([ ] or [~]) of TODO.md's lines `ls`, in plan order. F74: each row also carries
    `after_title` (what it waits on, in words: `after_words`) and `state` (`queue_state`; STATE `st` says
    which slot runs it and since when)."""
    names, out = _kind_names(), []
    tasks = list(P.iter_tasks(ls))
    titles = {tid: P.short_title(rest, 200) for _, _, tid, rest, _ in tasks}
    names_of = {tid: after_name(rest) for _, _, tid, rest, _ in tasks}
    live = {tid for _, box, tid, _, _ in tasks if box in ' ~'}
    landed = {tid for _, box, tid, _, _ in tasks if box not in ' ~'} | done_ids()
    where = slot_of(st or {}, time.time() if now is None else now)
    for section, box, tid, rest, i in tasks:
        if box not in ' ~' or P._shelved(ls, i):  # B115: a shelved task is set aside, not queued
            continue
        f = P.fields(ls[i])
        after, pri = P.waits_on(ls, i), task_pri(rest, section)
        everything = P.ALL in f.get('after', [])
        out.append({'id': tid, 'kind': task_kind(tid, names), 'title': titles[tid],
                    'files': f.get('files', []), 'after': after, 'pri': pri,
                    'section': section, 'blocked': box == '~',
                    'after_title': after_words(after, names_of, live, everything, landed),
                    'state': queue_state(tid, pri, after, live, where, box == '~')})
    return out


# F74: a queue row's state, first word. 'blocked' (beyond the design's four): a [~] task waits on a person or
# a fix, and 'ready' would say it can start.
QUEUE_STATES = ('running', 'blocked', 'critical', 'after', 'ready')


def done_ids() -> set[str]:
    """The ids DONE.md holds (landed tasks the plan moved there)."""
    try:
        return {tid for _, _, tid, _, _ in P.iter_tasks(P.lines(S.C.done))}
    except Exception:  # noqa: BLE001 - no DONE.md
        return set()


def slot_of(st: dict, now: float) -> dict[str, str]:
    """F74: {task id: 'running sN Nm'} for every task a slot of STATE `st` runs ('running sN' with no start)."""
    out = {}
    for n, tid in (st.get('running') or {}).items():
        if not tid:
            continue
        name = f's{n}' if str(n).isdigit() else str(n)
        since = (st.get('since') or {}).get(n)
        out[tid] = f'running {name} {int((now - since) // 60)}m' if since else f'running {name}'
    return out


def after_name(rest: str, width: int = 40) -> str:
    """B115: a task as an `after` names it: its short title up to its first ': ' ('Release: bump the version…'
    -> 'Release'), cut at a word to about `width`."""
    t = P.short_title(rest, 200)
    head = t.split(': ', 1)[0].strip()
    return P.short_title(head or t, width)


def after_words(after: list[str], titles: dict[str, str], live: set[str], everything: bool = False,
                landed: set[str] | None = None) -> str:
    """F74: what a queued task waits on, as the queue row says it: 'all: everything above it' for `after: all`;
    else each id with its name while it is open ('F66 Run page', `after_name`), '(landed)' once it is done ('B109
    (landed)'), '(not in the plan)' for an id neither open nor in `landed` (None: every id not open is landed);
    joined by ', '; '' for nothing."""
    if everything:
        return 'all: everything above it'

    def one(t: str) -> str:
        if t in live:
            return f'{t} {titles.get(t, "")}'.rstrip()
        return f'{t} (landed)' if landed is None or t in landed else f'{t} (not in the plan)'
    return ', '.join(one(t) for t in after)


def queue_state(tid: str, pri: str, after: list[str], live: set[str], where: dict[str, str],
                blocked: bool = False) -> str:
    """F74: a queue row's state: 'running sN Nm' while a slot runs it, else 'blocked' ([~]: waits on a person
    or a fix), else 'critical', else 'after' while a task it waits on is still open, else 'ready'."""
    if tid in where:
        return where[tid]
    if blocked:
        return 'blocked'
    if pri == 'critical':
        return 'critical'
    return 'after' if any(t in live for t in after) else 'ready'


def needs_rows(waiting, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(needs-you items, concepts) from `status.waiting_ok()`'s list; shelved items are left out of both."""
    needs, concepts = [], []
    stamps = {w[1]: w[7] for w in waiting if len(w) > 7 and w[7]}
    for label, tid, k, what, url, title, shelved, *_ in waiting:
        if shelved:
            continue
        if label == 'CONCEPT':
            concepts.append({'id': tid, 'concept': k, 'title': title, 'url': url, 'copy': concept_copy(k)})
        needs.append({'label': label, 'id': tid, 'concept': k, 'title': title, 'what': what, 'url': url,
                      'ask': P.plain_ask(label, what, title), 'age': P.age(stamps.get(tid, ''), now)})
    return needs, concepts


def _bridge_link(sid: str) -> str:
    """The claude.ai/code link of the session `sid`, from its transcript's Remote Control entry; '' for none."""
    if not sid:
        return ''
    try:
        from agent_runner.control import control_link, control_state
        from agent_runner.slots import entries
        return control_link(control_state(entries(sid, skip_bad=True))['bridge'])
    except Exception:  # noqa: BLE001 - a link is a nicety: a missing transcript or backend leaves it ''
        return ''


def c1_row() -> dict:
    """c1, the run's own control session: live or not, and its claude.ai/code link."""
    try:
        from agent_runner.control import control_live
        pid = control_live(1)
    except Exception:  # noqa: BLE001
        pid = 0
    try:
        sid = S.C.notes('control1.pid').read_text(encoding='utf-8').strip().partition(' ')[2] if pid else ''
    except OSError:
        sid = ''
    return {'name': 'c1', 'task': '', 'title': 'control session', 'minutes': None,
            'state': 'live' if pid else 'off', 'files': [], 'link': _bridge_link(sid), 'terminal': ''}


def slot_link(name: str) -> str:
    """Slot `name`'s (s2) claude.ai/code link: its pane's agent session id, then that transcript's link."""
    try:
        from agent_runner import slots
        mux = slots.MUX
        pid = mux.panes().get(name, ('', 0))[1]
        return _bridge_link(mux.session_id(pid) or '') if pid else ''
    except Exception:  # noqa: BLE001
        return ''


def slot_count(up: bool, st: dict) -> int:
    """F71: the run's slot count: STATE's `slots`; from a STATE written before F71 its state line ('3 slots,
    paused'); while the run starts and has written no STATE yet, `[run] slots`; 0 when no run is up."""
    if not up:
        return 0
    if isinstance(st.get('slots'), int) and not isinstance(st.get('slots'), bool):
        return max(st['slots'], 0)
    if m := re.match(r'(\d+) slots?\b', str(st.get('state') or '')):
        return int(m.group(1))
    try:
        return int(S.C.raw.get('run', {}).get('slots') or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def idle_row(name: str) -> dict:
    """F71: a slot of the run with no task."""
    return {'name': name, 'task': '', 'title': '', 'minutes': None, 'state': 'idle', 'files': [], 'link': '',
            'terminal': ''}


def tmux_panes() -> list[str]:
    """B113: every tmux pane, one 'session<TAB>window name<TAB>@runner<TAB>@runner-repo<TAB>@runner-run' line
    each; [] without tmux or a server."""
    import shutil
    if not shutil.which('tmux'):
        return []
    try:
        r = sp.run(['tmux', 'list-panes', '-a', '-F',
                    f'#{{session_name}}\t#{{window_name}}\t#{{{S.TAG}}}\t#{{{S.REPO_TAG}}}\t#{{{S.RUN_TAG}}}'],
                   capture_output=True, text=True, timeout=5)
    except (OSError, sp.SubprocessError):
        return []
    return r.stdout.splitlines() if not r.returncode else []


OLDER_RUN = 'This run was started by an older agent-runner: restart it to see its sessions.'  # C23


def _ours(owner: str) -> bool:
    """C23: a pane's @runner-repo names this main checkout."""
    try:
        return bool(owner) and Path(owner).resolve() == Path(S.ROOT).resolve()
    except OSError:
        return False


def control_windows(panes: list[str]) -> dict[int, str]:
    """B113/C23: {N: title} of this repository's control session windows in `panes` (`tmux_panes` lines), read
    only by the tags this version sets: a pane tagged @runner cN whose @runner-repo is this main checkout. The
    title is its window's name after "<repo> · " and, when it is N, "N · " ("<repo> · 6 · Pairing broken" is
    'Pairing broken', "<repo> · R43 · site deploy" 'R43 · site deploy'); 'control session' when nothing is left
    ("<repo> · 3", "<repo> · control 3"). A pane with no tags is never guessed at (see `older_run`)."""
    repo = S.ROOT.name
    out: dict[int, str] = {}
    for line in panes:
        _, wname, tag, owner = (line.split('\t') + [''] * 4)[:4]
        if not (tagged := re.fullmatch(r'c(\d+)', tag)) or not _ours(owner):
            continue
        n = int(tagged[1])
        title = wname[len(repo) + 3:].strip() if wname.startswith(f'{repo} · ') else ''
        if title in (str(n), f'control {n}'):
            title = ''
        elif title.startswith(f'{n} · '):
            title = title[len(f'{n} · '):].strip()
        out.setdefault(n, title or 'control session')
    return out


def older_run(up: bool, panes: list[str]) -> bool:
    """C23: an older agent-runner started the project's run: it is up, its runner pane (@runner-run this main
    checkout) is in `panes`, and that pane has no @runner-repo tag (this version sets both on it). False for a
    hidden run (no runner pane) and with no tmux panes to read: then nothing can be told."""
    if not up:
        return False
    runner = [cols for cols in ((line.split('\t') + [''] * 5)[:5] for line in panes) if _ours(cols[4])]
    return bool(runner) and not any(_ours(cols[3]) for cols in runner)


def control_rows(windows: dict[int, str], links=None) -> list[dict]:
    """B113: c1 (`c1_row`, titled by its window when it has one), then each other control session window as
    cN with its title; `links` as `session_rows` (None: each link from its pid file's transcript)."""
    c1 = c1_row()
    if windows.get(1):
        c1['title'], c1['state'] = windows[1], 'live'
    if links and 'c1' in links:
        c1['link'] = links['c1']
    out = [c1]
    for n in sorted(k for k in windows if k > 1):
        if links is not None:
            link = links.get(f'c{n}', '')
        else:
            try:
                link = _bridge_link(S.C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip()
                                    .partition(' ')[2])
            except OSError:
                link = ''
        out.append({'name': f'c{n}', 'task': '', 'title': windows[n], 'minutes': None, 'state': 'live',
                    'files': [], 'link': link, 'terminal': ''})
    return out


def session_rows(st: dict, ls: list[str], titles: dict[str, str], now: float, links=None,
                 terminal_base: str = '', slots: int = 0, windows: dict[int, str] | None = None) -> list[dict]:
    """c1 and the other control sessions (B113: `control_rows`; `windows` as `control_windows`, None: read from
    tmux), then each slot of STATE `st` in slot order: s1..s<slots> (F71: an idle one, no task, as `idle_row`)
    and any slot past the count still on its task. `links` ({'s2': url}) replaces the lookup by pane;
    `terminal_base` is where the run page serves terminals ('' none yet: each row's `terminal` stays '')."""
    files = {tid: P.fields(ls[i]).get('files', []) for _, _, tid, _, i in P.iter_tasks(ls)}
    out = control_rows(control_windows(tmux_panes()) if windows is None else windows, links)
    merging = set(st.get('merging') or [])
    running = dict(st.get('running') or {})
    for n in range(1, slots + 1):
        running.setdefault(str(n), '')
    for n, tid in sorted(running.items(), key=lambda kv: (not kv[0].isdigit(), kv[0].zfill(4))):
        name = f's{n}' if n.isdigit() else n
        if not tid:
            out.append(idle_row(name))
            continue
        since = (st.get('since') or {}).get(n)
        out.append({'name': name, 'task': tid, 'title': titles.get(tid, ''),
                    'minutes': int((now - since) // 60) if since else None,
                    'state': 'merging' if tid in merging else 'running', 'files': files.get(tid, []),
                    'link': links.get(name, '') if links is not None else slot_link(name),
                    'terminal': f'{terminal_base.rstrip("/")}/terminal/{name}' if terminal_base else ''})
    return out


def status_rows(up: bool, st: dict, progress: str) -> list[str]:
    """The status lines: the run's state, progress, the no-gate warning, and usage."""
    from agent_runner.land import no_gate_line
    out = [f'run up: {st.get("state", "starting")}' if up else 'no run is up']
    for k, said in (('paused', 'paused'), ('stopping', 'stopping: finishing the running tasks')):
        if up and st.get(k):
            out.append(said)
    try:
        if nogate := no_gate_line():
            out.append(nogate)
    except Exception:  # noqa: BLE001
        pass
    out += [l for l in progress.splitlines() if l]
    use = st.get('usage') or {}
    if parts := [f'{w} {use[k]:.0f}%' for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
                 if use.get(k) is not None]:
        out.append('usage: ' + ', '.join(parts))
    return out


def log_tail(n: int = LOG_TAIL) -> list[str]:
    try:
        return S.C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()[-n:] if n else []
    except OSError:
        return []


def snapshot(up: bool | None = None, now: float | None = None, log_n: int = LOG_TAIL, links=None,
             terminal_base: str = '', windows: dict[int, str] | None = None) -> dict:
    """The run, as one JSON-ready dict (see the module doc). `up` and `now` default to the real ones; `links`,
    `terminal_base` and `windows` as `session_rows` (`windows` given: tmux is not read, nor `older_run` asked).
    Call after `state.init`."""
    from agent_runner.status import progress_line, release_line, waiting_ok
    up = S.run_up() if up is None else up
    now = time.time() if now is None else now
    st, ls = _state(up), P.lines(S.C.todo)
    titles = P.titles(S.C.done, S.C.todo, width=200)
    release = release_line(ls)
    try:
        progress = progress_line(now=dt.datetime.fromtimestamp(now))
    except Exception:  # noqa: BLE001 - a git hiccup costs the progress line, not the snapshot
        progress = ''
    needs, concepts = needs_rows(waiting_ok(), dt.datetime.fromtimestamp(now))
    slots = slot_count(up, st)
    panes = tmux_panes() if windows is None else None
    older = panes is not None and older_run(up, panes)
    if panes is not None:
        windows = control_windows(panes)
    sessions = [] if older else session_rows(st, ls, titles, now, links, terminal_base, slots, windows)
    return {'project': S.project(), 'at': dt.datetime.fromtimestamp(now).isoformat(timespec='seconds'),
            'up': up, 'status': status_rows(up, st, '\n'.join(x for x in (progress, release) if x)),
            'slots': slots, 'sessions': sessions, 'sessions_note': OLDER_RUN if older else '',
            'queue': queue_rows(ls, st, now),
            'needs': needs, 'concepts': concepts, 'log': log_tail(log_n), 'release': release,
            'quick_asks': quick_asks(), 'terminal_mode': terminal_mode(), 'controls': controls(),
            'run': {'paused': bool(up and st.get('paused')), 'stopping': bool(up and st.get('stopping'))}}


def snapshot_json(**kw) -> str:
    return json.dumps(snapshot(**kw), ensure_ascii=False)


# --- the actions ----------------------------------------------------------------------------------------------

def _run(argv: list[str]) -> tuple[int, str]:
    """Run the runner with `argv` in the main checkout: (exit code, what it printed)."""
    r = sp.run(runner_cmd() + argv, cwd=S.ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout + r.stderr).strip()


RUN = [_run]  # what every action runs; a test or a wrapping UI swaps it


def call(argv: list[str]) -> dict:
    """One action's result: {'ok', 'code', 'out', 'argv'}."""
    code, out = RUN[0](argv)
    return {'ok': code == 0, 'code': code, 'out': out, 'argv': argv}


def _flags(files=None, after=None, pri: str = '', test: str = '') -> list[str]:
    out = []
    if files:
        out += ['--files', ','.join(files) if isinstance(files, (list, tuple)) else files]
    if after:
        out += ['--after', ','.join(after) if isinstance(after, (list, tuple)) else after]
    if test:
        out += ['--test', test]
    if pri:
        out += ['--pri', pri]
    return out


def plan_add(kind: str, text: str, files=None, after=None, pri: str = '', test: str = '') -> dict:
    """Queue a task: `plan add KIND TEXT --files … --after … --pri …`."""
    return call(['plan', 'add', kind, text, *_flags(files, after, pri, test)])


def plan_change(tid: str, text: str = '', files=None, after=None, pri: str = '', test: str = '') -> dict:
    """The page's direct edit of a queued task: `plan edit ID [TEXT] [--files …]`, rewritten in place (a slot
    running it is told)."""
    return call(['plan', 'edit', tid, *([text] if text else []), *_flags(files, after, pri, test)])


def drop(tid: str, why: str) -> dict:
    """`plan drop ID WHY`: not wanted; a slot running it is stopped."""
    return call(['plan', 'drop', tid, why])


def shelve(tid: str) -> dict:
    """`plan shelve ID`: later; stays blocked, off Needs you."""
    return call(['plan', 'shelve', tid])


def release(now: bool = False, text: str = '') -> dict:
    """Queue a release: `plan add V [TEXT]`, which waits for the running tasks to land; `now`: `--now`."""
    return call(['plan', 'add', 'V', *([text] if text else []), *(['--now'] if now else [])])


def to_c1(text: str) -> dict:
    """Hand `text` to c1 the way the runner feed hands on a message: typed into c1's pane when it is live,
    else a new control session that gets it as its first message (`control --new --ask`). c1's pane is found
    by its c1 tag (`control_window`), never $TMUX_PANE: the caller (the run, a terminal page) is not c1 (B111)."""
    try:
        from agent_runner.control import control_live, control_window
        from agent_runner.slots import send_to_pane
        if (pid := control_live(1)) and (pane := control_window(1, pid)) and send_to_pane(pane, text):
            return {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []}
    except Exception:  # noqa: BLE001 - no tmux, no c1: a new control session takes it
        pass
    return call(['control', '--new', '--ask', text])


SEND = [to_c1]  # how chat, answers and take reach c1; a test swaps it


def chat(text: str) -> dict:
    """The page's chat box: the person's words to c1, as they typed them."""
    return SEND[0](text)


def answer(tid: str, text: str) -> dict:
    """A reply to a Needs you item, for c1 to settle (`plan confirm|change|shelve` as its needs guide says)."""
    title = P.titles(S.C.todo).get(tid, '')
    return SEND[0](f'{tid}{f" ({title})" if title else ""}: {text}')


def take(tid: str) -> dict:
    """Take (do it here): c1 is asked "do ID here", and does it as its take guide says (`take ID`, the work in
    that worktree), so the page never makes a worktree nobody works in."""
    return SEND[0](f'do {tid} here')


def open_session(slot: str) -> dict:
    """F68: open slot `slot` (s2) in claude.ai/code and the apps (`slots.slot_open`): under `[run] sessions =
    'one'` a slot is listed there only once opened. Its link as 'out', or why not."""
    from agent_runner.slots import slot_open
    link, why = slot_open(slot)
    return {'ok': bool(link), 'code': 0 if link else 1, 'out': link or why, 'argv': []}


def move(tid: str, where: str, other: str) -> dict:
    """F72: `plan move ID after|before OTHER`: the queue's J/K, one place down / up past its neighbour."""
    if where not in ('after', 'before'):
        return {'ok': False, 'code': 2, 'out': f'move: where is after or before, not {where!r}', 'argv': []}
    return call(['plan', 'move', tid, where, other])


# --- F82: the run controls ---------------------------------------------------------------------------------
#
# One list for the web page and agent-runner ui alike, so the two cannot drift apart: each control's key, its
# label, the runner command it runs ('{n}' the slot count typed, '{id}' the task), its key in agent-runner ui,
# where it shows ('run': the run's own; 'task': a slot's task), and what it asks before it runs ('' nothing).
# Take back is the one that is no runner command of its own: c1 is asked "do ID here", as `take` does.

STOP_NOW_ASK = ('Stop now ends every agent session at once (each resumes in the next run); '
                'the merges under way finish. Stop now?')
RUN_CONTROLS = (
    {'key': 'slot_add', 'label': 'Slot +1', 'argv': ('slots', '+1'), 'tui': '+', 'where': 'run'},
    {'key': 'slot_remove', 'label': 'Slot -1', 'argv': ('slots', '-1'), 'tui': '-', 'where': 'run'},
    {'key': 'slots_set', 'label': 'Set slots', 'argv': ('slots', '{n}'), 'tui': '=', 'where': 'run'},
    {'key': 'pause', 'label': 'Pause', 'argv': ('pause',), 'tui': 'P', 'where': 'run'},
    {'key': 'go_on', 'label': 'Go on', 'argv': ('pause', '--off'), 'tui': 'G', 'where': 'run'},
    {'key': 'force', 'label': 'Force past the caps', 'argv': ('force',), 'tui': 'F', 'where': 'run'},
    {'key': 'caps_on', 'label': 'Caps back on', 'argv': ('force', '--off'), 'tui': 'C', 'where': 'run'},
    {'key': 'stop', 'label': 'Stop (running tasks finish)', 'argv': ('stop',), 'tui': 'S', 'where': 'run'},
    {'key': 'stop_now', 'label': 'Stop now', 'argv': ('stop', '--force'), 'tui': 'X', 'where': 'run',
     'confirm': STOP_NOW_ASK},
    {'key': 'stop_undo', 'label': 'Take the stop back', 'argv': ('stop', '--undo'), 'tui': 'U', 'where': 'run'},
    {'key': 'task_take', 'label': 'Take back', 'ask': 'do {id} here', 'tui': 'H', 'where': 'task'},
    {'key': 'task_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'where': 'task'},
)
TASK_DROP_WHY = 'dropped from its slot from the run controls'
SLOT_COUNT = re.compile(r'[+-]?\d{1,3}')
TASK_ID = re.compile(r'[A-Z]+\d+[a-z]?')


def run_control_of(key: str) -> dict | None:
    return next((c for c in RUN_CONTROLS if c['key'] == key), None)


def controls() -> list[dict]:
    """The run controls as a page shows them: key, label, TUI key, where, what it needs typed ('n': a slot
    count, 'id': a task) and its confirm question ('' none)."""
    def needs(c):
        words = c.get('argv') or (c.get('ask'),)
        return 'n' if any('{n}' in w for w in words) else 'id' if any('{id}' in w for w in words) else ''
    return [{'key': c['key'], 'label': c['label'], 'tui': c['tui'], 'where': c['where'], 'needs': needs(c),
             'confirm': c.get('confirm', '')} for c in RUN_CONTROLS]


def control_argv(key: str, n='', tid: str = '', why: str = '') -> list[str]:
    """The runner command control `key` runs, filled in; ValueError says what is missing or wrong."""
    c = run_control_of(key)
    if c is None:
        raise ValueError(f'no such run control: {key!r}')
    words = list(c.get('argv') or ())
    n = str(n).strip()
    if any('{n}' in w for w in words) and not (SLOT_COUNT.fullmatch(n) and (key != 'slots_set' or n.isdigit())):
        raise ValueError(f'{key}: the slot count is a number, not {n!r}')
    if any('{id}' in w for w in words + [c.get('ask') or '']) and not TASK_ID.fullmatch(tid or ''):
        raise ValueError(f'{key}: a task id (F82), not {tid!r}')
    return [w.replace('{n}', n).replace('{id}', tid).replace('{why}', why or TASK_DROP_WHY) for w in words]


def run_control(key: str, n='', tid: str = '', why: str = '', confirm: bool = False) -> dict:
    """F82: run one run control (RUN_CONTROLS) for the web page or agent-runner ui. One with a confirm question
    runs only with `confirm` true; without it the result is not ok and carries the question as 'confirm'."""
    try:
        argv = control_argv(key, n, tid, why)
    except ValueError as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    c = run_control_of(key)
    if c.get('confirm') and confirm is not True:
        return {'ok': False, 'code': 3, 'out': c['confirm'], 'confirm': c['confirm'], 'argv': argv}
    if c.get('ask'):
        return SEND[0](c['ask'].replace('{id}', tid))
    return call(argv)


ACTIONS = {'plan_add': plan_add, 'plan_change': plan_change, 'chat': chat, 'answer': answer, 'drop': drop,
           'take': take, 'shelve': shelve, 'release': release, 'open_session': open_session, 'move': move,
           'run_control': run_control}


def act(name: str, **args) -> dict:
    """Run the action `name` with `args` (a page's POST body): an unknown name is an error result, not a raise."""
    if name not in ACTIONS:
        return {'ok': False, 'code': 2, 'out': f'no such action: {name}', 'argv': []}
    try:
        return ACTIONS[name](**args)
    except TypeError as e:
        return {'ok': False, 'code': 2, 'out': f'{name}: {e}', 'argv': []}


# --- F74: the feed, chat with any control session, quick asks, concept copies, the terminal view ---------------
#
# The feed is a session's transcript (Claude Code's JSONL; Pi's, in Claude's shape by `slots.backend().entry`)
# as entries {'kind': say|you|tool|out, 'text'}, newest last: the agent's words, the person's, each tool step
# and its output, so a page shows the words with the steps folded. The terminal view is the session's live
# tmux pane, through ttyd when it is installed ('ttyd'; C25: with tmux and no ttyd, 'install': the page says how
# to install it); on Windows or with no tmux, the feed only ('feed').

FEED_BYTES = 400_000  # the tail of a transcript a feed reads: a long session's whole file is not read each poll
FEED_MAX = 200  # entries a feed returns
OUT_LINES, OUT_CHARS, TOOL_CHARS = 3, 300, 120  # how much of a tool's output, and of its call, a feed keeps
INTERRUPTED = '[Request interrupted'  # how Claude Code records an Escape in the transcript
QUICK_ASKS = (  # F74: the Status chat's quick asks, sent to c1: (key, label, text)
    ('since', 'since last look', 'what happened since my last look?'),
    ('yesterday', 'since yesterday', 'what happened since yesterday?'),
    ('needs', 'what needs me', 'what needs me?'),
    ('usage', 'usage', 'where are the tokens going?'),
)
KEYS = ('Enter', 'Escape', 'Tab', 'BSpace', 'Up', 'Down', 'Left', 'Right', 'C-c')  # named keys `keys` may send
LINK = re.compile(r'https://claude\.ai/code\S*')
CONCEPT_ID = re.compile(r'[A-Za-z]+\d+\w*')


def _clip(text: str, lines: int, chars: int) -> str:
    ls = text.strip().splitlines()
    out = '\n'.join(ls[:lines]) + ('\n…' if len(ls) > lines else '')
    return out if len(out) <= chars else out[:chars - 1] + '…'


def _blocks_text(c) -> str:
    """A content's text: a string as is, else its text blocks joined by newlines."""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text'
                         and isinstance(x.get('text'), str))
    return ''


def tool_words(name: str, args) -> str:
    """A tool call as a feed line: 'Bash(./run status)', 'Read(agent_runner/cmds.py)', 'Edit(a.py)'."""
    arg = ''
    if isinstance(args, dict):
        for k in ('command', 'file_path', 'path', 'pattern', 'url', 'query', 'description', 'prompt'):
            if isinstance(args.get(k), str) and args[k].strip():
                arg = args[k]
                break
        else:
            arg = next((v for v in args.values() if isinstance(v, str) and v.strip()), '')
    arg = ' '.join(arg.split())
    return f'{name}({arg[:TOOL_CHARS - 1] + "…" if len(arg) > TOOL_CHARS else arg})' if arg else str(name)


def feed_entries(rows) -> list[dict]:
    """F74: transcript entries (Claude's shape) as feed entries, in order: 'you' (what the person typed, not
    the runner's or a hook's text), 'say' (the agent's words), 'tool' (a tool call, `tool_words`) and 'out' (its
    result, cut to OUT_LINES lines). Thinking, meta, compact summaries and subagents' entries are left out."""
    from agent_runner.control import RUNNER_TURN
    out: list[dict] = []
    for d in rows:
        if not isinstance(d, dict) or d.get('type') not in ('user', 'assistant') or d.get('isSidechain') \
                or d.get('isMeta') or d.get('isCompactSummary'):
            continue
        m = d.get('message') or {}
        c = m.get('content')
        if d['type'] == 'assistant':
            for b in (c if isinstance(c, list) else [{'type': 'text', 'text': c}] if isinstance(c, str) else []):
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text' and str(b.get('text') or '').strip():
                    out.append({'kind': 'say', 'text': b['text'].strip()})
                elif b.get('type') in ('tool_use', 'toolCall'):  # Claude's, Pi's
                    out.append({'kind': 'tool', 'text': tool_words(b.get('name', 'tool'),
                                                                   b.get('input', b.get('arguments')))})
            continue
        if m.get('role') == 'toolResult':  # Pi: a tool's result is a message of its own
            out.append({'kind': 'out', 'text': _clip(_blocks_text(c), OUT_LINES, OUT_CHARS)})
            continue
        for b in ([{'type': 'text', 'text': c}] if isinstance(c, str) else c if isinstance(c, list) else []):
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_result':
                out.append({'kind': 'out', 'text': _clip(_blocks_text(b.get('content')), OUT_LINES, OUT_CHARS)})
            elif b.get('type') == 'text' and (t := str(b.get('text') or '').strip()):
                if t.startswith(INTERRUPTED):
                    out.append({'kind': 'out', 'text': 'interrupted'})
                elif not t.startswith(RUNNER_TURN) and not t.startswith('<task-notification>'):
                    out.append({'kind': 'you', 'text': t})
    return out


def session_sid(name: str) -> str:
    """The agent session id of `name`: cN's from its pid file ("pid sid", kept while it is closed: its
    transcript stays), a slot's (s2) from its pane's process; '' for none."""
    if re.fullmatch(r'c\d+', name):
        try:
            return S.C.notes(f'control{name[1:]}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
        except OSError:
            return ''
    try:
        from agent_runner import slots
        pid = slots.MUX.panes().get(name, ('', 0))[1]
        return (slots.MUX.session_id(pid) or '') if pid else ''
    except Exception:  # noqa: BLE001 - no tmux, no such slot
        return ''


def transcript_of(name: str) -> str:
    """The transcript file of session `name` (c1, c6, s2); '' for none."""
    if not (sid := session_sid(name)):
        return ''
    try:
        from agent_runner.slots import transcript
        return transcript(sid) or ''
    except Exception:  # noqa: BLE001
        return ''


def tail_rows(path: str, nbytes: int = FEED_BYTES):
    """The transcript entries in the last `nbytes` of `path` (a line cut at the start, or not JSON, skipped),
    each in Claude's shape."""
    try:
        from agent_runner.slots import backend
        shape = backend().entry
    except Exception:  # noqa: BLE001
        shape = lambda d: d  # noqa: E731
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - nbytes, 0))
            data = f.read()
    except OSError:
        return
    lines = data.decode('utf-8', errors='replace').splitlines()
    for l in lines[1:] if size > nbytes else lines:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if isinstance(d, dict) and (d := shape(d)) is not None:
            yield d


def feed(name: str, limit: int = FEED_MAX) -> dict:
    """F74: session `name`'s feed (`feed_entries` of its transcript's tail), newest last: {'ok', 'name',
    'entries', 'more' (older entries left out), 'link' (its claude.ai/code session, '' for none)}."""
    path = transcript_of(name)
    rows = feed_entries(tail_rows(path)) if path else []
    sid = session_sid(name)
    return {'ok': bool(path), 'name': name, 'entries': rows[-limit:] if limit else rows,
            'more': len(rows) > limit > 0, 'link': _bridge_link(sid) if sid else '',
            **({} if path else {'out': f'{name} has no transcript to read yet.'})}


def quick_asks() -> list[dict]:
    """F74: the Status chat's quick asks, for a page's buttons: key, label, the text sent to c1."""
    return [{'key': k, 'label': l, 'text': t} for k, l, t in QUICK_ASKS]


def concept_copy(cid: str) -> str:
    """F74: the local copy of concept `cid`'s page (<notes>/concepts/<ID>.html, written by `done --artifact`),
    as a path; '' when there is none."""
    if not cid or not CONCEPT_ID.fullmatch(cid):
        return ''
    try:
        p = S.C.notes('concepts', f'{cid}.html')
        return str(p) if p.is_file() else ''
    except Exception:  # noqa: BLE001 - no notes dir yet
        return ''


def terminal_mode() -> str:
    """F74: how a page shows a session's terminal: 'ttyd' (installed, with tmux), 'install' (tmux, no ttyd: the
    page says how to install it; C25), or 'feed' (Windows, or no tmux: the feed and the session link only)."""
    import shutil
    from agent_runner import plat
    if plat.WINDOWS or not shutil.which('tmux'):
        return 'feed'
    return 'ttyd' if shutil.which('ttyd') else 'install'


def session_pane(name: str) -> str:
    """The tmux pane of `name`: c1 or another control session cN by its tag (`control.control_window`), a slot
    (s2) by the run's panes; '' when it has none (a hidden run, no tmux, not up)."""
    if re.fullmatch(r'c\d+', name):
        try:
            from agent_runner.control import control_live, control_window
            return control_window(int(name[1:]), control_live(int(name[1:])))
        except Exception:  # noqa: BLE001
            return ''
    try:
        from agent_runner import slots
        if getattr(slots.MUX, 'name', '') != 'tmux':
            return ''
        return slots.MUX.panes().get(name, ('', 0))[0]
    except Exception:  # noqa: BLE001
        return ''


def _tmux(argv: list[str]) -> tuple[int, str]:
    try:
        r = sp.run(['tmux', *argv], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5)
    except (OSError, sp.SubprocessError) as e:
        return 1, str(e)
    return r.returncode, r.stdout if not r.returncode else r.stderr.strip()


TMUX = [_tmux]  # how `keys` reaches tmux; a test swaps it


def _no_pane(name: str) -> dict:
    return {'ok': False, 'code': 1, 'out': f'{name} has no tmux pane (the run is hidden, {name} is not up, or '
                                           f'there is no tmux): its feed and session link still work.', 'argv': []}


def keys(session: str, text: str = '', key: str = '') -> dict:
    """F74: `text` typed into `session`'s pane (c6, s2) as is (`send-keys -l`), then the named `key` (one of
    KEYS: Enter, Escape, …) if given; `interrupt` sends Escape through it (C25: no longer an action)."""
    if key and key not in KEYS:
        return {'ok': False, 'code': 2, 'out': f'keys: key is one of {", ".join(KEYS)}, not {key!r}', 'argv': []}
    if not (pane := session_pane(session)):
        return _no_pane(session)
    for argv in ([['send-keys', '-t', pane, '-l', text]] if text else []) + \
            ([['send-keys', '-t', pane, key]] if key else []):
        code, out = TMUX[0](argv)
        if code:
            return {'ok': False, 'code': code, 'out': f'tmux send-keys: {out}', 'argv': argv}
    return {'ok': True, 'code': 0, 'out': f'typed into {session}', 'argv': []}


def interrupt(session: str = 'c1') -> dict:
    """F74: interrupt `session` (Escape into its pane), as a person pressing Esc in it would."""
    r = keys(session, key='Escape')
    return {**r, 'out': f'interrupted {session}'} if r['ok'] else r


def send(name: str, text: str) -> dict:
    """F74: the person's words to session `name` as they typed them: c1 as `chat` hands them on (`SEND`), any
    other control session or slot typed into its pane (`slots.send_to_pane`)."""
    if name == 'c1':
        return SEND[0](text)
    if not (pane := session_pane(name)):
        return _no_pane(name)
    from agent_runner import slots
    ok = slots.send_to_pane(pane, text)
    return {'ok': ok, 'code': 0 if ok else 1, 'out': f'sent to {name}' if ok else f'could not type into {name}',
            'argv': []}


def chat_to(text: str, to: str = 'c1') -> dict:
    """F74: the chat box of any control session: `to` (c1, c6) gets `text`."""
    return send(to, text)


def new_control(ask: str = '') -> dict:
    """F74: start a new control session (`control --new`, `ask` its first message): the result's 'link' is its
    claude.ai/code link ('' when it printed none)."""
    r = call(['control', '--new', *(['--ask', ask] if ask else [])])
    m = LINK.search(r['out'] or '')
    return {**r, 'link': m.group(0).rstrip('.,)') if m else ''}


def concept_chat_text(row: dict) -> str:
    """F86: the first message of a new control session about one concept (a Concepts row: concept, id, title,
    url, copy): which concept, its page link and local copy, and to follow guide concepts."""
    cid = row.get('concept') or row.get('id') or ''
    title = row.get('title') or ''
    where = [f'its page {row["url"]}' if row.get('url') else 'no page link',
             f'its local copy {row["copy"]}' if row.get('copy') else 'no local copy']
    return (f"This chat is about concept {cid} '{title}': {', '.join(where)}. Read guide concepts first and "
            f"follow it: change that same page with the Artifact tool and open it inline, and build nothing "
            f"until I say a plain go.")


def concept_chat(cid: str, title: str = '', url: str = '', copy: str = '') -> dict:
    """F86: a new control session about concept `cid` (its K id, or the id of its build task): `control --new
    --ask` with `concept_chat_text`. The row comes from the waiting list; `title`, `url` and `copy` fill in for
    a concept no longer listed."""
    if not cid or not CONCEPT_ID.fullmatch(cid):
        return {'ok': False, 'code': 2, 'out': f'concept_chat: no concept id: {cid!r}', 'argv': []}
    try:
        from agent_runner.status import waiting_ok
        _, rows = needs_rows(waiting_ok(), dt.datetime.now())
    except Exception:  # noqa: BLE001 - no plan to read: the given title and link
        rows = []
    row = next((r for r in rows if cid in (r.get('concept'), r.get('id'))), None) or \
        {'concept': cid, 'title': title, 'url': url, 'copy': copy or concept_copy(cid)}
    return new_control(concept_chat_text(row))


def quick_ask(key: str) -> dict:
    """F74: one of the Status chat's quick asks (QUICK_ASKS: since, yesterday, needs, usage), sent to c1."""
    text = next((t for k, _, t in QUICK_ASKS if k == key), '')
    if not text:
        return {'ok': False, 'code': 2, 'out': f'quick_ask: key is one of {", ".join(k for k, _, _ in QUICK_ASKS)}, '
                                               f'not {key!r}', 'argv': []}
    return SEND[0](text)


ACTIONS.update({'chat_to': chat_to, 'interrupt': interrupt, 'new_control': new_control, 'quick_ask': quick_ask})
ACTIONS['concept_chat'] = concept_chat  # F86
