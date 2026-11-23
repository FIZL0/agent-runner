"""F94: Runner Home, one always-on page for every project on this machine.

    agent-runner home install     set it up as a per-user service that starts at boot (systemd --user with
                                  linger on Linux, launchd on macOS, a scheduled task on Windows); prints the
                                  link and a QR code
    agent-runner home uninstall   take the service away again (the registry and token stay)
    agent-runner home status      installed or not, serving or not, and the link
    agent-runner home add PATH    list a project that is not under the scanned folders (remove PATH: unlist it)
    agent-runner home list        the projects Home lists, one per line
    agent-runner home serve       the server itself, in this terminal (what the service runs)
    agent-runner home peer add LINK   show another machine's Home under Devices (remove LINK: stop); `peers` lists

Off until installed: nothing runs and nothing listens until `home install`. The server is the same kind as a
run's page (web.py): standard library only, token-gated, bound to every interface so a phone on the LAN or on
Tailscale reaches it, on port 8770 (`port` in the registry). A run that finds the port taken, or Home installed
at all (F165), serves its own page on 127.0.0.1 only (web.start_web), and Home routes to it; the run's link is
Home's /p/KEY/ (B146, site_links), so one device address switches between runners:

    GET  /?t=TOKEN               the Home page: F134: the run app (web_page.html) in Home mode, its All projects
                                 view: every project, running, idle or off, what needs you, buttons, Devices
    GET  /projects?t=TOKEN       the same as JSON (`project_rows`)
    POST /act?t=TOKEN            {"project": KEY, "name": start|stop|pause|resume|slots, "arg": "+1"}: the
                                 runner's own command in that project (`run_action`)
    POST /add?t=TOKEN            {"path": PATH} lists a project; /remove unlists one
    ANY  /p/KEY/...?t=TOKEN      that project's run app, routed to its run's page with the run's own token, so
                                 Home's link is the only one a phone needs; a run works the same with Home off
    ANY  /p/KEY/t/TOKEN/NAME/... F107: session NAME's terminal tab, the run's ttyd for it (WebSocket included);
                                 the token is in the path, since ttyd's page drops the query
    GET  /devices?t=TOKEN        F95: Device Vitals, this machine and each peer Home's (vitals.py), and their
                                 alerts (Needs you); /device?id=ID the vitals page; /vitals/device this
                                 machine's; /vitals/clean Clean; /dev/ID/... the same on device ID

The registry (<config>/home.json, <config> being ~/.config/agent-runner, %APPDATA%\\agent-runner on Windows, or
AGENT_RUNNER_HOME_CONFIG) holds the projects added by hand, scanned ones hidden by `remove`, the folders scanned
(default ~/repos: each folder in it with a runner.toml) and the port. The token is <config>/home.token.
"""
from __future__ import annotations

import concurrent.futures as cf
import hmac
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import subprocess as sp
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from agent_runner import home_screen

PORT = 8770
SERVICE = 'agent-runner-home'  # the systemd unit's and the scheduled task's name
LABEL = 'dev.agent-runner.home'  # launchd's label
SCAN = ['~/repos']
LOOK_EVERY = 5.0  # s between two looks at the package's files (`HomeServer.restart_due`)
NEEDS_TTL = 20.0  # s a project's needs count is kept before `needs` runs again


# --- the registry -----------------------------------------------------------------------------------------------

def config_dir() -> Path:
    if env := os.environ.get('AGENT_RUNNER_HOME_CONFIG'):
        return Path(env).expanduser()
    if sys.platform.startswith('win'):
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming') / 'agent-runner'
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'agent-runner'


def registry_file() -> Path:
    return config_dir() / 'home.json'


