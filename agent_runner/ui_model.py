"""F65: the run page model: one snapshot of the run (JSON) for the web page, the terminal UI and the claude.ai
copy, and the actions they share.

`snapshot()` reads what `status` reads (STATE, the plan, the run log, Needs you) and returns one plain dict:

    status    the status lines: run up or not, its state, progress, release, no-settings or no-gate warning, usage
    slots     the run's slot count (0 when no run is up; while it starts, [run] slots)
    sessions  every live control session (cN, its title from state), then each slot s1..s<slots>
              and any past the count still on a task: task, title, minutes, state (running, merging, idle: no
              task), files, session link, terminal URL
    sessions_note  '' (kept for pages that read it: C26 has no older run to tell apart)
    queue     every open task in TODO.md: id, kind, title, files, after, pri, section, blocked, after_title
              (what it waits on in words: 'F66 Run page: …', 'B109 (landed)', 'all: everything above it') and
              state ('running s2 6m', 'critical', 'after', 'tool', 'parked', 'ready'); with shared tools set, needs
              and tool_wait ('waits for iPhone 15, held by F389, 12 min')
    tools     the shared tools ([run.tools]; F168): name, label, state, words, waits; [] without them
    shelved   F184: the shelved tasks (`shelved_rows`), which queue, needs and concepts leave out: id, kind, title,
              ask in plain words, state 'shelved'
    needs     what waits on the person (not the shelved ones): label, id, ask in plain words, link, age, detail (what
              its card and popup say: said, title, where, summary, lead, steps, expect, notes, shots, step_more and inputs (F175); need_detail)
    concepts  concept pages waiting for an OK: build id, concept id, title, page link, copy (the local copy
              of the page `done --artifact` kept, <notes>/concepts/<ID>.html; '' for none)
    log       the run log's last lines
    release   the release lines, one per release ('' for none)
    releases  F185: the Releases group, one row each (`release_rows`): the open V tasks (also moved last in
              `queue`, each with `release`: its row), or a placeholder while `[run] auto_release` counts, then
              the last one released
    quick_asks  the Status chat's quick asks, each a new chat: key, label, text
    terminal_mode  how a session's terminal shows: 'ttyd', or 'install' (no ttyd yet)
    run       paused, stopping, forced, power, and `state`: the state pill's words (F124: `run_state`)
    usage     F124: the account's usage, [{'name': 'session'|'week', 'pct'}]
    lately    F124: what landed lately, newest first, [{'at', 'text'}], the words `status` lists under "lately"
    fixups    F124: what the Fix up controls would work on (`fixups`): {'resume', 'unclaim', 'wip': [{'id', 'label'}]}
    claude_login  F126a: the Claude login warning (`watch.claude_login_line`), the page's banner, else ''
    no_settings  F178: the warning when no settings file was found (`no_settings`), else ''
    chat_quiet  F128: `[ui] chat_quiet` in seconds (0 off)
    version   the run's agent-runner version, from STATE ('' when no run is up or an older run wrote none);
              F90: the TUI restarts and the run page reloads when it changes

F74 adds, outside the snapshot (read on demand, per session): `feed(name)` (its transcript as say/you/tool/out
entries); and the actions `chat_to` (any control session), `interrupt`, `new_control` and `quick_ask`; F86
`concept_chat` (a new control session about one concept).

Each action calls what the CLI already does, as a subprocess of the runner (`runner_cmd()`), so a page and a
terminal change the run exactly as a person typing the command would (B138: a Needs you button's `answer` runs
`plan confirm|change` or `sheet` itself); `chat`, a typed `answer` and a Chat or Take back control open a new control session with the
message as its first (F176). Standard library only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess as sp
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

from agent_runner import need_detail
from agent_runner import plan as P
from agent_runner import plansync
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
    tool_waits, tool_names = split_wait_words(ls, st, now) | tool_wait_words(ls, st, now), project_tools()
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
                    'state': queue_state(tid, pri, after, live, where, box == '~', tid in tool_waits)})
        if tool_names:  # F168
            out[-1].update(needs=f.get('needs', []), tool_wait=tool_waits.get(tid, ''))
        elif tid in tool_waits:  # B184: memory; B196: its author's split
            out[-1]['tool_wait'] = tool_waits[tid]
        if P.release(tid):  # F186: one that started cannot be dropped from its row
            out[-1]['started'] = release_started(tid, st or {})
    return out


def release_started(tid: str, st: dict) -> bool:
    """F186: is release task `tid` under way: a slot of STATE `st` runs it, it merges, or a person took it."""
    from agent_runner.sched import taken
    return tid in (st.get('running') or {}).values() or tid in (st.get('merging') or []) or \
        bool(S.C and tid in taken())


# F74: a queue row's state, first word. 'blocked' (beyond the design's four): a [~] task waits on a person or
# a fix, and 'ready' would say it can start. B118: 'parked' (level later, TODO.md's Parked section): a run never
# starts it, so it must not say 'ready' either.
QUEUE_STATES = ('running', 'blocked', 'critical', 'after', 'tool', 'parked', 'ready')


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
                blocked: bool = False, tool: bool = False) -> str:
    """F74: a queue row's state: 'running sN Nm' while a slot runs it, else 'blocked' ([~]: waits on a person
    or a fix), else 'parked' (B118: level 'later': a run never starts it), else 'critical', else 'after' while a
    task it waits on is still open, else 'ready'. F168: 'tool' comes before 'critical': only a shared tool keeps it."""
    if tid in where:
        return where[tid]
    if blocked:
        return 'blocked'
    if pri == 'later':
        return 'parked'
    if tool and not any(t in live for t in after):
        return 'tool'
    if pri == 'critical':
        return 'critical'
    return 'after' if any(t in live for t in after) else 'ready'


def tool_wait_words(ls: list[str], st: dict | None, now: float | None = None) -> dict[str, str]:
    """F168: {task: 'waits for iPhone 15, held by F389, 12 min'}; {} when nothing waits, or they do not read."""
    from agent_runner import shared_tools
    try:
        return shared_tools.wait_words(ls, st or {}, now)
    except Exception:  # noqa: BLE001 - costs the words, not the snapshot
        return {}


def split_wait_words(ls: list[str], st: dict | None, now: float | None = None) -> dict[str, str]:
    """B196: {task: 'waits to be split, starts in 4 min if it is not'}; not one running or taken by hand."""
    from agent_runner import sched
    try:
        return P.split_waits(ls, now, {*sched.taken(), *((st or {}).get('running') or {}).values()})
    except Exception:  # noqa: BLE001 - costs the words, not the snapshot
        return {}


def project_tools() -> list[str]:
    """The names a task's `needs:` may have here: [run.tools], and the devices the project uses (F169)."""
    from agent_runner import shared_tools
    return sorted(shared_tools.specs())


def tool_rows(up: bool, ls: list[str], st: dict, now: float | None = None) -> list[dict]:
    """F168: the project's shared tools (`shared_tools.rows`) while a run is up; [] without the setting."""
    from agent_runner import shared_tools
    try:
        return shared_tools.rows(ls, st, now) if up else []
    except Exception:  # noqa: BLE001 - costs the line, not the snapshot
        return []


RELEASE_SHOWN = 5  # how many of the tasks a release waits for its line names; the rest are a count


def release_rows(ls: list[str], st: dict | None = None, landed: int | None = None, now: float | None = None) -> list[dict]:
    """F185: the releases, one row each, the same words on the run page, the TUI, `status` and `plan`: each
    release task (kind V) open in TODO.md's lines `ls` (`release_tasks`), one releasing now first; with none
    open and `[run] auto_release` on, a placeholder 'Next release · auto at 10 landed: 6/10 · when the run goes
    idle' (F131; `landed`: tasks landed since the last release, counted when None); last, the newest release
    that landed (`last_release`). `text` is a whole row, `note` what it does not wait on; `placeholder` True for a
    row that is no open task."""
    st = st or {}
    rows = release_tasks(ls, st)
    if not rows and (ph := auto_release_row(ls, landed)):
        rows = [ph]
    done = last_release(now)
    return rows + ([done] if done and done['id'] not in {r['id'] for r in rows} else [])


