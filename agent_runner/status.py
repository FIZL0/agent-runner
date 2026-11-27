"""What the run tells a person: status, since and follow, Needs you lines."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import time

from agent_runner import pitch, plan as P, pr_rows, shared_tools, theme, until_watch
from agent_runner.config import shown_cmd
from agent_runner.state import C, default_branch, git, project
from agent_runner.state import (EV_DEFERRED, EV_DROPPED, EV_HELD, EV_IDLE, EV_LANDED, EV_LEFT, EV_NO_COMMITS,
    EV_PARKED, EV_PART, EV_RELEASED, EV_STALLED, EV_STARTED, EV_STOP_ASKED, EV_STOP_BACK, EV_STOPPED)
from agent_runner.state import EV_DRIFT
from agent_runner.state import EV_DEVICE
from agent_runner.state import EV_CONTEXT
from agent_runner.state import EV_AUTO_AUDIT, EV_AUTO_RELEASE, EV_FILE_SPLIT
from agent_runner.brief import has_sheet
from agent_runner.land import wip_lines
from agent_runner.land import no_gate_line
from agent_runner.whole_write import write_whole


def tasks_left(ls: list[str]) -> tuple[int, int]:
    """(tasks left, how many of those are blocked) in TODO.md's lines `ls`: the open and blocked top-level tasks,
    not those under a section a run never starts (Parked, where `--pri later` files, and Stretch), nor shelved
    ones (`plan shelve`: blocked, off Needs you until a person brings them back)."""
    rows = _counted(ls)
    return len(rows), sum(box == '~' for box, _, _ in rows)


GROUP_WORDS = (('start', 'can start now'), ('running', 'running now'), ('wait', 'wait on another task'),
               ('check', 'wait on a check'), ('needs', 'need you'), ('held', 'held for another reason'))


def _counted(ls: list[str]) -> list[tuple[str, str, int]]:
    """(box, id, index) of each task the tasks left count counts: open or blocked top-level tasks, not in Parked
    or Stretch, not shelved, and not a split task's own line while any of its parts is still open (B816)."""
    rows = [(box, tid, i) for section, box, tid, _, i in P.iter_tasks(ls)
            if box in ' ~' and not section.startswith(P.SKIPPED) and not P._shelved(ls, i)]
    ids = {tid for _, tid, _ in rows}
    return [(box, tid, i) for box, tid, i in rows
            if not (P.SPLIT.search(ls[i]) and P.subtasks(tid, ls[i], ids))]


def task_groups(ls: list[str], running=()) -> dict[str, int]:
    """F440: how the tasks left divide, each task counted once: `start` (open, nothing it waits on still open),
    `running` (a slot or a taken session has it: ids in `running`), `wait` (an `after:` or `(after …)` task
    still open), `check` (blocked on an --until check), `needs` (blocked on a person, as Needs you has it) and
    `held` (blocked for any other reason). Zero groups are left out."""
    open_ = P.open_ids(ls)
    out: dict[str, int] = {}
    for box, tid, i in _counted(ls):
        if tid in running:
            g = 'running'
        elif box == '~' and P._on_person(ls, i):
            g = 'needs'
        elif box == '~' and P.until_of(ls, i):
            g = 'check'
        else:
            tail = ls[i + len(P._item_block(ls, i)) - 1]
            after = [t.strip() for w in P.WAITS.findall(tail)[-1:] for t in w.split(',')] if box == '~' else []
            waits = [t for t in dict.fromkeys(P.waits_on(ls, i) + P.resolve_after(ls, i, after))
                     if t in open_ and t != tid]
            g = 'wait' if waits else 'start' if box == ' ' else 'held'
        out[g] = out.get(g, 0) + 1
    return out


def groups_text(groups: dict[str, int]) -> str:
    """'23 tasks left: 6 can start now, 12 wait on another task, 5 need you' ('0 tasks left' for none)."""
    left = sum(groups.values())
    parts = [f'{groups[g]} {w}' for g, w in GROUP_WORDS if groups.get(g)]
    return f'{left} task{"" if left == 1 else "s"} left' + (': ' + ', '.join(parts) if parts else '')


def _running_ids() -> set[str]:
    """The ids a slot runs (STATE) or a person's session has taken."""
    from agent_runner.sched import taken  # here, not at the top: as merge and land do
    ids: set[str] = set()
    try:
        ids |= {str(v) for v in (json.loads(C.notes('STATE').read_text(encoding='utf-8')).get('running') or {}).values() if v}
    except (OSError, ValueError, AttributeError):
        pass
    try:
        ids |= set(taken())
    except (OSError, SystemExit):
        pass
    return ids


MERGED_SUBJECT = re.compile(r"^(?:Merge branch '?task/)?([A-Z]+\d+[a-z0-9]*)\b")  # a commit subject's task id


def merges_since(start: dt.datetime) -> int:
    """How many tasks merged since `start` (B78): the distinct task ids the run logged as landed ('<ID>:
    merged, ticked|part') or as merged with the rest blocked ('<ID>: merged, blocked', B85: their code is on the shared
    branch too, as the commit-subject count below has it), so a fast-forward merge counts and a task's two merge commits, or a remerge, count once. With
    no run log (events.jsonl or run.log), the distinct task ids that head the shared branch's first-parent
    commit subjects since `start` ('B45 …', "Merge branch 'task/F33'")."""
    if events_file().exists() or C.notes('run.log').exists():
        local = start.astimezone().replace(tzinfo=None) if start.tzinfo else start  # event stamps: local time
        first = local.isoformat(timespec='seconds')
        return len({ev['id'] for ev in read_events()
                    if ev['kind'] in (EV_LANDED, EV_PART) and ev.get('id') and ev['time'][:19] >= first})
    try:
        branch = default_branch()
    except SystemExit:  # a misconfigured [git] master_branch: status still answers, counting HEAD
        branch = 'HEAD'
    r = git('log', '--first-parent', f'--since={start.isoformat(timespec="seconds")}', '--format=%s', branch)
    if r.returncode != 0:
        return 0
    return len({m[1] for s in r.stdout.splitlines() if (m := MERGED_SUBJECT.match(s))})


