"""F65: the run page model: one snapshot of the run (JSON) for the web page, the terminal UI and the claude.ai
copy, and the actions they share.

`snapshot()` reads what `status` reads (STATE, the plan, the run log, Needs you) and returns one plain dict:

    status    the status lines: run up or not, its state, progress, release, no-gate warning, usage
    slots     the run's slot count (0 when no run is up; while it starts, [run] slots)
    sessions  c1 and every other live control session (cN, its title from state), then each slot s1..s<slots>
              and any past the count still on a task: task, title, minutes, state (running, merging, idle: no
              task), files, session link, terminal URL
    sessions_note  '' (kept for pages that read it: C26 has no older run to tell apart)
    queue     every open task in TODO.md: id, kind, title, files, after, pri, section, blocked, after_title
              (what it waits on in words: 'F66 Run page: …', 'B109 (landed)', 'all: everything above it') and
              state ('running s2 6m', 'critical', 'after', 'parked', 'ready')
    needs     what waits on the person (not the shelved ones): label, id, ask in plain words, link, age
    concepts  concept pages waiting for an OK: build id, concept id, title, page link, copy (the local copy
              of the page `done --artifact` kept, <notes>/concepts/<ID>.html; '' for none)
    log       the run log's last lines
    release   the release line ('' when no release is queued)
    quick_asks  the Status chat's quick asks sent to c1: key, label, text
    terminal_mode  how a session's terminal shows: 'ttyd', 'install' (no ttyd yet), 'feed' (Windows)
    version   the run's agent-runner version, from STATE ('' when no run is up or an older run wrote none);
              F90: the TUI restarts and the run page reloads when it changes

F74 adds, outside the snapshot (read on demand, per session): `feed(name)` (its transcript as say/you/tool/out
entries); and the actions `chat_to` (any control session), `interrupt`, `new_control` and `quick_ask`; F86
`concept_chat` (a new control session about one concept).

Each action calls what the CLI already does, as a subprocess of the runner (`runner_cmd()`), so a page and a
terminal change the run exactly as a person typing the command would (B138: a Needs you button's `answer` runs
`plan confirm|change` or `sheet` itself); `chat`, a typed `answer` and `take` hand a message to c1 the way the runner feed hands one on (typed into c1, else a new control session with
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
# a fix, and 'ready' would say it can start. B118: 'parked' (level later, TODO.md's Parked section): a run never
# starts it, so it must not say 'ready' either.
QUEUE_STATES = ('running', 'blocked', 'critical', 'after', 'parked', 'ready')


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
    or a fix), else 'parked' (B118: level 'later': a run never starts it), else 'critical', else 'after' while a
    task it waits on is still open, else 'ready'."""
    if tid in where:
        return where[tid]
    if blocked:
        return 'blocked'
    if pri == 'later':
        return 'parked'
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
                      'ask': (ask := P.plain_ask(label, what, title)), 'ask_short': ask_short(ask),
                      'age': P.age(stamps.get(tid, ''), now)})
    return needs, concepts


ASK_SHORT = 120  # B152: the most a short ask runs to, in characters


def ask_short(ask: str, limit: int = ASK_SHORT) -> str:
    """B152: a Needs you ask, short, on one line: its first sentence, without parenthesised asides and paths
    (those stay in the full ask), cut to `limit` characters with an ellipsis."""
    s = re.sub(r'\s+', ' ', ask or '').strip()
    while (t := re.sub(r'\s*\([^()]*\)', '', s)) != s:  # asides, nested ones too
        s = t
    # paths: ~/x, ./x, /abs, a/b.md, a/b/c; not words like yes/no, TCP/IP or 17/18
    s = re.sub(r'\s*(?<!\S)(?:(?:~|\.{1,2})?/\S+|[\w.@+-]+(?:/[\w.@+-]+)+\.[A-Za-z]\w{0,4}\b'
               r'|[\w.@+-]+(?:/[\w.@+-]+){2,})', '', s)
    s = re.split(r'(?<=[.!?])\s+(?=[A-Z])', s.strip(' ,;:'), maxsplit=1)[0].strip(' ,;:')
    s = re.sub(r'\s+([,.;:!?])', r'\1', s)
    return s if len(s) <= limit else s[:limit - 1].rstrip(' ,;:-') + '…'


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
    """Slot `name`'s (s2) claude.ai/code link: its session's agent session id, then that transcript's link."""
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