def release_tasks(ls: list[str], st: dict) -> list[dict]:
    """The open release tasks of `ls` as `release_rows`' rows, `state` 'releasing' (a slot of STATE `st` runs it,
    or it merges), 'blocked', 'waits' (`waits`: [{id, title}]; `words` names the first RELEASE_SHOWN, `all` every
    one) or 'next' (nothing left before it)."""
    tasks = [t for t in P.iter_tasks(ls) if t[1] in ' ~']
    live, titles, away, out = P.open_ids(ls), {}, None, []
    for section, box, tid, rest, i in tasks:
        if not P.release(tid) or section.startswith(P.SKIPPED) or P._shelved(ls, i):
            continue
        titles = titles or {t: after_name(_no_tag(r)) for _, _, t, r, _ in tasks}
        note, held = '', []
        waits = P.WAITS.findall(' '.join(P._item_block(ls, i))) if box == '~' else []
        if tid in (st.get('running') or {}).values() or tid in (st.get('merging') or []):
            state = 'releasing'
        elif box == '~' and not waits:
            state = 'blocked'
        else:
            if P._waits_all(ls, i):
                held = [t for t in P.before_all(ls, i) if t in live and t != tid]
                note = P.not_waiting([t for t in P.on_person_before(ls, i) if t != tid])  # B101
                if P.ALL in P.fields(ls[i]).get('after', []):  # B107: a task taken by hand lands after it
                    from agent_runner.sched import taken
                    from agent_runner.status import taken_note
                    away = set(taken()) if away is None else away
                    note += taken_note([t for t in held if t in away])
                    held = [t for t in held if t not in away]
            else:
                ids = [t.strip() for t in waits[-1].split(',')] if waits else P.waits_on(ls, i)
                held = [t for t in dict.fromkeys(ids) if t in live and t != tid]
            state = 'waits' if held else 'next'
        names = [f'{t} {titles.get(t, "")}'.rstrip() for t in held]
        more = len(names) - RELEASE_SHOWN
        words = full = {'releasing': 'releasing now', 'blocked': 'blocked', 'next': 'next'}.get(state, '')
        if held:
            full = f'waits for {len(names)}: {", ".join(names)}'
            words = f'waits for {len(names)}: {", ".join(names[:RELEASE_SHOWN])}, and {more} more' if more > 0 else full
        out.append({'id': tid, 'title': titles[tid], 'state': state, 'words': words, 'all': full, 'placeholder': False,
                    'waits': [{'id': t, 'title': titles.get(t, '')} for t in held],
                    'text': f'{tid} {titles[tid]} · {words}', 'note': note})
    return sorted(out, key=lambda r: r['state'] != 'releasing')


def release_ask(rows: list[dict]) -> dict | None:
    """F186: what a New release is told of the open releases among `release_rows`' rows: {'said': 'V17 is already
    queued', 'ask': the question before another is queued, 'seen': their ids, which the Yes carries}; None with none."""
    rows = [r for r in rows if not r.get('placeholder')]
    if not rows:
        return None
    said = '; '.join(f'{r["id"]} is {"releasing now" if r["state"] == "releasing" else "already queued"}' for r in rows)
    return {'said': said, 'ask': f'{said}. Queue another release?', 'seen': ' '.join(sorted(r['id'] for r in rows))}


RELEASE_LOCK = threading.Lock()  # F186: one New release at a time looks at the plan and adds to it


def new_release(argv: list[str], seen: str = '', confirm: bool = False) -> dict:
    """F186: queue a release by `argv`; with one open already only on a `confirm` that names the ones open now
    (`seen`), so neither a second press nor a second Yes queues one more unasked."""
    with RELEASE_LOCK:
        ask = release_ask(release_tasks(P.lines(S.C.todo), _state(S.run_up()))) if S.C else None
        if ask and not (confirm is True and seen == ask['seen']):
            return {'ok': False, 'code': 3, 'out': ask['ask'], 'confirm': ask['ask'], 'seen': ask['seen'], 'argv': argv}
        return call(argv)


def _no_tag(rest: str) -> str:
    """A task's line without F130's `(alone)` tag, which is no title."""
    return re.sub(r'^\s*(?:\(follow-up, \w+\)\s*)?\(alone\)\s*', '', rest)


def auto_release_row(ls: list[str], landed: int | None = None) -> dict | None:
    """F131: the placeholder row while `[run] auto_release` counts and no release is queued, else None."""
    from agent_runner.autorelease import auto_release_of
    every, idle = auto_release_of(S.C.run.get('auto_release', False) if S.C else False)
    if not (every or idle) or P.open_release(ls):  # a shelved or Parked release: none is queued by itself
        return None
    if every and landed is None:
        landed = landed_count()
    count = '' if landed is None else f': {landed}/{every}'
    words = ' · '.join(([f'auto at {every} landed{count}'] if every else []) +
                       (['when the run goes idle'] if idle else []))
    return {'id': '', 'title': 'Next release', 'state': 'auto', 'words': words, 'all': words, 'placeholder': True,
            'waits': [], 'text': f'Next release · {words}', 'note': ''}


_LAST_RELEASE: list = [None, None]  # `last_release`: the event log's mark when last read, and (stamp, id, title)


def last_release(now: float | None = None) -> dict | None:
    """F185: the newest release task the run log says landed, as a row 'V9 Release 0.62.0 · released 17:06'
    (the date too when that is not today); None when none did."""
    from agent_runner.status import as_event, events_file, read_events, release_version
    if not S.C:  # before `state.init`: the plan's lines alone
        return None
    try:
        f = events_file().stat()
        mark = (str(events_file()), f.st_size, f.st_mtime_ns)
        if _LAST_RELEASE[0] != mark:
            evs = [e for x in read_events() if (e := as_event(x))]
            j = next((j for j in range(len(evs) - 1, -1, -1)
                      if evs[j]['kind'] == S.EV_LANDED and P.release(evs[j].get('id') or '')), None)
            _LAST_RELEASE[:] = [mark, None if j is None else
                                (evs[j]['time'], evs[j]['id'], f'Release {release_version(evs, j)}'.rstrip())]
        if not _LAST_RELEASE[1]:
            return None
        stamp, tid, title = _LAST_RELEASE[1]
        at = dt.datetime.fromisoformat(stamp[:19])
    except (OSError, ValueError):  # no event log yet: costs the row
        return None
    today = dt.datetime.fromtimestamp(time.time() if now is None else now).date()
    words = f'released {at:%H:%M}' if at.date() == today else f'released {at:%Y-%m-%d %H:%M}'
    return {'id': tid, 'title': title, 'state': 'released', 'words': words, 'all': words, 'placeholder': True,
            'waits': [], 'text': f'{tid} {title} · {words}', 'note': ''}


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


def pin_releases(queue: list[dict], rows: list[dict]) -> list[dict]:
    """The queue with the release tasks `rows` stand for moved to its end, each carrying `release`: its row. The
    plan views show them in the Releases group above the queue (F185). A placeholder row is not a task: not added."""
    by = {r['id']: r for r in rows if not r.get('placeholder')}
    at = {q['id']: q for q in queue}
    return [q for q in queue if q['id'] not in by] + [dict(at[t], release=r) for t, r in by.items() if t in at]


def needs_rows(waiting, now: dt.datetime) -> tuple[list[dict], list[dict]]:
    """(needs-you items, concepts) from `status.waiting_ok()`'s list; shelved items are left out of both."""
    needs, concepts = [], []
    stamps = {w[1]: w[7] for w in waiting if len(w) > 7 and w[7]}
    texts = need_detail.task_lines() if waiting else {}
    for label, tid, k, what, url, title, shelved, *_ in waiting:
        if shelved:
            continue
        opts, what = need_detail.decide_options(tid, what, texts.get(tid, '')) if label == 'DECIDE' else ([], what)  # F181c
        if label == 'CONCEPT':
            concepts.append({'id': tid, 'concept': k, 'title': title, 'url': url, 'copy': concept_copy(k)})
        needs.append({'label': label, 'id': tid, 'concept': k, 'title': title, 'what': what, 'url': url,
                      'ask': (ask := P.plain_ask(label, what, title)), 'ask_short': ask_short(ask),
                      'age': P.age(stamps.get(tid, ''), now),
                      'detail': need_detail.detail(label, tid, ask, title, texts.get(tid, ''), ask_short)})  # F162
        if opts:
            needs[-1]['options'] = opts
        elif label == 'DECIDE' and url and (easy := sheet_options(tid, texts.get(tid, ''))):  # F181b
            needs[-1].update(options=easy, picks={o['name']: o.pop('send') for o in easy})
        if label == 'PITCH':  # F98
            from agent_runner import pitch
            xs = [{'id': x['id'], 'title': x['title']} for x in pitch.changes_of(tid, state='waiting')]
            needs[-1].update(copy=concept_copy(tid), changes=xs, options=['Approve'] + [
                f'Not {w}: {how}' for w in ['this'] + ([x['id'] for x in xs] if len(xs) > 1 else [])
                for how in ('reopen', 'drop')])
        needs[-1]['answers'] = need_answers(needs[-1])  # C33: both pages draw these
    return needs, concepts


def shelved_rows(ls: list[str], waiting) -> list[dict]:
    """F184: every shelved task (`plan shelve`) of TODO.md's lines `ls`, in plan order, a list of its own: the Plan
    view shows them in the Parked group, and the queue, Needs you and Concepts leave them out. `ask`: what it waits on
    the person for, from `status.waiting_ok()`'s list ('' for one that list does not have, which `plan unshelve`
    refuses)."""
    names, by = _kind_names(), {w[1]: w for w in waiting if w[6]}
    out = []
    for section, _, tid, rest, i in P.iter_tasks(ls):
        if not P._shelved(ls, i):
            continue
        w = by.get(tid)
        out.append({'id': tid, 'kind': task_kind(tid, names), 'title': P.short_title(w[5] if w else rest, 200),
                    'section': section, 'ask': P.plain_ask(w[0], w[3], w[5]) if w else '', 'state': 'shelved'})
    return out


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
    """C26: {N: title} of this repository's live control sessions (those with a live pid file), each
    titled from the name kept in state (`<notes>/controlN.title`, `given_title`); no window names are read."""
    try:
        from agent_runner.control import control_given, control_live_numbers
        return {n: given_title(control_given(n), n) for n in control_live_numbers()}
    except Exception:  # noqa: BLE001 - no notes dir yet
        return {}


