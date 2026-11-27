"""C44: the queue, the releases, Needs you and the shelved rows of a snapshot.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

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


def split_queued(ls: list[str], tid: str, i: int, tasks: list[tuple]) -> bool:
    """B811a: is the task at ls[i] a split one (`(split into …)`) with an open part neither parked nor shelved? Then it
    stands in the queue, even at level later. `tasks`: `P.iter_tasks`' rows."""
    if not P.SPLIT.search(ls[i]):
        return False
    parts = P.subtasks(tid, ls[i], [t for _, box, t, _, _ in tasks if box in ' ~'])
    return any(t in parts and not section.startswith(P.PARKED) and task_pri(rest, section) != 'later'
               and not P._shelved(ls, j) for section, _, t, rest, j in tasks)


def split_parts(ls: list[str], tid: str, i: int, tasks: list[tuple], done: list[str]) -> dict | None:
    """B811b: of the split task at ls[i], `parts` (how many), `landed` (how many of them), `open` ([{id, title}] of the
    rest), `list` (F453: every part {id, title, landed}: the landed first, then the open in plan order) and `words`; None for a task that was not split, or has no part yet. A dropped part is none, and one that was
    split itself counts once, not its parts too. `done`: DONE.md's lines."""
    if not P.SPLIT.search(ls[i]):
        return None
    known: dict[str, str | None] = {}  # its title while open, None once landed
    names: dict[str, str] = {}  # F453: every part's title, a landed one's too
    for x, rows in ((done, P.iter_tasks(done)), (ls, tasks)):
        for _, box, t, rest, j in rows:
            if box in ' ~':
                known[t] = names[t] = after_name(P.SPLIT.sub('', rest))
            elif not P._dropped(x, j):
                known[t], names[t] = None, after_name(P.SPLIT.sub('', rest))
    kids = P.subtasks(tid, ls[i], known)
    own = [t for t in known if t in kids and not any(
        P.child(p, t) and (known[p] is not None or known[t] is None) for p in kids)]
    if not own:
        return None
    landed = sum(known[t] is None for t in own)
    order = {t: n for n, (_, _, t, _, _) in enumerate(tasks)}  # F453: plan order, from the plan itself
    every = [t for t in own if known[t] is None] + sorted((t for t in own if known[t] is not None), key=lambda t: order.get(t, len(order)))
    return {'parts': len(own), 'landed': landed, 'open': [{'id': t, 'title': known[t]} for t in own if known[t] is not None],
            'list': [{'id': t, 'title': names[t], 'landed': known[t] is None} for t in every],
            'words': f'Split: {landed} of {len(own)} part{"s" * (len(own) != 1)} landed'}


def done_lines() -> list[str]:
    try:
        return P.lines(S.C.done)
    except Exception:  # noqa: BLE001 - no DONE.md
        return []


