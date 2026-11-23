"""F106b: the stream engine (`[run] engine = "stream"`): a slot's Claude Code session run headless, `claude -p
--input-format stream-json --output-format stream-json`, by its shim (`run_stream`); what a person or the run sends
it becomes its next user message (`StreamInput`). `slots` builds its command line and job."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess as sp
import time
from pathlib import Path

from agent_runner import plat
from agent_runner.attach import attach_listen

STREAM_GRACE = 5.0  # s after a result event, with a message sent during that turn, for the next turn to start
PASTE_ON, PASTE_OFF = b'\x1b[200~', b'\x1b[201~'


def stream_message(text: str) -> bytes:
    """One stream-json user message, the line a headless session reads on its stdin."""
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': text}]}},
                      ensure_ascii=False).encode('utf-8') + b'\n'


class StreamInput:
    """F106b: what arrives for a headless session (on its FIFO, or from an attached terminal) as stream-json
    lines: a JSON line (`HiddenMux.send`) passes as it is; typed text (a bracketed paste, keys) becomes a user
    message at its Enter, so `send_fifo` and the run page's typing reach it too. Other keys are dropped."""

    def __init__(self):
        self.buf, self.text, self.paste = b'', b'', False

    def feed(self, data: bytes) -> list[bytes]:
        self.buf += data
        out = []
        while self.buf:
            b = self.buf
            if not self.paste and not self.text and b[:1] == b'{':
                if (j := b.find(b'\n')) < 0:
                    break
                line, self.buf = b[:j].strip(), b[j + 1:]
                try:
                    json.loads(line)
                    out.append(line + b'\n')
                except ValueError:
                    self.text = line  # not a message after all: typed text, sent at the Enter it ended with
                    out += self._enter()
                continue
            if b[:1] == b'\x1b':
                for mark, on in ((PASTE_ON, True), (PASTE_OFF, False)):
                    if b.startswith(mark):
                        self.paste, self.buf = on, b[len(mark):]
                        break
                else:
                    if PASTE_ON.startswith(b) or PASTE_OFF.startswith(b):
                        break  # the rest of the mark is still to come
                    self.buf = b[1:]  # a key such as Escape, which stream-json has no message for
                continue
            if not self.paste and b[:1] in (b'\r', b'\n'):
                self.buf = b[1:]
                out += self._enter()
                continue
            m = re.search(rb'\x1b' if self.paste else rb'[\x1b\r\n]', b)
            k = m.start() if m else len(b)
            self.text, self.buf = self.text + b[:k], b[k:]
        return out

    def _enter(self) -> list[bytes]:
        text, self.text = self.text.decode('utf-8', errors='replace'), b''
        return [stream_message(text)] if text.strip() else []


def attach_frames(buf: bytes) -> tuple[list[tuple[bytes, bytes]], bytes]:
    """The whole frames an attached terminal sent (`attach.attach_take`'s format: kind, length, payload) and what
    is left of one not yet whole."""
    import struct
    frames = []
    while len(buf) >= 3:
        n = struct.unpack('>H', buf[1:3])[0]
        if len(buf) < 3 + n:
            break
        frames.append((buf[:1], buf[3:3 + n]))
        buf = buf[3 + n:]
    return frames, buf


