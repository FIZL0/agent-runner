"""F114: the viewers of one hidden session (attach.Viewers), and the Windows listener (a token-guarded port), run
on any OS with plat.WINDOWS patched."""
from __future__ import annotations

import json
import select
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, eq, report  # noqa: E402
from agent_runner import attach as A, cmds, plat  # noqa: E402


class Session:
    """A Viewers with a thread, and what it did."""

    def __init__(self, path: Path):
        self.sizes, self.typed = [], []
        self.v = A.Viewers(path, self.typed.append, lambda r, c: self.sizes.append((r, c)), (50, 200))
        threading.Thread(target=self.v.serve, daemon=True).start()


def until(f) -> bool:
    end = time.monotonic() + 10
    while time.monotonic() < end and not f():
        time.sleep(0.02)
    return bool(f())


def test_windows_port(tmp: Path) -> None:
    print('Windows: the shim listens on 127.0.0.1 for clients with its token; attach does not refuse')
    with mock.patch.object(plat, 'WINDOWS', True):
        path = tmp / 'slot9.sock'
        s = Session(path)
        d = json.loads(path.read_text(encoding='utf-8'))
        check(s.v.listener.getsockname()[0] == '127.0.0.1' and len(d['token']) > 20, 'a port on this machine alone, a token', d)
        import socket
        bad = socket.create_connection(('127.0.0.1', d['port']), timeout=5)
        bad.sendall(A.attach_input_frames(b'rm'))
        eq(bad.recv(9), b'', 'a client without the token is sent away')
        quiet = socket.create_connection(('127.0.0.1', d['port']), timeout=5)
        c = A.connect(path)
        c.sendall(A.attach_size_frame(30, 100) + A.attach_input_frames(b'hi'))
        check(until(lambda: s.typed == [b'hi']), 'one with it types', s.typed)
        check(until(lambda: (30, 100) in s.sizes), 'and sizes', s.sizes)
        s.v.out(b'printed')
        c.settimeout(5)
        eq(c.recv(99), b'printed', 'and gets what the session prints')
        check(not select.select([quiet], [], [], 0.2)[0], 'one that sent no token gets nothing')
        check(A.reachable(path), 'reachable')
        s.v.close()
        check(not path.exists() and not A.reachable(path), 'the file goes with the session')
        path.write_text('{"port": 1}', encoding='utf-8')
        check(not A.reachable(path), 'a left-over file is no session')
        with mock.patch.object(cmds, 'init'), mock.patch.object(cmds, 'session_socket', lambda n: path), \
                mock.patch.object(cmds, 'attach_session', lambda p, n: 7):
            eq([cmds.cmd_attach([n]) for n in ('s9', 'c3')], [7, 7], 'attach attaches')


def test_sizes(tmp: Path) -> None:
    print("several viewers: the session has the smallest of their sizes, and its own when they have gone")
    with mock.patch.object(plat, 'WINDOWS', True):
        path = tmp / 'slot8.sock'
        s = Session(path)
        big, small = A.connect(path), A.connect(path)
        big.sendall(A.attach_size_frame(40, 150))
        check(until(lambda: s.sizes[-1:] == [(40, 150)]), 'one viewer: its size', s.sizes)
        small.sendall(A.attach_size_frame(45, 50))
        check(until(lambda: s.sizes[-1:] == [(40, 50)]), 'a phone beside it: the fewest rows and columns', s.sizes)
        small.sendall(A.attach_size_frame(1, 2))
        third = A.connect(path)
        n = len(s.sizes)
        third.sendall(A.attach_size_frame(60, 180))
        check(until(lambda: s.sizes[n:] == [(39, 50), (40, 50)]), 'a larger one moves nothing: the screen is drawn again for it, '
              'and a frame folded away sets no size', s.sizes[n:])
        small.close()
        check(until(lambda: s.sizes[-1:] == [(40, 150)]), 'the phone goes: the others have their width back', s.sizes)
        big.close()
        third.close()
        check(until(lambda: s.sizes[-1:] == [(50, 200)]), 'the last one goes: its own size', s.sizes)
        s.v.close()


def test_typed() -> None:
    print("Ctrl-b d detaches a terminal; through the run page Ctrl-b is the session's")
    with mock.patch.dict(A.os.environ):
        A.os.environ.pop('AGENT_RUNNER_WEB', None)
        t = A.Typed()
        eq([t.feed(b'a\x02'), t.feed(b'\x02b'), t.feed(b'\x02dz')], [(b'a', False), (b'\x02b', False), (b'', True)], 'a terminal')
        A.os.environ['AGENT_RUNNER_WEB'] = '1'
        eq(A.Typed().feed(b'\x02d'), (b'\x02d', False), 'the run page')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-attach-'))
    return report([lambda: test_windows_port(tmp), lambda: test_sizes(tmp), test_typed])


if __name__ == '__main__':
    sys.exit(main())