def control_rows(windows: dict[int, str], links=None) -> list[dict]:
    """B113: each live control session as cN with
    its title (`windows`, as `control_titles`); `links` as `session_rows` (None: each link from its pid file's
    transcript)."""
    out = []
    for n in sorted(windows):
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
    """The control sessions (B113: `control_rows`; `windows` as `control_titles`, None: read from
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


NO_SETTINGS = 'no settings found, so no test gate and nothing is pushed'


def no_settings(c=None, st: dict | None = None) -> str:
    """F178: NO_SETTINGS when the project of config `c` (default: this one) has no settings file, else ''. `st`: an up
    run's STATE, which says what that run itself found (it may have been started with AGENT_RUNNER_CONFIG)."""
    if st and 'no_settings' in st:
        return NO_SETTINGS if st['no_settings'] else ''
    c = c or S.C
    # runner.local.toml alone can set a gate or the push: then the words would not be true
    if not c or c.file or c.run['test'] or (c.push_merge and 'push_merge' in c.given.get('git', ())):
        return ''
    return NO_SETTINGS


def status_rows(up: bool, st: dict, progress: str, login: str | None = None) -> list[str]:
    """The status lines: the run's state, progress, the no-settings or no-gate warning, and usage. `login`: the Claude
    login warning, when it is read already."""
    from agent_runner.land import no_gate_line
    out = [f'run up: {st.get("state", "starting")}' if up else 'no run is up']
    for k, said in (('paused', 'paused'), ('stopping', 'stopping: finishing the running tasks')):
        if up and st.get(k):
            out.append(said)
    try:
        if line := no_settings(st=st if up else None) or no_gate_line():
            out.append(line)
    except Exception:  # noqa: BLE001
        pass
    from agent_runner.watch import claude_login_line
    if login := claude_login_line() if login is None else login:  # F126
        out.append(login)
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


_PLAN_FACTS: dict = {}  # `plan_facts` by the project's files: what they held when last read
FACTS_TAIL = 512 * 1024  # bytes of the event log's end that `plan_facts` reads: more than a day of events


def plan_facts(c, now: dt.datetime | None = None) -> dict:
    """F150: what All projects says of the plan of config `c` (any project, up or off, `state.init` or not):
    {'titles' (open tasks, {id: title}), 'queue' (the next tasks, [{'id', 'title'}]), 'landed' (today's titles, newest
    first)}. Kept until a file it reads changes."""
    now = now or dt.datetime.now()
    files = (c.todo, c.done, c.notes('events.jsonl'))

    def mark(f):
        try:
            s = f.stat()
            return s.st_size, s.st_mtime_ns
        except OSError:
            return None
    marks = (now.date(), *map(mark, files))
    hit = _PLAN_FACTS.get(str(c.todo))
    if hit and hit[0] == marks:
        return hit[1]
    ls = P.lines(c.todo)
    queue = [{'id': tid, 'title': P.short_title(rest, 200)} for section, box, tid, rest, _ in P.iter_tasks(ls)
             if box == ' ' and not section.startswith(P.SKIPPED)][:10]
    names = P.titles(c.done, c.todo, width=200)
    out = {'titles': {tid: names[tid] for _, box, tid, _, _ in P.iter_tasks(ls) if box in ' ~'}, 'queue': queue,
           'landed': [names.get(tid, tid) for tid in landed_on(files[2], now.date().isoformat())]}
    _PLAN_FACTS[str(c.todo)] = (marks, out)
    return out


def landed_on(events: Path, day: str) -> list[str]:
    """The ids that landed on `day` (YYYY-MM-DD), newest first, from a project's event log."""
    try:
        with open(events, 'rb') as f:
            f.seek(max(0, events.stat().st_size - FACTS_TAIL))
            tail = f.read().decode('utf-8', 'replace').splitlines()
    except OSError:
        return []
    ids: list[str] = []
    for line in reversed(tail):
        if f'"{day}T' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:  # the first line of the tail is cut
            continue
        if isinstance(e, dict) and e.get('kind') in (S.EV_LANDED, S.EV_PART) and e.get('id') and e['id'] not in ids:
            ids.append(e['id'])
    return ids


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
    from agent_runner.watch import claude_login_line
    up = S.run_up() if up is None else up
    now = time.time() if now is None else now
    st, ls = _state(up), P.lines(S.C.todo)
    login = claude_login_line()  # F126a
    titles = P.titles(S.C.done, S.C.todo, width=200)
    releases = release_rows(ls, st, now=now)  # F185
    release = release_line(ls, st, releases)
    try:
        progress = progress_line(now=dt.datetime.fromtimestamp(now))
    except Exception:  # noqa: BLE001 - a git hiccup costs the progress line, not the snapshot
        progress = ''
    waiting = waiting_ok()
    needs, concepts = needs_rows(waiting, dt.datetime.fromtimestamp(now))
    shelved = shelved_rows(ls, waiting)  # F184
    slots = slot_count(up, st)
    sessions = session_rows(st, ls, titles, now, links, terminal_base, slots, windows)
    for r in sessions:
        r['task_controls'] = task_controls_on(r)  # C33
    run = {'paused': bool(up and st.get('paused')), 'stopping': bool(up and st.get('stopping')),
           'forced': bool(up and st.get('forced')), 'power': str(st.get('power') or '') if up else '',
           'state': run_state(up, st)}  # F124
    queue = pin_releases(queue_rows(ls, st, now), releases)
    tools = tool_rows(bool(up), ls, st, now)  # F168
    for where, rows in (('queue', queue), ('shelved', shelved), ('need', needs), ('concept', concepts), ('session', sessions)):
        for r in rows:
            r['acts'] = row_acts(where, r)  # C34, C35
            if labels := row_labels(where, r):  # F180
                r['labels'] = labels
            if asks := row_asks(where, r):  # F186
                r['asks'] = asks
    fix = fixups(st, ls)
    rel_ask = release_ask(releases)  # F186
    return {**controls_shown(bool(up), run, fix), 'run': run, 'fixups': fix,
            'project': S.project(), 'at': dt.datetime.fromtimestamp(now).isoformat(timespec='seconds'),
            'up': up, 'status': status_rows(up, st, '\n'.join(x for x in (progress, release, tools_line(tools)) if x), login),
            'tools': tools, 'tool_names': project_tools(),
            'slots': slots, 'sessions': sessions, 'sessions_note': '',
            'queue': queue, 'releases': releases, 'release_acts': [c['key'] for c in RUN_CONTROLS
                                                                   if c['where'] == 'release'],
            'shelved': shelved, 'needs': needs, 'concepts': concepts, 'log': log_tail(log_n), 'release': release,
            'release_said': rel_ask['said'] if rel_ask else '',
            'quick_asks': quick_asks(), 'terminal_mode': terminal_mode(), 'controls': controls(rel_ask),
            'no_settings': no_settings(st=st if up else None),  # F178
            'claude_login': login,  # F126a
            'unpushed': unpushed_line(),  # F98
            'usage': usage_rows(st), 'lately': lately(titles), 'chat_quiet': chat_quiet(),
            'version': str(st.get('version') or '')}  # F90: the run's version ('' from an older run)


def tools_line(tools: list[dict]) -> str:
    from agent_runner import shared_tools
    return shared_tools.line(tools)


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


def _flags(files=None, after=None, pri: str = '', test: str = '', needs=None) -> list[str]:
    out = []
    if files:
        out += ['--files', ','.join(files) if isinstance(files, (list, tuple)) else files]
    if after:
        out += ['--after', ','.join(after) if isinstance(after, (list, tuple)) else after]
    if test:
        out += ['--test', test]
    if needs:
        out += ['--needs', ','.join(needs) if isinstance(needs, (list, tuple)) else needs]
    if pri:
        out += ['--pri', pri]
    return out


def plan_add(kind: str, text: str, files=None, after=None, pri: str = '', test: str = '', needs=None) -> dict:
    """Queue a task: `plan add KIND TEXT --files … --after … --pri …`."""
    return call(['plan', 'add', kind, text, *_flags(files, after, pri, test, needs)])


def plan_change(tid: str, text: str = '', files=None, after=None, pri: str = '', test: str = '', needs=None) -> dict:
    """The page's direct edit of a queued task: `plan edit ID [TEXT] [--files …]`, rewritten in place (a slot
    running it is told)."""
    return call(['plan', 'edit', tid, *([text] if text else []), *_flags(files, after, pri, test, needs)])


def drop(tid: str, why: str) -> dict:
    """`plan drop ID WHY`: not wanted; a slot running it is stopped."""
    return call(['plan', 'drop', tid, why])


def to_new(text: str) -> dict:
    """F176: a prompt opens a chat of its own: a new control session with `text` as its first message, started
    without waiting for its link (`control --new --no-wait --ask`)."""
    return call(['control', '--new', '--no-wait', '--ask', text, '--no-feed'])