def queue_rows(ls: list[str], st: dict | None = None, now: float | None = None) -> list[dict]:
    """Every open task ([ ] or [~]) of TODO.md's lines `ls`, in plan order. F74: each row also carries
    `after_title` (what it waits on, in words: `after_words`) and `state` (`queue_state`; STATE `st` says
    which slot runs it and since when)."""
    from agent_runner import plan_wait, row_hold
    names, out = _kind_names(), []
    tasks = list(P.iter_tasks(ls))
    titles = {tid: P.short_title(rest, 200) for _, _, tid, rest, _ in tasks}
    names_of = {tid: after_name(rest) for _, _, tid, rest, _ in tasks}
    live = {tid for _, box, tid, _, _ in tasks if box in ' ~'}
    landed = {tid for _, box, tid, _, _ in tasks if box not in ' ~'} | done_ids()
    where = slot_of(st or {}, time.time() if now is None else now)
    tool_waits, tool_names = split_wait_words(ls, st, now) | tool_wait_words(ls, st, now), project_tools()
    untils = until_wait_words(ls)
    busy = under_way_rows(st or {})  # F429b
    done = done_lines() if any(P.SPLIT.search(ls[t[-1]]) for t in tasks) else []
    for section, box, tid, rest, i in tasks:
        if box not in ' ~' or P._shelved(ls, i):  # B115: a shelved task is set aside, not queued
            continue
        f = P.fields(ls[i])
        after, pri = P.waits_on(ls, i), task_pri(rest, section)
        on_tasks = False
        if box == '~' and (ids := plan_wait.blocked_on(ls, i)):  # F441: blocked on tasks alone, as `reopen` reads it
            after = [t for t in dict.fromkeys(P.resolve_after(ls, i, ids)) if t != tid]
            on_tasks = any(t in live for t in after)
        if pri == 'later' and split_queued(ls, tid, i, tasks):
            pri = 'normal'
        everything = P.ALL in f.get('after', []) and 'ahead' not in f  # F435: a listed one names them
        out.append({'id': tid, 'kind': task_kind(tid, names), 'title': titles[tid],
                    'files': f.get('files', []), 'after': after, 'pri': pri,
                    'section': section, 'blocked': box == '~',
                    'after_title': after_words(after, names_of, live, everything, landed),
                    'state': queue_state(tid, pri, after, live, where, box == '~' and not on_tasks, tid in tool_waits)})
        if tool_names:  # F168
            out[-1].update(needs=f.get('needs', []), tool_wait=tool_waits.get(tid, ''))
        elif tid in tool_waits:  # B184: memory; B196: its author's split
            out[-1]['tool_wait'] = tool_waits[tid]
        if tid in untils and tid not in where:  # F427b: neither the person nor a slot: it says what it waits for
            out[-1].update(state='tool', tool_wait=untils[tid])
        if size := ' '.join(f.get('size') or []).strip():  # F485: size: simple|complex, beside its other fields
            out[-1]['size'] = size
        if tid in busy:
            out[-1].update(under_way=True, way=busy[tid])
        if row_hold._not_queued(ls, i):  # F429b: `plan hold` refuses it
            out[-1]['no_hold'] = True
        if 'held' in f:  # F429
            out[-1]['held'] = True
            if row_hold.shows_held(ls, i) and out[-1]['state'] != 'parked' and tid not in where:
                out[-1]['state'] = 'held'
        if split := split_parts(ls, tid, i, tasks, done):  # B811b
            out[-1]['split'] = split
            if box != '~' and out[-1]['state'] in ('ready', 'critical', 'after', 'tool'):
                out[-1]['state'] = 'split'
        if P.release(tid) and releases_on():  # F186: one that started cannot be dropped from its row
            out[-1]['started'] = release_started(tid, st or {})
    return out


def under_way_rows(st: dict) -> dict[str, dict]:
    """F429b, B846: the tasks no slot of STATE `st` runs that are under way all the same, and how, as a queue row says
    it: {task: {'words', 'chat': the live chat that took it ('c10')}}, 'chat' only when one did. No git is run."""
    if not S.C:
        return {}
    from agent_runner import taken_by
    from agent_runner.sched import taken
    out = {q[0]: {'words': 'Waits to resume'} for q in S.queued().values()}
    by_hand = taken()
    live = control_titles() if by_hand else {}
    for tid, d in by_hand.items():
        n = taken_by.chat(S.C, d, live)
        out[tid] = {'words': 'Taken by hand' if n is None else 'Taken by a chat that has ended'}
        if n:
            out[tid] = {'words': f'Taken by the chat {chat_name(n, live[n])}', 'chat': f'c{n}'}
    return {**out, **{tid: {'words': 'Merging'} for tid in st.get('merging') or []}}


def chat_name(n: int, title: str) -> str:
    """B846: control session `n`'s name as the run page's Chats list says it (its chatName); `title`: `control_titles`'."""
    from agent_runner.control_settled import pid_sid
    st = chat_row(n, pid_sid(S.C, n))
    title = st.get('title') or title
    return title if title and (st['renamed'] or title != 'control session') else f'Chat {n}'


def releases_on() -> bool:
    from agent_runner import autorelease
    return autorelease.releases_on()


