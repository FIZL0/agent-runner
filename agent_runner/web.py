"""F66: the run page on the web. A run serves it from this machine (`[run] web`, on by default) on
`[run] web_port` (8770), bound to every interface so a phone on the LAN or Tailscale reaches it. F165: one address
for every project: with Runner Home installed (and no web_port set by the person), or with that port taken, it
listens on 127.0.0.1 only, on a free port that only Home opens (`start_web`); the link shown is Home's /p/KEY/.

    GET  /?t=TOKEN               F79: the page (web_page.html), the run app: a chat app over F74's model, light
                                 and dark by the browser's setting, laid out for a phone and a desktop
    GET  /manifest.webmanifest?t=TOKEN, /icon-N.png?t=TOKEN   B179: the app on a Home Screen (home_screen.py)
    GET  /snapshot?t=TOKEN       the run page model's snapshot, as JSON, with the machine's name and each
                                 concept's options (`run_snapshot`)
    GET  /events?t=TOKEN         the same snapshot over server-sent events, sent again whenever it changes
    POST /act?t=TOKEN            {"name": ACTION, "args": {...}}: one of `ui_model.ACTIONS` (plan add, plan edit,
                                 drop, shelve, release, chat, answer, take, move, unpark, rename_chat, need_chat,
                                 setting_device …; F93 `talk`, the Talk view's words to its own control
                                 session), its result as JSON
    GET  /terminal/NAME?t=TOKEN  where slot NAME's (or c1's, or cN's) own terminal is served by ttyd (`attach NAME`),
                                 started on demand; without one, why (no ttyd, not up), its session link and whether
                                 it can be resumed
    GET  /t/TOKEN/NAME/...       F114: that terminal, ttyd's page and WebSocket, on this address (session_frame.py)
    GET  /feed/NAME?t=TOKEN      F74: session NAME's transcript as say/you/tool/out entries (`ui_model.feed`)
    GET  /settings?t=TOKEN       F97: every setting, its value, source and default (`ui_model.settings`)
    GET  /task/ID?t=TOKEN        F85: task ID's whole text (`plan ID`), for its row folded open
    GET  /concept/ID?t=TOKEN     F74: concept ID's local page copy (<notes>/concepts/ID.html), sandboxed
    GET  /speech?t=TOKEN         F158: the voices this machine can read Talk's replies with (`speech.voices`)
    POST /speech?t=TOKEN         F158: {"text", "voice"}: that text as a WAV clip (`speech.Speaker`)
    GET  /diff/NAME?t=TOKEN      F75: slot NAME's diff so far (`slot_diff`), for its diff tab
    POST /upload?t=TOKEN&name=N  F79: an attachment (the body, as is) kept under <notes>/uploads; its path on this
                                 machine comes back, for the message that hands it to a session

Every request carries the token (`?t=`, or an `X-Token` header): the page can type into sessions, so one without
it is refused. The token is made once per project (<notes>/web.token) and printed by `status` and in the run
log with the page's address. Standard library only; ttyd is optional (a chat says how to install it).
"""

from __future__ import annotations

import hmac
import html
import json
import os
import re
import secrets
import shutil
import socket
import subprocess as sp
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent_runner import home_screen, plat, session_frame, speech
from agent_runner import state as S
from agent_runner import ui_model as U

PAGE = Path(__file__).with_name('web_page.html')
# B164: the page as it was when this process loaded its code: an update on disk while the run is up must not
# serve a page that asks for routes and actions this run does not have. A restart serves the new one.
PAGE_TEXT = PAGE.read_text(encoding='utf-8')
BOOT = secrets.token_hex(4)  # B164: this process, so the page knows when the run restarted
TICK = 2.0  # s between snapshots the events stream compares
PING = 15.0  # s of no change before the stream sends a keep-alive comment
TTYD_INSTALL = ('ttyd is not installed, so a chat cannot show the session. Install it on the machine the run is on '
                '(Arch: pacman -S ttyd; Debian/Ubuntu: apt install ttyd; macOS: brew install ttyd; Windows: winget '
                'install tsl0922.ttyd) and open the chat again.')


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


def site_urls(root: Path | None = None) -> list[str]:
    """B146: the run app's addresses through the device site (home.site_links: Runner Home's /p/KEY/ on its port)
    for the project at `root` (this run's), [] while nothing on the device routes it. Worked out each time it is
    shown, never kept in <notes>/web.url: that keeps the run's own port, which Home routes to, and the device
    site can come up or go after the run starts."""
    try:
        from agent_runner.home import site_links
        return site_links(root or S.C.root)
    except Exception:  # noqa: BLE001 - the run's own link still works without Home
        return []