def run_stream(argv: list[str], cwd: str, env: dict, marker: Path, logfile: Path | None, brief: str,
               events: Path | None) -> tuple[int, int]:
    """F106b: run one headless session (`claude -p --input-format stream-json --output-format stream-json`), its
    pid in `marker` while it runs. `brief` is its first user message; what arrives on the FIFO beside the marker
    (slotN.in) or from a terminal attached on its socket (slotN.sock) is its next (`StreamInput`). Its event
    stream goes to `logfile` (the slot log), to `events` (its spend is read there) and to attached terminals.
    The session ends at a result event: its stdin is closed, at once when nothing was sent during that turn,
    else when no next turn starts within STREAM_GRACE s; held while a background command runs (`due`). No
    ANTHROPIC_API_KEY reaches it, so it runs on the claude.ai login: plan usage. Returns its exit code and pid. OSError when it cannot be started."""
    exe = shutil.which(argv[0], path=env.get('PATH') or os.environ.get('PATH'))
    if not exe:
        raise FileNotFoundError(f'{argv[0]} is not on PATH')
    full = {k: v for k, v in {**os.environ, **env, 'AGENT_RUNNER_MARKER': str(marker)}.items()
            if k != 'ANTHROPIC_API_KEY'}
    out = open(logfile, 'ab') if logfile else None
    ev = open(events, 'ab') if events else None
    proc = sp.Popen([exe, *argv[1:]], cwd=cwd, env=full, stdin=sp.PIPE, stdout=sp.PIPE,
                    stderr=out or sp.DEVNULL, bufsize=0)
    marker.write_text(str(proc.pid), encoding='utf-8')
    inbox, sockpath = marker.with_suffix('.in'), marker.with_suffix('.sock')
    inq, listener, clients = -1, None, {}  # clients: socket -> (bytes of a frame not yet whole, its StreamInput)
    st = {'open': True, 'sent': False, 'grace': 0.0, 'hold': 0.0, 'line': b''}

    def close_input() -> None:
        nonlocal inq
        if st['open']:
            st['open'] = False
            try:
                proc.stdin.close()
            except OSError:
                pass
        if inq >= 0:  # a tell from now on is refused, not lost
            os.close(inq)
            inq = -1
            inbox.unlink(missing_ok=True)

    def write_in(lines: list[bytes]) -> None:
        for line in lines:
            if not st['open']:
                return
            try:
                proc.stdin.write(line)
                proc.stdin.flush()
            except OSError:
                close_input()
                return
            st['sent'], st['grace'] = True, 0.0

    def took(data: bytes) -> None:
        for f in (out, ev):
            if f:
                f.write(data)
                f.flush()
        for c in list(clients):
            try:
                c.sendall(data)
            except OSError:
                clients.pop(c)
                c.close()
        st['line'] += data
        *whole, st['line'] = st['line'].split(b'\n')
        for raw in whole:
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if e.get('type') == 'result':  # a message came during this turn: give its turn the time to start
                now = time.monotonic()
                st['grace'] = now + (STREAM_GRACE if st['sent'] else 0.0)
                st['sent'], st['hold'] = False, now + int(os.environ.get('AGENT_RUNNER_IDLE_MAX', 10800))
            elif st['grace']:
                st['grace'] = 0.0  # the next turn started

    def due() -> None:
        """Close stdin once the grace after a result is over, unless the agent still runs a background command
        (a `done` waiting on the gate), whose end starts its next turn: as the Stop hook's waiter does, it is
        held until then, up to AGENT_RUNNER_IDLE_MAX s, and no longer once `run finish` / `ask` or `done` ran."""
        if not st['grace'] or time.monotonic() <= st['grace']:
            return
        marks = (marker.with_suffix('.end'), marker.with_suffix('.finished'))
        if not any(m.exists() for m in marks) and plat.children(proc.pid) and time.monotonic() < st['hold']:
            st['grace'] = time.monotonic() + 2.0
            return
        close_input()

    write_in([stream_message(brief)])
    st['sent'] = False  # the brief is this turn's own message
    try:
        if plat.WINDOWS:  # no FIFO or socket there: the brief, then the stream until the result
            import queue
            import threading
            got: queue.Queue = queue.Queue()

            def pump() -> None:
                while data := proc.stdout.read(65536):
                    got.put(data)
                got.put(b'')
            threading.Thread(target=pump, daemon=True).start()
            while True:
                try:
                    data = got.get(timeout=0.5)
                except queue.Empty:
                    data = None
                if data == b'':
                    break
                if data:
                    took(data)
                due()
        else:
            import select
            inbox.unlink(missing_ok=True)
            try:
                os.mkfifo(inbox, 0o600)
                inq = os.open(inbox, os.O_RDWR | os.O_NONBLOCK)
            except OSError:
                inq = -1
            listener = attach_listen(sockpath)
            fifo_in, fd = StreamInput(), proc.stdout.fileno()
            while True:
                watch = [fd] + ([inq] if inq >= 0 else []) + ([listener] if listener else []) + list(clients)
                r, _, _ = select.select(watch, [], [], 0.5)
                if fd in r:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        data = b''
                    if not data:
                        break
                    took(data)
                if listener and listener in r:
                    try:
                        c, _ = listener.accept()
                        c.settimeout(0.5)
                        clients[c] = (b'', StreamInput())
                    except OSError:
                        pass
                for c in [c for c in r if c in clients]:
                    try:
                        got = c.recv(65536)
                    except OSError:
                        got = b''
                    if not got:
                        clients.pop(c)
                        c.close()
                        continue
                    frames, rest = attach_frames(clients[c][0] + got)
                    clients[c] = (rest, clients[c][1])
                    for kind, payload in frames:
                        if kind == b'd':
                            write_in(clients[c][1].feed(payload))
                if inq >= 0 and inq in r:
                    try:
                        write_in(fifo_in.feed(os.read(inq, 65536)))
                    except OSError:
                        pass
                due()
    finally:
        close_input()
        code = proc.wait()
        for f in (out, ev):
            if f:
                f.close()
        for c in clients:
            c.close()
        if listener:
            listener.close()
            sockpath.unlink(missing_ok=True)
        inbox.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
    return code, proc.pid
