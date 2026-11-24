"""F170: what a chat's or slot's Claude session is doing, for the controls the run page has in place of the lines at the
bottom of its window: its status (`status`), its background shells and agents (`tasks`), Stop and Force send, the
commands it takes (`skills`), and Claude Code's update. Read from what Claude Code keeps: `<claude dir>/sessions/PID.json`
and the session's transcript.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess as sp
import threading
import time
from pathlib import Path

from agent_runner import plat
from agent_runner import ui_model as U

BUSY = 'busy'  # Claude Code's word; 'idle', 'shell' (idle, a background shell runs) and 'waiting' (a question) are others


def record(name: str) -> dict:
    """What Claude Code keeps of the process that runs session `name` (c6, s2): its status, sessionId; {} for none."""
    from agent_runner.feed import claude_sessions_dir
    from agent_runner.slots import marker_pid
    inbox = U.hidden_inbox(name)
    pid = marker_pid(inbox.with_suffix('.live')) if inbox else 0
    if not pid:
        return {}
    for p in (pid, *plat.children(pid)):
        try:
            d = json.loads((claude_sessions_dir() / f'{p}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and plat.alive(p):
            return d
    return {}


def status(name: str) -> str:
    """'busy', 'idle', 'shell' (idle, a background shell runs), another word of Claude Code's, or '' (it says none)."""
    return str(record(name).get('status') or '')


def transcript(name: str, rec: dict) -> str:
    from agent_runner import slots
    sid = str(rec.get('sessionId') or '')
    return (slots.transcript(sid) if sid else '') or U.transcript_of(name)


# --- what is queued in it ---------------------------------------------------------------------------------------

# F190b: what Claude Code 2.1.331 queues and that no person sent
NOT_SENT = ('<task-notification>', '<agent-message', '<system-reminder>')
TAG = re.compile(r'</?pasted_content[^>]*>\n?')  # Claude Code wraps a paste (each message typed in is one) in it


def queued_in(rows, since: float = 0) -> int:
    """F190b: how many sent messages transcript entries `rows` leave queued. Claude Code writes a queue-operation entry for
    each step: enqueue (its content; none for a message with images), dequeue (the oldest goes in as the next turn),
    remove (one went into the turn under way) and popAll (what can be edited is back in the input). An entry before
    `since` (epoch s) is of an earlier process, whose queue ended with it."""
    from agent_runner.control import LEAD, _stamp
    line: list = []

    def sent(c) -> bool:
        return not (isinstance(c, str) and TAG.sub('', c).lstrip().startswith((*NOT_SENT, LEAD)))
    for d in rows:
        if d.get('type') != 'queue-operation' or (since and (_stamp(d) or since) < since):
            continue
        op, c = d.get('operation'), d.get('content')
        if op == 'enqueue':
            line.append(c)
        elif op == 'dequeue':
            del line[:1]
        elif op == 'remove' and c in line:
            line.remove(c)
        elif op == 'popAll':
            line = [x for x in line if not sent(x)]
    return sum(map(sent, line))


def queued(rec: dict, ops) -> int:
    """`queued_in` for the process of `rec` (`record`); 0 while it rests: what was queued has gone in."""
    if rec.get('status') in (None, '', 'idle', 'shell'):
        return 0
    return queued_in(ops, (rec.get('startedAt') or 0) / 1000)


def queued_now(name: str) -> int:
    """`queued` of session `name`, read now."""
    rec = record(name)
    path = transcript(name, rec) if rec else ''
    return queued(rec, U.tail_rows(path, TASK_BYTES)) if path else 0


# --- its background work ---------------------------------------------------------------------------------------

TASK_BYTES = 4_000_000  # the tail of a transcript its background work is read from
OUT_BYTES = 2000  # the tail of a shell's output its sheet shows
STARTED = re.compile(r'running in background with ID: (\w+)\. Output is being written to: (\S+\.output)')
ENDED = re.compile(r'<task-id>([\w-]+)</task-id>.*?<status>(\w+)</status>', re.S)


