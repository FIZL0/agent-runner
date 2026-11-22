"""F66: the run page on the web. A run serves it from this machine (`[run] web`, on by default) on
`[run] web_port` (8770), bound to every interface so a phone on the LAN or Tailscale reaches it.

    GET  /?t=TOKEN               F79: the page (web_page.html), the run app: a chat app over F74's model, light
                                 and dark by the browser's setting, laid out for a phone and a desktop
    GET  /snapshot?t=TOKEN       the run page model's snapshot, as JSON, with the machine's name and each
                                 concept's options (`run_snapshot`)
    GET  /events?t=TOKEN         the same snapshot over server-sent events, sent again whenever it changes
    POST /act?t=TOKEN            {"name": ACTION, "args": {...}}: one of `ui_model.ACTIONS` (plan add, plan edit,
                                 drop, shelve, release, chat, answer, take, move), its result as JSON
    GET  /terminal/NAME?t=TOKEN  where slot NAME's (or c1's, or cN's) tmux pane is served by ttyd, started on demand;
                                 without ttyd, the built-in view to use instead (or, with no tmux, the feed only)
    GET  /feed/NAME?t=TOKEN      F74: session NAME's transcript as say/you/tool/out entries (`ui_model.feed`)
    GET  /pane/NAME?t=TOKEN      F74: the built-in terminal view: NAME's pane as text now (`ui_model.capture`)
    GET  /concept/ID?t=TOKEN     F74: concept ID's local page copy (<notes>/concepts/ID.html), sandboxed
    GET  /diff/NAME?t=TOKEN      F75: slot NAME's diff so far (`slot_diff`), for its diff tab
    POST /upload?t=TOKEN&name=N  F79: an attachment (the body, as is) kept under <notes>/uploads; its path on this
                                 machine comes back, for the message that hands it to a session

Every request carries the token (`?t=`, or an `X-Token` header): the page can type into panes, so one without
it is refused. The token is made once per project (<notes>/web.token) and printed by `status` and in the run
log with the page's address. Standard library only; ttyd is optional (the terminal tab says how to install it).
"""

from __future__ import annotations

import hmac
import json
import os
import re
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


def control_pane(n: int) -> str:
    """F73: control session cN's tmux pane, by its cN tag (or its pid, when its pid file names a live one)."""
    try:
        from agent_runner.control import control_live, control_window
        return control_window(n, control_live(n))
    except Exception:  # noqa: BLE001 - no tmux, no such window
        return ''


def pane_of(name: str) -> str:
    """The tmux pane id of slot `name` (s2), of c1 or of another control session (c6); '' when it has none (a
    hidden slot, no tmux)."""
    if name == 'c1':
        return c1_pane()
    if name[:1] == 'c' and name[1:].isdigit():
        return control_pane(int(name[1:]))
    try:
        from agent_runner import slots
        if getattr(slots.MUX, 'name', '') != 'tmux':
            return ''
        return slots.MUX.panes().get(name, ('', 0))[0]
    except Exception:  # noqa: BLE001
        return ''


FEED_ONLY = ('There is no tmux here (Windows, or it is not installed), so {name} has no terminal to show: its feed '
             'and its session link show it.')


def terminal_fallback(name: str) -> dict:
    """F74: the terminal tab without ttyd: with tmux, the built-in view (`mode` 'builtin': GET `capture` every
    `every` s, POST the `keys` action to type), and how to install ttyd for the live one; else the feed only."""
    if U.terminal_mode() == 'feed':
        return {'ok': False, 'mode': 'feed', 'out': FEED_ONLY.format(name=name), 'feed': f'feed/{name}'}
    return {'ok': False, 'mode': 'builtin', 'out': TTYD_INSTALL + ' Until then the built-in view shows the pane.',
            'capture': f'pane/{name}', 'every': U.CAPTURE_EVERY, 'feed': f'feed/{name}'}


DIFF_BYTES = 200_000  # the most of a slot's diff the diff tab shows


