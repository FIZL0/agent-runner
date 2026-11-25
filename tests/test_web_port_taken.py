"""B844: a run whose web_port is taken: without Runner Home its page is on the next free port for every interface, with
Home on 127.0.0.1 behind it; the page-only process and the run after it keep that port.

    python3 tests/test_web_port_taken.py
"""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from unittest import mock

from _check import check, eq, report
from _web import fake_repo, get, in_tmp

from agent_runner import home as H
from agent_runner import page_https as T
from agent_runner import page_only as P
from agent_runner import plat
from agent_runner import state as S
from agent_runner import web as W
from test_page_only import until

BOX = 'box.tail.ts.net'


class Tail:
    """A fake Tailscale: its Serve rules, and the changes asked of it."""

    def __init__(self, port: int):
        self.status = {'TCP': {str(port + 1): {'HTTPS': True}},
                       'Web': {f'{BOX}:{port + 1}': {'Handlers': {'/': {'Proxy': f'http://127.0.0.1:{port}'}}}}}
        self.changes: list[str] = []

    def __call__(self, *args, limit=0.0):
        import json
        if args == ('status', '--json'):
            return True, json.dumps({'BackendState': 'Running', 'Self': {'DNSName': BOX + '.'}, 'CertDomains': [BOX]})
        if args[:2] == ('serve', 'status'):
            return True, json.dumps(self.status)
        self.changes.append(' '.join(args))
        https = next(a for a in args if a.startswith('--https=')).partition('=')[2]
        if args[-1] == 'off':
            self.status['TCP'].pop(https, None)
            self.status['Web'].pop(f'{BOX}:{https}', None)
        else:
            self.status['TCP'][https] = {'HTTPS': True}
            self.status['Web'][f'{BOX}:{https}'] = {'Handlers': {'/': {'Proxy': args[-1]}}}
        return True, ''


def held_port() -> socket.socket:
    """A taken port with free ones after it (low enough that the kernel hands none of them out meanwhile)."""
    for port in range(20000 + os.getpid() % 4000, 30000, 50):
        got: list[socket.socket] = []
        try:
            for p in range(port, port + 8):
                s = socket.socket()
                got.append(s)
                s.bind(('0.0.0.0', p))
            got[0].listen()
            return got.pop(0)
        except OSError:
            if got and len(got) == 8:
                got.pop(0).close()
        finally:
            for s in got:
                s.close()
    raise AssertionError('no free ports')