SEND = [to_new]  # how chat and answers start a chat; a test swaps it


def chat(text: str) -> dict:
    """The page's chat box: the person's words, as they typed them, to a new chat."""
    return SEND[0](text)


SHEET_GO = ('go', 'recommended')  # a pick sheet's reply for its recommended picks
CHECK_FAILED = 'No: the check failed'  # B138: what a CONFIRM's No reopens the task with


def need_label(tid: str) -> str:
    """B138: the label of what `tid` asks (CONFIRM, DECIDE, BLOCKED, STUCK, CONCEPT); '' when nothing needs you
    about it."""
    from agent_runner import pitch
    if pitch.PITCH_ID.fullmatch(tid or ''):  # F98
        return pitch.LABEL if any(r[1] == tid for r in pitch.rows()) else ''
    if (tid or '').startswith('tool-'):  # F168
        from agent_runner import shared_tools
        return shared_tools.LABEL if any(r[1] == tid for r in shared_tools.asks()) else ''
    try:
        return P._ask(tid, S.C.todo)[0]
    except (SystemExit, OSError, AttributeError):
        return ''


def answer_argv(tid: str, text: str, button: bool = False, note: str = '') -> tuple[list[str], str]:
    """B138: the runner command that settles a Needs you reply at once, and what to say once it did; ([], '')
    when the reply is a chat's to read. A button's Yes (or a pick, or done) is `plan confirm ID "<reply>"`, a
    CONFIRM's No is `plan change ID "No: the check failed"`; a pick sheet's go or Send line is `sheet ID
    --go|--picks`; a concept's option button is `plan approve ID "<option>"` (B149). F181a: words typed as the
    reply to a DECIDE are its answer, so they run the same command as a button's; typed for any other label they
    are a new chat's. F162: `note`, the words beside a button's answer, go with it: in the task's note,
    or a pitch no's --why; `answer` sends an approved pitch's to a new chat."""
    said, label, note = (text or '').strip(), need_label(tid), ' '.join((note or '').split())
    noted = f': {note}' if note else ''
    why = [f'--why={note}'] if note else []  # one word of the command line, so words that start with - stay words
    noting = [f'--note={note}'] if note else []
    if label == 'PITCH' and button:  # F98
        if said.lower() == 'approve':
            return ['pitch', 'approve', tid], f'{tid} approved'
        if m := re.fullmatch(r'not (\w+): (reopen|drop)', said, re.I):
            one, how = m[1], m[2].lower()
            argv = ([] if how == 'reopen' else ['--drop', 'all']) if one.lower() == 'this' else [f'--{how}', one]
            return ['pitch', 'no', tid, *argv, *why], f'{tid}: the run undoes it'
        return [], ''
    if label == 'DECIDE':
        from agent_runner.brief import has_sheet
        if has_sheet(tid) and said.lower() in SHEET_GO:
            return ['sheet', tid, '--go', *noting], f'{tid} answered with the recommended picks'
        if has_sheet(tid) and said.startswith(f'{tid} picks:'):
            return ['sheet', tid, '--picks', said, *noting], f'{tid} answered with your picks'
    if label == 'CONCEPT' and button and said:  # B149: a concept's option button approves that option itself
        return ['plan', 'approve', tid, said + noted], f'{tid} approved ({said}): a run starts its build'
    if not said or label not in ('CONFIRM', 'DECIDE', 'BLOCKED', P.STUCK) or not (button or label == 'DECIDE'):
        return [], ''
    if label == 'CONFIRM' and said.lower() == 'no':
        return ['plan', 'change', tid, f'No{noted}' if note else CHECK_FAILED], f'{tid} reopened: the check failed'
    if label == 'CONFIRM':
        return ['plan', 'confirm', tid, said + noted], f'{tid} ticked'
    return ['plan', 'confirm', tid, said + noted], f'{tid} answered ({said}): a run starts it'


def answer(tid: str, text: str, button: bool = False, note: str = '') -> dict:
    """A reply to a Needs you item. B138: a button's answer, and the words typed for a DECIDE (F181a), run the
    plan command itself (`answer_argv`), with no AI session, and an ok result carries 'said' (what was done, for
    the toast) and 'gone' (the item, off Needs you); the words typed for any other label go to a new chat to
    settle as its needs guide says."""
    argv, done = answer_argv(tid, text, button, note)
    if button and not argv and not need_label(tid):  # answered already, or never asked: say so, no AI session
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    if argv:
        r = call(argv)
        if r['ok']:
            if argv[0] == 'pitch':
                done = r['out'].splitlines()[0] if r['out'] else done  # F98: pushed, or what it waits for
                words = ' '.join((note or '').split())
                if words and argv[1] == 'approve':  # F162a: its tasks are done, so the words go where a reply does
                    sent = SEND[0](f'{tid}: approved. {words}')
                    if not sent['ok']:
                        why = (sent['out'].splitlines() or [''])[0]
                        S.log(f'{tid}: approved; the words with it went to no chat ({why}): {words}')
                        done += f'. Your words were not sent ({why}): {words}'
            r.update(said=done, gone=tid)
        return r
    title = P.titles(S.C.todo).get(tid, '')
    return SEND[0](f'{tid}{f" ({title})" if title else ""}: {text}')


def as_data(value: str) -> str:
    """F175: `value` as a JSON string that holds no plan markup: what could start a field, a note, a block or a tag on
    a task line is a \\u escape, which reads back as it was."""
    return re.sub(r'[^\w .,:/?&=#%+@~!;\'"\\-]|:(?= )|:(?=\W?$)',
                  lambda m: ''.join(f'\\u{ord(u):04x}' for u in _utf16(m[0])), json.dumps(value, ensure_ascii=False)[1:-1]
                  ).join('""')


def _utf16(text: str) -> list[str]:
    b = text.encode('utf-16-be', 'surrogatepass')
    return [chr(b[j] << 8 | b[j + 1]) for j in range(0, len(b), 2)]


def need_give(tid: str, values: dict | None = None, confirm: bool = False, secure: bool = False) -> dict:
    """F175: Done on a Needs you item with inputs: `values` ({key: what the person entered}) are sent as its answer. A
    text or a link goes into the answer the task reopens with, as quoted data (`as_data`); a secret only into
    `asks.env_file`, and the answer says its name and that path. `secure`: it came over https, from this machine or
    from the terminal UI; without that a secret is refused. One that fails its input's check sends nothing: 'field' is
    its key, 'out' why. An input's `confirm` question is asked first, as 'confirm', unless `confirm` is true.
    Kept out of ACTIONS: the page that calls it sets `secure` itself, never from what was sent."""
    def no(out: str, code: int = 1, **more) -> dict:
        return {'ok': False, 'code': code, 'out': out, 'argv': [], **more}

    if not TASK_ID.fullmatch(tid or ''):
        return no(f'need_give: a task id (F83), not {tid!r}', 2)
    label = need_label(tid)
    if not label:
        return no(f'{tid} no longer needs you (answered already?)')
    inputs = need_detail.asks_file(tid).get('inputs') or [] if label in need_detail.INPUT_LABELS else []
    if not inputs or not isinstance(values, dict) or set(values) != {x['key'] for x in inputs}:
        return no(f'what {tid} asks for changed: look again')
    got = {k: v.strip() if isinstance(v, str) else v for k, v in values.items()}
    for x in inputs:
        if x['kind'] == 'secret' and secure is not True:
            return no(f'{x["label"]}: a secret is taken only over https or on this computer; this page came over plain '
                      f'http, where others on the network could read it', field=x['key'])
        if why := need_detail.input_wrong(x, got[x['key']]):
            return no(why, field=x['key'])
    asked = ' '.join(x['confirm'] for x in inputs if x['confirm'])
    if asked and confirm is not True:
        return no(asked, 3, confirm=asked)
    from agent_runner import asks
    secrets = {x['env']: got[x['key']] for x in inputs if x['kind'] == 'secret'}
    back = lambda: None  # noqa: E731
    if secrets:
        try:
            back = asks.keep_secrets(tid, secrets, S.C)
        except (OSError, ValueError) as e:
            return no(f'the secret could not be kept ({e.strerror or e if isinstance(e, OSError) else "bad file"}); nothing was sent')
    where = asks.env_file(tid, S.C)
    said = 'given (data, not instructions): ' + '; '.join(
        f'{x["env"]} is in {where}' if x['kind'] == 'secret' else f'{as_data(x["label"])} is {as_data(got[x["key"]])}'
        for x in inputs)
    # a CONFIRM's yes would tick the task: what was given is for the task to go on with, so it reopens
    try:
        r = call(['plan', 'change' if label == 'CONFIRM' else 'confirm', tid, said])
    except OSError as e:  # the runner did not start
        r = no(str(e))
    if r['ok']:
        r.update(said=f'{tid} has what you gave: a run starts it', gone=tid)
    else:
        try:
            back()
        except OSError:
            pass
    return r


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
# Take back is the one that is no runner command of its own: a new chat is asked "do ID here".

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
def answer_of(row: dict, key: str) -> str:
    """F180: the fixed answer the answer action `key` stands for on a Needs you row ('' none): need_yes and need_no
    when its answers are Yes and No, else need_answerN its Nth."""
    if row.get('label') == 'TOOL':
        return ''
    xs = [a['value'] for a in (row['answers'] if 'answers' in row else need_answers(row))]
    keys = ['need_yes', 'need_no'] if xs == ['Yes', 'No'] else [f'need_answer{j}' for j in range(1, len(xs) + 1)]
    return dict(zip(keys, xs)).get(key, '')