def release_started(tid: str, st: dict) -> bool:
    """F186: is release task `tid` under way: a slot of STATE `st` runs it, it merges, or a person took it."""
    from agent_runner.sched import taken
    return tid in (st.get('running') or {}).values() or tid in (st.get('merging') or []) or \
        bool(S.C and tid in taken())


# F74: a queue row's state, first word. 'blocked' (beyond the design's four): a [~] task waits on a person or
# a fix, and 'ready' would say it can start. B118: 'parked' (level later, TODO.md's Parked section): a run never
# starts it, so it must not say 'ready' either. F429: 'held' (`plan hold`; its row also carries `held`).
# B811b: 'split': its parts are the work (its row also carries `split`: `split_parts`).
QUEUE_STATES = ('running', 'blocked', 'held', 'critical', 'after', 'tool', 'split', 'parked', 'ready')


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


def until_wait_words(ls: list[str]) -> dict[str, str]:
    """F427b: {task: 'waits for version 0.66.0'} for the tasks blocked on until checks."""
    try:
        return P.until_waits(ls, S.C)
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
    release task (kind V) open in TODO.md's lines `ls` (`release_tasks`), one releasing now first; while
    `[run] auto_release` counts (none open, or F195a: they only wait), a placeholder 'Next release · auto at 10 landed: 6/10 · when the run goes
    idle' (F131; `landed`: tasks landed since the last release, counted when None); last, the newest release
    that landed (`last_release`). `text` is a whole row, `note` what it does not wait on; `placeholder` True for a
    row that is no open task. [] with `[run] releases` off (F193)."""
    if not releases_on():
        return []
    st = st or {}
    rows = release_tasks(ls, st)
    if ph := auto_release_row(ls, landed, rows):
        rows.append(ph)
    done = last_release(now)
    return rows + ([done] if done and done['id'] not in {r['id'] for r in rows} else [])


def release_tasks(ls: list[str], st: dict) -> list[dict]:
    """The open release tasks of `ls` as `release_rows`' rows, `state` 'releasing' (a slot of STATE `st` runs it,
    or it merges), 'blocked', 'waits' (`waits`: [{id, title}]; `words` names the first RELEASE_SHOWN, `all` every
    one; `everything`: it waits for all above its place, not for tasks it names or lists) or 'next' (nothing left before it)."""
    tasks = [t for t in P.iter_tasks(ls) if t[1] in ' ~']
    live, titles, away, out = P.open_ids(ls), {}, None, []
    from agent_runner import release_ahead
    for section, box, tid, rest, i in tasks:
        if not P.release(tid) or section.startswith(P.SKIPPED) or P._shelved(ls, i):
            continue
        titles = titles or {t: after_name(_no_tag(r)) for _, _, t, r, _ in tasks}
        note, held = '', []
        checks = P.until_of(ls, i)
        waits = P.WAITS.findall(' '.join(P._item_block(ls, i))) if box == '~' and not checks else []
        if tid in (st.get('running') or {}).values() or tid in (st.get('merging') or []):
            state = 'releasing'
        elif box == '~' and not waits:
            state = 'blocked'
        elif 'held' in P.fields(ls[i]) and (box == ' ' or waits):  # F429
            state = 'held'
        else:
            if P._waits_all(ls, i):
                held = [t for t in P.before_all(ls, i) if t in live and t != tid]
                note = P.not_waiting(P.not_waiting_on(ls, i))  # B101, B207
                if P.ALL in P.fields(ls[i]).get('after', []):  # B107: a task taken by hand lands after it
                    from agent_runner.sched import taken
                    from agent_runner.status import taken_note
                    away = set(taken()) if away is None else away
                    note += taken_note([t for t in held if t in away])
                    held = [t for t in held if t not in away]
            else:
                ids = [t.strip() for t in waits[-1].split(',')] if waits else P.waits_on(ls, i)
                held = [t for t in dict.fromkeys(ids) if t in live and t != tid]
                note = '' if waits else P.not_waiting(P.not_waiting_on(ls, i))  # B207: `after: all above`
            state = 'waits' if held else 'next'
        everything = bool(held) and not release_ahead.is_listed(ls[i]) and not P._named_after(ls, i) and (
            P._waits_all(ls, i) or not waits and P.LAST in P.fields(ls[i]).get('after', []))  # B825
        names = [f'{t} {titles.get(t, "")}'.rstrip() for t in held]
        more = len(names) - RELEASE_SHOWN
        words = full = {'releasing': 'releasing now', 'blocked': 'blocked', 'held': 'held', 'next': 'next'}.get(state, '')
        if checks and state == 'blocked':  # F427b
            words = full = f'waits for {P.until_label(checks, S.C)}'
        if held:
            full = f'waits for {len(names)}: {", ".join(names)}'
            words = f'waits for {len(names)}: {", ".join(names[:RELEASE_SHOWN])}, and {more} more' if more > 0 else full
        out.append({'id': tid, 'title': titles[tid], 'state': state, 'words': words, 'all': full, 'placeholder': False,
                    'waits': [{'id': t, 'title': titles.get(t, '')} for t in held], 'everything': everything,
                    'text': f'{tid} {titles[tid]} · {words}', 'note': note})
    return sorted(out, key=lambda r: r['state'] != 'releasing')


def release_ask(rows: list[dict]) -> dict | None:
    """F186: what a New release is told of the open releases among `release_rows`' rows: {'said': 'V17 is already
    queued', 'ask': the question before another is queued, 'seen': their ids, which the Yes carries}; None with none."""
    rows = [r for r in rows if not r.get('placeholder')]
    if not rows:
        return None
    from agent_runner.sched import taken
    by_hand = taken() if S.C else {}
    said = '; '.join(f'{r["id"]} is ' + ('releasing now' if r['state'] == 'releasing' else 'taken by a person'
                                         if r['id'] in by_hand else 'already queued') for r in rows)
    return {'said': said, 'ask': f'{said}. Queue another release?', 'seen': ' '.join(sorted(r['id'] for r in rows))}


