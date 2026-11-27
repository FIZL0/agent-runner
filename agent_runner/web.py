"""F66: the run page on the web. A run serves it from this machine (`[run] web`, on by default) on
`[run] web_port` (8770), bound to every interface so a phone on the LAN or Tailscale reaches it. F165: one address
for every project: with Runner Home installed (and no web_port set by the person, or that port taken) it listens
on 127.0.0.1 only, on a free port that only Home opens (`start_web`); the link shown is Home's /p/KEY/. B844: without
Home, that port taken, it is on the next free one for every interface.

    GET  /?t=TOKEN               F79: the page (web_page.html), the run app: a chat app over F74's model, light
                                 and dark by the browser's setting, laid out for a phone and a desktop
    GET  /manifest.webmanifest?t=TOKEN, /icon-N.png?t=TOKEN   B179: the app on a Home Screen (home_screen.py)
    GET  /snapshot?t=TOKEN       the run page model's snapshot, as JSON, with the machine's name and each
                                 concept's options (`run_snapshot`)
    GET  /events?t=TOKEN         the same snapshot over server-sent events, sent again whenever it changes
    POST /act?t=TOKEN            {"name": ACTION, "args": {...}}: one of `ui_model.ACTIONS` (plan add, plan edit,
                                 drop, chat, answer, move, run_control, rename_chat, need_chat,
                                 setting_device …; F93 `talk`, the Talk view's words to its own control
                                 session), its result as JSON
    GET  /logins?t=TOKEN         F406a: each model provider, its login (never a secret) and how its terminal's last one
                                 ended (provider_login.Logins.rows); only with the key
    GET  /terminal/login-PROVIDER, /terminal/login-copilot~DOMAIN?t=TOKEN   F406a: `run login` in a terminal, served as
                                 NAME below; only with the key
    GET  /terminal/NAME?t=TOKEN  where slot NAME's (or cN's) own terminal is served by ttyd (`attach NAME`),
                                 started on demand; without one, why (no ttyd, not up), its session link and whether
                                 it can be resumed
    GET  /t/TOKEN/NAME/...       F114: that terminal, ttyd's page and WebSocket, on this address (session_frame.py)
    GET  /live/NAME?t=TOKEN      F170: what session NAME's Claude is doing: its status, mode and background work
                                 (session_now.live)
    GET  /feed/NAME?t=TOKEN      F74: session NAME's transcript as say/you/tool/out entries (`ui_model.feed`)
    GET  /history/NAME?t=TOKEN   F191a: a page of session NAME's whole history, the newest, or &before=MARK, or
                                 &since=MARK (session_history)
    GET  /settings?t=TOKEN       F97: every setting, its value, source and default (`ui_model.settings`)
    GET  /tools?t=TOKEN          F169: every tool and device of the Tools page, with no secret (`devices.page`)
    POST /tools?t=TOKEN          F169: {"op": …}: a device added, edited, tested, its secrets set (`devices.post`); only
                                 over https or loopback, and from this page
    POST /give?t=TOKEN           F175a: {"tid", "values", "confirm"}: Done on a Needs you item with inputs
                                 (`ui_model.need_give`); whether it may hold a secret is the connection's to say
    GET  /task/ID?t=TOKEN        F85: task ID's whole text (`plan ID`), for its row folded open
    GET  /plan-search?q=WORDS&t=TOKEN   F212: the tasks of TODO.md and DONE.md that match (`plan_search.search`)
    GET  /why/ID?t=TOKEN         F162: why a Needs you item waits: its agent's last words (`ui_model.need_why`)
    GET  /shot/DIR/FILE?t=TOKEN  F162: a Needs you item's picture or video (Range too), under <notes>/uploads or <notes>/asks
    GET  /concept/ID?t=TOKEN     F74: concept ID's local page copy (<notes>/concepts/ID.html), sandboxed
    GET  /speech?t=TOKEN         F158: the voices this machine can read Talk's replies with (`speech.voices`)
    POST /speech?t=TOKEN         F158: {"text", "voice"}: that text as a WAV clip (`speech.Speaker`)
    GET  /recorded?t=TOKEN       F161a: whether a clip can be made into words here, and why not (`recorded.engine`)
    POST /recorded?t=TOKEN       F161a: a 16 kHz mono WAV clip, as is: {"ok", "words"} (`recorded.Listener`)
    GET  /diff/NAME?t=TOKEN      F75: slot NAME's diff so far (`slot_diff`), for its diff tab
    POST /upload?t=TOKEN&name=N  F79: an attachment (the body, as is) kept under <notes>/uploads; its path on this
                                 machine comes back, for the message that hands it to a session

Every request carries the token (`?t=`, or an `X-Token` header): the page can type into sessions, so one without
it is refused. The token is made once per project (<notes>/web.token) and printed by `status` and in the run
log with the page's address. Standard library only; ttyd is optional (a chat says how to install it).
"""

