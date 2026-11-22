"""F65: the run page model: one snapshot of the run (JSON) for the web page, the terminal UI and the claude.ai
copy, and the actions they share.

`snapshot()` reads what `status` reads (STATE, the plan, the run log, Needs you) and returns one plain dict:

    status    the status lines: run up or not, its state, progress, release, no-gate warning, usage
    slots     the run's slot count (0 when no run is up; while it starts, [run] slots)
    sessions  c1, then each slot s1..s<slots> and any past the count still on a task: task, title, minutes,
              state (running, merging, idle: no task), files, session link, terminal URL
    queue     every open task in TODO.md: id, kind, title, files, after, pri, section, blocked
    needs     what waits on the person (not the shelved ones): label, id, ask in plain words, link, age
    concepts  concept pages waiting for an OK: build id, concept id, title, page link
    log       the run log's last lines
    release   the release line ('' when no release is queued)

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


def queue_rows(ls: list[str]) -> list[dict]:
    """Every open task ([ ] or [~]) of TODO.md's lines `ls`, in plan order."""
    names, out = _kind_names(), []
    for section, box, tid, rest, i in P.iter_tasks(ls):
        if box not in ' ~':
            continue
        f = P.fields(ls[i])
        out.append({'id': tid, 'kind': task_kind(tid, names), 'title': P.short_title(rest, 200),
                    'files': f.get('files', []), 'after': P.waits_on(ls, i), 'pri': task_pri(rest, section),
                    'section': section, 'blocked': box == '~'})
    return out


def needs_rows(waiting, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(needs-you items, concepts) from `status.waiting_ok()`'s list; shelved items are left out of both."""
    needs, concepts = [], []
    stamps = {w[1]: w[7] for w in waiting if len(w) > 7 and w[7]}
    for label, tid, k, what, url, title, shelved, *_ in waiting:
        if shelved:
            continue
        if label == 'CONCEPT':
            concepts.append({'id': tid, 'concept': k, 'title': title, 'url': url})
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


def session_rows(st: dict, ls: list[str], titles: dict[str, str], now: float, links=None,
                 terminal_base: str = '', slots: int = 0) -> list[dict]:
    """c1, then each slot of STATE `st` in slot order: s1..s<slots> (F71: an idle one, no task, as `idle_row`)
    and any slot past the count still on its task. `links` ({'s2': url}) replaces the lookup by pane;
    `terminal_base` is where the run page serves terminals ('' none yet: each row's `terminal` stays '')."""
    files = {tid: P.fields(ls[i]).get('files', []) for _, _, tid, _, i in P.iter_tasks(ls)}
    out = [c1_row()]
    if links and 'c1' in links:
        out[0]['link'] = links['c1']
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
             terminal_base: str = '') -> dict:
    """The run, as one JSON-ready dict (see the module doc). `up` and `now` default to the real ones; `links`
    and `terminal_base` as `session_rows`. Call after `state.init`."""
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
    return {'project': S.project(), 'at': dt.datetime.fromtimestamp(now).isoformat(timespec='seconds'),
            'up': up, 'status': status_rows(up, st, '\n'.join(x for x in (progress, release) if x)),
            'slots': slots, 'sessions': session_rows(st, ls, titles, now, links, terminal_base, slots),
            'queue': queue_rows(ls),
            'needs': needs, 'concepts': concepts, 'log': log_tail(log_n), 'release': release}


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


ACTIONS = {'plan_add': plan_add, 'plan_change': plan_change, 'chat': chat, 'answer': answer, 'drop': drop,
           'take': take, 'shelve': shelve, 'release': release}


def act(name: str, **args) -> dict:
    """Run the action `name` with `args` (a page's POST body): an unknown name is an error result, not a raise."""
    if name not in ACTIONS:
        return {'ok': False, 'code': 2, 'out': f'no such action: {name}', 'argv': []}
    try:
        return ACTIONS[name](**args)
    except TypeError as e:
        return {'ok': False, 'code': 2, 'out': f'{name}: {e}', 'argv': []}