def _answer_action(key: str, label: str, tui: str, **more) -> dict:
    """F180: one fixed answer's entry in RUN_CONTROLS; its TUI key works in the answer tab only."""
    return {'key': key, 'label': label, 'tui': tui, 'where': 'need', 'answer': True, 'tab': 'answer',
            'fits': lambda r: bool(answer_of(r, key)), 'label_of': lambda r: answer_of(r, key), **more}


ANSWER_MAX, ANSWER_KEYS = 12, 'abcdefg'  # F180: the most fixed answers a row draws, and the TUI keys of the first ones
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
    {'key': 'task_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'task'},
    # C34: a Queue row's actions ('where' 'queue', '{id}' the row's task; `fits` says which rows it is allowed on, and
    # each snapshot row carries those keys as `acts`; '{pri}' the other level of critical / normal), and the release
    # tab's ('where' 'release'). 'tui_sure' False: the terminal UI runs it without asking (the page asks).
    # 'confirm_of' (F186): a row's own confirm ('' the entry's), asked by both; the snapshot row's `asks` carries it.
    {'key': 'queue_priority', 'label': 'Priority', 'argv': ('plan', 'edit', '{id}', '--pri', '{pri}'), 'tui': 'p',
     'where': 'queue', 'fits': lambda r: r.get('state') != 'parked'},
    {'key': 'queue_unpark', 'label': 'Unpark', 'argv': ('plan', 'edit', '{id}', '--pri', 'normal'), 'tui': 'U',
     'where': 'queue', 'help': 'unpark (a parked task: no J/K or p)', 'fits': lambda r: r.get('state') == 'parked'},
    {'key': 'queue_take', 'label': 'Do it here', 'ask': 'do {id} here', 'tui': 'H', 'where': 'queue'},
    {'key': 'queue_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'queue', 'why': 'dropped from the run app', 'tui_sure': False,
     'fits': lambda r: not r.get('started'),
     'confirm_of': lambda r: f'Drop {r["id"]}? It leaves the plan, and nothing is released.' if P.release(r['id']) else '',
     'confirm': 'It leaves the plan, and a slot running it is stopped. Drop it?'},
    # F184: a shelved task's, in the Parked group; never Unpark, which would not reopen it
    {'key': 'shelved_back', 'label': 'Bring back', 'argv': ('plan', 'unshelve', '{id}'), 'tui': 'U', 'where': 'shelved',
     'help': 'bring back (a shelved task)', 'said': '{id} is under Needs you again',
     'fits': lambda r: bool(r.get('ask'))},
    {'key': 'shelved_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'shelved', 'why': 'dropped from Parked', 'said': '{id} dropped', 'help': 'drop (a shelved task)',
     'confirm': 'Drop {id}? It leaves the plan, and its work is not done.'},
    # C35: the other panels' row actions, the same shape: 'need' (a Needs you item), 'concept', 'session' (a control
    # session cN). 'fn' one of ROW_FNS run with the row's id (a new chat, a close); 'chat' it opens a chat; 'said' its
    # toast, and a Needs you item it is done with leaves the list. '{id}' in a confirm is the row's id.
    # F180: its fixed answers (`need_answers`), each labelled by its row ('label_of', the snapshot row's `labels`):
    # 'answer' runs `answer` with that label, 'tab' the TUI tab its key works in, 'help' '' not in the keys list
    _answer_action('need_yes', 'Yes', 'y', help='yes (answer tab)'),
    _answer_action('need_no', 'No', 'n', help='no (answer tab)'),
    *(_answer_action(f'need_answer{j}', f'Answer {j}', ANSWER_KEYS[j - 1:j], help="a pick's options" if j == 1 else '',
                     help_keys='a b c' if j == 1 else '') for j in range(1, ANSWER_MAX + 1)),
    {'key': 'need_later', 'label': 'Later', 'argv': ('plan', 'shelve', '{id}'), 'tui': 'L', 'where': 'need',
     'said': '{id} is set aside until you bring it back', 'fits': lambda r: r.get('label') not in ('PITCH', 'TOOL')},
    {'key': 'need_chat', 'label': 'Chat', 'fn': 'need_chat', 'chat': True, 'tui': 'N', 'where': 'need',
     'fits': lambda r: r.get('label') != 'TOOL'},
    {'key': 'need_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'D', 'tui_also': 'd',
     'where': 'need', 'why': 'dropped from Needs you', 'said': '{id} dropped',
     'confirm': 'Drop {id}? It leaves the plan, and its work is not done.',
     'fits': lambda r: r.get('label') not in ('PITCH', 'TOOL')},
    {'key': 'concept_chat', 'label': 'New chat', 'fn': 'concept_chat', 'chat': True, 'tui': 'N', 'where': 'concept',
     'help': 'chat about it'},
    {'key': 'concept_drop', 'label': 'Drop', 'argv': ('plan', 'drop', '{id}', '{why}'), 'tui': 'd',
     'where': 'concept', 'why': 'dropped from agent-runner ui', 'tui_sure': False, 'tui_main': False,
     'confirm': 'It leaves the plan. Drop it?'},
    {'key': 'session_close', 'label': 'Close', 'fn': 'close_session', 'tui': 'd', 'where': 'session',
     'tui_main': False,
     'help': 'close a control session (its transcript stays)',
     'fits': lambda r: bool(re.fullmatch(r'c\d+', str(r.get('name', ''))))},
    {'key': 'release_wait', 'label': 'Release when the running tasks land', 'argv': ('plan', 'add', 'V'), 'tui': '⏎',
     'where': 'release'},
    {'key': 'release_now', 'label': 'Release now, without them', 'argv': ('plan', 'add', 'V', '--now'), 'tui': 'f',
     'where': 'release'},
)
TASK_DROP_WHY = 'dropped from its slot from the run controls'
SLOT_COUNT = re.compile(r'[+-]?\d{1,3}')
TASK_ID = P.TASK_ID  # B199: the ids plan takes, parts of parts (F162a2) too


CONTROL_ROWS = (('start',), ('slot_add', 'slot_remove', 'slots_set'), ('pause', 'go_on'), ('force', 'caps_on'),
                ('stop', 'stop_now', 'stop_undo'), ('suspend', 'shutdown'), ('upgrade', 'restart'),
                ('resume', 'unclaim'), ('wip_show', 'wip_restore', 'wip_drop'))  # C33: the terminal UI's key rows


def task_controls_on(row) -> bool:
    """C33: a slot's task controls (Take back, Drop) work while it works on a task, not while the task lands
    (merging); a control session has none."""
    return isinstance(row, dict) and bool(row.get('task')) and not re.fullmatch(r'c\d+', str(row.get('name', ''))) \
        and row.get('state') != 'merging'


def controls_shown(up: bool, run: dict, fixups: dict) -> dict:
    """C33: which run controls show now, for both pages: 'shown' the keys (all but Start the run while none is up,
    only a Fix up one then; Force or Caps back on by the run's state; a Fix up one while there is something to fix)
    and 'card' the everyday ones on the page's Run card."""
    shown = []
    for c in RUN_CONTROLS:
        if c['where'] != 'run' or (c['key'] == 'restart' and _plat().WINDOWS):
            continue
        if (c.get('fix') and not (fixups or {}).get(c['fix'])) or (c['key'] == 'force' and run.get('forced')) or \
                (c['key'] == 'caps_on' and not run.get('forced')):
            continue
        if c.get('up', True) == up or (not up and c.get('fix')):
            shown.append(c['key'])
    card = ['start'] if not up else ['slot_remove', 'slot_add', 'go_on' if run.get('paused') else 'pause',
                                      'stop_undo' if run.get('stopping') else 'stop']
    return {'shown': shown, 'card': card}


def _plat():
    from agent_runner import plat
    return plat


def row_acts(where: str, row: dict) -> list[str]:
    """C34: the keys of the actions of panel `where` ('queue') allowed on `row` now, in the list's order."""
    return [c['key'] for c in RUN_CONTROLS if c['where'] == where and c.get('fits', lambda r: True)(row)]


def row_labels(where: str, row: dict) -> dict[str, str]:
    """F180: {key: label} of the actions allowed on `row` whose label is the row's own."""
    return {c['key']: c['label_of'](row) for c in RUN_CONTROLS
            if c['where'] == where and 'label_of' in c and c['fits'](row)}


def row_asks(where: str, row: dict) -> dict[str, str]:
    """F186: {key: question} of the actions allowed on `row` whose confirm is the row's own."""
    return {c['key']: q for c in RUN_CONTROLS if c['where'] == where and 'confirm_of' in c
            and c.get('fits', lambda r: True)(row) and (q := c['confirm_of'](row))}


