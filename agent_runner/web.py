"""F66: the run page on the web. A run serves it from this machine (`[run] web`, on by default) on
`[run] web_port` (8770), bound to every interface so a phone on the LAN or Tailscale reaches it.

    GET  /?t=TOKEN               the page (web_page.html): lazygit panels over F65's snapshot, in `[ui] theme`
    GET  /snapshot?t=TOKEN       the run page model's snapshot, as JSON
    GET  /events?t=TOKEN         the same snapshot over server-sent events, sent again whenever it changes
    POST /act?t=TOKEN            {"name": ACTION, "args": {...}}: one of `ui_model.ACTIONS` (plan add, plan edit,
                                 drop, shelve, release, chat, answer, take, move), its result as JSON
    GET  /terminal/NAME?t=TOKEN  where slot NAME's (or c1's) tmux pane is served by ttyd, started on demand

Every request carries the token (`?t=`, or an `X-Token` header): the page can type into panes, so one without
it is refused. The token is made once per project (<notes>/web.token) and printed by `status` and in the run
log with the page's address. Standard library only; ttyd is optional (the terminal tab says how to install it).
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import shutil
import socket
import subprocess as sp
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent_runner import state as S
from agent_runner import theme as TH
from agent_runner import ui_model as U

PAGE = Path(__file__).with_name('web_page.html')
TICK = 2.0  # s between snapshots the events stream compares
PING = 15.0  # s of no change before the stream sends a keep-alive comment
TTYD_INSTALL = ('ttyd is not installed, so the terminal tab cannot show the pane. Install it on this machine '
                '(Arch: pacman -S ttyd; Debian/Ubuntu: apt install ttyd; macOS: brew install ttyd) and open '
                'the tab again.')


# --- the token and the address ----------------------------------------------------------------------------------

def token_file() -> Path:
    return S.C.notes('web.token')


def web_token() -> str:
    """This project's run page token: read from <notes>/web.token, made there (owner-only) the first time."""
    f = token_file()
    try:
        if t := f.read_text(encoding='utf-8').strip():
            return t
    except OSError:
        pass
    t = secrets.token_urlsafe(18)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(t + '\n', encoding='utf-8')
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return t


def page_url(port: int, token: str, host: str = '') -> str:
    return f'http://{host or socket.gethostname()}:{port}/?t={token}'


def lan_ip() -> str:
    """This machine's address on the network it routes out of ('' if none): a phone that cannot resolve the
    bare hostname still reaches this. No packet is sent (a UDP connect only picks the route)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))
            ip = s.getsockname()[0]
        return '' if ip.startswith('127.') else ip
    except OSError:
        return ''


def page_urls(port: int, token: str) -> list[str]:
    """The page's addresses: by hostname, then by LAN address when there is one."""
    return [page_url(port, token)] + ([page_url(port, token, ip)] if (ip := lan_ip()) else [])


def url_file() -> Path:
    return S.C.notes('web.url')


def page_line() -> str:
    """`run page: URL` while a run serves the page (what `status` prints), else ''."""
    try:
        if S.run_up() and (us := url_file().read_text(encoding='utf-8').split()):
            return f'run page: {us[0]}' + (f' (or {us[1]})' if len(us) > 1 else '')
    except OSError:
        pass
    return ''


# --- c1 and the terminals ---------------------------------------------------------------------------------------

def c1_pane() -> str:
    """c1's tmux pane, found by its tag (never $TMUX_PANE: in the run that is the runner's own pane)."""
    try:
        from agent_runner.control import control_live, control_window
        pid = control_live(1)
        return control_window(1, pid) if pid else ''
    except Exception:  # noqa: BLE001 - no tmux, no c1
        return ''


def pane_of(name: str) -> str:
    """The tmux pane id of slot `name` (s2) or of c1; '' when it has none (a hidden slot, no tmux)."""
    if name == 'c1':
        return c1_pane()
    try:
        from agent_runner import slots
        if getattr(slots.MUX, 'name', '') != 'tmux':
            return ''
        return slots.MUX.panes().get(name, ('', 0))[0]
    except Exception:  # noqa: BLE001
        return ''