def progress_line(window: str = '24h', now: dt.datetime | None = None) -> str:
    """'merged 11 in the last 24h · 23 tasks left (2 blocked)': the line `status` and the control sessions'
    opening headline give for how the run is getting on."""
    now = now or dt.datetime.now()
    start = since_start(window, None, now)
    if start.tzinfo is None:
        start = start.astimezone()  # local time, as git reads a --since with no zone
    w = window.strip()
    span = f'in the last {w}' if re.fullmatch(r'\d+(?:\.\d+)?\s*[a-zA-Z]+', w) else \
        'today' if w.lower() == 'today' else f'since {w}'
    return f'merged {merges_since(start)} {span} · ' + groups_text(task_groups(P.lines(C.todo), _running_ids()))


RELEASE_TASK = re.compile(r'\W*(?:\(alone\)\s*)?(?:release\b|cut (?:a|the next) (?:release|version)\b)',
                          re.I)  # F130: after its `(alone)` tag


def release_line(ls: list[str], st: dict | None = None, rows=None) -> str:
    """F185: 'release: ' and its words for each release (`ui_model.release_rows`, built from STATE `st`, read
    when None; `rows` given: those), as the run page and the TUI say it: 'release: V5 Release · waits for 2: F1
    one, F2 two', 'release: Next release · auto at 10 landed: 6/10'. Then 'release: waits on 7 of 25 tasks (T5)'
    for each other queued release task in TODO.md's lines `ls` (not kind V; one whose title starts "Release"
    or "Cut the next version"): of the tasks it waits on (its last block's `(after …)`, else its `after:`
    field), how many are still open. '' when there is none. A task whose `after:` says `all above` (`plan add
    --last`, F43) gets a line too, 'last:' unless it is a release, naming what holds it. F193: with `[run] releases` off, the 'last:'
    lines alone."""
    from agent_runner import ui_model as U
    from agent_runner.autorelease import releases_on
    if st is None:
        st = U._state(U.S.run_up()) if U.S.C else {}  # before `state.init`: the plan's lines alone
    if rows is None:
        rows = U.release_rows(ls, st)
    live, out, away = P.open_ids(ls), [f'release: {r["text"]}{r.get("note", "")}' for r in rows], None
    shown, on = {r['id'] for r in rows}, releases_on()
    for section, box, tid, rest, i in P.iter_tasks(ls):
        last = P.LAST in P.fields(ls[i]).get('after', []) or (box in ' ~' and P._waits_all(ls, i))
        if tid in shown:  # said by its row
            continue
        if box not in ' ~' or section.startswith(P.SKIPPED) or not (RELEASE_TASK.match(rest) or last):
            continue
        kind = 'release' if RELEASE_TASK.match(rest) or P.release(tid) else 'last'
        if kind == 'release' and not on:  # F193
            continue
        if checks := P.until_of(ls, i):  # F427b
            out.append(f'{kind}: waits for {P.until_label(checks, C)} ({tid})')
            continue
        if P._waits_all(ls, i):  # `after: all` (F35): a count of what is still before it, not an id list
            held = [t for t in P.before_all(ls, i) if t in live and t != tid]
            skipped = P.not_waiting_on(ls, i)  # B101, B207: said, not waited on
            hand = []
            if P.release(tid) and P.ALL in P.fields(ls[i]).get('after', []):  # B107: a taken task lands after
                if away is None:
                    from agent_runner.sched import taken
                    away = set(taken())
                hand = [t for t in held if t in away]
                held = [t for t in held if t not in away]
            said = P.not_waiting(skipped) + taken_note(hand)
            out.append(f'{kind}: {P.all_line(tid, len(held), skipped)}{taken_note(hand)}' if held
                       else f'{kind}: ready, nothing left to wait on ({tid}){said}')
            continue
        w = P.WAITS.findall(' '.join(P._item_block(ls, i))) if box == '~' else []
        ids = [t.strip() for t in w[-1].split(',') if t.strip()] if w else P.waits_on(ls, i)
        ids = [t for t in dict.fromkeys(ids) if t != tid]
        held = [t for t in ids if t in live]
        named = f': {", ".join(held[:6])}{" …" if len(held) > 6 else ""}' if last and not w else ''
        said = P.not_waiting(P.not_waiting_on(ls, i)) if last and not w else ''  # B207
        out.append((f'{kind}: waits on {len(held)} of {len(ids)} task{"" if len(ids) == 1 else "s"} ({tid}){named}'
                    if held else f'{kind}: ready, nothing left to wait on ({tid})') + said)
    return '\n'.join(out)


def taken_note(ids) -> str:
    """'; not waiting on: R67 (taken by hand)' for the tasks taken by hand an `after: all` release passes over
    (B107): their work lands in the next release. '' for none."""
    return f'; not waiting on: {", ".join(ids)} (taken by hand)' if ids else ''


# --- run events (F41): <notes>/events.jsonl, and run.log lines from before it ----------------------------

