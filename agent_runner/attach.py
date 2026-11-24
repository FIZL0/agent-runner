"""F88: attach to a hidden session's terminal through its shim's socket, as dtach does.

The shim (`slots.run_pty`, `slots.run_conpty`) listens on <notes>/slotN.sock (controlN.sock), removed when the
session ends: a Unix socket, mode 0600; on Windows a small file that holds a port on 127.0.0.1 and a token, which a
client sends first (a frame of kind b'k'), or is dropped after TOKEN_WAIT s. It sends what the session prints to every
attached client as is; a client sends frames: one kind byte, a 2-byte big-endian length, the payload. Kind b'd' is input for the session, b'w' that
client's terminal size (2-byte rows, 2-byte columns): the session gets the smallest of its clients' (`Viewers`, F114).
`attach_session` is the client `attach sN|cN` runs: Ctrl-b d detaches.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import subprocess as sp
import sys
import threading
import time
from pathlib import Path

from agent_runner import plat, state  # state.C read when called: init sets it after import

DETACH_KEY = 'Ctrl-b d'  # as tmux had it
DETACH_PREFIX = 0x02     # Ctrl-b; then 'd' detaches, Ctrl-b again sends one Ctrl-b
TERM_RESET = b'\x1b[0m\x1b[?25h\x1b[?2004l\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?1049l'


def attach_frame(kind: bytes, payload: bytes) -> bytes:
    import struct
    return kind + struct.pack('>H', len(payload)) + payload


def attach_size_frame(rows: int, cols: int) -> bytes:
    import struct
    return attach_frame(b'w', struct.pack('>HH', max(1, rows), max(1, cols)))


def attach_input_frames(data: bytes) -> bytes:
    return b''.join(attach_frame(b'd', data[i:i + 65535]) for i in range(0, len(data), 65535))


def attach_listen(path: Path):
    """The shim's listening socket at `path` (mode 0600, an old one replaced; Windows: a port on 127.0.0.1, named in
    the file `path` with the token a client must send); None when it cannot be made (a path too long for a Unix
    socket, say): the session runs, it just cannot be attached."""
    if plat.WINDOWS:
        return listen_tcp(path)
    import socket
    try:
        path.unlink(missing_ok=True)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except (OSError, AttributeError):
        return None
    old = os.umask(0o177)
    try:
        s.bind(str(path))
        s.listen(8)
        s.setblocking(False)
        return s
    except OSError:
        s.close()
        return None
    finally:
        os.umask(old)


TOKENS: dict[int, str] = {}  # F114: a TCP listener's port -> the token its clients send first (in its own shim)

TOKEN_WAIT = 5.0  # F146: s a client has to send it


def listen_tcp(path: Path):
    """F114: the Windows listener: a free port on 127.0.0.1, written to `path` with its token (owner-only)."""
    import socket
    try:
        s = socket.create_server(('127.0.0.1', 0))
    except OSError:
        return None
    try:
        s.setblocking(False)
        port, token = s.getsockname()[1], secrets.token_urlsafe(24)
        path.unlink(missing_ok=True)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as f:
            if os.name == 'nt':  # the mode means nothing there: this user alone, before the token is in it
                from agent_runner.conpty import _kernel32, _user_sid
                who = '*' + _user_sid(_kernel32())
                sp.run(['icacls', str(path), '/inheritance:r', '/grant:r', f'{who}:F'], check=True, timeout=20,
                       stdout=sp.DEVNULL, stderr=sp.DEVNULL, creationflags=plat.CREATE_NO_WINDOW)
            json.dump({'port': port, 'token': token}, f)
    except (OSError, sp.SubprocessError):
        s.close()
        path.unlink(missing_ok=True)
        return None
    TOKENS[port] = token
    return s


def connect(sock: Path):
    """F114: a connection to the session whose shim listens at `sock` (its token sent, where it wants one). OSError
    when it takes none (it ended, or its shim was killed)."""
    import socket
    if not plat.WINDOWS:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(str(sock))
        except OSError:
            s.close()
            raise
        return s
    try:
        d = json.loads(sock.read_text(encoding='utf-8'))
        port, token = int(d['port']), str(d['token'])
    except (ValueError, KeyError, TypeError) as e:
        raise OSError(f'{sock.name} names no port') from e
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.settimeout(None)
    s.sendall(attach_frame(b'k', token.encode()))
    return s


def reachable(sock: Path) -> bool:
    """F114: does the session's shim take a connection at `sock`? (A killed shim leaves the file behind.)"""
    try:
        connect(sock).close()
        return True
    except OSError:
        return False


SIZE_MIN = (5, 20)  # a terminal smaller than this (a frame being folded away) sets no size
REDRAW = 0.4 if plat.WINDOWS else 0.08  # s the session is a row short, so it draws its whole screen again (a
# pseudo-console loses the second of two sizes that come close together)