def queue_row(tid: str) -> dict | None:
    """C34: the queue's row of task `tid` as TODO.md has it now (None: not queued)."""
    return next((q for q in queue_rows(P.lines(S.C.todo), _state(S.run_up())) if q['id'] == tid), None)


ROW_WORDS = {'queue': 'a queued task', 'shelved': 'a shelved task', 'need': 'something that needs you', 'concept': 'a concept waiting',
             'session': 'a control session'}


def row_of(where: str, tid: str) -> dict | None:
    """C35: the row of panel `where` that `tid` names as the plan has it now (None: it is not there)."""
    if where == 'queue':
        return queue_row(tid)
    if where == 'session':
        return {'name': tid} if re.fullmatch(r'c\d+', tid or '') else None
    from agent_runner.status import waiting_ok
    if where == 'shelved':
        return next((r for r in shelved_rows(P.lines(S.C.todo), waiting_ok()) if r['id'] == tid), None)
    needs, concepts = needs_rows(waiting_ok(), dt.datetime.now())
    return next((r for r in (needs if where == 'need' else concepts)
                 if tid == r['id'] or (where == 'concept' and tid == r['concept'])), None)


def run_control_of(key: str) -> dict | None:
    return next((c for c in RUN_CONTROLS if c['key'] == key), None)


def controls(rel_ask: dict | None = None) -> list[dict]:
    """The run controls as a page shows them: key, label, TUI key, where, what it needs typed ('n': a slot
    count, 'id': a task) and its confirm question ('' none). F186: with a release open (`rel_ask`:
    `release_ask`), New release's actions ask, and carry the open ones as `seen`."""
    from agent_runner import plat

    def needs(c):
        if c.get('fix'):
            return 'pick'
        words = c.get('argv') or (c.get('ask') or '',)
        if c.get('fn') or c.get('answer'):
            return 'id'
        return 'n' if any('{n}' in w for w in words) else 'id' if any('{id}' in w for w in words) else ''
    return [{'key': c['key'], 'label': c['label'], 'tui': c['tui'], 'where': c['where'], 'needs': needs(c),
             'confirm': rel_ask['ask'] if rel_ask and c['where'] == 'release' else c.get('confirm', ''),
             'seen': rel_ask['seen'] if rel_ask and c['where'] == 'release' else '', 'group': c.get('group', ''), 'fix': c.get('fix', ''),
             'each': bool(c.get('each')), 'up': c.get('up', True), 'tui_also': c.get('tui_also', ''),
             'tui_sure': c.get('tui_sure', True), 'chat': bool(c.get('ask') or c.get('chat')), 'fn': bool(c.get('fn')),
             'tui_main': c.get('tui_main', True), 'answer': bool(c.get('answer')),
             'tab': c.get('tab', '')} for c in RUN_CONTROLS
            if not (plat.WINDOWS and c['key'] == 'restart')]  # no re-exec there


def control_argv(key: str, n='', tid: str = '', why: str = '', pri: str = '') -> list[str]:
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
    return [w.replace('{n}', n).replace('{id}', tid).replace('{why}', why or c.get('why') or TASK_DROP_WHY)
            .replace('{pri}', pri) for w in words]


def run_control(key: str, n='', tid: str = '', why: str = '', confirm: bool = False, wait: bool = True,
                text: str = '', note: str = '') -> dict:
    """F82: run one run control (RUN_CONTROLS) for the web page or agent-runner ui. One with a confirm question
    runs only with `confirm` true; without it the result is not ok and carries the question as 'confirm'. B139:
    one with an 'ask' starts a new control session with it (`new_control`, `wait` as there). F180: an answer takes `text`, the label the
    person pressed (refused when the row's answers have changed since), and `note`, the words beside it. F186: a New release takes
    the open releases the person said Yes to (`seen`) as `text`."""
    c = run_control_of(key)
    if c and c.get('each') and not tid:  # every one there is: 'Release stale claims (2)'
        ids = [x['id'] for x in fixups(_state(S.run_up()), P.lines(S.C.todo)).get(c['fix']) or []]
        if not ids:
            return {'ok': False, 'code': 1, 'out': f'{c["label"]}: there is nothing to do', 'argv': []}
        rs = [run_control(key, tid=i) for i in ids]
        bad = next((r for r in rs if not r['ok']), None)
        return bad or {**rs[-1], 'out': ', '.join(r['out'] for r in rs)}
    pri, row = '', {}
    if c and c['where'] in ROW_WORDS:  # C34, C35: allowed on this row now (the snapshot's `acts`, checked again)
        row = row_of(c['where'], tid)
        if c.get('answer') and row is None:
            return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
        if row and row.get('started') and key == 'queue_drop':  # F186
            return {'ok': False, 'code': 1, 'out': f'{tid} has started: a running release cannot be dropped', 'argv': []}
        if row is None or key not in row_acts(c['where'], row):
            return {'ok': False, 'code': 1, 'out': f'{c["label"]}: {tid or "none"} is not {ROW_WORDS[c["where"]]} it '
                                                   f'fits', 'argv': []}
        pri = 'normal' if row.get('pri') == 'critical' else 'critical'
        if c.get('answer'):
            said = answer_of(row, key)
            if text != said:
                return {'ok': False, 'code': 1, 'out': f"{tid}'s answers changed: look again", 'argv': []}
            return answer(tid, (row.get('picks') or {}).get(said, said), button=True, note=note)  # F181b: a pick sheet's
    if c and c.get('fn'):
        return ROW_FNS[c['fn']](tid, wait)
    try:
        argv = control_argv(key, n, tid, why, pri)
    except ValueError as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if c.get('confirm') and confirm is not True:
        ask = row_asks(c['where'], row).get(key) or c['confirm'].replace('{id}', tid)
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': argv}
    if c.get('ask'):
        return new_control(c['ask'].replace('{id}', tid), wait)
    if c['where'] == 'release':  # F186
        return new_release(argv, text, confirm)
    r = call(argv)
    FIXUPS[0] = float('-inf')  # what there is to fix is looked up anew
    if r['ok'] and c.get('said'):  # C35
        r.update(said=c['said'].replace('{id}', tid), **({'gone': tid} if c['where'] == 'need' else {}))
    return r


