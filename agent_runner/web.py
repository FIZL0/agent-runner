"""F66: the run page on the web. A run serves it from this machine (`[run] web`, on by default) on
`[run] web_port` (8770), bound to every interface so a phone on the LAN or Tailscale reaches it. F94: with Runner
Home installed and that port taken, on a free port instead, which Runner Home routes to.

    GET  /?t=TOKEN               F79: the page (web_page.html), the run app: a chat app over F74's model, light
                                 and dark by the browser's setting, laid out for a phone and a desktop; F81: it
                                 opens /term instead when this browser last chose it, or `[ui] web` = "terminal"
    GET  /term?t=TOKEN           F81: the terminal-style page (web_term.html, F75's page) over the same model, in
                                 `[ui] theme`; its App view (T) and the run app's Terminal view switch between them
    GET  /snapshot?t=TOKEN       the run page model's snapshot, as JSON, with the machine's name and each
                                 concept's options (`run_snapshot`)
    GET  /events?t=TOKEN         the same snapshot over server-sent events, sent again whenever it changes
    POST /act?t=TOKEN            {"name": ACTION, "args": {...}}: one of `ui_model.ACTIONS` (plan add, plan edit,
                                 drop, shelve, release, chat, answer, take, move, unpark; F93 `talk`, the Talk
                                 view's words to its own control session), its result as JSON
    GET  /terminal/NAME?t=TOKEN  where slot NAME's (or c1's, or cN's) own terminal is served by ttyd (`attach NAME`),
                                 started on demand; without ttyd, how to install it (on Windows, the feed only)
    GET  /feed/NAME?t=TOKEN      F74: session NAME's transcript as say/you/tool/out entries (`ui_model.feed`)
    GET  /concept/ID?t=TOKEN     F74: concept ID's local page copy (<notes>/concepts/ID.html), sandboxed
    GET  /diff/NAME?t=TOKEN      F75: slot NAME's diff so far (`slot_diff`), for its diff tab
    POST /upload?t=TOKEN&name=N  F79: an attachment (the body, as is) kept under <notes>/uploads; its path on this
                                 machine comes back, for the message that hands it to a session

Every request carries the token (`?t=`, or an `X-Token` header): the page can type into sessions, so one without
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
TERM = Path(__file__).with_name('web_term.html')  # F81: the terminal-style page
TICK = 2.0  # s between snapshots the events stream compares
PING = 15.0  # s of no change before the stream sends a keep-alive comment
TTYD_INSTALL = ('ttyd is not installed, so the terminal tab cannot show a session\'s terminal. Install it on this machine '
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


def serve_https_urls(status: dict, port: int, token: str) -> list[str]:
    """B130: the https addresses `tailscale serve status --json` (parsed as `status`) proxies to this machine's
    `port`, with the token: `https://HOST:PORT/?t=TOKEN` for each Web entry whose handler proxies there."""
    out = []
    for hostport, web in ((status or {}).get('Web') or {}).items():
        for h in ((web or {}).get('Handlers') or {}).values():
            m = re.fullmatch(r'https?://(?:127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0):(\d+)/?', str((h or {}).get('Proxy', '')))
            if m and int(m.group(1)) == port:
                host, _, p = hostport.rpartition(':')
                if host and ((status.get('TCP') or {}).get(p) or {}).get('HTTPS') is True:
                    out.append(f'https://{host}' + ('' if p == '443' else f':{p}') + f'/?t={token}')
                break
    return out


def tailscale_https_urls(port: int, token: str, run=sp.run) -> list[str]:
    """B130: the https addresses Tailscale Serve gives the page on `port` ([] without tailscale or a serve for
    it). Safari's mic needs a secure context, so these come first where the page's address is printed."""
    if run is sp.run and not shutil.which('tailscale'):
        return []
    try:
        r = run(['tailscale', 'serve', 'status', '--json'], capture_output=True, text=True, timeout=5)
        return serve_https_urls(json.loads(r.stdout or '{}'), port, token) if r.returncode == 0 else []
    except (OSError, ValueError, sp.SubprocessError):
        return []


def page_urls(port: int, token: str) -> list[str]:
    """The page's addresses: by hostname, then by LAN address when there is one."""
    return [page_url(port, token)] + ([page_url(port, token, ip)] if (ip := lan_ip()) else [])


def url_file() -> Path:
    return S.C.notes('web.url')