def load_registry() -> dict:
    """{'projects': [added paths], 'hidden': [scanned paths removed], 'scan': [folders], 'port': int,
    'installed': bool (`home install` turned Home on), 'peers': [other Homes' links], 'tailscale': bool}."""
    try:
        data = json.loads(registry_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    port = data.get('port')
    return {'projects': [str(p) for p in data.get('projects') or [] if isinstance(p, str)],
            'hidden': [str(p) for p in data.get('hidden') or [] if isinstance(p, str)],
            'scan': [str(p) for p in data.get('scan') or SCAN if isinstance(p, str)],
            'port': port if isinstance(port, int) and not isinstance(port, bool) and 0 <= port < 65536 else PORT,
            'installed': data.get('installed') is True,
            'peers': [str(p) for p in data.get('peers') or [] if isinstance(p, str)],  # F95: other Homes' links
            'tailscale': data.get('tailscale') is not False}  # F95: look for Homes on the tailnet too


def save_registry(reg: dict) -> None:
    f = registry_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + '.tmp')
    tmp.write_text(json.dumps(reg, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, f)


def home_token() -> str:
    """Home's token: <config>/home.token, made there (owner-only) the first time."""
    f = config_dir() / 'home.token'
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


def is_project(p: Path) -> bool:
    return (p / 'runner.toml').is_file()


def scanned(reg: dict) -> list[Path]:
    """Each folder directly in a scanned folder (~/repos) that holds a runner.toml."""
    out = []
    for base in reg['scan']:
        b = Path(base).expanduser()
        try:
            out += [p for p in sorted(b.iterdir()) if p.is_dir() and is_project(p)]
        except OSError:
            continue
    return out


def projects(reg: dict | None = None) -> list[Path]:
    """The projects Home lists: scanned ones not hidden, then those added by hand, once each, by name."""
    reg = reg or load_registry()
    hidden = {str(Path(p).expanduser().resolve()) for p in reg['hidden']}
    seen: dict[str, Path] = {}
    for p in scanned(reg) + [Path(x).expanduser() for x in reg['projects']]:
        r = p.resolve()
        if str(r) not in hidden and str(r) not in seen:
            seen[str(r)] = r
    return sorted(seen.values(), key=lambda p: (p.name.lower(), str(p)))


def add_project(path: str) -> tuple[bool, str]:
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return False, f'{p} is not a folder'
    if not (is_project(p) or (p / '.git').exists()):
        return False, f'{p} is not a project: no runner.toml and no git repository there'
    reg = load_registry()
    reg['hidden'] = [h for h in reg['hidden'] if Path(h).expanduser().resolve() != p]
    if str(p) not in reg['projects']:
        reg['projects'].append(str(p))
    save_registry(reg)
    return True, f'Home lists {p.name} ({p})'


def remove_project(path: str) -> tuple[bool, str]:
    """Unlist a project: one added by hand is dropped, a scanned one is hidden."""
    p = Path(path).expanduser().resolve()
    reg = load_registry()
    was = p in projects(reg)
    reg['projects'] = [x for x in reg['projects'] if Path(x).expanduser().resolve() != p]
    if p in [s.resolve() for s in scanned(reg)] and str(p) not in reg['hidden']:
        reg['hidden'].append(str(p))
    save_registry(reg)
    return (True, f'Home no longer lists {p.name}') if was else (False, f'Home did not list {p}')


def keys(roots: list[Path]) -> dict[str, Path]:
    """{key: root}: a project's key in Home's addresses is its folder name, made safe, -2, -3… when taken."""
    out: dict[str, Path] = {}
    for r in roots:
        base = re.sub(r'[^A-Za-z0-9._-]+', '-', r.name).strip('-.') or 'project'
        k, n = base, 1
        while k in out:
            n += 1
            k = f'{base}-{n}'
        out[k] = r
    return out


# --- what each project is doing ---------------------------------------------------------------------------------

def child_env() -> dict:
    """The environment the runner's commands get from Home: none of a slot's or a session's markers."""
    env = dict(os.environ)
    for k in ('AGENT_RUNNER_REPO', 'AGENT_RUNNER_CONFIG', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_WORKTREE',
              'AGENT_RUNNER', 'AGENT_RUNNER_CONTROL', 'CLAUDECODE', 'CLAUDE_CODE_ENTRYPOINT'):
        env.pop(k, None)
    return env


def runner(root: Path, argv: list[str], timeout: float = 90.0) -> sp.CompletedProcess:
    from agent_runner.config import runner_cmd
    env = child_env()
    if not argv:  # B145: bare agent-runner from Home is its start button; the run logs who started it
        env['AGENT_RUNNER_STARTED_BY'] = 'Home start'
    return sp.run([*runner_cmd(), *argv], cwd=str(root), stdin=sp.DEVNULL, capture_output=True, text=True,
                  encoding='utf-8', errors='replace', timeout=timeout, env=env)


_NEEDS: dict[str, tuple[float, int | None, list[str]]] = {}


def needs_said(root: Path, call=runner) -> tuple[int | None, list[str]]:
    """What in the project waits on the person, from `needs`: (how many, None when it cannot say; its 'ID -
    what to do' lines). Kept NEEDS_TTL seconds, since a phone polls."""
    hit = _NEEDS.get(str(root))
    if hit and time.monotonic() - hit[0] < NEEDS_TTL:
        return hit[1], hit[2]
    n: int | None = None
    items: list[str] = []
    try:
        r = call(root, ['needs'], 30.0)
        ls = [l for l in r.stdout.strip().splitlines() if l.strip()]
        last = ls[-1] if ls else ''
        if not r.returncode:
            m = re.match(r'(\d+|One|one) things? needs? you', last)
            n = 0 if last.startswith('Nothing') else (int(m[1]) if m and m[1].isdigit() else 1 if m else None)
            items = ls[:-1] if n else []
    except (OSError, sp.SubprocessError):
        pass
    _NEEDS[str(root)] = (time.monotonic(), n, items)
    return n, items


def needs_count(root: Path, call=runner) -> int | None:
    """How many things in the project wait on the person (`needs_said`)."""
    return needs_said(root, call)[0]


def run_link(root: Path) -> tuple[int, str] | None:
    """(port, token) of the page the project's run serves (its <notes>/web.url), None while it serves none."""
    from agent_runner.cmds import run_info
    if not run_info(root).get('up'):
        return None
    try:
        from agent_runner.config import Config
        us = Config(root).notes('web.url').read_text(encoding='utf-8').split()
        u = urlsplit(us[0])
        t = (parse_qs(u.query).get('t') or [''])[0]
        return (int(u.port), t) if u.port and t else None
    except (OSError, SystemExit, ValueError, KeyError, TypeError, IndexError):
        return None


def site_links(root: Path, serves=None, https=None) -> list[str]:
    """B146: the run app of the project at `root` through the device site, Runner Home serving on this device:
    http://HOST:PORT/p/KEY/?t=HOME_TOKEN, by hostname then by LAN address, so one device address switches between
    runners. [] when nothing on the device routes /p/KEY: no Home token yet, Home does not answer on its port
    (a run's page may hold it), or Home does not list the project. Makes no file (the token is only read)."""
    try:
        token = (config_dir() / 'home.token').read_text(encoding='utf-8').strip()
        if not token:
            return []
        from agent_runner.config import main_checkout
        try:
            me = main_checkout(Path(root)).resolve()
        except (OSError, SystemExit):
            me = Path(root).resolve()
        reg = load_registry()
        key = next((k for k, r in keys(projects(reg)).items() if r == me), None)
        if key is None or not (serves or serving)(reg['port']):
            return []
        from agent_runner.web import https_first, page_urls
        # F134: Home's Tailscale Serve https address first, at /p/KEY/ (Talk's mic needs https)
        return https_first([u.replace('/?t=', f'/p/{key}/?t=', 1) for u in page_urls(reg['port'], token)], https)
    except (OSError, ValueError, SystemExit):
        return []


def why_closed(root: Path) -> str:
    """F165: why Home does not open the page of the run at `root`, which only Home can, and what opens it."""
    reg = load_registry()
    if serving(reg['port']):
        from agent_runner.config import main_checkout
        try:
            root = main_checkout(Path(root))
        except (OSError, SystemExit):
            pass
        return f'Runner Home does not list this project: `agent-runner home add {root}` opens it there'
    if home_on():
        return 'Runner Home is down, and only Home opens it: `agent-runner home install` starts Home again'
    return ('nothing opens it: only Runner Home can, and Home is not installed; `agent-runner home install` gives '
            'every project on this device one address')


def project_row(key: str, root: Path, info=None, facts=None, needs=needs_said) -> dict:
    """What Home shows of one project: {'key', 'name', 'root', 'state' (running|idle|off), 'paused',
    'stopping', 'slots', 'running' (task ids), 'left', 'needs' (how many), 'asks' (their 'ID - what to do'
    lines), 'page' (its run app through Home, or '')}."""
    n, asks = needs(root)
    from agent_runner import cmds
    run = (info or cmds.run_info)(root) or {}
    # B135: Home only asks whether there is a link, so no Tailscale lookup per project on each refresh
    # B146: nor the device site lookup (Home is the device site; it would ask itself)
    f = facts(root, run) if facts else cmds.run_facts(root, run, https=lambda port, token: [],
                                                       site=lambda r: [f'p/{key}/'])
    up = bool(run.get('up'))
    running = sorted(str(v) for v in (run.get('running') or {}).values() if v) if up else []
    words = str(run.get('state') or '')
    return {'key': key, 'name': root.name, 'root': str(root),
            'state': 'off' if not up else 'running' if running else 'idle',
            'paused': up and 'paused' in words, 'stopping': bool(f.get('stopping')),
            'slots': run.get('slots') if up and isinstance(run.get('slots'), int) else None,
            'running': running, 'left': f.get('left'), 'needs': n, 'asks': asks[:5],
            'page': f'p/{key}/' if up and f.get('link') else ''}


def project_rows(reg: dict | None = None, row=project_row) -> list[dict]:
    ks = keys(projects(reg))
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(lambda kv: row(*kv), ks.items()))


ACTIONS = {'start': [], 'stop': ['stop'], 'pause': ['pause'], 'resume': ['pause', '--off'], 'slots': ['slots']}