class Viewers:
    """F114: the terminals attached to one session: what it prints goes to all of them (`out`), what they type to it
    (`write`), and it gets the smallest of their sizes (`resize`), so none of them gets lines wider than it is or
    rows it has no place for; with the last one gone, `size` again. A terminal that just came, when its own size
    changes nothing, has the session a row short for a moment, which draws the whole screen again. `lock` is for the
    Windows shim, whose output comes on a thread of its own."""

    def __init__(self, path: Path, write, resize, size: tuple[int, int]):
        self.path, self.write, self.resize, self.default, self.now = path, write, resize, size, size
        self.listener = attach_listen(path)
        self.token = TOKENS.get(self.listener.getsockname()[1], '') if self.listener and plat.WINDOWS else ''
        self.clients: dict = {}  # socket -> the bytes of a frame not yet whole
        self.sizes: dict = {}  # socket -> (rows, columns)
        self.due = 0.0  # when the size comes back after a redraw
        self.lock, self.ended = threading.RLock(), False
        self.waits: dict = {}  # F146: socket -> when it is dropped, its token not come
        self.asked: set = set()  # sockets whose token came (no token: every one)

    def watched(self) -> list:
        return ([self.listener] if self.listener else []) + list(self.clients)

    def wait(self, most: float) -> float:
        return min(most, max(0.0, self.due - time.monotonic())) if self.due else most

    def tick(self) -> None:
        for c in [c for c, end in self.waits.items() if time.monotonic() >= end]:
            self.drop(c)
        if self.due and time.monotonic() >= self.due:
            self.due = 0.0
            self._set(self.now)

    def out(self, data: bytes) -> None:
        with self.lock:
            for c in list(self.clients):
                if self.token and c not in self.asked:
                    continue
                try:
                    c.sendall(data)
                except OSError:  # gone, or too slow to take it: that client is dropped, not the session
                    self.drop(c)

    def take(self, ready: list) -> None:
        """Accept and read what `select` says is there."""
        with self.lock:
            if self.listener and self.listener in ready:
                try:
                    c, _ = self.listener.accept()
                    c.settimeout(0.5)  # a client that takes no output for this long is dropped, once
                    self.clients[c] = b''
                    if self.token:
                        self.waits[c] = time.monotonic() + TOKEN_WAIT
                except OSError:
                    pass
            for c in [c for c in ready if c in self.clients]:
                try:
                    got = c.recv(65536)
                except OSError:
                    got = b''
                if not got:
                    self.drop(c)
                    continue
                buf = self.clients[c] + got
                while len(buf) >= 3 and len(buf) >= 3 + (n := int.from_bytes(buf[1:3], 'big')):
                    kind, payload, buf = buf[:1], buf[3:3 + n], buf[3 + n:]
                    if not self.frame(c, kind, payload):
                        break
                if c in self.clients:
                    self.clients[c] = buf

    def frame(self, c, kind: bytes, payload: bytes) -> bool:
        """Act on one frame of client `c`; False when it was sent away. An unknown kind is skipped."""
        if self.token and c not in self.asked:
            if kind != b'k' or not hmac.compare_digest(payload, self.token.encode()):
                self.drop(c)
                return False
            self.asked.add(c)
            self.waits.pop(c, None)
            return True
        if kind == b'd':
            self.write(payload)
        elif kind == b'w' and len(payload) == 4:
            size = int.from_bytes(payload[:2], 'big'), int.from_bytes(payload[2:], 'big')
            if size[0] >= SIZE_MIN[0] and size[1] >= SIZE_MIN[1]:
                new = c not in self.sizes
                self.sizes[c] = size
                self.fit(redraw=new)
        return True

    def fit(self, redraw: bool = False) -> None:
        want = (min(r for r, _ in self.sizes.values()), min(c for _, c in self.sizes.values())) \
            if self.sizes else self.default
        if want != self.now:
            self.now, self.due = want, 0.0
            self._set(want)
        elif redraw:
            self._set((want[0] - 1, want[1]))
            self.due = time.monotonic() + REDRAW

    def _set(self, size: tuple[int, int]) -> None:
        if self.ended:  # what it resized may be gone
            return
        try:
            self.resize(*size)
        except OSError:
            pass

    def drop(self, c) -> None:
        if c in self.clients:
            self.clients.pop(c)
            self.asked.discard(c)
            self.waits.pop(c, None)
            c.close()
            if self.sizes.pop(c, None):
                self.fit()

    def serve(self) -> None:
        """The Windows shim's thread: accept and read until `close`."""
        import select
        while not self.ended and self.listener:
            try:
                r, _, _ = select.select(self.watched(), [], [], self.wait(0.5))
            except (OSError, ValueError):  # a client `out` dropped meanwhile
                continue
            self.take(r)
            with self.lock:
                self.tick()

    def close(self) -> None:
        with self.lock:
            self.stop()
            for c in self.clients:
                c.close()
            self.clients, self.sizes, self.waits = {}, {}, {}

    def stop(self) -> None:
        """F146: take no one new, no input and no size; who is here still gets what the session prints last."""
        with self.lock:
            self.ended = True
            if self.listener:
                self.listener.close()
                self.listener = None
                self.path.unlink(missing_ok=True)


