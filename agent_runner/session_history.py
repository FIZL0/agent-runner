"""F191a: a chat's or slot's whole history, from its transcript, in pages, as data the run page draws in Claude
Code's terminal look. Claude Code's fullscreen session keeps its older lines to itself, so the transcript is the
only source.

    history(name)               the newest page
    history(name, before=MARK)  the page before it ('before' of the page the caller has)
    history(name, since=MARK)   what was written after it ('since' of the last answer)

Pages go from newest to oldest; inside one, entries run oldest to newest, the order they are drawn in. A mark names
the transcript and a byte in it, so no page reads more of a long transcript than it needs. A mark of another
transcript (after a /clear, or a slot's next session) or past the end gives the newest page with `reset` true:
the caller drops what it has.

An answer is {'ok', 'name', 'entries', 'before' ('' at the start of the transcript), 'since', 'reset', 'more' (of a
`since`: more was written than one answer holds, ask again)}. An entry has 'kind', 'id' (the same in every answer),
'at' (epoch s, when the transcript says), and by its kind:

    you     'text', 'images' (how many), 'from': 'person' | 'runner', 'cut' (characters left out), 'command' (true
            for a slash command)
    say     'text', Claude's markdown
    tool    'name' and 'arg' as Claude Code words the call: Update(a.py); 'call' (its id); 'group' 'read' | 'search'
            (neighbours with one Claude Code folds to one line, "Read 3 files"); 'state' 'open' (no result
            yet: at work while the session is, else cut off; /live says which) | 'ok' | 'error'; and once it has a result, a result's fields
    result  'call' and a result's fields: the result of a call that is in no entry of this answer, because the caller
            has it already (or, after a very long call, gets it with an older page)
    note    'what' (NOTES) and 'text'; a 'turn' has 'ms' instead, how long the turn took

A result's fields: 'state', 'summary' (the folded line, '' for none), 'text' (its output, cut), 'show' (how many
lines of it are shown while folded), 'lines' (how many the whole output has; `lines - show` is Claude Code's
"… +N lines"), and 'diff': files as {'file', 'added', 'removed', 'hunks': [{'old', 'new', 'lines'}], 'cut'}."""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_runner import ui_model as U

PAGE = 100  # entries a page holds, about
PAGE_MAX = 300
PAGE_BYTES = 6_000_000  # how much transcript one answer reads at most, a single longer line apart
PAIR_BYTES = 4_000_000  # how much more it reads for the call of a result
BLOCK = 1 << 18
YOU_CHARS, OUT_LINES, OUT_CHARS, ARG_CHARS = 10_000, 60, 6_000, 400
SHOW, SHOW_ERROR, SHOW_WRITE = 3, 10, 10  # the lines of an output Claude Code shows folded
DIFF_LINES = 120
NOTES = ('compacted', 'output', 'recap', 'event', 'hook', 'error', 'interrupted', 'info', 'turn')

BRIEF = 'Unattended run: '  # how a task's brief, a slot's first message, starts
TAGS = re.compile(r'</?pasted_content[^>]*>\n?')
REMINDER = re.compile(r'<system-reminder>.*?</system-reminder>\s*', re.S)
ANSI = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]')
TOOL_NAMES = {'Edit': 'Update', 'MultiEdit': 'Update', 'NotebookEdit': 'Update', 'Grep': 'Search', 'Glob': 'Search',
              'WebFetch': 'Fetch', 'WebSearch': 'Web Search'}
GROUPS = {'Read': 'read', 'Grep': 'search', 'Glob': 'search'}


# --- the transcript's lines ----------------------------------------------------------------------------------

def lines_before(f, end: int):
    """(start byte, line) of each line of `f` before byte `end` (a line's start), last first."""
    held: list[bytes] = []  # the pieces of a line whose start is not read yet, last first
    pos = end
    while pos > 0:
        n = min(BLOCK, pos)
        pos -= n
        f.seek(pos)
        first, *rest = f.read(n).split(b'\n')
        if rest:
            at = pos + n
            for part in reversed(rest):
                at -= len(part)
                line = part + b''.join(reversed(held))
                held = []
                if line:
                    yield at, line
                at -= 1
        held.append(first)
    if line := b''.join(reversed(held)):
        yield 0, line


def whole_end(f) -> int:
    """The byte after the last whole line of `f`: one being written is left for later."""
    f.seek(0, 2)
    pos = f.tell()
    while pos > 0:
        n = min(BLOCK, pos)
        f.seek(pos - n)
        if (i := f.read(n).rfind(b'\n')) >= 0:
            return pos - n + i + 1
        pos -= n
    return 0


