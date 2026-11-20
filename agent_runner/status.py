"""What the run tells a person: status, since and follow, Needs you lines."""

from __future__ import annotations

import datetime as dt
import os
import re
import time

from agent_runner import plan as P
from agent_runner.config import shown_cmd
from agent_runner.state import C, default_branch, git
from agent_runner.brief import has_sheet, wizard_cmd, wizard_file
from agent_runner.land import wip_lines


def tasks_left(ls: list[str]) -> tuple[int, int]:
    """(tasks left, how many of those are blocked) in TODO.md's lines `ls`: the open and blocked top-level tasks,
    not those under a section a run never starts (Parked, where `--pri later` files, and Stretch), nor shelved
    ones (`plan shelve`: blocked, off Needs you until a person brings them back)."""
    left = blocked = 0
    for section, box, _, _, i in P.iter_tasks(ls):
        if box not in ' ~' or section.startswith(P.SKIPPED):
            continue
        if box == '~':
            tail = ' '.join(P._item_block(ls, i))
            at = P._block_at(tail)
            if at >= 0 and tail[at:].lstrip().startswith('BLOCKED: ' + P.SHELVED):
                continue
            blocked += 1
        left += 1
    return left, blocked


def merges_since(start: dt.datetime) -> int:
    """How many merge commits the shared branch has since `start` (`git log --merges --since`)."""
    try:
        branch = default_branch()
    except SystemExit:  # a misconfigured [git] master_branch: status still answers, counting HEAD
        branch = 'HEAD'
    r = git('log', '--merges', f'--since={start.isoformat(timespec="seconds")}', '--format=%H', branch)
    return len(r.stdout.split()) if r.returncode == 0 else 0


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
    left, blocked = tasks_left(P.lines(C.todo))
    return (f'merged {merges_since(start)} {span} · {left} task{"" if left == 1 else "s"} left'
            + (f' ({blocked} blocked)' if blocked else ''))


RELEASE_TASK = re.compile(r'\W*(?:release\b|cut (?:a|the next) (?:release|version)\b)', re.I)


def release_line(ls: list[str]) -> str:
    """'release: waits on 7 of 25 tasks (T5)' for each queued release task in TODO.md's lines `ls` (one whose
    title starts "Release" or "Cut the next version"): of the tasks it waits on (its last block's `(after …)`,
    else its `after:` field), how many are still open. '' when none is queued. A task whose `after:` says
    `all above` (`plan add --last`, F43) gets a line too, 'last:' unless it is a release, naming what holds it."""
    live, out = P.open_ids(ls), []
    for section, box, tid, rest, i in P.iter_tasks(ls):
        last = P.LAST in P.fields(ls[i]).get('after', [])
        if box not in ' ~' or section.startswith(P.SKIPPED) or not (RELEASE_TASK.match(rest) or last):
            continue
        kind = 'release' if RELEASE_TASK.match(rest) else 'last'
        w = P.WAITS.findall(' '.join(P._item_block(ls, i))) if box == '~' else []
        ids = [t.strip() for t in w[-1].split(',') if t.strip()] if w else P.waits_on(ls, i)
        ids = [t for t in dict.fromkeys(ids) if t != tid]
        held = [t for t in ids if t in live]
        named = f': {", ".join(held[:6])}{" …" if len(held) > 6 else ""}' if last and not w else ''
        out.append(f'{kind}: waits on {len(held)} of {len(ids)} task{"" if len(ids) == 1 else "s"} ({tid}){named}'
                   if held else f'{kind}: ready, nothing left to wait on ({tid})')
    return '\n'.join(out)


EVENT = re.compile(r'^=== \S*T(\d\d:\d\d)\S* (?:(\S+): (merged, (?:ticked|blocked|part)|not merged, parked as \S+|LEFT FOR A HUMAN)\b'
                   r'|(run stopped|run idle))')  # what `status` lists under "lately"


# --- since: what happened since the person last looked ----------------------------------------------------

