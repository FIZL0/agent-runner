#!/usr/bin/env python3
"""F94: Runner Home. Its registry of projects, the buttons calling the runner, routing a project's address to
its run's own page, the service files per OS, the QR code, and a run moving off a port Home holds.

    python3 tests/test_home_service.py      (temp folders, servers on free local ports; no service installed)
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import socket
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import home as H  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import web as W  # noqa: E402


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d).resolve()
            with mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'cfg')}):
                f(tmp)
    go.__name__ = f.__name__
    return go


def project(at: Path, toml: bool = True) -> Path:
    at.mkdir(parents=True)
    git(at, 'init', '-q')
    if toml:
        (at / 'runner.toml').write_text('[run]\nslots = 2\n', encoding='utf-8')
    return at


def get(url: str, data: bytes | None = None, follow: bool = True) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, data=data, method='POST' if data is not None else 'GET',
                                 headers={'Content-Type': 'application/json'} if data is not None else {})
    opener = urllib.request.build_opener(*([] if follow else [NoRedirect()]))
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def test_registry(tmp: Path) -> None:
    print('the registry: projects under ~/repos with a runner.toml, ones added by hand, ones unlisted')
    repos = tmp / 'repos'
    a, plain, c = project(repos / 'alpha'), project(repos / 'plain', toml=False), project(repos / 'charlie')
    (repos / 'notes.txt').write_text('x', encoding='utf-8')
    elsewhere = project(tmp / 'work' / 'bravo', toml=False)
    H.save_registry({**H.load_registry(), 'scan': [str(repos)]})
    eq(H.projects(), [a, c], 'scanned: each folder in ~/repos with a runner.toml, none without')
    eq(H.load_registry()['port'], 8770, 'Home is on port 8770 unless the registry says otherwise')
    ok, said = H.add_project(str(elsewhere))
    check(ok, 'a git repository outside ~/repos can be added by hand', said)
    eq(H.projects(), [a, elsewhere, c], 'and is listed, by name with the rest')
    check(not H.add_project(str(tmp / 'nope'))[0], 'a folder that is not there is refused')
    (tmp / 'empty').mkdir()
    check(not H.add_project(str(tmp / 'empty'))[0], 'and a folder that is no project')
    ok, _ = H.remove_project(str(c))
    check(ok, 'a scanned project can be unlisted')
    eq(H.projects(), [a, elsewhere], 'and stays unlisted though it is still in ~/repos')
    eq(H.load_registry()['hidden'], [str(c)], 'it is kept as hidden, not deleted')
    H.add_project(str(c))
    eq(H.projects(), [a, elsewhere, c], 'adding it again brings it back')
    H.remove_project(str(elsewhere))
    eq(H.load_registry()['projects'], [str(c)], 'unlisting one added by hand drops it from the registry')
    check(not H.remove_project(str(plain))[0], 'unlisting one Home never listed says so')
    eq(H.keys([a, tmp / 'x' / 'alpha', tmp / 'my proj']), {'alpha': a, 'alpha-2': tmp / 'x' / 'alpha',
                                                          'my-proj': tmp / 'my proj'},
       "a project's key is its folder name, made safe and told apart")
    t = H.home_token()
    eq(H.home_token(), t, 'the token is made once and kept')
    if os.name != 'nt':
        eq(oct((tmp / 'cfg' / 'home.token').stat().st_mode & 0o777), '0o600', 'readable by its owner only')
    r = run(tmp, 'home', 'list', env={**os.environ, 'AGENT_RUNNER_HOME_CONFIG': str(tmp / 'cfg')})
    eq(r.stdout.split(), [str(a), str(c)], '`agent-runner home list` prints them, from any folder')
    eq(run(tmp, 'home', 'install', 'extra').returncode, 2, 'a word too many is a usage error')


def test_rows(tmp: Path) -> None:
    print('each project: running, idle or off, paused, its slots, tasks queued, what needs you')
    root = tmp / 'p'
    infos = {'off': {'up': False}, 'idle': {'up': True, 'slots': 2, 'state': '2 slots', 'running': {}},
             'running': {'up': True, 'slots': 3, 'state': '3 slots, paused', 'running': {'2': 'F9', '1': 'B4'}}}
    rows = {k: H.project_row('p', root, info=lambda r, v=v: v,
                             facts=lambda r, run: {'left': 4, 'stopping': False,
                                                   'link': 'http://h:9/?t=x' if run.get('up') else ''},
                             needs=lambda r: (1, ['B2 - pick one - reply A/B'])) for k, v in infos.items()}
    eq(rows['off']['asks'], ['B2 - pick one - reply A/B'], 'and what each one is')
    eq((rows['off']['state'], rows['off']['page'], rows['off']['slots']), ('off', '', None),
       'no run up: off, nothing to open')
    eq((rows['idle']['state'], rows['idle']['paused'], rows['idle']['slots']), ('idle', False, 2),
       'a run up with nothing running: idle')
    eq((rows['running']['state'], rows['running']['paused'], rows['running']['running']), ('running', True, ['B4', 'F9']),
       'a run with tasks: running, with its tasks, and paused when its state says so')
    eq(rows['running']['page'], 'p/p/', "its run app opens through Home's own address")
    eq((rows['off']['left'], rows['off']['needs']), (4, 1), 'tasks queued and what needs you, run or not')

    def needs_said(text, code=0):
        H._NEEDS.clear()
        return H.needs_count(root, call=lambda r, a, t: SimpleNamespace(returncode=code, stdout=text, stderr=''))
    eq(needs_said('B2 - pick one - reply A/B\nF3 - check it\n2 things need you\n'), 2, '`needs` says 2: 2')
    eq(H.needs_said(root)[1], ['B2 - pick one - reply A/B', 'F3 - check it'], "with its 'ID - what to do' lines")
    eq(needs_said('Nothing needs you\n'), 0, 'Nothing needs you: 0')
    eq(needs_said('1 thing needs you\n'), 1, 'one thing: 1')
    eq(needs_said('boom', 1), None, 'a failing `needs`: unknown, not 0')
    calls = []
    H._NEEDS.clear()
    for _ in range(3):
        H.needs_count(root, call=lambda r, a, t: calls.append(a) or SimpleNamespace(returncode=0, stdout='Nothing needs you',
                                                                                    stderr=''))
    eq(len(calls), 1, 'a phone polling does not run `needs` each time: it is kept a while')


def test_actions(tmp: Path) -> None:
    print("Start, Stop, Pause and slots run the runner's own command in that project")
    eq(H.action_argv('start'), [], 'start: bare agent-runner (no terminal, so the run starts in the background)')
    eq(H.action_argv('stop'), ['stop'], 'stop: stop')
    eq(H.action_argv('pause'), ['pause'], 'pause: pause')
    eq(H.action_argv('resume'), ['pause', '--off'], 'resume: pause --off')
    eq([H.action_argv('slots', a) for a in ('+1', '-1', '4')], [['slots', '+1'], ['slots', '-1'], ['slots', '4']],
       'slots: +1, -1 or a count')
    eq([H.action_argv('slots', a) for a in ('0', 'x', '+2', '4; rm')], [None] * 4, 'anything else is refused')
    eq(H.action_argv('upgrade'), None, 'and so is a command Home has no button for')
    calls = []

    def call(root, argv, timeout):
        calls.append((root, argv))
        return SimpleNamespace(returncode=0, stdout='the run is up in the background: 2 slots\n', stderr='')
    root = tmp / 'p'
    r = H.run_action(root, 'start', call=call)
    eq((calls[-1], r['ok']), ((root, []), True), 'start calls the runner in the project folder')
    has(r['out'], 'is up in the background', 'and says what it said')
    H.run_action(root, 'slots', '+1', call=call)
    eq(calls[-1], (root, ['slots', '+1']), 'slots +1 calls `slots +1`')
    n = len(calls)
    r = H.run_action(root, 'slots', 'lots', call=call)
    eq((r['ok'], len(calls)), (False, n), 'a refused action calls nothing')
    r = H.run_action(root, 'stop', call=lambda *a: SimpleNamespace(returncode=1, stdout='', stderr='no run up'))
    eq((r['ok'], r['out']), (False, 'no run up'), "the runner's failure comes back as it said it")
    with mock.patch.object(H.sp, 'run') as sr:
        sr.return_value = SimpleNamespace(returncode=0, stdout='', stderr='')
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_REPO': '/elsewhere', 'AGENT_RUNNER_SLOT': '3'}):
            H.runner(root, ['pause'])
    argv, kw = sr.call_args[0][0], sr.call_args[1]
    eq((argv[-1], kw['cwd'], kw['stdin']), ('pause', str(root), H.sp.DEVNULL), 'the real call: the runner, in the project, no input')
    check('AGENT_RUNNER_REPO' not in kw['env'] and 'AGENT_RUNNER_SLOT' not in kw['env'],
          'without a slot\'s markers, so it acts on that project')
    check('AGENT_RUNNER_STARTED_BY' not in kw['env'], 'B145: a command other than start is not marked')
    with mock.patch.object(H.sp, 'run') as sr:
        sr.return_value = SimpleNamespace(returncode=0, stdout='', stderr='')
        H.runner(root, [])
    eq(sr.call_args[1]['env'].get('AGENT_RUNNER_STARTED_BY'), 'Home start',
       'B145: the start button marks the run as started by Home')


class FakeRun(BaseHTTPRequestHandler):
    """A run's page as Home sees it: it echoes what reached it, and streams /events."""
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def answer(self, body: bytes):
        data = json.dumps({'method': self.command, 'path': self.path, 'body': body.decode()}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith('/events'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            for i in range(3):
                self.wfile.write(f'data: {i}\n\n'.encode())
                self.wfile.flush()
            return
        self.answer(b'')

    def do_POST(self):
        self.answer(self.rfile.read(int(self.headers.get('Content-Length') or 0)))


def test_routing(tmp: Path) -> None:
    print("routing: /p/KEY/ is that project's run app, reached with the run's own token")
    fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeRun)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    alpha, beta = tmp / 'alpha', tmp / 'beta'
    acted = []
    links = {alpha: (fake.server_address[1], 'RUNTOKEN'), beta: None}
    srv = H.serve_home('HOMETOKEN', 0, '127.0.0.1', roots=lambda: [alpha, beta],
                       rows=lambda: [{'key': 'alpha', 'state': 'running'}], link=lambda r: links[r],
                       act=lambda root, name, arg: acted.append((root, name, arg)) or {'ok': True, 'out': 'done'})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        eq(get(f'{base}/')[0], 403, 'no token: refused')
        eq(get(f'{base}/p/alpha/snapshot?t=WRONG')[0], 403, 'a wrong token: refused, the run app too')
        code, body, _ = get(f'{base}/?t=HOMETOKEN')
        eq(code, 200, 'the Home page with its token')
        has(body.decode(), 'Runner Home', 'is the Home page')
        page = body.decode()
        check('const HOME_PAGE=true;' in page and 'data-psw' in page and 'function switcher()' in page
              and 'class="app"' in page, "F134: Home's page is the run app's markup, with the project switcher",
              page[:400])
        src = Path(H.__file__).read_text(encoding='utf-8')
        check('<style' not in src and 'PAGE = r"""' not in src, 'F134: no Home-only page or CSS left in home.py')
        code, body, _ = get(f'{base}/projects?t=HOMETOKEN')
        d = json.loads(body)
        eq((d['ok'], d['projects'], d['machine']), (True, [{'key': 'alpha', 'state': 'running'}], socket.gethostname()),
           'the projects as JSON, with the machine\'s name')
        code, body, _ = get(f'{base}/p/alpha/snapshot?t=HOMETOKEN&n=2')
        got = json.loads(body)
        eq((code, got['method'], got['path']), (200, 'GET', '/snapshot?t=RUNTOKEN&n=2'),
           "the run's page gets the path, the run's token in place of Home's, and the rest of the query")
        code, body, _ = get(f'{base}/p/alpha/act?t=HOMETOKEN', json.dumps({'name': 'chat'}).encode())
        got = json.loads(body)
        eq((got['method'], got['path'], json.loads(got['body'])), ('POST', '/act?t=RUNTOKEN', {'name': 'chat'}),
           'a POST goes through with its body')
        code, body, _ = get(f'{base}/p/alpha/events?t=HOMETOKEN')
        eq(body.decode(), 'data: 0\n\ndata: 1\n\ndata: 2\n\n', 'the events stream comes through as it is sent')
        code, _, hd = get(f'{base}/p/alpha?t=HOMETOKEN', follow=False)
        eq((code, hd.get('Location')), (302, '/p/alpha/?t=HOMETOKEN'), '/p/KEY goes to /p/KEY/, where the app\'s calls are relative')
        code, body, _ = get(f'{base}/p/beta/?t=HOMETOKEN')
        eq(code, 502, 'a project with no run up has no app to route to')
        has(body.decode(), 'no run up', 'and says so, with the way back to Home')
        eq(get(f'{base}/p/gamma/?t=HOMETOKEN')[0], 404, 'an unknown project: 404')
        code, body, _ = get(f'{base}/act?t=HOMETOKEN', json.dumps({'project': 'alpha', 'name': 'slots', 'arg': '+1'}).encode())
        eq((json.loads(body)['ok'], acted), (True, [(alpha, 'slots', '+1')]), "a button's POST acts on that project")
        eq(get(f'{base}/act?t=HOMETOKEN', json.dumps({'project': 'nope', 'name': 'stop'}).encode())[0], 404,
           'one for an unknown project: 404')
        eq(get(f'{base}/act?t=HOMETOKEN', b'[1]')[0], 400, 'a body that is not an object: 400')
    finally:
        srv.stop()
        fake.shutdown()
        fake.server_close()

    print("…and to a real run's page")
    run_srv = W.serve('RUNTOK2', 0, '127.0.0.1', snap=lambda: {'sessions': [], 'hello': 'from the run'})
    srv = H.serve_home('HT', 0, '127.0.0.1', roots=lambda: [alpha], rows=lambda: [],
                       link=lambda r: (run_srv.server_address[1], 'RUNTOK2'))
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        code, body, _ = get(f'{base}/p/alpha/?t=HT')
        eq(code, 200, "the run app's page through Home")
        has(body.decode(), "new URLSearchParams\\(location.search\\).get\\('t'\\)",
            "it reads its token from its own address, which holds Home's: Home swaps it on every call")
        code, body, _ = get(f'{base}/p/alpha/snapshot?t=HT')
        eq(json.loads(body).get('hello'), 'from the run', "its snapshot, from the run's server")
        mine = H.serve_home(H.home_token(), 0, '127.0.0.1', roots=lambda: [], rows=lambda: [])
        check(H.serving(mine.server_address[1]), '`home status`: Home answers on its port')
        mine.stop()
        check(not H.serving(run_srv.server_address[1]), "and a run's page on that port is not Home")
    finally:
        srv.stop()
        run_srv.stop()


class FakeTtyd(BaseHTTPRequestHandler):
    """ttyd, as far as Home sees it: its page under its base path, and a WebSocket that echoes what it gets."""
    protocol_version = 'HTTP/1.1'
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        FakeTtyd.seen.append((self.path, self.headers.get('Sec-WebSocket-Protocol'), self.headers.get('Host')))
        if not self.path.startswith('/t/RUNTOKEN/s1/'):
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.headers.get('Upgrade', '').lower() == 'websocket':
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Protocol', 'tty')
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            while data := self.rfile.read1(1024):
                self.wfile.write(b'echo:' + data)
            return
        data = f'<title>ttyd</title>{self.path}'.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_terminal_tab(tmp: Path) -> None:
    print("terminal tab: /p/KEY/t/TOKEN/NAME/ reaches the run's ttyd, its WebSocket included")
    ttyd = ThreadingHTTPServer(('127.0.0.1', 0), FakeTtyd)
    ttyd.daemon_threads = True
    threading.Thread(target=ttyd.serve_forever, daemon=True).start()
    asked = []

    class Run(FakeRun):
        def do_GET(self):
            asked.append(self.path)
            if self.path.startswith('/terminal/s1?'):
                out = {'ok': True, 'port': ttyd.server_address[1], 'path': '/t/RUNTOKEN/s1/'}
            else:
                out = {'ok': False, 'out': 'c9 is not up, so there is nothing for ttyd to show.'}
            data = json.dumps(out).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    run_srv = ThreadingHTTPServer(('127.0.0.1', 0), Run)
    threading.Thread(target=run_srv.serve_forever, daemon=True).start()
    alpha = tmp / 'alpha'
    srv = H.serve_home('HOMETOKEN', 0, '127.0.0.1', roots=lambda: [alpha], rows=lambda: [],
                       link=lambda r: (run_srv.server_address[1], 'RUNTOKEN'))
    hp = srv.server_address[1]
    base = f'http://127.0.0.1:{hp}'
    try:
        code, body, _ = get(f'{base}/p/alpha/t/HOMETOKEN/s1/')
        eq((code, body.decode()), (200, '<title>ttyd</title>/t/RUNTOKEN/s1/'),
           "ttyd's page, at its own path with the run's token, Home's token taken from the path")
        eq(asked[-1], '/terminal/s1?t=RUNTOKEN', "Home asked the run where s1's ttyd is (which starts it)")
        code, body, _ = get(f'{base}/p/alpha/t/HOMETOKEN/s1/?t=HOMETOKEN&x=1')
        eq(body.decode(), '<title>ttyd</title>/t/RUNTOKEN/s1/?x=1', "Home's token in the query does not reach ttyd")
        code, body, _ = get(f'{base}/p/alpha/t/HOMETOKEN/s1/token')
        eq((code, body.decode()), (200, '<title>ttyd</title>/t/RUNTOKEN/s1/token'),
           "ttyd's calls under its path come through without a query")
        eq(get(f'{base}/p/alpha/t/WRONG/s1/')[0], 403, 'a wrong token in the path: refused')
        eq(get(f'{base}/p/alpha/t/HOMETOKEN/s1')[0], 404, 'no slash after the name: not a terminal address')
        code, body, _ = get(f'{base}/p/alpha/t/HOMETOKEN/c9/')
        eq(code, 502, 'a session with no terminal: 502')
        has(body.decode(), 'c9 is not up', "with the run's reason")

        with socket.create_connection(('127.0.0.1', hp), timeout=10) as c:
            c.sendall(b'GET /p/alpha/t/HOMETOKEN/s1/ws HTTP/1.1\r\nHost: home\r\nUpgrade: websocket\r\n'
                      b'Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                      b'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: tty\r\n\r\n')
            got = b''
            while b'\r\n\r\n' not in got:
                chunk = c.recv(4096)
                check(chunk, 'the upgrade answer comes before the socket ends', got)
                if not chunk:
                    break
                got += chunk
            head = got.split(b'\r\n\r\n')[0].decode()
            has(head.split('\r\n')[0], '101', 'the WebSocket upgrade goes through: 101')
            has(head, 'Sec-WebSocket-Protocol: tty', "with ttyd's protocol")
            eq(FakeTtyd.seen[-1], ('/t/RUNTOKEN/s1/ws', 'tty', f'127.0.0.1:{ttyd.server_address[1]}'),
               "ttyd got the upgrade at its own path, the browser's protocol header kept")
            c.sendall(b'keys')
            back = b''
            while len(back) < len(b'echo:keys'):
                chunk = c.recv(4096)
                if not chunk:
                    break
                back += chunk
            eq(back, b'echo:keys', 'bytes flow both ways after the upgrade')
        page = (Path(W.__file__).parent / 'web_term.html').read_text(encoding='utf-8')
        has(page, r"'t/'\+encodeURIComponent\(T\)\+'/'\+encodeURIComponent\(name\)\+'/'",
            "the terminal-style page's pane goes by t/TOKEN/NAME/ when it is opened through Home")
    finally:
        srv.stop()
        run_srv.shutdown()
        run_srv.server_close()
        ttyd.shutdown()
        ttyd.server_close()


def test_restart_on_upgrade(tmp: Path) -> None:
    print('B165: the package changed on disk: Home asks for a restart once, never with a request or tunnel open')
    disk = ['v1']
    srv = H.HomeServer('HOMETOKEN', 0, '127.0.0.1', roots=lambda: [], rows=lambda: [], stamp=lambda: disk[0])
    asked = []
    srv.shutdown = lambda: asked.append(1)

    def tick(n: int = 1) -> int:
        for _ in range(n):
            srv.service_actions()
        for t in threading.enumerate():
            if t.name == 'home-restart':
                t.join(10)
        return len(asked)

    class Stream:
        shut = 0

        def shutdown(self, how):
            self.shut += 1

        def detach(self):  # Windows
            self.shut += 1
            return -1

    try:
        with mock.patch.object(H, 'LOOK_EVERY', 0.0):
            eq(tick(3), 0, 'the files it started on: no restart')
            disk[0] = None
            eq(tick(3), 0, 'files that cannot be read (mid-install): no restart')
            disk[0] = 'v2'
            eq(tick(), 0, 'a change seen once (an install under way): not yet')
            check(srv.enter(), 'a request comes in')
            eq(tick(3), 0, 'never while a request is open')
            stream = Stream()
            srv.streams['page'] = stream
            check(srv.enter(), "a page's event stream opens too")
            eq((tick(3), stream.shut), (0, 0), 'with a request open the stream is left alone')
            srv.leave()
            eq((tick(), stream.shut), (0, 1), 'only event streams left: they are ended, and still no restart')
            del srv.streams['page']
            srv.leave()
            eq(tick(), 1, 'nothing open: a restart is asked for')
            disk[0] = 'v3'
            eq(tick(5), 1, 'once, whatever changes next')
            check(not srv.enter(), 'a request that comes then is not run')
            said = []
            h = SimpleNamespace(server=srv, body=lambda: b'', send=lambda *a: said.append(a[0]))
            H.HomeHandler.counted(h, 'GET')
            eq((said, h.close_connection), ([], True), 'a GET is dropped: the browser asks again')
            H.HomeHandler.counted(h, 'POST')
            eq(said, [503], 'a POST is told to try again')
    finally:
        srv.server_close()
    calls = []
    eq(H.restart_home(lambda exe, argv: calls.append((exe, argv))), 1, 'the restart itself')
    eq(calls, [(H.sys.executable, H.sys.orig_argv)], 'runs the same command again in place')

    def gone(exe, argv):
        raise FileNotFoundError(exe)
    eq(H.restart_home(gone), 1, 'a failed one exits 1, so the service manager starts Home again')
    pkg = tmp / 'pkg'
    pkg.mkdir()
    (pkg / 'web_page.html').write_text('old', encoding='utf-8')
    with mock.patch.object(H, '__file__', str(pkg / 'home.py')):
        was = H.package_stamp()
        eq(H.package_stamp(), was, 'unchanged files: the same stamp')
        (pkg / 'web_page.html').write_text('newer', encoding='utf-8')
        check(H.package_stamp() != was, 'a changed page, the version the same: another stamp')
    with mock.patch.object(H, '__file__', str(tmp / 'gone' / 'home.py')):
        eq(H.package_stamp(), None, 'no package there: None')


def test_restart_on_windows(tmp: Path) -> None:
    print('F152: Windows: a detached helper runs the scheduled task again, and uninstall still stops Home')
    pyw, py = 'C:\\venv\\Scripts\\pythonw.exe', 'C:\\venv\\Scripts\\python.exe'
    check(H.can_restart('linux', '/usr/bin/python3'), 'Linux: always')
    check(not H.can_restart('win32', pyw), 'Windows, Home not installed: no task to run')
    H.mark_installed(True)
    check(H.can_restart('win32', pyw), 'run by its task')
    check(not H.can_restart('win32', py), 'typed in a terminal: it keeps serving')

    spawned = []
    eq(H.restart_home_task(8770, spawned.append), 0, 'the old Home ends well')
    eq(spawned[0][:2], [H.sys.executable, '-c'], 'and leaves a helper')
    has(spawned[0][2], rf'restart_task\({os.getpid()}, 8770\)', 'told its pid and port')
    compile(spawned[0][2], 'helper', 'exec')

    def no_spawn(argv):
        raise OSError('no')
    eq(H.restart_home_task(8770, no_spawn), 1, 'no helper started: it says so')

    calls, live = [], [True, True, False]
    call = lambda c: calls.append(c[1]) or (1 if c[1] == '/End' else 0, '')  # noqa: E731
    eq(H.restart_task(7, 8770, call, lambda p: calls.append(p) or not live.pop(0), lambda p: True), 0, 'the helper')
    eq(calls, [7, 7, 7, '/End', '/Run'], 'waits for the old Home to exit, then /End (which may fail) and /Run')
    calls, up = [], [False, True]
    eq(H.restart_task(7, 8770, call, lambda p: True, lambda p: up.pop(0)), 0, 'a /Run that came too early')
    eq(calls, ['/End', '/Run'] * 2, 'is run again')
    calls = []
    eq(H.restart_task(7, 8770, call, lambda p: True, lambda p: False), 1, 'a Home that never answers')
    eq(calls, ['/End', '/Run'] * 3, 'three times, no more')
    calls = []
    eq(H.restart_task(7, 8770, lambda c: calls.append(c[1]) or (1, ''), lambda p: True, lambda p: True), 1,
       'uninstalled meanwhile: /Run fails')
    eq(calls, ['/End', '/Run'], 'and it stops there')
    eq([c[1] for c in H.uninstall_commands('windows', None)], ['/Change', '/End', '/Delete'],
       'uninstall disables the task first, so no /Run lands after its /End')

    with mock.patch.object(H.sys, 'stdout', None), mock.patch.object(H.sys, 'stderr', None):
        H.log_without_console()
        f = H.sys.stdout
        print('no console')
        check(f is not None and H.sys.stderr is f, 'pythonw.exe has no stdout or stderr: both are a file')
        f.close()
    has((tmp / 'cfg' / 'home.log').read_text(encoding='utf-8'), 'no console', "Home's log")
    with mock.patch.object(H, 'os_kind', lambda *a: 'windows'):
        a, b = socket.socketpair()
        b.settimeout(10)
        H.end_stream(a)
        eq((a.fileno(), b.recv(1)), (-1, b''), "Windows: an event stream's handle is closed, which wakes its reader")
        b.close()


def test_restart_waits(tmp: Path) -> None:
    print('B165: over real sockets: a tunnel holds the restart; a run page event stream is ended for it')
    disk, beat = ['v1'], threading.Event()

    class Run(FakeRun):
        def do_GET(self):
            if self.path.startswith('/terminal/'):
                data = json.dumps({'ok': True, 'port': run_srv.server_address[1], 'path': '/t/RUNTOKEN/s1/'}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.headers.get('Upgrade'):
                return FakeTtyd.do_GET(self)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(b'data: 1\n\n')
            self.wfile.flush()
            beat.wait(60)  # a quiet stream
            self.close_connection = True

    run_srv = ThreadingHTTPServer(('127.0.0.1', 0), Run)
    run_srv.daemon_threads = True
    threading.Thread(target=run_srv.serve_forever, daemon=True).start()

    def opened(hp: int, head: bytes, until: bytes) -> socket.socket:
        c = socket.create_connection(('127.0.0.1', hp), timeout=10)
        c.sendall(head + b'\r\n\r\n')
        got = b''
        while until not in got:
            chunk = c.recv(4096)
            if not chunk:
                break
            got += chunk
        has(got.decode(), until.decode(), 'open')
        return c

    socks = []
    with mock.patch.object(H, 'LOOK_EVERY', 0.0):
        srv = H.HomeServer('HOMETOKEN', 0, '127.0.0.1', roots=lambda: [tmp / 'alpha'], rows=lambda: [],
                           link=lambda r: (run_srv.server_address[1], 'RUNTOKEN'), stamp=lambda: disk[0])
        loop = threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        loop.start()
        hp = srv.server_address[1]
        try:
            ws = opened(hp, b'GET /p/alpha/t/HOMETOKEN/s1/ws HTTP/1.1\r\nHost: h\r\nUpgrade: websocket\r\n'
                        b'Connection: Upgrade', b'\r\n\r\n')
            es = opened(hp, b'GET /p/alpha/events?t=HOMETOKEN HTTP/1.1\r\nHost: h', b'data: 1\n\n')
            socks += [ws, es]
            disk[0] = 'v2'
            loop.join(0.6)
            check(loop.is_alive() and srv.due and not srv.restart, 'a tunnel open: due, and it keeps serving')
            ws.sendall(b'keys')
            eq(ws.recv(4096), b'echo:keys', 'and the terminal works on')
            ws.close()
            eq(es.recv(4096), b'', 'the tunnel gone: the quiet event stream is ended')
            loop.join(10)
            check(not loop.is_alive() and srv.restart, 'and the server stops serving, to restart')
        finally:
            beat.set()
            for c in socks:
                c.close()
            if loop.is_alive():
                srv.shutdown()
            srv.server_close()
            run_srv.shutdown()
            run_srv.server_close()


def test_run_link(tmp: Path) -> None:
    print("the run's own page: its port and token from its notes, only while the run is up")
    root = project(tmp / 'proj')
    from agent_runner.config import Config
    Config(root).notes('web.url').write_text('http://box:45678/?t=abc123\nhttp://10.0.0.2:45678/?t=abc123\n',
                                             encoding='utf-8')
    with mock.patch('agent_runner.cmds.run_info', return_value={'up': True}):
        eq(H.run_link(root), (45678, 'abc123'), 'its port and token')
    with mock.patch('agent_runner.cmds.run_info', return_value={'up': False}):
        eq(H.run_link(root), None, 'no run up: none, whatever an old file says')


def test_units(tmp: Path) -> None:
    print('the service files: systemd user unit with linger, launchd agent, scheduled task')
    argv = ['/usr/bin/python3', '/opt/agent runner/run', 'home', 'serve']
    log = tmp / 'home.log'
    u = H.unit_text('linux', argv, log, {'PATH': '/usr/bin:/bin'})
    has(u, r'ExecStart=/usr/bin/python3 "/opt/agent runner/run" home serve\n', 'systemd: ExecStart runs `home serve`, quoted')
    has(u, r'WantedBy=default\.target', 'enabled for the user')
    has(u, r'Restart=on-failure', 'and restarted when it fails')
    has(u, r'Environment=PATH=/usr/bin:/bin', "with this shell's PATH, so it finds git and claude")
    p = plistlib.loads(H.unit_text('macos', argv, log, {'PATH': '/usr/bin'}).encode())
    eq((p['Label'], p['ProgramArguments'], p['RunAtLoad'], p['KeepAlive']), (H.LABEL, argv, True, True),
       'launchd: a valid plist that runs it at load and keeps it alive')
    eq((p['EnvironmentVariables'], p['StandardErrorPath']), ({'PATH': '/usr/bin'}, str(log)), 'its PATH and log')
    eq(H.unit_text('windows', ['C:\\Py\\pythonw.exe', 'C:\\My Tools\\run', 'home', 'serve'], log),
       'C:\\Py\\pythonw.exe "C:\\My Tools\\run" home serve', 'Windows: the command line the task runs, quoted')
    eq(H.unit_path('linux', tmp).name, 'agent-runner-home.service', 'systemd: a user unit')
    eq(H.unit_path('macos', tmp), tmp / 'Library' / 'LaunchAgents' / 'dev.agent-runner.home.plist',
       'launchd: a LaunchAgent')
    eq(H.unit_path('windows', tmp), None, 'Windows: no file, the task is in Task Scheduler')
    eq(H.os_kind('linux'), 'linux', 'linux')
    eq(H.os_kind('darwin'), 'macos', 'darwin is macOS')
    eq(H.os_kind('win32'), 'windows', 'win32 is Windows')
    eq(H.serve_argv('linux')[-2:], ['home', 'serve'], 'the service runs `agent-runner home serve`')

    print('install and uninstall: the file, then the commands, then the link and a QR code')
    env = {'HOME': str(tmp / 'home'), 'XDG_CONFIG_HOME': str(tmp / 'home' / '.config'), 'USER': 'me'}
    with mock.patch.dict(os.environ, env), mock.patch.object(Path, 'home', lambda: tmp / 'home'), \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, token: []), \
            mock.patch.object(H, 'offer_https', lambda port, urls, **kw: urls):  # F134: test_https_links has these
        for kind, want in (('linux', [['systemctl', '--user', 'daemon-reload'],
                                      ['systemctl', '--user', 'enable', '--now', 'agent-runner-home.service'],
                                      ['loginctl', 'enable-linger', 'me']]),
                           ('macos', [['launchctl', 'unload'], ['launchctl', 'load', '-w']]),
                           ('windows', [['schtasks', '/Create', '/TN', 'agent-runner-home', '/SC', 'ONLOGON'],
                                        ['schtasks', '/Run', '/TN', 'agent-runner-home']])):
            calls, said = [], []
            code = H.install(kind, call=lambda c: calls.append(c) or (1 if c[:2] == ['launchctl', 'unload'] else 0, ''),
                             out=said.append, check=lambda p: True)
            eq(code, 0, f'{kind}: install succeeds')
            eq([c[:len(w)] for c, w in zip(calls, want)], want, f'{kind}: and runs, in order: {want}')
            unit = H.unit_path(kind)
            if unit:
                check(unit.exists() and 'home' in unit.read_text(encoding='utf-8'), f'{kind}: its file is written', unit)
            text = '\n'.join(said)
            has(text, rf':8770/\?t={H.home_token()}', f'{kind}: it prints the link with its token')
            has(text, '▀|▄|█', f'{kind}: and a QR code of it')
            check(H.home_on(), f'{kind}: and Home is on in the registry (runs read it)')
            H.add_project(str(project(tmp / f'added-{kind}')))
            check(H.home_on(), f'{kind}: adding a project keeps it on')
            calls = []
            eq(H.uninstall(kind, call=lambda c: calls.append(c) or (0, ''), out=said.append), 0, f'{kind}: uninstall')
            check(calls and calls[0][0] in ('systemctl', 'launchctl', 'schtasks'), f'{kind}: it stops the service', calls)
            check(not H.home_on(), f'{kind}: Home is off again')
            if unit:
                check(not unit.exists(), f'{kind}: and removes its file')
        said = []
        code = H.install('linux', call=lambda c: (1, 'linger needs a login') if c[0] == 'loginctl' else (0, ''),
                         out=said.append, check=lambda p: True)
        eq(code, 0, 'linger refused: still installed')
        has(said[0], 'when you log in, not at boot', 'and says what that costs')
        said = []
        H.install('linux', call=lambda c: (0, ''), out=said.append, check=lambda p: False)
        has('\n'.join(said), 'does not answer on port 8770 yet: a run may hold that port',
            'installed but not answering: install says so, and why it may be')
        said = []
        eq(H.install('linux', call=lambda c: (1, 'no user bus') if c[2:3] == ['enable'] else (0, ''), out=said.append,
                     check=lambda p: True), 1, 'the service refused: install fails')
        has(said[-1], 'no user bus', 'with what systemctl said')

        print('status asks the service manager, not only whether the file is there')
        unit = H.unit_path('linux')
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text('x', encoding='utf-8')
        asked = []
        check(not H.installed('linux', call=lambda c: asked.append(c) or (1, 'disabled')), 'a unit not enabled: not installed')
        eq(asked[-1][:3], ['systemctl', '--user', 'is-enabled'], 'systemctl is-enabled says')
        check(H.installed('linux', call=lambda c: (0, '')), 'enabled: installed')
        check(H.installed('macos', call=lambda c: (0, '')) is False, 'no plist: not installed, nothing asked')

        print('a Windows command line past schtasks\' limit goes through a launcher file')
        short = 'C:\\py\\pythonw.exe run home serve'
        eq(H.task_command(short), short, 'a short one as it is')
        long = 'C:\\' + 'x' * 300 + '\\pythonw.exe run home serve'
        tr = H.task_command(long)
        check(len(tr) <= H.TR_MAX and tr.endswith('home-serve.cmd"'), 'a long one: the launcher\'s path', tr)
        has((tmp / 'cfg' / 'home-serve.cmd').read_text(encoding='utf-8'), 'x{300}', 'which holds the command')


SERVE_STATUS = {'TCP': {'8771': {'HTTPS': True}},
                'Web': {'box.tail1.ts.net:8771': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}}}}