class Terminals:
    """One ttyd per pane, started the first time its tab opens, on web_port+1, +2, …; each serves only under
    /t/TOKEN/NAME/, so the address is as secret as the page's. It attaches a grouped tmux session of its own
    (destroyed when the browser leaves), so watching a pane moves no other client's window."""

    def __init__(self, token: str, port: int, bind: str):
        self.token, self.port, self.bind = token, port, bind
        self.procs: dict[str, tuple[sp.Popen, int, str]] = {}
        self.lock = threading.Lock()

    def argv(self, name: str, pane: str, port: int) -> list[str]:
        sess = sp.run(['tmux', 'display-message', '-p', '-t', pane, '#{session_name}'], capture_output=True,
                      text=True).stdout.strip()
        return ['ttyd', '-W', '-p', str(port), *(['-i', self.bind] if self.bind not in ('', '0.0.0.0') else []),
                '-b', f'/t/{self.token}/{name}',
                'tmux', 'new-session', '-t', sess, ';', 'set-option', 'destroy-unattached', 'on', ';',
                'select-window', '-t', pane, ';', 'select-pane', '-t', pane]

    def open(self, name: str) -> dict:
        if not shutil.which('ttyd'):
            return {'ok': False, 'out': TTYD_INSTALL}
        pane = pane_of(name)
        if not pane:
            return {'ok': False, 'out': f'{name} has no tmux pane (the run is hidden, or {name} is not up), so '
                                        f'there is nothing for ttyd to show.'}
        with self.lock:
            p = self.procs.get(name)
            if p and p[0].poll() is None and p[2] == pane:
                port = p[1]
            else:
                if p and p[0].poll() is None:
                    p[0].terminate()
                self.procs.pop(name, None)
                used = {v[1] for v in self.procs.values() if v[0].poll() is None}
                port = next(x for x in range(self.port + 1, self.port + 200) if x not in used)
                proc = sp.Popen(self.argv(name, pane, port), stdin=sp.DEVNULL, stdout=sp.DEVNULL,
                                stderr=sp.PIPE, start_new_session=True)
                try:  # one that cannot start (its port taken) ends at once: say so, not a dead frame
                    err = proc.communicate(timeout=0.8)[1].decode(errors='replace').strip()
                    return {'ok': False, 'out': f'ttyd for {name} ended at once (port {port}): {err[-300:]}'}
                except sp.TimeoutExpired:
                    pass
                self.procs[name] = (proc, port, pane)
        return {'ok': True, 'port': port, 'path': f'/t/{self.token}/{name}/'}

    def close(self) -> None:
        for proc, _, _ in self.procs.values():
            if proc.poll() is None:
                proc.terminate()


# --- the server -------------------------------------------------------------------------------------------------

class Snapshots:
    """The snapshot, made at most once per TICK however many pages watch it."""

    def __init__(self, make):
        self.make, self.lock, self.at, self.last = make, threading.Lock(), 0.0, ''

    def get(self) -> str:
        with self.lock:
            if time.monotonic() - self.at >= TICK or not self.last:
                try:
                    self.last = json.dumps(self.make(), ensure_ascii=False)
                except Exception as e:  # noqa: BLE001 - a bad read shows on the page, it does not end the stream
                    self.last = json.dumps({'error': f'{type(e).__name__}: {e}'})
                self.at = time.monotonic()
            return self.last


def page_html(name: str | None = None) -> bytes:
    """F69: the page in theme `name` (default `[ui] theme`): its tokens in style#theme, and every theme's in THEMES
    for the page's picker (T), one table with the terminal page (theme.py)."""
    name = TH.checked(name or TH.configured())
    themes = TH.all_resolved()
    css = ':root{' + ';'.join(f'--{k}:{v}' for k, v in themes[name].items() if k != 'mode') + \
        f';color-scheme:{"light" if themes[name]["mode"] == "light" else "dark"}}}'
    data = json.dumps({'default': name, 'themes': themes}).replace('</', '<\\/')
    page = PAGE.read_text(encoding='utf-8').replace('/*THEME_CSS*/', css, 1)
    return page.replace('/*THEMES*/{"default":"ryha","themes":{}}', data, 1).encode('utf-8')