def parse(line: bytes) -> dict | None:
    try:
        d = json.loads(line.decode('utf-8', errors='replace'))
    except (ValueError, RecursionError):
        return None
    if not isinstance(d, dict):
        return None
    try:
        from agent_runner.slots import backend
        return backend().entry(d)
    except Exception:  # noqa: BLE001 - no project initialised: Claude's shape as it is
        return d


# --- a transcript entry as history entries -------------------------------------------------------------------

def _tag(text: str, name: str) -> str:
    m = re.search(rf'<{name}>(.*?)</{name}>', text, re.S)
    return m.group(1).strip() if m else ''


def _cut(text: str, lines: int, chars: int) -> str:
    return '\n'.join(text.splitlines()[:lines])[:chars]


def _note(what: str, text: str) -> dict:
    return {'kind': 'note', 'what': what, 'text': text}


def told(text: str) -> list[dict]:
    """A user message's text as entries: the person's or the runner's words, a slash command, a command's output, a
    background event; [] for text Claude Code does not show."""
    from agent_runner.control import LEAD, RUNNER_TURN
    t = text.strip()
    if t.startswith('<task-notification>'):
        return [_note('event', _tag(t, 'event') or _tag(t, 'summary') or 'Background work ended')]
    if t.startswith('<bash-input>'):
        return [{'kind': 'you', 'text': '! ' + _tag(t, 'bash-input'), 'images': 0, 'from': 'person', 'cut': 0}]
    if t.startswith(('<local-command-stdout>', '<local-command-stderr>', '<bash-stdout>', '<bash-stderr>')):
        out = '\n'.join(x for n in ('local-command-stdout', 'local-command-stderr', 'bash-stdout', 'bash-stderr')
                        if (x := _tag(t, n)))
        return [_note('output', _cut(ANSI.sub('', out), OUT_LINES, OUT_CHARS))] if out else []
    if t.startswith(('<command-name>', '<command-message>')):
        if not (cmd := _tag(t, 'command-name')):
            return []
        words = f'{cmd} {_tag(t, "command-args")}'.strip()
        return [{'kind': 'you', 'text': words, 'images': 0, 'from': 'person', 'cut': 0, 'command': True}]
    t = TAGS.sub('', REMINDER.sub('', t)).strip()
    if not t or (t.startswith(RUNNER_TURN) and not t.startswith(LEAD)):
        return []
    return [{'kind': 'you', 'text': t[:YOU_CHARS], 'images': 0, 'cut': max(len(t) - YOU_CHARS, 0),
             'from': 'runner' if t.startswith((LEAD, BRIEF)) else 'person'}]


def call_words(name: str, args) -> tuple[str, str]:
    """A tool call as Claude Code words it: ('Update', 'a.py')."""
    a = args if isinstance(args, dict) else {}
    shown = TOOL_NAMES.get(name, name)
    if m := re.fullmatch(r'mcp__(.+?)__(.+)', name):
        shown = f'{m.group(1)} - {m.group(2)} (MCP)'
    elif name in ('Agent', 'Task') and isinstance(a.get('subagent_type'), str) and a['subagent_type']:
        shown = a['subagent_type']
    keys = ('description', 'prompt') if name in ('Agent', 'Task') else (
        'command', 'file_path', 'notebook_path', 'path', 'pattern', 'url', 'query', 'skill', 'description', 'prompt')
    if name in ('Grep', 'Glob'):
        bits = [f'{k}: "{a[k]}"' for k in ('pattern', 'path', 'glob') if isinstance(a.get(k), str) and a[k]]
        return shown, ', '.join(bits)[:ARG_CHARS]
    arg = next((a[k] for k in keys if isinstance(a.get(k), str) and a[k].strip()), None)
    if arg is None:
        arg = next((v for v in a.values() if isinstance(v, str) and v.strip()), '')
    arg = arg.strip()
    return shown, arg if len(arg) <= ARG_CHARS else arg[:ARG_CHARS - 1] + '…'


def system_note(d: dict) -> list[dict]:
    sub, text = d.get('subtype'), d.get('content') if isinstance(d.get('content'), str) else ''
    if sub == 'turn_duration':
        ms = d.get('durationMs')
        return [{'kind': 'note', 'what': 'turn', 'ms': ms}] if isinstance(ms, (int, float)) else []
    if sub == 'compact_boundary':
        return [_note('compacted', text or 'Conversation compacted')]
    if sub == 'away_summary':
        return [_note('recap', text)] if text else []
    if sub == 'local_command':
        return told(text)
    if sub in ('informational', 'bridge_status', 'api_error') and text:
        return [_note('error' if d.get('level') == 'error' or sub == 'api_error' else 'info', ANSI.sub('', text))]
    return []


