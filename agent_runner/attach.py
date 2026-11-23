"""F88: attach to a hidden session's terminal through its shim's socket, as dtach does (POSIX).

The shim (`slots.run_pty`) listens on <notes>/slotN.sock (controlN.sock), mode 0600, removed when the session
ends. It sends what the session prints to every attached client as is; a client sends frames: one kind byte, a
2-byte big-endian length, the payload. Kind b'd' is input for the session, b'w' a terminal size (2-byte rows,
2-byte columns) set with TIOCSWINSZ. `attach_session` is the client `attach sN|cN` runs: Ctrl-b d detaches.
"""
from __future__ import annotations

import os
import re
import sys
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
    """The shim's listening socket at `path` (mode 0600, an old one replaced); None when it cannot be made
    (a path too long for a Unix socket, say): the session runs, it just cannot be attached."""
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


def attach_take(buf: bytes, fd: int) -> bytes:
    """The whole frames at the start of `buf` acted on against the pty `fd`; what is left of a frame not yet
    whole is returned. An unknown kind is skipped."""
    import fcntl
    import struct
    import termios
    while len(buf) >= 3:
        n = struct.unpack('>H', buf[1:3])[0]
        if len(buf) < 3 + n:
            break
        kind, payload, buf = buf[:1], buf[3:3 + n], buf[3 + n:]
        try:
            if kind == b'd':
                os.write(fd, payload)
            elif kind == b'w' and n == 4:
                rows, cols = struct.unpack('>HH', payload)
                fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
        except OSError:
            pass
    return buf


def session_socket(name: str) -> Path | None:
    """F88: the attach socket of hidden session `name` (sN, cN), when its shim is up; else None."""
    m = re.fullmatch(r'([cs])(\d+)', name)
    if not m or plat.WINDOWS:
        return None
    try:
        sock = state.C.notes(f'{"control" if m[1] == "c" else "slot"}{m[2]}.sock')
        return sock if sock.exists() else None
    except (AttributeError, OSError):  # no repo set up: no notes, so no socket
        return None


def attach_session(sock: Path, name: str, stdin: int = 0, stdout: int = 1) -> int:
    """F88 `attach sN|cN` for a hidden session: this terminal on the session's own terminal, through its
    shim's socket, until Ctrl-b d (the session keeps running) or the session ends. The terminal is raw while
    attached and put back after; its size goes to the session on connect (nudged a row smaller, then right,
    so Claude Code draws the whole screen again) and on every resize. 1 when the socket takes no connection."""
    import select
    import signal
    import socket
    import termios
    import threading
    import tty
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(sock))
    except OSError as e:
        s.close()
        print(f'{name}: could not attach ({e})', file=sys.stderr)
        return 1

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
        prefix = False
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
                send, detach = bytearray(), False
                for b in data:
                    if prefix:
                        prefix = False
                        if b == ord('d'):
                            detach = True
                            break
                        send += bytes([DETACH_PREFIX]) if b == DETACH_PREFIX else bytes([DETACH_PREFIX, b])
                    elif b == DETACH_PREFIX:
                        prefix = True
                    else:
                        send.append(b)
                if send:
                    s.sendall(attach_input_frames(bytes(send)))
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