RELEASE_WAIT = 60.0  # s a New release waits for another one to be queued (the page's, a TUI's)


def new_release(argv: list[str], seen: str = '', confirm: bool = False) -> dict:
    """F186: queue a release by `argv`; with one open already only on a `confirm` that names the ones open now
    (`seen`), so neither a second press nor a second Yes queues one more unasked. One at a time looks at the plan
    and adds to it, across the pages and TUIs (a file lock of its own: the `plan add` it runs takes the plan's)."""
    if not S.C:  # before `state.init`
        return call(argv)
    end = time.monotonic() + RELEASE_WAIT
    while not (f := _plat().lock(S.C.notes('release.lock'))):
        if time.monotonic() >= end:
            return {'ok': False, 'code': 1, 'out': 'another release is being queued: look again', 'argv': argv}
        time.sleep(0.05)
    with f:
        ask = release_ask(release_tasks(P.lines(S.C.todo), _state(S.run_up())))
        if ask and not (confirm is True and seen == ask['seen']):
            return {'ok': False, 'code': 3, 'out': ask['ask'], 'confirm': ask['ask'], 'seen': ask['seen'], 'argv': argv}
        return call(argv)


def _no_tag(rest: str) -> str:
    """A task's line without F130's `(alone)` tag, which is no title."""
    return re.sub(r'^\s*(?:\(follow-up, \w+\)\s*)?\(alone\)\s*', '', rest)


def _counts_on(ls: list[str], rows: list[dict]) -> bool:
    """F195c: do all the open releases (`release_tasks`' `rows`) only wait for open tasks, so that a count goes on beside
    them (as `autorelease.waiting_releases` says)? A shelved, Parked, blocked, taken or moved (F429a) one stops it."""
    from agent_runner import release_moves
    from agent_runner.sched import taken
    boxes = {tid: box for _, box, tid, _, _ in P.iter_tasks(ls)}
    waits = {r['id'] for r in rows if r['state'] == 'waits' and boxes[r['id']] == ' '} - release_moves.moved_ids(ls)
    return not {t for t in P.open_ids(ls) if P.release(t)} - waits and not (waits and waits & set(taken()))