def page_line() -> str:
    """`run page: URL` while a run serves the page (what `status` prints), else ''. B130: a Tailscale Serve https
    address for its port comes first (Safari's mic needs https); <notes>/web.url keeps the http ones, which Home
    reads its port from."""
    try:
        if S.run_up() and (us := url_file().read_text(encoding='utf-8').split()):
            u = urlsplit(us[0])
            if u.port and (t := (parse_qs(u.query).get('t') or [''])[0]):
                us = [x for x in tailscale_https_urls(u.port, t) if x not in us] + us
            return f'run page: {us[0]}' + (f' (or {us[1]})' if len(us) > 1 else '')
    except (OSError, ValueError):
        pass
    return ''


# --- c1 and the terminals ---------------------------------------------------------------------------------------

def socket_of(name: str) -> str:
    """C26: the attach socket of session `name` (s2, c1, c6) as a path, '' when it has none (not up, Windows)."""
    try:
        from agent_runner.attach import session_socket
        sock = session_socket(name)
        return str(sock) if sock else ''
    except Exception:  # noqa: BLE001 - no notes dir
        return ''


FEED_ONLY = ('On Windows {name} runs in a hidden console, so it has no terminal to show here: its feed and its '
             'session link show it.')


def terminal_fallback(name: str) -> dict:
    """F74: the terminal tab without ttyd: how to install ttyd (`mode` 'install'; C24: ttyd is the only Terminal
    view, and the chat works meanwhile); on Windows the feed only."""
    if U.terminal_mode() == 'feed':
        return {'ok': False, 'mode': 'feed', 'out': FEED_ONLY.format(name=name), 'feed': f'feed/{name}'}
    return {'ok': False, 'mode': 'install', 'feed': f'feed/{name}',
            'out': TTYD_INSTALL + f' Until then, the chat shows {name} and takes your messages.'}


WEB_REFUSED = {'keys'}  # C24: actions the web does not take (typing into a pane went with the built-in view)


class ActsOnce:
    """F137: the page's outbox sends each action with a client id (`cid`) and sends it again after a drop or a
    reload, so an action whose id the server has run already answers with its first result instead of running
    twice (a `new_control` sent twice would start two chats). A copy that comes while the first still runs waits
    for it. The last KEEP ids are kept, in memory: a restarted run page forgets them."""
    KEEP = 500
    WAIT = 300.0  # s a copy waits for the first to finish

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: dict[str, list] = {}  # cid -> [done Event, result]

    def run(self, cid: str, fn) -> dict:
        if not cid:
            return fn()
        with self.lock:
            got = self.seen.get(cid)
            first = got is None
            if first:
                got = self.seen[cid] = [threading.Event(), None]
                while len(self.seen) > self.KEEP:
                    self.seen.pop(next(iter(self.seen)))
        if not first:
            got[0].wait(self.WAIT)
            if got[1] is None:
                return {'ok': False, 'code': 1, 'out': 'that action is still running', 'argv': [], 'again': True}
            return {**got[1], 'again': True}
        try:
            got[1] = fn()
        except BaseException:
            with self.lock:  # it did not finish: a later copy runs it
                self.seen.pop(cid, None)
            raise
        finally:
            got[0].set()
        return got[1]

CONTROL_N = re.compile(r'\bcontrol (\d+)\b')  # F93: the number `control --new` prints for the session it opened


def talk(text: str, to: str = '') -> dict:
    """F93: the Talk view's words (heard or typed) to its control session: to `to` (cN, its live Talk session)
    with the spoken-reply reminder (`talk_message`), else a new control session titled Talk whose first message
    says how to answer (`talk_ask`). The result's 'session' is where they went ('' when it cannot tell)."""
    from agent_runner.control import talk_ask, talk_message
    text = str(text or '').strip()
    if not text:
        return {'ok': False, 'code': 2, 'out': 'talk: nothing was said', 'argv': [], 'session': ''}
    if re.fullmatch(r'c\d+', to or ''):
        r = U.chat_to(talk_message(text), to)
        if r.get('ok'):
            return {**r, 'session': to}
    r = U.new_control(talk_ask(text))
    m = CONTROL_N.search(r.get('out') or '')
    return {**r, 'session': f'c{m[1]}' if r.get('ok') and m else ''}