def action_argv(name: str, arg: str = '') -> list[str] | None:
    """The runner command a Home button runs, None for one it does not take: start is bare agent-runner (no
    terminal there, so the run starts in the background), slots takes +1, -1 or a count."""
    if name not in ACTIONS:
        return None
    if name == 'slots':
        arg = str(arg).strip()
        if not re.fullmatch(r'[+-]1|[1-9]\d?', arg):
            return None
        return ['slots', arg]
    return list(ACTIONS[name])


def run_action(root: Path, name: str, arg: str = '', call=runner) -> dict:
    """Run a Home button's command in project `root`: {'ok', 'out'}."""
    argv = action_argv(name, arg)
    if argv is None:
        return {'ok': False, 'out': f'no such action: {name} {arg}'.strip()}
    try:
        r = call(root, argv, 120.0 if name == 'start' else 60.0)
    except (OSError, sp.SubprocessError) as e:
        return {'ok': False, 'out': f'{name}: {e}'}
    _NEEDS.pop(str(root), None)
    out = (r.stdout + ('\n' + r.stderr if r.stderr.strip() else '')).strip()
    return {'ok': r.returncode == 0, 'out': out[-2000:] or f'{name}: done'}


# --- the page ---------------------------------------------------------------------------------------------------

def home_page() -> bytes:
    """F134: Home's own page is the run app (web_page.html, its look and tokens) in Home mode: the project
    switcher and the All projects view (every project's row and buttons, add project, Devices) with no run
    behind it. Opening a project moves to /p/KEY/, the same app with that project's run."""
    from agent_runner.web import page_html
    return page_html(home=True)



# --- the server -------------------------------------------------------------------------------------------------

HOP = {'connection', 'keep-alive', 'transfer-encoding', 'te', 'trailer', 'upgrade', 'proxy-connection'}


class HomeHandler(BaseHTTPRequestHandler):
    server: 'HomeServer'
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a) -> None:
        pass

    def allowed(self) -> bool:
        q = parse_qs(urlsplit(self.path).query)
        got = (q.get('t') or [''])[0] or self.headers.get('X-Token', '') or self.path_token()
        return bool(got) and hmac.compare_digest(got.encode(), self.server.token.encode())

    def path_token(self) -> str:
        """F107: a run's terminal tab is /p/KEY/t/TOKEN/NAME/...: ttyd's page asks for its token and its socket
        by paths under its own, without the query, so the token rides in the path (as on the run's own ttyd)."""
        parts = urlsplit(self.path).path.split('/')  # ['', 'p', KEY, 't', TOKEN, NAME, ...]
        return parts[4] if len(parts) > 5 and parts[1] == 'p' and parts[3] == 't' else ''

    def send(self, code: int, body: bytes | str | dict, ctype: str = 'application/json; charset=utf-8') -> None:
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()
        self.wfile.write(data)

    def body(self) -> bytes:
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        return self.rfile.read(n) if n > 0 else b''

    def route(self, method: str) -> None:
        path = urlsplit(self.path).path
        if not self.allowed():
            return self.send(403, {'ok': False, 'out': 'Runner Home needs its token: open the link '
                                   '`agent-runner home status` prints (…/?t=TOKEN)'})
        if method == 'GET' and path.endswith('/' + home_screen.MANIFEST):  # B179
            return self.manifest(path)
        if path == '/p' or path.startswith('/p/'):
            return self.proxy(method)
        if method == 'GET' and (png := home_screen.icon_at(path)):
            return self.send(200, png, 'image/png')
        if method == 'GET' and path in ('/', '/index.html'):
            return self.send(200, home_page(), 'text/html; charset=utf-8')
        if path in ('/device', '/devices') or path.startswith(('/dev/', '/vitals/')):  # F95: Device Vitals
            code, out, ctype = self.server.vitals.handle(method, path, parse_qs(urlsplit(self.path).query),
                                                         self.body() if method == 'POST' else b'')
            return self.send(code, out, ctype)
        if method == 'GET' and path == '/projects':
            return self.send(200, {'ok': True, 'machine': socket.gethostname(), 'projects': self.server.rows()})
        if method == 'POST' and path in ('/act', '/add', '/remove'):
            try:
                req = json.loads(self.body() or b'{}')
                if not isinstance(req, dict):
                    raise ValueError('the body must be an object')
            except ValueError as e:
                return self.send(400, {'ok': False, 'out': f'bad request: {e}'})
            if path == '/add':
                ok, out = add_project(str(req.get('path') or ''))
                return self.send(200, {'ok': ok, 'out': out})
            root = self.server.project(str(req.get('project') or ''))
            if root is None:
                return self.send(404, {'ok': False, 'out': f'no such project: {req.get("project")}'})
            if path == '/remove':
                ok, out = remove_project(str(root))
                return self.send(200, {'ok': ok, 'out': out})
            return self.send(200, self.server.act(root, str(req.get('name') or ''), str(req.get('arg') or '')))
        self.send(404, {'ok': False, 'out': f'no such page: {path}'})

    def manifest(self, path: str) -> None:
        """B179: Home's root is the app's scope; `p` names the project whose run app the icon opens on. Under /p/KEY/
        the answer is Home's too, never the run's, which holds the run's own token."""
        m = re.fullmatch(r'(/p/([^/]+))?/' + re.escape(home_screen.MANIFEST), path)
        if not m:
            return self.send(404, {'ok': False, 'out': f'no such page: {path}'})
        key = m[2] or (parse_qs(urlsplit(self.path).query).get('p') or [''])[0]
        key = key if key and self.server.project(key) else ''
        self.send(200, home_screen.manifest(key or 'Runner Home', self.server.token, key, '../../' if m[2] else './'),
                  home_screen.MANIFEST_TYPE)

    def do_GET(self) -> None:
        self.counted('GET')

    def do_POST(self) -> None:
        self.counted('POST')

    def counted(self, method: str) -> None:
        """B165: the request counts as open until it is answered (a terminal tunnel: until it ends). One that
        comes as Home restarts is not run: a GET is dropped unanswered, so the browser asks again (an error answer
        would end its event stream for good); a POST, which it would not send again, is told so."""
        if not self.server.enter():
            self.close_connection = True
            if method == 'POST':
                self.body()
                self.send(503, {'ok': False, 'out': 'Runner Home is restarting on a new version; try again'})
            return
        try:
            self.route(method)
        finally:
            self.server.leave()

    def proxy(self, method: str) -> None:
        """/p/KEY/REST: the project's run app. The request goes on to the run's own page (127.0.0.1, its port)
        with the run's token in place of Home's, and the answer streams back as it comes (its events too)."""
        u = urlsplit(self.path)
        parts = u.path.split('/', 3)  # ['', 'p', KEY, REST]
        key = parts[2] if len(parts) > 2 else ''
        if len(parts) < 4:  # /p/KEY: the page's calls are relative to /p/KEY/
            self.send_response(302)
            self.send_header('Location', f'/p/{key}/?{u.query}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        root = self.server.project(key)
        if root is None:
            return self.send(404, {'ok': False, 'out': f'no such project: {key}'})
        link = self.server.link(root)
        if link is None:
            return self.send(502, '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                             '<meta name="color-scheme" content="light dark"><title>Runner Home</title>'
                             f'<p>{root.name} has no run up, so it has no run app to open. '
                             f'<a href="/?{u.query}">Back to Home</a> to start it.</p>', 'text/html; charset=utf-8')
        port, token = link
        if parts[3].startswith('t/'):
            return self.terminal(root, port, token, parts[3], u.query)
        query = [(k, v) for k, vs in parse_qs(u.query, keep_blank_values=True).items() if k != 't' for v in vs]
        target = '/' + parts[3] + '?' + urlencode([('t', token), *query])
        self.forward(method, root, port, target)

    def terminal(self, root: Path, port: int, token: str, rest: str, query: str) -> None:
        """F107: /p/KEY/t/TOKEN/NAME/REST is session NAME's terminal tab: the run's ttyd for it (started on demand
        by the run's /terminal/NAME, on the run's port+N), at its own path, its WebSocket included."""
        bits = rest.split('/', 3)  # ['t', TOKEN, NAME, REST]
        if len(bits) < 4:
            return self.send(404, {'ok': False, 'out': 'a terminal address ends in a slash: t/TOKEN/NAME/'})
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        try:
            conn.request('GET', f'/terminal/{bits[2]}?' + urlencode([('t', token)]))
            got = json.loads(conn.getresponse().read() or b'{}')
        except (OSError, ValueError) as e:
            return self.send(502, {'ok': False, 'out': f'{root.name}\'s run page did not answer: {e}'})
        finally:
            conn.close()
        if not isinstance(got, dict) or not got.get('ok') or not got.get('port') or not got.get('path'):
            out = got.get('out') if isinstance(got, dict) else ''
            return self.send(502, f'<pre>{_xml(str(out or "no terminal for " + bits[2]))}</pre>',
                             'text/html; charset=utf-8')
        rest_q = urlencode([(k, v) for k, vs in parse_qs(query, keep_blank_values=True).items() if k != 't'
                            for v in vs])  # Home's token stays at Home
        target = str(got['path']).rstrip('/') + '/' + bits[3] + (f'?{rest_q}' if rest_q else '')
        if 'websocket' in self.headers.get('Upgrade', '').lower():
            return self.tunnel(root, int(got['port']), target)
        self.forward(self.command, root, int(got['port']), target)

    def tunnel(self, root: Path, port: int, target: str) -> None:
        """A WebSocket upgrade: the request goes on as it came (its path swapped), then bytes flow both ways
        until either side ends."""
        try:
            up = socket.create_connection(('127.0.0.1', port), timeout=10)
        except OSError as e:
            return self.send(502, {'ok': False, 'out': f'{root.name}\'s terminal did not answer: {e}'})
        head = [f'{self.command} {target} HTTP/1.1', f'Host: 127.0.0.1:{port}',
                *(f'{k}: {v}' for k, v in self.headers.items() if k.lower() not in ('host', 'x-token'))]
        self.close_connection = True
        try:
            up.sendall(('\r\n'.join(head) + '\r\n\r\n').encode('latin-1'))
            up.settimeout(None)
        except OSError:
            up.close()
            return

        def browser_to_run() -> None:
            try:
                while data := self.rfile.read1(65536):
                    up.sendall(data)
            except (OSError, ValueError):
                pass
            try:
                up.shutdown(socket.SHUT_WR)
            except OSError:
                pass

        pump = threading.Thread(target=browser_to_run, name='home-ws', daemon=True)
        pump.start()
        try:
            while data := up.recv(65536):
                self.wfile.write(data)
        except OSError:
            pass
        finally:
            up.close()
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            pump.join(timeout=5)

    def forward(self, method: str, root: Path, port: int, target: str) -> None:
        """The request goes on to 127.0.0.1:PORT at TARGET; the answer streams back as it comes."""
        data = self.body()
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP | {'host', 'x-token'}}
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=60)
        try:
            conn.request(method, target, body=data if method == 'POST' else None, headers=headers)
            sock = conn.sock
            r = conn.getresponse()
        except OSError as e:
            conn.close()
            return self.send(502, {'ok': False, 'out': f'{root.name}\'s run page did not answer: {e}'})
        try:
            self.send_response(r.status)
            length = r.getheader('Content-Length')
            for k, v in r.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            if length is None:
                self.send_header('Connection', 'close')
                self.close_connection = True
            self.end_headers()
            if (r.getheader('Content-Type') or '').startswith('text/event-stream'):
                self.server.streams[self] = sock  # B165: Home may end it to restart; the page connects again
            while chunk := r.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
        except OSError:  # the browser or the run went away
            self.close_connection = True
        finally:
            self.server.streams.pop(self, None)
            conn.close()