def fake_tailscale(status: dict):
    """`tailscale serve status --json` answering `status`, as web.tailscale_https_urls runs it."""
    def run(argv, **kw):
        eq(argv[:3], ['tailscale', 'serve', 'status'], 'asks tailscale serve status')
        return subprocess.CompletedProcess(argv, 0, json.dumps(status), '')
    return lambda port, token: W.tailscale_https_urls(port, token, run=run)


def test_https_links(tmp: Path) -> None:
    print("F134: Home's links put Tailscale Serve's https address first (Talk's mic needs https)")
    token = H.home_token()
    with mock.patch.object(W, 'lan_ip', lambda: '192.168.1.5'):
        said = []
        eq(H.status('linux', out=said.append, https=fake_tailscale(SERVE_STATUS), on=True, up=True), 0, 'status')
        lines = [s.strip() for s in '\n'.join(said).splitlines()]
        urls = [s for s in lines if s.startswith('http')]
        eq(urls[0], f'https://box.tail1.ts.net:8771/?t={token}', 'home status lists the https URL first')
        check(any(u.startswith('http://192.168.1.5:8770/') for u in urls[1:]), 'then the http ones', urls)

        print('install: the https link first, and the QR code holds it')
        env = {'HOME': str(tmp / 'home'), 'XDG_CONFIG_HOME': str(tmp / 'home' / '.config'), 'USER': 'me'}
        with mock.patch.dict(os.environ, env), mock.patch.object(Path, 'home', lambda: tmp / 'home'), \
                mock.patch.object(H, 'qr_text', lambda text: f'QR[{text}]'):
            said = []
            eq(H.install('linux', call=lambda c: (0, ''), out=said.append, check=lambda p: True,
                         https=fake_tailscale(SERVE_STATUS)), 0, 'install')
            text = '\n'.join(said)
            check(text.index('https://box.tail1.ts.net:8771/') < text.index('http://192.168.1.5:8770/'),
                  'install prints the https link first', text)
            has(text, rf'QR\[https://box\.tail1\.ts\.net:8771/\?t={token}\]', 'and the QR code is of it')
            said, asked = [], []
            with mock.patch.object(H.shutil, 'which', lambda t: '/usr/bin/' + t):
                H.install('linux', call=lambda c: (0, ''), out=said.append, check=lambda p: True,
                          https=fake_tailscale({}), ask=lambda q: asked.append(q) or False)
            check(asked and 'tailscale serve --bg --https=8771' in asked[0], 'no serve: install offers to set one up', asked)
            has('\n'.join(said), r'run: tailscale serve --bg --https=8771 http://127\.0\.0\.1:8770',
                'a no: install says the command')

    print('install with no serve: offers to set one up, or says the command')
    plain = ['http://box:8770/?t=x']
    ran, said = [], []
    with mock.patch.object(H, 'home_urls', lambda port, https=None: ['https://box.ts.net:8771/?t=x'] + plain):
        got = H.offer_https(8770, plain, call=lambda c: ran.append(c) or (0, ''), out=said.append,
                            ask=lambda q: True, which=lambda t: '/usr/bin/tailscale')
    eq(ran, [['tailscale', 'serve', '--bg', '--https=8771', 'http://127.0.0.1:8770']], 'a yes runs tailscale serve')
    eq(got[0], 'https://box.ts.net:8771/?t=x', 'and the links are read again, https first')
    ran, said = [], []
    got = H.offer_https(8770, plain, call=lambda c: ran.append(c) or (0, ''), out=said.append,
                        ask=lambda q: False, which=lambda t: '/usr/bin/tailscale')
    eq((ran, got), ([], plain), 'a no runs nothing')
    has(said[-1], r'run: tailscale serve --bg --https=8771 http://127\.0\.0\.1:8770', 'and says the command')
    said = []
    H.offer_https(8770, plain, out=said.append, ask=lambda q: True, which=lambda t: None)
    has(said[-1], 'With Tailscale installed', 'no tailscale: says what https needs')
    said = []
    eq(H.offer_https(8770, ['https://a/?t=x'] + plain, out=said.append, ask=lambda q: 1 / 0), ['https://a/?t=x'] + plain,
       'an https link already: nothing offered')