def given_title(name: str, n: int) -> str:
    """A control session's title from the name the runner gave it (`control_given`): what follows "<repo> · "
    and, when it is N, "N · " ("<repo> · 6 · Pairing broken" is 'Pairing broken', "<repo> · R43 · site deploy"
    'R43 · site deploy'); 'control session' when nothing is left ("<repo> · 3", "<repo> · control 3", '')."""
    repo = S.ROOT.name
    title = name[len(repo) + 3:].strip() if name.startswith(f'{repo} · ') else ''
    if title in (str(n), f'control {n}'):
        title = ''
    elif title.startswith(f'{n} · '):
        title = title[len(f'{n} · '):].strip()
    return title or 'control session'


def control_titles() -> dict[int, str]:
    """C26: {N: title} of this repository's live control sessions (c1 and those with a live pid file), each
    titled from the name kept in state (`<notes>/controlN.title`, `given_title`); no window names are read."""
    try:
        from agent_runner.control import control_given, control_live, control_live_numbers
        live = ([1] if control_live(1) else []) + control_live_numbers()
        return {n: given_title(control_given(n), n) for n in live}
    except Exception:  # noqa: BLE001 - no notes dir yet
        return {}


def control_rows(windows: dict[int, str], links=None) -> list[dict]:
    """B113: c1 (`c1_row`, titled from state when it is live), then each other live control session as cN with
    its title (`windows`, as `control_titles`); `links` as `session_rows` (None: each link from its pid file's
    transcript)."""
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
    """c1 and the other control sessions (B113: `control_rows`; `windows` as `control_titles`, None: read from
    state), then each slot of STATE `st` in slot order: s1..s<slots> (F71: an idle one, no task, as `idle_row`)
    and any slot past the count still on its task. `links` ({'s2': url}) replaces the lookup by session;
    `terminal_base` is where the run page serves terminals ('' none yet: each row's `terminal` stays '')."""
    files = {tid: P.fields(ls[i]).get('files', []) for _, _, tid, _, i in P.iter_tasks(ls)}
    out = control_rows(control_titles() if windows is None else windows, links)
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
    `terminal_base` and `windows` as `session_rows` (`windows` given: state is not read for titles).
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
    sessions = session_rows(st, ls, titles, now, links, terminal_base, slots, windows)
    return {'project': S.project(), 'at': dt.datetime.fromtimestamp(now).isoformat(timespec='seconds'),
            'up': up, 'status': status_rows(up, st, '\n'.join(x for x in (progress, release) if x)),
            'slots': slots, 'sessions': sessions, 'sessions_note': '',
            'queue': queue_rows(ls, st, now),
            'needs': needs, 'concepts': concepts, 'log': log_tail(log_n), 'release': release,
            'quick_asks': quick_asks(), 'terminal_mode': terminal_mode(), 'controls': controls(),
            'run': {'paused': bool(up and st.get('paused')), 'stopping': bool(up and st.get('stopping'))},
            'version': str(st.get('version') or '')}  # F90: the run's version ('' from an older run)


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
    """Hand `text` to c1 the way the runner feed hands on a message: typed into c1 when it is live (through its
    hidden shim's FIFO, `control.control_type`), else a new control session that gets it as its first message
    (`control --new --ask`)."""
    try:
        from agent_runner.control import control_live, control_type
        if control_live(1) and control_type(1, text):
            return {'ok': True, 'code': 0, 'out': 'sent to c1', 'argv': []}
    except Exception:  # noqa: BLE001 - no c1 to type into: a new control session takes it
        pass
    return call(['control', '--new', '--ask', text])


SEND = [to_c1]  # how chat and answers reach c1; a test swaps it


def chat(text: str) -> dict:
    """The page's chat box: the person's words to c1, as they typed them."""
    return SEND[0](text)


SHEET_GO = ('go', 'recommended')  # a pick sheet's reply for its recommended picks
CHECK_FAILED = 'No: the check failed'  # B138: what a CONFIRM's No reopens the task with


def need_label(tid: str) -> str:
    """B138: the label of what `tid` asks (CONFIRM, DECIDE, BLOCKED, STUCK, CONCEPT); '' when nothing needs you
    about it."""
    try:
        return P._ask(tid, S.C.todo)[0]
    except (SystemExit, OSError, AttributeError):
        return ''


