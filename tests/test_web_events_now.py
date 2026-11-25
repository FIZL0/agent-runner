"""B850b: the events stream sends a fresh snapshot at once after an /act answer and after a STATE change.

    python3 tests/test_web_events_now.py
"""
from __future__ import annotations

import os
import queue
import threading
import time
import urllib.request
from pathlib import Path

from _check import check, report
from _web import fake_repo, post, in_tmp  # noqa: E402

from agent_runner import web as W  # noqa: E402


def reader(url: str, got: queue.Queue) -> None:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            for line in r:
                if line.startswith(b'data: '):
                    got.put((time.monotonic(), line))
    except Exception:  # noqa: BLE001 - the server stopped
        pass


def next_data(got: queue.Queue, after: float, within: float):
    end = time.monotonic() + within
    while (left := end - time.monotonic()) > 0:
        try:
            at, _ = got.get(timeout=left)
        except queue.Empty:
            return None
        if at >= after:
            return at - after
    return None


def test_events_now(tmp: Path) -> None:
    fake_repo(tmp)
    n = [0]

    def snap():
        n[0] += 1
        return {'n': n[0]}
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=snap)
    state = tmp / 'STATE.test'
    state.write_text('{}', encoding='utf-8')
    srv.snaps.state = lambda: state
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    got: queue.Queue = queue.Queue()
    try:
        threading.Thread(target=reader, args=(f'{base}/events?t={token}', got), daemon=True).start()
        check(next_data(got, 0, 5) is not None, 'the stream sends a first snapshot')
        time.sleep(0.3)
        code, _ = post(f'{base}/act?t={token}', {'name': 'chat_order', 'args': {'order': []}})
        answered = time.monotonic()
        lag = next_data(got, answered - 0.05, 0.5)
        check(lag is not None, f'a fresh snapshot within 0.5 s of the /act answer (code {code}, lag {lag})')
        time.sleep(0.3)
        state.write_text('{"running": {"a": 1}}', encoding='utf-8')
        os.utime(state, ns=(time.time_ns(), time.time_ns() + 10**9))
        changed = time.monotonic()
        lag = next_data(got, changed, 0.5)
        check(lag is not None, f'a fresh snapshot within 0.5 s of a STATE change (lag {lag})')
        made = n[0]
        time.sleep(1.0)
        check(n[0] - made <= 1, f'no more snapshots otherwise than once per TICK ({n[0] - made} in 1 s)')
    finally:
        srv.stop()


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_events_now)]))