def package_stamp() -> tuple | None:
    """B165: the package's files on disk (name, mtime, size), which an upgrade changes; None when they cannot
    be read (mid-install)."""
    try:
        return tuple(sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size)
                            for f in Path(__file__).parent.iterdir() if f.is_file())) or None
    except OSError:
        return None


def end_stream(sock: socket.socket) -> None:
    """End an event stream another thread waits on. On Windows a shutdown does not wake that thread; closing the
    handle itself does (F152)."""
    if os_kind() == 'windows':
        socket.close(sock.detach())
    else:
        sock.shutdown(socket.SHUT_RDWR)


class HomeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, token: str, port: int, bind: str = '0.0.0.0', rows=project_rows, act=run_action,
                 link=run_link, roots=projects, vitals=None, stamp=None):
        self.stamp = stamp  # B165: package_stamp, or None: never restarts by itself
        self.started_on = self.seen = stamp() if stamp else None
        self.looked, self.due, self.restart = time.monotonic(), False, False
        self.open_lock, self.open = threading.Lock(), 0  # requests being answered, terminal tunnels included
        self.streams: dict = {}  # of those, the runs' event streams: {handler: its socket to the run}
        self.token, self._rows, self._act, self._link, self._roots = token, rows, act, link, roots
        self.vitals = vitals or home_vitals(self)
        if self.vitals.act is None:
            self.vitals.act = self.act_key  # the vitals page's + slot runs this Home's buttons
        super().__init__((bind, port), HomeHandler)

    def act_key(self, key: str, name: str, arg: str) -> dict:
        """A Home button on a project named by its key (the vitals page's + slot)."""
        root = self.project(key)
        return {'ok': False, 'out': f'no such project: {key}'} if root is None else self.act(root, name, arg)

    def rows(self) -> list[dict]:
        return self._rows()

    def project(self, key: str) -> Path | None:
        return keys(self._roots()).get(key)

    def act(self, root: Path, name: str, arg: str) -> dict:
        return self._act(root, name, arg)

    def link(self, root: Path) -> tuple[int, str] | None:
        return self._link(root)

    def enter(self) -> bool:
        with self.open_lock:
            self.open += not self.restart
            return not self.restart

    def leave(self) -> None:
        with self.open_lock:
            self.open -= 1

    def restart_due(self) -> bool:
        """B165: the package's files are not the ones this server started on, and were the same on two looks, so a
        restart never lands mid-install."""
        if self.stamp and time.monotonic() - self.looked >= LOOK_EVERY:
            self.looked = time.monotonic()
            new = self.stamp()
            self.due = new is not None and new != self.started_on and new == self.seen
            self.seen = new
        return self.due

    def service_actions(self) -> None:
        """B165: between requests (serve_forever calls it, at least twice a second): when the package changed, ask
        for a restart, once, and only with no request or terminal tunnel open. Pages keep an event stream open all
        day, so with only those left they are ended first; each page connects again by itself."""
        super().service_actions()
        if self.restart or not self.restart_due():
            return
        with self.open_lock:
            self.restart = self.open == 0
            ended = list(self.streams.values()) if 0 < self.open <= len(self.streams) else []
        for sock in ended:
            try:
                end_stream(sock)
            except OSError:
                pass
        if self.restart:
            threading.Thread(target=self.shutdown, name='home-restart', daemon=True).start()

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