def row_entries(d: dict, at: int) -> list[dict]:
    """Transcript entry `d`, at byte `at`, as history entries. A tool call keeps its input ('_args'), and a result is
    raw ('_block', '_made'), until `joined` words them."""
    from agent_runner.control import _stamp
    from agent_runner.feed import queued_message
    if d.get('isSidechain') or d.get('isMeta') or d.get('isCompactSummary') or d.get('isVisibleInTranscriptOnly'):
        return []
    uid = d['uuid'] if isinstance(d.get('uuid'), str) and d['uuid'] else str(at)
    when = _stamp(d)
    d = queued_message(d) or d
    made: list[tuple[int, dict]] = []
    if d.get('type') == 'system':
        made = [(0, e) for e in system_note(d)]
    elif d.get('type') == 'attachment':
        a = d.get('attachment') if isinstance(d.get('attachment'), dict) else {}
        if a.get('type') == 'queued_command':  # a background event that came during a turn
            made = [(0, e) for e in told(U._blocks_text(a.get('prompt'))) if e['kind'] == 'note']
        elif a.get('type') == 'hook_blocking_error':
            err = a.get('blockingError')
            err = err.get('blockingError') if isinstance(err, dict) else err
            made = [(0, _note('hook', f'{a.get("hookName") or "Stop"} hook error: {err}'))] if isinstance(err, str) else []
    elif d.get('type') in ('user', 'assistant'):
        m = d.get('message') if isinstance(d.get('message'), dict) else {}
        c = m.get('content')
        blocks = [{'type': 'text', 'text': c}] if isinstance(c, str) else c if isinstance(c, list) else []
        blocks = [(j, b) for j, b in enumerate(blocks) if isinstance(b, dict)]
        results = sum(b.get('type') == 'tool_result' for _, b in blocks)
        for j, b in blocks:
            text = b['text'].strip() if b.get('type') == 'text' and isinstance(b.get('text'), str) else ''
            if d['type'] == 'assistant':
                if text:
                    made.append((j, _note('error', text) if d.get('isApiErrorMessage') else {'kind': 'say', 'text': text}))
                elif b.get('type') == 'tool_use':
                    name = str(b.get('name') or 'tool')
                    shown, arg = call_words(name, b.get('input'))
                    made.append((j, {'kind': 'tool', 'name': shown, 'arg': arg, 'call': str(b.get('id') or ''),
                                     **({'group': GROUPS[name]} if name in GROUPS else {}), 'state': 'open',
                                     '_tool': name, '_args': b.get('input')}))
            elif b.get('type') == 'tool_result':
                made.append((j, {'kind': 'result', 'call': str(b.get('tool_use_id') or ''), '_block': b,
                                 '_made': d.get('toolUseResult') if results == 1 else None}))
            elif text.startswith(U.INTERRUPTED):
                made.append((j, _note('interrupted', 'Interrupted')))
            elif text:
                made += [(j, e) for e in told(text)]
        if d['type'] == 'user' and (pics := sum(b.get('type') == 'image' for _, b in blocks)):
            said = next((e for _, e in made if e['kind'] == 'you'), None)
            if said:
                said['images'] = pics
            elif not results:
                made.append((0, {'kind': 'you', 'text': '', 'images': pics, 'from': 'person', 'cut': 0}))
    return [{**e, 'id': f'{uid}:{j}', **({'at': when} if when else {})} for j, e in made]


# --- results, folded as Claude Code folds them ---------------------------------------------------------------

def diff_of(path, patch, room: int = DIFF_LINES) -> dict:
    """One file's structured patch as a result's 'diff' entry, with at most `room` lines."""
    out: dict = {'file': str(path or ''), 'added': 0, 'removed': 0, 'hunks': [], 'cut': 0}
    for h in patch if isinstance(patch, list) else []:
        if not isinstance(h, dict) or not isinstance(h.get('lines'), list):
            continue
        ls = [x for x in h['lines'] if isinstance(x, str)]
        out['added'] += sum(x.startswith('+') for x in ls)
        out['removed'] += sum(x.startswith('-') for x in ls)
        if kept := ls[:max(room, 0)]:
            out['hunks'].append({'old': h.get('oldStart') or 0, 'new': h.get('newStart') or 0,
                                 'lines': [x[:OUT_CHARS] for x in kept]})
        out['cut'] += len(ls) - len(kept)
        room -= len(kept)
    return out