def pty_resize(fd: int):
    """F114: what sets the size of the pty `fd` (`Viewers`' resize)."""
    def resize(rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    return resize


def pty_write(fd: int):
    def write(data: bytes) -> None:
        try:
            os.write(fd, data)
        except OSError:
            pass
    return write


def session_socket(name: str) -> Path | None:
    """F88: the attach socket of hidden session `name` (sN, cN), when its shim is up; else None."""
    m = re.fullmatch(r'([cs])(\d+)', name)
    if not m:
        return None
    try:
        sock = state.C.notes(f'{"control" if m[1] == "c" else "slot"}{m[2]}.sock')
        return sock if sock.exists() else None
    except (AttributeError, OSError):  # no repo set up: no notes, so no socket
        return None


class Typed:
    """What an attached terminal types: the bytes to send on, and whether Ctrl-b d was pressed."""

    def __init__(self):
        self.prefix, self.keys = False, not os.environ.get('AGENT_RUNNER_WEB')

    def feed(self, data: bytes) -> tuple[bytes, bool]:
        if not self.keys:
            return data, False
        send = bytearray()
        for b in data:
            if self.prefix:
                self.prefix = False
                if b == ord('d'):
                    return bytes(send), True
                send += bytes([DETACH_PREFIX]) if b == DETACH_PREFIX else bytes([DETACH_PREFIX, b])
            elif b == DETACH_PREFIX:
                self.prefix = True
            else:
                send.append(b)
        return bytes(send), False


def attach_session(sock: Path, name: str, stdin: int = 0, stdout: int = 1) -> int:
    """F88 `attach sN|cN` for a hidden session: this terminal on the session's own terminal, through its
    shim's socket, until Ctrl-b d (the session keeps running) or the session ends. The terminal is raw while
    attached and put back after; its size goes to the session on connect (nudged a row smaller, then right,
    so Claude Code draws the whole screen again) and on every resize. 1 when the socket takes no connection.
    F114: with AGENT_RUNNER_WEB set (the run page's ttyd) there is no detach key, so Ctrl-b is the session's too."""
    try:
        s = connect(sock)
    except OSError as e:
        print(f'{name}: could not attach ({e})', file=sys.stderr)
        return 1
    if plat.WINDOWS:
        from agent_runner.attach_windows import attach_console
        return attach_console(s, name)
    import select
    import signal
    import termios
    import tty
    typed = Typed()

    def size() -> tuple[int, int] | None:
        try:
            cols, rows = os.get_terminal_size(stdout)
            return rows, cols
        except OSError:
            return None

    def send_size(nudge: bool = False) -> None:
        if not (sz := size()):
            return
        try:
            if nudge:
                s.sendall(attach_size_frame(sz[0] - 1, sz[1]))
                time.sleep(0.05)
            s.sendall(attach_size_frame(*sz))
        except OSError:
            pass

    saved = termios.tcgetattr(stdin) if os.isatty(stdin) else None
    main = threading.current_thread() is threading.main_thread()
    resized = [False]  # set by SIGWINCH, sent from the loop (never mid-frame from the handler)
    old = signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True)) if main else None
    why = f'detached from {name} ({name} keeps running)'
    try:
        if saved:
            tty.setraw(stdin)
        send_size(nudge=True)
        while True:
            r, _, _ = select.select([stdin, s], [], [], 0.2)
            if resized[0]:
                resized[0] = False
                send_size()
            if s in r:
                data = s.recv(65536)
                if not data:
                    why = f'{name} ended'
                    break
                os.write(stdout, data)
            if stdin in r:
                data = os.read(stdin, 4096)
                if not data:
                    why = f'input ended: detached from {name} ({name} keeps running)'
                    break
                send, detach = typed.feed(data)
                if send:
                    s.sendall(attach_input_frames(send))
                if detach:
                    break
    except OSError:
        why = f'{name}: the connection to its terminal broke'
    finally:
        s.close()
        if main:
            signal.signal(signal.SIGWINCH, signal.SIG_DFL if old is None else old)
        if saved:
            termios.tcsetattr(stdin, termios.TCSADRAIN, saved)
        if os.isatty(stdout):
            os.write(stdout, TERM_RESET)
        os.write(stdout, f'\r\n[{why}]\r\n'.encode())
    return 0