U.ACTIONS['talk'] = talk  # F93: the run page's Talk view


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
    """One ttyd per session, started the first time its tab opens, on web_port+1, +2, …; each serves only under
    /t/TOKEN/NAME/, so the address is as secret as the page's. C26: it runs `attach NAME` for each browser,
    a client of the session's own socket (F88) like any other, so watching it moves no other client."""

    def __init__(self, token: str, port: int, bind: str):
        self.token, self.port, self.bind = token, port, bind
        self.procs: dict[str, tuple[sp.Popen, int, str]] = {}
        self.lock = threading.Lock()

    def argv(self, name: str, sock: str, port: int) -> list[str]:
        from agent_runner.config import runner_cmd
        return ['ttyd', '-W', '-p', str(port), *(['-i', self.bind] if self.bind not in ('', '0.0.0.0') else []),
                '-b', f'/t/{self.token}/{name}', *runner_cmd(), 'attach', name]

    def open(self, name: str) -> dict:
        if U.terminal_mode() == 'feed' or not shutil.which('ttyd'):
            return terminal_fallback(name)
        sock = socket_of(name)
        if not sock:
            return {'ok': False, 'mode': 'feed', 'feed': f'feed/{name}',
                    'out': f'{name} is not up, so there is nothing for ttyd to show.'}
        with self.lock:
            p = self.procs.get(name)
            if p and p[0].poll() is None and p[2] == sock:
                port = p[1]
            else:
                if p and p[0].poll() is None:
                    p[0].terminate()
                self.procs.pop(name, None)
                used = {v[1] for v in self.procs.values() if v[0].poll() is None}
                port = next(x for x in range(self.port + 1, self.port + 200) if x not in used)
                proc = sp.Popen(self.argv(name, sock, port), cwd=str(S.ROOT), stdin=sp.DEVNULL, stdout=sp.DEVNULL,
                                stderr=sp.PIPE, start_new_session=True)
                try:  # one that cannot start (its port taken) ends at once: say so, not a dead frame
                    err = proc.communicate(timeout=0.8)[1].decode(errors='replace').strip()
                    return {'ok': False, 'out': f'ttyd for {name} ended at once (port {port}): {err[-300:]}'}
                except sp.TimeoutExpired:
                    pass
                self.procs[name] = (proc, port, sock)
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
                    self.last = json.dumps(with_chat_order(self.make()), ensure_ascii=False)
                except Exception as e:  # noqa: BLE001 - a bad read shows on the page, it does not end the stream
                    self.last = json.dumps({'error': f'{type(e).__name__}: {e}'})
                self.at = time.monotonic()
            return self.last


def web_view() -> str:
    """F81: `[ui] web`, the view the run page's link opens: 'app' or 'terminal' ('app' with no project)."""
    try:
        v = S.C.raw.get('ui', {}).get('web', 'app')
    except Exception:  # noqa: BLE001 - no project initialised: the default
        return 'app'
    from agent_runner.config import WEB_VIEWS
    return v if v in WEB_VIEWS else 'app'


def page_html(view: str | None = None) -> bytes:
    """F79: the run app. Its light and dark looks follow the browser's setting (`[ui] theme` is the terminal
    UI's). F81: `[ui] web` (or `view`) goes into WEB_VIEW, for a browser that never chose a view."""
    return PAGE.read_text(encoding='utf-8').replace(
        "/*WEB_VIEW*/'app'", json.dumps(view or web_view()), 1).encode('utf-8')


def term_html(name: str | None = None) -> bytes:
    """F81: the terminal-style page (web_term.html, F75's page), in theme `name` (default `[ui] theme`): its tokens in
    style#theme, and every theme's in THEMES for the page's picker (t), one table with the terminal UI."""
    from agent_runner import theme as TH
    name = TH.checked(name or TH.configured())
    themes = TH.all_resolved()
    css = ':root{' + ';'.join(f'--{k}:{v}' for k, v in themes[name].items() if k != 'mode') + \
        f';color-scheme:{"light" if themes[name]["mode"] == "light" else "dark"}}}'
    data = json.dumps({'default': name, 'themes': themes}).replace('</', '<\\/')
    page = TERM.read_text(encoding='utf-8').replace('/*THEME_CSS*/', css, 1)
    return page.replace('/*THEMES*/{"default":"ryha","themes":{}}', data, 1).encode('utf-8')


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


TTYD_PACKAGES = (('pacman', 'sudo pacman -S ttyd'), ('apt', 'sudo apt install ttyd'), ('dnf', 'sudo dnf install ttyd'),
                 ('zypper', 'sudo zypper install ttyd'), ('brew', 'brew install ttyd'))


def ttyd_install_cmd(which=shutil.which) -> str:
    """B120: the command that installs ttyd here, from the first package manager found ('' when none is)."""
    return next((cmd for tool, cmd in TTYD_PACKAGES if which(tool)), '')


