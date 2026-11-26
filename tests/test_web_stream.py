"""The run page's events stream stays live (B838): the ping is an event the page hears, and a quiet stream dials again.

    python3 tests/test_web_stream.py
"""
from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, report

from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, logic_js, in_tmp  # noqa: E402


def test_ping_event(tmp: Path) -> None:
    fake_repo(tmp)
    token = W.web_token()
    snap = U.snapshot(up=False, links={}, terminal_base='.')
    with mock.patch.object(W, 'PING', 0.3), mock.patch.object(W, 'TICK', 0.2):
        srv = W.serve(token, 0, '127.0.0.1', snap=lambda: snap)
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{srv.server_address[1]}/events?t={token}', timeout=10) as r:
                first = r.readline().decode()
                check(first.startswith('data: {'), 'the stream opens with the snapshot', first[:80])
                eq(r.readline(), b'\n', 'the snapshot ends')
                eq(r.readline() + r.readline() + r.readline(), b'event: ping\ndata: 1\n\n',
                   'a quiet stream sends a named ping, which no onmessage takes for a snapshot')
        finally:
            srv.stop()


def test_redial_logic(tmp: Path) -> None:
    if not shutil.which('node'):
        print('  (no node here: the redial logic test is skipped)')
        return
    got = logic_js([['streamRedial', 0, 20000, 'quiet'], ['streamRedial', 0, 33000, 'quiet'], ['streamRedial', 0, 3000, 'shown'],
                    ['streamRedial', 0, 6000, 'shown'], ['dialWait', 0]])
    eq(got, [False, True, False, True, 1000], 'quiet past two pings dials; shown again dials unless heard in the last 5 s')


def test_page_wiring(tmp: Path) -> None:
    js = (Path(W.__file__).parent / 'page' / '180-live.js').read_text(encoding='utf-8')
    for part in ("addEventListener('ping'", "'visibilitychange'", "'pageshow'", "'online'", 'ES.close()', 'console.error'):
        check(part in js, f'the live script has {part}')
    check('catch(x){}' not in js, 'no error in drawing a snapshot is swallowed')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_ping_event), in_tmp(test_redial_logic), in_tmp(test_page_wiring)]))
