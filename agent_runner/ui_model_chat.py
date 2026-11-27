"""C44: the feed, chatting with any control session, quick asks, concept copies, the terminal view.

Part of `ui_model`: `ui_model` runs this file in its own namespace (see its end), so these names are `ui_model`'s, and a
test that sets `ui_model.X` reaches the code here. Not imported on its own."""

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
    kept = kept + (queued_lines(name) if name[:1] == 'c' and S.C else [])  # F192d1: what a tap queued
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


def find_ttyd() -> str:
    """B761: the ttyd to run, '' when there is none. A run that was up when winget installed it still has the PATH from
    before, so winget's own folders are looked in too: Links, or the package's (no Links where Windows allows no links)."""
    import shutil
    from agent_runner import plat
    if got := shutil.which('ttyd'):
        return got
    if not plat.WINDOWS or not (local := os.environ.get('LOCALAPPDATA')):
        return ''
    winget = Path(local, 'Microsoft', 'WinGet')
    found = [winget / 'Links' / 'ttyd.exe', *winget.glob('Packages/tsl0922.ttyd_*/ttyd.exe')]
    return next((str(p) for p in found if p.is_file()), '')


def terminal_mode() -> str:
    """F74: how a page shows a session's terminal: 'ttyd' (installed: it serves `attach NAME`) or 'install' (no
    ttyd: the page says how to install it; C25). F114: on Windows too."""
    return 'ttyd' if find_ttyd() else 'install'


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


def _wake_closed(name: str, wait: bool) -> dict | None:
    """B859: a message to chat `name` that was closed for being idle (`control_closed.idle_closed_chats`) reopens it
    first (`control_reopen.reopen_control`), waiting up to START_WAIT s for it to come up. None to go on; else
    the answer (not sent). `wait` is not looked at: it always waits."""
    m = re.fullmatch(r'c(\d+)', name or '')
    if not m or hidden_inbox(name):
        return None
    from agent_runner import control as K
    from agent_runner.control_reopen import reopen_control
    from agent_runner.control_closed import idle_closed_chats
    n = int(m[1])
    if not (gone := idle_closed_chats(chat_quiet()).get(n)):
        return None
    if not reopen_control(n, gone[1]):
        return {'ok': False, 'code': 1, 'out': f'{name} could not be reopened', 'argv': []}
    K.log(f'control {n}: reopened, the person wrote to it after it was closed for being idle')
    end = time.monotonic() + START_WAIT  # waits even for the page: a second try would reopen it twice
    while not hidden_inbox(name):
        if time.monotonic() >= end:
            return {'ok': False, 'code': 1, 'out': f'{name} is still starting, so it could not take the message',
                    'argv': []}
        time.sleep(0.2)
    return None


def chat_to(text: str, to: str = '', force: bool = False, unsent: bool = False, wait: bool = True) -> dict:
    """F74: the chat box of any control session: `to` (c6) gets `text`, with no `to` a new one (F176). B154: 'at' is when it was typed, and
    'name' the new control session. F170: `force` interrupts it first while it works
    (`session_now.force_send`); `unsent`: the page sees words in its input, so the text goes below them.
    F190b: `force` with no text sends what is queued in it (`session_now.force_queued`) and types nothing.
    B158: a chat still starting gets it once it takes input; with `wait` False (the run page) the answer is 'hold'
    meanwhile."""
    if force and not text.strip():
        if not to:
            return {'ok': False, 'code': 2, 'out': 'chat_to: force with no text needs a session', 'argv': []}
        from agent_runner.session_now import force_queued
        return {**force_queued(to, unsent), 'at': time.time()}
    if held := _wake_closed(to, wait):
        return held
    if held := _starting(to, wait):
        return held
    at = time.time()
    if to and (force or unsent):
        from agent_runner.session_now import force_send
        r = {**force_send(to, text, send, unsent, force), 'at': at}
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
    r = name_new(call(['control', '--new', *([] if wait else ['--no-wait']), *(['--ask', ask, '--no-feed'] if ask else [])]), ask)
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


def name_new(r: dict, ask: str) -> dict:
    """F196e: a new chat (`r`, the answer of `control --new`, which names it 'control N') that has no name of its own yet
    gets its first message's words (`control_name`), so its row reads them while it starts, never the bare cN; its own
    title (`control --title`) replaces them later. `r` as it was."""
    n = re.search(r'\bcontrol (\d+) ', r.get('out') or '') if r.get('ok') and ask else None
    if not n:
        return r
    try:
        from agent_runner import control as K
        if given_title(K.control_given(int(n.group(1))), int(n.group(1))) == 'control session':
            K.control_give(int(n.group(1)), K.control_name(int(n.group(1)), ask))
    except Exception:  # noqa: BLE001 - no notes dir: the name stays as control gave it
        pass
    return r


# --- F192d1: one tap queues an option's stored tasks ------------------------------------------------------------

def with_task_counts(live: dict) -> dict:
    """F192d1: `live` (`session_now.live`) with each question ('ask', 'asks') carrying 'tasks': {option: how many
    stored tasks it queues} (`option_tasks.counts`); options without stored tasks are left out."""
    from agent_runner import option_tasks

    def one(a):
        if not isinstance(a, dict) or not a.get('question'):
            return a
        try:
            n = option_tasks.counts(a['question'])
        except Exception:  # noqa: BLE001 - no notes dir: no counts
            n = {}
        return {**a, 'tasks': n}
    return {**live, **({'ask': one(live['ask'])} if live.get('ask') else {}),
            **({'asks': [one(a) for a in live['asks']]} if live.get('asks') else {})}


def queued_lines_file(name: str) -> Path:
    """F192d1: the run's own chat lines of chat `name` (what a tap queued), never sent to Claude."""
    return S.C.notes(f'{name}.queued-lines.json')


def queued_lines(name: str) -> list[dict]:
    try:
        rows = json.loads(queued_lines_file(name).read_text())
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def option_queue(chat: str, question: str, option: str) -> dict:
    """F192d1: queue `option`'s stored tasks of `question` in chat `chat` at once (`option_tasks.queue`, once only)
    and add one chat line saying what was queued; nothing is sent to Claude. Not ok when none were stored or they were
    queued already (a second tap adds nothing)."""
    from agent_runner import option_tasks
    if not re.fullmatch(r'c\d+', chat or '') or not question or not option:
        return {'ok': False, 'code': 2, 'out': f'option_queue: a chat, a question and an option; not {chat!r}', 'argv': []}
    tasks = option_tasks.queue(question, option)
    if not tasks:
        return {'ok': False, 'code': 1, 'out': 'Nothing to queue (queued already?)', 'argv': []}
    words = '; '.join(next((a for a in t if not a.startswith('-') and len(a) > 2), t[0]) for t in tasks)
    line = f'“{option}”: queued {len(tasks)} task{"s" if len(tasks) != 1 else ""}: {words}'
    rows = queued_lines(chat)
    rows.append({'kind': 'out', 'text': line, 'id': f'queued:{len(rows)}', 'at': time.time()})
    try:
        queued_lines_file(chat).write_text(json.dumps(rows, ensure_ascii=False))
    except OSError:
        pass
    return {'ok': True, 'code': 0, 'out': line, 'queued': len(tasks), 'argv': []}


ACTIONS['option_queue'] = option_queue