LATELY = (EV_LANDED, EV_PART, EV_PARKED, EV_LEFT, EV_STOPPED, EV_IDLE, EV_AUTO_RELEASE, EV_FILE_SPLIT, EV_AUTO_AUDIT)  # what `status` lists under "lately"
ENDS = (EV_LANDED, EV_PART, EV_PARKED, EV_LEFT, EV_NO_COMMITS, EV_DEFERRED, EV_DROPPED)  # a task a stopping run no longer waits for
SAID = {  # event kind -> the phrase since, follow and status start its line with
    EV_LANDED: 'landed', EV_PART: 'part landed, rest stuck', EV_PARKED: 'stuck, not merged', EV_LEFT: 'needs you',
    EV_STALLED: 'looks stuck', EV_STARTED: 'started', EV_HELD: 'run held, needs you',
    EV_IDLE: 'run idle: nothing left it may start', EV_STOPPED: 'run stopped', EV_STOP_ASKED: 'stop requested',
    EV_STOP_BACK: 'stop taken back'}

SINCE_LINE = re.compile(r'^=== (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S* (.*)$')
_ID = r'([A-Za-z]+\d+[a-z0-9]*)'
LEGACY = [  # a run.log line written before events.jsonl (F41): (pattern on its message, event kind, its fields)
    (re.compile(rf'^{_ID}: merged, (?:ticked|part)'), EV_LANDED, ('id',)),
    (re.compile(rf'^{_ID}: merged, blocked'), EV_PART, ('id',)),
    (re.compile(rf'^{_ID}: not merged, parked as \S+ — (.*)'), EV_PARKED, ('id', 'why')),
    (re.compile(rf'^{_ID}: LEFT FOR A HUMAN — (.*)'), EV_LEFT, ('id', 'why')),
    (re.compile(rf'^{_ID}: no commits — '), EV_NO_COMMITS, ('id',)),
    (re.compile(rf'^{_ID}: the run stops; '), EV_DEFERRED, ('id',)),
    (re.compile(rf'^dropped {_ID}; '), EV_DROPPED, ('id',)),
    (re.compile(rf'^slot \d+: {_ID} looks stalled'), EV_STALLED, ('id',)),
    (re.compile(rf'^slot \d+: {_ID} \([^;)]*;'), EV_STARTED, ('id',)),
    (re.compile(r'^STOPPED: (.+)'), EV_HELD, ('why',)),
    (re.compile(r'^run idle'), EV_IDLE, ()),
    (re.compile(r'^run stopped'), EV_STOPPED, ()),
    (re.compile(r'^\S+ v?\d+(?:\.\d+)+ released\b'), EV_RELEASED, ()),
    (re.compile(r'^stop asked for:.*?\b(\d+) left before the run exits$'), EV_STOP_ASKED, ('left',)),
    (re.compile(r'^stop taken back\b'), EV_STOP_BACK, ()),
]


def legacy_event(line: str) -> dict | None:
    """A run.log line from before events.jsonl as the event it logged, or None (also for a line no reader wants)."""
    if not (m := SINCE_LINE.match(line)):
        return None
    stamp, msg = m.groups()
    for rx, kind, names in LEGACY:
        if e := rx.match(msg):
            ev = {'time': stamp, 'kind': kind, 'id': '', 'text': msg}
            ev.update(zip(names, e.groups()))
            if 'left' in ev:
                ev['left'] = int(ev['left'])
            return ev
    return None


def as_event(item) -> dict | None:
    """An event from what a reader was handed: an events.jsonl record (a dict, or its JSON line) or a run.log line."""
    if isinstance(item, dict):
        return item if item.get('kind') and item.get('time') else None
    if item.startswith('{'):
        try:
            ev = json.loads(item)
        except ValueError:
            return None
        return ev if isinstance(ev, dict) and ev.get('kind') and isinstance(ev.get('time'), str) else None
    return legacy_event(item)


def event_stamp(item) -> str | None:
    """The ISO stamp of a run.log line or an event, whatever it says; None when it has none."""
    if isinstance(item, str) and (m := SINCE_LINE.match(item)):
        return m[1]
    ev = as_event(item)
    return ev['time'][:19] if ev else None


def events_file():
    return C.notes('events.jsonl')


def read_events() -> list[dict]:
    """Every run event, oldest first: events.jsonl's records, after the events of run.log lines older than its
    first (a run.log from before events.jsonl, F41)."""
    evs = []
    try:
        evs = [e for l in events_file().read_text(encoding='utf-8', errors='replace').splitlines()
               if (e := as_event(l))]
    except OSError:
        pass
    first = evs[0]['time'][:19] if evs else None
    try:
        old = C.notes('run.log').read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        old = []
    if first:  # the run.log lines before events.jsonl began; after that, its records say it all
        old = [l for l in old if (m := SINCE_LINE.match(l)) and m[1] < first]
    return [e for l in old if (e := legacy_event(l))] + evs


# --- since: what happened since the person last looked ----------------------------------------------------

