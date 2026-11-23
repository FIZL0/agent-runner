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
    release_row  F131: the release as one row at the queue's end (`release_row`): the V task (also moved last
              in `queue`, with `release`: this row), or a placeholder while `[run] auto_release` counts; None
    quick_asks  the Status chat's quick asks sent to c1: key, label, text
    terminal_mode  how a session's terminal shows: 'ttyd', 'install' (no ttyd yet), 'feed' (Windows)
    run       paused, stopping, forced, power, and `state`: the state pill's words (F124: `run_state`)
    usage     F124: the account's usage, [{'name': 'session'|'week', 'pct'}]
    lately    F124: what landed lately, newest first, [{'at', 'text'}], the words `status` lists under "lately"
    fixups    F124: what the Fix up controls would work on (`fixups`): {'resume', 'unclaim', 'wip': [{'id', 'label'}]}
    chat_quiet  F128: `[ui] chat_quiet` in seconds (0 off)
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
import os
import re
import subprocess as sp
import threading
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


def release_row(ls: list[str], st: dict | None = None, landed: int | None = None) -> dict | None:
    """F131: the release as one row, pinned at the end of the queue, the same words on the run page, the TUI
    and `status` (`status.release_line`). A release task (kind V) open in TODO.md's lines `ls`: that task, with
    `words` 'waits for 24 open ahead', 'ready', 'blocked', or 'building' while a slot of STATE `st` runs it or
    it merges. None queued and `[run] auto_release` on: a placeholder (`placeholder` True, `id` '') 'Next
    release · auto at 10 landed: 6/10 · when the run goes idle' (`landed`: tasks landed since the last release,
    `autorelease.landed_since_release` when None). Else None. `text` is the whole row: 'V5 Release · building'."""
    st = st or {}
    for section, box, tid, rest, i in P.iter_tasks(ls):
        if box not in ' ~' or not P.release(tid) or section.startswith(P.SKIPPED) or P._shelved(ls, i):
            continue
        live, note = P.open_ids(ls), ''
        waits = P.WAITS.findall(' '.join(P._item_block(ls, i))) if box == '~' else []
        if tid in (st.get('running') or {}).values() or tid in (st.get('merging') or []):
            words = 'building'
        elif box == '~' and not waits:
            words = 'blocked'
        else:
            if P._waits_all(ls, i):
                held = [t for t in P.before_all(ls, i) if t in live and t != tid]
                note = P.not_waiting([t for t in P.on_person_before(ls, i) if t != tid])  # B101
                if P.ALL in P.fields(ls[i]).get('after', []):  # B107: a task taken by hand lands after it
                    from agent_runner.sched import taken
                    from agent_runner.status import taken_note
                    away = set(taken())
                    note += taken_note([t for t in held if t in away])
                    held = [t for t in held if t not in away]
            else:
                ids = [t.strip() for t in waits[-1].split(',')] if waits else P.waits_on(ls, i)
                held = [t for t in dict.fromkeys(ids) if t in live and t != tid]
            words = f'waits for {len(held)} open ahead' if held else 'ready'
        title = after_name(re.sub(r'^\s*(?:\(follow-up, \w+\)\s*)?\(alone\)\s*', '', rest))  # F130's tag
        return {'id': tid, 'title': title, 'words': words, 'placeholder': False,
                'text': f'{tid} {title} · {words}', 'note': note}
    from agent_runner.autorelease import auto_release_of
    every, idle = auto_release_of(S.C.run.get('auto_release', False) if S.C else False)
    if not (every or idle) or P.open_release(ls):  # a shelved or Parked release: none is queued by itself
        return None
    if every and landed is None:
        landed = landed_count()
    count = '' if landed is None else f': {landed}/{every}'
    words = ' · '.join(([f'auto at {every} landed{count}'] if every else []) +
                       (['when the run goes idle'] if idle else []))
    return {'id': '', 'title': 'Next release', 'words': words, 'placeholder': True,
            'text': f'Next release · {words}', 'note': ''}


LANDED_COUNT: list = [None, 0.0, None]  # what the last count was of, when (monotonic), and the count
LANDED_FOR = 30.0  # seconds a count holds while events.jsonl is unchanged (a version tag can still arrive)


def landed_count() -> int | None:
    """F131: how many tasks landed since the last release, counted again after a new event or `LANDED_FOR`
    seconds (a page reads a snapshot every few seconds; the count runs git). None: it could not be counted."""
    from agent_runner.autorelease import landed_since_release
    f = S.C.notes('events.jsonl')
    try:
        s = f.stat()
        mark = (str(f), s.st_size, s.st_mtime)
    except OSError:
        mark = (str(f), None, None)
    if mark != LANDED_COUNT[0] or time.monotonic() - LANDED_COUNT[1] > LANDED_FOR:
        try:
            n = len(landed_since_release(S.default_branch()))
        except (Exception, SystemExit):  # noqa: BLE001 - a git hiccup costs the count, not the row
            n = None
        LANDED_COUNT[:] = [mark, time.monotonic(), n]
    return LANDED_COUNT[2]


