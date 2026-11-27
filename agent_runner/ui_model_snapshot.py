"""C44: the sessions, the status, the usage and `snapshot` itself.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

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
    person's own name for it), and for one on the harness loop 'model' (F406g: its provider's name and model)}. Read again only when its transcript changed."""
    out = {'link': '', 'last': '', 'at': 0, 'needs_reply': False, 'renamed': False, 'title': ''}
    try:
        from agent_runner import control as K
        from agent_runner.control_harness import chat_model
        from agent_runner.control_names import person_name
        if model := chat_model(sid):
            out['model'] = model
        from agent_runner.slots import entries, transcript
        path = str(sid and transcript(sid) or '')
        st: dict = {}
        if path:
            f = Path(path).stat()
            mark = (f.st_size, f.st_mtime_ns)
            if _CHAT_STATE.get(path, (None,))[0] != mark:
                from agent_runner import chat_question
                rows = list(entries(sid, skip_bad=True))
                _CHAT_STATE[path] = (mark, K.control_state(rows), chat_question.ask(rows, bare=True))  # B832: one read
            st = _CHAT_STATE[path][1]
            if q := _CHAT_STATE[path][2]:  # B832: the DECIDE it ends on, for Home's Needs you (`chat_question.chat_needs`)
                out.update(question=q, sid=sid)
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


def new_chat_model() -> str:
    """F406g: the provider's name and model of a new chat ('Codex · gpt-6-sol'); '' on Claude Code."""
    try:
        from agent_runner import control_harness
        return control_harness.new_chat_model()
    except Exception:  # noqa: BLE001 - settings that cannot be read are said elsewhere
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