def test_qr(tmp: Path) -> None:
    print('the QR code: a valid symbol, readable by a scanner when one is here')
    url = 'http://192.168.1.23:8770/?t=' + 'a' * 24
    m = H.qr_matrix(url)
    eq(len(m), 29, 'a 52-byte link: version 3, 29 modules a side')
    finder = [[True] * 7, [True] + [False] * 5 + [True]] + [[True, False, True, True, True, False, True]] * 3 + \
        [[True] + [False] * 5 + [True], [True] * 7]
    for x0, y0 in ((0, 0), (22, 0), (0, 22)):
        eq([row[x0:x0 + 7] for row in m[y0:y0 + 7]], finder, f'a finder pattern at {x0},{y0}')
    eq(H.qr_matrix('x' * 300), None, 'too long for version 10: none, and install prints only the link')
    eq(len(H.qr_text(url, ansi=False).splitlines()), (29 + 5) // 2, 'two rows of modules per line, with a quiet zone')
    check('\x1b[' in H.qr_text(url, ansi=True), 'on a terminal, drawn black on white whatever its colours')
    if shutil.which('zbarimg'):
        for text in ('hi', url, 'b' * 250):
            m = H.qr_matrix(text)
            s, q = 4, 4
            n = (len(m) + 2 * q) * s
            rows = [''.join('1' if 0 <= y // s - q < len(m) and 0 <= x // s - q < len(m) and m[y // s - q][x // s - q]
                            else '0' for x in range(n)) for y in range(n)]
            f = tmp / 'qr.pbm'
            f.write_text(f'P1\n{n} {n}\n' + '\n'.join(rows) + '\n', encoding='ascii')
            r = subprocess.run(['zbarimg', '-q', '--raw', str(f)], capture_output=True, text=True)
            eq(r.stdout.strip(), text, f'zbarimg reads it back ({len(text)} bytes, {len(m)} modules)')


def test_run_moves_off_the_port(tmp: Path) -> None:
    print("a run whose port Home holds serves its page on a free one, and Home routes to it")
    root = project(tmp / 'proj')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    old = Path.cwd()
    os.chdir(root)
    try:
        S.init(root)
        held = socket.socket()
        held.bind(('0.0.0.0', 0))
        held.listen()
        port = held.getsockname()[1]
        H.save_registry(H.load_registry())  # a registry, but Home not installed
        with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), \
                mock.patch.dict(S.C.run, {'web': True, 'web_port': port}), mock.patch.object(S, 'log') as lg:
            srv = W.start_web()
        try:  # B146: another run holds the port: a free one, with Home off too
            check(srv is not None and srv.server_address[1] != port, 'B146: Home off: still served, on another port', srv)
            has(' '.join(str(c) for c in lg.call_args_list), f'port {port} is taken', 'and the run log says why')
        finally:
            if srv:
                srv.stop()
        H.mark_installed(True)
        with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), \
                mock.patch.dict(S.C.run, {'web': True, 'web_port': port}), mock.patch.object(S, 'log') as lg:
            srv = W.start_web()
        try:
            check(srv is not None and srv.server_address[1] != port, 'the page is served on another port', srv)
            logged = ' '.join(str(c) for c in lg.call_args_list)
            has(logged, f'port {port} is taken', 'the run log says why')
            has(logged, 'Runner Home opens it', 'and that Home opens it')
            us = W.url_file().read_text(encoding='utf-8').split()
            has(us[0], f':{srv.server_address[1]}/', 'its notes hold the port it got, which Home reads')
        finally:
            if srv:
                srv.stop()
            held.close()
    finally:
        os.chdir(old)