def tasks(rows) -> list[dict]:
    """The background shells and agents transcript entries `rows` name, oldest first: {'id', 'kind' ('shell' or
    'agent'), 'name' (the command, the agent's description), 'at' (epoch s), 'running', 'out' (a shell's output file)}."""
    from agent_runner.control import _stamp, _texts
    out: dict[str, dict] = {}
    uses: dict[str, dict] = {}
    for d in rows:
        if not isinstance(d, dict) or d.get('isSidechain'):
            continue
        if d.get('type') == 'assistant':
            for x in (d.get('message') or {}).get('content') or []:
                if isinstance(x, dict) and x.get('type') == 'tool_use':
                    uses[str(x.get('id'))] = x
                    inp = x.get('input') or {}
                    if x.get('name') in ('TaskStop', 'KillShell', 'KillBash') and \
                            (t := out.get(str(inp.get('task_id') or inp.get('shell_id')))):
                        t['running'] = False
            continue
        for t in _texts(d):
            for m in ENDED.finditer(t):
                if m[1] in out:
                    out[m[1]]['running'] = m[2] == 'running'
        content = (d.get('message') or {}).get('content') if d.get('type') == 'user' else None
        for x in content if isinstance(content, list) else ():
            if not (isinstance(x, dict) and x.get('type') == 'tool_result'):
                continue
            call = uses.get(str(x.get('tool_use_id')), {})
            got, inp = d.get('toolUseResult'), call.get('input') or {}
            text = U._blocks_text(x.get('content'))
            if m := STARTED.search(text):
                out[m[1]] = {'id': m[1], 'kind': 'shell', 'name': ' '.join(str(inp.get('command') or '').split()),
                             'at': _stamp(d) or 0, 'running': True, 'out': m[2]}
            elif isinstance(got, dict) and got.get('status') == 'async_launched' and got.get('agentId'):
                out[got['agentId']] = {'id': got['agentId'], 'kind': 'agent', 'at': _stamp(d) or 0, 'running': True,
                                       'name': str(got.get('description') or inp.get('description') or 'Agent')}
    return list(out.values())