def home_vitals(srv: HomeServer):
    """F95: the server's Device Vitals (vitals.Vitals): sampling starts with `serve` or the first vitals call;
    its day of samples is kept in Home's config folder."""
    from agent_runner.vitals import Vitals
    return Vitals(srv._roots, config_dir(), peers=lambda: load_registry()['peers'], token=srv.token,
                  tailscale=load_registry()['tailscale'], act=srv.act_key)


def serve_home(token: str, port: int, bind: str = '0.0.0.0', **kw) -> HomeServer:
    """Start a Home server in a daemon thread and return it (port 0: any free port)."""
    srv = HomeServer(token, port, bind, **kw)
    threading.Thread(target=srv.serve_forever, name='runner-home', daemon=True).start()
    return srv


def home_urls(port: int | None = None, https=None) -> list[str]:
    """Home's links, with its token: F134: the Tailscale Serve https addresses for its port first (Talk's mic
    needs https; `https(port, token)`, web.tailscale_https_urls), then by hostname and by LAN address."""
    from agent_runner.web import page_urls, tailscale_https_urls
    port = load_registry()['port'] if port is None else port
    token = home_token()
    plain = page_urls(port, token)
    return [u for u in (https or tailscale_https_urls)(port, token) if u not in plain] + plain


def serve_https_argv(port: int) -> list[str]:
    """F134: the Tailscale Serve command that gives Home on `port` an https address (on port+1, 8771)."""
    return ['tailscale', 'serve', '--bg', f'--https={port + 1}', f'http://127.0.0.1:{port}']


def offer_https(port: int, urls: list[str], call=None, out=print, ask=None, which=None) -> list[str]:
    """F134: with no https link for Home (`urls` all http), offer to set up Tailscale Serve for it: `ask(question)`
    (default: a y/n prompt when stdin is a terminal) says yes, the command runs and the links are read again;
    otherwise say the command. Without tailscale, one line on what https needs. Returns the links to print."""
    if any(u.startswith('https://') for u in urls):
        return urls
    cmd = serve_https_argv(port)
    line = ' '.join(cmd)
    if not (which or shutil.which)('tailscale'):
        out(f"No https link: Talk's mic needs one. With Tailscale installed, `{line}` gives Home one.")
        return urls
    if ask is None and sys.stdin.isatty():
        def ask(q: str) -> bool:
            try:
                return input(q + ' [Y/n] ').strip().lower() in ('', 'y', 'yes')
            except EOFError:
                return False
    if ask and ask(f"Home has no https link (Talk's mic needs one). Run `{line}`?"):
        code, said = (call or sh)(cmd)
        if code == 0:
            got = home_urls(port)
            if not any(u.startswith('https://') for u in got):
                out(f'{line} ran, but tailscale serve status shows no https address for port {port} yet: '
                    f'`agent-runner home status` lists it once it does')
            return got
        out(f'{line} failed: {said}')
        return urls
    out(f"For an https link (Talk's mic needs one), run: {line}")
    return urls


# --- the service ------------------------------------------------------------------------------------------------

def os_kind(platform: str | None = None) -> str:
    p = platform or sys.platform
    return 'windows' if p.startswith('win') else 'macos' if p == 'darwin' else 'linux'


def serve_argv(kind: str | None = None) -> list[str]:
    """What the service runs: the runner's own command, `home serve`. On Windows pythonw.exe beside the
    interpreter, when there is one, so no console window opens at logon."""
    from agent_runner.config import runner_cmd
    argv = runner_cmd()
    if os_kind(kind) == 'windows' and argv[0].lower().endswith('python.exe'):
        w = Path(argv[0]).with_name('pythonw.exe')
        if w.exists():
            argv = [str(w), *argv[1:]]
    return [*argv, 'home', 'serve']


def unit_path(kind: str, home: Path | None = None) -> Path | None:
    """Where the service's file goes: the systemd user unit, the launchd agent's plist; None on Windows (the
    scheduled task lives in Task Scheduler)."""
    home = home or Path.home()
    if kind == 'linux':
        return Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'systemd' / 'user' / f'{SERVICE}.service'
    if kind == 'macos':
        return home / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
    return None


def _xml(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _sd_quote(a: str) -> str:
    return a if re.fullmatch(r'[A-Za-z0-9_@%+=:,./-]+', a) else '"' + a.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _win_quote(a: str) -> str:
    return f'"{a}"' if (' ' in a or not a) else a


def unit_text(kind: str, argv: list[str], log: Path, env: dict | None = None) -> str:
    """The service's definition for `kind`: a systemd user unit, a launchd plist, or (Windows) the command line
    the scheduled task runs."""
    env = env or {}
    if kind == 'linux':
        envs = ''.join(f'Environment={_sd_quote(f"{k}={v}")}\n' for k, v in sorted(env.items()))
        return ('[Unit]\nDescription=agent-runner Home: every project\'s run, one page\n'
                'After=network-online.target\nWants=network-online.target\n\n'
                f'[Service]\nExecStart={" ".join(_sd_quote(a) for a in argv)}\n{envs}'
                'Restart=on-failure\nRestartSec=5\n\n[Install]\nWantedBy=default.target\n')
    if kind == 'macos':
        args = ''.join(f'    <string>{_xml(a)}</string>\n' for a in argv)
        envs = ''.join(f'    <key>{_xml(k)}</key><string>{_xml(v)}</string>\n' for k, v in sorted(env.items()))
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n<dict>\n'
                f'  <key>Label</key><string>{LABEL}</string>\n'
                f'  <key>ProgramArguments</key>\n  <array>\n{args}  </array>\n'
                + (f'  <key>EnvironmentVariables</key>\n  <dict>\n{envs}  </dict>\n' if envs else '')
                + '  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n'
                f'  <key>StandardOutPath</key><string>{_xml(str(log))}</string>\n'
                f'  <key>StandardErrorPath</key><string>{_xml(str(log))}</string>\n'
                '</dict>\n</plist>\n')
    return ' '.join(_win_quote(a) for a in argv)