def run_snapshot() -> dict:
    return U.snapshot(terminal_base='.')


class Handler(BaseHTTPRequestHandler):
    server: 'WebServer'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a) -> None:  # the run log is not an access log
        pass

    def allowed(self) -> bool:
        q = parse_qs(urlsplit(self.path).query)
        got = (q.get('t') or [''])[0]
        return bool(got) and hmac.compare_digest(got.encode(), self.server.token.encode())

    def send(self, code: int, body: bytes | str, ctype: str = 'application/json; charset=utf-8') -> None:
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def refuse(self) -> None:
        self.send(403, json.dumps({'ok': False, 'out': 'the run page needs its token: open the address '
                                   '`status` prints (…/?t=TOKEN)'}))

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if not self.allowed():
            return self.refuse()
        if path in ('/', '/index.html'):
            return self.send(200, page_html(), 'text/html; charset=utf-8')
        if path == '/snapshot':
            return self.send(200, self.server.snaps.get())
        if path == '/events':
            return self.events()
        if path.startswith('/terminal/'):
            return self.send(200, json.dumps(self.server.terms.open(path.split('/')[2])))
        self.send(404, json.dumps({'ok': False, 'out': f'no such page: {path}'}))

    def do_POST(self) -> None:
        if not self.allowed():
            return self.refuse()
        if urlsplit(self.path).path != '/act':
            return self.send(404, json.dumps({'ok': False, 'out': 'POST goes to /act'}))
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            name, args = str(body.get('name', '')), body.get('args') or {}
            if not isinstance(args, dict):
                raise ValueError('args must be an object')
        except (ValueError, AttributeError) as e:
            return self.send(400, json.dumps({'ok': False, 'out': f'bad request: {e}'}))
        r = U.act(name, **args)
        self.server.snaps.at = 0.0  # the next snapshot shows what the action changed
        self.send(200, json.dumps(r, ensure_ascii=False))

    def events(self) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        last, quiet = '', time.monotonic()
        try:
            while not self.server.stopped.is_set():
                snap = self.server.snaps.get()
                if snap != last:
                    self.wfile.write(f'data: {snap}\n\n'.encode('utf-8'))
                    last, quiet = snap, time.monotonic()
                elif time.monotonic() - quiet >= PING:
                    self.wfile.write(b': ping\n\n')
                    quiet = time.monotonic()
                self.wfile.flush()
                self.server.stopped.wait(TICK / 2)
        except OSError:  # the page went away
            pass


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, token: str, port: int, bind: str = '0.0.0.0', snap=run_snapshot):
        self.token, self.snaps, self.stopped = token, Snapshots(snap), threading.Event()
        super().__init__((bind, port), Handler)
        self.terms = Terminals(token, self.server_address[1], bind)

    def stop(self) -> None:
        self.stopped.set()
        self.shutdown()
        self.server_close()
        self.terms.close()


def serve(token: str, port: int, bind: str = '0.0.0.0', snap=run_snapshot) -> WebServer:
    """Start a run page server in a daemon thread and return it (port 0: any free port)."""
    srv = WebServer(token, port, bind, snap)
    threading.Thread(target=srv.serve_forever, name='run-page', daemon=True).start()
    return srv


def start_web() -> WebServer | None:
    """The run's start: serve the page when `[run] web` is on (the run log gets its address), else nothing.
    A port in use costs the page, not the run. AGENT_RUNNER_NO_WEB=1 (the test suites) turns it off too."""
    url_file().unlink(missing_ok=True)
    r = S.C.run
    if not r.get('web', True) or os.environ.get('AGENT_RUNNER_NO_WEB'):
        return None
    port = int(r.get('web_port', 8770))
    try:
        srv = serve(web_token(), port)
    except OSError as e:
        S.log(f'run page: cannot serve on port {port} ({e}); set [run] web_port, or web = false')
        return None
    urls = page_urls(srv.server_address[1], srv.token)
    url_file().write_text('\n'.join(urls) + '\n', encoding='utf-8')
    S.log(f'run page: {" or ".join(urls)}' + ('' if shutil.which('ttyd') else ' (no terminal tab: ttyd is not installed)'))
    return srv