def output_tail(path: str) -> str:
    """The end of a background shell's output file ('' for none)."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(f.tell() - OUT_BYTES, 0))
            return f.read().decode('utf-8', errors='replace').strip()
    except OSError:
        return ''


_TASKS: dict[str, tuple[int, list[dict]]] = {}  # transcript -> (its size, its tasks then)


def live(name: str) -> dict:
    """The page's word on session `name`: {'ok', 'status', 'since' (when it began, epoch s), 'mode' (its permission mode
    as the transcript has it), 'queued' (F190b: how many sent messages are queued in it), 'tasks' (`tasks`, the running ones and the last few ended; a shell's output tail in
    'tail')}."""
    rec = record(name)
    if not rec:
        return {'ok': False, 'status': '', 'since': 0, 'mode': '', 'queued': 0, 'tasks': []}
    path = transcript(name, rec)
    rows: list[dict] = []
    if path:
        try:
            size = os.stat(path).st_size
        except OSError:
            size = 0
        if _TASKS.get(path, (None,))[0] != size:
            mode, kept, ops = '', [], []
            for d in U.tail_rows(path, TASK_BYTES):
                if d.get('type') == 'permission-mode':
                    mode = str(d.get('permissionMode') or '')
                elif d.get('type') == 'queue-operation':
                    ops.append(d)
                kept.append(d)
            _TASKS[path] = (size, [{'mode': mode, 'ops': ops}, *tasks(kept)])
            while len(_TASKS) > 20:
                _TASKS.pop(next(iter(_TASKS)))
        rows = _TASKS[path][1]
    mode = rows[0]['mode'] if rows else ''
    run = [t for t in rows[1:] if t['running']]
    done = [t for t in rows[1:] if not t['running']][-3:]
    if rec.get('status') == 'idle':  # nothing of it runs any more, whatever the transcript missed
        run = [t for t in run if t['kind'] == 'agent']
    return {'ok': True, 'status': str(rec.get('status') or ''), 'since': (rec.get('statusUpdatedAt') or 0) / 1000,
            'mode': mode, 'queued': queued(rec, rows[0]['ops'] if rows else ()), 'tasks': [{**{k: v for k, v in t.items() if k != 'out'},
                                     **({'tail': output_tail(t['out'])} if t.get('out') else {})} for t in run + done]}


# --- Stop and Force send ---------------------------------------------------------------------------------------

STOP_WAIT = 6.0  # s an interrupted session gets to come to rest
NEXT_WAIT = 2.0  # s it gets before the next interrupt: what was queued has gone in as its next turn by then
TRIES = 3


def _fail(out: str, code: int = 1) -> dict:
    return {'ok': False, 'code': code, 'out': out, 'argv': []}


_STOPPED: dict[str, float] = {}  # session -> when it last got a Ctrl+C
_STOP_LOCK = threading.Lock()
AGAIN = 3.0  # s until Stop sends another: its status may still say busy for a moment, and a second one closes it


def stop(session: str) -> dict:
    """The page's Stop: one Ctrl+C to `session` while it works, never to an idle one (twice in a row closes Claude
    Code). A session whose status is not known (the harness loop) gets Escape, which is harmless idle."""
    with _STOP_LOCK:
        st = status(session)
        if st == BUSY:
            if time.monotonic() - _STOPPED.get(session, -AGAIN) < AGAIN:
                return {'ok': True, 'code': 0, 'out': f'{session} is stopping', 'argv': []}
            _STOPPED[session] = time.monotonic()
            r = U.keys(session, key='C-c')
            return {**r, 'out': f'stopped {session}'} if r['ok'] else r
    if st:
        return _fail(f'{session} is not working, so there is nothing to stop')
    return U.interrupt(session)


def rest(session: str) -> str:
    """Interrupt `session` until it rests; '' once it does, else why not. Messages that were queued go in as its next
    turn at the first interrupt, so that turn is interrupted too: they are in the conversation, not lost."""
    for i in range(TRIES):
        if status(session) != BUSY:
            return ''
        r = U.keys(session, key='Escape')
        if not r['ok']:
            return r['out']
        end = time.monotonic() + (NEXT_WAIT if i < TRIES - 1 else STOP_WAIT)
        while time.monotonic() < end:
            time.sleep(0.1)
            if status(session) != BUSY:
                time.sleep(0.4)  # a queued message would have started by now
                if status(session) != BUSY:
                    return ''
                break
    return f'{session} did not stop, so the message was not sent'


def force_send(session: str, text: str, send, unsent: bool = False) -> dict:
    """Force send: interrupt `session` while it works, wait until it rests, then `send(session, text)` once; idle, it
    just sends. Interrupted before it had answered at all, Claude Code puts that prompt back in its input: the new
    message goes on a line of its own below it, so both reach it, once (a command goes first, and the prompt stays in the input)."""
    busy = status(session) == BUSY
    if not busy and not unsent:
        return send(session, text)
    if busy and (why := rest(session)):
        return _fail(why)
    # ctrl+j: a new line in Claude Code's input. A command must stand first, so before one ctrl+s sets the prompt that
    # was put back aside: it comes back once the command is sent
    U.keys(session, text='\x13' if text[:1] in '!/' else '\n')
    time.sleep(0.2)
    return send(session, text)


_FORCE_LOCKS: dict[str, threading.Lock] = {}  # session -> one force at a time, so a second press never interrupts twice


def put_back(name: str, since: float) -> bool:
    """F190b: whether an interrupt at `since` (epoch s) left words in session `name`'s input: the last thing said is a
    prompt with no answer and no word that it was interrupted, or the queue was popped there."""
    from agent_runner.control import _stamp
    path = transcript(name, record(name))
    rows = list(U.tail_rows(path)) if path else []
    ops = [d for d in rows if d.get('type') == 'queue-operation' and (_stamp(d) or 0) >= since]
    said = U.feed_entries(rows)
    return bool(ops) and ops[-1].get('operation') == 'popAll' or bool(said) and said[-1]['kind'] == 'you'


def force_queued(session: str, unsent: bool = False) -> dict:
    """F190b: Force send of what is queued in `session`: one Escape, at which Claude Code takes the queued messages in
    as its next turn; no text is typed. Nothing queued, or not working: nothing is done.
    With messages queued, an interrupted prompt that had no answer yet stays in the conversation. Only when the last
    of the queue went in just before the Escape is that prompt back in the input (or, queue and all, popped there):
    Enter sends it from there, once: never into a question, nor with `unsent` (words were in its input before)."""
    with _FORCE_LOCKS.setdefault(session, threading.Lock()):
        busy = status(session) == BUSY
        n = queued_now(session) if busy else 0
        if not n:
            why = f'nothing is queued in {session}' if busy else f'{session} is not working, so nothing was forced'
            return {'ok': True, 'code': 0, 'out': why, 'argv': []}
        at = int(time.time() * 1000) / 1000  # ms, as the transcript's stamps are
        r = U.keys(session, key='Escape')
        if not r['ok']:
            return r
        end = time.monotonic() + STOP_WAIT
        while time.monotonic() < end:
            time.sleep(0.2)
            if status(session) != BUSY:
                time.sleep(0.4)  # a queued message would have started by now
                if (st := status(session)) != BUSY:
                    if not unsent and st in ('idle', 'shell') and put_back(session, at):
                        r = U.keys(session, key='Enter')
                        if not r['ok']:
                            return r
                    break
            elif queued_now(session) < n:
                time.sleep(0.4)
                if status(session) == BUSY:
                    break
        else:
            return _fail(f'{session} did not stop, so its queued messages are still queued')
        return {'ok': True, 'code': 0, 'out': f'sent the queued messages to {session}', 'argv': []}


# --- its commands ----------------------------------------------------------------------------------------------

_SKILLS: dict[str, tuple[int, dict[str, str]]] = {}  # transcript -> (how far it was read, name -> description)


def skills(path: str) -> dict[str, str]:
    """The skills session transcript `path` lists (its skill_listing entries, plugin and bundled ones too): name ->
    description. Each call reads only what was added since the last."""
    at, got = _SKILLS.get(path, (0, {}))
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            if f.tell() < at:
                at, got = 0, {}
            f.seek(at)
            while (line := f.readline()).endswith(b'\n'):
                at += len(line)
                if b'"skill_listing"' not in line:
                    continue
                try:
                    a = json.loads(line).get('attachment') or {}
                except (ValueError, AttributeError):
                    continue
                if a.get('type') != 'skill_listing':
                    continue
                said = dict(re.findall(r'^- ([\w:.-]+): (.*)$', str(a.get('content') or ''), re.M))
                for n in a.get('names') or said:
                    got[str(n)] = said.get(n, got.get(n, ''))[:120]
    except OSError:
        return got
    _SKILLS[path] = (at, got)
    return got


def session_skills(name: str) -> dict[str, str]:
    """`skills` of session `name`'s transcript; {} for none."""
    if not re.fullmatch(r'[cs]\d+', name):
        return {}
    path = transcript(name, record(name))
    return skills(path) if path else {}