def answer_argv(tid: str, text: str, button: bool = False) -> tuple[list[str], str]:
    """B138: the runner command that settles a Needs you reply at once, and what to say once it did; ([], '')
    when the reply is c1's to read. A button's Yes (or a pick, or done) is `plan confirm ID "<reply>"`, a
    CONFIRM's No is `plan change ID "No: the check failed"`; a pick sheet's go or Send line is `sheet ID
    --go|--picks`. Free words typed in the reply box are c1's."""
    said, label = (text or '').strip(), need_label(tid)
    if label == 'DECIDE' and button:
        from agent_runner.brief import has_sheet
        if has_sheet(tid) and said.lower() in SHEET_GO:
            return ['sheet', tid, '--go'], f'{tid} answered with the recommended picks'
        if has_sheet(tid) and said.startswith(f'{tid} picks:'):
            return ['sheet', tid, '--picks', said], f'{tid} answered with your picks'
    if not button or not said or label not in ('CONFIRM', 'DECIDE', 'BLOCKED', P.STUCK):
        return [], ''
    if label == 'CONFIRM' and said.lower() == 'no':
        return ['plan', 'change', tid, CHECK_FAILED], f'{tid} reopened: the check failed'
    if label == 'CONFIRM':
        return ['plan', 'confirm', tid, said], f'{tid} ticked'
    return ['plan', 'confirm', tid, said], f'{tid} answered ({said}): a run starts it'


def answer(tid: str, text: str, button: bool = False) -> dict:
    """A reply to a Needs you item. B138: a button's answer runs the plan command itself (`answer_argv`), with
    no AI session, and an ok result carries 'said' (what was done, for the toast) and 'gone' (the item, off
    Needs you); the words typed in a reply box go to c1 to settle as its needs guide says."""
    argv, done = answer_argv(tid, text, button)
    if button and not argv and not need_label(tid):  # answered already, or never asked: say so, no AI session
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    if argv:
        r = call(argv)
        if r['ok']:
            r.update(said=done, gone=tid)
        return r
    title = P.titles(S.C.todo).get(tid, '')
    return SEND[0](f'{tid}{f" ({title})" if title else ""}: {text}')


def take(tid: str, wait: bool = True) -> dict:
    """Take (do it here): a new control session is asked "do ID here" (B139: not c1, whose whole history each
    send would carry), and does it as its take guide says (`take ID`, the work in that worktree), so the page
    never makes a worktree nobody works in. The result is `new_control`'s: 'name' the new cN to open."""
    return new_control(f'do {tid} here', wait)


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