def since_event(item, titles: dict[str, str]) -> tuple[str, str, str] | None:
    """An event (or a run.log line, `as_event`) as (its ISO stamp, the task id or '', one plain phrase:
    "landed: <title> [F5]"), or None when it is not something a person wants told. Read from the event's kind,
    id and fields, never its text, so rewording a log message changes nothing here (F41)."""
    if not (ev := as_event(item)):
        return None
    stamp, kind, tid = ev['time'][:19], ev['kind'], ev.get('id') or ''
    if kind == EV_RELEASED:
        return stamp, '', str(ev.get('text', '')).strip()
    if kind == EV_AUTO_RELEASE and tid:  # F63: 'queued V5 (auto_release: 10 landed)'
        return stamp, tid, f'queued {tid} (auto_release: {ev.get("why") or "?"})'
    if kind == EV_AUTO_AUDIT and tid:  # F417: 'queued R5 (auto_audit: 50 landed)'
        return stamp, tid, f'queued {tid} (auto_audit: {ev.get("why") or "?"})'
    if kind == EV_FILE_SPLIT and tid:  # F200b: 'queued C9 to split a.py: 3 ready tasks wait for it'
        return stamp, tid, f'queued {tid} to split {ev.get("file") or "?"}: {ev.get("waiters", 0)} ready tasks wait for it'
    if kind in (EV_DRIFT, EV_DEVICE):  # B45: 'needs you: Claude Code X changed Y; Z no longer works'; C27: 'needs you: box: CPU at 95°C'
        return stamp, '', f'{SAID[EV_LEFT]}: {str(ev.get("text", "")).strip()}'
    if kind == shared_tools.EV_TOOL:  # F168: 'needs you: Connect the iPhone 15 by USB: 2 tasks wait [tool-iphone15]'
        return stamp, '', f'{SAID[EV_LEFT]}: {str(ev.get("text", "")).strip()}'
    if kind == shared_tools.EV_MEMORY:  # B184: no Needs you item: 'B392 stopped for low memory 3 times; it goes on …'
        return stamp, tid, str(ev.get('text', '')).strip()
    if kind == pitch.EV_PITCH:  # F98: 'needs you: Approve 2 changes to push: … [pitch1]'
        return stamp, '', f'{SAID[EV_LEFT]}: {str(ev.get("text", "")).strip()}'
    if kind == EV_CONTEXT and tid:  # F25: 'B32 peaked 168k (over 150k): runner.py 61k, test_runner.py 22k'
        top = str(ev.get('top') or '')
        return stamp, tid, f'{tid} peaked {ev.get("peak")}k (over {ev.get("warn")}k)' + (f': {top}' if top else '')
    if kind not in SAID:
        return None
    said = SAID[kind]
    if kind == EV_STOP_ASKED:
        return stamp, '', f'{said}: {ev.get("left", 0)} left before the run exits'
    if kind == EV_STOP_BACK:
        return stamp, '', f'{said}: the run is starting tasks again'
    if kind == EV_HELD:
        return stamp, '', f'{said}: {str(ev.get("why", "")).split(":")[0].strip()}'
    if kind in (EV_IDLE, EV_STOPPED):
        return stamp, '', said
    if not tid:
        return None
    why = str(ev.get('why') or '')
    why = f' ({why.split(". ")[0][:60].rstrip(" .")})' if why else ''
    return stamp, tid, f'{said}: {titles.get(tid) or tid}{why} [{tid}]'


def since_start(arg: str | None, mark: str | None, now: dt.datetime) -> dt.datetime:
    """Where `since` starts: `arg` ("2h", "30m", "1d", "today", "yesterday", or a date/time), else the mark
    the last `since` left, else 24 hours back."""
    if not arg:
        try:
            return dt.datetime.fromisoformat(mark) if mark else now - dt.timedelta(hours=24)
        except ValueError:
            return now - dt.timedelta(hours=24)
    a = arg.strip().lower()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if a == 'today':
        return midnight
    if a == 'yesterday':
        return midnight - dt.timedelta(days=1)
    if m := re.fullmatch(r'(\d+(?:\.\d+)?)\s*(m|min|mins|h|hr|hrs|hours?|d|days?|w|weeks?)', a):
        n, u = float(m[1]), m[2][0]
        return now - dt.timedelta(**{{'m': 'minutes', 'h': 'hours', 'd': 'days', 'w': 'weeks'}[u]: n})
    try:
        return dt.datetime.fromisoformat(arg.strip())
    except ValueError:
        raise SystemExit(f'{shown_cmd()} since: {arg!r} is not a time: 2h, 30m, 1d, today, yesterday, or 2026-11-19T14:00')


def when(stamp: str, now: dt.datetime) -> str:
    """An ISO stamp as a person reads it: "14:05" today, "yesterday 21:02", else "11-17 21:02"."""
    t = dt.datetime.fromisoformat(stamp)
    days = (now.date() - t.date()).days
    return t.strftime('%H:%M') if days == 0 else ('yesterday ' if days == 1 else t.strftime('%m-%d ')) + t.strftime('%H:%M')


def since_text(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
               since_mark: bool = False, waiting=None, wips=None, digest: bool = False) -> tuple[str, str | None]:
    """(what `since` prints, the newest stamp it read or None): the concepts waiting for the person's OK first
    (`waiting`, however old), then each event after `start`, oldest first, one short line each; or one line
    saying there is nothing new. `digest` (B88, `since` without --all): the events folded by `since_digest`."""
    text, last = (since_digest if digest else _since_events)(log_lines, start, titles, now, since_mark)
    return '\n'.join([*waiting_text(waiting, now=now, wips=wips), text]), last


def _since_events(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
                  since_mark: bool) -> tuple[str, str | None]:
    out, last = [], None
    for l in log_lines:
        if not (stamp := event_stamp(l)):
            continue
        try:
            if dt.datetime.fromisoformat(stamp) <= start:
                continue
        except ValueError:
            continue
        last = stamp
        if e := since_event(l, titles):
            out.append(f'  {when(e[0], now)}  {e[2]}')
    head = f'since {when(start.isoformat(timespec="seconds"), now)}' + (' (your last look)' if since_mark else '')
    return (f'{head}:\n' + '\n'.join(out) if out else f'nothing new {head}'), last


DIGEST_CAP = 10  # B88: titled lines a since digest shows before it names the rest by id
DIGEST_WIDTH = 70  # B88: a run line (a release's words) cut to this in the digest
DIGEST_RUN = 3  # B88: the run lines (releases, holds) a digest shows, newest
DIGEST_STUCK = (EV_PART, EV_PARKED, EV_LEFT, EV_STALLED)  # a task's last state the digest lists under Stuck


# B89: the cut digest's last line. The person may be in the Claude app or on a phone, where no command runs, so
# it reads as an ask; the control session answers it with `since --all` handed over as a page (guide.py).
DIGEST_MORE = 'more: ask for the full list'