LOCAL = '127.0.0.1'


def own_links(urls: list[str]) -> list[str]:
    """F165: of a run's own addresses (<notes>/web.url), those another device may open: not the 127.0.0.1 one,
    which is there for Runner Home only and is never shown."""
    return [u for u in urls if urlsplit(u).hostname != LOCAL]


def closed_line() -> str:
    """F165: why nothing opens this run's page, and what opens it (home.why_closed)."""
    from agent_runner.home import why_closed
    return why_closed(S.C.root)


def https_first(urls: list[str], https=None) -> list[str]:
    """`urls` with the Tailscale Serve https addresses for the first one's port ahead of them, at its path
    (/p/KEY/ through the device site, B146) and with its token (B130: Safari's mic needs https)."""
    if not urls:
        return []
    u = urlsplit(urls[0])
    if u.port and (t := (parse_qs(u.query).get('t') or [''])[0]):
        path = u.path or '/'
        got = [x.replace('/?t=', f'{path}?t=', 1) for x in (https or tailscale_https_urls)(u.port, t)]
        return [x for x in got if x not in urls] + urls
    return list(urls)


def page_line(site=None) -> str:
    """`run page: URL` while a run serves the page (what `status` prints), else ''. B146: the device site's
    /p/KEY/ address when one routes this project (site_urls), else the run's own; F165: with neither, why; B130: a Tailscale Serve https
    address for that port comes first (Safari's mic needs https); <notes>/web.url keeps the run's own http ones,
    which Home reads its port from."""
    try:
        if S.run_up() and (us := url_file().read_text(encoding='utf-8').split()):
            us = https_first((site or site_urls)() or own_links(us))
            if not us:
                return f'run page: {closed_line()}'
            return f'run page: {us[0]}' + (f' (or {us[1]})' if len(us) > 1 else '')
    except (OSError, ValueError):
        pass
    return ''


# --- F138: option buttons that answer the run with no AI session ------------------------------------------------
#
# A concept page's or a pick sheet's option button is a plain link to the run page's https address:
# <https base>/pick?id=<ID>&o=<option>&k=<code>. The code is a one-use secret made for that item and kept in
# <notes>/pick-codes/<ID>.json, never the run page's own token, so a leaked page can only pick an option for that
# item. /pick checks it, runs `plan confirm ID "go with <option>: <its name>"` (a pick sheet: `sheet ID --picks`),
# burns it, and shows a small page saying what happened (or why not: used, unknown, settled already).

PICK_OPTION = re.compile(r'[A-Za-z0-9]{1,8}')  # a concept's option: A, B, C
PICK_MAX = 600  # chars of a pick sheet's picks line
_PICK_LOCK = threading.Lock()


def pick_file(tid: str) -> Path:
    return S.C.notes('pick-codes', f'{tid}.json')


def _pick_state(tid: str) -> dict:
    try:
        d = json.loads(pick_file(tid).read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pick_code(tid: str) -> str:
    """Item `tid`'s pick code: the unused one kept for it, else a fresh one (owner-only file)."""
    if (d := _pick_state(tid)).get('code') and not d.get('used'):
        return d['code']
    code = secrets.token_urlsafe(18)
    f = pick_file(tid)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({'id': tid, 'code': code, 'made': time.strftime('%Y-%m-%d %H:%M')}) + '\n',
                 encoding='utf-8')
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return code


def run_port() -> int:
    """The run page's port: the one a run serves it on (<notes>/web.url), else `[run] web_port`; 0 when only
    Runner Home opens it (F165)."""
    try:
        if us := url_file().read_text(encoding='utf-8').split():
            if not own_links(us):
                return 0
            if p := urlsplit(us[0]).port:
                return p
    except (OSError, ValueError):
        pass
    return int(S.C.run.get('web_port', 8770))


def https_base(https=None) -> str:
    """The run page's https address with no path and no token (`https://host[:port]`), from Tailscale Serve;
    '' when it gives none (no https: the pages keep today's flow)."""
    port = run_port()
    for u in (https or tailscale_https_urls)(port, 'x') if port else []:
        s = urlsplit(u)
        if s.scheme == 'https' and s.netloc:
            return f'https://{s.netloc}'
    return ''