def pin_release(queue: list[dict], row: dict | None) -> list[dict]:
    """F131: the queue with the release task `row` stands for moved to its end, carrying `release`: the row,
    whose words the page and the TUI show. A placeholder row is not a task: it is not added."""
    if not row or row.get('placeholder'):
        return queue
    return [q for q in queue if q['id'] != row['id']] + [dict(q, release=row) for q in queue if q['id'] == row['id']]


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
        if label == 'PITCH':  # F98
            from agent_runner import pitch
            xs = [{'id': x['id'], 'title': x['title']} for x in pitch.changes_of(tid, state='waiting')]
            needs[-1].update(copy=concept_copy(tid), changes=xs, options=['Approve'] + [
                f'Not {w}: {how}' for w in ['this'] + ([x['id'] for x in xs] if len(xs) > 1 else [])
                for how in ('reopen', 'drop')])
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


_CHAT_STATE: dict[str, tuple[tuple, dict]] = {}  # transcript -> (its size and time, `control_state` of it)


def chat_state(n: int, sid: str) -> dict:
    """F128: control session `n`'s state for its row: {'link', 'last' (who spoke last), 'at' (its last activity, epoch
    s, 0 unknown), 'needs_reply' (Claude spoke last and its message has an open question), 'renamed', 'title' (the
    person's own name for it)}. Read again only when its transcript changed."""
    out = {'link': '', 'last': '', 'at': 0, 'needs_reply': False, 'renamed': False, 'title': ''}
    try:
        from agent_runner import control as K
        from agent_runner.control_names import person_name
        from agent_runner.slots import entries, transcript
        path = str(sid and transcript(sid) or '')
        st: dict = {}
        if path:
            f = Path(path).stat()
            mark = (f.st_size, f.st_mtime_ns)
            if _CHAT_STATE.get(path, (None,))[0] != mark:
                _CHAT_STATE[path] = (mark, K.control_state(entries(sid, skip_bad=True)))
            st = _CHAT_STATE[path][1]
        name, renamed = person_name(n, st.get('title') or ''), K.control_renamed(st, n)
        out.update(link=K.control_link(st.get('bridge') or ''), last=st.get('last') or '', at=int(st.get('at') or 0),
                   renamed=renamed, title=name or (st.get('title') or '' if renamed else ''))
        if st.get('last') == 'claude':
            out['needs_reply'] = bool(K.decide_question(st['text']) or K.open_question(st['text'], K.control_cfg()['open']))
    except Exception:  # noqa: BLE001 - a nicety of the row: a missing transcript or backend leaves it plain
        pass
    return out


def chat_quiet() -> float:
    """F128: `[ui] chat_quiet` in seconds: how long after its last activity a chat that needs no reply is grayed."""
    from agent_runner.control import duration
    try:
        return duration(S.C.raw['ui'].get('chat_quiet', '6h'), 21600.0)
    except (AttributeError, KeyError, TypeError):
        return 21600.0


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
            'state': 'live' if pid else 'off', 'files': [], 'terminal': '', **chat_row(1, sid)}


def chat_row(n: int, sid: str) -> dict:
    """F128: what a control session's row adds from its transcript (`chat_state`); its title only when the person
    gave it one (F129)."""
    st = chat_state(n, sid)
    if not st['title']:
        st.pop('title')
    return st


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
        c1['title'], c1['state'] = c1['title'] if c1.get('renamed') else windows[1], 'live'
    if links and 'c1' in links:
        c1['link'] = links['c1']
    out = [c1]
    for n in sorted(k for k in windows if k > 1):
        try:
            sid = S.C.notes(f'control{n}.pid').read_text(encoding='utf-8').strip().partition(' ')[2]
        except Exception:  # noqa: BLE001 - no pid file (or no notes dir): a plain row
            sid = ''
        row = {'name': f'c{n}', 'task': '', 'title': windows[n], 'minutes': None, 'state': 'live', 'files': [],
               'terminal': '', **chat_row(n, sid)}
        if links is not None:
            row['link'] = links.get(f'c{n}', '')
        out.append(row)
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


def unpushed_line() -> str:
    """F98: how many landed changes wait for the person's approval to be pushed; '' for none."""
    try:
        from agent_runner import pitch
        return pitch.waiting_line()
    except Exception:  # noqa: BLE001 - costs the line, not the snapshot
        return ''


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
    if unpushed := unpushed_line():
        out.append(unpushed)
    out += [l for l in progress.splitlines() if l]
    use = st.get('usage') or {}
    if parts := [f'{w} {use[k]:.0f}%' for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
                 if use.get(k) is not None]:
        out.append('usage: ' + ', '.join(parts))
    return out


def run_state(up: bool, st: dict) -> str:
    """F124: the run's state in a word or two, the state pill's on every page of the run app."""
    return ('Not up' if not up else 'Stopping' if st.get('stopping') else 'Paused' if st.get('paused') else
            'Caps forced' if st.get('forced') else 'Running')


def usage_rows(st: dict) -> list[dict]:
    use = st.get('usage') or {}
    return [{'name': w, 'pct': round(use[k])} for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
            if isinstance(use.get(k), (int, float))]


_LATELY: list = [None, []]  # the event log's path, size and time, and what lately() read from it