def _many(n: int, word: str) -> str:
    return f'{n} {word}' + ('' if n == 1 else 's')


def changed_words(added: int, removed: int) -> str:
    bits = ([f'added {_many(added, "line")}'] if added else []) + ([f'removed {_many(removed, "line")}'] if removed else [])
    return ', '.join(bits).capitalize()


def result_fields(tool: str, args, block: dict, made) -> dict:
    """A tool result as Claude Code folds it ('a result's fields', above). `made` is the transcript's own record of it."""
    args, r = args if isinstance(args, dict) else {}, made if isinstance(made, dict) else {}
    text, summary, show, diff = U._blocks_text(block.get('content')), '', SHOW, []
    if block.get('is_error'):
        text = re.sub(r'</?tool_use_error>', '', text).strip()
        if made == 'User rejected tool use' or text.startswith("The user doesn't want to proceed"):
            return {'state': 'error', 'summary': 'Interrupted', 'text': '', 'show': 0, 'lines': 0}
        text = text if text.startswith('Error') else f'Error: {text}'
        show = SHOW_ERROR
    elif isinstance(r.get('stdout'), str) or isinstance(r.get('stderr'), str):
        text = '\n'.join(x.strip('\n') for x in (r.get('stdout'), r.get('stderr')) if isinstance(x, str) and x.strip())
        if r.get('backgroundTaskId'):
            summary = 'Running in the background'
        elif r.get('isImage'):
            summary, text = '[Image]', ''
        elif not text:
            summary = '(No output)'
        edits = r.get('bashEditDiff') if isinstance(r.get('bashEditDiff'), dict) else {}
        room = DIFF_LINES
        for x in edits.get('files') if isinstance(edits.get('files'), list) else []:
            if isinstance(x, dict):
                diff.append(diff_of(x.get('filePath'), x.get('hunks'), room))
                room -= sum(len(h['lines']) for h in diff[-1]['hunks'])
    elif isinstance(r.get('structuredPatch'), list) and r['structuredPatch']:
        diff = [diff_of(r.get('filePath') or args.get('file_path'), r['structuredPatch'])]
        summary, text, show = changed_words(diff[0]['added'], diff[0]['removed']), '', 0
    elif tool == 'Write':
        text = args.get('content') if isinstance(args.get('content'), str) else text
        summary, show = f'Wrote {_many(len(text.splitlines()), "line")} to {args.get("file_path", "")}', SHOW_WRITE
    elif tool in ('Edit', 'MultiEdit', 'NotebookEdit'):
        old, new = (str(args.get(k) or '').splitlines() for k in ('old_string', 'new_string'))
        if tool == 'Edit' and (old or new):  # no patch in the transcript: the call's own two texts
            diff = [diff_of(args.get('file_path'), [{'lines': ['-' + x for x in old] + ['+' + x for x in new]}])]
            summary, text, show = changed_words(len(new), len(old)), '', 0
    elif tool == 'Read':
        f = r.get('file') if isinstance(r.get('file'), dict) else {}
        n = f.get('numLines') if isinstance(f.get('numLines'), int) else len(text.splitlines())
        image = r.get('type') == 'image' or (not text and any(
            isinstance(b, dict) and b.get('type') == 'image' for b in block.get('content') or []))
        summary, show = 'Read image' if image else f'Read {_many(n, "line")}', 0
    elif tool in ('Grep', 'Glob'):
        files = r.get('numFiles')
        n = r.get('numLines') or (files if isinstance(files, int) else len(text.splitlines()))
        summary, show = f'Found {_many(n, "line" if r.get("numLines") else "file" if isinstance(files, int) else "line")}', 0
    elif tool in ('Agent', 'Task'):
        summary, show = 'Backgrounded agent' if r.get('isAsync') else 'Done', 0
        text = '' if r.get('isAsync') else text
    elif tool == 'Skill':
        summary, text = 'Loaded skill', ''
    text = ANSI.sub('', text).strip('\n')
    kept = _cut(text, OUT_LINES, OUT_CHARS)
    return {'state': 'error' if block.get('is_error') else 'ok', 'summary': summary, 'text': kept,
            'show': min(show, len(kept.splitlines())), 'lines': len(text.splitlines()), **({'diff': diff} if diff else {})}