def no_https_why() -> str:
    """Why `https_base` is '' (F165: without naming a port only Home opens)."""
    if port := run_port():
        return f'Tailscale Serve proxies none to port {port}'
    return 'it is reached through Runner Home only, which takes no option links'


def pick_link(base: str, tid: str, code: str, option: str = '') -> str:
    """One option's link (no `o` when `option` is ''; a pick sheet adds its picks line to it)."""
    from urllib.parse import quote
    return f'{base}/pick?id={quote(tid)}&k={quote(code)}' + (f'&o={quote(option)}' if option else '')


def pick_base(tid: str, https=None) -> str:
    """F138: item `tid`'s link with no option, for a pick sheet's Send to add its picks to ('' with no https)."""
    return pick_link(base, tid, pick_code(tid)) if (base := https_base(https)) else ''


def pick_links(tid: str, options: list[str], https=None) -> list[str]:
    """F138: one link per option of item `tid` ([] with no https address)."""
    if not (base := https_base(https)):
        return []
    code = pick_code(tid)
    return [pick_link(base, tid, code, o) for o in options]


def _concept_of(tid: str) -> tuple[str, str]:
    """(concept id, build id) of a waiting concept that `tid` names (either one); ('', '') for none."""
    from agent_runner import plan as P
    try:
        for build, cid, _, _ in P.waiting(S.C.todo, all=True):
            if tid in (build, cid):
                return cid, build
    except (SystemExit, OSError):
        pass
    return '', ''


def pick(tid: str, option: str, code: str) -> tuple[int, str]:
    """F138: answer item `tid` with `option` when `code` is its unused pick code: (HTTP status, what to say)."""
    from agent_runner.brief import has_sheet
    with _PICK_LOCK:  # a double tap runs once
        d = _pick_state(tid) if re.fullmatch(r'[A-Za-z]+\d+[a-z0-9]*', tid or '') else {}
        if not d.get('code') or not code or not hmac.compare_digest(code.encode(), str(d['code']).encode()):
            return 403, 'This link is unknown: it was not made for this item. Use the buttons on its page.'
        if d.get('used'):
            return 409, f'This link was used already ({d.get("option", "")} on {d["used"]}): {tid} is answered.'
        if not U.need_label(tid):
            return 409, f'{tid} is settled already: nothing waits for an answer on it.'
        sheet = has_sheet(tid)
        if not option or (len(option) > PICK_MAX if sheet else not PICK_OPTION.fullmatch(option)):
            return 400, f'{option!r} is not an option of {tid}.'
        if sheet:
            argv = ['sheet', tid, '--go'] if option.lower() in ('go', 'recommended') else \
                ['sheet', tid, '--picks', option]
            said = f'Sent your picks for {tid}: the run starts it again.'
        else:
            cid, build = _concept_of(tid)
            opts = concept_options(U.concept_copy(cid or tid))
            i = ord(option.upper()) - ord('A') if len(option) == 1 and option.isalpha() else -1
            name = opts[i]['name'] if 0 <= i < len(opts) else ''
            name = re.sub(r'\s*\(recommended\)\s*$', '', re.sub(rf'^\s*{option}\s*[:.)-]\s*', '', name, flags=re.I),
                          flags=re.I).strip()  # 'B: drawer (recommended)' is named 'drawer'
            argv = ['plan', 'confirm', tid, f'go with {option}' + (f': {name}' if name else '')]
            said = (f'Approved {option}' + (f' ({name})' if name else '') + f': the run starts {build}.'
                    if build else f'Answered {tid} with {option}: the run starts it again.')
        r = U.call(argv)
        if not r['ok']:
            return 409, f'{tid} was not answered: {(r.get("out") or "").strip() or "the runner refused it"}'
        d.update(used=time.strftime('%Y-%m-%d %H:%M'), option=option if not sheet else 'picks')
        pick_file(tid).write_text(json.dumps(d) + '\n', encoding='utf-8')
        return 200, said


