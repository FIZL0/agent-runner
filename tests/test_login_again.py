"""F126b: 'Log in again': the terminal that renews the Claude login, on the run page and on Runner Home, and the hold
that keeps it while a phone is on the sign-in page."""
from __future__ import annotations

import io
import json
import os
import re
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import FAILED, check, eq

from agent_runner import home as H
from agent_runner import login_hold as L
from agent_runner import session_frame as SF
from agent_runner import state as S
from agent_runner import ui_model as U
from agent_runner import web as W
from _web import asked, fake_repo, get

tmp = Path(tempfile.mkdtemp(prefix='agent-runner-login-'))
os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'hc')
repo = fake_repo(tmp)
token = W.web_token()
run = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
home = H.serve_home('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: [], vitals=mock.Mock())
WS = 'GET {} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n'


def until(what, s: float = 10) -> bool:
    end = time.monotonic() + s
    while not what() and time.monotonic() < end:
        time.sleep(0.02)
    return bool(what())


class Ttyd:
    """A ttyd's WebSocket: greets each client, pings it, says back what it types; `stop` ends it as the command's end does."""

    def __init__(self):
        self.srv = socket.create_server(('127.0.0.1', 0))
        self.port, self.clients, self.got, self.targets, self.pongs = self.srv.getsockname()[1], [], [], [], 0
        threading.Thread(target=self.take, daemon=True).start()

    def take(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            threading.Thread(target=self.one, args=(c,), daemon=True).start()

    def one(self, c):
        f = c.makefile('rb')
        self.targets.append(f.readline().split()[1].decode())
        while f.readline() != b'\r\n':
            pass
        c.sendall(b'HTTP/1.1 101 x\r\n\r\n' + L.frame(2, b'link') + L.frame(9, b'p'))
        self.clients.append(c)
        try:
            while True:
                op, _, body = L.read_frame(f)
                if op == 10:
                    self.pongs += 1
                else:
                    self.got.append(body)
        except (EOFError, OSError):
            c.close()

    def stop(self):
        self.clients[-1].sendall(L.frame(8, struct.pack('>H', 1000)))


def browser(port: int, path: str):
    c = socket.create_connection(('127.0.0.1', port), timeout=10)
    c.sendall(WS.format(path).encode())
    f = c.makefile('rb')
    first = f.readline()
    head = b''
    while (line := f.readline()) not in (b'\r\n', b''):
        head += line
    return c, f, first, head


try:
    print('the button is on both pages, and the terminal in its sheet')
    for html in (W.page_html(), W.page_html(home=True)):
        check(b'data-login>Log in again</button>' in html and b'SHEETS.login' in html, 'the banner has the button')

    print("ttyd's command is the fixed one, with no word of a request")
    for terms, t in ((run.terms, token), (home.terms(), 'HT')):
        argv = terms.argv('login', 'login', 9)
        eq(argv[-3:], ['claude', 'auth', 'login'], 'claude auth login')
        check('attach' not in argv and not {'-a', '--url-arg'} & set(argv), 'no other command, no arguments from the URL', argv)
        eq((argv[argv.index('-i') + 1], argv[argv.index('-b') + 1]), ('127.0.0.1', f'/t/{t}/login'), 'on 127.0.0.1, at its token')

    print('only with the token, and only that command')
    seen = []
    up = {'ok': True, 'port': 9}
    with mock.patch.object(W.Terminals, 'ttyd', lambda self, n, sock='': up), mock.patch.object(
            SF, 'frame', lambda h, port, path, n, look: (seen.append((path, n)), h.send(200, '{}'))):
        for srv, t in ((run, token), (home, 'HT')):
            base = f'http://127.0.0.1:{srv.server_address[1]}'
            eq(json.loads(get(f'{base}/terminal/login?t={t}')[1])['path'], f'/t/{t}/login/', 'where it is')
            seen.clear()
            eq(get(f'{base}/t/{t}/login/?arg=sh&fontSize=12')[0], 200, 'with the token')
            eq(seen, [(f'/t/{t}/login/', 'login')], 'the query goes nowhere')
            for bad in (f'{base}/t/wrong/login/', f'{base}/t//login/', f'{base}/terminal/login?t=wrong', f'{base}/terminal/login'):
                eq(get(bad)[0], 403, f'refused: {bad.split("/", 3)[3]}')
            for other in ('sh', 'login2', 'claude', 'login%20x', '..'):
                eq(get(f'{base}/t/{t}/{other}/')[0], 404, f'no such terminal: {other}')

        print('a trusted network is let in without the key, but not to the login')
        ts = '100.101.1.2'
        S.C.raw['ui']['trusted_networks'] = ['tailnet']
        H.save_registry({**H.load_registry(), 'trusted_networks': ['tailnet']})
        rb, hb = (f'http://127.0.0.1:{s.server_address[1]}' for s in (run, home))
        eq((asked(f'{rb}/snapshot', ts, run), asked(f'{hb}/projects', ts, home)), (200, 200), 'the page opens')
        for base, srv in ((rb, run), (hb, home), (f'{hb}/p/k', home), (f'{hb}/p/k/', home)):
            eq([asked(f'{base}{p}', ts, srv) for p in ('/t//login/', '/terminal/login')], [403, 403], f'refused at {base}')
        S.C.raw['ui']['trusted_networks'] = []
        H.save_registry({**H.load_registry(), 'trusted_networks': []})

    print('without ttyd: how to install it, and the command')
    with mock.patch.object(U, 'terminal_mode', return_value='install'), mock.patch.object(
            W, 'ttyd_install_cmd', side_effect=['sudo pacman -S ttyd', '', 'sudo pacman -S ttyd', '']):
        for srv, t in ((run, token), (home, 'HT')):
            url = f'http://127.0.0.1:{srv.server_address[1]}/terminal/login?t={t}'
            r = json.loads(get(url)[1])
            eq((r['ok'], r['mode']), (False, 'install'), 'not opened')
            check('(sudo pacman -S ttyd)' in r['out'] and 'run claude auth login in a terminal' in r['out'], 'both said', r['out'])
            check('apt install ttyd' in json.loads(get(url)[1])['out'], 'no package manager known: the list')

    print('the hold: a browser that comes back has the same login; only its own end is an end')
    ttyd = Ttyd()
    with mock.patch.object(W.Terminals, 'ttyd', lambda self, n, sock='': {'ok': True, 'port': ttyd.port}):
        for srv, t in ((run, token), (home, 'HT')):
            port, path, hold, n = srv.server_address[1], f'/t/{t}/login/ws', (run.terms if srv is run else home.terms()).login, len(ttyd.targets)
            ttyd.got.clear()
            c, f, first, head = browser(port, path)
            check(b' 101 ' in first and b's3pPLMBiTxaQ9kYGzzhZRbK+xOo=' in head, 'a WebSocket', (first, head))
            eq(L.read_frame(f)[2], b'link', 'what it prints')
            eq(ttyd.targets[n:], [path], "at ttyd's own path")
            c.sendall(b'\x82\x83\x01\x02\x03\x04' + bytes([ord('a') ^ 1, ord('b') ^ 2, ord('c') ^ 3]))
            check(until(lambda: ttyd.got == [b'abc']), 'what is typed reaches it', ttyd.got)
            f.close()
            c.close()
            check(until(lambda: not hold.viewers), 'the phone went away')
            check(hold.live() and len(ttyd.targets) == n + 1 and until(lambda: ttyd.pongs), 'the login goes on, its pings answered')
            c, f, first, _ = browser(port, path)
            eq(L.read_frame(f)[2], b'link', 'back: what it printed so far')
            eq(len(ttyd.targets), n + 1, 'the same login, not a new one')
            ttyd.clients[-1].sendall(L.frame(9, b'p'))
            eq(L.read_frame(f)[0], 9, 'a browser is pinged, so one that vanished is noticed')
            ttyd.stop()
            op, _, body = L.read_frame(f)
            eq((op, body), (8, struct.pack('>H', L.ENDED)), 'the command ended: said as that')
            check(until(lambda: not hold.live()), 'so the next press starts a new one')
            f.close()
            c.close()
        c, f, *_ = browser(home.server_address[1], '/t/HT/login/ws')
        L.read_frame(f)
        f.close()
        c.close()
        hold = home.terms().login
        check(until(lambda: not hold.viewers), 'gone again')
        home.restart_due = lambda: True
        home.service_actions()
        check(hold.live() and not home.restart, 'Home does not restart under it')
        hold.left -= L.HOLD + 1
        ttyd.clients[-1].sendall(L.frame(9, b'p'))
        check(until(lambda: not hold.live()), 'nobody came back for HOLD: ended')
        home.restart_due = lambda: False
    with mock.patch.object(W.Terminals, 'ttyd', lambda self, n, sock='': {'ok': True, 'port': ttyd.port}), \
            mock.patch.object(L, 'QUIET', 0.3):
        c, f, *_ = browser(run.server_address[1], f'/t/{token}/login/ws')
        check(until(lambda: run.terms.login.viewers == [] and run.terms.login.left), 'a silent browser is dropped')
        check(run.terms.login.live(), 'and the login waits')
        f.close()
        c.close()
    try:
        L.read_frame(io.BytesIO(b'\x82\x7f' + (1 << 40).to_bytes(8, 'big')))
        check(False, 'a huge frame is refused')
    except EOFError:
        check(True, 'a huge frame is refused')
    eq(re.search(r"code===(\d+)", W.PAGE_TEXT.split("d.session!==LG.name")[1])[1], str(L.ENDED), 'the page knows the same end code')
finally:
    run.stop()
    home.stop()
raise SystemExit(1 if FAILED else print('\nall checks passed'))