def service_env() -> dict:
    """What the service needs from this shell: PATH (git, claude), and the settings that move the runs folder
    and Home's config."""
    return {k: os.environ[k] for k in ('PATH', 'AGENT_RUNNER_HOME', 'AGENT_RUNNER_HOME_CONFIG', 'CLAUDE_CODE_TMPDIR',
                                       'CLAUDE_CONFIG_DIR')
            if os.environ.get(k)}  # F95, F144: where the vitals find the session temp folders and the open sessions


def install_commands(kind: str, unit: Path | None, task_cmd: str = '') -> list[list[str]]:
    if kind == 'linux':
        user = os.environ.get('USER') or os.environ.get('LOGNAME') or ''
        return [['systemctl', '--user', 'daemon-reload'],
                ['systemctl', '--user', 'enable', '--now', f'{SERVICE}.service'],
                ['loginctl', 'enable-linger', *([user] if user else [])]]
    if kind == 'macos':
        return [['launchctl', 'unload', str(unit)], ['launchctl', 'load', '-w', str(unit)]]
    return [['schtasks', '/Create', '/TN', SERVICE, '/SC', 'ONLOGON', '/RL', 'LIMITED', '/F', '/TR', task_cmd],
            ['schtasks', '/Run', '/TN', SERVICE]]


def uninstall_commands(kind: str, unit: Path | None) -> list[list[str]]:
    if kind == 'linux':
        return [['systemctl', '--user', 'disable', '--now', f'{SERVICE}.service'],
                ['systemctl', '--user', 'daemon-reload']]
    if kind == 'macos':
        return [['launchctl', 'unload', '-w', str(unit)]]
    # F152: disabled first, so a restart under way (restart_task) cannot start the task again after /End
    return [['schtasks', '/Change', '/TN', SERVICE, '/DISABLE'], ['schtasks', '/End', '/TN', SERVICE],
            ['schtasks', '/Delete', '/TN', SERVICE, '/F']]


ALLOWED_TO_FAIL = {('launchctl', 'unload'), ('schtasks', '/End'), ('schtasks', '/Change')}  # nothing loaded or running yet


def sh(argv: list[str]) -> tuple[int, str]:
    try:
        r = sp.run(argv, capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stderr or r.stdout).strip()
    except (OSError, sp.SubprocessError) as e:
        return 127, str(e)


def serving(port: int, host: str = '127.0.0.1') -> bool:
    """Does Home itself answer on `port` (not a run's page that holds it)? F165: asked for its page, not
    /projects: those rows run commands in every project, so a slow one would read as Home being down."""
    conn = http.client.HTTPConnection(host, port, timeout=3)
    try:
        conn.request('GET', '/?' + urlencode({'t': home_token()}))
        r = conn.getresponse()
        return r.status == 200 and b'Runner Home' in r.read()
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def installed(kind: str | None = None, call=sh) -> bool:
    """Is the service set up, as the service manager itself says (not only its file being there)?"""
    kind = kind or os_kind()
    if kind == 'windows':
        return call(['schtasks', '/Query', '/TN', SERVICE])[0] == 0
    u = unit_path(kind)
    if not (u and u.exists()):
        return False
    if kind == 'linux':
        return call(['systemctl', '--user', 'is-enabled', '--quiet', f'{SERVICE}.service'])[0] == 0
    return call(['launchctl', 'list', LABEL])[0] == 0


def home_on() -> bool:
    """F94: has `home install` turned Home on (and no `uninstall` off since)? Runs read it from the registry,
    with no call to the service manager: then only Home opens a run's page (F165)."""
    try:
        return bool(json.loads(registry_file().read_text(encoding='utf-8')).get('installed'))
    except (OSError, ValueError, AttributeError):
        return False


def mark_installed(on: bool) -> None:
    save_registry({**load_registry(), 'installed': on})


TR_MAX = 261  # the longest command line schtasks /TR takes


def task_command(text: str) -> str:
    """The scheduled task's /TR: the command line itself, or, past schtasks' limit, a launcher file in
    <config> that runs it."""
    if len(text) <= TR_MAX:
        return text
    f = config_dir() / 'home-serve.cmd'
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(f'@echo off\r\n{text}\r\n', encoding='utf-8')
    return f'"{f}"'


