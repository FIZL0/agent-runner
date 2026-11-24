"""Ending the runner feed an older version started (B195), opening a new control session (`control --new`), and a
one-shot on the harness loop (`harness_once`, F406e)."""

from __future__ import annotations

import json
import os
import re
import subprocess as sp
import sys
import time
import uuid
from pathlib import Path

from agent_runner import plat
from agent_runner.config import runner_cmd, shown_cmd
from agent_runner.state import C, log, ROOT, run_up
from agent_runner.slots import HARNESS, link_drift, on_harness, remote_answer_drift
from agent_runner.slots import marker_pid, remote_off_why, remote_on, REMOTE_URL
from agent_runner.control import (control_env, CONTROL_LINK_WAIT, control_live, control_name,
    claim_control_number, control_unclaim, hidden_control, hidden_control_log,
    person_message, rc_sweep, REMOTE_DIR, SESSION_LINK)


BOARD_WAIT = 10  # s an older version's board gets to end: by itself once its feed has, then on SIGTERM
BOARD_FILES = ('live', 'exit', 'job', 'log', 'shim', 'in', 'sock')  # <notes>/board.*: what it left


def board_up() -> int:
    """B195: the pid of an older version's board (`since --board`, named in <notes>/board.live) that still runs,
    else 0. Its command line must say so: after a reboot the pid can be anyone's, and where the OS does not show it
    (macOS) the board is left to end by itself, as it does once its feed has."""
    pid = marker_pid(C.notes('board.live'))
    return pid if pid and plat.alive(pid) and '--board' in (plat.cmdline(pid) or ()) else 0


def end_board() -> None:
    """B195: a run keeps no board and no runner feed. End the board an older version started (its feed was ended
    first, `rc_sweep`, so its entry in the apps is archived), and drop what they left in the notes."""
    end = time.monotonic() + BOARD_WAIT
    while board_up() and time.monotonic() < end:
        time.sleep(0.25)
    if pid := board_up():
        plat.terminate(pid)
        end = time.monotonic() + BOARD_WAIT
        while board_up() and time.monotonic() < end:
            time.sleep(0.25)
    feed_forget_session()
    if pid := board_up():
        log(f'board: an older version\'s (pid {pid}) did not end; left running, the next start ends it')
        return
    for f in (*(f'board.{x}' for x in BOARD_FILES), 'no-board'):
        try:
            C.notes(f).unlink(missing_ok=True)
        except OSError:
            pass