from __future__ import annotations

import hashlib
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
from urllib.parse import parse_qs, unquote, urlsplit

from agent_runner import devices, home_screen, login_hold, need_detail, page_https, plan_search, plat, provider_login, recorded, session_frame, session_history, session_now, session_theme, speech, trust, watch
from agent_runner import state as S
from agent_runner import ui_model as U
from agent_runner import web_actions  # noqa: F401  F460a: its actions join U.ACTIONS
from agent_runner import web_review  # noqa: F401  F444c: pitch_ask and pitch_better join U.ACTIONS

# C45: the code is in files by area, each run in this module's own namespace in this order (the names are one
# module's, as before the split: a test's `W.X = v` reaches all of it). Put new code in the file of its area, not in this
# one: web_urls (page file, token, addresses), web_pick (F138 option buttons), web_session (a session's socket, live,
# resume), web_acts (ActsOnce, talk), web_terminal (diff, ttyd), web_snapshot (the snapshot and its extras, chat order),
# web_commands (slash commands), web_upload; then the Handler and the server stay here; web_home (Runner Home's watch,
# start_web) is run after them.
PARTS = ('web_urls', 'web_pick', 'web_session', 'web_acts', 'web_terminal', 'web_snapshot', 'web_commands', 'web_upload')
LATE_PARTS = ('web_home',)


def _load_parts(parts) -> None:
    for part in parts:
        path = Path(__file__).with_name(part + '.py')
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), globals())


_load_parts(PARTS)

# B838: the keep-alive is a named event, so the page can tell a quiet stream from a dead one; its data is no snapshot
# and an older page's onmessage never hears it (only unnamed events reach onmessage)
STREAM_PING = b'event: ping\ndata: 1\n\n'

def byte_range(asked: str, size: int) -> tuple[int, int] | None:
    """F445a: the [start, end) of a file of `size` bytes a Range header asks for, (0, 0) when the file has none of
    it; None for the whole file: no Range, several, or one that is malformed."""
    m = re.fullmatch(r'bytes=(\d*)-(\d*)', asked.strip(), re.A)
    if not m or len(asked) > 60 or not (m[1] or m[2]):
        return None
    if not m[1]:
        return (max(0, size - int(m[2])), size) if int(m[2]) and size else (0, 0)
    start, last = int(m[1]), int(m[2]) if m[2] else size
    if last < start:
        return None if m[2] else (0, 0)
    return (start, min(last + 1, size)) if start < size else (0, 0)