SINCE_LINE = re.compile(r'^=== (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\S* (.*)$')
SINCE_EVENTS = [  # (pattern on a run.log line's message, kind); the first that matches names it
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): merged, (?:ticked|part)'), 'landed'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): merged, blocked'), 'part landed, rest stuck'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): not merged, parked as \S+ — (.*)'), 'stuck, not merged'),
    (re.compile(r'^([A-Za-z]+\d+[a-z0-9]*): LEFT FOR A HUMAN — (.*)'), 'needs you'),
    (re.compile(r'^slot \d+: ([A-Za-z]+\d+[a-z0-9]*) looks stalled'), 'looks stuck'),
    (re.compile(r'^slot \d+: ([A-Za-z]+\d+[a-z0-9]*) \([^;)]*;'), 'started'),
    (re.compile(r'^STOPPED: ([^:]+)'), 'run held, needs you'),
    (re.compile(r'^run idle'), 'run idle: nothing left it may start'),
    (re.compile(r'^run stopped'), 'run stopped'),
    (re.compile(r'^(\S+ v?\d+(?:\.\d+)+ released\b.*)'), 'released'),  # F51: `release_line_for`'s line
    (STOP_ASKED := re.compile(r'^stop asked for:.*?\b(\d+) left before the run exits$'), 'stop requested'),  # F42: `stop_note`'s
    (STOP_BACK := re.compile(r'^stop taken back\b'), 'stop taken back'),
]
STOP_ENDS = re.compile(r'^(?:([A-Za-z]+\d+[a-z0-9]*): (?:merged, |not merged, parked |LEFT FOR A HUMAN |no commits — '
                       r'|the run stops; )|dropped ([A-Za-z]+\d+[a-z0-9]*); )')


def since_event(line: str, titles: dict[str, str]) -> tuple[str, str, str] | None:
    """A run.log line as (its ISO stamp, the task id or '', one plain phrase: "landed: <title> [F5]"), or None
    when it is not something a person wants told."""
    if not (m := SINCE_LINE.match(line)):
        return None
    stamp, msg = m.groups()
    for rx, kind in SINCE_EVENTS:
        if e := rx.match(msg):
            if kind == 'released':
                return stamp, '', e.group(1).strip()
            if kind == 'stop requested':
                return stamp, '', f'{kind}: {e.group(1)} left before the run exits'
            if kind == 'stop taken back':
                return stamp, '', f'{kind}: the run is starting tasks again'
            if kind.startswith('run '):
                what = f'{kind}: {e.group(1).strip()}' if e.groups() else kind
                return stamp, '', what
            tid = e.group(1)
            why = e.group(2) if rx.groups > 1 else ''
            why = f' ({why.split(". ")[0][:60].rstrip(" .")})' if why else ''
            return stamp, tid, f'{kind}: {titles.get(tid) or tid}{why} [{tid}]'
    return None


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
               since_mark: bool = False, waiting=None, wips=None) -> tuple[str, str | None]:
    """(what `since` prints, the newest stamp it read or None): the concepts waiting for the person's OK first
    (`waiting`, however old), then each event after `start`, oldest first, one short line each; or one line
    saying there is nothing new."""
    text, last = _since_events(log_lines, start, titles, now, since_mark)
    return '\n'.join([*waiting_text(waiting, now=now, wips=wips), text]), last


def _since_events(log_lines: list[str], start: dt.datetime, titles: dict[str, str], now: dt.datetime,
                  since_mark: bool) -> tuple[str, str | None]:
    out, last = [], None
    for l in log_lines:
        if not (m := SINCE_LINE.match(l)):
            continue
        try:
            if dt.datetime.fromisoformat(m[1]) <= start:
                continue
        except ValueError:
            continue
        last = m[1]
        if e := since_event(l, titles):
            out.append(f'  {when(e[0], now)}  {e[2]}')
    head = f'since {when(start.isoformat(timespec="seconds"), now)}' + (' (your last look)' if since_mark else '')
    return (f'{head}:\n' + '\n'.join(out) if out else f'nothing new {head}'), last


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
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(stamp + '\n', encoding='utf-8')
    os.replace(tmp, f)