def since_digest(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
                 since_mark: bool = False, cap: int = DIGEST_CAP) -> tuple[str, str | None]:
    """B88 `since`'s default: the events after `start` folded into a digest short enough to say back on a
    phone: a headline count, then one line per task with its last state under the summary's headings (Started
    and Landed newest first, Stuck), then the run's own lines (releases, a hold, its last state); run idle / stopped
    repeats and restarts fold away. At most `cap` titled lines: past that, Landed names the rest by id only (each
    landed task named once) and other groups count them, then DIGEST_MORE (B89: an ask, never a command)."""
    tasks: dict[str, tuple[str, str, str]] = {}  # id -> (stamp, kind, phrase without its state word)
    run_lines: list[str] = []
    run_state, last = '', None
    for l in log_lines:
        if not (stamp := event_stamp(l)):
            continue
        try:
            if dt.datetime.fromisoformat(stamp) <= start:
                continue
        except ValueError:
            continue
        last = stamp
        if not (e := since_event(l, titles)) or not (ev := as_event(l)):
            continue
        kind, tid = ev['kind'], e[1]
        if kind == EV_CONTEXT:
            continue  # a session's size: the full log has it
        if tid and kind in SAID:
            phrase = e[2].removeprefix(f'{SAID[kind]}: ')
            if kind == EV_LEFT:
                phrase = f'{SAID[EV_LEFT]}: {phrase}'
            tasks.pop(tid, None)  # re-insert: the dict keeps the order of each task's last event
            tasks[tid] = (e[0], kind, phrase)
        elif kind in (EV_IDLE, EV_STOPPED, EV_STOP_ASKED, EV_STOP_BACK):
            run_state = f'{e[2]} ({when(e[0], now)})'
        else:  # released, held, Claude Code drift
            said = e[2] if len(e[2]) <= DIGEST_WIDTH else e[2][:DIGEST_WIDTH - 1].rstrip() + '…'
            line = f'{said} ({when(e[0], now)})'
            if line not in run_lines:
                run_lines.append(line)
    head = f'since {when(start.isoformat(timespec="seconds"), now)}' + (' (your last look)' if since_mark else '')
    if not tasks and not run_lines and not run_state:
        return f'nothing new {head}', last
    groups = [('Started', [t for t, v in reversed(tasks.items()) if v[1] == EV_STARTED]),
              ('Landed', [t for t, v in reversed(tasks.items()) if v[1] == EV_LANDED]),
              ('Stuck', [t for t, v in tasks.items() if v[1] in DIGEST_STUCK])]
    counts = [f'{len(ids)} {name.lower()}' for name, ids in groups if ids]
    out = [f'{head}: ' + (', '.join(counts) if counts else 'no task news')]
    room, shown = cap, {}
    for name, ids in sorted(groups, key=lambda g: ('Stuck', 'Started', 'Landed').index(g[0])):  # the cap spares Stuck first
        shown[name] = ids[:max(room, 0)]
        room -= len(shown[name])
    cut = False
    for name, ids in groups:
        if not ids:
            continue
        out.append(f'{name}:')
        out += [f'  {tasks[t][2]}' for t in shown[name]]
        rest = ids[len(shown[name]):]
        if rest:
            cut = True
            out.append(f'  …and {len(rest)} more: {", ".join(rest)}' if name == 'Landed' else f'  …and {len(rest)} more')
    if len(run_lines) > DIGEST_RUN:  # many releases or holds: the newest, then a count
        cut = True
        run_lines = [f'…and {len(run_lines) - DIGEST_RUN} earlier', *run_lines[-DIGEST_RUN:]]
    if run_state:
        run_lines.append(f'last: {run_state}')
    if run_lines:
        out.append('Run:')
        out += [f'  {l}' for l in run_lines]
    if cut:
        out.append(DIGEST_MORE)
    return '\n'.join(out), last


def since_mark_file() -> Path:
    return C.notes('since.last')


def move_since_mark(stamp: str) -> None:
    """Move `<notes>/since.last` forward to `stamp` (never back: a `since yesterday` does not show again what
    the last look saw)."""
    f = since_mark_file()
    try:
        old = f.read_text(encoding='utf-8').strip()
        if old and dt.datetime.fromisoformat(old) >= dt.datetime.fromisoformat(stamp):
            return
    except (OSError, ValueError):
        pass
    write_whole(f, f'{stamp}\n'.encode('utf-8'))


def what_changed(tid: str) -> str:
    """The first sentence of the commit subject a task landed with (its `done` message), without the id; ''."""
    r = git('log', '-n', '1', '-E', f'--grep=^{re.escape(tid)}( |:|$)', '--format=%s', 'HEAD')
    subj = r.stdout.strip() if not r.returncode else ''
    subj = re.sub(rf'^{re.escape(tid)}[: ]\s*', '', subj)
    subj = re.split(r'(?<=[.;:])\s|\s—\s|, (?=and |so |which )', subj, maxsplit=1)[0].rstrip(' .;:')
    return subj if len(subj) <= 100 else subj[:99].rsplit(' ', 1)[0] + '…'


NEEDS_YOU = ('needs you', 'looks stuck', 'run held, needs you',
             'stuck, not merged')  # since_event kinds only a person can clear (B32: a parked task too)