def wait_serving(port: int, timeout: float = 8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if serving(port):
            return True
        time.sleep(0.5)
    return False


def install(kind: str | None = None, call=sh, out=print, check=wait_serving, https=None, ask=None) -> int:
    """Set the service up for `kind` (default this OS): its file, the service manager's commands, then wait
    for the page to answer and print the link and a QR code. The service gets the PATH and runs-folder
    settings of this shell (a scheduled task runs with the user's own logon environment)."""
    kind = kind or os_kind()
    mark_installed(True)  # Home is on from now on: a run that is up leaves Home's port within seconds
    reg = load_registry()
    home_token()  # made now, so the link below holds it
    log = config_dir() / 'home.log'
    argv = serve_argv(kind)
    unit = unit_path(kind)
    text = unit_text(kind, argv, log, service_env())
    if unit:
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text(text, encoding='utf-8')
    else:
        text = task_command(text)
    for cmd in install_commands(kind, unit, text):
        code, said = call(cmd)
        if code and tuple(cmd[:2]) not in ALLOWED_TO_FAIL:
            if cmd[0] == 'loginctl':  # without linger it starts at login, not at boot: say so, keep going
                out(f'note: {" ".join(cmd)} failed ({said}): Home starts when you log in, not at boot')
                continue
            out(f'agent-runner home install: {" ".join(cmd)} failed: {said}')
            return 1
    urls = home_urls(reg['port'], https)
    where = {'linux': f'systemd user service {SERVICE} ({unit})', 'macos': f'launchd agent {LABEL} ({unit})',
             'windows': f'scheduled task {SERVICE} (at logon)'}[kind]
    out(f'Runner Home is installed: {where}, on port {reg["port"]}.')
    if not check(reg['port']):
        out(f'It does not answer on port {reg["port"]} yet: a run may hold that port (one on an older '
            f'version gives it up when it next starts; Home keeps trying meanwhile), or see {log}.')
    urls = offer_https(reg['port'], urls, call=call, out=out, ask=ask)
    out('Open it on your phone (same network or Tailscale):\n  ' + '\n  '.join(urls))
    # F134: the QR code holds the https link when there is one (the mic needs it), else the LAN address
    if q := qr_text(urls[0] if urls[0].startswith('https://') else urls[-1]):
        out(q)
    return 0


def uninstall(kind: str | None = None, call=sh, out=print) -> int:
    kind = kind or os_kind()
    unit = unit_path(kind)
    if kind != 'windows' and not (unit and unit.exists()):
        out('Runner Home is not installed')
        return 0
    bad = []
    for cmd in uninstall_commands(kind, unit):
        code, said = call(cmd)
        if code and tuple(cmd[:2]) not in ALLOWED_TO_FAIL:
            bad.append(f'{" ".join(cmd)}: {said}')
    if unit:
        unit.unlink(missing_ok=True)
        if kind == 'linux':
            call(['systemctl', '--user', 'daemon-reload'])
    (config_dir() / 'home-serve.cmd').unlink(missing_ok=True)
    mark_installed(False)
    out('Runner Home is uninstalled' + (f' (but: {"; ".join(bad)})' if bad else '') +
        f'. Its projects and token stay in {config_dir()}; a run serves its own page again from its next start.')
    return 1 if bad and kind == 'windows' else 0


def status(kind: str | None = None, out=print, https=None, on=None, up=None) -> int:
    kind = kind or os_kind()
    reg = load_registry()
    on = installed(kind) if on is None else on
    up = serving(reg['port']) if up is None else up
    out(f'Runner Home: {"installed" if on else "not installed (agent-runner home install)"}, '
        f'{"serving" if up else "not serving"} on port {reg["port"]}')
    if on or up:
        out('  ' + '\n  '.join(home_urls(reg['port'], https)))  # F134: the https link first
    ps = projects(reg)
    out(f'{len(ps)} project{"" if len(ps) == 1 else "s"}: ' + (', '.join(p.name for p in ps) or 'none'))
    return 0


def log_without_console() -> None:
    """Under pythonw.exe (Windows' scheduled task) there is no stdout or stderr, and code that asks them fails
    (F152): they are Home's log then."""
    if sys.stdout is None or sys.stderr is None:
        config_dir().mkdir(parents=True, exist_ok=True)
        f = open(config_dir() / 'home.log', 'a', encoding='utf-8', errors='replace', buffering=1)
        sys.stdout, sys.stderr = sys.stdout or f, sys.stderr or f


def serve(port: int | None = None) -> int:
    log_without_console()
    reg = load_registry()
    port = reg['port'] if port is None else port
    try:
        srv = HomeServer(home_token(), port, stamp=package_stamp if can_restart() else None)
    except OSError as e:
        print(f'agent-runner home: cannot serve on port {port} ({e}): a run may hold it; with Home installed '
              f'it gives the port up', file=sys.stderr)
        return 1
    print(f'Runner Home: {" or ".join(home_urls(srv.server_address[1]))}', flush=True)
    srv.vitals.start()  # F95: the day of samples builds up while Home runs, page open or not
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    if not srv.restart:
        return 0
    return restart_home_task(port) if os_kind() == 'windows' else restart_home()


def can_restart(kind: str | None = None, exe: str | None = None) -> bool:
    """Can this Home restart itself? On Windows, which has no real exec, only as the scheduled task, which runs
    it with pythonw.exe (serve_argv); a `home serve` typed in a terminal runs python.exe and keeps serving."""
    if os_kind(kind) != 'windows':
        return True
    return re.split(r'[\\/]', exe or sys.executable)[-1].lower() == 'pythonw.exe' and home_on()


def restart_home_task(port: int, spawn=None) -> int:
    """F152: Windows: a detached helper, on the package's new files, starts the scheduled task again once this
    process is gone (restart_task). The task stays what runs Home, so `home uninstall` still ends it."""
    from agent_runner import plat
    code = (f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); '
            f'from agent_runner import home; sys.exit(home.restart_task({os.getpid()}, {port}))')
    print('Runner Home: agent-runner changed on disk; restarting its scheduled task', flush=True)
    try:
        # python.exe, hidden: under pythonw.exe, which has no console, each schtasks would open a window
        py = Path(sys.executable).with_name('python.exe')
        (spawn or plat.spawn_detached)([str(py) if py.exists() else sys.executable, '-c', code])
    except OSError as e:
        print(f'agent-runner home: the restart failed: {e}', file=sys.stderr)
        return 1
    return 0


def restart_task(pid: int, port: int, call=sh, gone=None, check=wait_serving, tries: int = 3, wait: float = 15.0,
                 kill=os.kill) -> int:
    """F152, the helper's part: wait for the old Home (`pid`) to exit, and end it by its pid if it hangs: /End on
    the running task could end this helper with it. Then end and run the task until Home answers: a /Run while the task still counts as running is ignored.
    Uninstalled meanwhile: the task is disabled or deleted, /Run fails, and it stops there."""
    from agent_runner import plat
    gone = gone or (lambda p: not plat.alive(p))
    end = time.monotonic() + wait
    while not (exited := gone(pid)) and time.monotonic() < end:
        time.sleep(0.2)
    if not exited:
        try:
            kill(pid, 15)  # SIGTERM; TerminateProcess on Windows
        except OSError:
            pass
    for _ in range(tries):
        call(['schtasks', '/End', '/TN', SERVICE])  # may fail: it has ended by itself
        if call(['schtasks', '/Run', '/TN', SERVICE])[0]:
            return 1
        if check(port, 30.0):  # a first start on new files is slow, and the next try would end it
            return 0
    return 1


def restart_home(exec_=None) -> int:
    """B165: start Home again as it was started, on the package's new files: the same process, so the service
    manager sees no stop. Returns only when that failed (the service manager then starts it again)."""
    print('Runner Home: agent-runner changed on disk; restarting on it', flush=True)
    try:
        (exec_ or os.execv)(sys.executable, sys.orig_argv)
    except OSError as e:
        print(f'agent-runner home: the restart failed: {e}', file=sys.stderr)
    return 1


USAGE = ('agent-runner home [slots|plan] | home install|uninstall|status|list|serve|peers | home add|remove PATH | '
         'home peer add|remove LINK')


def peer_change(op: str, link: str) -> tuple[bool, str]:
    """F95: list (`add`) or unlist another machine's Home by its link (http://host:8770/?t=TOKEN), so this
    Home's Devices list shows that machine too."""
    from agent_runner.vitals import peer_base
    link = link.strip()
    if op == 'add' and not peer_base(link):
        return False, f'not a Home link: {link} (want http://HOST:PORT/?t=TOKEN, as `home status` there prints it)'
    reg = load_registry()
    had = link in reg['peers']
    reg['peers'] = [p for p in reg['peers'] if p != link] + ([link] if op == 'add' else [])
    save_registry(reg)
    if op == 'add':
        return True, f'Home shows {urlsplit(link).hostname} under Devices'
    return (True, f'Home no longer shows {urlsplit(link).hostname}') if had else (False, f'not listed: {link}')