def with_extras(snap: dict) -> dict:
    """F79: what the run app shows beyond the snapshot: this machine's name, and each concept's options."""
    snap['machine'] = socket.gethostname()
    if snap.get('terminal_mode') == 'install':
        snap['ttyd_install'] = ttyd_install_cmd()  # B120: the page's one line on how to get the terminal tab
    for c in snap.get('concepts') or []:
        c['options'] = concept_options(c.get('copy', ''))
    return snap


CHAT_ORDER_FILE = 'chat_order.json'  # F133: the sidebar's chat order and pins, in the notes dir


def chat_list(names: list[str], saved: dict | None) -> list[str]:
    """F133: the Chats list in its shown order: the pinned chats first (in their saved order), then chats the saved
    order does not know yet (new ones, just under the pins), then the rest in the saved order. A chat that is gone
    (not in `names`) drops out; with nothing saved the list stays as `names` gives it."""
    saved = saved if isinstance(saved, dict) else {}
    order = [n for n in saved.get('order') or [] if isinstance(n, str)]
    pins = [n for n in saved.get('pins') or [] if isinstance(n, str)]
    if not order and not pins:
        return list(names)
    known = list(dict.fromkeys([n for n in order if n in names] + [n for n in pins if n in names]))
    pinned = [n for n in known if n in pins]
    return pinned + [n for n in names if n not in known] + [n for n in known if n not in pins]


def chat_order_path() -> Path | None:
    try:
        return S.C.notes(CHAT_ORDER_FILE)
    except Exception:  # noqa: BLE001 - no project, so no notes dir
        return None


def load_chat_order() -> dict:
    p = chat_order_path()
    try:
        d = json.loads(p.read_text(encoding='utf-8')) if p else {}
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def save_chat_order(order=None, pins=None) -> dict:
    """F133: the `chat_order` action: keep the sidebar's chat order and pins (lists of cN names) for every page."""
    def names(v):
        return list(dict.fromkeys(n for n in v if isinstance(n, str) and re.fullmatch(r'c\d+', n))) \
            if isinstance(v, list) else None
    order, pins = names(order), names(pins if pins is not None else load_chat_order().get('pins') or [])
    if order is None or pins is None:
        return {'ok': False, 'code': 2, 'out': 'chat_order: order and pins are lists of chat names', 'argv': []}
    p = chat_order_path()
    if not p:
        return {'ok': False, 'code': 2, 'out': 'chat_order: no project here to keep it in', 'argv': []}
    tmp = p.with_name(p.name + '.tmp')  # written whole, then moved in: a snapshot never reads half a file
    tmp.write_text(json.dumps({'order': order, 'pins': pins}), encoding='utf-8')
    os.replace(tmp, p)
    return {'ok': True, 'code': 0, 'out': 'chat order kept', 'argv': []}


def with_chat_order(snap):
    """F133: the snapshot with the kept chat order (`chat_order`, every chat shown) and pins (`chat_pins`)."""
    if not isinstance(snap, dict) or 'error' in snap:
        return snap
    saved = load_chat_order()
    names = [s.get('name') for s in snap.get('sessions') or [] if isinstance(s, dict)
             and re.fullmatch(r'c\d+', str(s.get('name')))]
    snap['chat_order'] = chat_list(names, saved)
    snap['chat_pins'] = [n for n in saved.get('pins') or [] if n in names]
    return snap


def run_snapshot() -> dict:
    return with_extras(U.snapshot(terminal_base='.'))


# B119: the agent CLI's own slash commands the run app's composer menu offers after the session's skills
BUILTIN_COMMANDS = (
    ('clear', 'Start the conversation over'),
    ('compact', 'Summarise the conversation so far to free context'),
    ('context', 'Show how full the context is'),
    ('cost', 'Show what this session has used'),
    ('model', 'Pick the model'),
    ('memory', 'Edit the memory files'),
    ('help', 'List the commands'),
)


def skill_description(text: str) -> str:
    """The `description:` line of a SKILL.md or command file's front matter, '' for none."""
    m = re.match(r'---\s*\n(.*?)\n---', text, re.S)
    d = re.search(r'^description:\s*(.+)$', m.group(1), re.M) if m else None
    return d.group(1).strip().strip('"\'') if d else ''