def auto_release_row(ls: list[str], landed: int | None = None, rows: list[dict] | None = None) -> dict | None:
    """F131: the placeholder row while `[run] auto_release` counts, else None. F195c: beside open releases (`rows`,
    `release_tasks`') that only wait it is the count alone (idle queues none then). `left`: how many more must land
    (None: not counted)."""
    from agent_runner.autorelease import auto_release_of
    every, idle = auto_release_of(S.C.run.get('auto_release', False) if S.C else False)
    if P.open_release(ls):
        idle = False
        if not _counts_on(ls, rows or []):
            return None
    if not (every or idle):
        return None
    if every and landed is None:
        landed = landed_count()
    held = next_held()
    count = '' if landed is None else f': {landed}/{every}'
    words = ' · '.join((['held'] if held else []) + ([f'auto at {every} landed{count}'] if every else []) +
                       (['when the run goes idle'] if idle else []))
    return {'id': '', 'title': 'Next release', 'state': 'auto', 'words': words, 'all': words, 'placeholder': True,
            'left': max(every - landed, 0) if every and landed is not None else None, 'before': '', 'waits': [], 'text': f'Next release · {words}', 'note': '', **({'held': True} if held else {})}


_NEXT_HELD: list = [None, False]  # `next_held`: the event log's mark when last read, and what it said


def next_held() -> bool:
    """F429b: is the Next release row held (`plan hold next-release`)?"""
    if not S.C:
        return False
    from agent_runner import release_moves
    f = S.C.notes('events.jsonl')
    try:
        s = f.stat()
        mark = (str(f), s.st_size, s.st_mtime_ns)
        if _NEXT_HELD[0] != mark:
            _NEXT_HELD[:] = [mark, release_moves.cuts().held]
    except (OSError, KeyError, ValueError):  # no event log yet
        return False
    return _NEXT_HELD[1]


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


def grip_on(row: dict) -> bool:
    """B824b: has the Plan queue row `row` a grip? Each but a parked one and a release already started; a task that runs or is
    under way too: a move is of its place alone."""
    state = str(row.get('state') or '')
    started = row.get('started') or row.get('under_way') or state.startswith('running')
    return state != 'parked' and not (started and P.release(row['id']))


def pin_releases(queue: list[dict], rows: list[dict]) -> list[dict]:
    """The queue with each release task `rows` stand for carrying `release`: its row, at its place (F195c). The auto
    release's row, which is no task, gets `before`: the id of the task it stands before, after as many that may land as
    it still needs ('' for the queue's end). F429b: each has `menu`, the keys of its row menu; B824b: and
    `grip`, whether it can be moved (`grip_on`)."""
    by = {r['id']: r for r in rows if not r.get('placeholder')}
    for r in rows:
        if r.get('state') == 'auto' and r.get('left') is not None:
            tasks = [q['id'] for q in queue if q['id'] not in by and q['state'] not in ('parked', 'blocked', 'held')]
            r['before'] = tasks[r['left']] if r['left'] < len(tasks) else ''
        if r.get('state') == 'auto':
            r.update(menu=row_acts('queuemenu', r), grip=True)
    queue = [dict(q, menu=row_acts('queuemenu', q), grip=grip_on(q)) for q in queue]
    return [dict(q, release=by[q['id']]) if q['id'] in by else q for q in queue]


def _need_devices(text: str) -> list[dict]:
    """F408: the devices with a web page that a task's `needs:` names (`devices.need_pages`)."""
    from agent_runner import devices
    try:
        return devices.need_pages(text.partition('\n')[0], S.C)
    except Exception:  # noqa: BLE001 - costs the links, not the list
        return []