class Handler(BaseHTTPRequestHandler):
    server: 'WebServer'
    protocol_version = 'HTTP/1.1'
    keyless = False  # F136: this request came in by its network

    def log_message(self, *a) -> None:  # the run log is not an access log
        pass

    def allowed(self) -> bool:
        q = parse_qs(urlsplit(self.path).query)
        return self.key_ok((q.get('t') or [''])[0])

    def key_ok(self, got: str) -> bool:
        """The run page's key, or, F136, a client on one of `[ui] trusted_networks`."""
        key = bool(got) and hmac.compare_digest(got.encode(), self.server.token.encode())
        self.keyless = not key and trust.lets_in(run_trusted(), self.command, self.client_address[0], self.headers)
        return key or self.keyless

    def end_headers(self) -> None:
        if self.keyless:  # F136: with no key, only its own pages may frame it
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
        super().end_headers()

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
            return session_frame.send_app(self, page_html())  # B769a
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
            of = (parse_qs(urlsplit(self.path).query).get('s') or [''])[0]
            return self.send(200, json.dumps(slash_commands(of), ensure_ascii=False))
        if path.startswith('/live/'):  # F170
            return self.send(200, json.dumps(U.with_task_counts(session_now.live(path.split('/')[2])), ensure_ascii=False))  # F192d1: counts
        if path.startswith('/terminal/'):
            name = path.split('/')[2]
            login = provider_login.is_login(name)  # F406a: its whole rest is the name, so a domain's path is refused
            if self.keyless and (login or name == session_frame.LOGIN):  # F126b
                return self.refuse()
            return self.send(200, json.dumps(self.server.terms.open(path[len('/terminal/'):] if login else name)))
        if path == '/logins':  # F406a
            return self.refuse() if self.keyless else self.send(200, json.dumps(
                {'ok': True, 'providers': self.server.terms.logins.rows()}, ensure_ascii=False))
        if path.startswith('/feed/'):
            return self.send(200, json.dumps(U.feed(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/history/'):  # F191a
            q = parse_qs(urlsplit(self.path).query)
            return self.send(200, json.dumps(session_history.asked(path.split('/')[2], q), ensure_ascii=False))
        if path == '/settings':  # F97
            return self.send(200, json.dumps(U.settings(), ensure_ascii=False, default=str))
        if path == '/tools':  # F169
            try:
                got = devices.page(S.C, devices.channel(self.client_address[0], self.headers, False, behind=True))
            except Exception as e:  # noqa: BLE001 - an answer, so the page says why
                got = {'ok': False, 'out': f'The tools could not be read ({type(e).__name__}).'}
            return self.send(200, json.dumps(got, ensure_ascii=False))
        if path == '/speech':  # F158
            return self.send(200, json.dumps(speech.voices()))
        if path == '/recorded':  # F161a
            return self.send(200, json.dumps(recorded.engine()))
        if path.startswith('/task/'):  # F85
            got = U.task_text(path.split('/')[2])
            if got.get('ok'):  # F509: what its agent said it did when it finished, '' for none
                from agent_runner import done as D
                got['writeup'] = D.writeup(S.C, got['id'])
            return self.send(200, json.dumps(got, ensure_ascii=False))
        if path == '/plan-search':  # F212
            words = (parse_qs(urlsplit(self.path).query).get('q') or [''])[0]
            return self.send(200, json.dumps(plan_search.search(words), ensure_ascii=False))
        if path.startswith('/why/'):  # F162
            return self.send(200, json.dumps(U.need_why(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/shot/'):  # F162
            return self.shot(unquote(path[len('/shot/'):]))
        if path.startswith('/diff/'):
            return self.send(200, json.dumps(slot_diff(path.split('/')[2]), ensure_ascii=False))
        if path.startswith('/concept/'):
            return self.concept(path.split('/')[2])
        self.send(404, json.dumps({'ok': False, 'out': f'no such page: {path}'}))

    def do_POST(self) -> None:
        if not self.allowed():
            self.unread()
            return self.refuse()
        if urlsplit(self.path).path == '/upload':
            return self.upload()
        if urlsplit(self.path).path == '/speech':
            return self.speech()
        if urlsplit(self.path).path == '/recorded':
            return self.recorded()
        if urlsplit(self.path).path == '/tools':
            return self.tools()
        if urlsplit(self.path).path == '/give':
            return self.give()
        if urlsplit(self.path).path == '/queue':
            return self.queue()
        if urlsplit(self.path).path != '/act':
            return self.send(404, json.dumps({'ok': False, 'out': 'POST goes to /act, /give, /queue, /upload, /speech, /recorded or /tools'}))
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            name, args = str(body.get('name', '')), body.get('args') or {}
            cid = str(body.get('cid') or '')[:80]  # F137: the outbox's client id
            if not isinstance(args, dict):
                raise ValueError('args must be an object')
            if name == 'chat_to' and body.get('hold'):  # B158: beside args, so a run older than the page ignores it
                args = {**args, 'wait': False}
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
        self.server.snaps.fresh()  # B850b: the next snapshot shows what the action changed, sent at once
        self.send(200, json.dumps(r, ensure_ascii=False))

    def session(self, path: str) -> None:
        """F114: /t/TOKEN/NAME/REST, session NAME's own terminal (ttyd's page and calls under its path, its WebSocket).
        The token rides in the path, since ttyd's page drops the query."""
        bits = path.split('/', 4)  # ['', 't', TOKEN, NAME, REST]
        if len(bits) < 5 or not self.key_ok(bits[2]):
            return self.refuse()
        name = bits[3]
        if name == session_frame.LOGIN or provider_login.is_login(name):
            # F126b: with the key only, also on a trusted network; its query goes nowhere
            return self.refuse() if self.keyless else session_frame.login_frame(self, self.server.terms, bits[4], name)
        path = f'/t/{self.server.token}/{name}/{bits[4]}'  # the ttyd's own path, whatever key this one had (F136)
        if not re.fullmatch(r'[cs]\d+', name):
            return self.send(404, json.dumps({'ok': False, 'out': f'no such session: {name}'}))
        got = self.server.terms.ttyd(name)
        if not got['ok']:
            return self.send(502, f'<pre>{html.escape(got["out"])}</pre>', 'text/html; charset=utf-8')
        query = urlsplit(self.path).query
        session_frame.frame(self, got['port'], path + (f'?{query}' if query else ''), name, frame_look(name))

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

    def unread(self) -> None:
        """F169: a refused request's body may hold a secret. It is read and thrown away (a little of it), and the
        connection closes: left there it would be taken for the next request, and its error would say it back."""
        self.close_connection = True
        try:
            n = int(self.headers.get('Content-Length') or 0)
            if 0 < n <= devices.BODY_MAX:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass

    def tools(self) -> None:
        """F169: a device changed on the Tools page (`devices.post`). Refused unread when it may not carry a secret."""
        try:
            size = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            size = 0
        why = devices.channel(self.client_address[0], self.headers, behind=True)
        if why or not 0 < size <= devices.BODY_MAX or \
                (self.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
            self.unread()
            return self.send(403 if why else 400, json.dumps(devices.refusal(why) if why else
                                                             {'ok': False, 'out': 'bad request'}))
        code, got = devices.post(self.rfile.read(size), S.C)
        self.server.snaps.at = 0.0
        self.send(code, json.dumps(got, ensure_ascii=False))

    def queue(self) -> None:
        """F192d1: a tap on an option with stored tasks: {chat, question, option} queues them once
        (`ui_model.option_queue`), with one chat line and no message to Claude."""
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
            args = {k: str(body.get(k) or '') for k in ('chat', 'question', 'option')}
        except (ValueError, AttributeError) as e:
            return self.send(400, json.dumps({'ok': False, 'out': f'bad request: {e}'}))
        try:
            r = U.option_queue(**args)
        except Exception as e:  # noqa: BLE001 - an answer, so the page shows it failed
            r = {'ok': False, 'code': 1, 'out': f'queueing failed: {e}', 'argv': []}
        self.server.snaps.fresh()
        self.send(200, json.dumps(r, ensure_ascii=False))

    def give(self) -> None:
        """F175a: Done on a Needs you item with inputs. `secure` is the connection's (`devices.channel`), never the
        page's own word; text and links go over plain http too. No answer, and no error, holds what was sent."""
        try:
            size = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            size = 0
        why = devices.channel(self.client_address[0], self.headers, behind=True)
        if why == 'origin' or not 0 < size <= devices.BODY_MAX or \
                (self.headers.get('Content-Type') or '').split(';')[0].strip().lower() != 'application/json':
            self.unread()
            return self.send(403 if why == 'origin' else 400, json.dumps(
                devices.refusal(why) if why == 'origin' else {'ok': False, 'out': 'bad request'}))
        try:
            body = json.loads(self.rfile.read(size))
            tid, values = body['tid'], body['values']
            if not isinstance(tid, str) or not isinstance(values, dict):
                raise ValueError('tid or values')
        except (ValueError, KeyError, TypeError, RecursionError):
            return self.send(400, json.dumps({'ok': False, 'out': 'bad request'}))
        try:
            r = U.need_give(tid, values, confirm=body.get('confirm') is True, secure=not why)
        except Exception as e:  # noqa: BLE001 - the type alone: an error's text may hold what was sent
            r = {'ok': False, 'code': 1, 'out': f'that failed on the machine ({type(e).__name__})', 'argv': []}
        self.server.snaps.at = 0.0
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

    def recorded(self) -> None:
        """F161a: a recorded clip as words, for the page that sent it alone. 413 or 400: the clip is refused; 503: no words, and why."""
        try:
            size = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            size = 0
        if not 0 < size <= recorded.BYTES_MAX:
            self.close_connection = True
            left = size if size <= 4 * recorded.BYTES_MAX else 0  # a little too long: read and thrown away, so the page hears why
            while left > 0 and (got := self.rfile.read(min(left, 1 << 16))):
                left -= len(got)
            return self.send(413 if size > 0 else 400, json.dumps({'ok': False, 'out': (
                f'a clip is at most {recorded.SECONDS_MAX} seconds' if size > 0 else 'the clip is missing')}))
        try:
            words = self.server.listener.read(self.rfile.read(size))
        except recorded.BadClip as e:
            return self.send(400, json.dumps({'ok': False, 'out': str(e)}))
        except speech.SpeechError as e:
            return self.send(503, json.dumps({'ok': False, 'out': str(e)}))
        self.send(200, json.dumps({'ok': True, 'words': words}, ensure_ascii=False))

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

    def shot(self, src: str) -> None:
        """F162: a Needs you item's picture or video ('uploads/a.png', 'asks/b.mp4'): those of those two folders only.
        F445a: in parts as asked for (Range), which Safari needs to play a video at all."""
        f = need_detail.shot_file(src)
        try:
            h = f.open('rb') if f else None
        except OSError:
            h = None
        if h is None:
            return self.send(404, json.dumps({'ok': False, 'out': 'no such picture or video'}))
        with h:
            size = os.fstat(h.fileno()).st_size
            part = byte_range(self.headers.get('Range') or '', size)
            start, end = part or (0, size)
            self.send_response(416 if start >= end else 206 if part else 200)
            self.send_header('Content-Type', need_detail.shot_type(h.read(need_detail.HEAD)))
            self.send_header('Content-Length', str(end - start))
            self.send_header('Accept-Ranges', 'bytes')
            if part:
                self.send_header('Content-Range', f'bytes {start}-{end - 1}/{size}' if start < end else f'bytes */{size}')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            h.seek(start)
            left = end - start
            try:
                while left and (data := h.read(min(left, 1 << 18))):
                    self.wfile.write(data)
                    left -= len(data)
            except OSError:  # the player went away: it seeks by asking again
                left = -1
            if left:
                self.close_connection = True

    def events(self) -> None:
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        last, quiet, gen, looked = '', time.monotonic(), -1, 0.0
        try:
            while not self.server.stopped.is_set():
                now_gen = self.server.snaps.changed()
                if now_gen == gen and time.monotonic() - looked < TICK / 2:
                    self.server.stopped.wait(NOW)  # B850b: a done action or a new STATE is seen within NOW
                    continue
                gen, looked = now_gen, time.monotonic()
                snap = self.server.snaps.get()
                if snap != last:
                    self.wfile.write(f'data: {snap}\n\n'.encode('utf-8'))
                    last, quiet = snap, time.monotonic()
                elif time.monotonic() - quiet >= PING:
                    self.wfile.write(STREAM_PING)  # B838: an event the page hears, not a comment
                    quiet = time.monotonic()
                self.wfile.flush()
        except OSError:  # the page went away
            pass


def ui_themes_css() -> str:
    """F473: the themes the page's UI settings offer, as CSS (theme.py's table; omarchy read now, from this machine)."""
    from agent_runner import theme
    try:
        return theme.page_css()
    except Exception:  # noqa: BLE001 - an unreadable colors.toml: the page keeps its own look
        return ''


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != 'nt'  # F165: on Windows it would let two runs share one port

    def __init__(self, token: str, port: int, bind: str = '0.0.0.0', snap=run_snapshot):
        self.token, self.snaps, self.stopped = token, Snapshots(snap), threading.Event()
        self.once = ActsOnce(S.C.notes('acts-once.jsonl') if S.C else None)  # F137
        self.speaker = speech.Speaker()  # F158
        self.listener = recorded.Listener()  # F161a
        super().__init__((bind, port), Handler)
        self.terms = Terminals(token, self.server_address[1], bind)
        self.moving = threading.Lock()
        self.https = False  # F96: page_https made a Tailscale Serve rule for it

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
            if self.https:  # B847: its Serve rule proxies the port Home takes: Home keeps the https address
                self.https = False
                page_https.hand_over()
            self.shutdown()
            self.server_close()
            self.terms.close()
            self.socket, self.server_address = new, new.getsockname()
            self.server_port = self.server_address[1]
            self.terms = Terminals(self.token, self.server_port, LOCAL)
            threading.Thread(target=self.serve_forever, name='run-page', daemon=True).start()
            return True

    def https_off(self) -> None:
        if self.https:
            self.https = False
            page_https.https_off()

    def stop(self) -> None:
        self.stopped.set()
        with self.moving:
            self.https_off()
            self.shutdown()
            self.server_close()
            self.terms.close()
        self.speaker.close()
        self.listener.close()


def serve(token: str, port: int, bind: str = '0.0.0.0', snap=run_snapshot) -> WebServer:
    """Start a run page server in a daemon thread and return it (port 0: any free port)."""
    srv = WebServer(token, port, bind, snap)
    threading.Thread(target=srv.serve_forever, name='run-page', daemon=True).start()
    return srv



_load_parts(LATE_PARTS)
