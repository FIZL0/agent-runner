"""C26: the run view, `agent-runner attach` with no name (or `attach run`): the run's log, followed live as
the run's own terminal shows it, and the runner keys typed here (s, s!, p, f, +, -, slots N, z, x, u, ?, and
an empty line for Remote Control). Each key goes to the run through `loop.send_key` (the KEYS file the run
already reads), so the view works from any terminal and over ssh. Ctrl-C leaves the view; the run keeps going.
"""
from __future__ import annotations

import queue
import re
import sys
import threading
import time

from agent_runner.config import shown_cmd
from agent_runner.state import C, run_up

VIEW_TAIL = 40  # lines of run.log shown as the view opens
REMOTE_KEY = 'remote'  # what an empty line posts: the run opens Remote Control, as Enter in its terminal does
TOGGLES = ('s', 's!', 'p', 'f', '+', '-', 'z', 'x', 'u')


def view_key(line: str) -> str | None:
    """The key a line typed in the run view posts to the run; '?' is answered by the view itself, and None is a
    line that is no runner key."""
    k = ' '.join(line.strip().lower().split())
    if not k:
        return REMOTE_KEY
    if k in TOGGLES or k in ('?', 'h', 'help'):
        return '?' if k in ('h', 'help') else k
    if re.fullmatch(r'slots [+-]?\d+', k) or re.fullmatch(r'[spfzx] (?:on|off)', k):
        return k  # `p on`, `s off`: one way only, as `take_keys` reads them
    return None


def _read_lines(stdin, q: queue.Queue) -> None:
    for line in stdin:
        q.put(line)
    q.put(None)  # end of input: the view keeps following the log until Ctrl-C


def run_view(stdin=None, out=None, poll: float = 0.5, until: float | None = None, check_up: bool = True) -> int:
    """Show the end of run.log, then follow it and take typed keys until Ctrl-C (or `until`, a monotonic
    deadline, for tests). 1 when no run is up in this repository."""
    from agent_runner.loop import keys_help, send_key
    stdin = sys.stdin if stdin is None else stdin
    out = sys.stdout if out is None else out
    if check_up and not run_up():
        print(f'no run is up in this repository: {shown_cmd()} starts one; {shown_cmd()} status shows the last',
              file=sys.stderr)
        return 1
    logf = C.notes('run.log')

    def say(text: str) -> None:
        out.write(text if text.endswith('\n') else text + '\n')
        out.flush()

    say(keys_help(view=True))
    try:
        text = logf.read_text(encoding='utf-8', errors='replace')
    except OSError:
        text = ''
    pos = len(text.encode('utf-8'))
    for l in text.splitlines()[-VIEW_TAIL:]:
        say(l)
    q: queue.Queue = queue.Queue()
    threading.Thread(target=_read_lines, args=(stdin, q), daemon=True).start()
    try:
        while until is None or time.monotonic() < until:
            try:
                with open(logf, 'rb') as f:
                    f.seek(0, 2)
                    size = f.tell()
                    if size < pos:  # a new log (rotated or cleared): from its start
                        pos = 0
                    f.seek(pos)
                    new = f.read()
                    pos += len(new)
            except OSError:
                new = b''
            if new:
                out.write(new.decode('utf-8', 'replace'))
                out.flush()
            while True:
                try:
                    line = q.get_nowait()
                except queue.Empty:
                    break
                if line is None:
                    continue
                k = view_key(line)
                if k == '?':
                    say(keys_help(view=True))
                elif k is None:
                    say(f'unknown key {line.strip()!r}: ? lists the runner keys')
                else:
                    send_key(k)
                    say(f'sent to the run: {"Enter (Remote Control)" if k == REMOTE_KEY else k}')
            time.sleep(poll)
    except KeyboardInterrupt:
        say('\nleft the run view; the run keeps going')
    return 0