def main(argv: list[str]) -> int:
    cmd, rest = (argv[0], argv[1:]) if argv else ('', [])
    if cmd in ('install', 'uninstall', 'status', 'list') and not rest:
        if cmd == 'list':
            print('\n'.join(str(p) for p in projects()))
            return 0
        return {'install': install, 'uninstall': uninstall, 'status': status}[cmd]()
    if cmd == 'serve' and len(rest) <= 1 and all(a.isdigit() for a in rest):
        return serve(int(rest[0]) if rest else None)
    if cmd == 'peers' and not rest:
        print('\n'.join(load_registry()['peers']) or 'No peers listed: `home peer add LINK` adds another Home')
        return 0
    if cmd == 'peer' and len(rest) == 2 and rest[0] in ('add', 'remove'):
        ok, said = peer_change(rest[0], rest[1])
        print(said, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    if cmd in ('add', 'remove') and len(rest) == 1:
        ok, said = (add_project if cmd == 'add' else remove_project)(rest[0])
        print(said, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    print(USAGE, file=sys.stderr)
    return 2


# --- the QR code ------------------------------------------------------------------------------------------------
# A small QR encoder (byte mode, error correction level L, versions 1-10: up to 271 bytes, room for any link
# Home prints), after Project Nayuki's QR Code generator (MIT). Standard library only, so install shows the
# code on every OS.

_ECC_L = [7, 10, 15, 20, 26, 18, 20, 24, 30, 18]  # EC codewords per block, versions 1-10
_BLOCKS_L = [1, 1, 1, 1, 1, 2, 2, 2, 2, 4]


def _raw_modules(ver: int) -> int:
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        a = ver // 7 + 2
        n -= (25 * a - 10) * a - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_L[ver - 1] * _BLOCKS_L[ver - 1]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(deg: int) -> list[int]:
    res, root = [0] * (deg - 1) + [1], 1
    for _ in range(deg):
        for j in range(deg):
            res[j] = _gf_mul(res[j], root)
            if j + 1 < deg:
                res[j] ^= res[j + 1]
        root = _gf_mul(root, 0x02)
    return res


def _rs_remainder(data: list[int], div: list[int]) -> list[int]:
    res = [0] * len(div)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(div):
            res[i] ^= _gf_mul(c, f)
    return res


def qr_matrix(text: str) -> list[list[bool]] | None:
    """The QR code of `text` as rows of dark (True) modules, without the quiet zone; None when it is too long."""
    data = text.encode('utf-8')
    ver = next((v for v in range(1, 11) if 4 + (8 if v < 10 else 16) + 8 * len(data) <= _data_codewords(v) * 8), 0)
    if not ver:
        return None
    bits: list[int] = []

    def put(val: int, n: int) -> None:
        bits.extend((val >> i) & 1 for i in range(n - 1, -1, -1))
    put(0b0100, 4)
    put(len(data), 8 if ver < 10 else 16)
    for b in data:
        put(b, 8)
    cap = _data_codewords(ver) * 8
    put(0, min(4, cap - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int(''.join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    # error correction, in blocks, interleaved
    nb, ecl = _BLOCKS_L[ver - 1], _ECC_L[ver - 1]
    raw = _raw_modules(ver) // 8
    short, short_len = nb - raw % nb, raw // nb
    div, blocks, k = _rs_divisor(ecl), [], 0
    for i in range(nb):
        dat = words[k:k + short_len - ecl + (0 if i < short else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, div)
        if i < short:
            dat = dat + [0]
        blocks.append(dat + ecc)
    stream = [blk[i] for i in range(len(blocks[0])) for j, blk in enumerate(blocks)
              if i != short_len - ecl or j >= short]
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x: int, y: int, dark: bool) -> None:
        mod[y][x], fn[y][x] = dark, True
    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                if 0 <= cx + dx < size and 0 <= cy + dy < size:
                    setf(cx + dx, cy + dy, max(abs(dx), abs(dy)) not in (2, 4))
    if ver > 1:
        na = ver // 7 + 2
        step = (ver * 4 + na * 2 + 1) // (na * 2 - 2) * 2
        pos = list(reversed([size - 7 - i * step for i in range(na - 1)] + [6]))
        for i, a in enumerate(pos):
            for j, b in enumerate(pos):
                if (i, j) in ((0, 0), (0, na - 1), (na - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        setf(a + dx, b + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mask: int) -> None:
        d = (1 << 3) | mask  # level L is 01
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        fb = ((d << 10) | rem) ^ 0x5412
        g = lambda i: (fb >> i) & 1 == 1  # noqa: E731
        for i in range(6):
            setf(8, i, g(i))
        setf(8, 7, g(6))
        setf(8, 8, g(7))
        setf(7, 8, g(8))
        for i in range(9, 15):
            setf(14 - i, 8, g(i))
        for i in range(8):
            setf(size - 1 - i, 8, g(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, g(i))
        setf(8, size - 8, True)
    format_bits(0)  # reserve the format areas before the data goes in
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        vb = (ver << 12) | rem
        for i in range(18):
            a, b, dark = size - 11 + i % 3, i // 3, (vb >> i) & 1 == 1
            setf(a, b, dark)
            setf(b, a, dark)
    i = 0
    for right in range(size - 1, 0, -2):
        if right <= 6:
            right -= 1
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if (right + 1) & 2 == 0 else vert
                if not fn[y][x] and i < len(stream) * 8:
                    mod[y][x] = (stream[i >> 3] >> (7 - (i & 7))) & 1 == 1
                    i += 1
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
             lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
             lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
             lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]

    def masked(m: int) -> list[list[bool]]:
        return [[mod[y][x] ^ (not fn[y][x] and masks[m](x, y)) for x in range(size)] for y in range(size)]

    def penalty(g: list[list[bool]]) -> int:
        p = 0
        for line in g + [list(c) for c in zip(*g)]:
            run = 1
            for a, b in zip(line, line[1:]):
                run = run + 1 if a == b else 1
                p += 3 if run == 5 else 1 if run > 5 else 0
        p += 3 * sum(g[y][x] == g[y][x + 1] == g[y + 1][x] == g[y + 1][x + 1]
                     for y in range(size - 1) for x in range(size - 1))
        dark = sum(map(sum, g))
        return p + (abs(dark * 20 - size * size * 10) + size * size - 1) // (size * size) * 10
    best, best_p = 0, None
    for m in range(8):
        format_bits(m)
        pm = penalty(masked(m))
        if best_p is None or pm < best_p:
            best, best_p = m, pm
    format_bits(best)
    return masked(best)


def qr_text(text: str, ansi: bool | None = None) -> str:
    """The QR code of `text` for a terminal, two rows per line in half blocks, with a quiet zone. With `ansi`
    (stdout a terminal) it is drawn black on white whatever the terminal's colours; without, light modules are
    the drawn ones, which reads on a dark terminal."""
    m = qr_matrix(text)
    if m is None:
        return ''
    ansi = sys.stdout.isatty() if ansi is None else ansi
    q = 2
    n = len(m) + 2 * q
    g = [[False] * n for _ in range(q)] + [[False] * q + r + [False] * q for r in m] + [[False] * n for _ in range(q + 1)]
    out = []
    for y in range(0, n, 2):
        top, bot = g[y], g[y + 1]
        if ansi:  # dark modules drawn in black on a white background
            row = ''.join(' ▀▄█'[a + 2 * b] for a, b in zip(top, bot))
            out.append(f'\x1b[30;107m{row}\x1b[0m')
        else:  # light modules drawn
            out.append(''.join(' ▀▄█'[(not a) + 2 * (not b)] for a, b in zip(top, bot)))
    return '\n'.join(out)