def concept_row_news(k: str, copy: str) -> dict:
    """F197a: a concept row's 'version', 'news' ('new', 'updated' or '') and 'news_words' (`concept_news`)."""
    if not S.C or not k:
        return {'version': '', 'news': '', 'news_words': ''}
    from agent_runner import concept_news
    return concept_news.news(S.C, k, copy)


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
            url = '' if url.startswith('/concept/') else url  # F406e: no claude.ai page: `copy` is the page
            concepts.append({'id': tid, 'concept': k, 'title': title, 'url': url, 'copy': concept_copy(k)})
            concepts[-1]['lead'] = concept_chat_text(concepts[-1])  # B219a: the run page's first message opens with it
            concepts[-1].update(concept_row_news(k, concepts[-1]['copy']))  # F197a: New / Updated
        needs.append({'label': label, 'id': tid, 'concept': k, 'title': title, 'what': what, 'url': url,
                      'ask': (ask := P.plain_ask(label, what, title)), 'ask_short': ask_short(ask),
                      'age': P.age(stamps.get(tid, ''), now),
                      'detail': need_detail.detail(label, tid, ask, title, texts.get(tid, ''))})  # F162
        if devs := _need_devices(texts.get(tid, '')):  # F408
            needs[-1]['devices'] = devs
        if label == 'DECIDE' and not url:
            needs[-1].update(sheet_copy(tid))  # F411
        if opts:
            needs[-1]['options'] = opts
        elif label == 'DECIDE' and (url or needs[-1].get('page')) and (easy := sheet_options(tid, texts.get(tid, ''))):  # F181b
            needs[-1].update(options=easy, picks={o['name']: o.pop('send') for o in easy})
        if label == 'PITCH':  # F98
            from agent_runner import pitch
            xs = [{'id': x['id'], 'title': x['title']} for x in pitch.changes_of(tid, state='waiting')]
            needs[-1].update(copy=concept_copy(tid), changes=xs, options=['Approve'] + [
                f'Not {w}: {how}' for w in ['this'] + ([x['id'] for x in xs] if len(xs) > 1 else [])
                for how in ('reopen', 'drop')])
        needs[-1]['answers'] = need_answers(needs[-1])  # C33: both pages draw these
        if frame := concept_frame(needs[-1]):
            needs[-1]['frame'] = frame  # F463: its card shows the options page framed
    concepts += page_rows({c['concept'] or c['id'] for c in concepts} | {c['id'] for c in concepts},
                          {n['id'] for n in needs})
    return needs, concepts


def page_rows(shown: set[str], waits: set[str]) -> list[dict]:
    """F457: a Concepts row for each page served at /concept/<ID> (<notes>/concepts/<ID>.html) whose task is still in
    the plan and not done or dropped, beside the concepts `shown` already: a report or videos a task put up with
    publish-page. `page`: it is no concept (no Pick/OK); `waits`: its task also has a Needs you item."""
    try:
        files = sorted(S.C.notes('concepts').glob('*.html'))
        ls = P.lines(S.C.todo)
        tasks = {tid: (box, rest) for _, box, tid, rest, i in P.iter_tasks(ls)
                 if not P._shelved(ls, i)}  # F184: shelved tasks stay out of Concepts
    except Exception:  # noqa: BLE001 - no notes dir or plan: no pages
        return []
    out = []
    for f in files:
        tid = f.stem
        if tid in shown or tid not in tasks or tasks[tid][0] in 'x-':
            continue
        out.append({'id': tid, 'concept': tid, 'title': P.short_title(tasks[tid][1], 200), 'url': '',
                    'copy': str(f), 'page': True, 'waits': tid in waits})
    out += chat_page_rows(files, shown, filed=filed_chat_pages(ls))
    pages = {f.stem: f for f in files}
    for row in approved_rows(ls, shown | {r['id'] for r in out}):
        if f := pages.get(row['id']):
            out.append({**row, 'copy': str(f), 'waits': row['build'] in waits})  # a parked build's Needs you item
    out += history_rows(files, ls, done_lines(), shown | {r['id'] for r in out})
    return out