def skill_files(base: Path) -> list[tuple[str, Path]]:
    """[(slash command name, its file)] under a `.claude` folder: skills/<name>/SKILL.md and commands/<name>.md."""
    out = [(f.parent.name, f) for f in sorted(base.glob('skills/*/SKILL.md'))]
    return out + [(f.stem, f) for f in sorted(base.glob('commands/*.md'))]


def slash_commands() -> list[dict]:
    """B119: the slash commands a session takes, for the run app's composer menu: [{'name', 'desc'}]. The control
    session's own skills first (/run /since /follow /control /pause /stop /slots, as guide.control_skills writes
    them), then the agent CLI's built-ins (/clear /compact …), then the project's and the person's own skills and
    commands (`.claude/skills`, `.claude/commands`), each name once."""
    from agent_runner.control import CONTROL_SKILL, control_cmd
    from agent_runner.guide import control_skills
    seen: dict[str, str] = {}
    try:
        cmd = control_cmd()
    except Exception:  # noqa: BLE001 - the runner's path only fills the skills' bodies, not their names or lines
        cmd = 'agent-runner'
    own = control_skills(cmd, CONTROL_SKILL)
    order = ['run', 'since', 'follow', CONTROL_SKILL, 'pause', 'stop', 'slots']
    for name in sorted(own, key=lambda n: (order.index(n) if n in order else len(order), n)):
        seen[name] = re.sub(r'\s*\(the person typed /\S+?(, or [^)]*)?\)\.?$', '', skill_description(own[name]))
    for name, desc in BUILTIN_COMMANDS:
        seen.setdefault(name, desc)
    for base in (Path(S.ROOT) / '.claude', Path.home() / '.claude'):
        for name, f in skill_files(base):
            if name not in seen:
                try:
                    seen[name] = skill_description(f.read_text(encoding='utf-8', errors='replace'))[:120]
                except OSError:
                    continue
    return [{'name': n, 'desc': d} for n, d in seen.items()]


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
        if path == '/term':  # not /term/: the page's calls are relative to /
            return self.send(200, term_html(), 'text/html; charset=utf-8')
        if path == '/snapshot':
            return self.send(200, self.server.snaps.get())
        if path == '/events':
            return self.events()
        if path == '/commands':
            return self.send(200, json.dumps(slash_commands(), ensure_ascii=False))
        if path.startswith('/terminal/'):
            return self.send(200, json.dumps(self.server.terms.open(path.split('/')[2])))
        if path.startswith('/feed/'):
            return self.send(200, json.dumps(U.feed(path.split('/')[2]), ensure_ascii=False))
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
            cid = str(body.get('cid') or '')[:80]  # F137: the outbox's client id
            if not isinstance(args, dict):
                raise ValueError('args must be an object')
        except (ValueError, AttributeError) as e:
            return self.send(400, json.dumps({'ok': False, 'out': f'bad request: {e}'}))
        if name in WEB_REFUSED:
            return self.send(404, json.dumps({'ok': False, 'out': f'no such action on the web: {name}'}))
        def run() -> dict:
            try:
                return save_chat_order(**args) if name == 'chat_order' else U.act(name, **args)
            except TypeError as e:  # F133: chat_order is the web's own action, kept beside the chats it orders
                return {'ok': False, 'code': 2, 'out': f'{name}: {e}', 'argv': []}
        r = self.server.once.run(cid, run)
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
        self.once = ActsOnce()  # F137
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


def home_installed() -> bool:
    """F94: is Runner Home set up on this machine (`home install`, no `uninstall` since)?"""
    try:
        from agent_runner.home import home_on
        return home_on()
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        return False


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
        if not home_installed():
            S.log(f'run page: cannot serve on port {port} ({e}); set [run] web_port, or web = false')
            return None
        try:  # F94: Runner Home holds the port: a free one, which Home routes to
            srv = serve(web_token(), 0)
            S.log(f'run page: port {port} is taken ({e}), so it is on port {srv.server_address[1]} '
                  f'(Runner Home opens it)')
        except OSError as e2:
            S.log(f'run page: cannot serve on port {port} ({e2}); set [run] web_port, or web = false')
            return None
    urls = page_urls(srv.server_address[1], srv.token)
    url_file().write_text('\n'.join(urls) + '\n', encoding='utf-8')
    # B129: the run log names a Tailscale Serve https address first too (the mic needs https); web.url stays http
    shown = [x for x in tailscale_https_urls(srv.server_address[1], srv.token) if x not in urls] + urls
    S.log(f'run page: {" or ".join(shown)}' + ('' if shutil.which('ttyd') else ' (no terminal tab: ttyd is not installed)'))
    return srv