def needs_you_line(line, titles: dict[str, str], now: dt.datetime, waiting) -> str | None:
    """An event (or run.log line) as `since --follow --needs-you` prints it, or None when it does not need the person: the run
    held (STOPPED, with what holds it), a task left for a human, one that looks stalled, and a task that landed
    or blocked waiting on a person's answer (a CONFIRM/DECIDE/BLOCKED ask, or a concept page waiting for an OK:
    `waiting` is `waiting_ok()`'s list, read after the line was logged)."""
    if not (e := since_event(line, titles)):
        return None
    kind = e[2].split(': ', 1)[0]
    if kind in NEEDS_YOU:
        what = e[2]
        if kind == SAID[EV_HELD] and (ev := as_event(line)):
            held = ': '.join(x for x in (str(ev.get('why') or '').strip(), str(ev.get('detail') or '').strip()) if x)
            what = f'{kind}: {held if len(held) <= 240 else held[:239].rsplit(" ", 1)[0] + "…"}'
        return f'{when(e[0], now)}  {named(what)}'
    if e[1] and kind in ('landed', 'part landed, rest stuck'):
        for label, tid, k, ask, url, title, shelved, *_ in waiting or []:
            if e[1] in (tid, k) and not shelved:  # B27: in everyday words, no caps label
                return f'{when(e[0], now)}  {named(ASK_FEED)}' + '  '.join(
                    x for x in (f'{P.plain_ask(label, ask, title or titles.get(tid) or tid, label == 'DECIDE' and has_sheet(tid))} [{tid}]',
                                url) if x)
    return None


ASK_FEED = 'needs you: '  # how a feed line about an item under Needs you starts (B27; was 'waits for you: ')


def named(what: str) -> str:
    """F33: a Needs you line with its project first ('iFizBox needs you: … [R43]', 'iFizBox: looks stuck: …'),
    so the person knows which project's control session answers it; as is before `init` names one."""
    if not (p := project()):
        return what
    return f'{p} {what}' if what.startswith('needs you') else f'{p}: {what}'


def follow_lines(chunk: str, titles: dict[str, str], now: dt.datetime, needs_you: bool = False,
                 waiting=None, stop: dict | None = None) -> tuple[list[str], str | None]:
    """The lines `since --follow` prints for new run.log text: one plain line per event, a landed task with
    what changed; and the newest stamp read. `needs_you`: only what needs the person (`needs_you_line`).
    F42: once a stop is asked for, each line ends ' · N left': the tasks the stopping run still waits for,
    from the stop line's count less each task that merged, parked or was left since; `stop` keeps that
    count from one chunk to the next (`follow` passes the same dict each time)."""
    out, last = [], None
    stop = {} if stop is None else stop
    for l in chunk.splitlines():
        last = event_stamp(l) or last
        if ev := as_event(l):
            if ev['kind'] == EV_STOP_ASKED:
                stop.clear()
                stop.update(left=int(ev.get('left') or 0), ended=set())
            elif ev['kind'] in (EV_STOP_BACK, EV_STOPPED):
                stop.clear()
            elif 'left' in stop and ev['kind'] in ENDS and (tid := ev.get('id')) and tid not in stop['ended']:
                stop['ended'].add(tid)
                stop['left'] = max(0, stop['left'] - 1)
        left = f' · {stop["left"]} left' if 'left' in stop else ''
        if needs_you:
            if nl := needs_you_line(l, titles, now, waiting):
                out.append(nl + left)
            continue
        if e := since_event(l, titles):
            line = f'{when(e[0], now)}  {e[2]}'
            kind = as_event(l)['kind']
            if e[1] and kind == EV_LANDED and (did := what_changed(e[1])):
                line += f' — {did}'
            out.append(line + ('' if kind == EV_STOP_ASKED else left))
            if waiting and e[1] and kind in (EV_LANDED, EV_PART) \
                    and (nl := needs_you_line(l, titles, now, waiting)):
                out.append(nl + left)  # the full feed carries the asks too
    return out, last


def follow(poll: float = 2.0, until: float | None = None, needs_you: bool = False, mark: bool = True,
           hold=None, end=None) -> int:
    """`since --follow`: print one plain line per new event as run.log gets it, moving the since mark as it
    prints; from the log's end, until killed (or `until`, a monotonic deadline, for tests). `needs_you`: only
    what needs the person (`needs_you_line`), and the mark stays put: the landed and started lines it skips
    are still news for the next `since`. `mark=False` (`--keep-mark`): the mark stays put too.
    `hold` (`--keep-mark`, `board_held`): while it says so, nothing is read or printed; what was logged
    meanwhile prints when it lets go. `end`: stop once it says so."""
    logf = events_file() if events_file().exists() else C.notes('run.log')  # F41: run.log only before events.jsonl
    try:
        pos = logf.stat().st_size
    except OSError:
        pos = 0
    print(f'watching {logf} for what needs you: the run held, a task left for you, stalled, or waiting on your '
          f'answer' if needs_you else
          f'following {logf}: one line per landed, started or stuck task, a release, a stop asked for or taken back '
          f'(then how many tasks are left), and when the run goes idle or stops',
          flush=True)
    buf = ''
    stop: dict = {}  # F42: the stop countdown, carried from one chunk to the next
    while until is None or time.monotonic() < until:
        if end is not None and end():
            return 0
        if hold is not None and hold():
            try:
                time.sleep(poll)
            except KeyboardInterrupt:
                return 0
            continue
        try:
            if logf != events_file() and events_file().exists():  # a run that writes events came up: follow them
                logf, pos, buf = events_file(), 0, ''
            size = logf.stat().st_size
            if size < pos:  # the log was cut or replaced: read it again from the top
                pos = 0
            if size > pos:
                with open(logf, 'rb') as f:
                    f.seek(pos)
                    data = f.read()
                pos += len(data)
                buf += data.decode('utf-8', errors='replace')
                chunk, _, buf = buf.rpartition('\n')
                landed = any((e := as_event(l)) and e['kind'] in (EV_LANDED, EV_PART) for l in chunk.splitlines())
                lines, last = follow_lines(chunk, P.titles(C.done, C.todo), dt.datetime.now(), needs_you,
                                           waiting_ok() if landed else None, stop)
                for l in lines:
                    print(l, flush=True)
                if last and mark and not needs_you:
                    move_since_mark(last)
        except OSError:
            pass
        except KeyboardInterrupt:
            return 0
        try:
            time.sleep(poll)
        except KeyboardInterrupt:
            return 0
    return 0


