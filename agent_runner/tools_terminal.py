"""F466d: the Tools page's terminal, so a person on a phone can run a command on this machine without a terminal here.

It rides POST /tools (`devices.post`), so it opens only over https or loopback with the page token (`devices.channel`,
checked by web.py before any op runs); over plain http from another host it is refused like a secret.
A shell runs as the runner's OS user, in the project's main checkout or $HOME, as the person picks.

Agents cannot reach it: there is no CLI to attach, and no transcript: what is typed and shown lives only in this
process's memory (the last OUT_MAX bytes of output) and is never logged, so it never reaches run.log, a chat or a push.
A terminal closes when its page stops asking for output (the tab closed: GONE seconds), after IDLE seconds with
nothing typed, or with 'End every terminal'.
"""
from __future__ import annotations

import os
import secrets
import signal
import threading
import time
from pathlib import Path

from agent_runner.devices import Refused

IDLE = 15 * 60  # s with nothing typed
GONE = 45  # s with no page asking for its output: the tab is closed
OUT_MAX = 256 * 1024  # bytes of output kept, for the page to draw
IN_MAX = 4096  # bytes typed at once
MAX_OPEN = 4

_lock = threading.Lock()
_terms: dict[str, 'Term'] = {}
_sweeper: threading.Thread | None = None


class Term:
    def __init__(self, pid: int, fd: int, where: str):
        self.pid, self.fd, self.where = pid, fd, where
        self.out = bytearray()
        self.base = 0  # the offset of out[0] in everything the shell wrote
        self.typed = self.seen = time.monotonic()
        self.ended = False
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        while True:
            try:
                b = os.read(self.fd, 4096)
            except OSError:
                b = b''
            with _lock:
                if not b:
                    self.ended = True
                    return
                self.out += b
                if len(self.out) > OUT_MAX:
                    cut = len(self.out) - OUT_MAX
                    del self.out[:cut]
                    self.base += cut

    def close(self) -> None:
        for sig in (signal.SIGHUP, signal.SIGKILL):
            try:
                os.killpg(self.pid, sig)
            except OSError:
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.waitpid(self.pid, os.WNOHANG)
        except OSError:
            pass


def _folder(where: str, c) -> Path:
    if where == 'project':
        from agent_runner import config
        return config.main_checkout(c.root)
    return Path.home()


def _spawn(cwd: Path) -> tuple[int, int]:
    import pty
    shell = os.environ.get('SHELL') or '/bin/sh'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('AGENT_RUNNER', 'CLAUDE'))}
    env.update(TERM='dumb', PWD=str(cwd), HISTFILE='/dev/null')  # what is typed is kept nowhere
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - the child
        try:
            os.chdir(cwd)
            os.execve(shell, [shell, '-i'], env)
        finally:
            os._exit(127)
    return pid, fd


def sweep(now: float | None = None) -> list[str]:
    """Close the terminals idle too long, whose page is gone, or whose shell ended; their ids."""
    now = time.monotonic() if now is None else now
    with _lock:
        out = [i for i, t in _terms.items() if now - t.typed > IDLE or now - t.seen > GONE or
               (t.ended and now - t.seen > 5)]
        gone = [_terms.pop(i) for i in out]
    for t in gone:
        t.close()
    return out


def _sweeping() -> None:
    while True:
        time.sleep(10)
        sweep()


def _get(a: dict) -> Term:
    t = _terms.get(a.get('id') if isinstance(a.get('id'), str) else '')
    if not t:
        raise Refused('that terminal has ended')
    return t


def op_open(a: dict, c) -> dict:
    global _sweeper
    if os.name != 'posix':
        raise Refused('the terminal works on Linux and macOS only')
    sweep()
    where = 'project' if a.get('where') == 'project' else 'home'
    cwd = _folder(where, c)
    with _lock:
        if len(_terms) >= MAX_OPEN:
            raise Refused(f'{MAX_OPEN} terminals are open already: end one first')
    pid, fd = _spawn(cwd)
    tid = secrets.token_urlsafe(12)
    with _lock:
        _terms[tid] = Term(pid, fd, where)
        if _sweeper is None:
            _sweeper = threading.Thread(target=_sweeping, daemon=True)
            _sweeper.start()
    return {'out': f'a terminal is open in {cwd}', 'id': tid, 'cwd': str(cwd)}


def op_send(a: dict, c) -> dict:
    data = a.get('data') if isinstance(a.get('data'), str) else ''
    b = data.encode('utf-8')
    if len(b) > IN_MAX:
        raise Refused('that is too long to type at once')
    t = _get(a)
    t.typed = t.seen = time.monotonic()
    os.write(t.fd, b)
    return {'out': ''}


def op_read(a: dict, c) -> dict:
    """The output since `at`; `at` comes back as where the next read starts."""
    sweep()
    t = _get(a)
    at = a.get('at') if isinstance(a.get('at'), int) and a.get('at') >= 0 else 0
    with _lock:
        t.seen = time.monotonic()
        start = max(at, t.base)
        data = bytes(t.out[start - t.base:])
        end = t.base + len(t.out)
    return {'out': '', 'data': data.decode('utf-8', 'replace'), 'at': end, 'ended': t.ended,
            'idle': int(IDLE - (time.monotonic() - t.typed))}


def op_close(a: dict, c) -> dict:
    with _lock:
        t = _terms.pop(a.get('id') if isinstance(a.get('id'), str) else '', None)
    if t:
        t.close()
    return {'out': 'the terminal has ended'}


def op_close_all(a: dict, c) -> dict:
    with _lock:
        ts = list(_terms.values())
        _terms.clear()
    for t in ts:
        t.close()
    return {'out': f'{len(ts)} terminal{"" if len(ts) == 1 else "s"} ended'}


def count() -> int:
    with _lock:
        return len(_terms)


OPS = {'term_open': op_open, 'term_send': op_send, 'term_read': op_read, 'term_close': op_close,
       'term_close_all': op_close_all}
