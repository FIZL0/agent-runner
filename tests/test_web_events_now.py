#!/usr/bin/env python3
"""B850b: the events stream sends a fresh snapshot within 0.5 s of an /act answer and of a STATE change."""
from __future__ import annotations

import json
import queue
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _check import check, report  # noqa: E402

from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402


class FakeC:
    def __init__(self, d: Path):
        self.d = d

    def notes(self, *parts):
        return self.d.joinpath(*parts)


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    count = [0]

    def snap():
        count[0] += 1
        return {'n': count[0]}

    with mock.patch.object(S, 'C', FakeC(tmp)), mock.patch.object(W, 'TICK', 30.0), \
            mock.patch.object(U, 'act', lambda name, **a: {'ok': True, 'code': 0, 'out': '', 'argv': []}):
        srv = W.WebServer('tok', 0, '127.0.0.1', snap=snap)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        got: queue.Queue = queue.Queue()

        def listen():
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/events?t=tok', timeout=20) as r:
                for line in r:
                    if line.startswith(b'data: '):
                        got.put(json.loads(line[6:]))

        threading.Thread(target=listen, daemon=True).start()
        first = got.get(timeout=5)
        check('n' in first, 'the stream sends a first snapshot')
        try:
            got.get(timeout=1.0)
            check(False, 'no second snapshot without a change (TICK is 30 s here)')
        except queue.Empty:
            pass
        req = urllib.request.Request(f'http://127.0.0.1:{port}/act?t=tok', data=json.dumps({'name': 'x'}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=10).read()
        t0 = time.monotonic()
        try:
            got.get(timeout=0.5)
            check(True, 'a snapshot within 0.5 s of the /act answer')
        except queue.Empty:
            check(False, 'a snapshot within 0.5 s of the /act answer')
        time.sleep(0.3)
        (tmp / 'STATE').write_text('{"state": "running"}', encoding='utf-8')
        t0 = time.monotonic()
        try:
            got.get(timeout=0.5)
            check(time.monotonic() - t0 < 0.5, 'a snapshot within 0.5 s of a STATE change')
        except queue.Empty:
            check(False, 'a snapshot within 0.5 s of a STATE change')
        srv.stopped.set()
        srv.shutdown()


if __name__ == '__main__':
    raise SystemExit(report([main]))