def waiting_ok() -> list[tuple]:
    """What waits for the person (`plan.asks`, shelved ones too), from the main checkout's TODO.md: concept pages
    and tasks blocked on a person."""
    try:
        if not C.todo.exists():
            return []
        stamps = P.asked_at(C.todo)
        return [(*a, stamps.get(a[1], '')) for a in P.asks(C.todo, all=True)] + pitch.rows(C) + \
            pr_rows.asks(C) + shared_tools.asks(C) + until_watch.asks(C)  # F427c
    except (OSError, SystemExit):
        return []


def waiting_text(waiting, width: int = 60, now: dt.datetime | None = None, wips=None) -> list[str]:
    """B27: 'Needs you:' and per ask one line in everyday words, what is asked and what to
    reply, with its age first ('2h') and its [id] last, then its link on a line of its
    own; in `[run] needs_order` (oldest first); a count of the shelved ones last. [] for none. `waiting` is
    `waiting_ok()`'s list: asks tuples, an `(asked …)` stamp eighth when there is one. No caps labels."""
    if not waiting and not wips:
        return []
    waiting = waiting or []
    cf = P.needs_cfg()
    now = now or dt.datetime.now()
    stamps = {w[1]: w[7] for w in waiting if len(w) > 7 and w[7]}
    out, shelved = [], 0
    for label, tid, k, what, url, title, sh, *_ in P.in_order(waiting, stamps, cf['order']):
        if sh:
            shelved += 1
            continue
        title = title if len(title) <= width else title[:width - 1].rstrip() + '…'
        old = P.age(stamps.get(tid, ''), now) if cf['ages'] else ''
        out.append('  ' + (f'{old:>3}  ' if old else '') +
                   f'{P.plain_ask(label, what, title, label == "DECIDE" and has_sheet(tid))} [{k or tid}]')
        if url:
            out.append(f'    {url}')
    out += wip_lines(wips or [], now)  # F23: a person's edits moved aside, never deleted by the run
    if not out:
        return []  # only shelved ones: they asked to leave this list
    if shelved:
        out.append(shelved_line(shelved))
    return [needs_heading(cf['heading'])] + out


def shelved_line(n: int) -> str:
    """B90: Needs you's count of the shelved asks. A control session relays it to a person who may be in the
    Claude app or on a phone, where no command runs, so there it reads as an ask (the control session answers
    it with `plan waiting --all`); at a terminal it keeps the command."""
    from agent_runner.control import CONTROL_N_ENV  # here, not at the top: control imports much of the runner
    if os.environ.get(CONTROL_N_ENV, '').strip():
        return f'  ({n} shelved: ask to see them)'
    return f'  ({n} shelved: plan waiting --all)'


def needs_heading(heading: str) -> str:
    """F33: Needs you's heading line with its project: 'iFizBox needs you:'; another heading keeps its
    words, the project after it ('Your turn (iFizBox):'); as is before `init` names one."""
    if not (p := project()):
        return f'{heading}:'
    return f'{p} needs you:' if heading.lower() == 'needs you' else f'{heading} ({p}):'


def tool_lines(st: dict) -> list[str]:
    """F168: the Tools line and a line per task a shared tool, or memory (B184), keeps waiting."""
    from agent_runner.sched import taken  # here, not at the top: as merge and land do
    try:
        split = [f'  {t} {said}' for t, said in P.split_waits(
            P.lines(C.todo), busy={*taken(), *(st.get('running') or {}).values()}).items()]  # B196
    except (OSError, AttributeError):  # no plan, or no init
        split = []
    try:
        tools = shared_tools.rows(st=st)
        return [x for x in (shared_tools.line(tools),) if x] + \
            ([f'  {t} {said}' for t, said in shared_tools.wait_words(st=st).items()]) + split
    except (OSError, SystemExit, ValueError, KeyError, AttributeError):  # no plan, or no init: the lines, not status
        return split


def until_lines() -> list[str]:
    """F427b: a line per task blocked on until checks, run up or not: '  F1 waits for version 0.66.0'."""
    try:
        return [f'  {t} {said}' for t, said in P.until_waits(P.lines(C.todo), C).items()]
    except (OSError, AttributeError):  # no plan, or no init
        return []


def spend_shown(st: dict, n: str) -> str:
    """F103: what slot n's task has spent so far ('1.2M tok $3.40'), as the run last wrote it to STATE."""
    got = (st.get('spend') or {}).get(n)
    if not (isinstance(got, list) and len(got) == 2 and all(isinstance(x, (int, float)) for x in got)) or not got[0]:
        return ''
    from agent_runner.cost import spend_text
    return spend_text(int(got[0]), float(got[1]))


def release_version(evs: list[dict], j: int) -> str:
    """The version the release task landing at evs[j] released (the next 'released' event), '' when none is logged:
    a release is logged right after its own landing (`announce_release`), so not past the next one."""
    for x in evs[j + 1:]:
        if x['kind'] in (EV_LANDED, EV_PART):
            return ''
        if x['kind'] == EV_RELEASED:
            return (str(x.get('text', '')).split() + ['', ''])[1]
    return ''