def history_rows(files: list, ls: list[str], done: list[str], shown: set[str]) -> list[dict]:
    """F516: a Concepts row for each past concept whose page file is still in <notes>/concepts: its task is ticked
    or dropped (in TODO.md's lines `ls` or DONE.md's `done`), so approved and built, dropped or done. Newest page
    first. `history`: the page lists it grayed under History, with View and Chat only."""
    past = {}
    for _, box, tid, rest, _i in P.iter_tasks(done):
        past[tid] = rest
    for _, box, tid, rest, _i in P.iter_tasks(ls):
        if box in 'x-':
            past[tid] = rest
        else:
            past.pop(tid, None)  # open again in TODO.md
    rows = []
    for f in files:
        if f.stem in shown or f.stem not in past or not f.stem.startswith('K'):  # concepts only, not a task's report
            continue
        try:
            at = f.stat().st_mtime
        except OSError:
            continue
        rows.append((at, {'id': f.stem, 'concept': f.stem, 'title': P.short_title(past[f.stem], 200), 'url': '',
                          'copy': str(f), 'page': True, 'waits': False, 'history': True}))
    return [r for _, r in sorted(rows, key=lambda x: -x[0])]


CHAT_PAGE_DAYS = 7


def filed_chat_pages(ls: list[str]) -> set[str]:
    """B881: the chat<id> pages the plan names (/concept/chat<id>): a chat filed them as a concept."""
    return set(re.findall(r'/concept/(chat[0-9a-f]+)\b', '\n'.join(ls)))


def chat_page_rows(files: list, shown: set[str], now: float | None = None,
                   filed: set[str] | None = None) -> list[dict]:
    """B875: a Concepts row for each page a chat published (<notes>/concepts/chat<id>.html): it has no task in the
    plan, so the task check above left it out. Pages from the last CHAT_PAGE_DAYS days only; its title is the page's
    <title>. B881: only pages a chat filed as a concept (`filed`, the plan names them); its reports stay off."""
    out, now = [], now or time.time()
    for f in files:
        if not re.fullmatch(r'chat[0-9a-f]+', f.stem) or f.stem in shown or f.stem not in (filed or set()):
            continue
        try:
            if now - f.stat().st_mtime > CHAT_PAGE_DAYS * 86400:
                continue
            m = re.search(r'<title>([^<]*)', f.read_text(encoding='utf-8', errors='replace')[:4000], re.I)
        except OSError:
            continue
        title = (m.group(1).strip() if m else '') or 'A page from a chat'
        out.append({'id': f.stem, 'concept': f.stem, 'title': title[:200], 'url': '', 'copy': str(f),
                    'page': True, 'waits': False})
    return out


BUILD_OF = re.compile(r'^\s*(?:\([^)]*\)\s*)?Build the option a person approves on concept ([A-Z]+\d+[a-z0-9]*)\'s page: ')


def approved_rows(ls: list[str], shown: set[str]) -> list[dict]:
    """B866: a Concepts row for each approved concept (ticked, so in DONE.md) whose build task in TODO.md's lines
    `ls` is still open and not waiting for the OK: it stays listed with its page until the build lands. `build`: the
    build task's id; `building`: 'parked' when the build is blocked or shelved, else 'building'."""
    out = []
    for _, box, bid, rest, i in P.iter_tasks(ls):
        m = BUILD_OF.match(rest.lstrip('* '))
        if not m or box in 'x-' or (k := m.group(1)) in shown:
            continue
        if box == '~' and P.WAIT_OK in ''.join(P._item_block(ls, i)):
            continue  # not approved yet: the concept row shows it
        parked = box == '~' or P._shelved(ls, i)
        title = P.short_title(rest.lstrip('* ')[m.end():], 200)
        mark = f"approved: {'parked' if parked else 'building'} {bid}"
        out.append({'id': k, 'concept': k, 'title': f'{title} ({mark})', 'url': '', 'page': True, 'waits': False,
                    'build': bid, 'building': 'parked' if parked else 'building', 'approved': mark})
        shown = shown | {k}
    return out


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