def closed_rows(listed: set[str] = frozenset()) -> list[dict]:
    """B859: each control session closed for being idle (`control_closed.idle_closed_chats`) as a cN row with state
    'closed' and 'closed': True, so the page lists it in Quiet until chat_quiet passes; not those in `listed`."""
    try:
        from agent_runner.control import control_given
        from agent_runner.control_closed import idle_closed_chats
        gone = idle_closed_chats(chat_quiet())
    except Exception:  # noqa: BLE001 - no notes dir yet
        return []
    out = []
    for n in sorted(gone):
        if f'c{n}' in listed:
            continue
        at, sid = gone[n]
        row = {'name': f'c{n}', 'task': '', 'title': given_title(control_given(n), n), 'minutes': None,
               'state': 'closed', 'files': [], 'terminal': '', **chat_row(n, sid), 'closed': True}
        row['at'] = row.get('at') or int(at)
        row['needs_reply'] = False
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
    if windows is None:
        out += closed_rows({r['name'] for r in out})
    merging = set(st.get('merging') or [])
    running = dict(st.get('running') or {})
    for n in range(1, slots + 1):
        running.setdefault(str(n), '')
    from agent_runner.merge_rows import gate_phase, live_gates
    gates = live_gates() if any(running.values()) else []
    for n, tid in sorted(running.items(), key=lambda kv: (not kv[0].isdigit(), kv[0].zfill(4))):
        name = f's{n}' if n.isdigit() else n
        if not tid:
            out.append(idle_row(name))
            continue
        since = (st.get('since') or {}).get(n)
        out.append({'name': name, 'task': tid, 'title': titles.get(tid, ''),
                    'minutes': int((now - since) // 60) if since else None,
                    'state': 'merging' if tid in merging else 'running',
                    'gate': gate_phase(tid, n, gates), 'files': files.get(tid, []),
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


def pr_lines() -> list[str]:
    """F420: the open pull requests' status lines (`pr_rows.lines`)."""
    try:
        from agent_runner import pr_rows
        return pr_rows.lines()
    except Exception:  # noqa: BLE001 - costs the lines, not the snapshot
        return []


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


_FILE_AGENT: dict = {}  # `agent_problem`: root -> its settings files as last read, the agent they name, whether a role runs on it


def agent_problem(c=None, st: dict | None = None) -> str:
    """B764b: what is wrong with `[run] agent` of config `c` (default: this one), else ''. What its files say
    now counts: a wrong agent saved under a run that keeps its own, a fix this process has not loaded. `st`: an up run's STATE, which says what that
    run finds (its PATH may not be this process's)."""
    if st and 'agent_problem' in st:
        return str(st['agent_problem'] or '')
    c = c or S.C
    if not c:
        return ''
    from agent_runner import claude_use, config
    now = config.settings_print(c.root)
    if _FILE_AGENT.get(c.root, (None,))[0] != now:
        try:
            new = config.Config(c.root)
        except (Exception, SystemExit):  # noqa: BLE001 - a file that does not load: the run log says it
            new = c
        _FILE_AGENT[c.root] = now, new.run['agent'], claude_use.uses(new, c.run.get('model_flag') or '')
    return config.agent_problem(c.root, *_FILE_AGENT[c.root][1:])


def status_rows(up: bool, st: dict, progress: str, login: str | None = None) -> list[str]:
    """The status lines: the run's state, progress, the no-settings, no-gate and wrong-agent warnings, and usage. `login`: the Claude
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
    if line := agent_problem(st=st if up else None):  # B764b
        out.append(line)
    from agent_runner.watch import claude_login_line
    if login := claude_login_line() if login is None else login:  # F126
        out.append(login)
    if unpushed := unpushed_line():
        out.append(unpushed)
    out += pr_lines()  # F420
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


_LATELY: list = [None, [], []]  # the event log's path, size and time, and what lately() and past_releases() read from it
LATELY_MAX, PAST_RELEASES = 60, 20  # rows a snapshot carries
LATELY_ALL = 6  # of every kind, newest first; past these a row is a landing


def landed_row(at: str, tid: str, text: str) -> dict:
    """F426c: a "lately" line as a row: 'id' its task, 'kind' 'landed' or 'part' for a landing, with its 'title'."""
    from agent_runner.status import SAID
    row = {'at': at, 'text': text, 'id': tid, 'kind': ''}
    for kind, event in (('landed', S.EV_LANDED), ('part', S.EV_PART)):
        if tid and text.startswith(f'{SAID[event]}: '):
            row.update(kind=kind, title=text.removeprefix(f'{SAID[event]}: ').removesuffix(f' [{tid}]'))
            break
    return row


def _landings(titles: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(`lately`'s rows, `past_releases`'), read again only when the event log changed."""
    from agent_runner.status import events_file, lately_events, read_events, release_version
    try:
        f = events_file().stat()
        mark = (str(events_file()), f.st_size, f.st_mtime_ns)
    except (OSError, AttributeError):
        mark = None
    if mark is None or _LATELY[0] != mark:
        try:
            evs = read_events()
            rows = [landed_row(*m) for m in lately_events(evs[-2000:], titles)][::-1]
            rows = [r for i, r in enumerate(rows) if i < LATELY_ALL or r['kind']][:LATELY_MAX]
            past: list[dict] = []
            for j in range(len(evs) - 1, -1, -1):
                tid = evs[j].get('id') or ''
                if evs[j]['kind'] == S.EV_LANDED and P.release(tid) and tid not in {r['id'] for r in past}:
                    past.append({'id': tid, 'title': f'Release {release_version(evs, j)}'.rstrip(), 'at': evs[j]['time'][:19]})
                    if len(past) == PAST_RELEASES:
                        break
            _LATELY[:] = [mark, rows, past]
        except Exception:  # noqa: BLE001 - no event log yet
            return [], []
    return _LATELY[1], _LATELY[2]


def lately(titles: dict[str, str]) -> list[dict]:
    """F124: what landed lately, newest first: `status`'s "lately" lines, from the event log (`landed_row`)."""
    return _landings(titles)[0]


def past_releases(titles: dict[str, str]) -> list[dict]:
    """F426c: the releases that landed, newest first; [] with `[run] releases` off (F193)."""
    return _landings(titles)[1] if releases_on() else []


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


RUN_WAIT = 'waits for the run to start'


def wait_for_run(queue: list[dict]) -> list[dict]:
    """F402c1: the queue rows `queue` with no run up: one that nothing else keeps says that it waits for the run, in
    the words of state 'tool', which the run page and the TUI both show. A release's words are its own row's."""
    from agent_runner.sched import taken
    by_hand = taken() if any(q.get('under_way') for q in queue) else ()  # one that waits to resume waits for the run
    live = {tid for _, box, tid, _, _ in P.iter_tasks(P.lines(S.C.todo)) if box in ' ~'}
    for q in queue:
        if q.get('state') == 'critical' and live & set(q.get('after') or []):
            q['state'] = 'after'  # another task keeps it first
        if q.get('state') in ('ready', 'critical') and not q.get('release') and q.get('id') not in by_hand:
            q.update(tool_wait=RUN_WAIT + (', goes first' if q['state'] == 'critical' else ''), state='tool',
                     waits_run=True)
    return queue


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
    from agent_runner import merge_rows, pr_rows
    from agent_runner.status import progress_line, release_line, waiting_ok
    from agent_runner.watch import claude_login_line
    up = S.run_up() if up is None else up
    now = time.time() if now is None else now
    st, ls = _state(up), P.lines(S.C.todo)
    login = claude_login_line()  # F126a
    titles = P.titles(S.C.done, S.C.todo, width=200)
    releases = release_rows(ls, st, now=now)  # F185
    release, manage = release_line(ls, st, releases), releases_on()  # F193: off, `release` has the 'last:' lines alone
    try:
        progress = progress_line(now=dt.datetime.fromtimestamp(now))
    except Exception:  # noqa: BLE001 - a git hiccup costs the progress line, not the snapshot
        progress = ''
    waiting = waiting_ok()
    needs, concepts = needs_rows(waiting, dt.datetime.fromtimestamp(now))
    need_tools(needs)  # F428b
    shelved = shelved_rows(ls, waiting)  # F184
    slots = slot_count(up, st)
    sessions = session_rows(st, ls, titles, now, links, terminal_base, slots, windows)
    for r in sessions:
        r['task_controls'] = task_controls_on(r)  # C33
    run = {'paused': bool(up and st.get('paused')), 'stopping': bool(up and st.get('stopping')),
           'forced': bool(up and st.get('forced')), 'power': str(st.get('power') or '') if up else '',
           'state': run_state(up, st)}  # F124
    queue = pin_releases(queue_rows(ls, st, now), releases)
    prs = pr_rows.rows(titles=titles)  # F420
    queue = pr_rows.mark(queue, prs, bool(up))
    if not up:
        queue = wait_for_run(queue)  # F402c1
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
            'tools': tools, 'tool_names': project_tools(), 'untils': until_rows(ls, titles),  # F427d
            'slots': slots, 'sessions': sessions, 'sessions_note': '',
            'queue': queue, 'manage_releases': manage, 'releases': releases,
            'release_acts': [c['key'] for c in RUN_CONTROLS if c['where'] == 'release' and manage],
            'shelved': shelved, 'needs': needs, 'chat_needs': chat_needs(sessions),  # B832
            'concepts': concepts, 'log': log_tail(log_n), 'release': release if manage else '',
            'release_said': rel_ask['said'] if rel_ask else '',
            'quick_asks': quick_asks(), 'terminal_mode': terminal_mode(), 'controls': controls(rel_ask),
            'no_settings': no_settings(st=st if up else None),  # F178
            'agent_problem': agent_problem(st=st if up else None),  # B764b
            'claude_login': login,  # F126a
            'unpushed': unpushed_line(),  # F98
            'prs': prs, 'pr_limit': pr_rows.limit_line(),  # F420
            'responses': kept_responses(),  # F425a
            'kinds': theme.kind_table(_kind_names()),  # F195b
            'merging': merge_rows.rows(st, titles, _bridge_link, links) if up else [],  # F426e
            'usage_max': {'session': S.C.run.get('session_max'), 'week': S.C.run.get('weekly_max')},  # F426e
            'usage_held': _usage_held(st) if up else '',  # F468
            'usage': usage_rows(st), 'lately': lately(titles), 'past_releases': past_releases(titles), 'chat_quiet': chat_quiet(), 'chat_model': new_chat_model(),
            'version': str(st.get('version') or '')}  # F90: the run's version ('' from an older run)


def _usage_held(st: dict) -> str:
    """F468: the line saying the usage caps hold new tasks, '' when they do not."""
    import time
    from agent_runner.cap_hold import held_line
    return held_line(st, S.C.run, time.time())


def kept_responses() -> list[dict]:
    """F425a: the kept Needs you responses that opened no chat, newest first."""
    try:
        from agent_runner import sent_responses as R
        return R.recent()
    except Exception:  # noqa: BLE001 - costs the rows, not the snapshot
        return []


def need_tools(needs: list[dict]) -> None:
    """F428b: to a Needs you row's `devices`, the runner.toml tools with a web page that its task needs, each with its
    `source` and `label`. A tool whose name a device also has is the tool, as `needs:` takes it."""
    from agent_runner import device_page, devices, need_detail, shared_tools
    try:
        texts = need_detail.task_lines() if needs else {}
        lines = [(r, l) for r in needs if ' | needs: ' in (l := texts.get(r['id'], '').partition('\n')[0])]
        if not lines or not (pages := devices.tool_pages(S.C)):
            return
        specs = shared_tools.specs(S.C)
        for r, l in lines:
            rows = [{'name': n, 'label': specs[n]['label'], 'source': devices.TOML, 'page': dev['page'],
                     'state': device_page.state(devices._page_dir(dev)) if dev.get('page_id') else ''}
                    for n in shared_tools.needs_of(l, S.C)
                    if not specs[n]['device'] and (dev := pages.get(n)) and dev.get('page')]
            if rows:
                r['devices'] = r.get('devices', []) + rows
    except Exception:  # noqa: BLE001 - costs the links, not the snapshot
        return


def until_rows(ls: list[str], titles: dict[str, str], c=None) -> list[dict]:
    """F427d: each check some blocked task in TODO.md's lines `ls` waits on, for the Tools page: {check, label, state,
    said, at (the last check's time, '' before the first), tasks: [{id, title}]}. [] when none waits."""
    from agent_runner import until, until_watch
    try:
        waits = until_watch.waiters(ls)
        seen = until_watch.read(c)
        out = []
        for check in sorted({x for cs in waits.values() for x in cs}):
            r = seen.get(check) or {}
            at = r.get('at')
            out.append({'check': check, 'label': until.label(check, c), 'state': str(r.get('state') or ''),
                        'said': str(r.get('said') or ''),
                        'at': dt.datetime.fromtimestamp(at).isoformat(timespec='seconds') if at else '',
                        'tasks': [{'id': t, 'title': titles.get(t, '')} for t in sorted(waits) if check in waits[t]]})
        return out
    except Exception:  # noqa: BLE001 - costs the list, not the snapshot
        return []


def until_check(check: str = '') -> dict:
    """F427d: Check now: one round of the until checks at once (each check a task waits on, `until_watch.round_`), which
    reopens the tasks whose checks all pass. `check` is the one pressed, named in the answer."""
    from agent_runner import until, until_watch
    if not until_watch._BUSY.acquire(blocking=False):
        return {'ok': False, 'code': 1, 'out': 'The checks are running already; they show the result in a moment.', 'argv': []}
    try:
        reopened = until_watch.round_(S.default_branch())
    except Exception as e:  # noqa: BLE001 - an answer, not a raise
        return {'ok': False, 'code': 1, 'out': f'Could not run the checks: {e}', 'argv': []}
    finally:
        until_watch._BUSY.release()
    r = until_watch.read().get(check) or {}
    name = until.label(check) if check else 'The checks'
    said = f'{name}: {r.get("state") or "checked"}' + (f', {r["said"]}' if r.get('said') else '')
    if reopened:
        said += f'. Reopened {", ".join(reopened)}.'
    return {'ok': True, 'code': 0, 'out': said, 'argv': []}


def tools_line(tools: list[dict]) -> str:
    from agent_runner import shared_tools
    return shared_tools.line(tools)


def snapshot_json(**kw) -> str:
    return json.dumps(snapshot(**kw), ensure_ascii=False)


def chat_needs(sessions: list[dict]) -> list[dict]:
    """B832: `chat_question.chat_needs`; [] when it cannot be read (a nicety of Home, not the snapshot's)."""
    try:
        from agent_runner import chat_question
        return chat_question.chat_needs(sessions)
    except Exception:  # noqa: BLE001
        return []