def what_changed(tid: str) -> str:
    """The first sentence of the commit subject a task landed with (its `done` message), without the id; ''."""
    r = git('log', '-n', '1', '-E', f'--grep=^{re.escape(tid)}( |:|$)', '--format=%s', 'HEAD')
    subj = r.stdout.strip() if not r.returncode else ''
    subj = re.sub(rf'^{re.escape(tid)}[: ]\s*', '', subj)
    subj = re.split(r'(?<=[.;:])\s|\s—\s|, (?=and |so |which )', subj, maxsplit=1)[0].rstrip(' .;:')
    return subj if len(subj) <= 100 else subj[:99].rsplit(' ', 1)[0] + '…'


NEEDS_YOU = ('needs you', 'looks stuck', 'run held, needs you',
             'stuck, not merged')  # since_event kinds only a person can clear (B32: a parked task too)


def needs_you_line(line: str, titles: dict[str, str], now: dt.datetime, waiting) -> str | None:
    """A run.log line as `since --follow --needs-you` prints it, or None when it does not need the person: the run
    held (STOPPED, with what holds it), a task left for a human, one that looks stalled, and a task that landed
    or blocked waiting on a person's answer (a CONFIRM/DECIDE/BLOCKED ask, or a concept page waiting for an OK:
    `waiting` is `waiting_ok()`'s list, read after the line was logged)."""
    if not (e := since_event(line, titles)):
        return None
    kind = e[2].split(': ', 1)[0]
    if kind in NEEDS_YOU:
        what = e[2]
        if kind == 'run held, needs you' and (m := SINCE_LINE.match(line)):
            held = m[2][len('STOPPED: '):].strip()
            what = f'{kind}: {held if len(held) <= 240 else held[:239].rsplit(" ", 1)[0] + "…"}'
        return f'{when(e[0], now)}  {what}'
    if e[1] and kind in ('landed', 'part landed, rest stuck'):
        for label, tid, k, ask, url, title, shelved, *_ in waiting or []:
            if e[1] in (tid, k) and not shelved:  # B27: in everyday words, no caps label
                return f'{when(e[0], now)}  {ASK_FEED}' + '  '.join(
                    x for x in (f'{P.plain_ask(label, ask, title or titles.get(tid) or tid, label == 'DECIDE' and has_sheet(tid))} [{tid}]',
                                url) if x)
    return None


ASK_FEED = 'needs you: '  # how a feed line about an item under Needs you starts (B27; was 'waits for you: ')


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
        if m := SINCE_LINE.match(l):
            last = m[1]
            msg = m[2]
            if s := STOP_ASKED.match(msg):
                stop.clear()
                stop.update(left=int(s[1]), ended=set())
            elif STOP_BACK.match(msg) or msg.startswith('run stopped'):
                stop.clear()
            elif 'left' in stop and (s := STOP_ENDS.match(msg)) and (s[1] or s[2]) not in stop['ended']:
                stop['ended'].add(s[1] or s[2])
                stop['left'] = max(0, stop['left'] - 1)
        left = f' · {stop["left"]} left' if 'left' in stop else ''
        if needs_you:
            if nl := needs_you_line(l, titles, now, waiting):
                out.append(nl + left)
            continue
        if e := since_event(l, titles):
            line = f'{when(e[0], now)}  {e[2]}'
            if e[1] and e[2].startswith('landed: ') and (did := what_changed(e[1])):
                line += f' — {did}'
            out.append(line + ('' if e[2].startswith('stop requested: ') else left))
            if waiting and (e[1] and e[2].split(': ', 1)[0] in ('landed', 'part landed, rest stuck')) \
                    and (nl := needs_you_line(l, titles, now, waiting)):
                out.append(nl + left)  # the full feed carries the asks too: the runner feed is the one watch
    return out, last