def lately(titles: dict[str, str], n: int = 6) -> list[dict]:
    """F124: what landed lately, newest first: `status`'s "lately" lines, from the event log."""
    from agent_runner.status import events_file, lately_events, read_events
    try:
        f = events_file().stat()
        mark = (str(events_file()), f.st_size, f.st_mtime_ns)
    except (OSError, AttributeError):
        mark = None
    if mark is None or _LATELY[0] != mark:
        try:
            _LATELY[:] = [mark, [{'at': m[0], 'text': m[2]}
                                 for m in lately_events(read_events()[-2000:], titles)[-n:]][::-1]]
        except Exception:  # noqa: BLE001 - no event log yet
            return []
    return _LATELY[1]


FIXUPS: list = [0.0, '', {}]  # when `fixups` last looked (monotonic), at which root, and what it found
FIXUPS_FOR = 20.0  # s: it runs git and reads the slot logs, and a page reads a snapshot every few seconds


def fixups(st: dict, ls: list[str]) -> dict:
    """F124: what the Fix up controls would work on, each [{'id', 'label'}]: `resume`, open tasks whose session was
    cut off with its work kept (a wip/<ID> branch and a session to resume) that nothing runs; `unclaim`, other runs'
    stale claims; `wip`, main-checkout edits a merge moved aside."""
    if FIXUPS[1] == str(S.ROOT) and time.monotonic() - FIXUPS[0] < FIXUPS_FOR:
        return FIXUPS[2]
    out: dict[str, list] = {'resume': [], 'unclaim': [], 'wip': []}
    titles = {tid: P.short_title(rest, 60) for _, box, tid, rest, _ in P.iter_tasks(ls) if box == ' '}
    try:
        from agent_runner import plansync
        from agent_runner.land import WIP, wip_main_info
        from agent_runner.slots import transcript
        from agent_runner.watch import last_session
        for name, _, files in wip_main_info():
            out['wip'].append({'id': name.removeprefix('wip/'),
                               'label': f'{name.removeprefix("wip/main-checkout-")} · {files} file{"s" * (files != 1)}'})
        busy = set((st.get('running') or {}).values()) | set(st.get('merging') or []) | \
            {q[0] for q in S.queued().values()}
        refs = S.git('for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/').stdout.split()
        for tid in dict.fromkeys(m[1] for x in refs if (m := WIP.fullmatch(x))):
            if tid in titles and tid not in busy and (last := last_session(tid)) and transcript(last[1]):
                out['resume'].append({'id': tid, 'label': titles[tid]})
        me = plansync.owner(S.C)
        for tid, cl in sorted(plansync.claims(S.C).items()):
            if cl.owner != me and plansync.stale(cl):
                out['unclaim'].append({'id': tid, 'label': plansync.label(cl)})
    except Exception:  # noqa: BLE001 - a git or plan hiccup costs the Fix up items, not the snapshot
        pass
    FIXUPS[:] = [time.monotonic(), str(S.ROOT), out]
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
    row = release_row(ls, st)  # F131: the release, one row at the queue's end
    release = release_line(ls, st, row)
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
            'queue': pin_release(queue_rows(ls, st, now), row), 'release_row': row,
            'needs': needs, 'concepts': concepts, 'log': log_tail(log_n), 'release': release,
            'quick_asks': quick_asks(), 'terminal_mode': terminal_mode(), 'controls': controls(),
            'run': {'paused': bool(up and st.get('paused')), 'stopping': bool(up and st.get('stopping')),
                    'forced': bool(up and st.get('forced')), 'power': str(st.get('power') or '') if up else '',
                    'state': run_state(up, st)},  # F124
            'unpushed': unpushed_line(),  # F98
            'usage': usage_rows(st), 'lately': lately(titles), 'fixups': fixups(st, ls), 'chat_quiet': chat_quiet(),
            'version': str(st.get('version') or '')}  # F90: the run's version ('' from an older run)


def snapshot_json(**kw) -> str:
    return json.dumps(snapshot(**kw), ensure_ascii=False)


# --- the actions ----------------------------------------------------------------------------------------------

def _run(argv: list[str]) -> tuple[int, str]:
    """Run the runner with `argv` in the main checkout: (exit code, what it printed)."""
    env = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER_CONTROL'}  # F160: the person's, not the session's
    if argv[:1] and argv[0] in ('plan', 'pitch', 'sheet'):  # that started the run or the TUI
        env['AGENT_RUNNER_BY'] = 'the person in the run app'
    r = sp.run(runner_cmd() + argv, cwd=S.ROOT, env=env, capture_output=True, text=True, encoding='utf-8',
               errors='replace')
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
    return call(['control', '--new', '--ask', text, '--no-feed'])


SEND = [to_c1]  # how chat and answers reach c1; a test swaps it


def chat(text: str) -> dict:
    """The page's chat box: the person's words to c1, as they typed them."""
    return SEND[0](text)


SHEET_GO = ('go', 'recommended')  # a pick sheet's reply for its recommended picks
CHECK_FAILED = 'No: the check failed'  # B138: what a CONFIRM's No reopens the task with