def slot_diff(name: str) -> dict:
    """F75: the diff tab: slot `name`'s (s2) work so far, its worktree (committed or not) against where it
    branched off the shared branch: {'ok', 'name', 'text'} or {'ok': False, 'out': why}."""
    if not (name[:1] == 's' and name[1:].isdigit()):
        return {'ok': False, 'name': name, 'out': f'{name} is not a slot: only a slot has a diff'}
    d = Path(S.SLOTS_DIR) / name
    if not d.is_dir():
        return {'ok': False, 'name': name, 'out': f'{name} has no worktree yet'}
    try:
        base = S.default_branch()
    except SystemExit as e:
        return {'ok': False, 'name': name, 'out': str(e)}

    def git(*a: str) -> sp.CompletedProcess:
        return sp.run(['git', '-C', str(d), *a], capture_output=True, text=True, encoding='utf-8',
                      errors='replace', timeout=20)
    try:
        mb = git('merge-base', base, 'HEAD')
        if mb.returncode:
            return {'ok': False, 'name': name, 'out': f'git merge-base {base} HEAD: {mb.stderr.strip()}'}
        r = git('diff', mb.stdout.strip())
    except (OSError, sp.SubprocessError) as e:
        return {'ok': False, 'name': name, 'out': f'git diff: {e}'}
    if r.returncode:
        return {'ok': False, 'name': name, 'out': f'git diff: {r.stderr.strip()}'}
    text = r.stdout
    if len(text) > DIFF_BYTES:
        text = text[:DIFF_BYTES] + '\n… (the rest left out)'
    return {'ok': True, 'name': name, 'text': text}


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
            return terminal_fallback(name)
        pane = pane_of(name)
        if not pane:
            return {'ok': False, 'mode': 'feed', 'feed': f'feed/{name}',
                    'out': f'{name} has no tmux pane (the run is hidden, or {name} is not up), so '
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


def page_html() -> bytes:
    """F79: the run app. Its light and dark looks follow the browser's setting (`[ui] theme` is the terminal
    UI's), so the file is served as it is."""
    return PAGE.read_bytes()


_OPTIONS: dict[str, tuple[float, list]] = {}  # a concept copy's path: (its mtime, its options)


def concept_options(path: str) -> list[dict]:
    """F79: a concept's options for the Plan's buttons, from its local page copy as the terminal UI reads it
    (`tui.concept_page`: the headings one level below the title): [{'name', 'rec'}]; [] for no copy."""
    if not path:
        return []
    try:
        mt = os.path.getmtime(path)
        if (hit := _OPTIONS.get(path)) and hit[0] == mt:
            return hit[1]
        from agent_runner.tui import concept_page
        opts = [{'name': o['name'], 'rec': o['rec']}
                for o in concept_page(Path(path).read_text(encoding='utf-8', errors='replace'))['options']]
    except OSError:
        return []
    _OPTIONS[path] = (mt, opts)
    return opts


def with_extras(snap: dict) -> dict:
    """F79: what the run app shows beyond the snapshot: this machine's name, and each concept's options."""
    snap['machine'] = socket.gethostname()
    for c in snap.get('concepts') or []:
        c['options'] = concept_options(c.get('copy', ''))
    return snap


def run_snapshot() -> dict:
    return with_extras(U.snapshot(terminal_base='.'))


UPLOAD_BYTES = 50 * 1024 * 1024  # the largest attachment the page may upload


def upload_dir() -> Path:
    """F79: where attachments are kept: <notes>/uploads (.runner/uploads by default), git-ignored with it."""
    d = S.C.notes('uploads', 'x').parent
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    """An uploaded file's name made safe to keep: its last path part, only letters, digits and . _ - (others
    become _), no leading dot, at most 100 characters; 'file' when nothing is left."""
    base = re.split(r'[\\/]', name or '')[-1]
    base = re.sub(r'[^A-Za-z0-9._-]+', '_', base).lstrip('.')[-100:]
    return base or 'file'


def save_upload(name: str, data: bytes) -> dict:
    """F79: keep an attachment under `upload_dir()` as <time>-<safe name> (never over another file): {'ok', 'path'
    (absolute, for the session it is handed to), 'name'}."""
    d = upload_dir()
    stem = time.strftime('%Y%m%d-%H%M%S') + '-' + safe_name(name)
    p, n = d / stem, 1
    while p.exists():
        n += 1
        p = d / f'{n}-{stem}'
    p.write_bytes(data)
    return {'ok': True, 'path': str(p.resolve()), 'name': p.name}


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
        if path.startswith('/feed/'):
            return self.send(200, json.dumps(U.feed(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/pane/'):
            return self.send(200, json.dumps(U.capture(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/diff/'):
            return self.send(200, json.dumps(slot_diff(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/concept/'):
            return self.concept(path.split('/')[2])
        self.send(404, json.dumps({'ok': False, 'out': f'no such page: {path}'}))

    def do_POST(self) -> None:
        if not self.allowed():
            return self.refuse()
        if urlsplit(self.path).path == '/upload':
            return self.upload()
        if urlsplit(self.path).path != '/act':
            return self.send(404, json.dumps({'ok': False, 'out': 'POST goes to /act or /upload'}))
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

    def upload(self) -> None:
        """F79: an attachment from the message box: the body as is, `name` in the query (`save_upload`)."""
        try:
            size = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            size = -1
        if size <= 0 or size > UPLOAD_BYTES:
            self.close_connection = True
            return self.send(413 if size > 0 else 400, json.dumps({'ok': False, 'out': (
                f'an attachment is at most {UPLOAD_BYTES // 1024 // 1024} MB' if size > 0 else 'an empty upload')}))
        name = (parse_qs(urlsplit(self.path).query).get('name') or [''])[0]
        try:
            r = save_upload(name, self.rfile.read(size))
        except OSError as e:
            return self.send(500, json.dumps({'ok': False, 'out': f'could not keep the upload: {e}'}))
        self.send(200, json.dumps(r, ensure_ascii=False))

    def concept(self, cid: str) -> None:
        """F74: a concept's local page copy (`ui_model.concept_copy`), for the page to show inline. Sandboxed:
        it runs as a page of its own origin, so its scripts never reach the run page or its token."""
        f = U.concept_copy(cid)
        if not f:
            return self.send(404, json.dumps({'ok': False, 'out': f'no local copy of concept {cid}\'s page'}))
        data = Path(f).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', 'sandbox allow-scripts')
        self.end_headers()
        self.wfile.write(data)

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