def follow(poll: float = 2.0, until: float | None = None, needs_you: bool = False, mark: bool = True,
           hold=None, end=None) -> int:
    """`since --follow`: print one plain line per new event as run.log gets it, moving the since mark as it
    prints; from the log's end, until killed (or `until`, a monotonic deadline, for tests). `needs_you`: only
    what needs the person (`needs_you_line`), and the mark stays put: the landed and started lines it skips
    are still news for the next `since`. `mark=False` (the board): the mark stays put too.
    `hold` (the runner feed, `board_held`): while it says so, nothing is read or printed, so the feed's
    session gets no turn; what was logged meanwhile prints when it lets go. `end`: stop once it says so
    (the board, once its run has ended)."""
    logf = C.notes('run.log')
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
                lines, last = follow_lines(chunk, P.titles(C.done, C.todo), dt.datetime.now(), needs_you,
                                           waiting_ok() if 'merged, ' in chunk else None, stop)
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
        return [(*a, stamps.get(a[1], '')) for a in P.asks(C.todo, all=True)]
    except (OSError, SystemExit):
        return []


def waiting_text(waiting, width: int = 60, now: dt.datetime | None = None, wips=None) -> list[str]:
    """B27: '[needs] heading' ('Needs you:') and per ask one line in everyday words, what is asked and what to
    reply, with its age first ('2h', when `[needs] ages`) and its [id] last, then its link on a line of its
    own; in `[needs] order` (oldest first); a count of the shelved ones last. [] for none. `waiting` is
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
        if label != 'CONCEPT' and wizard_file(tid):  # F17: the one command that walks them through it
            out.append(f'    run: {wizard_cmd(tid)}')
    out += wip_lines(wips or [], now)  # F23: a person's edits moved aside, never deleted by the run
    if not out:
        return []  # only shelved ones: they asked to leave this list
    if shelved:
        out.append(f'  ({shelved} shelved: plan waiting --all)')
    return [f'{cf["heading"]}:'] + out


def status_text(up: bool, st: dict, log_lines: list[str], titles: dict[str, str], now: float, width: int = 60,
                waiting=None, progress: str = '', wips=None) -> str:
    """`agent-runner status`, short enough for a phone: concepts waiting for the person's OK first, then the
    run's state, `progress` (`progress_line`, `release_line`), each slot's task, title and minutes, what is
    merging, the last few merged / blocked / parked, and usage."""
    out = waiting_text(waiting, now=dt.datetime.fromtimestamp(now) if now else None, wips=wips)
    out.append(f'run up: {st.get("state", "starting")}' if up else 'no run is up')
    out += progress.splitlines()
    for n, tid in sorted(st.get('running', {}).items(), key=lambda kv: (not kv[0].isdigit(), kv[0].zfill(4))):
        title = titles.get(tid, '')
        title = title if len(title) <= width else title[:width - 1].rstrip() + '…'
        mins = f'{int((now - st["since"][n]) // 60)} min' if n in st.get('since', {}) else ''
        out.append('  ' + '  '.join(x for x in (f's{n}' if n.isdigit() else n, f'{title} [{tid}]' if title else tid,
                                                 mins) if x))
    if up and not st.get('running'):
        out.append('  no task running')
    if st.get('merging'):
        out.append('merging: ' + ', '.join(f'{titles[t]} [{t}]' if titles.get(t) else t for t in st['merging']))
    events = [m for l in log_lines[-2000:] if EVENT.match(l) and (m := since_event(l, titles))]
    if events:
        out.append('lately:')
        out += [f'  {m[0][11:16]} {m[2]}' for m in events[-5:]]
    use = st.get('usage') or {}
    if any(v is not None for v in use.values()):
        out.append('usage: ' + ', '.join(f'{w} {use[k]:.0f}%' for k, w in (('five_hour', 'session'), ('seven_day', 'week'))
                                         if use.get(k) is not None))
    return '\n'.join(out)