def need_label(tid: str) -> str:
    """B138: the label of what `tid` asks (CONFIRM, DECIDE, BLOCKED, STUCK, CONCEPT); '' when nothing needs you
    about it."""
    from agent_runner import pitch
    if pitch.PITCH_ID.fullmatch(tid or ''):  # F98
        return pitch.LABEL if any(r[1] == tid for r in pitch.rows()) else ''
    try:
        return P._ask(tid, S.C.todo)[0]
    except (SystemExit, OSError, AttributeError):
        return ''


def answer_argv(tid: str, text: str, button: bool = False) -> tuple[list[str], str]:
    """B138: the runner command that settles a Needs you reply at once, and what to say once it did; ([], '')
    when the reply is c1's to read. A button's Yes (or a pick, or done) is `plan confirm ID "<reply>"`, a
    CONFIRM's No is `plan change ID "No: the check failed"`; a pick sheet's go or Send line is `sheet ID
    --go|--picks`; a concept's option button is `plan approve ID "<option>"` (B149). Free words typed in the
    reply box are c1's."""
    said, label = (text or '').strip(), need_label(tid)
    if label == 'PITCH' and button:  # F98
        if said.lower() == 'approve':
            return ['pitch', 'approve', tid], f'{tid} approved'
        if m := re.fullmatch(r'not (\w+): (reopen|drop)', said, re.I):
            one, how = m[1], m[2].lower()
            argv = ([] if how == 'reopen' else ['--drop', 'all']) if one.lower() == 'this' else [f'--{how}', one]
            return ['pitch', 'no', tid, *argv], f'{tid}: the run undoes it'
        return [], ''
    if label == 'DECIDE' and button:
        from agent_runner.brief import has_sheet
        if has_sheet(tid) and said.lower() in SHEET_GO:
            return ['sheet', tid, '--go'], f'{tid} answered with the recommended picks'
        if has_sheet(tid) and said.startswith(f'{tid} picks:'):
            return ['sheet', tid, '--picks', said], f'{tid} answered with your picks'
    if label == 'CONCEPT' and button and said:  # B149: a concept's option button approves that option itself
        return ['plan', 'approve', tid, said], f'{tid} approved ({said}): a run starts its build'
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
            if argv[0] == 'pitch':
                done = r['out'].splitlines()[0] if r['out'] else done  # F98: pushed, or what it waits for
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

# F124: `group` is the More… sheet's group ('' on the Run card itself), 'fix' where a Fix up control's choices come
# from (the snapshot's `fixups`; it shows only while there are some, and '{id}' is the one picked). A control with
# `up` False starts a run, so it shows only while none is up.
STOP_NOW_ASK = ('Stop now ends every agent session at once (each resumes in the next run); '
                'the merges under way finish. Stop now?')
SUSPEND_ASK = ('This computer suspends once the run stops or goes idle, and its sessions stop with it. Asked again, it '
               'is taken back. Suspend?')
SHUTDOWN_ASK = ('This computer shuts down once the run stops or goes idle, and every session on it ends. Asked again, it '
                'is taken back. Shut down?')