# --- Claude Code's update --------------------------------------------------------------------------------------

UPDATES = re.compile(  # the commands Claude Code's own notice names; nothing else is run
    r'claude update|mise upgrade claude(-code)?|brew upgrade (--cask )?claude-code(@latest)?|'
    r'npm (i|install|update) -g @anthropic-ai/claude-code(@latest)?|bun add -g @anthropic-ai/claude-code(@latest)?|'
    r'pnpm (add|update) -g @anthropic-ai/claude-code(@latest)?|winget upgrade Anthropic\.ClaudeCode|apk upgrade claude-code')
UPDATE_WAIT = 600


def claude_update(cmd: str) -> dict:
    """Run the update command Claude Code's notice shows (`UPDATES`), on this machine."""
    cmd = ' '.join(str(cmd or '').split())
    if not UPDATES.fullmatch(cmd):
        return _fail(f'not an update command of Claude Code\'s: {cmd!r}', 2)
    argv = shlex.split(cmd)
    try:
        r = sp.run([plat.exe(argv[0]), *argv[1:]], capture_output=True, text=True, encoding='utf-8', errors='replace',
                   stdin=sp.DEVNULL, timeout=UPDATE_WAIT, cwd=str(Path.home()))
    except (OSError, sp.SubprocessError) as e:
        return _fail(f'{cmd}: {e}')
    said = (r.stdout + r.stderr).strip().splitlines()
    if r.returncode:
        return {'ok': False, 'code': r.returncode, 'out': f'{cmd}: {said[-1] if said else f"exit {r.returncode}"}', 'argv': argv}
    return {'ok': True, 'code': 0, 'out': 'Claude Code is updated. A chat moves to it when it restarts.', 'argv': argv}


def restart_chat(chat: str) -> dict:
    """Restart an idle chat: its Claude Code ends and its conversation comes up again under its number, with
    the version and look there are now."""
    from agent_runner import control as K, control_reopen
    m = re.fullmatch(r'c(\d+)', str(chat))
    if not m:
        return _fail(f'restart_chat: a chat, not {chat!r}', 2)
    n, rec = int(m[1]), record(chat)
    if rec.get('status') != 'idle':
        return _fail(f'{chat} has work going on: restart it once it is done')
    sid = str(rec.get('sessionId') or '') or K.control_kept_sid(n)
    if not sid or not K.transcript(sid):
        return _fail(f'{chat} has nothing said in it to restart with')
    if bad := K.agent_held():  # B764c: ended now, it could not come up again
        return _fail(f'{chat} was not restarted: {bad}')
    K.control_keep_sid(n, sid)
    plat.terminate(int(rec['pid']))
    end = time.monotonic() + 15
    while time.monotonic() < end and (plat.alive(int(rec['pid'])) or U.hidden_inbox(chat)):
        time.sleep(0.1)  # its shim takes its files away last: never the new session's
    time.sleep(0.3)
    where = control_reopen.reopen_control(n, sid)
    return {'ok': bool(where), 'code': 0 if where else 1, 'argv': [], 'name': chat,
            'out': f'{chat} is restarting' if where else f'{chat} could not be restarted (the run log says why)'}


U.ACTIONS.update({'stop_session': stop, 'claude_update': claude_update, 'restart_chat': restart_chat})