def board_held() -> bool:
    """`since --follow --keep-mark`: hold its lines (B13)? While the run is idle, or paused or stopping with nothing
    running or merging, nothing more lands until the run starts something or a task is added. No run up: nothing
    to hold for."""
    try:
        st = json.loads(C.notes('STATE').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return False
    if not isinstance(st, dict):
        return False
    held = bool(st.get('idle') or (st.get('paused') or st.get('stopping'))
                and not st.get('running') and not st.get('merging'))
    return held and run_up()  # STATE first: the lock is only probed when STATE would hold (a stale one, too)


FEED_SID = 'feed.sid'  # <notes>/remote/feed.sid: the session id an older version's runner feed kept
SID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def feed_sid_parts() -> tuple[str, str]:
    """(session id, runner command) as <notes>/remote/feed.sid holds them (B91); '' for either one missing."""
    try:
        lines = C.notes(REMOTE_DIR, FEED_SID).read_text(encoding='utf-8').splitlines()
    except OSError:
        return '', ''
    lines = [ln.strip() for ln in lines] + ['', '']
    return lines[0], lines[1]


def feed_forget_session() -> None:
    """B195: forget the session id an older version's runner feed kept."""
    C.notes(REMOTE_DIR, FEED_SID).unlink(missing_ok=True)


def feed_model() -> str:
    """F101: `[models] feed` (haiku by default): what publishes the run page's claude.ai copy (page_copy.py)."""
    return (C.raw.get('models') or {}).get('feed') or 'haiku'


def feed_on_harness() -> bool:
    """F406e: `[models] feed` is another provider's: its one-shot runs on the harness loop, which cannot publish to
    claude.ai."""
    return on_harness(feed_model())


def harness_once(model: str, prompt: str, cwd: Path, timeout: float, tools: str = 'read') -> tuple[str, str]:
    """F406e: one answer of a fresh harness loop session on `model`, given only `prompt` and `tools` (names, a comma
    between two): (its last words, why it failed). One of the two is ''. Never raises."""
    sid = str(uuid.uuid4())
    pf = C.notes(f'once-{sid}.prompt')
    env = {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER_SLOT', 'AGENT_RUNNER')}  # no slot's session
    try:
        pf.write_text(prompt, encoding='utf-8')
        argv = HARNESS.argv('', pf, sid, [*HARNESS.flags(sid, model, 0, False, True), '--tools', tools])
        r = sp.run(argv, cwd=str(cwd), env=env, stdin=sp.DEVNULL, capture_output=True, text=True, encoding='utf-8',
                   errors='replace', timeout=timeout)
        said = ''
        if r.returncode == 0 and (f := HARNESS.find_transcript(sid)):
            for line in Path(f).read_text(encoding='utf-8').splitlines():
                d = json.loads(line)
                if d.get('type') == 'assistant':
                    said = '\n'.join(b.get('text') or '' for b in d['message']['content'] if b.get('type') == 'text').strip()
    except (OSError, ValueError, sp.SubprocessError) as e:
        return '', f'the one-shot on {model} did not run: {e}'
    finally:
        pf.unlink(missing_ok=True)
    if said:
        return said, ''
    end = ' '.join(f'{r.stderr or ""} {r.stdout or ""}'.split())[-300:]
    return '', f'the one-shot on {model} gave no answer (exit {r.returncode}): {end}'


def feed_sid_file() -> str:
    """The session id <notes>/remote/feed.sid holds (its first line, B91), stripped; '' without one."""
    return feed_sid_parts()[0]


def claude_sessions_dir() -> Path:
    """Where Claude Code keeps one <pid>.json per live session, its sessionId among the fields."""
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'sessions'


def queued_message(d: dict) -> dict | None:
    """B106: a message the person sent while a session was busy (handling a Monitor event, a command), as Claude
    Code records it: no type=user entry but an attachment {type: queued_command, prompt: <text or content
    blocks, images too>, commandMode: prompt}. Given back in a type=user entry's shape, so readers take it like
    any other person message, in transcript order; None for any other entry, and for a queued task notification
    (commandMode task-notification) or one not from the person."""
    att = d.get('attachment') if isinstance(d, dict) else None
    if not isinstance(att, dict) or att.get('type') != 'queued_command':
        return None
    if att.get('commandMode', 'prompt') != 'prompt':
        return None
    prompt = att.get('prompt')
    if not isinstance(prompt, (str, list)):
        return None
    out = {'type': 'user', 'uuid': d.get('uuid') or att.get('source_uuid'),
           'timestamp': d.get('timestamp') or att.get('timestamp'), 'version': d.get('version'),
           'origin': att.get('origin') or d.get('origin') or {'kind': 'human'}, 'message': {'content': prompt}}
    return out if person_message(out) else None


def control_ask_file(n: int, text: str) -> Path:
    """Where `control --new` leaves the first message for `control N --ask-file` (read and removed there):
    a file, so the text never passes through a shell command line."""
    f = C.notes(f'control{n}.ask')
    f.write_text(text, encoding='utf-8')
    return f


def read_ask_file(path: str) -> str:
    """`control N --ask-file PATH`: the handed-on message, the file removed once read."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return ''
    try:
        Path(path).unlink()
    except OSError:
        pass
    return text


def control_new(n: int | None = None, wait: float = CONTROL_LINK_WAIT, ask: str = '',
                images: list[str] | tuple = ()) -> int:
    """`control --new`: another control session, opened without taking focus (a hidden terminal; Windows with no
    ConPTY: a hidden console), on Remote Control as "<repo> · control N" with `[run] remote`.
    Prints its claude.ai/code link once its log shows it, so the session that ran it can answer with a link.
    Its first message is `ask`, handed to `control N` in a file (`control_ask_file`), with `images` (files) named
    in it."""
    if not n:  # B131: claimed until it is up, so an ask that arrives meanwhile gets the next number
        n = claim_control_number()
        try:
            return control_new(n, wait, ask, images)
        finally:
            control_unclaim(n)
    if pid := control_live(n):
        print(f'control {n} already runs (pid {pid})', file=sys.stderr)
        return 1
    images = [str(Path(i).resolve()) for i in images]
    given = ['--ask-file', str(control_ask_file(n, ask))] if ask else []
    cmd = [*runner_cmd(), 'control', str(n), *given, *[x for i in images for x in ('--file', i)]]
    name = control_name(n, ask, images)
    if plat.WINDOWS and not plat.has_conpty():
        plat.spawn_console(cmd, ROOT, control_env(), hidden=True)
        print(f'control {n} is up in a hidden console' +
              (f': "{name}" at {REMOTE_URL}' if remote_on() else f' ({shown_cmd()} attach c{n} shows it)'))
        return 0
    return control_new_hidden(n, cmd, name, wait)


def control_new_hidden(n: int, cmd: list[str], name: str, wait: float = CONTROL_LINK_WAIT) -> int:
    """F59: `control --new`: control session `n` in a pseudo-terminal with no window
    (`hidden_control`; `attach cN` shows it). With `[run] remote` it prints its claude.ai/code link once its
    log shows it."""
    out = hidden_control_log(n)
    since = out.stat().st_size if out.exists() else 0
    pid, why = hidden_control(n, cmd)
    if not pid:
        print(f'control {n} could not start hidden: {why}', file=sys.stderr)
        return 1
    if why:  # B131: another `control --new` started control n a moment ago: its link is in its log already
        since = 0
        print(f'control {n} {why} (pid {pid}): this ask did not start another')
    where = f'a hidden terminal{"" if plat.WINDOWS else f" ({shown_cmd()} attach c{n} shows it)"}, its output in {out}'
    if wait < 0:  # F112 `control --new --no-wait` (-1): back at once; the link is read from state once it is up
        print(f'control {n} is starting in {where}')
        return 0
    if not remote_on():
        why = remote_off_why() if C.run['remote'] == 'auto' else ''
        print(f'control {n} is up in {where}; it is local' +
              (f' ({why})' if why else ': [run] remote = true puts control sessions on claude.ai/code'))
        return 0
    deadline = time.monotonic() + wait
    while True:
        try:
            with open(out, 'rb') as fh:
                fh.seek(since)
                shown = fh.read().decode('utf-8', 'replace')
        except OSError:
            shown = ''
        if m := SESSION_LINK.search(shown):
            print(f'control {n} is up: {m.group(0)}\n("{name}", in {where})')
            remote_answer_drift(f'control {n}')  # B45: it came up on Remote Control, so the answer is kept
            return 0
        if not plat.alive(pid) or time.monotonic() >= deadline:
            break
        time.sleep(1)
    if plat.alive(pid):  # B45: still running, Remote Control on, and no link in all that time
        link_drift(f'control {n}', wait)
    print(f'control {n} is up in {where}, but showed no link in {wait:g} s: find "{name}" at {REMOTE_URL}')
    return 0


def rc_sweep_stop() -> None:
    """The run's stop: end its control server (and an older version's feed, if one is left) now and wait for their
    teardown, so their entries are archived before the run exits (and before a suspend or power-off)."""
    feed_forget_session()
    rc_sweep(os.getpid(), stopping=True)