UPGRADE_ASK = 'The run restarts on the new version between merges. Running tasks keep going. Upgrade?'
RESTART_ASK = 'The run restarts between merges and reads its settings again. Running tasks keep going. Restart?'
WIP_DROP_ASK = 'These edits are deleted here and on the remote, and cannot be brought back. Drop them?'
RUN_CONTROLS = (
    {'key': 'slot_add', 'label': 'Slot +1', 'argv': ('slots', '+1'), 'tui': '+', 'where': 'run'},
    {'key': 'slot_remove', 'label': 'Slot -1', 'argv': ('slots', '-1'), 'tui': '-', 'where': 'run'},
    {'key': 'slots_set', 'label': 'Set slots', 'argv': ('slots', '{n}'), 'tui': '=', 'where': 'run', 'group': 'Run'},
    {'key': 'pause', 'label': 'Pause', 'argv': ('pause',), 'tui': 'P', 'where': 'run'},
    {'key': 'go_on', 'label': 'Go on', 'argv': ('pause', '--off'), 'tui': 'G', 'where': 'run'},
    {'key': 'force', 'label': 'Force past the caps', 'argv': ('force',), 'tui': 'F', 'where': 'run', 'group': 'Run'},
    {'key': 'caps_on', 'label': 'Caps back on', 'argv': ('force', '--off'), 'tui': 'C', 'where': 'run',
     'group': 'Run'},
    {'key': 'stop', 'label': 'Stop (running tasks finish)', 'argv': ('stop',), 'tui': 'S', 'where': 'run'},
    {'key': 'stop_now', 'label': 'Stop now', 'argv': ('stop', '--force'), 'tui': 'X', 'where': 'run',
     'group': 'Stop', 'confirm': STOP_NOW_ASK},
    {'key': 'stop_undo', 'label': 'Take the stop back', 'argv': ('stop', '--undo'), 'tui': 'U', 'where': 'run'},
    # C26: the run's u, z and x keys, posted as the run view posts them (`key`: they take themselves back when
    # sent again, as typed ones do)
    {'key': 'suspend', 'label': 'Suspend once stopped', 'argv': ('key', 'z'), 'tui': 'Z', 'where': 'run',
     'group': 'Stop', 'confirm': SUSPEND_ASK},
    {'key': 'shutdown', 'label': 'Shut down once stopped', 'argv': ('key', 'x'), 'tui': 'B', 'where': 'run',
     'group': 'Stop', 'confirm': SHUTDOWN_ASK},
    {'key': 'upgrade', 'label': 'Upgrade agent-runner', 'argv': ('key', 'u'), 'tui': 'V', 'where': 'run',
     'group': 'Run', 'confirm': UPGRADE_ASK},
    {'key': 'restart', 'label': 'Restart the run', 'argv': ('key', 'restart'), 'tui': 'Y', 'where': 'run',
     'group': 'Run', 'confirm': RESTART_ASK},
    {'key': 'start', 'label': 'Start the run', 'argv': (), 'tui': 'T', 'where': 'run', 'up': False},
    {'key': 'resume', 'label': 'Resume a cut-off task', 'argv': ('resume', '{id}'), 'tui': 'r', 'where': 'run',
     'group': 'Fix up', 'fix': 'resume'},
    {'key': 'unclaim', 'label': 'Release stale claims', 'argv': ('plan', 'unclaim', '{id}'), 'tui': 'L',
     'where': 'run', 'group': 'Fix up', 'fix': 'unclaim', 'each': True},
    {'key': 'wip_show', 'label': 'Show moved-aside edits', 'argv': ('wip', 'show', '{id}'), 'tui': 'W',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip'},
    {'key': 'wip_restore', 'label': 'Restore moved-aside edits', 'argv': ('wip', 'restore', '{id}'), 'tui': 'E',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip'},
    {'key': 'wip_drop', 'label': 'Drop moved-aside edits', 'argv': ('wip', 'drop', '{id}'), 'tui': 'O',
     'where': 'run', 'group': 'Fix up', 'fix': 'wip', 'confirm': WIP_DROP_ASK},
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
    from agent_runner import plat

    def needs(c):
        if c.get('fix'):
            return 'pick'
        words = c.get('argv') or (c.get('ask') or '',)
        return 'n' if any('{n}' in w for w in words) else 'id' if any('{id}' in w for w in words) else ''
    return [{'key': c['key'], 'label': c['label'], 'tui': c['tui'], 'where': c['where'], 'needs': needs(c),
             'confirm': c.get('confirm', ''), 'group': c.get('group', ''), 'fix': c.get('fix', ''),
             'each': bool(c.get('each')), 'up': c.get('up', True)} for c in RUN_CONTROLS
            if not (plat.WINDOWS and c['key'] == 'restart')]  # no re-exec there


def control_argv(key: str, n='', tid: str = '', why: str = '') -> list[str]:
    """The runner command control `key` runs, filled in; ValueError says what is missing or wrong."""
    c = run_control_of(key)
    if c is None:
        raise ValueError(f'no such run control: {key!r}')
    words = list(c.get('argv') or ())
    n = str(n).strip()
    if any('{n}' in w for w in words) and not (SLOT_COUNT.fullmatch(n) and (key != 'slots_set' or n.isdigit())):
        raise ValueError(f'{key}: the slot count is a number, not {n!r}')
    if c.get('fix') == 'wip':
        if not re.fullmatch(r'main-checkout-[\w.-]+', tid or ''):
            raise ValueError(f'{key}: which moved-aside edits? not {tid!r}')
    elif any('{id}' in w for w in words + [c.get('ask') or '']) and not TASK_ID.fullmatch(tid or ''):
        raise ValueError(f'{key}: a task id (F82), not {tid!r}')
    return [w.replace('{n}', n).replace('{id}', tid).replace('{why}', why or TASK_DROP_WHY) for w in words]


def run_control(key: str, n='', tid: str = '', why: str = '', confirm: bool = False, wait: bool = True) -> dict:
    """F82: run one run control (RUN_CONTROLS) for the web page or agent-runner ui. One with a confirm question
    runs only with `confirm` true; without it the result is not ok and carries the question as 'confirm'. B139:
    one with an 'ask' starts a new control session with it (`new_control`, `wait` as there), not c1."""
    c = run_control_of(key)
    if c and c.get('each') and not tid:  # every one there is: 'Release stale claims (2)'
        ids = [x['id'] for x in fixups(_state(S.run_up()), P.lines(S.C.todo)).get(c['fix']) or []]
        if not ids:
            return {'ok': False, 'code': 1, 'out': f'{c["label"]}: there is nothing to do', 'argv': []}
        rs = [run_control(key, tid=i) for i in ids]
        bad = next((r for r in rs if not r['ok']), None)
        return bad or {**rs[-1], 'out': ', '.join(r['out'] for r in rs)}
    try:
        argv = control_argv(key, n, tid, why)
    except ValueError as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if c.get('confirm') and confirm is not True:
        return {'ok': False, 'code': 3, 'out': c['confirm'], 'confirm': c['confirm'], 'argv': argv}
    if c.get('ask'):
        return new_control(c['ask'].replace('{id}', tid), wait)
    r = call(argv)
    FIXUPS[0] = float('-inf')  # what there is to fix is looked up anew
    return r


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
# The feed is a session's transcript (Claude Code's JSONL, which the harness loop writes too)
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
    result, cut to OUT_LINES lines). Thinking, meta, compact summaries and subagents' entries are left out.
    B134: an entry has 'id' (its transcript entry's uuid and block), when the transcript gives one: it stays the same
    in every later feed, where an index moves once the feed is capped.
    B154: a message queued while the session worked (`feed.queued_message`) is a 'you' too, and a 'you' has 'at',
    when the transcript got it (epoch s), if the entry says."""
    from agent_runner.control import RUNNER_TURN, _stamp
    from agent_runner.feed import queued_message
    out: list[dict] = []

    def eid(d: dict, j: int) -> dict:
        return {'id': f'{d["uuid"]}:{j}'} if isinstance(d.get('uuid'), str) and d['uuid'] else {}
    for d in rows:
        d = queued_message(d) or d
        if not isinstance(d, dict) or d.get('type') not in ('user', 'assistant') or d.get('isSidechain') \
                or d.get('isMeta') or d.get('isCompactSummary'):
            continue
        m = d.get('message') or {}
        c = m.get('content')
        if d['type'] == 'assistant':
            for j, b in enumerate(c if isinstance(c, list) else
                                  [{'type': 'text', 'text': c}] if isinstance(c, str) else []):
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text' and str(b.get('text') or '').strip():
                    out.append({'kind': 'say', 'text': b['text'].strip(), **eid(d, j)})
                elif b.get('type') == 'tool_use':
                    out.append({'kind': 'tool', 'text': tool_words(b.get('name', 'tool'), b.get('input')), **eid(d, j)})
            continue
        for j, b in enumerate([{'type': 'text', 'text': c}] if isinstance(c, str) else c if isinstance(c, list) else []):
            if not isinstance(b, dict):
                continue
            if b.get('type') == 'tool_result':
                out.append({'kind': 'out', 'text': _clip(_blocks_text(b.get('content')), OUT_LINES, OUT_CHARS),
                            **eid(d, j)})
            elif b.get('type') == 'text' and (t := str(b.get('text') or '').strip()):
                if t.startswith(INTERRUPTED):
                    out.append({'kind': 'out', 'text': 'interrupted', **eid(d, j)})
                elif not t.startswith(RUNNER_TURN) and not t.startswith('<task-notification>'):
                    at = _stamp(d)
                    out.append({'kind': 'you', 'text': t, **({'at': at} if at else {}), **eid(d, j)})
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


_PROMPTS: dict[str, tuple[int, int, list]] = {}  # transcript -> (`prompt_before`'s start, how far it read, the prompt)


def prompt_before(path: str, start: int) -> list[dict]:
    """B154: the person's latest prompt in the part of transcript `path` that a tail read from byte `start` leaves
    out, as feed entries ([] for none). Each poll reads only what the tail has left behind since the last one."""
    was, at, last = _PROMPTS.get(path, (0, 0, []))
    if was > start:  # a transcript written anew
        at, last = 0, []
    try:
        with open(path, 'rb') as f:
            f.seek(at)
            while at <= start and (line := f.readline()).endswith(b'\n'):
                at += len(line)
                if b'"user"' in line or b'queued_command' in line:
                    try:
                        last = [e for e in feed_entries([json.loads(line)]) if e['kind'] == 'you'][-1:] or last
                    except ValueError:
                        pass
    except OSError:
        return []
    _PROMPTS[path] = (start, at, last)
    return last


def feed(name: str, limit: int = FEED_MAX) -> dict:
    """F74: session `name`'s feed (`feed_entries` of its transcript's tail), newest last: {'ok', 'name',
    'entries', 'more' (older entries left out), 'link' (its claude.ai/code session, '' for none)}. B154: the
    person's latest prompt is always in it, first when the turn since is longer than the feed."""
    path = transcript_of(name)
    rows = feed_entries(tail_rows(path)) if path else []
    sid = session_sid(name)
    try:
        start = max(Path(path).stat().st_size - FEED_BYTES, 0) if path else 0
    except OSError:
        start = 0
    cut = start > 0
    kept = rows[-limit:] if limit else rows
    if not any(e['kind'] == 'you' for e in kept):
        kept = ([e for e in rows if e['kind'] == 'you'][-1:] or (prompt_before(path, start) if cut else [])) + kept
    return {'ok': bool(path), 'name': name, 'entries': kept,
            'more': cut or len(rows) > limit > 0, 'link': _bridge_link(sid) if sid else '',
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
    if plat.WINDOWS and not inbox.exists():
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
        if plat.WINDOWS and not inbox.exists():
            return _no_typing(name)
        ok = slots.send_fifo(inbox, text)
    else:
        return _no_pane(name)
    return {'ok': ok, 'code': 0 if ok else 1, 'out': f'sent to {name}' if ok else f'could not type into {name}',
            'argv': []}


def chat_to(text: str, to: str = 'c1') -> dict:
    """F74: the chat box of any control session: `to` (c1, c6) gets `text`. B154: 'at' is when it was typed, and
    'name' the new control session that took it when c1 was not up."""
    at = time.time()
    r = {**send(to, text), 'at': at}
    n = re.search(r'\bcontrol (\d+) ', r.get('out') or '') if to == 'c1' and r['ok'] else None
    return {**r, 'name': f'c{n.group(1)}'} if n else r


def new_control(ask: str = '', wait: bool = True) -> dict:
    """F74: start a new control session (`control --new`, `ask` its first message): the result's 'link' is its
    claude.ai/code link ('' when it printed none), 'name' its cN ('' when it said none). F112: `wait` False
    (`--no-wait`) returns once it starts, before its link is known. B154: 'ask' and 'at' (when it was called) let the
    page keep the ask shown until the feed has it."""
    at = time.time()
    r = call(['control', '--new', *([] if wait else ['--no-wait']), *(['--ask', ask, '--no-feed'] if ask else [])])
    m = LINK.search(r['out'] or '')
    n = re.search(r'\bcontrol (\d+) ', r['out'] or '')
    return {**r, 'link': m.group(0).rstrip('.,)') if m else '', 'name': f'c{n.group(1)}' if n else '',
            'ask': ask, 'at': at}


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


# --- F83: the combined run app rework: Needs you Drop and Chat, Rename, Settings, a task's whole text ----------

NEED_DROP_WHY = 'dropped from Needs you'  # F110


def need_drop(tid: str, confirm: bool = False) -> dict:
    """F110: Drop on a Needs you item: `plan drop ID`, after a confirm (without `confirm` the result is not ok and
    carries the question, as a run control's); an ok result carries 'gone', so the item leaves the list at once."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'code': 2, 'out': f'need_drop: a task id (F83), not {tid!r}', 'argv': []}
    ask = f'Drop {tid}? It leaves the plan, and its work is not done.'
    if confirm is not True:
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': []}
    r = drop(tid, NEED_DROP_WHY)
    return {**r, 'said': f'{tid} dropped', 'gone': tid} if r['ok'] else r


def pitch_no(pid: str, how: str = 'reopen', tid: str = '', confirm: bool = False) -> dict:
    """F98: Not this on a pitch, for all of it or the one change `tid`: the run undoes it here and reopens or drops
    its task. After a confirm, as `need_drop`."""
    from agent_runner import pitch
    if not pitch.PITCH_ID.fullmatch(pid or '') or how not in ('reopen', 'drop') or \
            (tid and not P.TASK_ID.fullmatch(tid)):
        return {'ok': False, 'code': 2, 'out': f'pitch_no: a pitch, reopen or drop, and a task id; not {pid!r} '
                                               f'{how!r} {tid!r}', 'argv': []}
    ask = f'Undo {tid or "all of it"} here and {how} {"its task" if tid else "the tasks"}?'
    if confirm is not True:
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': []}
    r = call(['pitch', 'no', pid, f'--{how}', tid] if tid else
             ['pitch', 'no', pid] + (['--drop', 'all'] if how == 'drop' else []))
    if r['ok']:
        r['said'] = f'{tid or pid}: the run undoes it'
        if not pitch.changes_of(pid, state='waiting'):  # the rest of it still waits otherwise
            r['gone'] = pid
    return r


def need_options(row: dict) -> list[str]:
    """F143: the possible answers to a Needs you row, as the pages offer them: Yes / No, a concept's options, a pick
    sheet's questions with theirs; [] when only a reply fits."""
    label, said = row.get('label', ''), f'{row.get("ask", "")} {row.get("what", "")}'
    if row.get('options'):
        return [str(o) for o in row['options']]
    if label == 'CONFIRM' or re.search(r'\byes ?(/|or) ?no\b', said, re.I):
        return ['Yes', 'No']
    if label == 'CONCEPT':
        from agent_runner.web import concept_options
        return [o['name'] for o in concept_options(concept_copy(row.get('concept') or ''))]
    if label == 'DECIDE':
        try:
            from agent_runner import sheet
            from agent_runner.brief import has_sheet
            if has_sheet(row.get('id', '')):
                spec = sheet.load(S.C.notes('sheets', f'{row["id"]}.json'))
                return [f'{q.get("q") or q.get("id", "")}: ' + ' / '.join(
                            str(o) + (' (recommended)' if j == q.get('recommended') else '')
                            for j, o in enumerate(q.get('answers') or []))
                        for q in sheet.questions(spec)]
        except Exception:  # noqa: BLE001 - a sheet that does not read: the ask says where it is
            pass
    return []


def agent_last_words(tid: str) -> str:
    """F143: the last message of the agent that worked on task `tid` (its latest session's transcript), else the
    task's own lines in TODO.md, uncut (what it blocked with); '' for neither."""
    try:
        from agent_runner.slots import transcript
        from agent_runner.watch import last_session
        if (last := last_session(tid)) and (path := transcript(last[1])):
            if says := [e['text'] for e in feed_entries(tail_rows(path)) if e['kind'] == 'say']:
                return says[-1]
    except Exception:  # noqa: BLE001 - no slot logs, or a transcript that does not read
        pass
    ls = P.lines(S.C.todo)
    return next(('\n'.join(P._item_block(ls, i)).strip() for _, _, t, _, i in P.iter_tasks(ls) if t == tid), '')


def need_chat_text(row: dict) -> str:
    """F143: the first message of a new control session about one Needs you row: its id and title, the agent's full
    last message (what it put to the person) and the possible answers."""
    ask, what, opts = row.get('ask') or '', row.get('what') or '', need_options(row)
    out = [f"This chat is about {row.get('id', '')} '{row.get('title') or ''}', which needs me. What was put to me:",
           ask]
    if what and what.strip(' .') not in ask:
        out.append(what)
    if (last := agent_last_words(row.get('id', ''))) and last not in out:
        out.append(f"The agent's last message:\n{last}")
    if opts:
        out.append('Possible answers:\n' + '\n'.join(f'- {o}' for o in opts))
    if row.get('url'):
        out.append(f'Its page: {row["url"]}')
    out.append('Say the question and its possible answers in a few plain words, then wait for my reply. Settle it as '
               'guide needs says once I answer; do nothing before that.')
    return '\n\n'.join(x for x in out if x)


def need_chat(tid: str, wait: bool = True) -> dict:
    """F143: Chat on a Needs you item: a new control session (`control --new --ask`) whose first message is
    `need_chat_text` of it. An id that is none, or no longer needs the person, is refused."""
    if not TASK_ID.fullmatch(tid or '') and need_label(tid) != 'PITCH':
        return {'ok': False, 'code': 2, 'out': f'need_chat: a task id (F83), not {tid!r}', 'argv': []}
    from agent_runner.status import waiting_ok
    rows, _ = needs_rows(waiting_ok(), dt.datetime.now())
    row = next((r for r in rows if r['id'] == tid), None)
    if row is None:
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    return new_control(need_chat_text(row), wait)


def rename_chat(chat: str, title: str) -> dict:
    """F129: the person's own name for control session `chat` (c1, c6): `control --rename N NAME`."""
    title = ' '.join(str(title or '').split())
    if not re.fullmatch(r'c\d+', chat or ''):
        return {'ok': False, 'code': 2, 'out': f'rename_chat: not a chat: {chat!r}', 'argv': []}
    if not title:
        return {'ok': False, 'code': 2, 'out': 'rename_chat: a name, please', 'argv': []}
    return call(['control', '--rename', chat[1:], title])


def task_text(tid: str) -> dict:
    """F85: a task's whole text, as `plan ID` prints it: {'ok', 'id', 'text'}."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'id': tid, 'out': f'a task id (F83), not {tid!r}'}
    r = call(['plan', tid])
    return {'ok': r['ok'], 'id': tid, 'text': r['out'] if r['ok'] else '', 'out': '' if r['ok'] else r['out']}


def settings() -> dict:
    """F97: every setting, its value, source and default (`config.settings_snapshot`), read from the files now."""
    from agent_runner import config as CF
    return CF.settings_snapshot(S.ROOT)


_SETTING_LOCK = threading.Lock()  # two pages saving at once: one read and write of the file at a time


def _setting_done(table: str, key: str, value=None, unset: bool = False) -> dict:
    from agent_runner import config as CF
    try:
        with _SETTING_LOCK:
            f = CF.save_local_setting(S.ROOT, table, key, value, unset)
    except (ValueError, OSError) as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if (table, key) in CF.SETTING_NOW and S.run_up():  # it applies now: the run that is up is told
        r = call(['slots', str(next(k['value'] for t in settings()['tables'] if t['table'] == table
                                    for k in t['keys'] if k['key'] == key))])
        if not r['ok']:
            return {**r, 'out': f'saved in {f.name}, but the run did not take it: {r["out"]}'}
    said = f'[{table}] {key} is reset' if unset else f'[{table}] {key} = {CF.toml_value(value)}'
    return {'ok': True, 'code': 0, 'out': f'{said} in {f.name}', 'argv': []}


def setting_device(table: str, key: str, value=None) -> dict:
    """F97: save a This device value: one key of runner.local.toml, in place, at once."""
    return _setting_done(table, key, value)


def setting_reset(table: str, key: str) -> dict:
    """F97: clear a device override: the key leaves runner.local.toml."""
    return _setting_done(table, key, unset=True)


def setting_project(table: str, key: str, value=None) -> dict:
    """F97: save a Project value: never an edit of the main checkout, but a queued C task on runner.toml, which lands
    through the gate."""
    from agent_runner import config as CF
    if problem := CF.setting_check(S.ROOT, table, key, value):
        return {'ok': False, 'code': 2, 'out': problem, 'argv': []}
    f = CF.config_file(S.ROOT)
    if re.search(r'\s\|\s*\w+:|—|BLOCKED:|\\n', CF.toml_value(value)):  # the plan's own marks: the line would not read back
        return {'ok': False, 'code': 2, 'out': f'[{table}] {key}: that value cannot go on a task line; ask for it in a '
                                               f'chat', 'argv': []}
    return plan_add('C', f'set [{table}] {key} = {CF.toml_value(value)} in {f.name if f else "runner.toml"} '
                         f'(from the run app\'s Settings)', files=['runner.toml' if not f else f.name])


ACTIONS.update({'pitch_no': pitch_no, 'need_drop': need_drop, 'need_chat': need_chat, 'rename_chat': rename_chat,
                'setting_device': setting_device, 'setting_reset': setting_reset, 'setting_project': setting_project})