ACTIONS = {'plan_add': plan_add, 'plan_change': plan_change, 'chat': chat, 'answer': answer, 'drop': drop,
           'open_session': open_session, 'move': move,
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
# The feed is a session's transcript (Claude Code's JSONL, which the harness loop writes too)
# as entries {'kind': say|you|tool|out, 'text'}, newest last: the agent's words, the person's, each tool step
# and its output, which Talk reads and the page tells a working session by. A chat or slot shows the session's own
# terminal (`attach NAME` through its shim's socket), through ttyd when it is installed ('ttyd'; C25: without
# ttyd, 'install': the page says how to install it), on every OS (F114).

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
    """F74: how a page shows a session's terminal: 'ttyd' (installed: it serves `attach NAME`) or 'install' (no
    ttyd: the page says how to install it; C25). F114: on Windows too."""
    import shutil
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


def interrupt(session: str) -> dict:
    """F74: interrupt `session` (Escape typed into it), as a person pressing Esc in it would."""
    r = keys(session, key='Escape')
    return {**r, 'out': f'interrupted {session}'} if r['ok'] else r


def send(name: str, text: str) -> dict:
    """F74: the person's words to session `name` as they typed them: '' a new one (`SEND`), a control session
    or slot typed in through its hidden shim's FIFO as a bracketed paste and Enter
    (`slots.send_fifo`; F89)."""
    if not name:
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


START_WAIT = 120.0  # s a message waits for a starting chat to take input (its first message may take 90)


def _starting(name: str, wait: bool) -> dict | None:
    """B158: None once control session `name` takes input (`control.control_takes_input`), waiting up to START_WAIT
    s for it; else the answer: not sent, with 'hold' when not told to `wait` (nothing typed, so try again)."""
    from agent_runner import control as K
    end = time.monotonic() + (START_WAIT if wait else 0)
    while re.fullmatch(r'c\d+', name) and hidden_inbox(name) and not K.control_takes_input(int(name[1:])):
        if time.monotonic() >= end:
            return {'ok': False, 'code': 1, 'out': f'{name} is still starting, so it could not take the message',
                    'argv': [], **({} if wait else {'hold': True})}
        time.sleep(0.2)
    return None


def chat_to(text: str, to: str = '', force: bool = False, unsent: bool = False, wait: bool = True) -> dict:
    """F74: the chat box of any control session: `to` (c6) gets `text`, with no `to` a new one (F176). B154: 'at' is when it was typed, and
    'name' the new control session. F170: `force` interrupts it first while it works
    (`session_now.force_send`); `unsent`: the page sees words in its input, so the text goes below them.
    B158: a chat still starting gets it once it takes input; with `wait` False (the run page) the answer is 'hold'
    meanwhile."""
    if held := _starting(to, wait):
        return held
    at = time.time()
    if to and (force or unsent):
        from agent_runner.session_now import force_send
        r = {**force_send(to, text, send, unsent), 'at': at}
    else:
        r = {**send(to, text), 'at': at}
    n = re.search(r'\bcontrol (\d+) ', r.get('out') or '') if not to and r['ok'] else None
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
    new control session with the ask as its first message (`new_control`, `wait` as there)."""
    text = next((t for k, _, t in QUICK_ASKS if k == key), '')
    if not text:
        return {'ok': False, 'code': 2, 'out': f'quick_ask: key is one of {", ".join(k for k, _, _ in QUICK_ASKS)}, '
                                               f'not {key!r}', 'argv': []}
    return new_control(text, wait)


ACTIONS.update({'chat_to': chat_to, 'interrupt': interrupt, 'new_control': new_control, 'quick_ask': quick_ask})
ACTIONS['concept_chat'] = concept_chat  # F86


def delete_chats(names: list | None = None) -> dict:
    """F118: the run page's chat delete: end each named control session (`control.end_control`) so it drops off
    the chat list."""
    names = [n for n in (names or []) if isinstance(n, str)]
    if not names:
        return {'ok': False, 'code': 2, 'out': 'delete_chats: no chats named', 'argv': []}
    bad = [n for n in names if not re.fullmatch(r'c\d+', n)]
    if bad:
        return {'ok': False, 'code': 2, 'out': f'delete_chats: not a chat: {", ".join(bad)}', 'argv': []}
    from agent_runner import control as K
    gone = [n for n in names if K.end_control(int(n[1:]), 'deleted from the run page')]
    left = [n for n in names if n not in gone]
    out = f'deleted {", ".join(gone)}' if gone else 'nothing deleted'
    return {'ok': True, 'code': 0, 'out': out + (f' ({", ".join(left)} already gone)' if left else ''),
            'deleted': gone, 'argv': []}


ACTIONS['delete_chats'] = delete_chats


# --- F83: the combined run app rework: Needs you Drop and Chat, Rename, Settings, a task's whole text ----------

def pitch_no(pid: str, how: str = 'reopen', tid: str = '', confirm: bool = False, why: str = '') -> dict:
    """F98: Not this on a pitch, for all of it or the one change `tid`: the run undoes it here and reopens or drops
    its task, with the words `why`. After a confirm, as a run control's."""
    from agent_runner import pitch
    if not pitch.PITCH_ID.fullmatch(pid or '') or how not in ('reopen', 'drop') or \
            (tid and not P.TASK_ID.fullmatch(tid)):
        return {'ok': False, 'code': 2, 'out': f'pitch_no: a pitch, reopen or drop, and a task id; not {pid!r} '
                                               f'{how!r} {tid!r}', 'argv': []}
    ask = f'Undo {tid or "all of it"} here and {how} {"its task" if tid else "the tasks"}?'
    if confirm is not True:
        return {'ok': False, 'code': 3, 'out': ask, 'confirm': ask, 'argv': []}
    why = ' '.join((why or '').split())
    r = call((['pitch', 'no', pid, f'--{how}', tid] if tid else
              ['pitch', 'no', pid] + (['--drop', 'all'] if how == 'drop' else [])) + ([f'--why={why}'] if why else []))
    if r['ok']:
        r['said'] = f'{tid or pid}: the run undoes it'
        if not pitch.changes_of(pid, state='waiting'):  # the rest of it still waits otherwise
            r['gone'] = pid
    return r


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
    """F76 (C33: here, the one place the terminal UI and the run page both read): a concept's K copy as {'title',
    'intro': [paragraphs], 'options': [{'name', 'body': [...], 'rec'}]}: the options are its headings one level
    below the title's (the first heading), each with what follows it; 'rec' marks the one whose heading says it
    is recommended."""
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


_OPTIONS: dict[str, tuple[float, list]] = {}  # a concept copy's path: (its mtime, its options)


def concept_options(path: str) -> list[dict]:
    """F79: a concept's options, from its local page copy (`concept_page`): [{'name', 'rec'}]; [] for no copy."""
    if not path:
        return []
    try:
        mt = os.path.getmtime(path)
        if (hit := _OPTIONS.get(path)) and hit[0] == mt:
            return hit[1]
        opts = [{'name': o['name'], 'rec': o['rec']}
                for o in concept_page(Path(path).read_text(encoding='utf-8', errors='replace'))['options']]
    except OSError:
        return []
    _OPTIONS[path] = (mt, opts)
    return opts


def need_answers(row: dict) -> list[dict]:
    """C33: the answers that fit a Needs you row, the one rule for the run page, the terminal UI and the chat
    text: [{'label', 'value'}], the first one the main button. Yes / No for a CONFIRM or a yes-or-no ask, a
    concept's options (A, B, C when its copy has none), a pitch's, a DECIDE's (F181c: {name, rec}, the value its bare
    name; F181b: its pick sheet's easy answers too), Done for a blocked item; [] when only a reply fits."""
    label, said = row.get('label', ''), f'{row.get("ask", "")} {row.get("what", "")}'
    if label == 'DECIDE' and any(isinstance(o, dict) for o in row.get('options') or []):
        return [{'label': o['name'] + (' (recommended)' if o.get('rec') else ''), 'value': o['name']}
                for o in row['options']]
    if row.get('options'):
        names = [str(o) for o in row['options']]
    elif label == 'CONFIRM' or re.search(r'\byes\s*(/|or)\s*no\b', said, re.I):
        names = ['Yes', 'No']
    elif label == 'CONCEPT':
        names = [o['name'] for o in concept_options(row.get('copy') or concept_copy(row.get('concept') or ''))] \
            or ['A', 'B', 'C']
    elif label == 'BLOCKED':
        names = ['Done']
    else:
        names = []
    return [{'label': n[:1].upper() + n[1:], 'value': n[:1].upper() + n[1:]} for n in names]


SHEET_GO_LABEL = 'Go with the recommended picks'


def sheet_options(tid: str, text: str = '') -> list[dict]:
    """F181b: the easy answers of `tid`'s pick sheet as a DECIDE's options, each {name, rec, send}, `send` the reply
    that settles the item (`answer_argv`): the recommended picks, and with one question each of its answers. [] with no
    sheet, one that does not read, one that `text` (the task's) says was answered already, or an item with inputs."""
    from agent_runner import sheet
    from agent_runner.brief import has_sheet
    if not has_sheet(tid) or need_detail.asks_file(tid).get('inputs'):
        return []
    try:
        spec = sheet.load(S.C.notes('sheets', f'{tid}.json'))
        qs = sheet.questions(spec)
        # the sheet file outlives its answer, and an old sheet must not answer a new ask
        if 'picks on the sheet:' in text:
            seen = ' '.join(text.split())
            heads = [x.split('): ', 1)[0] for x in (sheet.picks_note({'groups': [{'questions': [q]}]}, {}).split(': ', 1)[1] for q in qs)]
            if all(' '.join(f'{h}): '.split()) in seen for h in heads):
                return []
        out = [{'name': SHEET_GO_LABEL, 'rec': False, 'send': SHEET_GO[0]}]
        if len(qs) == 1:
            q = qs[0]
            names = [' '.join(str(a).replace('`', '').split()) for a in q['answers']]
            if all(0 < len(n) <= need_detail.OPTION_LEN and n.isprintable() for n in names) and \
                    len({n.casefold() for n in [SHEET_GO_LABEL, *names]}) == len(names) + 1:
                out += sorted(({'name': n, 'rec': j == sheet.rec(q), 'send': f'{tid} picks: {q["id"]}={chr(97 + j)}'}
                               for j, n in enumerate(names)), key=lambda o: not o['rec'])
        return out
    except Exception:  # noqa: BLE001 - a sheet that does not read: its page and the reply are still there
        return []


def need_options(row: dict) -> list[str]:
    """F143: the possible answers to a Needs you row for a chat's first message: its answers, else a pick sheet's
    questions with theirs; [] when only a reply fits."""
    if not row.get('picks') and (answers := row.get('answers') or need_answers(row)):  # F181b: a sheet's are its questions
        return [a['label'] for a in answers]
    label = row.get('label', '')
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


def agent_said(tid: str) -> str:
    """F162a2: the last message of the agent that worked on task `tid` (its latest session's transcript), or ''."""
    try:
        from agent_runner.slots import transcript
        from agent_runner.watch import last_session
        if (last := last_session(tid)) and (path := transcript(last[1])):
            if says := [e['text'] for e in feed_entries(tail_rows(path)) if e['kind'] == 'say']:
                return says[-1]
    except Exception:  # noqa: BLE001 - no slot logs, or a transcript that does not read
        pass
    return ''


def agent_last_words(tid: str) -> str:
    """F143: the agent's last message (`agent_said`), else the task's own lines in TODO.md, uncut (what it blocked
    with); '' for neither."""
    if said := agent_said(tid):
        return said
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
    if not TASK_ID.fullmatch(tid or '') and need_label(tid) not in ('PITCH', 'TOOL'):
        return {'ok': False, 'code': 2, 'out': f'need_chat: a task id (F83), not {tid!r}', 'argv': []}
    from agent_runner.status import waiting_ok
    rows, _ = needs_rows(waiting_ok(), dt.datetime.now())
    row = next((r for r in rows if r['id'] == tid), None)
    if row is None:
        return {'ok': False, 'code': 1, 'out': f'{tid} no longer needs you (answered already?)', 'argv': []}
    return new_control(need_chat_text(row), wait)


def close_session(tid: str, wait: bool = True) -> dict:
    """C35: close control session `tid` (c6): its process goes, its transcript stays (`control.close_from_tui`)."""
    from agent_runner import control as K
    return K.close_from_tui(int(tid[1:]))


# what a run control with an 'fn' runs, given the row's id and `wait` (C35)
ROW_FNS = {'need_chat': need_chat, 'concept_chat': lambda tid, wait: concept_chat(tid, wait=wait),
           'close_session': close_session}


def rename_chat(chat: str, title: str) -> dict:
    """F129: the person's own name for control session `chat` (c6): `control --rename N NAME`."""
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


def need_why(tid: str) -> dict:
    """F162: why a Needs you item waits, for its popup: the agent's last words (`agent_said`), '' when it left no session."""
    if not TASK_ID.fullmatch(tid or ''):
        return {'ok': False, 'id': tid, 'out': f'a task id (F83), not {tid!r}'}
    return {'ok': True, 'id': tid, 'text': agent_said(tid)}


def settings() -> dict:
    """F97: every setting, its value, source and default (`config.settings_snapshot`), read from the files now."""
    from agent_runner import config as CF
    snap, was = CF.settings_snapshot(S.ROOT), SETTINGS_AT[0]
    now = _setting_values(snap)
    snap['waits'] = [f'{t}.{k}' for (t, k), v in now.items() if was and (t, k) not in CF.SETTING_NOW and was.get((t, k)) != v]
    return snap


SETTINGS_AT: list[dict] = [{}]  # F166: the settings as this process read them at its start: one that differs now waits


def _setting_values(snap: dict) -> dict:
    return {(t['table'], k['key']): k['value'] for t in snap['tables'] for k in t['keys']}


def settings_start() -> None:
    """F166: the run's web server starts: keep what its settings are now (`settings`' `waits`)."""
    from agent_runner import config as CF
    SETTINGS_AT[0] = _setting_values(CF.settings_snapshot(S.ROOT))


_SETTING_LOCK = threading.Lock()  # two pages saving at once: one read and write of the file at a time


def _setting_done(table: str, key: str, value=None, unset: bool = False) -> dict:
    from agent_runner import config as CF
    try:
        with _SETTING_LOCK:
            f = CF.save_local_setting(S.ROOT, table, key, value, unset)
    except (ValueError, OSError) as e:
        return {'ok': False, 'code': 2, 'out': str(e), 'argv': []}
    if bad := _setting_now(table, key, f.name):
        return bad
    return {'ok': True, 'code': 0, 'out': f'{_setting_said(table, key, value, unset)} in {f.name}', 'argv': []}


def _setting_said(table: str, key: str, value, unset: bool) -> str:
    from agent_runner import config as CF
    return f'[{table}] {key} is reset' if unset else f'[{table}] {key} = {CF.toml_value(value)}'


def _setting_row(table: str, key: str) -> dict:
    return next(k for t in settings()['tables'] if t['table'] == table for k in t['keys'] if k['key'] == key)


def _setting_now(table: str, key: str, name: str) -> dict | None:
    """A setting that applies now: the run that is up is told; its result when it did not take it."""
    from agent_runner import config as CF
    if (table, key) not in CF.SETTING_NOW or not S.run_up():
        return None
    r = call(['slots', str(_setting_row(table, key)['value'])])
    return None if r['ok'] else {**r, 'out': f'saved in {name}, but the run did not take it: {r["out"]}'}


def setting_device(table: str, key: str, value=None) -> dict:
    """F97: save a This device value: one key of runner.local.toml, in place, at once."""
    return _setting_done(table, key, value)


def setting_reset(table: str, key: str) -> dict:
    """F97: clear a device override: the key leaves runner.local.toml."""
    return _setting_done(table, key, unset=True)


SETTING_SETTLE = 0.4  # s a save for everyone waits for others, so that rapid ones are one commit
SETTING_WAIT = 60.0  # s it waits for a merge that is landing
_SETTING_QUEUE: list[dict] = []  # the saves not written yet, oldest first
_SETTING_WRITE = threading.Lock()  # one batch of them at a time


def setting_project(table: str, key: str, value=None, unset: bool = False) -> dict:
    """F173: save a value for everyone (`unset`: take it out): one key of runner.toml, in place, committed alone and
    pushed at once (`_save_project`). Saves that come together are one commit."""
    from agent_runner import config as CF
    if unset and key not in CF.DEFAULTS.get(table, {}):
        return {'ok': False, 'code': 2, 'out': f'[{table}] {key} is not a setting', 'argv': []}
    if problem := '' if unset else CF.setting_check(S.ROOT, table, key, value):
        return {'ok': False, 'code': 2, 'out': problem, 'argv': []}
    mine = {'table': table, 'key': key, 'value': value, 'unset': unset, 'got': None}
    with _SETTING_LOCK:
        _SETTING_QUEUE.append(mine)
    with _SETTING_WRITE:
        if mine['got'] is None:  # not taken along by the save before it
            time.sleep(SETTING_SETTLE)
            batch: list[dict] = []
            try:
                _save_project(batch)
            except Exception as e:  # noqa: BLE001 - every save of the batch hears of it
                for x in batch:
                    x['got'] = x['got'] or {'ok': False, 'code': 1, 'out': f'not saved: {e}', 'argv': []}
    return mine['got'] or {'ok': False, 'code': 1, 'out': 'not saved', 'argv': []}


def _setting_push() -> str:
    """Push the commit as a plan edit is: what there is to say of it, '' when pushed (or nowhere to push)."""
    try:
        why = P._push(S.ROOT)
    except (Exception, SystemExit) as e:  # noqa: BLE001 - it is committed: never 'not saved'
        why = f'{type(e).__name__}: {e}'
    if why:
        return f'saved here, not pushed: {why}'
    return 'saved here; it is pushed with the next change you approve' if S.C.approve and S.C.push_remote else ''


def _save_project(batch: list[dict]) -> None:
    """Write the waiting saves (into `batch`) to runner.toml as one commit on the shared branch and push it as a plan
    edit is; each gets its result as `got`. It holds LANDING, which every merge takes to move the main checkout, and not
    MERGE: that one is held through a whole test gate, and a save must not wait an hour. A merge that is testing takes
    the commit in as it does any other the branch gets meanwhile."""
    from agent_runner import config as CF
    if not (free := S.LANDING.acquire(timeout=SETTING_WAIT)):
        why = 'a merge is landing and has not finished. Nothing was changed'
    with _SETTING_LOCK:
        batch[:] = _SETTING_QUEUE
        _SETTING_QUEUE.clear()
    bad = lambda x, why: x.update(got={'ok': False, 'code': 1, 'out': why, 'argv': []})  # noqa: E731
    try:
        f = CF.config_file(S.ROOT) or CF.main_checkout(S.ROOT) / 'runner.toml'
    except SystemExit as e:  # AGENT_RUNNER_CONFIG names a file that is gone
        why = f'{e}. Nothing was changed'
        if free:
            S.LANDING.release()
        free = False
    if not free:
        for x in batch:
            bad(x, why)
        return
    last = {(x['table'], x['key']): x for x in batch}  # the newest save of a key wins

    def edit(data: bytes) -> tuple[bytes, str]:
        done = []
        for x in last.values():
            try:
                data = CF.setting_edit(data, x['table'], x['key'], x['value'], x['unset'], f.name)
            except ValueError as e:
                bad(x, str(e))
                continue
            done.append(x)
        said = '; '.join(_setting_said(x['table'], x['key'], x['value'], x['unset']) for x in done)
        short = said if len(said) <= 100 else ', '.join(f'[{x["table"]}] {x["key"]}' for x in done)
        return data, f'settings: {short}'
    try:
        ok, note = plansync.commit_file(S.ROOT, f, edit, S.default_branch())
        if ok and not note:  # committed; the push in LANDING too: it may rebase the main checkout when no run is up
            note = _setting_push()
    except SystemExit as e:  # [git] master_branch is not out in the main checkout
        ok, note = False, f'{e}. Nothing was changed'
    finally:
        S.LANDING.release()
    if not ok:
        for x in last.values():
            if x['got'] is None:
                bad(x, note)
    else:
        if note == 'nothing to change':
            note = ''
        for x in last.values():
            if x['got'] is None:
                row = _setting_row(x['table'], x['key'])
                out = f'{_setting_said(x["table"], x["key"], x["value"], x["unset"])} in {f.name}'
                if note:
                    out += f' ({note})'
                if row['has_device']:
                    out += f'. This device keeps its own ({CF.toml_value(row["device"])})'
                x['got'] = (None if row['has_device'] else _setting_now(x['table'], x['key'], f.name)) or \
                    {'ok': True, 'code': 0, 'out': out, 'argv': []}
    for x in batch:
        x['got'] = x['got'] or last[(x['table'], x['key'])]['got']


ACTIONS.update({'pitch_no': pitch_no, 'need_chat': need_chat, 'rename_chat': rename_chat,
                'setting_device': setting_device, 'setting_reset': setting_reset, 'setting_project': setting_project})
