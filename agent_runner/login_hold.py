"""F126b: the WebSocket of the Claude login's terminal (ttyd running watch.LOGIN_CMD), held on while no browser is.

ttyd ends its command when the browser goes, and a phone drops the page's socket while its person is on the sign-in
page in another tab; a new `claude auth login` would not take the code of the old one's link. So ttyd has one client,
this one: browsers come and go on it, each is sent all it printed so far, and it ends HOLD s after the last one left.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time

HOLD = 600.0  # s a login waits for its person to come back from the sign-in page
QUIET = 20.0  # s a browser may say nothing (it is pinged with ttyd's pings, every 5 s), or take nothing, before it is gone
ENDED = 4001  # the close code that says the login itself ended, not only the connection
BIGGEST = 1 << 20  # bytes of one frame
MAGIC = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'  # RFC 6455


def read_frame(f) -> tuple[int, bytes, bytes]:
    """One WebSocket frame from file `f`: its opcode, its bytes as they came, its payload unmasked. EOFError at the end."""
    def take(n: int) -> bytes:
        data = f.read(n)
        if data is None or len(data) < n:
            raise EOFError
        return data
    head = take(2)
    n, more = head[1] & 127, b''
    if n > 125:
        more = take(2 if n == 126 else 8)
        n = int.from_bytes(more, 'big')
    if n > BIGGEST:
        raise EOFError
    mask = take(4) if head[1] & 128 else b''
    body = take(n)
    plain = bytes(b ^ mask[i % 4] for i, b in enumerate(body)) if mask else body
    return head[0] & 15, head + more + mask + body, plain


def frame(opcode: int, body: bytes, mask: bool = False) -> bytes:
    """A short frame (a control frame: under 126 bytes), masked as a client's must be."""
    head = bytes([128 | opcode, len(body) | (128 if mask else 0)])
    return head + (bytes(4) if mask else b'') + body  # a mask of zeroes leaves the body as it is


class LoginHold:
    def __init__(self):
        self.lock = threading.RLock()
        self.up: socket.socket | None = None
        self.said: list[bytes] = []  # what ttyd sent, for a browser that comes back
        self.viewers: list = []  # the browsers' handlers
        self.left = 0.0  # when the last one went

    def live(self) -> bool:
        return self.up is not None

    def _start(self, port: int, target: str) -> None:
        up = socket.create_connection(('127.0.0.1', port), timeout=10)
        try:
            up.sendall((f'GET {target} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                        f'Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\nSec-WebSocket-Version: 13\r\n'
                        'Sec-WebSocket-Protocol: tty\r\n\r\n').encode('latin-1'))
            f = up.makefile('rb')
            first = f.readline(4096)
            while f.readline(4096) not in (b'\r\n', b'\n', b''):
                pass
            if b' 101 ' not in first:
                raise OSError('ttyd took no WebSocket')
            up.settimeout(None)
        except OSError:
            up.close()
            raise
        self.up, self.said = up, []
        threading.Thread(target=self._listen, args=(up, f), name='login-hold', daemon=True).start()

    def _listen(self, up: socket.socket, f) -> None:
        try:
            while True:
                op, raw, body = read_frame(f)
                with self.lock:
                    if op == 9:  # ttyd's ping, every 5 s
                        up.sendall(frame(10, body, mask=True))
                        for v in self.viewers:
                            self._send(v, frame(9, b''))
                        if not self.viewers and time.monotonic() - self.left > HOLD:
                            break
                    elif op == 8:
                        break
                    elif op < 3:
                        self.said = [*self.said, raw][-2000:]
                        for v in self.viewers:
                            self._send(v, raw)
        except (OSError, EOFError, ValueError):
            pass
        finally:
            self._end(up, f)

    def _end(self, up: socket.socket, f) -> None:
        with self.lock:
            f.close()
            up.close()
            if self.up is up:
                self.up = None
                for v in self.viewers:
                    self._send(v, frame(8, struct.pack('>H', ENDED)))
                    try:
                        v.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                self.viewers = []

    @staticmethod
    def _send(viewer, data: bytes) -> None:
        try:
            viewer.wfile.write(data)
        except (OSError, ValueError):  # it is going: its own thread sees that
            try:
                viewer.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        with self.lock:
            if self.up:
                try:
                    self.up.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve(self, handler, port: int, target: str) -> None:
        """A browser's WebSocket on the login, which the first one starts; until either side goes."""
        key = handler.headers.get('Sec-WebSocket-Key') or ''
        with self.lock:
            if self.up is None:
                try:
                    self._start(port, target)
                except OSError as e:
                    return handler.send(502, json.dumps({'ok': False, 'out': f"the login's terminal did not answer: {e}"}))
            up = self.up
            accept = base64.b64encode(hashlib.sha1((key + MAGIC).encode()).digest()).decode()
            handler.close_connection = True
            handler.connection.settimeout(QUIET)
            self._send(handler, ('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                                 f'Sec-WebSocket-Accept: {accept}\r\nSec-WebSocket-Protocol: tty\r\n\r\n').encode()
                       + b''.join(self.said))
            self.viewers.append(handler)
        try:
            while True:
                op, raw, body = read_frame(handler.rfile)
                if op == 8:
                    break
                with self.lock:
                    if self.up is not up:
                        break
                    if op == 9:
                        self._send(handler, frame(10, body))
                    elif op < 3:
                        up.sendall(raw)
        except (OSError, EOFError, ValueError):
            pass
        finally:
            with self.lock:
                if handler in self.viewers:
                    self.viewers.remove(handler)
                self.left = time.monotonic()