def lately_events(log_lines: list, titles: dict[str, str]) -> list[tuple[str, str, str]]:
    """`status`'s lately: the LATELY events of `log_lines` as `since_event` says them. F131: a release task's
    landing names the version the merge released (the next 'released' event): 'landed: Release 1.2.0 [V5]'."""
    evs = [e for l in log_lines if (e := as_event(l))]
    out = []
    for j, e in enumerate(evs):
        if e['kind'] not in LATELY or not (m := since_event(e, titles)):
            continue
        tid = e.get('id') or ''
        if e['kind'] == EV_LANDED and P.release(tid):
            if v := release_version(evs, j):
                name = (titles.get(tid) or 'Release').replace('(alone) ', '').split(': ', 1)[0].strip()
                m = (m[0], m[1], f'{SAID[EV_LANDED]}: {name} {v} [{tid}]')
        out.append(m)
    return out


def kind_table() -> dict[str, dict]:
    """F195b: `theme.kind_table` of the project's kinds."""
    from agent_runner import ui_model as U
    return theme.kind_table(U._kind_names())


def task_words(tid: str, title: str, kinds: dict) -> str:
    """F195b: a task as `status` prints it: 'bug B216 Talk: the end is cut off'."""
    word = theme.kind_of(tid, kinds)['word']
    return ' '.join(x for x in (word, tid, title) if x)


def event_words(tid: str, said: str, kinds: dict) -> str:
    """F195b: a lately line with its kind: 'landed: Run page chats [B215]' as 'landed: bug B215 Run page chats'."""
    state, sep, what = said.partition(': ')
    if not tid or not sep or not what.endswith(f' [{tid}]'):
        return said
    what = what.removesuffix(f' [{tid}]')
    return f'{state}: {task_words(tid, what.removeprefix(tid).strip() if re.match(re.escape(tid) + r"( |$)", what) else what, kinds)}'


def cap_held_line(st: dict, now: float) -> str:
    """F468: the usage caps holding new tasks, with the settings' caps; '' when they do not."""
    from agent_runner.cap_hold import held_line, limits_on
    from agent_runner.state import C
    caps = C.run if C else {'session_max': 90, 'weekly_max': 90}
    if not limits_on(caps):
        return ''
    return held_line(st, caps, now)


def chat_need_lines() -> list[str]:
    """F486: Needs you's lines of the live chats' DECIDE questions the run has not filed yet (`chat_question.live_needs`)."""
    from agent_runner import chat_question
    return chat_question.need_lines(chat_question.live_needs(), '  ')


def slot_login(n: str) -> str:
    """F505: the Claude login slot `n`'s session runs on ('default' for the first), only when claude has more than
    one login; '' otherwise, or when it cannot be read."""
    try:
        from agent_runner import fallback
        if not fallback.multi():
            return ''
        from agent_runner.slots import MUX
        pane = MUX.panes().get(f's{n}')
        sid = pane and MUX.session_id(pane[1])
        if not sid:
            return ''
        return 'login ' + (fallback.session_login(sid) or fallback.login_names('claude')[0] or 'default')
    except Exception:  # noqa: BLE001 - status never fails on a login it cannot read
        return ''


def status_text(up: bool, st: dict, log_lines: list[str], titles: dict[str, str], now: float, width: int = 60,
                waiting=None, progress: str = '', wips=None, login: str = '', agent: str = '') -> str:
    """`agent-runner status`, short enough for a phone: concepts waiting for the person's OK first, then the
    run's state, `progress` (`progress_line`, `release_line`), each slot's task, title and minutes, what is
    merging, the last few merged / blocked / parked, and usage."""
    out = waiting_text(waiting, now=dt.datetime.fromtimestamp(now) if now else None, wips=wips)
    if chats := chat_need_lines():  # F486: a live chat's DECIDE, before the run files it
        out = (out or [needs_heading(P.needs_cfg()['heading'])]) + chats
    if up and (held := cap_held_line(st, now)):  # F468: first, plainly
        out.insert(0, held)
    out.append(f'run up: {st.get("state", "starting")}' if up else 'no run is up')
    if nogate := no_gate_line():  # up or not: the next run merges untested too
        out.append(nogate)
    if agent:  # B764b: `ui_model.agent_problem`
        out.append(agent)
    if login:  # F126: `watch.claude_login_line`
        out.append(login)
    from agent_runner.control_held import lines as held_lines  # B170; here: control imports much of the runner
    out += held_lines()
    if unpushed := pitch.waiting_line():  # F98
        out.append(unpushed)
    out += pr_rows.text(titles)  # F420
    out += progress.splitlines()
    kinds = kind_table()
    for n, tid in sorted(st.get('running', {}).items(), key=lambda kv: (not kv[0].isdigit(), kv[0].zfill(4))):
        title = titles.get(tid, '')
        title = title if len(title) <= width else title[:width - 1].rstrip() + '…'
        mins = f'{int((now - st["since"][n]) // 60)} min' if n in st.get('since', {}) else ''
        out.append('  ' + '  '.join(x for x in (f's{n}' if n.isdigit() else n, task_words(tid, title, kinds),
                                                 mins, spend_shown(st, n), slot_login(n)) if x))
    if up and not st.get('running'):
        out.append('  no task running')
    if up:
        out += tool_lines(st)  # F168
    out += until_lines()
    if st.get('merging'):
        out.append('merging: ' + ', '.join(task_words(t, titles.get(t, ''), kinds) for t in st['merging']))
    events = lately_events(log_lines[-2000:], titles)
    if events:
        out.append('lately:')
        out += [f'  {m[0][11:16]} {event_words(m[1], m[2], kinds)}' for m in events[-5:]]
    use = st.get('usage') or {}
    if any(v is not None for v in use.values()):
        out.append('usage: ' + ', '.join(f'{w} {use[k]:.0f}%' for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
                                         if use.get(k) is not None))
    return '\n'.join(out)