def unpark(tid: str) -> dict:
    """B118: Unpark a parked task (level later, a run never starts it): `plan edit ID --pri normal`, which moves
    it into Follow-ups, where a run starts it."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'code': 2, 'out': f'unpark: a task id (F83), not {tid!r}', 'argv': []}
    return call(['plan', 'edit', tid, '--pri', 'normal'])


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
    # C26: the run's u, z and x keys, posted as the run view posts them (`key`: they take themselves back when
    # sent again, as typed ones do)
    {'key': 'upgrade', 'label': 'Upgrade agent-runner', 'argv': ('key', 'u'), 'tui': 'V', 'where': 'run'},
    {'key': 'suspend', 'label': 'Suspend once stopped', 'argv': ('key', 'z'), 'tui': 'Z', 'where': 'run'},
    {'key': 'shutdown', 'label': 'Shut down once stopped', 'argv': ('key', 'x'), 'tui': 'B', 'where': 'run'},
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


def run_control(key: str, n='', tid: str = '', why: str = '', confirm: bool = False, wait: bool = True) -> dict:
    """F82: run one run control (RUN_CONTROLS) for the web page or agent-runner ui. One with a confirm question
    runs only with `confirm` true; without it the result is not ok and carries the question as 'confirm'. B139:
    one with an 'ask' starts a new control session with it (`new_control`, `wait` as there), not c1."""
    try:
        argv = control_argv(key, n, tid, why)
    except ValueError as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    c = run_control_of(key)
    if c.get('confirm') and confirm is not True:
        return {'ok': False, 'code': 3, 'out': c['confirm'], 'confirm': c['confirm'], 'argv': argv}
    if c.get('ask'):
        return new_control(c['ask'].replace('{id}', tid), wait)
    return call(argv)


ACTIONS = {'plan_add': plan_add, 'plan_change': plan_change, 'chat': chat, 'answer': answer, 'drop': drop,
           'take': take, 'shelve': shelve, 'release': release, 'open_session': open_session, 'move': move,
           'run_control': run_control, 'unpark': unpark}


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
# and its output, so a page shows the words with the steps folded. The terminal view is the session's own
# terminal (`attach NAME` through its shim's socket), through ttyd when it is installed ('ttyd'; C25: without
# ttyd, 'install': the page says how to install it); on Windows the feed only ('feed').

FEED_BYTES = 400_000  # the tail of a transcript a feed reads: a long session's whole file is not read each poll
FEED_MAX = 200  # entries a feed returns
OUT_LINES, OUT_CHARS, TOOL_CHARS = 3, 300, 120  # how much of a tool's output, and of its call, a feed keeps
INTERRUPTED = '[Request interrupted'  # how Claude Code records an Escape in the transcript
QUICK_ASKS = (  # F74: the Status chat's quick asks, each a new control session's first message (B139)
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
    transcript stays), a slot's (s2) from its hidden session's job; '' for none."""
    if re.fullmatch(r'c\d+', name):
        try:
            return S.C.notes(f'control{name[1:]}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
        except OSError:
            return ''
    try:
        from agent_runner import slots
        pid = slots.MUX.panes().get(name, ('', 0))[1]
        return (slots.MUX.session_id(pid) or '') if pid else ''
    except Exception:  # noqa: BLE001 - no such slot
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
    """F74: the Status chat's quick asks, for a page's buttons: key, label, the text a new control session gets (B139)."""
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
    """F74: how a page shows a session's terminal: 'ttyd' (installed: it serves `attach NAME`), 'install' (no
    ttyd: the page says how to install it; C25), or 'feed' (Windows: the feed and the session link only)."""
    import shutil
    from agent_runner import plat
    if plat.WINDOWS:
        return 'feed'
    return 'ttyd' if shutil.which('ttyd') else 'install'


def _no_pane(name: str) -> dict:
    return {'ok': False, 'code': 1, 'out': f'{name} is not up, so nothing can be typed into it: its feed and '
                                           f'session link still work.', 'argv': []}


KEY_BYTES = {'Enter': b'\r', 'Escape': b'\x1b', 'Tab': b'\t', 'BSpace': b'\x7f', 'Up': b'\x1b[A',
             'Down': b'\x1b[B', 'Right': b'\x1b[C', 'Left': b'\x1b[D', 'C-c': b'\x03'}  # F89: KEYS as a terminal sends them


def hidden_inbox(name: str) -> Path | None:
    """F89: the FIFO a hidden session's shim reads (`<notes>/controlN.in` for cN, `<notes>/slotN.in` for sN),
    found from its `.live` marker; None when it has none (not up, not a session name)."""
    m = re.fullmatch(r'([cs])(\d+)', name)
    if not m:
        return None
    try:
        marker = S.C.notes(f'{"control" if m[1] == "c" else "slot"}{m[2]}.live')
    except Exception:  # noqa: BLE001 - no notes dir
        return None
    return marker.with_suffix('.in') if marker.is_file() else None


def _no_typing(name: str) -> dict:
    return {'ok': False, 'code': 1, 'out': f'{name} runs hidden in a console that cannot be typed into (Windows): '
                                           f'its feed and session link still work.', 'argv': []}


def _hidden_keys(session: str, inbox: Path, text: str, key: str) -> dict:
    """F89: `keys` for a hidden session: `text` then `key` written raw to its shim's FIFO."""
    from agent_runner import plat, slots
    if plat.WINDOWS:
        return _no_typing(session)
    if not slots.send_fifo_raw(inbox, text.encode('utf-8') + KEY_BYTES.get(key, b'')):
        return {'ok': False, 'code': 1, 'out': f'could not type into {session} (nothing reads {inbox.name})',
                'argv': []}
    return {'ok': True, 'code': 0, 'out': f'typed into {session}', 'argv': []}


def keys(session: str, text: str = '', key: str = '') -> dict:
    """F74: `text` typed into `session` (c6, s2) as is, then the named `key` (one of KEYS: Enter, Escape, …) if
    given; `interrupt` sends Escape through it (C25: no longer an action). F89: both are written raw to its
    hidden shim's FIFO (`hidden_inbox`)."""
    if key and key not in KEYS:
        return {'ok': False, 'code': 2, 'out': f'keys: key is one of {", ".join(KEYS)}, not {key!r}', 'argv': []}
    if inbox := hidden_inbox(session):
        return _hidden_keys(session, inbox, text, key)
    return _no_pane(session)


def interrupt(session: str = 'c1') -> dict:
    """F74: interrupt `session` (Escape typed into it), as a person pressing Esc in it would."""
    r = keys(session, key='Escape')
    return {**r, 'out': f'interrupted {session}'} if r['ok'] else r


def send(name: str, text: str) -> dict:
    """F74: the person's words to session `name` as they typed them: c1 as `chat` hands them on (`SEND`), any
    other control session or slot typed in through its hidden shim's FIFO as a bracketed paste and Enter
    (`slots.send_fifo`; F89)."""
    if name == 'c1':
        return SEND[0](text)
    from agent_runner import plat, slots
    if inbox := hidden_inbox(name):
        if plat.WINDOWS:
            return _no_typing(name)
        ok = slots.send_fifo(inbox, text)
    else:
        return _no_pane(name)
    return {'ok': ok, 'code': 0 if ok else 1, 'out': f'sent to {name}' if ok else f'could not type into {name}',
            'argv': []}


def chat_to(text: str, to: str = 'c1') -> dict:
    """F74: the chat box of any control session: `to` (c1, c6) gets `text`."""
    return send(to, text)


def new_control(ask: str = '', wait: bool = True) -> dict:
    """F74: start a new control session (`control --new`, `ask` its first message): the result's 'link' is its
    claude.ai/code link ('' when it printed none), 'name' its cN ('' when it said none). F112: `wait` False
    (`--no-wait`) returns once it starts, before its link is known."""
    r = call(['control', '--new', *([] if wait else ['--no-wait']), *(['--ask', ask] if ask else [])])
    m = LINK.search(r['out'] or '')
    n = re.search(r'\bcontrol (\d+) ', r['out'] or '')
    return {**r, 'link': m.group(0).rstrip('.,)') if m else '', 'name': f'c{n.group(1)}' if n else ''}


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


def concept_chat(cid: str, title: str = '', url: str = '', copy: str = '', wait: bool = True) -> dict:
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
    return new_control(concept_chat_text(row), wait)  # F137: the run page starts it without waiting


def quick_ask(key: str, wait: bool = True) -> dict:
    """F74: one of the Status chat's quick asks (QUICK_ASKS: since, yesterday, needs, usage). B139: it starts a
    new control session with the ask as its first message (`new_control`, `wait` as there), not c1."""
    text = next((t for k, _, t in QUICK_ASKS if k == key), '')
    if not text:
        return {'ok': False, 'code': 2, 'out': f'quick_ask: key is one of {", ".join(k for k, _, _ in QUICK_ASKS)}, '
                                               f'not {key!r}', 'argv': []}
    return new_control(text, wait)


ACTIONS.update({'chat_to': chat_to, 'interrupt': interrupt, 'new_control': new_control, 'quick_ask': quick_ask})
ACTIONS['concept_chat'] = concept_chat  # F86


def delete_chats(names: list | None = None) -> dict:
    """F118: the run page's chat delete: end each named control session (`control.end_control`) so it drops off
    the chat list. c1, the Project chat, is never deleted: a list naming it is refused whole, nothing ended."""
    names = [n for n in (names or []) if isinstance(n, str)]
    if not names:
        return {'ok': False, 'code': 2, 'out': 'delete_chats: no chats named', 'argv': []}
    bad = [n for n in names if not re.fullmatch(r'c\d+', n)]
    if bad:
        return {'ok': False, 'code': 2, 'out': f'delete_chats: not a chat: {", ".join(bad)}', 'argv': []}
    if any(int(n[1:]) <= 1 for n in names):
        return {'ok': False, 'code': 2, 'out': 'The Project chat (c1) cannot be deleted.', 'argv': []}
    from agent_runner import control as K
    gone = [n for n in names if K.end_control(int(n[1:]), 'deleted from the run page')]
    left = [n for n in names if n not in gone]
    out = f'deleted {", ".join(gone)}' if gone else 'nothing deleted'
    return {'ok': True, 'code': 0, 'out': out + (f' ({", ".join(left)} already gone)' if left else ''),
            'deleted': gone, 'argv': []}


ACTIONS['delete_chats'] = delete_chats