def with_run(f):
    """Run `f(tmp, port, tail, log, start)` in a project whose web_port `port` another server holds."""
    def go(tmp: Path) -> None:
        fake_repo(tmp)
        held = held_port()
        port = held.getsockname()[1]
        tail, log = Tail(port), []

        def start(**settings):
            log.clear()
            with mock.patch.dict(S.C.run, {'web': True, 'web_port': port, **settings}):
                return W.start_web()
        env = {'AGENT_RUNNER_NO_WEB': '', 'AGENT_RUNNER_NO_SERVE': '', 'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'cfg')}
        with mock.patch.dict(os.environ, env), mock.patch.object(T, 'tailscale', tail), \
                mock.patch.object(T.shutil, 'which', lambda n, *a, **k: '/bin/true'), \
                mock.patch.object(W, 'tailscale_https_urls', lambda p, t: W.serve_https_urls(tail.status, p, t)), \
                mock.patch.object(W, 'lan_ip', lambda: '10.0.0.5'), mock.patch.object(W, 'HOME_LOOK', 999), \
                mock.patch.object(W, 'site_urls', lambda *a, **k: []), mock.patch.object(S, 'log', log.append), \
                mock.patch.object(P, 'held_messages', lambda: None):
            try:
                f(tmp, port, tail, log, start)
            finally:
                held.close()
    go.__name__ = f.__name__
    return go


def other_address() -> str:
    """An address of this machine that is not 127.0.0.1 (Linux has every 127.x one)."""
    if os.name != 'nt' and os.uname().sysname == 'Linux':
        return '127.0.0.2'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            return s.getsockname()[0]
    except OSError:
        return ''


@with_run
def test_without_home(tmp: Path, port, tail, log, start) -> None:
    rule = {k: dict(v) for k, v in tail.status.items()}
    srv = start()
    mine, t = srv.server_address[1], W.web_token()
    try:
        eq(srv.server_address, ('0.0.0.0', port + 2), 'every interface, the next port past the https port of web_port')
        if at := other_address():
            eq([get(f'http://{at}:{mine}/?t={x}')[0] for x in (t, 'no')], [200, 403], 'another address: with the key only')
        host = socket.gethostname()
        eq(P.urls(), [f'http://{h}:{mine}/?t={t}' for h in (host, BOX, '10.0.0.5')], 'web.url: hostname, tailnet, LAN')
        want = [f'https://{BOX}:{mine + 1}/?t={t}', *P.urls(), f'http://localhost:{mine}/?t={t}']
        eq(log[-1].split(' (ttyd')[0], 'run page: ' + ' or '.join(want), 'the run log has every link')
        check(any(f'port {port} is taken' in x and f'on port {mine}' in x for x in log), 'and why', log)
        check(not any('nothing opens it' in x or 'only Runner Home' in x for x in log), 'nothing untrue', log)
        with mock.patch.object(S, 'run_up', return_value=True):
            eq(W.page_line(), f'run page: {want[0]} (or {" or ".join(want[1:])})', 'and so has status')
        third = W.serve_open(0, port)
        eq(third.server_address, ('0.0.0.0', port + 4), "a third run's is past its https port too")
        third.stop()
    finally:
        srv.stop()
    check(all(f'--https={port + 1}' not in c for c in tail.changes), "web_port's rule is never changed", tail.changes)
    eq(tail.status, rule, 'its own is gone, the other is as it was')
    srv = start(web_https=False)
    try:
        check(f'http://{BOX}:{mine}/?t={t}' in log[-1] and 'https://' not in log[-1], 'web_https = false: http', log)
    finally:
        srv.stop()


@with_run
def test_ports(tmp: Path, port, tail, log, start) -> None:
    tail.status['TCP'][str(port + 2)] = {'HTTPS': True}
    T.keep_rule({'host': BOX, 'https': port + 4, 'port': port + 3, 'run': 'another'})
    eq(T.next_ports(port, 4), [port + 6, port + 8], "not Serve's ports nor a recorded rule's")
    tail.status['TCP'][str(port + 7)] = {'HTTPS': True}
    eq(T.next_ports(port, 4), [port + 8], "nor one whose https port is another's")
    tail.status['Web'][f'{BOX}:{port + 7}'] = {'Handlers': {'/': {'Proxy': f'http://127.0.0.1:{port + 6}'}}}
    eq(T.next_ports(port, 4), [port + 6, port + 8], 'but one with an https address already')
    eq(T.next_ports(65535), [], 'none past the last port')
    with mock.patch.object(T, 'next_ports', lambda p: []):
        srv = W.serve_open(0, port)
    check(srv.server_address[0] == '0.0.0.0' and srv.server_address[1] != port, 'none of them free: any')
    srv.stop()
    with mock.patch.object(P, 'take_over', lambda: port + 40):  # it was behind a Home that is gone
        srv = start()
    eq(srv.server_address, ('0.0.0.0', port + 6), 'a port that was only for Home is not opened')
    srv.stop()


@with_run
def test_home_installed(tmp: Path, port, tail, log, start) -> None:
    H.mark_installed(True)
    srv = start()
    try:
        check(srv.private(), 'F165: 127.0.0.1 behind Home')
    finally:
        srv.stop()
    with mock.patch.dict(S.C.given, {'run': {'web_port': port}}), mock.patch.object(W, 'home_port', lambda: 1):
        srv = start()
        try:
            check(srv.private() and any('is taken' in x and 'only Runner Home opens it' in x for x in log),
                  'so too with a web_port of its own', log)
        finally:
            srv.stop()
        H.mark_installed(False)
        with mock.patch.object(W, 'home_port', lambda: 0):
            srv = start()
        try:
            check(not srv.private(), 'no Home: open')
            H.mark_installed(True)
            W.HomeWatch(srv).look()
            eq((srv.private(), W.fell_back()), (True, 0), 'Home installed meanwhile: it moves behind it')
        finally:
            srv.stop()


@with_run
def test_page_only_keeps_it(tmp: Path, port, tail, log, start) -> None:
    run = start()
    mine, t = run.server_address[1], W.web_token()
    was = P.urls()
    S.C.notes('page.hand').write_text(
        f'{{"pid": {os.getpid()}, "bind": "{run.server_address[0]}", "port": {mine}}}', encoding='utf-8')
    go = threading.Event()
    th = threading.Thread(target=lambda: P.serve(go, handed=True), daemon=True)
    th.start()
    srv = None
    try:
        check(until(P.held), 'a run hands it over')
        run.https = False  # as hand_over: the rule stays
        run.stop()
        check(until(P.serving), 'the page-only process has it')
        S.C.notes('page.hand').unlink()
        eq(P.urls(), was, 'the same addresses')
        if at := other_address():
            eq(get(f'http://{at}:{mine}/?t={t}')[0], 200, 'open to other devices')
        with mock.patch.object(W, 'serve', wraps=W.serve) as served:
            lock = plat.lock(S.C.notes('run.lock'))
            try:
                srv = start()
            finally:
                lock.close()
        eq((srv.server_address, served.call_args_list[0].args[1]), (('0.0.0.0', mine), mine), 'the run keeps the port')
        eq(P.urls(), was, 'and the addresses')
        th.join(10)
        check(not th.is_alive(), 'the page-only process ended')
        srv.stop()
        # web_port free by now: the page that is open stays where it is; another web_port is the person's choice
        with mock.patch.object(P, 'take_over', lambda: mine):
            W.fell_file().write_text(f'{port + 6} {mine}\n', encoding='utf-8')
            for web_port, want in ((port + 6, mine), (port + 5, port + 5)):
                srv = start(web_port=web_port)
                eq(srv.server_address[1], want, f'web_port {web_port - port:+}')
                srv.stop()
    finally:
        go.set()
        th.join(10)
        if srv:
            srv.stop()


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(t) for t in (test_without_home, test_ports, test_home_installed,
                                                 test_page_only_keeps_it)]))