def joined(made: list[dict], earlier: dict[str, dict]) -> list[dict]:
    """The entries of an answer: each result put in its call's entry, or, when its call is in `earlier` or not found,
    an entry of its own."""
    calls: dict[str, dict] = {}
    out = []
    for e in made:
        if e['kind'] == 'tool' and e['call']:
            calls[e['call']] = e
        if e['kind'] != 'result':
            out.append(e)
            continue
        call = calls.get(e['call'])
        of = call or earlier.get(e['call']) or {}
        fields = result_fields(of.get('_tool', ''), of.get('_args'), e['_block'], e['_made'])
        if call:
            call.update(fields)
        else:
            out.append({**e, **fields})
    return [{k: v for k, v in e.items() if not k.startswith('_')} for e in out]


# --- the pages -----------------------------------------------------------------------------------------------

def page_before(f, end: int, limit: int) -> tuple[list[dict], int]:
    """(entries, start byte) of the page that ends at byte `end`. It starts at no result whose call it lacks, unless
    that call is further back than PAIR_BYTES."""
    rows: list[list[dict]] = []
    n, start = 0, end
    want: set[str] = set()  # results whose calls are not read yet
    for at, line in lines_before(f, end):
        read = end - at
        if rows and read > PAGE_BYTES + PAIR_BYTES:
            break
        start = at
        d = parse(line)
        made = row_entries(d, at) if d else []
        rows.append(made)
        for e in made:
            if e['kind'] == 'result':
                want.update({e['call']} - {''})
            else:
                n += 1
                if e['kind'] == 'tool':
                    want.discard(e['call'])
        if (n >= limit or read >= PAGE_BYTES) and not want:
            break
    return joined([e for made in reversed(rows) for e in made], {}), start


def calls_before(f, end: int, ids: set[str]) -> dict[str, dict]:
    """The tool entries of calls `ids`, made before byte `end` of `f`, at most PAIR_BYTES back."""
    out: dict[str, dict] = {}
    for at, line in lines_before(f, end):
        if out.keys() >= ids or end - at > PAIR_BYTES:
            break
        if b'tool_use' in line and any(i.encode() in line for i in ids):
            out.update({e['call']: e for e in row_entries(parse(line) or {}, at)
                        if e['kind'] == 'tool' and e['call'] in ids})
    return out


def page_since(f, start: int, end: int, limit: int) -> tuple[list[dict], int]:
    """(entries, the byte they end at) of what was written from byte `start` to `end`, an answer's worth."""
    f.seek(start)
    made: list[dict] = []
    at = start
    while at < end and len(made) < limit and at - start < PAGE_BYTES:
        line = f.readline()
        if not line.endswith(b'\n'):
            break
        if d := parse(line):
            made += row_entries(d, at)
        at += len(line)
    known = {e['call'] for e in made if e['kind'] == 'tool'}
    lost = {e['call'] for e in made if e['kind'] == 'result' and e['call']} - known
    return joined(made, calls_before(f, start, lost) if lost else {}), at


def mark_at(mark: str, of: str, end: int) -> int:
    """The byte `mark` names in transcript `of`, which ends at `end`; -1 for a mark that is not of it."""
    stem, _, at = mark.rpartition(':')
    return int(at) if stem == of and re.fullmatch(r'[0-9]{1,18}', at) and int(at) <= end else -1


def history(name: str, before: str = '', since: str = '', limit: int = PAGE) -> dict:
    """A page of session `name`'s (c6, s2) history; see the top of this file."""
    none = {'ok': False, 'name': name, 'entries': [], 'before': '', 'since': '', 'reset': False, 'more': False,
            'out': f'{name} has no transcript to read yet.'}
    path = U.transcript_of(name) if re.fullmatch(r'[cs]\d+', name) else ''
    if not path:
        return none
    limit, of = max(1, min(limit, PAGE_MAX)), Path(path).stem
    try:
        with open(path, 'rb') as f:
            end = whole_end(f)
            got = {'ok': True, 'name': name, 'before': '', 'since': f'{of}:{end}', 'reset': False, 'more': False}
            at = mark_at(since or before, of, end) if since or before else -1
            if since and at >= 0:
                entries, to = page_since(f, at, end, limit)
                return {**got, 'entries': entries, 'since': f'{of}:{to}', 'more': to < end}
            entries, start = page_before(f, at if at >= 0 else end, limit)
            return {**got, 'entries': entries, 'before': f'{of}:{start}' if start else '',
                    'reset': bool(since or before) and at < 0}
    except OSError:
        return none


def asked(name: str, query: dict[str, list[str]]) -> dict:
    """`history` as GET /history/NAME asks for it: before=MARK, since=MARK, n=ENTRIES."""
    get = lambda k: (query.get(k) or [''])[0]  # noqa: E731
    n = get('n')
    return history(name, get('before'), get('since'), int(n) if re.fullmatch(r'[0-9]{1,4}', n) else PAGE)