def test_device_site_link(tmp: Path) -> None:
    print("B146: with the port held, the run page's link goes through the device site (Home's /p/KEY/), else the bare port")
    from agent_runner import cmds as M
    root = project(tmp / 'proj')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    old = Path.cwd()
    os.chdir(root)
    held = socket.socket()
    held.bind(('0.0.0.0', 0))
    held.listen()
    port = held.getsockname()[1]
    srv = home = None
    nots = lambda p, t: []  # noqa: E731 - no Tailscale Serve here
    try:
        S.init(root)
        S.C.todo.parent.mkdir(parents=True, exist_ok=True)
        S.C.todo.write_text('- [ ] **B1** one\n', encoding='utf-8')  # run_facts counts the tasks left first
        H.save_registry({**H.load_registry(), 'scan': [str(tmp / 'none')]})
        H.add_project(str(root))
        with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: ''), \
                mock.patch.object(W, 'tailscale_https_urls', nots), \
                mock.patch.dict(S.C.run, {'web': True, 'web_port': port}), mock.patch.object(S, 'log'):
            srv = W.start_web()
        check(srv is not None and srv.server_address[1] != port, 'another run holds the port: served on a free one', srv)
        mine = srv.server_address[1]
        eq(srv.terms.port, mine, "the terminal tab's ttyd ports follow the port it got")
        bare = f'http://{socket.gethostname()}:{mine}/?t={W.web_token()}'
        eq(W.url_file().read_text(encoding='utf-8').split(), [bare], 'web.url keeps its own port (Home routes to it)')
        with mock.patch.object(S, 'run_up', return_value=True), mock.patch.object(W, 'tailscale_https_urls', nots), \
                mock.patch.object(W, 'lan_ip', lambda: ''):
            eq(W.page_line(), f'run page: {bare}', 'no device site: status gives the bare port link')
            eq(M.run_facts(root, {'up': True}, nots)['link'], bare, 'and so does run_facts (the picker)')
            home = H.serve_home(H.home_token(), 0, '127.0.0.1', roots=lambda: [root], rows=lambda: [])
            hp = home.server_address[1]
            H.save_registry({**H.load_registry(), 'port': hp})
            site = f'http://{socket.gethostname()}:{hp}/p/proj/?t={H.home_token()}'
            eq(H.site_links(root), [site], 'Home serves and lists the project: its /p/KEY/ link')
            eq(W.page_line(), f'run page: {site}', 'status gives the device site link')
            eq(M.run_facts(root, {'up': True}, nots)['link'], site, 'and so does run_facts (the picker)')
            ts = lambda p, t: [f'https://box.tail.ts.net/?t={t}'] if p == hp else []  # noqa: E731
            eq(M.run_facts(root, {'up': True}, ts)['link'], f'https://box.tail.ts.net/p/proj/?t={H.home_token()}',
               "a Tailscale Serve https address for Home's port keeps the /p/KEY/ path")
            eq(H.site_links(root, https=ts), [f'https://box.tail.ts.net/p/proj/?t={H.home_token()}', site],
               'F134: the /p/KEY/ links themselves put the https one first')
            H.remove_project(str(root))
            eq(H.site_links(root), [], 'Home does not list the project: no device site link')
            H.add_project(str(root))
            home.stop()
            home = None
            eq(W.page_line(), f'run page: {bare}', 'Home down: the bare port link again')
        srv.stop()
        # Home installed on a port nobody holds: the run still keeps off it, so Home can start later
        held.close()
        H.save_registry({**H.load_registry(), 'port': port})
        H.mark_installed(True)
        with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: ''), \
                mock.patch.object(W, 'tailscale_https_urls', nots), \
                mock.patch.dict(S.C.run, {'web': True, 'web_port': port}), mock.patch.object(S, 'log') as lg:
            srv = W.start_web()
        check(srv is not None and srv.server_address[1] != port, "Home installed: a run never binds Home's port", srv)
        has(' '.join(str(c) for c in lg.call_args_list), 'kept for it', 'and the run log says why')
    finally:
        for s in (srv, home):
            if s:
                s.stop()
        held.close()
        os.chdir(old)


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_registry), in_tmp(test_rows), in_tmp(test_actions), in_tmp(test_routing),
                           in_tmp(test_terminal_tab), in_tmp(test_restart_on_upgrade), in_tmp(test_restart_waits),
                           in_tmp(test_restart_on_windows),
                           in_tmp(test_run_link), in_tmp(test_units), in_tmp(test_https_links), in_tmp(test_qr),
                           in_tmp(test_run_moves_off_the_port), in_tmp(test_device_site_link)]))