def pick_page(code: int, said: str) -> bytes:
    """The small page /pick answers with."""
    import html as H
    head = 'Done' if code == 200 else 'Not answered'
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{head}</title>
<style>:root{{--bg:#f4f6f9;--fg:#1a1e26;--muted:#5f6876}}
@media (prefers-color-scheme:dark){{:root{{--bg:#11141a;--fg:#e6e9ef;--muted:#9aa3b2;color-scheme:dark}}}}
body{{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;margin:0;
padding:32px max(16px,env(safe-area-inset-left,0px))}}h1{{font-size:1.3rem;margin:0 0 8px}}p{{margin:0;max-width:36em}}
</style></head><body><h1>{head}</h1><p>{H.escape(said)}</p></body></html>""".encode('utf-8')


# --- c1 and the terminals ---------------------------------------------------------------------------------------

def socket_of(name: str) -> str:
    """C26: the attach socket of session `name` (s2, c1, c6) as a path, '' when it has none (not up)."""
    try:
        from agent_runner.attach import session_socket
        sock = session_socket(name)
        return str(sock) if sock else ''
    except Exception:  # noqa: BLE001 - no notes dir
        return ''


def terminal_fallback(name: str) -> dict:
    """F74: a chat without ttyd: how to install it (`mode` 'install'); the message box works meanwhile."""
    return {'ok': False, 'mode': 'install', 'out': TTYD_INSTALL + f' Until then, messages still reach {name}.'}


def session_live(name: str) -> bool:
    """F114: does session `name` run (its marker names a live process)?"""
    from agent_runner.slots import marker_pid
    try:
        pid = marker_pid(S.C.notes(f'{"control" if name[0] == "c" else "slot"}{name[1:]}.live'))
        return bool(pid and plat.alive(pid))
    except Exception:  # noqa: BLE001 - no notes dir
        return False


def headless(name: str) -> bool:
    """F114: a slot of the stream engine: it has no terminal, only a stream of events."""
    try:
        return bool(json.loads(S.C.notes(f'slot{name[1:]}.job').read_text(encoding='utf-8')).get('stream'))
    except Exception:  # noqa: BLE001 - no job, not JSON
        return False


def resumable(name: str) -> str:
    """F114: the conversation an ended chat (cN, not c1) can be resumed with, as a session id; '' for none."""
    if not re.fullmatch(r'c\d+', name) or name == 'c1':
        return ''
    try:
        from agent_runner.control import control_kept_sid
        from agent_runner.slots import transcript
        sid = control_kept_sid(int(name[1:]))
        return sid if sid and transcript(sid) else ''
    except Exception:  # noqa: BLE001 - no notes dir
        return ''


def no_session(name: str) -> dict:
    """F114: why session `name` has no terminal to show (`mode` 'none'): `live` (it runs), its claude.ai/code `link`
    and whether it can be resumed."""
    if not re.fullmatch(r'[cs]\d+', name):
        return {'ok': False, 'mode': 'none', 'live': False, 'out': f'{name} is not a session.', 'link': '', 'resume': False}
    live, sid = session_live(name), '' if name == 'c1' else resumable(name)
    if live and name[0] == 's' and headless(name):
        out = f'{name} runs headless ([run] engine = "stream"), so it has no terminal to show. Messages still reach it.'
    elif live and plat.WINDOWS and not plat.has_conpty():
        out = f'{name} runs in a hidden console: showing it here takes Windows 10 1809 or later.'
    elif live:
        out = f'{name} is up, but there is no terminal to attach to. If it just started, it comes in a moment.'
    else:
        out = f'{name} is not up, so there is no session to show.'
    link = U._bridge_link(sid or U.session_sid(name))
    return {'ok': False, 'mode': 'none', 'live': live, 'out': out, 'link': link, 'resume': bool(sid) and not live}


def resume_chat(chat: str) -> dict:
    """F114: Resume on an ended chat: its conversation comes up again under its number (`control N --reopen`)."""
    bad = {'ok': False, 'code': 2, 'argv': []}
    if not re.fullmatch(r'c\d+', str(chat)) or chat == 'c1':
        return {**bad, 'out': f'resume_chat: a chat (c2 and up), not {chat!r}'}
    if session_live(chat):
        return {'ok': True, 'code': 0, 'out': f'{chat} is up already', 'argv': [], 'name': chat}
    if not (sid := resumable(chat)):
        return {**bad, 'out': f'{chat} has no conversation left to resume'}
    from agent_runner.control_reopen import reopen_control
    where = reopen_control(int(chat[1:]), sid)
    return {'ok': bool(where), 'code': 0 if where else 1, 'argv': [], 'name': chat,
            'out': f'{chat} is resuming' if where else f'{chat} could not be resumed (the run log says why)'}


U.ACTIONS['resume_chat'] = resume_chat


WEB_REFUSED = {'keys'}  # C24: actions the web does not take (typing into a pane went with the built-in view)


class ActsOnce:
    """F137: the page's outbox sends each action with a client id (`cid`) and sends it again after a drop or a
    reload, so an action whose id the server has run already answers with its first result instead of running
    twice (a `new_control` sent twice would start two chats). A copy that comes while the first still runs waits
    for it (None, a 503, when it waited WAIT s in vain). The last KEEP finished ids are kept, in memory: a restarted
    run page forgets them."""
    KEEP = 500
    WAIT = 300.0  # s a copy waits for the first to finish

    def __init__(self):
        self.lock = threading.Lock()
        self.seen: dict[str, list] = {}  # cid -> [done Event, result]

    def run(self, cid: str, fn) -> dict | None:
        if not cid:
            return fn()
        with self.lock:
            got = self.seen.get(cid)
            first = got is None
            if first:
                got = self.seen[cid] = [threading.Event(), None]
                done = [k for k, v in self.seen.items() if v[0].is_set()]  # the oldest finished ones go
                for k in done[:max(0, len(self.seen) - self.KEEP)]:
                    self.seen.pop(k)
        if not first:
            if not got[0].wait(self.WAIT):
                return None  # still running: the page sends this copy again later (503)
            if got[1] is None:  # the first did not finish: this copy runs it
                return self.run(cid, fn)
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
    """One ttyd per session, started the first time it is opened, on 127.0.0.1 and a free port of its own; F114: the
    run page serves it under /t/TOKEN/NAME/ on its own address (`Handler.session`), so https and Runner Home reach
    it, and the address is as secret as the page's. C26: it runs `attach NAME` for each browser, a client of the
    session's own socket (F88) like any other; the session has the smallest of its clients' sizes (`attach.Viewers`)."""

    def __init__(self, token: str, port: int, bind: str):
        self.token, self.port, self.bind = token, port, LOCAL
        self.procs: dict[str, tuple[sp.Popen, int, str]] = {}
        self.lock = threading.Lock()

    def argv(self, name: str, sock: str, port: int) -> list[str]:
        from agent_runner.config import runner_cmd
        return ['ttyd', '-W', '-p', str(port), '-i', LOCAL, '-b', f'/t/{self.token}/{name}',
                *(['-w', str(S.ROOT)] if plat.WINDOWS else []),  # ttyd's Windows build starts nothing without it
                *session_frame.ttyd_options(session_frame.session_look()), *runner_cmd(), 'attach', name]

    def ended(self, name: str, port: int, err: str) -> str:
        # F165: a port nobody opens is never named; ttyd's own error has it
        return f'ttyd for {name} ended at once: ' + re.sub(rf'( to)?( port:?)? *\b{port}\b', '', err)

    def open(self, name: str) -> dict:
        """Where the page finds session `name`: {'ok', 'port' (the page's own), 'path'}, or why not."""
        sock = socket_of(name)
        if U.terminal_mode() == 'install':  # an ended one says that it ended: ttyd would not bring it back
            return terminal_fallback(name) if sock or session_live(name) else no_session(name)
        from agent_runner.attach import reachable
        if not sock or name[0] == 's' and headless(name) or not reachable(Path(sock)):
            return no_session(name)
        got = self.ttyd(name, sock)
        return got if not got['ok'] else {'ok': True, 'port': self.port, 'path': f'/t/{self.token}/{name}/'}

    def ttyd(self, name: str, sock: str = '') -> dict:
        """The port session `name`'s ttyd listens on, started when it is not up: {'ok', 'port'} or {'ok', 'out'}."""
        sock = sock or socket_of(name)
        with self.lock:
            p = self.procs.get(name)
            if p and p[0].poll() is None and (p[2] == sock or not sock):
                return {'ok': True, 'port': p[1]}
            if not sock or U.terminal_mode() == 'install':
                return no_session(name) if not sock else terminal_fallback(name)
            if p and p[0].poll() is None:
                p[0].terminate()
            self.procs.pop(name, None)
            with socket.create_server((LOCAL, 0)) as s:
                port = s.getsockname()[1]
            err = tempfile.TemporaryFile()  # not a pipe: nobody reads it while ttyd runs
            kw = {'creationflags': plat.CREATE_NO_WINDOW} if plat.WINDOWS else {'start_new_session': True}
            try:
                proc = sp.Popen(self.argv(name, sock, port), cwd=str(S.ROOT), stdin=sp.DEVNULL, stdout=sp.DEVNULL,
                                stderr=err, env={**os.environ, 'AGENT_RUNNER_WEB': '1'}, **kw)
            except OSError as e:
                err.close()
                return {'ok': False, 'mode': 'none', 'live': True, 'out': f'ttyd for {name} did not start: {e}'}
            end = time.monotonic() + 5
            while True:  # one that cannot start ends at once: say so, not a dead frame
                if proc.poll() is not None:
                    err.seek(0)
                    said = err.read().decode(errors='replace').strip()
                    err.close()
                    return {'ok': False, 'mode': 'none', 'live': True, 'out': self.ended(name, port, said[-300:])}
                try:
                    socket.create_connection((LOCAL, port), timeout=0.5).close()
                    break
                except OSError:
                    if time.monotonic() > end:
                        break
                    time.sleep(0.05)
            err.close()  # ttyd has its own copy
            self.procs[name] = (proc, port, sock)
            return {'ok': True, 'port': port}

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


def page_html(home: bool = False) -> bytes:
    """F79: the run app. Its light and dark looks follow the browser's setting (`[ui] theme` is the terminal
    UI's). F134: `home`
    is Runner Home's own page (HOME_PAGE): the All projects view and the project switcher, no run behind it."""
    page = PAGE_TEXT
    if home:
        page = page.replace('/*HOME_PAGE*/false', 'true', 1).replace(
            '<title>agent-runner</title>', '<title>Runner Home</title>', 1)
    else:  # B153: the project's name as the window title ('ifizbox · runner'), before the script runs
        try:
            name = S.project()
        except Exception:  # noqa: BLE001 - no project initialised: the default title
            name = ''
        if name:
            page = page.replace('<title>agent-runner</title>', f'<title>{html.escape(name)} · runner</title>', 1)
    return page.encode('utf-8')


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
                 ('zypper', 'sudo zypper install ttyd'), ('brew', 'brew install ttyd'),
                 ('winget', 'winget install tsl0922.ttyd'), ('scoop', 'scoop install ttyd'))


def ttyd_install_cmd(which=shutil.which) -> str:
    """B120: the command that installs ttyd here, from the first package manager found ('' when none is)."""
    return next((cmd for tool, cmd in TTYD_PACKAGES if which(tool)), '')


def with_extras(snap: dict) -> dict:
    """F79: what the run app shows beyond the snapshot: this machine's name, and each concept's options."""
    snap['machine'], snap['boot'] = socket.gethostname(), BOOT
    snap['session_look'] = session_frame.session_look()  # F114: the ground of a session's colours
    if snap.get('terminal_mode') == 'install':
        snap['ttyd_install'] = ttyd_install_cmd()  # B120: the page's one line on how to get it
    for c in snap.get('concepts') or []:
        c['options'] = concept_options(c.get('copy', ''))
    snap['home'] = home_address()  # B153: the project name top-left links to Runner Home
    return snap


def home_address() -> dict:
    """B153: Runner Home's port and token, for the run page's link to it on the host the page came from
    ({} while Home is not installed or has no token yet; the token file is only read, never made)."""
    try:
        port = home_port()
        if not port:
            return {}
        from agent_runner.home import config_dir
        token = (config_dir() / 'home.token').read_text(encoding='utf-8').strip()
        return {'port': port, 't': token} if token else {}
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        return {}


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
        if path == '/pick':  # F138: its own one-use code, not the page's token
            q = parse_qs(urlsplit(self.path).query)
            code, said = pick(*((q.get(k) or [''])[0] for k in ('id', 'o', 'k')))
            return self.send(code, pick_page(code, said), 'text/html; charset=utf-8')
        if path.startswith('/t/'):
            return self.session(path)
        if not self.allowed():
            return self.refuse()
        if path in ('/', '/index.html'):
            return self.send(200, page_html(), 'text/html; charset=utf-8')
        if path == '/' + home_screen.MANIFEST:  # B179
            try:
                name = S.project()
            except Exception:  # noqa: BLE001 - no project initialised: the default name
                name = ''
            return self.send(200, home_screen.manifest(name or 'agent-runner', self.server.token),
                             home_screen.MANIFEST_TYPE)
        if png := home_screen.icon_at(path):
            return self.send(200, png, 'image/png')
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
        if path == '/settings':  # F97
            return self.send(200, json.dumps(U.settings(), ensure_ascii=False, default=str))
        if path == '/speech':  # F158
            return self.send(200, json.dumps(speech.voices()))
        if path.startswith('/task/'):  # F85
            return self.send(200, json.dumps(U.task_text(path.split('/')[2]), ensure_ascii=False))
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
        if urlsplit(self.path).path == '/speech':
            return self.speech()
        if urlsplit(self.path).path != '/act':
            return self.send(404, json.dumps({'ok': False, 'out': 'POST goes to /act, /upload or /speech'}))
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
            except Exception as e:  # noqa: BLE001 - F137: an answer, so the outbox shows it failed, not a drop
                return {'ok': False, 'code': 1, 'out': f'{name} failed: {e}', 'argv': []}
        r = self.server.once.run(cid, run)
        if r is None:  # F137: a copy of an action still running: the outbox sends it again later
            return self.send(503, json.dumps({'ok': False, 'out': 'that action is still running'}))
        self.server.snaps.at = 0.0  # the next snapshot shows what the action changed
        self.send(200, json.dumps(r, ensure_ascii=False))

    def session(self, path: str) -> None:
        """F114: /t/TOKEN/NAME/REST, session NAME's own terminal (ttyd's page and calls under its path, its WebSocket).
        The token rides in the path, since ttyd's page drops the query."""
        bits = path.split('/', 4)  # ['', 't', TOKEN, NAME, REST]
        if len(bits) < 5 or not hmac.compare_digest(bits[2].encode(), self.server.token.encode()):
            return self.refuse()
        name = bits[3]
        if not re.fullmatch(r'[cs]\d+', name):
            return self.send(404, json.dumps({'ok': False, 'out': f'no such session: {name}'}))
        got = self.server.terms.ttyd(name)
        if not got['ok']:
            return self.send(502, f'<pre>{html.escape(got["out"])}</pre>', 'text/html; charset=utf-8')
        query = urlsplit(self.path).query
        session_frame.frame(self, got['port'], path + (f'?{query}' if query else ''), name, session_frame.session_look())

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

    def speech(self) -> None:
        """F158: a clip of Talk's reply, made on this machine; the page reads with the browser's own voice when
        none comes."""
        try:
            size = int(self.headers.get('Content-Length') or 0)
            if not 0 < size <= speech.TEXT_MAX * 8:
                self.close_connection = True  # the body stays unread
                raise ValueError('the text is missing or too long')
            body = json.loads(self.rfile.read(size))
            data = self.server.speaker.make(str(body['text']), str(body.get('voice') or ''))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return self.send(400, json.dumps({'ok': False, 'out': f'bad request: {e}'}))
        except speech.SpeechError as e:
            return self.send(503, json.dumps({'ok': False, 'out': str(e)}))
        self.send(200, data, 'audio/wav')

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
    allow_reuse_address = os.name != 'nt'  # F165: on Windows it would let two runs share one port

    def __init__(self, token: str, port: int, bind: str = '0.0.0.0', snap=run_snapshot):
        self.token, self.snaps, self.stopped = token, Snapshots(snap), threading.Event()
        self.once = ActsOnce()  # F137
        self.speaker = speech.Speaker()  # F158
        super().__init__((bind, port), Handler)
        self.terms = Terminals(token, self.server_address[1], bind)
        self.moving = threading.Lock()

    def private(self) -> bool:
        return self.server_address[0] == LOCAL

    def go_private(self) -> bool:
        """F165: leave the port it listens on for a free one on 127.0.0.1 (Runner Home was installed). What is
        being answered goes on; terminals open again through Home. False when the run is stopping."""
        with self.moving:
            if self.stopped.is_set():
                return False
            # the new one first: with no port to be had, the page stays where it is
            new = socket.create_server((LOCAL, 0))
            self.shutdown()
            self.server_close()
            self.terms.close()
            self.socket, self.server_address = new, new.getsockname()
            self.server_port = self.server_address[1]
            self.terms = Terminals(self.token, self.server_port, LOCAL)
            threading.Thread(target=self.serve_forever, name='run-page', daemon=True).start()
            return True

    def stop(self) -> None:
        self.stopped.set()
        with self.moving:
            self.shutdown()
            self.server_close()
            self.terms.close()
        self.speaker.close()


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


def home_port() -> int:
    """B146: the port Runner Home serves on (`port` in its registry, 8770), 0 while it is not installed."""
    try:
        if home_installed():
            from agent_runner.home import load_registry
            return int(load_registry()['port'])
    except Exception:  # noqa: BLE001 - a run's page never fails over Home
        pass
    return 0


def home_only() -> bool:
    """F165: is this run's page Runner Home's alone to open? With Home installed, unless the person set `[run]
    web_port` (runner.toml or runner.local.toml) to a port other than Home's own, which is kept for Home."""
    port = home_port()
    return bool(port) and ('web_port' not in S.C.given.get('run', ()) or S.C.run.get('web_port') == port)


def write_urls(srv: WebServer) -> list[str]:
    """Keep the page's own addresses in <notes>/web.url (Home reads the port and token there): returns them."""
    port = srv.server_address[1]
    urls = [page_url(port, srv.token, LOCAL)] if srv.private() else page_urls(port, srv.token)
    url_file().write_text('\n'.join(urls) + '\n', encoding='utf-8')
    return urls


class HomeWatch:
    """F165: while a run is up, what Runner Home does to its page. `look` every HOME_LOOK s: Home installed
    meanwhile: the page leaves its port for 127.0.0.1; on 127.0.0.1 and nothing opens it on two checks in a row
    (a restart of Home is over by then): the run log says so and how to start Home, once, and when it is back."""

    def __init__(self, srv: WebServer, said: str = ''):
        self.srv, self.said, self.missed, self.looks = srv, said, 0, 0

    def look(self) -> None:
        if not self.srv.private():
            if not home_only() or not self.srv.go_private():
                return
            write_urls(self.srv)
            S.log('run page: Runner Home is installed, so only Home opens it now')
            self.missed = 0
            return
        self.looks += 1
        if self.looks % HOME_CHECK:
            return
        from agent_runner.home import site_links, why_closed
        if urls := site_links(S.C.root, https=lambda port, token: []):
            self.missed = 0
            if self.said:
                self.said = ''
                S.log(f'run page: {" or ".join(https_first(urls))}')
            return
        self.missed += 1
        if self.missed >= 2 and (why := why_closed(S.C.root)) != self.said:
            self.said = why
            S.log(f'run page: {why}')

    def loop(self) -> None:
        while not self.srv.stopped.wait(HOME_LOOK):
            try:
                self.look()
            except Exception as e:  # noqa: BLE001 - the run goes on whatever Home does
                S.log(f'run page: looking for Runner Home failed ({type(e).__name__}: {e})')


HOME_LOOK = 2.0  # s between two looks (Home's install waits 8 s for its port)
HOME_CHECK = 10  # looks between two checks that Home opens the page


def start_web() -> WebServer | None:
    """The run's start: serve the page when `[run] web` is on (the run log gets its address), else nothing.
    F165: on `[run] web_port` for every interface, but with Runner Home installed (`home_only`), or that port
    taken by another, on 127.0.0.1 for Home alone: no project is on a port of its own unless the person set one.
    Without Home the first run up has web_port, and another one's log and status offer `home install`.
    A port in use costs the page, not the run. AGENT_RUNNER_NO_WEB=1 (the test suites) turns it off too."""
    url_file().unlink(missing_ok=True)
    r = S.C.run
    if not r.get('web', True) or os.environ.get('AGENT_RUNNER_NO_WEB'):
        return None
    from agent_runner.ui_model import settings_start
    settings_start()  # F166
    port = int(r.get('web_port', 8770))
    srv, why = None, ''
    if home_only():  # B146: Home's port is Home's, even while Home is not up yet
        if 'web_port' in S.C.given.get('run', ()):
            why = 'Runner Home is installed, so its port is kept for it'
    else:
        try:
            srv = serve(web_token(), port)
        except OSError as e:
            why = f'port {port} is taken ({e})'
    if srv is None:
        try:
            srv = serve(web_token(), 0, LOCAL)
        except OSError as e2:
            S.log(f'run page: cannot serve it ({e2}); set [run] web_port, or web = false')
            return None
        if why:
            S.log(f'run page: {why}, so only Runner Home opens it')
    urls = own_links(write_urls(srv))
    # B129: the run log names a Tailscale Serve https address first too (the mic needs https); web.url stays http.
    # B146: the device site's /p/KEY/ address first when one routes this project
    shown = https_first(site_urls() or urls)
    shown += [x for x in urls if x not in shown]
    closed = '' if shown else closed_line()
    S.log(f'run page: {" or ".join(shown) or closed}' +
          ('' if shutil.which('ttyd') else ' (ttyd is not installed, so a chat cannot show its session)'))
    threading.Thread(target=HomeWatch(srv, closed).loop, name='run-page-home', daemon=True).start()
    return srv
