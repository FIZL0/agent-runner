#!/usr/bin/env python3
"""F66: the run page on the web serves the page and the snapshot, runs an action's plan command, and refuses a
request without its token. F79: the page is the run app, and keeps uploaded attachments.

    python3 tests/test_web.py        (a temp repo, a server on a free local port, no agent; a few seconds)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402

TODO = """# TODO

## Now

### Next
- [ ] **F1** Board page for the run | files: a.py, tests/test_a.py
- [ ] **B2** Fix the merge retry | files: b.py | after: F1
"""


def fake_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q')
    (repo / '.gitignore').write_text('.runner/\n')
    (repo / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    S.init(repo)
    return repo


def get(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def test_server(tmp: Path) -> None:
    fake_repo(tmp)
    token = W.web_token()
    eq(W.web_token(), token, 'the token is made once and kept in <notes>/web.token')
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: U.snapshot(up=False, links={}, terminal_base='.'))
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        code, page = get(f'{base}/?t={token}')
        eq(code, 200, 'the page is served with the token')
        for part in ('<title>proj · runner</title>'.encode(), b'EventSource', b'Needs you', b'Working now', b'Up next'):
            check(part in page, f'the page has {part.decode()}')
        check(b'JetBrains Mono' not in page and b'lazygit' not in page, 'the terminal-style page is gone')

        code, body = get(f'{base}/snapshot?t={token}')
        snap = json.loads(body)
        eq(code, 200, 'the snapshot is served')
        eq([q['id'] for q in snap['queue']], ['F1', 'B2'], 'the snapshot carries the queue')
        eq(snap['status'][0], 'no run is up', 'and the status lines')

        with urllib.request.urlopen(f'{base}/events?t={token}', timeout=10) as r:
            eq(r.headers.get('Content-Type'), 'text/event-stream', 'events are server-sent events')
            first = r.readline().decode()
            check(first.startswith('data: ') and json.loads(first[6:])['queue'][0]['id'] == 'F1',
                  'the stream opens with the snapshot', first[:200])

        for path in ('/', '/snapshot', '/events', '/terminal/s1', '/snapshot?t=wrong'):
            code, _ = get(base + path)
            eq(code, 403, f'GET {path} without the token is refused')
        code, out = post(f'{base}/act', {'name': 'plan_add', 'args': {'kind': 'F', 'text': 'x'}})
        eq(code, 403, 'a POST without the token is refused')

        calls = []
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, 'added F3'))[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'plan_add', 'args': {
                'kind': 'F', 'text': 'Show usage on the board', 'files': 'a.py', 'pri': 'low'}})
        eq(code, 200, 'an action POST is answered')
        eq(calls, [['plan', 'add', 'F', 'Show usage on the board', '--files', 'a.py', '--pri', 'low']],
           'the action runs its plan command')
        check(out['ok'] and out['out'] == 'added F3', 'and its result comes back', out)

        calls = []  # F72: J/K in the queue moves the task one place past its neighbour
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, 'moved F1'))[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'move', 'args': {
                'tid': 'F1', 'where': 'after', 'other': 'B2'}})
            eq(calls, [['plan', 'move', 'F1', 'after', 'B2']], 'the move action runs plan move ID after <neighbour>')
            check(out['ok'], 'and says it moved', out)
            code, out = post(f'{base}/act?t={token}', {'name': 'move', 'args': {
                'tid': 'F1', 'where': 'top', 'other': 'B2'}})
            check(not out['ok'] and len(calls) == 1, 'a move other than after or before runs nothing', out)

        code, out = post(f'{base}/act?t={token}', {'name': 'nope', 'args': {}})
        check(not out['ok'] and 'no such action' in out['out'], 'an unknown action is an error result', out)
        code, out = post(f'{base}/act?t={token}', {'name': 'drop', 'args': ['F1']})
        eq(code, 400, 'args that are not an object are a bad request')

        with mock.patch.object(W.shutil, 'which', return_value=None), mock.patch('agent_runner.plat.WINDOWS', False):
            code, body = get(f'{base}/terminal/s1?t={token}')
        r = json.loads(body)
        check(not r['ok'] and r['out'].startswith(W.TTYD_INSTALL) and 'chat' in r['out'],
              'without ttyd the terminal tab says how to install it, and that the chat works meanwhile', r)
        check(r['mode'] == 'install' and 'capture' not in r and 'every' not in r,
              "C24: and no 'builtin' mode: the built-in view is gone", r)
        eq(get(f'{base}/pane/s1?t={token}')[0], 404, 'C24: the capture route is gone')
        with mock.patch.object(U, 'act', side_effect=AssertionError('keys reached ui_model')):
            code, out = post(f'{base}/act?t={token}', {'name': 'keys', 'args': {'session': 's1', 'text': 'x'}})
        check(code == 404 and not out['ok'], 'C24: the web no longer types keys into a pane', out)
        page = W.term_html().decode()
        check("'builtin'" not in page and "'pane/'" not in page and "act('keys'" not in page,
              "C24: the terminal-style page has no built-in view code (capture polling, the keys box)")
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.plat.WINDOWS', True):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        check(r['mode'] == 'feed' and 'Windows' in r['out'] and r['feed'] == 'feed/s1',
              'Windows: the feed only', r)
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.plat.WINDOWS', False), mock.patch.object(W, 'socket_of', return_value=''):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        check(not r['ok'] and 'is not up' in r['out'], 'a slot with no terminal says so', r)
        argv = W.Terminals(token, 8770, '0.0.0.0').argv('s2', '/x/slot2.sock', 8771)
        eq(argv[-2:], ['attach', 's2'], "C26: ttyd serves `attach s2`, the session's own socket")
    finally:
        srv.stop()


def test_real_action(tmp: Path) -> None:
    """One action through the real runner: plan add lands in TODO.md."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}', {
            'name': 'plan_add', 'args': {'kind': 'F', 'text': 'Run page shows usage', 'files': 'web.py'}})
        check(out.get('ok'), 'the real plan add ran', out)
        check('Run page shows usage' in (repo / 'plan' / 'TODO.md').read_text(encoding='utf-8'),
              'and the task is in TODO.md')
    finally:
        srv.stop()


def test_run_controls(tmp: Path) -> None:
    """F82: the run controls on the web: the page builds each control's request from the snapshot's one list
    (ui_model.RUN_CONTROLS), the server runs its runner command, and stop now runs only with the page's own
    confirm (no browser dialog)."""
    fake_repo(tmp)
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ('controlsCard()', 'Run controls', 'data-ctl=', 'data-tid=', 'data-sure', 'data-unsure',
                 'data-slots-n', 'controlReq(c,'):
        check(part in page, f'the page has {part}')
    for gone in ('confirm(', 'alert(', 'prompt('):
        check(gone not in page, f'the page uses no {gone}) dialog')
    want = {'slot_add': ['slots', '+1'], 'slot_remove': ['slots', '-1'], 'slots_set': ['slots', '4'],
            'pause': ['pause'], 'go_on': ['pause', '--off'], 'force': ['force'], 'caps_on': ['force', '--off'],
            'stop': ['stop'], 'stop_now': ['stop', '--force'], 'stop_undo': ['stop', '--undo'],
            'task_drop': ['plan', 'drop', 'F1', U.TASK_DROP_WHY],
            'upgrade': ['key', 'u'], 'suspend': ['key', 'z'], 'shutdown': ['key', 'x'],  # C26
            'restart': ['key', 'restart'], 'start': [], 'resume': ['resume', 'F1'],  # F124
            'unclaim': ['plan', 'unclaim', 'F1'], 'wip_show': ['wip', 'show', 'main-checkout-1'],
            'wip_restore': ['wip', 'restore', 'main-checkout-1'], 'wip_drop': ['wip', 'drop', 'main-checkout-1']}
    tid = lambda c: 'main-checkout-1' if c['fix'] == 'wip' else 'F1'  # noqa: E731
    cs = U.controls()
    if shutil.which('node'):
        reqs = logic_js([['controlReq', c, {'n': ' 4', 'tid': tid(c), 'sure': True}] for c in cs] +
                        [['controlReq', U.run_control_of('stop_now') | {'needs': '', 'confirm': U.STOP_NOW_ASK},
                          {'tid': 'F1'}]])
    else:
        print('  (no node here: the page requests are built in Python instead)')
        reqs = [{'name': 'run_control', 'args': {'key': c['key'], **({'n': '4'} if c['needs'] == 'n' else {}),
                                                  **({'tid': tid(c)} if c['needs'] in ('id', 'pick') else {}),
                                                  **({'confirm': True} if c['confirm'] else {})}} for c in cs] + \
            [{'name': 'run_control', 'args': {'key': 'stop_now'}}]
    if shutil.which('node'):
        stop_now = next(c for c in cs if c['key'] == 'stop_now')
        got = logic_js([['controlClick', stop_now, {}], ['controlClick', stop_now, {'sure': 'yes'}],
                        ['controlClick', stop_now, {'sure': True}],
                        ['controlClick', next(c for c in cs if c['key'] == 'stop'), {}],
                        ['taskControlsOn', {'name': 's1', 'task': 'F1', 'state': 'running'}],
                        ['taskControlsOn', {'name': 's2', 'task': 'B2', 'state': 'merging'}],
                        ['taskControlsOn', {'name': 's3', 'task': ''}]])
        eq(got[:4], [{'ask': True}, {'ask': True},
                     {'name': 'run_control', 'args': {'key': 'stop_now', 'confirm': True}},
                     {'name': 'run_control', 'args': {'key': 'stop'}}],
           "Stop now's button asks in the page first; only its Yes sends it, confirmed; Stop goes at once")
        eq(got[4:], [True, False, False], "a slot's Take back and Drop show while it works, not while it lands")
    ran, sent = [], []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'sent to the run'))[1]]), \
                mock.patch.object(U, 'SEND', [lambda text: (sent.append(text), {'ok': True, 'code': 0,
                                                                                 'out': 'sent', 'argv': []})[1]]):
            for c, rq in zip(cs, reqs):
                ran.clear()
                code, out = post(url, rq)
                if c['key'] == 'task_take':
                    eq((out.get('ok'), sent, ran), (True, [], [['control', '--new', '--ask', 'do F1 here', '--no-feed']]),
                       'B139: Take back asks a new control session "do F1 here", not c1')
                else:
                    eq((code, out.get('ok'), ran), (200, True, [want[c['key']]]),
                       f'{c["label"]} runs {" ".join(want[c["key"]])}')
            ran.clear()
            code, out = post(url, reqs[-1])
            eq((out.get('ok'), ran, out.get('confirm')), (False, [], U.STOP_NOW_ASK),
               "stop now without the page's confirm runs nothing and returns the question")
    finally:
        srv.stop()


def test_start(tmp: Path) -> None:
    fake_repo(tmp)
    eq(CF.DEFAULTS['run']['web'], True, '[run] web is on by default')
    eq(CF.DEFAULTS['run']['web_port'], 8770, 'on port 8770')
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.dict(S.C.run, {'web': False}):
        eq(W.start_web(), None, '[run] web = false serves nothing')
    eq(W.page_line(), '', 'and status prints no address')
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: '10.0.0.5'), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0}), mock.patch.object(S, 'log') as lg:
        srv = W.start_web()
    try:
        check(srv is not None, 'web = true serves the page')
        url, by_ip = W.url_file().read_text(encoding='utf-8').split()
        tail = f':{srv.server_address[1]}/?t={W.web_token()}'
        check(url.endswith(tail), 'its address carries the token', url)
        eq(by_ip, f'http://10.0.0.5{tail}', 'and its LAN address, for a phone that cannot resolve the hostname')
        check(any(url in str(c) for c in lg.call_args_list), 'the run log has the address', lg.call_args_list)
        with mock.patch.object(S, 'run_up', return_value=True):
            eq(W.page_line(), f'run page: {url} (or {by_ip})', 'status prints it while the run is up')
        eq(U.SEND[0], U.to_c1, "the run's chat goes through ui_model.to_c1, which finds c1 by its tag")
    finally:
        srv.stop()


def post_raw(url: str, data: bytes, ctype: str = 'image/png') -> tuple[int, dict]:
    req = urllib.request.Request(url, data=data, method='POST', headers={'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b'{}')


def test_upload(tmp: Path) -> None:
    """F79: an attachment from the message box is kept under .runner/uploads and its path comes back, for the
    message that hands it to the session; a name with a path in it cannot leave that folder."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    png = b'\x89PNG\r\n\x1a\nfake picture'
    try:
        code, r = post_raw(f'{base}/upload?t={token}&name=screen%20shot.png', png)
        eq(code, 200, 'an upload is answered')
        p = Path(r['path'])
        check(r['ok'] and p.is_file() and p.read_bytes() == png, 'the file is kept as sent', r)
        eq(p.parent, (repo / '.runner' / 'uploads').resolve(), 'under .runner/uploads')
        check(p.name.endswith('-screen_shot.png'), 'named by its time and its own name, made safe', p.name)
        code, r2 = post_raw(f'{base}/upload?t={token}&name=screen%20shot.png', b'second')
        check(r2['ok'] and r2['path'] != r['path'] and p.read_bytes() == png, 'a second one never overwrites it', r2)
        code, r3 = post_raw(f'{base}/upload?t={token}&name=..%2F..%2Fetc%2Fpasswd', b'x', 'text/plain')
        eq(Path(r3['path']).parent, p.parent, 'a name with a path in it stays in the uploads folder')
        check(Path(r3['path']).name.endswith('-passwd'), 'keeping only its last part', r3)
        code, r4 = post_raw(f'{base}/upload?t={token}&name=x', b'')
        check(code == 400 and not r4['ok'], 'an empty upload is refused', r4)
        code, _ = post_raw(f'{base}/upload?name=x.png', png)
        eq(code, 403, 'and an upload without the token')
    finally:
        srv.stop()
    eq(W.safe_name('.hidden'), 'hidden', 'no leading dot')
    eq(W.safe_name('C:\\Users\\me\\a b.txt'), 'a_b.txt', 'a Windows path keeps its last part')
    eq(W.safe_name(''), 'file', 'no name: file')


def test_feed_pane_concept(tmp: Path) -> None:
    """F74: /feed/NAME gives the session's feed, /concept/ID a concept's local page
    copy (sandboxed), and /act runs the new actions (interrupt, quick_ask)."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'queue': []})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    entries = [{'kind': 'say', 'text': 'hi'}]
    try:
        with mock.patch.object(U, 'feed', side_effect=lambda n: {'ok': True, 'name': n, 'entries': entries}):
            r = json.loads(get(f'{base}/feed/c6?t={token}')[1])
        eq((r['name'], r['entries']), ('c6', entries), "/feed/c6 is c6's feed")
        eq(get(f'{base}/concept/K5?t={token}')[0], 404, 'no copy: 404')
        S.C.notes('concepts', 'K5.html').write_text('<h1>Option A</h1>', encoding='utf-8')
        with urllib.request.urlopen(f'{base}/concept/K5?t={token}', timeout=10) as resp:
            body, csp = resp.read(), resp.headers.get('Content-Security-Policy', '')
        eq((body, csp), (b'<h1>Option A</h1>', 'sandbox allow-scripts'), 'the copy, sandboxed')
        eq(get(f'{base}/concept/K5')[0], 403, 'and only with the token')
        ran = []

        def no_send(t):
            raise AssertionError(f'B139: a quick ask reached c1: {t!r}')
        with mock.patch.object(U, 'SEND', [no_send]), \
                mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 7 is starting'))[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'quick_ask', 'args': {'key': 'needs', 'wait': False}})
        eq((out['ok'], out['name'], ran), (True, 'c7', [['control', '--new', '--no-wait', '--ask', 'what needs me?', '--no-feed']]),
           'B139: a quick ask through /act starts a new control session with it, named for the page to open')
        typed = []
        from agent_runner import slots as SLT
        with mock.patch.object(U, 'hidden_inbox', return_value=Path('/x/control6.in')), \
                mock.patch('agent_runner.plat.WINDOWS', False), \
                mock.patch.object(SLT, 'send_fifo_raw', lambda p, b: typed.append((p.name, b)) or True):
            code, out = post(f'{base}/act?t={token}', {'name': 'interrupt', 'args': {'session': 'c6'}})
        eq((out['ok'], typed), (True, [('control6.in', b'\x1b')]), 'interrupt c6 through /act')
    finally:
        srv.stop()


def test_control_rows(tmp: Path) -> None:
    """F73: a snapshot holding control session c6 and an idle s2: the page gives cN rows c1-like tabs (terminal,
    session) with no open button, an idle slot's terminal tab says it is idle, /terminal/c6 finds c6's pane by its
    tag, and the claude.ai copy lists c6 as a control session, not a slot."""
    from agent_runner import page_copy as PC
    fake_repo(tmp)
    snap = {'project': 'proj', 'at': 'now', 'status': ['run up'], 'queue': [], 'needs': [], 'concepts': [], 'log': [],
            'sessions': [
                {'name': 'c1', 'task': '', 'title': 'control session', 'minutes': None, 'state': 'live', 'files': [],
                 'link': 'https://claude.ai/code/c1', 'terminal': ''},
                {'name': 'c6', 'task': '', 'title': 'R43 site deploy', 'minutes': None, 'state': 'live', 'files': [],
                 'link': 'https://claude.ai/code/c6x', 'terminal': ''},
                U.idle_row('s2')]}
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: snap)
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        page = get(f'{base}/?t={token}')[1]
        eq([s['name'] for s in json.loads(get(f'{base}/snapshot?t={token}')[1])['sessions']], ['c1', 'c6', 's2'],
           'the snapshot carries c6 and the idle s2')
        for part in (b"S.snap.sessions.filter(s=>/^c\\d+$/.test(s.name))",  # F133: then put in the kept order
                     b"const working_=()=>slots().filter(s=>s.task)", b'<b>Idle</b>'):
            check(part in page, f'the app lists cN as a chat, a slot on a task as working: {part.decode()}')
        asked = []
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.plat.WINDOWS', False), \
                mock.patch('agent_runner.attach.session_socket', lambda n: asked.append(n)):
            r = json.loads(get(f'{base}/terminal/c6?t={token}')[1])
        eq(asked, ['c6'], "c6's terminal looks up control session 6's socket")
        check(not r['ok'] and 'c6 is not up' in r['out'], 'and says when it has none', r)
    finally:
        srv.stop()
    copy = PC.page_copy_html(snap)
    check('<span class="r">c6</span><span>R43 site deploy</span><a' in copy and 'https://claude.ai/code/c6x' in copy,
          'the copy lists c6 with its title and session link', copy)
    check('s2 is idle: nothing running' in copy, 'and the idle s2 as idle', copy)
    check('open it from the run page' not in copy, 'with no open-it hint on c6 or s2', copy)


def test_page(tmp: Path) -> None:
    """F79: the run app as its design has it: the sidebar (New chat, Home, Status, Plan, Chats, Agents
    working, the machine and usage), Home's parts, threads, the message box, the Plan, light and dark, no
    scrollbars, the container layout, its own 'ar' mark, and no direct edit of tasks."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        page = get(f'http://127.0.0.1:{srv.server_address[1]}/?t={token}')[1].decode()
    finally:
        srv.stop()
    for part in ('New chat', "['home','Home'],['status','Status'],['plan','Plan'],['concepts','Concepts'],['settings','Settings']",
                 'Style rules: docs/STYLE.md',
                 '<div class="shead row"><span>Chats</span>', '<div class="shead">Agents working</div>', 'class="livedot"',
                 'S.snap.machine', 'usage ${esc(use)}',  # the sidebar
                 'side.open', 'class="scrim"', 'data-menu',  # a drawer on a phone
                 'greeting()', 'How can I help with the run?', 'data-quick="since">', 'Since my last look',
                 'data-quick="needs">', 'What needs me', 'data-about="new">', 'Add a task',  # Home
                 '>Needs you<', 'data-ans=', 'data-later=', 'data-needchat=', 'data-needdrop=', '>Working now<', '>Up next<',
                 'data-about="plan:', 'Release when they land', 'Release now',
                 "outbox('answer'", "outbox('shelve'", "outbox('release'", "newChat('quick_ask'", "outbox('chat_to'",
                 "newChat('new_control'", "act('interrupt'",  # F137: through the outbox
                 '.a{display:grid;gap:8px;font:400 16.5px/1.6 var(--serif)', '.u{justify-self:end',  # threads
                 'Ran ${m.steps.length} step', 'Working on it…', "tq('feed/'",
                 'Goes straight to this agent', "tq('upload?name='", 'type="file" multiple', 'About: <b>',  # the box
                 "e.key==='Enter'&&!e.shiftKey", 'DRAFT_KEY', 'store.set(DRAFT_KEY(boxKey())',
                 'data-pick=', 'data-about="concept:', 'View ${I.ext}', "tq('concept/'",  # the Concepts view
                 '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])', ':root[data-theme="dark"]',
                 '*{box-sizing:border-box;scrollbar-width:none}', '*::-webkit-scrollbar{display:none}',
                 'container-type:inline-size', '@container (min-width:760px)', '<div class="logo">${esc(PN().charAt(0)'):
        check(part in page, f'the page has {part}')
    for gone in ('Anthropic', 'Claude', 'plan_change', 'direct edit', 'JetBrains Mono', '/*THEMES*/'):
        check(gone not in page, f'the page has no {gone}')


LOGIC_DRIVER = """const m=require(process.argv[2]);
const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(([fn,...a])=>m[fn](...a))));
"""


def logic_js(cases: list) -> list:
    """Run the page's pure script (<script id="logic">) in node on `cases` ([function name, *args] each)."""
    page = W.PAGE.read_text(encoding='utf-8')
    js = page.split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'logic.js').write_text(js, encoding='utf-8')
        (Path(d) / 'driver.js').write_text(LOGIC_DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'driver.js'), str(Path(d) / 'logic.js')], input=json.dumps(cases),
                           capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page script', r.stderr[-800:])
    return json.loads(r.stdout or '[]') or [None] * len(cases)


def test_logic(tmp: Path) -> None:
    """F79: the page's pure parts, driven in node: a feed as a conversation (tool steps folded into the reply
    after them), the working mark, the answer buttons, the queue in plain words, and what the box sends."""
    if not shutil.which('node'):
        print('  (no node here: the page script test is skipped)')
        return
    feed = [{'kind': 'you', 'text': 'fix it'}, {'kind': 'tool', 'text': 'Read(a.py)'},
            {'kind': 'out', 'text': '12 lines'}, {'kind': 'tool', 'text': 'Edit(a.py)'},
            {'kind': 'say', 'text': 'Fixed.'}, {'kind': 'you', 'text': 'thanks'}, {'kind': 'tool', 'text': 'Bash(ls)'}]
    sessions = [{'name': 's2', 'task': 'F1', 'minutes': 12}]
    got = logic_js([
        ['threadMsgs', feed],
        ['working', feed], ['working', feed[:5]], ['working', feed + [{'kind': 'out', 'text': 'interrupted'}]],
        ['working', []],
        ['answerOpts', {'label': 'CONFIRM', 'ask': 'Works?'}],
        ['answerOpts', {'label': 'DECIDE', 'options': ['ship it', 'wait']}],
        ['answerOpts', {'label': 'BLOCKED', 'ask': 'Log in'}],
        ['planWords', {'id': 'F1', 'state': 'running'}, sessions],
        ['planWords', {'id': 'B2', 'state': 'after', 'after_title': 'F1 Board page'}, sessions],
        ['planWords', {'id': 'B3', 'state': 'blocked'}, sessions],
        ['planWords', {'id': 'B4', 'state': 'ready'}, sessions],
        ['compose', None, 'hello', []],
        ['compose', {'kind': 'new'}, 'dark mode toggle', []],
        ['compose', {'kind': 'plan', 'id': 'F76', 'title': 'Terminal app'}, 'make it first', ['/r/.runner/uploads/a.png']],
        ['compose', None, '', ['/r/.runner/uploads/a.png', '/r/.runner/uploads/b.txt']],
        ['compose', {'kind': 'need', 'id': 'R6', 'title': 'Windows status'}, 'what do I check?', []],
        ['usageOf', ['run up: 3 slots', 'usage: session 40%, week 12%']],
        ['chatName', {'name': 'c1', 'title': 'control session'}], ['chatName', {'name': 'c6', 'title': 'Site deploy'}],
        ['chatName', {'name': 'c7', 'title': 'control session'}],
        ['planWords', {'id': 'F8', 'state': 'after', 'after_title': 'V5 Release'}, sessions],
    ])
    msgs = got[0]
    eq([m['w'] for m in msgs], ['u', 'a', 'u', 'a'], 'your words, its reply, yours, its steps so far')
    eq((msgs[1]['text'], [s['tool'] for s in msgs[1]['steps']], msgs[1]['steps'][0]['out']),
       ('Fixed.', ['Read(a.py)', 'Edit(a.py)'], '12 lines'), 'the steps before a reply fold into it, with their output')
    eq((msgs[3]['text'], len(msgs[3]['steps'])), ('', 1), 'steps with no reply yet stand alone')
    eq(got[1:5], [True, False, False, False], 'working while its last entry is a step, not after a reply or an interrupt')
    eq(got[5], ['Yes', 'No'], 'a CONFIRM answers Yes or No')
    eq(got[6], ['Ship it', 'Wait'], "a DECIDE's options are its buttons")
    eq(got[7], [], 'a BLOCKED has no answer buttons (Chat and Later only)')
    eq(got[8:12], ['s2 is on it · 12 min', 'Waits for F1 Board page', 'Waits for you',
                   'Ready to start when a slot is free'], 'the queue in plain words')
    eq(got[12], 'hello', 'plain words go as typed')
    eq(got[13], 'Add a task: dark mode toggle', 'Add a task says so')
    eq(got[14], 'About F76 (Terminal app): make it first\n\nAttached: /r/.runner/uploads/a.png',
       'the About line names the task; an attachment goes as its path')
    eq(got[15], 'Attached: /r/.runner/uploads/a.png, /r/.runner/uploads/b.txt', 'attachments alone')
    eq(got[16], 'About R6 (Windows status), which needs me: what do I check?',
       "a Needs you item's Chat talks about it with c1, not as its answer")
    eq(got[17], 'session 40%, week 12%', 'the usage line for the sidebar')
    eq(got[18:21], ['Project chat', 'Site deploy', 'Chat 7'], 'chats by their titles, c1 the project chat')
    eq(got[21], 'Waits for V5 Release', "B115: an after shows the id and its short title (the model's after_title)")


def test_extras(tmp: Path) -> None:
    """F79: the app's snapshot carries this machine's name and each concept's options, read from its copy."""
    fake_repo(tmp)
    copy = S.C.notes('concepts', 'K5.html')
    copy.write_text('<h1>Phone run page</h1><p>Three ways.</p><h2>A: tabs</h2><p>x</p><h2>B: drawer (recommended)'
                    '</h2><p>y</p><h2>C: cards</h2>', encoding='utf-8')
    snap = W.with_extras({'concepts': [{'id': 'K5', 'concept': 'K5', 'copy': str(copy)},
                                       {'id': 'K6', 'concept': 'K6', 'copy': ''}]})
    eq(snap['machine'], W.socket.gethostname(), "the machine's name")
    eq(snap['concepts'][0]['options'], [{'name': 'A: tabs', 'rec': False}, {'name': 'B: drawer (recommended)', 'rec': True},
                                        {'name': 'C: cards', 'rec': False}], 'a button per option, the recommended marked')
    eq(snap['concepts'][1]['options'], [], 'no copy: no option buttons (Chat and View still)')


def test_diff(tmp: Path) -> None:
    """F75: /diff/s1 is slot s1's work so far against the shared branch, committed or not."""
    repo = fake_repo(tmp)
    home = tmp / 'runs'
    home.mkdir()
    git(repo, 'worktree', 'add', '-q', '--detach', str(home / 's1'), 'HEAD')
    (home / 's1' / 'a.py').write_text('x = 1\n', encoding='utf-8')
    git(home / 's1', 'add', 'a.py')
    git(home / 's1', 'commit', '-qm', 'a')
    (home / 's1' / 'b.py').write_text('y = 2\n', encoding='utf-8')
    git(home / 's1', 'add', 'b.py')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        with mock.patch.object(S, 'SLOTS_DIR', home):
            r = json.loads(get(f'{base}/diff/s1?t={token}')[1])
            check(r['ok'] and '+x = 1' in r['text'] and '+y = 2' in r['text'], 'the diff has the commit and the staged file', r)
            r = json.loads(get(f'{base}/diff/s2?t={token}')[1])
            check(not r['ok'] and 'no worktree' in r['out'], 'a slot with no worktree says so', r)
            r = json.loads(get(f'{base}/diff/c1?t={token}')[1])
            check(not r['ok'] and 'not a slot' in r['out'], 'a control session has no diff', r)
        eq(get(f'{base}/diff/s1')[0], 403, 'and only with the token')
    finally:
        srv.stop()


TERM_DRIVER = """const m=require(process.argv[2]);
const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(([fn,...a])=>m[fn](...a))));
"""


def test_views(tmp: Path) -> None:
    """F81: /term serves the terminal view (F75's page, in [ui] theme) on the same server; the run app has a
    Terminal view switch in its sidebar (the drawer on a phone), the terminal view an App view link and the key T;
    the browser remembers the choice, and [ui] web picks the view for a browser that never chose."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        code, body = get(f'{base}/term?t={token}')
        term = body.decode()
        eq(code, 200, '/term is served')
        eq(get(f'{base}/term')[0], 403, 'and only with the token')
        app = get(f'{base}/?t={token}')[1].decode()
        with mock.patch.dict(S.C.raw['ui'], {'web': 'terminal'}):
            eq(W.web_view(), 'terminal', '[ui] web = "terminal" is read')
            app_t = get(f'{base}/?t={token}')[1].decode()
    finally:
        srv.stop()
    for part in ('<div class="top">', 'id="appview"', 'data-viewsw="app"', '<b class="pk">T</b> App view',
                 "if(k==='T')return[['appview']]", '<span class="b">T</span>      App view',
                 "VIEW_KEY='agent-runner.view'", "localStorage.setItem(VIEW_KEY,v)", 'Keybindings'):
        check(part in term, f'the terminal view has {part}')
    check('/*THEME_CSS*/' not in term and '"themes": {' in term, 'the terminal view carries [ui] theme and every theme')
    for part in ('data-viewsw="terminal"', '${I.term}Terminal view', 'href="term${esc(location.search)}"',
                 "VIEW_KEY='agent-runner.view'", "localStorage.setItem(VIEW_KEY,x.dataset.viewsw)",
                 "(v||WEB_VIEW)==='terminal')location.replace('term'+location.search)"):
        check(part in app, f'the run app has {part}')
    check('const WEB_VIEW="app"' in app, 'by default the link opens the run app')
    check('const WEB_VIEW="terminal"' in app_t, '[ui] web = "terminal": a browser that never chose opens /term')
    # the sidebar's switch sits in side(), which draws the drawer too
    side = app.split('function side(){', 1)[1].split('\nfunction ', 1)[0]
    check('data-viewsw="terminal"' in side, 'the switch is in the sidebar (and so the drawer)')
    (repo / 'runner.toml').write_text('[ui]\nweb = "tabs"\n', encoding='utf-8')
    try:
        CF.Config(repo)
        check(False, '[ui] web = "tabs" is refused')
    except SystemExit as e:
        check('[ui] web must be one of app, terminal' in str(e), '[ui] web is checked', str(e))
    if not shutil.which('node'):
        print('  (no node here: the terminal view key test is skipped)')
        return
    js = W.TERM.read_text(encoding='utf-8').split('<script id="keys">', 1)[1].split('</script>', 1)[0]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'keys.js').write_text(js, encoding='utf-8')
        (Path(d) / 'driver.js').write_text(TERM_DRIVER, encoding='utf-8')
        ctx = {'panel': 3, 'focusMain': False, 'tab': '', 'tabs': [], 'it': {}, 'typing': False}
        ev = lambda k: {'key': k, 'ctrl': False, 'meta': False, 'shift': False, 'alt': False}  # noqa: E731
        cases = [['route', ctx, ev('T')], ['route', ctx, ev('t')], ['route', dict(ctx, typing=True), ev('T')]]
        r = subprocess.run(['node', str(Path(d) / 'driver.js'), str(Path(d) / 'keys.js')], input=json.dumps(cases),
                           capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the terminal view script', r.stderr[-800:])
    got = json.loads(r.stdout or '[]') or [None] * 3
    eq(got[0], [['appview']], 'T: App view')
    eq(got[1], [['theme']], 't: the theme picker')
    eq(got[2], [], 'T while typing is a letter')


def test_new_chat(tmp: Path) -> None:
    """F84: a + on the Chats heading row starts a new chat (new_control through /act, which runs control --new),
    and the top bar's New chat has its own inline new-chat icon."""
    fake_repo(tmp)
    page = W.page_html().decode()
    check('<div class="shead row"><span>Chats</span><button class="shadd" data-new' in page,
          'the + sits at the end of the Chats heading row')
    check('data-new aria-label="New chat" title="New chat">${I.newchat}' in page and 'newchat:`<svg' in page,
          'the top bar keeps New chat, with the new-chat icon')
    check("newChat('new_control',{},'New chat')" in page and "outbox(name,{...args,wait:false}" in page,
          'data-new sends new_control through the outbox, without waiting (F137)')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    calls = []
    try:
        link = 'https://claude.ai/code/session_abc'
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, f'started c7: {link}'))[1]]):
            code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                             {'name': 'new_control', 'args': {}})
        eq((code, out.get('ok'), out.get('link')), (200, True, link), 'new_control answers with the new link')
        eq(calls, [['control', '--new']], 'its endpoint runs control --new')
    finally:
        srv.stop()


MOVES_DRIVER = r"""const {queueMoves}=require(process.argv[2]);
const ids=q=>q.map(t=>t.id).join('');
const Q=s=>[...s].map(id=>({id,title:id}));
const tick=()=>new Promise(r=>setTimeout(r,0));
async function run(order,fail){
  const S={snap:{status:[],queue:Q(order)},cur:{3:0}},out={seen:[],sent:[],toasts:[]},waits=[];
  const m=queueMoves({S,toast:(t,bad)=>out.toasts.push([t,!!bad]),render:()=>{},
    send:(tid,where,other)=>{out.sent.push(`${tid} ${where} ${other}`);return new Promise(r=>waits.push(r))},
    fetch:()=>Promise.resolve({status:[],queue:Q(fail?order:'BCDA')})});
  for(let n=0;n<3;n++){m.press(1);out.seen.push([ids(S.snap.queue),S.cur[3],out.sent.length])}
  S.snap=m.snap({status:['new'],queue:Q(order+'E')});  // a stale snapshot, with a new task, while moves pend
  out.during=[ids(S.snap.queue),S.snap.status[0]];
  for(let n=0;n<3;n++){await tick();if(waits[n])waits[n](fail&&n===0?{ok:false,out:'no such task'}:{ok:true})}
  await m.idle();await tick();await tick();
  out.after=[ids(S.snap.queue),S.cur[3],m.pending()];
  return out;
}
(async()=>{process.stdout.write(JSON.stringify([await run('ABCD',false),await run('ABCD',true)]))})();
"""


def test_term_moves(tmp: Path) -> None:
    """B117: Shift+J / Shift+K in the terminal view's [3] Queue are optimistic: the order and the selection change
    at once, the plan moves go in the background in order, a snapshot meanwhile keeps the local order, and a
    failed move is toasted and the server order taken."""
    page = W.TERM.read_text(encoding='utf-8')
    check('function reorder(step){MOVES.press(step)}' in page and 'S.snap=MOVES.snap(snap)' in page,
          'reorder and live snapshots go through queueMoves')
    if not shutil.which('node'):
        print('  (no node here: the queue move test is skipped)')
        return
    js = page.split('<script id="moves">', 1)[1].split('</script>', 1)[0]
    (tmp / 'moves.js').write_text(js, encoding='utf-8')
    (tmp / 'driver.js').write_text(MOVES_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'moves.js')], capture_output=True, text=True,
                       timeout=60)
    check(r.returncode == 0, 'node runs the queue move script', r.stderr[-800:])
    ok, bad = json.loads(r.stdout or '[{}, {}]')
    eq(ok.get('seen'), [['BACD', 1, 0], ['BCAD', 2, 0], ['BCDA', 3, 0]],
       'three fast J presses: order and selection change before any move is sent or answered')
    eq(ok.get('during'), ['BCDAE', 'new'],
       'a snapshot while moves are pending keeps the local order; its new task and the rest are taken')
    eq(ok.get('sent'), ['A after B', 'A after C', 'A after D'], 'the three moves are sent in order')
    eq(ok.get('toasts'), [], 'no toast per press')
    eq(ok.get('after'), ['BCDA', 3, 0], 'once drained the server order is taken, the selection on the task')
    eq(bad.get('sent'), ['A after B'], 'after a failed move the rest are not sent')
    check(len(bad.get('toasts', [])) == 1 and bad['toasts'][0][1] and 'no such task' in bad['toasts'][0][0],
          'a failed move is toasted', bad.get('toasts'))
    eq(bad.get('after'), ['ABCD', 0, 0], 'a failed move takes the server order back, the selection on the task')


def test_page_copy_publish(tmp: Path) -> None:
    """B122: a run change publishes the run page copy through a one-shot `claude -p` with only the Artifact tool,
    never by typing into a control session's pane; at most once every PAGE_COPY_EVERY s, only when the page
    changed apart from its clock and log; a one-shot that cannot publish stops the copy, with no c1 fallback."""
    from agent_runner import page_copy as PC, slots as SL
    fake_repo(tmp)
    keys = []
    runs = []
    rc = [0]
    real_run = subprocess.run

    def fake_run(argv, **kw):
        if '--tools' not in argv:  # the run's own git and the like
            return real_run(argv, **kw)
        runs.append((argv, kw))
        out = '' if rc[0] else 'https://claude.ai/artifact/0f3c-copy\n'
        return subprocess.CompletedProcess(argv, rc[0], out, 'boom' if rc[0] else '')

    def snap(t: str, task: str = 'F1', minutes: int = 3, log: str = 'a line') -> dict:
        return {'project': 'proj', 'at': t, 'up': True, 'status': [f'run up · usage {minutes}%'],
                'sessions': [{'name': 'c1', 'state': 'live', 'link': 'https://claude.ai/code/c1'},
                             {'name': 's1', 'task': task, 'title': 'a task', 'minutes': minutes,
                              'state': 'running', 'link': ''}],
                'queue': [], 'needs': [], 'concepts': [], 'log': [log], 'release': ''}

    PC.PAGE_COPY_AT[0], PC.PAGE_COPY_FAILS[0], PC.PAGE_COPY_OFF[0] = 0.0, 0, ''
    tick = lambda now, s: PC.page_copy_tick(now=now, snap=s, background=False)  # noqa: E731
    with mock.patch.object(PC, 'remote_on', lambda: True), \
            mock.patch.object(PC, 'C', S.C), mock.patch.object(PC, 'ROOT', S.ROOT), \
            mock.patch.object(PC.sp, 'run', fake_run), \
            mock.patch.object(SL, 'send_fifo', lambda *a, **k: keys.append(a) or True), \
            mock.patch.object(SL, 'send_fifo_raw', lambda *a, **k: keys.append(a) or True), \
            mock.patch('agent_runner.control.control_live', lambda *a, **k: keys.append(('live', a)) or 4242), \
            mock.patch('agent_runner.control.control_type', lambda *a, **k: keys.append(('type', a)) or True), \
            mock.patch.object(SL.MUX, 'send', lambda *a, **k: keys.append(('mux', a)) or True, create=True):
        check(tick(1000.0, snap('10:00')), 'a run change publishes the copy')
        argv, kw = runs[0]
        eq(argv[1:2], ['-p'], 'a one-shot headless session')
        eq(argv[argv.index('--tools') + 1], 'Artifact', 'with only the Artifact tool')
        check('--remote-control' not in argv and '--resume' not in argv, 'never a control session', argv)
        eq(kw['env'].get('CLAUDE_CODE_ARTIFACT'), '1', 'the Artifact tool turned on headless')
        check(str(PC.page_copy_file()) in argv[2], 'the prompt names the file', argv[2])
        eq(PC.page_copy_url(), 'https://claude.ai/artifact/0f3c-copy', 'the URL the one-shot published to is kept')
        for t in (1060.0, 1300.0, 1599.0):
            check(not tick(t, snap(f'{t}', task='B2')), f'debounced: no publish {t - 1000:.0f}s after the last')
        eq(len(runs), 1, 'one publish in the first PAGE_COPY_EVERY s')
        check(tick(1000.0 + PC.PAGE_COPY_EVERY, snap('10:10', task='B2')), 'the change publishes once that passed')
        check('0f3c-copy' in runs[-1][0][2], 'to the same URL', runs[-1][0][2])
        check(not tick(5000.0, snap('11:00', task='B2', minutes=40, log='another line')),
              'only the clock, minutes, usage and log changed: no publish')
        paused = snap('11:01', task='B2')
        paused['status'] = ['run paused · usage 3%']
        check(tick(5000.0 + PC.PAGE_COPY_EVERY, paused), 'a run that pauses is a change: published')
        runs.pop()
        rc[0] = 1
        for i, t in enumerate((7000.0, 8000.0, 9000.0)):
            check(tick(t, snap(f'{t}', task=f'T{i}')), f'publish {i + 1} is tried')
        check(PC.PAGE_COPY_OFF[0], 'three failed one-shots in a row stop the copy')
        check(not tick(20000.0, snap('later', task='T9')), 'a stopped copy publishes nothing more')
        eq(len(runs), 5, 'and starts no more one-shots')
        PC.PAGE_COPY_AT[0], PC.PAGE_COPY_FAILS[0], PC.PAGE_COPY_OFF[0] = 0.0, 0, ''
        with mock.patch.object(PC, 'page_copy_argv', lambda path, url, icon='dashboard': ['/nonexistent/agent-b122']):
            check(tick(30000.0, snap('x', task='Z1')), 'a publish is tried with no agent to start')
        check('cannot be started' in PC.PAGE_COPY_OFF[0], 'no agent to start: the copy stops', PC.PAGE_COPY_OFF[0])
    eq(keys, [], 'no run change sends keys to any pane or FIFO')
    check(not hasattr(PC, 'c1_send'), 'the copy has no way to type into c1')
    src = Path(PC.__file__).read_text(encoding='utf-8')
    for name in ('send_fifo', 'control_type', 'control_live', 'send_keys', 'MUX'):
        check(name not in src, f'page_copy.py never calls {name}')
    PC.PAGE_COPY_OFF[0] = ''


PARKED_TODO = TODO + """
### Parked
- [ ] **F83** Big future work for a person to schedule | files: p.py
"""


def test_parked(tmp: Path) -> None:
    """B118: a parked task (level later, TODO.md's Parked section) is in its own Parked group on the run app and
    the terminal-style page, never says Ready, and Unpark (plan edit ID --pri normal) moves it out of Parked."""
    repo = fake_repo(tmp)
    todo = repo / 'plan' / 'TODO.md'
    todo.write_text(PARKED_TODO, encoding='utf-8')
    q = {t['id']: t for t in U.queue_rows(todo.read_text(encoding='utf-8').splitlines())}
    eq(q['F83']['state'], 'parked', 'the model gives a task under Parked state parked')
    app, term = W.page_html().decode(), W.TERM.read_text(encoding='utf-8')
    for part in ('<div class="sec">Parked<span class="ln"></span></div>', "Parked: a run won't start it",
                 'data-unpark="${esc(q.id)}">Unpark</button>', 'data-about="plan:${esc(q.id)}">Chat</button>',
                 "outbox('unpark',{tid:id}", "q.state!=='running'&&q.state!=='parked'"):
        check(part in app, f'the run app has {part}')
    for part in ("Parked: a run won't start it", '<i class="chip park">parked</i>', "act('unpark',{tid:it.id}",
                 'items:()=>queueItems(S.snap.queue)', 'unpark (a Parked task)'):
        check(part in term, f'the terminal-style page has {part}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                         {'name': 'unpark', 'args': {'tid': 'F83'}})
    finally:
        srv.stop()
    check(code == 200 and out.get('ok'), 'the unpark act ran plan edit', out)
    eq(out.get('argv', [])[-4:], ['edit', 'F83', '--pri', 'normal'], 'unpark is plan edit ID --pri normal')
    after = todo.read_text(encoding='utf-8')
    parked = after.split('### Parked', 1)[1] if '### Parked' in after else ''
    check('F83' in after and 'F83' not in parked, 'F83 is out of Parked', after)
    q = {t['id']: t for t in U.queue_rows(after.splitlines())}
    eq((q['F83']['state'], q['F83']['pri']), ('ready', 'normal'), 'and is ready, at level normal')
    eq(U.act('unpark', tid='not an id')['ok'], False, 'unpark takes a task id only')
    if not shutil.which('node'):
        print('  (no node here: the Parked group script test is skipped)')
        return
    rows = [{'id': 'F83', 'state': 'parked'}, {'id': 'F1', 'state': 'ready'}, {'id': 'B2', 'state': 'after'}]
    got = logic_js([['planWords', {'id': 'F83', 'state': 'parked'}, []], ['queueGroups', rows]])
    eq(got[0], "Parked: a run won't start it", 'a parked row says so on the run app')
    check('Ready' not in got[0], 'and never Ready')
    eq([[r['id'] for r in g] for g in got[1]], [['F1', 'B2'], ['F83']], 'the Queue, then the Parked group')
    js = term.split('<script id="keys">', 1)[1].split('</script>', 1)[0]
    ev = lambda k: {'key': k, 'ctrl': False, 'meta': False, 'shift': False, 'alt': False}  # noqa: E731
    ctx = {'panel': 3, 'focusMain': False, 'tab': '', 'tabs': [], 'typing': False,
           'it': {'newtask': False, 'parked': True}}
    ready = dict(ctx, it={'newtask': False, 'parked': False})
    cases = [['parkedLast', {'queue': rows}], ['queueItems', rows],
             ['route', ctx, ev('U')], ['route', ctx, ev('E')], ['route', ctx, ev('J')], ['route', ctx, ev('p')],
             ['route', ready, ev('U')], ['footer', ctx, []]]
    (tmp / 'keys.js').write_text(js, encoding='utf-8')
    (tmp / 'driver.js').write_text(TERM_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'keys.js')], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the terminal-style page script', r.stderr[-800:])
    got = json.loads(r.stdout or '[]') or [None] * len(cases)
    eq([t['id'] for t in got[0]['queue']], ['F1', 'B2', 'F83'], 'parked tasks go after the rest')
    eq([t['id'] for t in got[1]], ['F1', 'B2', '+', 'F83'], '[3]: the queue, new task, then the Parked group')
    eq(got[2], [['act', 'unpark']], 'U on a parked row unparks it')
    eq(got[3], [['tabto', 'chat edit']], 'E: chat edit, as for other rows')
    eq((got[4], got[5]), ([], []), 'no J/K reorder or priority toggle on a parked row')
    eq(got[6], [], 'U does nothing on a row that is not parked')
    here = [k for k, _ in got[7]['here']]
    check('U' in here and 'E' in here, 'the key hints show U unpark and E chat edit', got[7])


def test_concepts_view(tmp: Path) -> None:
    """F87: the sidebar has Concepts (after Plan, with a count); its view lists the snapshot's concepts with their
    buttons (an option each, Chat, New chat, View), says no concept waits when none does, and its + queues a new
    concept as plan add K through /act; the Plan view no longer lists concepts."""
    fake_repo(tmp)
    app = W.page_html().decode()
    for part in ("['plan','Plan'],['concepts','Concepts']", 'count={home:needs,concepts:cn}',
                 'concepts:conceptsHTML', "concepts:'Concepts'", 'data-kadd aria-label="New concept"',
                 'data-kform', 'newConceptReq(S.kText)', 'cs.map(conceptCard)'):
        check(part in app, f'the run app has {part}')
    plan = app.split('function planHTML(){', 1)[1].split('\n}', 1)[0]
    check('concept' not in plan.lower(), 'the Plan view lists no concepts', plan)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                         {'name': 'plan_add', 'args': {'kind': 'K', 'text': 'a dark mode for the run app'}})
    finally:
        srv.stop()
    eq(out.get('argv', [])[-4:], ['plan', 'add', 'K', 'a dark mode for the run app'], "+'s request is plan add K TEXT")
    if not shutil.which('node'):
        print('  (no node here: the Concepts view script test is skipped)')
        return
    c = {'id': 'K5', 'concept': 'K5', 'title': 'Lazy layout', 'copy': '/n/K5.html',
         'options': [{'name': 'A: tabs', 'rec': False}, {'name': 'B: drawer (recommended)', 'rec': True}]}
    got = logic_js([['conceptButtons', c], ['conceptButtons', {'id': 'K6', 'options': []}],
                    ['newConceptReq', '  a dark mode  '], ['newConceptReq', '   '],
                    ['queuedId', 'added K12 a dark mode'], ['queuedId', 'ok']])
    eq([b['label'] for b in got[0]], ['A: tabs', 'B: drawer', 'Chat', 'New chat', 'View'],
       "a concept's buttons: its options (no '(recommended)'), Chat, New chat, View")
    eq([b.get('rec', False) for b in got[0]], [False, True, False, False, False], 'the recommended option stands out')
    eq([b['label'] for b in got[1]], ['Chat', 'New chat'], 'no copy and no page: no options and no View')
    eq(got[2], {'name': 'plan_add', 'args': {'kind': 'K', 'text': 'a dark mode'}}, '+ sends plan add K TEXT')
    eq(got[3], None, 'an empty box sends nothing')
    eq(got[4:], ['K12', ''], 'the queued id, from plan add\'s output')
    check("NO_CONCEPT='No concept waits for a pick.'" in app and '${NO_CONCEPT}' in app,
          'the empty state says no concept waits')


def test_esc_ctrl_c(tmp: Path) -> None:
    """B116: on the run app Esc never goes back while interrupting (B120: in the box it interrupts a working chat,
    out of it only goes back); Ctrl+C interrupts the open
    chat while it works (not over selected text), and a small Stop button sits by the working mark."""
    page = W.page_html().decode()
    start = page.index("document.addEventListener('keydown'")
    handler = page[start:page.index('\n});', start)]
    lines = handler.splitlines()
    esc_lines = [ln for ln in lines if "e.key==='Escape'" in ln]
    check(len(esc_lines) >= 2, 'the keydown handler has its Esc branches', esc_lines)
    # B120: in the message box Esc interrupts a working chat (after the menu closes); out of it, never
    out_of_box = handler[handler.index("if(e.key==='Escape'&&S.sel.length)"):]
    for ln in esc_lines:
        if ln.strip() in out_of_box:
            check('interrupt' not in ln, 'an Esc branch out of the box sends no interrupt', ln)
    esc_int = [ln for ln in esc_lines if 'interrupt' in ln]
    check(len(esc_int) == 1 and 'shownSession()' in esc_int[0] and 'busy(n)' in esc_int[0] and 'S.thread=null' not in esc_int[0],
          'Esc in the box interrupts only a working chat, and does not go back', esc_int)
    check(any("e.key==='Escape'" in ln and 'blur()' in ln for ln in lines), 'Esc in the box leaves it')
    check(any("e.key==='Escape'&&S.thread&&" in ln and 'S.thread=null' in ln for ln in lines), 'Esc out of the box goes back')
    ctrl = [ln for ln in lines if 'e.ctrlKey' in ln]
    check(len(ctrl) == 1 and "act('interrupt',{session:n})" in ctrl[0] and 'busy(n)' in ctrl[0]
          and '!selectedText(' in ctrl[0], 'Ctrl+C interrupts the working chat, not over selected text', ctrl)
    check('Working on it… · Ctrl+C interrupts<button type="button" class="btn mini" data-stop="${esc(n)}">Stop</button>'
          in page, 'the working mark says Ctrl+C interrupts and has a Stop button')
    check("if(x=q('[data-stop]')){const n=x.dataset.stop||shownSession();if(n)act('interrupt',{session:n});return}" in page,
          'Stop interrupts the session it stands by')
    # B124: the terminal-style page, the same way: route()'s Esc branches never interrupt, Ctrl+C does
    term = W.TERM.read_text(encoding='utf-8')
    js = term.split('<script id="keys">', 1)[1].split('</script>', 1)[0]
    route = js.split('function route(c,e){', 1)[1].split('\n}\n', 1)[0]
    term_esc = [ln for ln in route.splitlines() if "'Escape'" in ln]
    check(len(term_esc) >= 3, "the term page's route has its Esc branches", term_esc)
    for ln in term_esc:
        check('interrupt' not in ln, "a term page Esc branch sends no interrupt", ln)
    check('<span class="b">Ctrl+C</span> interrupts while it works' in term, 'the term help line says Ctrl+C interrupts')
    if not shutil.which('node'):
        print('  (no node here: the terminal-style page Ctrl+C test is skipped)')
        return
    ev = lambda k, ctrl=False: {'key': k, 'ctrl': ctrl, 'meta': False, 'shift': False, 'alt': False}  # noqa: E731
    box = {'panel': 2, 'focusMain': True, 'tab': 'chat', 'tabs': ['chat'], 'it': {}, 'typing': True,
           'chatBox': True, 'busy': True, 'selected': False}
    main = dict(box, typing=False, chatBox=False)
    cases = [['route', box, ev('Escape')], ['route', main, ev('Escape')], ['route', box, ev('c', True)],
             ['route', main, ev('c', True)], ['route', dict(box, selected=True), ev('c', True)],
             ['route', dict(box, busy=False), ev('c', True)], ['footer', box, []], ['footer', main, []]]
    (tmp / 'keys.js').write_text(js, encoding='utf-8')
    (tmp / 'driver.js').write_text(TERM_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'keys.js')], input=json.dumps(cases),
                       capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the terminal-style page script', r.stderr[-800:])
    got = json.loads(r.stdout or '[]') or [None] * len(cases)
    eq((got[0], got[1]), ([['blur']], [['back']]), 'Esc in a working chat leaves the box, then goes back')
    eq((got[2], got[3]), ([['interrupt']], [['interrupt']]), 'Ctrl+C interrupts the working chat')
    eq((got[4], got[5]), ([], []), 'Ctrl+C over selected text, or in an idle chat, is left to the browser')
    for f in got[6:8]:
        check(['Ctrl+C', 'interrupts'] in f['here'] and all(lb != 'interrupt' for _, lb in f['here']),
              "the key hints say 'Ctrl+C interrupts', and Esc no longer interrupts", f)


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


VERSION_DRIVER = r"""
const fs = require('fs');
let reloads = 0;
const location = {reload() { reloads++ }};
const src = fs.readFileSync(process.argv[2], 'utf8');
const out = [];
for (const seq of JSON.parse(fs.readFileSync(0, 'utf8'))) {
  reloads = 0;
  const follow = new Function('location', src + '\nreturn followVersion;')(location);
  const back = seq.map(v => follow(v));
  out.push([back, reloads]);
}
console.log(JSON.stringify(out));
"""


def test_follow_version_f90(tmp: Path) -> None:
    """F90: both run pages keep the run's version from the first snapshot and reload when a later one differs;
    a snapshot without one (an older run) changes nothing."""
    for path, call in ((W.PAGE, 'if(followVersion(s.version))return;'),
                       (W.TERM, 'if(followVersion(snap.version))return;')):
        page = path.read_text(encoding='utf-8')
        check(call in page, f'{path.name}: each snapshot goes through followVersion before it is taken')
        m = re.search(r"let RUN_VERSION='';\nfunction followVersion\(v\)\{.*?return true\}return false\}\n", page, re.S)
        check(m, f'{path.name}: has followVersion')
        if not m or not shutil.which('node'):
            print('  (no node here: the version reload script test is skipped)') if m else None
            continue
        (tmp / 'follow.js').write_text(m.group(0), encoding='utf-8')
        (tmp / 'driver.js').write_text(VERSION_DRIVER, encoding='utf-8')
        cases = [['0.59.0', '0.59.0', '0.59.0'], ['0.59.0', '0.60.0'], ['', None, '0.59.0', '', '0.59.0'],
                 ['', '', '']]
        r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'follow.js')], input=json.dumps(cases),
                           capture_output=True, text=True, timeout=60)
        check(r.returncode == 0, f'{path.name}: node runs followVersion', r.stderr[-800:])
        same, changed, missing, never = json.loads(r.stdout or '[[[], 0], [[], 0], [[], 0], [[], 0]]')
        eq(same, [[False, False, False], 0], f'{path.name}: the same version: no reload')
        eq(changed, [[False, True], 1], f'{path.name}: a different version: reload')
        eq(missing, [[False] * 5, 0], f'{path.name}: a missing version neither sets nor changes it')
        eq(never, [[False] * 3, 0], f'{path.name}: an older run, never a version: nothing')


def test_talk_f93(tmp: Path) -> None:
    """F93: Talk is the first view in the sidebar; a Talk send opens its own control session titled Talk whose
    first message carries the spoken-reply instruction, and later sends to it carry the reminder; the page finds
    that session, says why the mic cannot listen, shows the person's words alone and reads the reply aloud."""
    from agent_runner import control as CT
    fake_repo(tmp)
    page = W.page_html().decode()
    check('const nav=NAV;' in page.split('function side(){', 1)[1].split('\nfunction ', 1)[0],
          'the sidebar draws its views from NAV')
    check("act('talk',{text:msg,to})" in page and 'data-mic' in page and 'webkitSpeechRecognition' in page
          and 'speechSynthesis.speak' in page, 'the Talk view: a mic, Web Speech, the talk action, read aloud')
    ask = CT.talk_ask('what is going on?')
    for words in ('short plain sentences', 'Never say task IDs, branch names, file paths, commands, links',
                  'no markdown', 'lists, tables', 'round numbers', 'one thing at a time'):
        check(words in ask, f'the Talk brief says: {words}')
    eq(CT.control_title(ask), 'Talk', 'a Talk session is titled Talk')
    eq(CT.control_title('Talk mode: what now'), 'Talk mode: what now', 'a typed "Talk mode:" ask is not Talk')
    eq(U.given_title(CT.control_name(7, ask), 7), 'Talk', 'and the run page lists it as Talk')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    calls, typed = [], []
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (calls.append(argv), (0, 'control 7 is up in a hidden terminal'))[1]]):
            code, out = post(url, {'name': 'talk', 'args': {'text': ' what is going on? ', 'to': ''}})
            eq((code, out.get('ok'), out.get('session')), (200, True, 'c7'), 'the first Talk send opens c7')
            eq(calls, [['control', '--new', '--ask', ask, '--no-feed']], 'with the spoken-reply instruction as its first message')
            with mock.patch.object(U, 'chat_to', lambda text, to: (typed.append((to, text)),
                                                                   {'ok': True, 'code': 0, 'out': '', 'argv': []})[1]):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'and the merge?', 'to': 'c7'}})
            eq((out.get('ok'), out.get('session')), (True, 'c7'), 'a later send goes to the live Talk session')
            eq(typed, [('c7', CT.TALK_TAG + 'and the merge?')], 'with the spoken-reply reminder')
            with mock.patch.object(U, 'chat_to', lambda text, to: {'ok': False, 'code': 1, 'out': 'gone', 'argv': []}):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'hello', 'to': 'c7'}})
            eq((out.get('ok'), calls[-1]), (True, ['control', '--new', '--ask', CT.talk_ask('hello'), '--no-feed']),
               'a Talk session that is gone: a new one opens')
            code, out = post(url, {'name': 'talk', 'args': {'text': '  '}})
            eq(out.get('ok'), False, 'nothing said: nothing sent')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the Talk script test is skipped)')
        return
    live = [{'name': 'c1', 'title': 'control session', 'state': 'live'}, {'name': 'c4', 'title': 'Talk', 'state': 'live'},
            {'name': 'c6', 'title': 'Site deploy', 'state': 'live'}, {'name': 'c8', 'title': 'Talk', 'state': 'ended'}]
    feed = [{'kind': 'you', 'text': 'old'}, {'kind': 'say', 'text': 'Old.'}, {'kind': 'you', 'text': 'now?'},
            {'kind': 'tool', 'text': 'Bash(run status)'}, {'kind': 'say', 'text': 'Two agents are **working**.'},
            {'kind': 'tool', 'text': 'Bash(x)'}, {'kind': 'say', 'text': 'Nothing needs you.'}]
    got = logic_js([['talkSession', live, 'c6'], ['talkSession', live, 'c8'],
                    ['talkSession', live[:1], ''], ['micProblem', False, True], ['micProblem', True, False],
                    ['micProblem', True, True], ['micProblem', False, False], ['talkShown', ask], ['talkShown', CT.talk_message('and you?')],
                    ['talkShown', 'plain words'], ['talkReply', feed, 2], ['talkReply', feed[:6], 2],
                    ['talkReply', feed, 7]])
    eq(got[:3], ['c6', 'c4', ''], 'the remembered live session, else a live chat titled Talk, else none')
    check('https or localhost' in got[3] and 'Type below' in got[3], 'plain http: the mic says it needs https', got[3])
    check('cannot turn speech into text' in got[4], 'no speech recognition: the mic says so', got[4])
    eq(got[5], '', 'https with recognition: the mic listens')
    check('https link' in got[6] and 'cannot turn speech' not in got[6],
          'B130: plain http without recognition (Safari hides it there): the mic points at the https link', got[6])
    del got[6]
    eq(got[6:9], ['what is going on?', 'and you?', 'plain words'], "the person's words show without the brief")
    eq(got[9], 'Two agents are working. Nothing needs you.', 'the reply since the send, in plain words, read aloud')
    eq(got[10:12], ['', ''], 'nothing is read while it still works, or before it says anything new')
    js = W.PAGE.read_text(encoding='utf-8').split('<script id="logic">', 1)[1].split('</script>', 1)[0]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'logic.js').write_text(js, encoding='utf-8')
        r = subprocess.run(['node', '-e', 'process.stdout.write(JSON.stringify(require(process.argv[1]).NAV))',
                            str(Path(d) / 'logic.js')], capture_output=True, text=True, timeout=60)
    nav = json.loads(r.stdout or '[]')
    eq([k for k, _ in nav][:2], ['talk', 'home'], 'Talk is the top view in the sidebar, above Home')


def test_delete_chats_f118(tmp: Path) -> None:
    """F118: the page's delete_chats reaches control.end_control for each named chat and refuses c1; each chat
    row but c1 has a delete button, a delete is sent only once Undo is past, and chatPick picks as Ctrl/Cmd+click
    (toggle) and Shift+click (a range from the last clicked) do, never c1."""
    from agent_runner import control as CT
    fake_repo(tmp)
    page = W.page_html().decode()
    check('data-del=' in page and 'data-undo' in page and 'data-delsel' in page and "name:'delete_chats'" in page,
          'the page: a delete button per chat, Undo, a Delete N bar, the delete_chats action')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    ended = []
    try:
        with mock.patch.object(CT, 'end_control', lambda n, why: (ended.append(n), n != 7)[1]):
            code, out = post(url, {'name': 'delete_chats', 'args': {'names': ['c4', 'c7']}})
            eq((code, out.get('ok'), out.get('deleted'), ended), (200, True, ['c4'], [4, 7]),
               'each named chat is ended; one already gone is said so')
            code, out = post(url, {'name': 'delete_chats', 'args': {'names': ['c1']}})
            eq((out.get('ok'), ended), (False, [4, 7]), 'c1 cannot be deleted: nothing ended')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the chat pick test is skipped)')
        return
    names = ['c1', 'c3', 'c4', 'c6', 'c9']
    got = logic_js([['chatPick', names, [], '', 'c4', 'toggle'], ['chatPick', names, ['c4'], 'c4', 'c9', 'toggle'],
                    ['chatPick', names, ['c4', 'c9'], 'c9', 'c4', 'toggle'], ['chatPick', names, ['c4'], 'c4', 'c9', 'range'],
                    ['chatPick', names, [], 'c6', 'c1', 'range'], ['chatPick', names, ['c3'], 'c3', 'c1', 'toggle'],
                    ['chatPick', names, ['c3', 'c4'], 'c4', 'c6', ''], ['chatPick', names, [], '', 'c6', 'range']])
    eq(got[0], {'sel': ['c4'], 'last': 'c4'}, 'Ctrl/Cmd+click picks a chat')
    eq(got[1], {'sel': ['c4', 'c9'], 'last': 'c9'}, 'and another, in list order')
    eq(got[2], {'sel': ['c9'], 'last': 'c4'}, 'and again takes it out')
    eq(got[3], {'sel': ['c4', 'c6', 'c9'], 'last': 'c4'}, 'Shift+click picks the range from the last clicked')
    eq(got[4]['sel'], ['c3', 'c4', 'c6'], 'a range up to c1 leaves c1 out')
    eq(got[5]['sel'], ['c3'], 'c1 is never picked')
    eq(got[6], {'sel': [], 'last': 'c6'}, 'a plain click drops the pick')
    eq(got[7], {'sel': ['c6'], 'last': 'c6'}, 'Shift+click with nothing clicked before picks that one')


def test_https_link_b130(tmp: Path) -> None:
    fake_repo(tmp)
    serve = {'TCP': {'8771': {'HTTPS': True}, '8791': {'HTTPS': True}},
             'Web': {'box.tail.ts.net:8771': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}},
                     'box.tail.ts.net:8791': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8790'}}}}}
    eq(W.serve_https_urls(serve, 8770, 'TK'), ['https://box.tail.ts.net:8771/?t=TK'],
       'the https port that proxies to the web port gives the https link')
    eq(W.serve_https_urls(serve, 8780, 'TK'), [], 'no serve for that port: no https link')
    eq(W.serve_https_urls({}, 8770, 'TK'), [], 'nothing served: none')
    plain = {'TCP': {'80': {'HTTP': True}}, 'Web': {'box.tail.ts.net:80': {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:8770'}}}}}
    eq(W.serve_https_urls(plain, 8770, 'TK'), [], 'a plain-http serve gives no https link')
    on443 = {'TCP': {'443': {'HTTPS': True}}, 'Web': {'box.tail.ts.net:443': {'Handlers': {'/': {'Proxy': 'http://localhost:8770'}}}}}
    eq(W.serve_https_urls(on443, 8770, 'TK'), ['https://box.tail.ts.net/?t=TK'], 'port 443 needs no port')
    ran = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(serve), '')
    eq(W.tailscale_https_urls(8770, 'TK', run=ran), ['https://box.tail.ts.net:8771/?t=TK'], 'read from tailscale')
    W.url_file().parent.mkdir(parents=True, exist_ok=True)
    W.url_file().write_text('http://box:8770/?t=TK\nhttp://10.0.0.5:8770/?t=TK\n', encoding='utf-8')
    with mock.patch.object(S, 'run_up', return_value=True), \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, t: W.serve_https_urls(serve, port, t)):
        eq(W.page_line(), 'run page: https://box.tail.ts.net:8771/?t=TK (or http://box:8770/?t=TK)',
           'status prints the https link first')
    # B129: the run log's address line at the start names the https link first too; web.url keeps the http ones
    with mock.patch.dict(W.os.environ, {'AGENT_RUNNER_NO_WEB': ''}), mock.patch.object(W, 'lan_ip', lambda: ''), \
            mock.patch.dict(S.C.run, {'web': True, 'web_port': 0}), mock.patch.object(S, 'log') as lg, \
            mock.patch.object(W, 'tailscale_https_urls', lambda port, t: [f'https://box.tail.ts.net:8771/?t={t}']):
        srv = W.start_web()
    try:
        line = next(str(c.args[0]) for c in lg.call_args_list if 'run page:' in str(c.args[0]))
        check(line.startswith(f'run page: https://box.tail.ts.net:8771/?t={W.web_token()} or http://'),
              'B129: the run log prints the https link first', line)
        check(all(u.startswith('http://') for u in W.url_file().read_text(encoding='utf-8').split()),
              'web.url keeps the http addresses (Home reads its port from them)')
    finally:
        srv.stop()
    # B129: an insecure context (plain http) gets the needs-https message, even where recognition exists
    if shutil.which('node'):
        got = logic_js([['micProblem', False, True]])
        check('needs https' in got[0], 'B129: insecure context: the mic says it needs https', got[0])


LISTEN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
let spoke = 0, sent = [];
const window = {speechSynthesis: {cancel() { spoke++ }, speak() { spoke++ }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance {}
let rec = null;
class SR { constructor() { rec = this } start() { this.started = spoke } stop() {} }
const navigator = {language: 'en-US'};
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: ''};
const micWhy = () => '', toast = () => {}, render = () => {}, talkSend = t => { sent.push(t) };
const I = {stop: '', talk: '', speak: '', mute: ''};
const el = {}, $ = k => el[k] = el[k] || {classList: {toggle() {}}, setAttribute() {}, textContent: '', className: ''};
const setHTML = () => true, talkTyping = () => false, talkDock = () => (talkDraw(), $('talkline').textContent);
let TS = {read: true, voice: '', mic: 'tap', auto: false};
eval(logic.replace('const TALK_SET', 'var TALK_SET') + grab('function unlockSpeech(') + grab('function talkDraw(') + grab('function listen(') + `
  listen();
  const before = rec.started;
  rec.onerror({error: 'no-speech'}); rec.onend();
  const line = talkDock();
  listen();
  const cleared = talkDock();
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'hello'}], {isFinal: true})]}); rec.onend();
  TK.state = 'speaking'; rec = null; spoke = 0;
  listen();
  const stopped = {state: TK.state, cancelled: spoke, listened: !!rec};
  console.log(JSON.stringify({before, line, cleared, sent, stopped}));`);
"""


def test_listen_heard_nothing_b132(tmp: Path) -> None:
    """B132: a listen touches no speechSynthesis before rec.start() (iOS then hears nothing), and one that ends with
    no words says so in the talk line with the last error, instead of going quiet."""
    if not shutil.which('node'):
        print('  (no node here: the listen script test is skipped)')
        return
    (tmp / 'driver.js').write_text(LISTEN_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs listen()', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('before'), 0, 'listen does not touch speechSynthesis before rec.start()')
    eq(got.get('line'), 'Heard nothing (error: no-speech)', 'no words and error no-speech: the talk line says so')
    eq(got.get('cleared'), 'Listening…', 'the next listen clears it')
    eq(got.get('sent'), ['hello'], 'words heard are still sent')
    eq(got.get('stopped'), {'state': '', 'cancelled': 1, 'listened': False},
       'a tap during a reply only stops it: no listen right after a speech call')


TALK_HEAR_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const said = [];
const window = {speechSynthesis: {cancel() {}, speak(u) { if (u.text) said.push(u.text) }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
const navigator = {language: 'en-US'};
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }};
const toast = () => {}, render = () => {}, tq = p => p, followVersion = () => false, TALK_KEY = 'ar-talk';
const keepSent = () => {}, sessionOf = () => null, newCid = () => 'k';  // B154
const OB = {offline: false}, drain = () => {};  // F137: takeSnap wakes the outbox
let TS = {read: true, voice: '', mic: 'tap', auto: false}; const voices = () => [], talkTyping = () => false;  // F124
const HOME_PAGE = false, document = {};  // B153: takeSnap sets the window title
const S = {snap: {sessions: [], queue: []}, feeds: {}, sent: {}, waitNew: null};
const chats = () => S.snap.sessions.filter(s => /^c\d+$/.test(s.name)), working_ = () => [];
const feedOf = n => (S.feeds[n] || {}).entries || [];
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: ''};
let feeds = {}, actDone = null, actResult = null;
const fetch = async p => ({json: async () => ({ok: true, entries: feeds[decodeURIComponent(p.split('/')[1])] || []})});
const act = () => new Promise(res => { actDone = () => res(actResult) });
const tick = () => new Promise(r => setTimeout(r, 0));
const c13 = [{name: 'c13', title: 'Talk', state: 'live'}];
const reply = [{kind: 'you', text: 'Talk mode: …\n\nThey said: Hello'}, {kind: 'say', text: "Hi there. I'm listening."}];
const reset = () => { said.length = 0; TK.state = ''; TK.wait = null; S.snap.sessions = []; S.feeds = {}; feeds = {};
  for (const k in kept) delete kept[k] };
eval(logic + grab('function talkName(') + grab('function talkWaitName(') + grab('async function talkSend(')
  + grab('function talkHear(') + grab('function unlockSpeech(') + grab('function speak(') + grab('function takeSnap(')
  + grab('async function loadFeed(') + grab('function addSent(') + `
(async () => {
  const out = {};
  // the session was just opened and the talk action named none: two snapshots list c13, titled Talk, with its reply
  actResult = {ok: true, session: ''};
  const sent = talkSend('Hello'); actDone(); await sent;
  feeds.c13 = reply;
  for (let i = 0; i < 2; i++) { takeSnap({sessions: c13}); await tick(); await tick() }
  out.unnamed = {state: TK.state, said: said.join(' '), remembered: kept['ar-talk'] || ''};
  const shown = talkName();  // what talkHTML renders: convo of this chat's feed
  out.shown = {name: shown, last: (feedOf(shown).slice(-1)[0] || {}).text || ''};
  // the talk action still waits for the new chat's link while its reply lands: the snapshots hear it meanwhile
  reset(); actResult = {ok: true, session: 'c13'};
  const slow = talkSend('Hello');
  feeds.c13 = reply;
  for (let i = 0; i < 2; i++) { takeSnap({sessions: c13}); await tick(); await tick() }
  out.slow = {state: TK.state, said: said.join(' ')};
  actDone(); await slow; await tick();
  out.slowAfter = {state: TK.state, wait: TK.wait};
  // B134: a feed at its cap (its length stands still, its indexes move): what came after the send is still heard,
  // and a reply that says again what was said before is not cut short
  const old = [];
  for (let i = 0; i < 200; i++) old.push({kind: i % 2 ? 'say' : 'you', text: i % 2 ? 'Okay.' : 'ping', id: 'e' + i});
  const more = [{kind: 'you', text: '(Talk: answer as speech.) Hello', id: 'n0'}, {kind: 'say', text: 'Okay.', id: 'n1'},
                {kind: 'say', text: 'Two agents are running.', id: 'n2'}];
  for (const ids of [true, false]) {
    reset(); actResult = {ok: true, session: 'c13'}; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
    const strip = es => ids ? es : es.map(({kind, text}) => ({kind, text}));
    const base = ids ? old : old.map((e, i) => ({...e, text: e.text + i}));
    S.feeds.c13 = {entries: strip(base)};
    const cap = talkSend('Hello'); actDone(); await cap;
    feeds.c13 = strip(base.concat(more).slice(-200));
    for (let i = 0; i < 2; i++) { await loadFeed('c13') }
    out['capped' + (ids ? '' : 'NoIds')] = {state: TK.state, said: said.join(' '), len: feedOf('c13').length};
  }
  // the feed was not read yet at the send: only what follows the person's own words is read aloud
  reset(); actResult = {ok: true, session: 'c13'}; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
  const un = talkSend('Hello'); actDone(); await un;
  feeds.c13 = old.concat(more);
  for (let i = 0; i < 2; i++) { await loadFeed('c13') }
  out.unread = said.join(' ');
  // F124: read replies aloud off: the reply shows, nothing is said
  reset(); actResult = {ok: true, session: 'c13'}; TS.read = false; kept['ar-talk'] = 'c13'; S.snap.sessions = c13;
  S.feeds.c13 = {entries: old}; const mute = talkSend('Hello'); actDone(); await mute;
  feeds.c13 = old.concat(more); for (let i = 0; i < 2; i++) { await loadFeed('c13') }
  out.mute = {state: TK.state, said: said.join(' ')};
  console.log(JSON.stringify(out));
})();`);
"""


def test_talk_reply_heard_b133(tmp: Path) -> None:
    """B133: a Talk reply is always shown and read aloud: a talkSend to a just-opened chat (the talk action named no
    session) is heard from the snapshots that list it, so is a reply that lands while the action still waits for the
    new chat's link."""
    if not shutil.which('node'):
        print('  (no node here: the Talk reply script test is skipped)')
        return
    (tmp / 'driver.js').write_text(TALK_HEAR_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs talkSend and the snapshots', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('unnamed'), {'state': 'speaking', 'said': "Hi there. I'm listening.", 'remembered': 'c13'},
       'a just-opened chat, then two snapshots: speaking the reply, and the chat is remembered')
    eq(got.get('slow'), {'state': 'speaking', 'said': "Hi there. I'm listening."},
       'a reply that lands while the talk action still runs is spoken')
    eq(got.get('slowAfter'), {'state': 'speaking', 'wait': None}, 'the action ending later does not wait again')
    eq(got.get('capped'), {'state': 'speaking', 'said': 'Okay. Two agents are running.', 'len': 200},
       'B134: a Talk chat past the feed cap: the whole reply is read, what it says again too')
    eq(got.get('cappedNoIds'), {'state': 'speaking', 'said': 'Okay. Two agents are running.', 'len': 200},
       'B134: and from a transcript without ids')
    eq(got.get('unread'), 'Okay. Two agents are running.', 'B134: a feed not read at the send: only the reply')
    eq(got.get('mute'), {'state': '', 'said': ''}, 'F124: read replies aloud off: nothing is said')
    eq(got.get('shown'), {'name': 'c13', 'last': "Hi there. I'm listening."},
       'the Talk view shows c13, its feed ending with the reply')


SLASH_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n'), CMDS = JSON.parse(process.argv[3]);
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { this.v[k] = v }};
const DRAFT_KEY = k => k, boxKey = () => 'c1', grow = () => {}, esc = s => String(s), tq = p => p;
const S = {thread: 'c1', sel: [], drawer: false};
const busy = () => false, act = () => {}, selectedText = () => false, render = () => {}, newConcept = () => {};
let sent = 0; const send = () => { sent++ };
const menu = {hidden: true, innerHTML: '', querySelector() { return null }};
const ta = {value: '', blurred: 0, matches(s) { return s === '[data-in]' }, focus() {}, blur() { this.blurred++ },
            setSelectionRange() {}, closest() { return null }};
const document = {activeElement: ta, addEventListener(t, f) { handlers[t] = f },
                  querySelector(s) { return s === '[data-slash]' ? menu : s === '[data-in]' ? ta : null }};
const fetch = () => Promise.resolve({json: () => Promise.resolve(CMDS)});
eval(logic + slice('const SL={', 'ta.value.length);\n}\n') + slice("document.addEventListener('keydown',", '\n});\n') + `
(async () => {
  await new Promise(r => setTimeout(r, 0));
  const out = {}, type = v => { ta.value = v; slashShow(ta) };
  const rows = () => [...menu.innerHTML.matchAll(/<b>\\/([^<]*)<\\/b>/g)].map(m => m[1]);
  const key = k => handlers.keydown({key: k, target: ta, preventDefault() {}});
  type('/'); out.slash = {hidden: menu.hidden, rows: rows()};
  type('/s'); out.s = rows();
  key('ArrowDown'); out.on = (menu.innerHTML.match(/class="on"[^>]*><b>\\/([^<]*)/) || [])[1];
  key('Enter'); out.picked = {value: ta.value, hidden: menu.hidden, sent};
  type('/co'); key('Escape'); out.esc = {hidden: menu.hidden, blurred: ta.blurred, value: ta.value, thread: S.thread};
  type('hello /run'); out.mid = menu.hidden;
  type('/clear'); key('Enter'); out.full = {sent, hidden: menu.hidden};
  console.log(JSON.stringify(out));
})();`);
"""


def test_slash_menu_b119(tmp: Path) -> None:
    """B119: typing / in the message box shows the session's slash commands (/commands: the control session's own
    skills, the agent CLI's built-ins, the project's skills) as a menu that filters as you type; arrows and Enter
    pick, Esc closes the menu and stays in the chat, and a command typed in full is sent."""
    repo = fake_repo(tmp)
    (repo / '.claude' / 'skills' / 'deploy').mkdir(parents=True)
    (repo / '.claude' / 'skills' / 'deploy' / 'SKILL.md').write_text(
        '---\nname: deploy\ndescription: Ship the site\n---\nDo it.\n', encoding='utf-8')
    token = W.web_token()
    (tmp / 'home' / '.claude' / 'commands').mkdir(parents=True)  # the person's own, apart from this machine's
    (tmp / 'home' / '.claude' / 'commands' / 'notes.md').write_text('---\ndescription: Take notes\n---\nGo.\n')
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        with mock.patch.object(Path, 'home', return_value=tmp / 'home'):
            code, body = get(f'http://127.0.0.1:{srv.server_address[1]}/commands?t={token}')
    finally:
        srv.stop()
    eq(code, 200, '/commands answers')
    cmds = json.loads(body)
    names = [c['name'] for c in cmds]
    eq(names[:7], ['run', 'since', 'follow', 'control', 'pause', 'stop', 'slots'], "the control session's own first")
    check({'clear', 'compact', 'deploy', 'notes'} <= set(names), "the built-ins, the project's skill and the "
          "person's command are listed", names)
    eq(len(names), len(set(names)), 'each name once')
    eq(next(c['desc'] for c in cmds if c['name'] == 'run'), "The agent-runner run's status",
       'a description without its (the person typed …)')
    eq(next(c['desc'] for c in cmds if c['name'] == 'deploy'), 'Ship the site', "a skill's description")
    if not shutil.which('node'):
        print('  (no node here: the slash menu script test is skipped)')
        return
    got = logic_js([['slashMatches', cmds, '/sl'], ['slashMatches', [], '/pa'], ['slashMatches', cmds, 'hi'],
                    ['slashMatches', cmds, '/run now'], ['slashMove', 0, 3, 'ArrowUp'], ['slashMove', 2, 3, 'ArrowDown']])
    eq([c['name'] for c in got[0]], ['slots'], '/sl filters to /slots')
    eq([c['name'] for c in got[1]], ['pause', 'compact'], 'no list from the run page: the fixed list stands in')
    eq(got[2:4], [[], []], 'no menu without a leading / or once a space follows the command')
    eq(got[4:], [2, 0], 'the arrows wrap round')
    few = [{'name': n, 'desc': ''} for n in ('run', 'since', 'slots', 'control', 'clear', 'compact', 'cost')]
    (tmp / 'driver.js').write_text(SLASH_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE), json.dumps(few)], capture_output=True,
                       text=True, timeout=60)
    check(r.returncode == 0, 'node runs the slash menu', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('slash'), {'hidden': False, 'rows': [c['name'] for c in few]}, "'/' shows the menu with every command")
    eq(got.get('s'), ['since', 'slots', 'cost'], "'/s' filters: names that start with s, then those that hold it")
    eq(got.get('on'), 'slots', 'ArrowDown moves the highlight')
    eq(got.get('picked'), {'value': '/slots ', 'hidden': True, 'sent': 0}, 'Enter picks it into the box, not sent')
    eq(got.get('esc'), {'hidden': True, 'blurred': 0, 'value': '/co', 'thread': 'c1'},
       'Esc closes the menu and stays in the box and the chat')
    eq(got.get('mid'), True, 'a / later in the words shows no menu')
    eq(got.get('full'), {'sent': 1, 'hidden': True}, 'Enter on a command typed in full sends it')


COMPOSER_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');  // a Windows checkout is CRLF
const slice = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i) + b.length); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const handlers = {}, acts = [];
const store = {v: {}, get(k) { return this.v[k] || '' }, set(k, v) { if (v) this.v[k] = v; else delete this.v[k] }};
const DRAFT_KEY = k => 'ar-draft:' + k, grow = () => {}, esc = s => String(s), tq = p => p;
const S = {thread: 'c1', sel: [], drawer: false, view: 'home'};
const boxKey = () => S.thread || 'home';
let BUSY = false, sent = 0, prevented = 0, TALK = '';
const talkName = () => TALK;
const busy = () => BUSY, act = (n, a) => { acts.push([n, a.session]) }, selectedText = () => false,
      render = () => {}, newConcept = () => {}, send = () => { sent++ };
const menu = {hidden: true, innerHTML: '', querySelector() { return null }};
const ta = {value: '', blurred: 0, selectionStart: 0, selectionEnd: 0, matches(s) { return s === '[data-in]' },
            focus() {}, blur() { this.blurred++ }, closest() { return null },
            setSelectionRange(a, b) { this.selectionStart = a; this.selectionEnd = b }};
const document = {activeElement: ta, addEventListener(t, f) { handlers[t] = f },
                  querySelector(s) { return s === '[data-slash]' ? menu : s === '[data-in]' ? ta : null }};
const fetch = () => Promise.resolve({json: () => Promise.resolve([])});
eval(logic + slice('const HIST_KEY=', 'return true;\n}\n') + slice('const SL={', 'ta.value.length);\n}\n')
     + slice('const shownSession=', ";\n") + slice("document.addEventListener('click',", '\n});\n')
     + slice("document.addEventListener('keydown',", '\n});\n') + `
(async () => {
  await new Promise(r => setTimeout(r, 0));
  const out = {};
  const key = (k, o) => { const was = prevented; handlers.keydown(Object.assign({key: k, target: ta,
    preventDefault() { prevented++ }}, o || {})); return prevented > was };
  const at = (v, c) => { ta.value = v; ta.selectionStart = ta.selectionEnd = c == null ? v.length : c };
  histAdd('c1', 'first'); histAdd('c1', 'second\\nline'); histAdd('c1', 'second\\nline'); histAdd('c2', 'other');
  out.stored = JSON.parse(store.get('ar-hist:c1'));
  at('draft');
  out.up1 = [key('ArrowUp'), ta.value, store.get('ar-draft:c1')];
  out.upMid = [key('ArrowUp'), ta.value];          // the caret on the recalled message's last line: Up moves it
  ta.setSelectionRange(0, 0);
  out.up2 = [key('ArrowUp'), ta.value];
  out.upTop = [key('ArrowUp'), ta.value];
  out.down1 = [key('ArrowDown'), ta.value];
  out.down2 = [key('ArrowDown'), ta.value];
  out.down3 = [key('ArrowDown'), ta.value];
  out.draft = store.get('ar-draft:c1');
  S.thread = 'c2'; at('');
  out.other = [key('ArrowUp'), ta.value];
  S.thread = 'c3'; at('');
  out.none = [key('ArrowUp'), ta.value];
  S.thread = 'c1'; at('one');
  out.shift = [key('Enter', {shiftKey: true}), sent];
  out.enter = [key('Enter'), sent];
  BUSY = true; at('x');
  out.escBusy = [key('Escape'), acts.slice(), ta.blurred, S.thread];
  BUSY = false;
  out.escIdle = [key('Escape'), acts.length, ta.blurred, S.thread];
  store.v['ar-hist:c4'] = 'not json'; S.thread = 'c4'; at('');
  out.bad = [key('ArrowUp'), ta.value];
  // B142: Esc in the box interrupts the shown session too: c1 on Home, the Talk session in the Talk view
  S.thread = null; S.view = 'home'; BUSY = true; acts.length = 0; at('x');
  out.homeEsc = [key('Escape'), acts.slice()];
  acts.length = 0; S.view = 'talk'; TALK = 'c7';
  out.talkEsc = [key('Escape'), acts.slice()];
  acts.length = 0; S.view = 'home'; BUSY = false; const blurs = ta.blurred;
  out.homeEscIdle = [key('Escape'), acts.length, ta.blurred - blurs];
  // B141: on Home (no chat open) Ctrl+C and Stop interrupt c1 while it works; in the Talk view the Talk session
  S.thread = null; S.view = 'home'; BUSY = true; acts.length = 0;
  const ctrlC = () => key('c', {ctrlKey: true});
  out.homeCtrlC = [ctrlC(), acts.slice()];
  acts.length = 0;
  handlers.click({target: {closest: s => s === '[data-stop]' ? {dataset: {stop: ''}} : null}});
  out.homeStop = acts.slice();
  acts.length = 0; S.view = 'talk'; TALK = 'c7';
  out.talkCtrlC = [ctrlC(), acts.slice()];
  acts.length = 0; TALK = '';
  out.talkNone = [ctrlC(), acts.slice()];
  acts.length = 0; S.view = 'home'; BUSY = false;
  out.homeIdle = [ctrlC(), acts.slice()];
  console.log(JSON.stringify(out));
})();`);
"""


def test_composer_keys_b120(tmp: Path) -> None:
    """B120: the run app's message box takes Claude Code's keys: Up and Down recall the messages sent in that chat
    (kept per chat in localStorage), Shift+Enter makes a new line and Enter sends, Esc interrupts a working chat;
    the keys are listed once (BOX_KEYS); without ttyd the page shows one line with this machine's install command."""
    page = W.page_html().decode()
    check('const BOX_KEYS=[' in page and page.count('keysLine()') >= 2, 'the keys are listed once, in BOX_KEYS, and '
          'shown under the box')
    check("'ar-hist:'+k" in page and 'localStorage' in page, 'the history is kept per chat in localStorage')
    check("S.snap.terminal_mode==='install'" in page and 'The terminal tab (the real session) needs ttyd' in page,
          'without ttyd the page says the terminal tab needs it')
    eq(W.ttyd_install_cmd(lambda t: t == 'pacman'), 'sudo pacman -S ttyd', 'Arch: pacman')
    eq(W.ttyd_install_cmd(lambda t: t == 'brew'), 'brew install ttyd', 'macOS: brew')
    eq(W.ttyd_install_cmd(lambda t: False), '', 'no package manager known: no command')
    with mock.patch.object(W, 'ttyd_install_cmd', return_value='sudo pacman -S ttyd'):
        eq(W.with_extras({'terminal_mode': 'install'}).get('ttyd_install'), 'sudo pacman -S ttyd',
           'the snapshot carries the install command when ttyd is missing')
        check('ttyd_install' not in W.with_extras({'terminal_mode': 'ttyd'}), 'and not when ttyd is there')
    if not shutil.which('node'):
        print('  (no node here: the message box keys test is skipped)')
        return
    got = logic_js([['histPush', ['a'], ' b '], ['histPush', ['a', 'b'], 'b'], ['histPush', ['a'], '  '],
                    ['histStep', 2, None, 'ArrowUp'], ['histStep', 2, 0, 'ArrowUp'], ['histStep', 2, 1, 'ArrowDown'],
                    ['histEdge', 'ab\ncd', 1, 1, 'ArrowUp'], ['histEdge', 'ab\ncd', 4, 4, 'ArrowUp'],
                    ['histEdge', 'ab\ncd', 1, 1, 'ArrowDown'], ['histEdge', 'ab', 0, 2, 'ArrowUp']])
    eq(got[:3], [['a', 'b'], ['a', 'b'], ['a']], 'a sent message joins the history, not twice in a row, not blank')
    eq(got[3:6], [1, 0, 2], 'Up from the draft goes to the last message, stops at the first; Down comes back')
    eq(got[6:], [True, False, False, False], 'Up and Down leave the text only from its first / last line')
    (tmp / 'driver.js').write_text(COMPOSER_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the message box keys', r.stderr[-800:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('stored'), ['first', 'second\nline'], 'the history is stored per chat, a repeat once')
    eq(got.get('up1'), [True, 'second\nline', ''], 'Up recalls the last message sent in this chat, not saved as '
       'the draft')
    eq(got.get('upMid'), [False, 'second\nline'], 'Up off its first line moves the caret, as in Claude Code')
    eq(got.get('up2'), [True, 'first'], 'Up on the first line recalls the one before')
    eq(got.get('upTop'), [True, 'first'], 'Up at the oldest stays there')
    eq(got.get('down1'), [True, 'second\nline'], 'Down goes forward again')
    eq(got.get('down2'), [True, 'draft'], 'Down past the last brings back the unsent draft')
    eq(got.get('down3'), [False, 'draft'], 'Down at the draft does nothing more')
    eq(got.get('draft'), 'draft', 'the draft is saved again')
    eq(got.get('other'), [True, 'other'], "another chat recalls its own messages")
    eq(got.get('none'), [False, ''], 'a chat with no history leaves Up alone')
    eq(got.get('shift'), [False, 0], 'Shift+Enter is left to the box (a new line), not sent')
    eq(got.get('enter'), [True, 1], 'Enter sends')
    eq(got.get('escBusy'), [True, [['interrupt', 'c1']], 0, 'c1'], 'Esc interrupts the working chat and stays in it')
    eq(got.get('escIdle'), [True, 1, 1, 'c1'], 'Esc in an idle chat leaves the box, sends nothing, does not go back')
    eq(got.get('bad'), [False, ''], 'a broken stored history is read as none')
    eq(got.get('homeEsc'), [True, [['interrupt', 'c1']]], 'B142: Esc on Home interrupts a working c1')
    eq(got.get('talkEsc'), [True, [['interrupt', 'c7']]], 'B142: in the Talk view, the Talk session')
    eq(got.get('homeEscIdle'), [True, 0, 1], 'B142: with c1 idle, Esc on Home leaves the box')
    # B141: with no chat open the page shows c1, and Ctrl+C and Stop interrupt it while it works
    eq(got.get('homeCtrlC'), [True, [['interrupt', 'c1']]], 'Ctrl+C with no chat open interrupts a working c1')
    eq(got.get('homeStop'), [['interrupt', 'c1']], 'Stop with no chat open interrupts c1')
    eq(got.get('talkCtrlC'), [True, [['interrupt', 'c7']]], 'in the Talk view Ctrl+C interrupts the Talk session')
    eq(got.get('talkNone'), [False, []], 'a Talk view with no Talk session yet interrupts nothing')
    eq(got.get('homeIdle'), [False, []], 'an idle c1 leaves Ctrl+C to the browser')
    check('data-stop="${esc(shownNow)}"' in page, "the box's Stop names the shown session")


def test_interrupt_c1_b141(tmp: Path) -> None:
    """B141: interrupt c1 types Escape into its hidden session's FIFO, <notes>/control1.in, and the feed shows
    the transcript's interrupt as 'interrupted'."""
    from agent_runner import slots as SLT
    fake_repo(tmp)
    S.C.notes('control1.live').write_text(str(os.getpid()), encoding='utf-8')
    typed = []
    with mock.patch('agent_runner.plat.WINDOWS', False), \
            mock.patch.object(SLT, 'send_fifo_raw', lambda p, b: typed.append((p.name, b)) or True):
        r = U.interrupt('c1')
    eq((r['ok'], typed, r['out']), (True, [('control1.in', b'\x1b')], 'interrupted c1'),
       'interrupt c1 sends Escape to control1.in')
    row = {'type': 'user', 'message': {'content': [{'type': 'text', 'text': '[Request interrupted by user]'}]}}
    eq(U.feed_entries([row]), [{'kind': 'out', 'text': 'interrupted'}], "the page's feed then shows 'interrupted'")


def test_chat_order_f133(tmp: Path) -> None:
    """F133: the Chats order and pins, set through /act chat_order, are kept by the run (a file in the notes dir):
    the snapshot after a reload, and a new server's, list the chats in that order with the pins; a deleted chat
    drops out, a new one goes just under the pins. Each chat row has a pin button and drags by pointer events,
    and chatMove places a dropped row with the pins kept first."""
    fake_repo(tmp)
    page = W.page_html().decode()
    check('data-pin=' in page and "act('chat_order'" in page and "'pointerdown'" in page and 'data-crow=' in page,
          'the page: a pin button per chat, rows dragged by pointer events, the chat_order action')
    sessions = [{'name': n} for n in ('c1', 'c3', 'c4', 's1')]
    token = W.web_token()

    def snap_of(srv) -> dict:
        return json.loads(get(f'http://127.0.0.1:{srv.server_address[1]}/snapshot?t={token}')[1])

    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'sessions': sessions})
    try:
        eq((snap_of(srv)['chat_order'], snap_of(srv)['chat_pins']), (['c1', 'c3', 'c4'], []),
           'nothing kept yet: the snapshot order')
        url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
        code, out = post(url, {'name': 'chat_order', 'args': {'order': ['c4', 'c1', 'c3'], 'pins': ['c4']}})
        eq((code, out.get('ok')), (200, True), 'chat_order is taken')
        eq(post(url, {'name': 'chat_order', 'args': {'order': 'c4'}})[1].get('ok'), False, 'order must be a list')
        eq(post(url, {'name': 'chat_order', 'args': {'nope': 1}})[1].get('ok'), False, 'an unknown arg is refused')
        s = snap_of(srv)
        eq((s['chat_order'], s['chat_pins']), (['c4', 'c1', 'c3'], ['c4']), 'a reload shows the kept order')
        eq(post(url, {'name': 'chat_order', 'args': {'order': ['c4', 'c3', 'c1']}})[1].get('ok'), True, 'order alone')
        s = snap_of(srv)
        eq((s['chat_order'], s['chat_pins']), (['c4', 'c3', 'c1'], ['c4']), 'an order sent alone keeps the pins')
    finally:
        srv.stop()
    check(W.S.C.notes(W.CHAT_ORDER_FILE).exists(), 'kept in the notes dir')
    sessions = [{'name': n} for n in ('c1', 'c3', 'c7', 's1')]  # c4 deleted, c7 new
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {'sessions': sessions})
    try:
        s = snap_of(srv)
        eq((s['chat_order'], s['chat_pins']), (['c7', 'c3', 'c1'], []),
           'a new server (another page, a phone): the deleted pinned chat drops out, the new one goes on top')
    finally:
        srv.stop()
    if not shutil.which('node'):
        print('  (no node here: the chat move test is skipped)')
        return
    names = ['c4', 'c1', 'c3', 'c6']
    got = logic_js([['chatMove', names, ['c4'], 'c6', 1], ['chatMove', names, ['c4'], 'c1', 3],
                    ['chatMove', names, ['c4'], 'c4', 3], ['chatMove', names, ['c4', 'c3'], 'c3', 1]])
    eq(got[0], ['c4', 'c6', 'c1', 'c3'], 'a row dropped at place 1 lands there')
    eq(got[1], ['c4', 'c3', 'c6', 'c1'], 'and at the end')
    eq(got[2], ['c4', 'c1', 'c3', 'c6'], 'a pinned chat dragged down stays above the unpinned')
    eq(got[3], ['c4', 'c3', 'c1', 'c6'], 'a chat just pinned joins the pins')


def test_answer_button_b138(tmp: Path) -> None:
    """B138: a Needs you button through /act runs the plan command itself, never an AI session (SEND fails if
    called), and its ok result names the item gone; the page drops that item at once and keeps it off while a
    snapshot taken before the answer still lists it; a failed answer keeps it."""
    from agent_runner import plan as P
    fake_repo(tmp)
    P.block('F1', 'CONFIRM: check the board loads on your phone', todo=S.C.todo)

    def no_send(text):
        raise AssertionError(f'an answer button reached an AI session: {text!r}')
    ran = []
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'confirmed and ticked F1'))[1]]), \
                mock.patch.object(U, 'SEND', [no_send]):
            code, yes = post(url, {'name': 'answer', 'args': {'tid': 'F1', 'text': 'Yes', 'button': True}})
            code, no = post(url, {'name': 'answer', 'args': {'tid': 'F1', 'text': 'No', 'button': True}})
    finally:
        srv.stop()
    eq(ran, [['plan', 'confirm', 'F1', 'Yes'], ['plan', 'change', 'F1', 'No: the check failed']],
       'Yes is plan confirm, No is plan change (reopened)')
    eq((yes['ok'], yes['said'], yes['gone']), (True, 'F1 ticked', 'F1'), 'the result says what was done')
    eq(no['said'], 'F1 reopened: the check failed', "No's words")
    page = W.PAGE.read_text(encoding='utf-8')
    check("outbox('answer',{tid:n.id,text:x.dataset.v,button:true},{need:n.id" in page, 'the page sends a button answer', '')
    check("obCards(x=>x.need)" in page, 'the answer stands in Needs you while it is sent (F137)', '')
    if not shutil.which('node'):
        print('  (no node here: the page script test is skipped)')
        return
    needs = [{'id': 'F1'}, {'id': 'R6'}]
    got = logic_js([
        ['goneMark', {}, yes, 1000],
        ['needsShown', needs, {'F1': 1000}, 2000],
        ['needsShown', needs, {'F1': 1000}, 1000 + 31000],
        ['goneMark', {}, {'ok': False, 'out': 'plan: F1 is not waiting'}, 1000],
        ['answerSaid', yes, 'F1', 'Yes'],
    ])
    eq(got[0], {'F1': 1000}, 'an ok result marks the item answered')
    eq(got[1], [{'id': 'R6'}], 'the page drops it at once, and a stale snapshot keeps it off')
    eq(got[2], needs, 'a while later the run\'s own list counts again')
    eq(got[3], {}, 'a failed answer marks nothing: the item stays')
    eq(got[4], 'F1 ticked', 'the toast says what was done')


def test_pick_f138(tmp: Path) -> None:
    """F138: an option button's /pick link answers the item with no AI session and no page token: a good code
    confirms it (`plan confirm ID "go with B: <its name>"`) and is burnt; a reused, wrong or missing code is
    refused, and so is an item settled already. pick-links prints one link per option, with no token in them;
    with no https address it says so and prints none."""
    import io
    from contextlib import redirect_stderr, redirect_stdout
    from agent_runner import cmds, plan as P
    fake_repo(tmp)
    token = W.web_token()
    https = lambda port, t: [f'https://box.tail.ts.net:8771/?t={t}']
    cid, build = P.concept_shown('tabs or a drawer', 'https://claude.ai/artifact/k1', ['a.py'],
                                 todo=S.C.todo, done=S.C.done)
    copy = S.C.notes('concepts', f'{cid}.html')
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text('<h1>Menu</h1><h2>A: tabs</h2><p>x</p><h2>B: drawer (recommended)</h2><p>y</p>', encoding='utf-8')
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(W, 'tailscale_https_urls', https), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out):
        rc = cmds.cmd_pick_links([cid, 'A,B,C'])
    eq(rc, 0, 'pick-links prints the links')
    lines = out.getvalue().split()
    eq(len(lines), 6, 'one link per option')
    eq([lines[0], lines[2], lines[4]], ['A', 'B', 'C'], 'each line names its option')
    link = lines[3]
    check(link.startswith(f'https://box.tail.ts.net:8771/pick?id={cid}&k=') and link.endswith('&o=B'),
          'a link is the run page https base /pick?id&k&o', link)
    check(token not in out.getvalue() and 't=' not in out.getvalue(), 'no page token in the links', out.getvalue())
    code = re.search(r'&k=([^&]+)', link)[1]
    eq(json.loads(W.pick_file(cid).read_text())['code'], code, 'the code is kept in .runner/pick-codes')
    check(code != token, 'the code is not the page token')
    with mock.patch.object(W, 'tailscale_https_urls', lambda port, t: []), mock.patch.object(cmds, 'init', lambda: None), \
            redirect_stdout(out), redirect_stderr(err):
        rc = cmds.cmd_pick_links([cid, 'A,B'])
    eq(rc, 1, 'no https address: no links')
    check('no https address' in err.getvalue(), 'and it says so', err.getvalue())
    ran = []
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'

    def fake_run(argv):
        ran.append(argv)
        return 0, 'approved'
    try:
        with mock.patch.object(U, 'RUN', [fake_run]):
            c1, wrong = get(f'{base}/pick?id={cid}&o=B&k=nope')
            c2, tok = get(f'{base}/pick?id={cid}&o=B&k={token}')
            c3, ok = get(f'{base}{link[link.index("/pick"):]}')
            c4, again = get(f'{base}{link[link.index("/pick"):]}')
    finally:
        srv.stop()
    eq((c1, c2), (403, 403), 'a wrong code, or the page token, is refused')
    check(b'unknown' in wrong, 'and says the link is unknown', wrong)
    eq(c3, 200, 'the good code answers')
    eq(ran, [['plan', 'confirm', cid, 'go with B: drawer']], 'it runs plan confirm with the option name')
    check(b'Approved B (drawer)' in ok and f'the run starts {build}'.encode() in ok, 'and says what it did', ok)
    eq(c4, 409, 'the code is burnt: a second tap is refused')
    check(b'used already' in again, 'and says it was used', again)
    check(json.loads(W.pick_file(cid).read_text()).get('used'), 'the code file is marked used')
    # an item settled already
    P.block('F1', 'DECIDE: which colour', todo=S.C.todo)
    code1 = W.pick_code('F1')
    with mock.patch.object(U, 'need_label', lambda tid: ''):
        eq(W.pick('F1', 'A', code1)[0], 409, 'an item settled already is refused')
    eq(W.pick_code('F1'), code1, 'an unused code is kept for the next links')
    with mock.patch.object(U, 'RUN', [fake_run]):
        eq(W.pick('F1', 'A', code1)[0], 200, 'a DECIDE answers too')
    eq(ran[-1], ['plan', 'confirm', 'F1', 'go with A'], 'with its option')
    check(W.pick_code('F1') != code1, 'once used, new links get a new code')
    eq(W.pick('../x', 'A', code1)[0], 403, 'a bad id is unknown')
    eq(W.pick('F1', '', '')[0], 403, 'no code: unknown')


def test_outbox_f137(tmp: Path) -> None:
    """F137: the page draws an action at once and keeps it in an outbox (localStorage) until the run answers; it
    is sent again after a drop or a reload with the same client id, which the run page runs only once. A failed
    action stays, with Retry and Discard. New chats start without waiting, and messages to a chat still starting
    go once it has its name."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    ran = []
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 7 is starting in a hidden '
                                                                            'terminal'))[1]]):
            _, a = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k1'})
            _, b = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k1'})
            _, c = post(url, {'name': 'new_control', 'args': {'wait': False}, 'cid': 'k2'})
            _, d = post(url, {'name': 'concept_chat', 'args': {'cid': 'K5', 'title': 'T', 'wait': False}, 'cid': 'k3'})
    finally:
        srv.stop()
    eq([x[:3] for x in ran], [['control', '--new', '--no-wait']] * 3, 'k1 ran once; k2 and the concept chat ran')
    eq((a['ok'], a['name'], b.get('again'), b['name'], c.get('again')), (True, 'c7', True, 'c7', None),
       'a copy of k1 answers with its first result; a new cid runs again')
    eq(d['name'], 'c7', 'a concept chat starts without waiting too')
    once, n = W.ActsOnce(), []

    def boom():
        n.append(1)
        raise RuntimeError('cut off')
    for _ in range(2):
        try:
            once.run('x', boom)
        except RuntimeError:
            pass
    eq(len(n), 2, 'an action that did not finish runs again for the same cid')
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        def crash(name, **a):
            raise RuntimeError('disk full')
        with mock.patch.object(U, 'act', crash):
            code, e = post(url, {'name': 'chat_to', 'args': {'text': 'x'}, 'cid': 'k9'})
        eq((code, e['ok'], e['out']), (200, False, 'chat_to failed: disk full'),
           'an action that crashes answers as failed (Retry, Discard), so the outbox does not send it for ever')
        gate, ran2 = __import__('threading').Event(), []

        def slow(name, **a):
            ran2.append(1)
            gate.wait(10)
            return {'ok': True}
        with mock.patch.object(U, 'act', slow), mock.patch.object(W.ActsOnce, 'WAIT', 0.2):
            t = __import__('threading').Thread(target=post, args=(url, {'name': 'chat_to', 'args': {}, 'cid': 'k10'}))
            t.start()
            while not ran2:
                __import__('time').sleep(0.02)
            code, w = post(url, {'name': 'chat_to', 'args': {}, 'cid': 'k10'})
            gate.set()
            t.join(10)
        eq((code, len(ran2)), (503, 1), 'a copy of an action still running gets 503 (sent again later), not a failure')
    finally:
        srv.stop()
    eq(once.run('', lambda: {'ok': True}), {'ok': True}, 'no cid: it just runs')
    page = W.PAGE.read_text(encoding='utf-8')
    for part in ("JSON.stringify({name:it.name,args:it.args,cid:it.cid})", "addEventListener('online',()=>drain())",
                 'id="obbar"', 'id="obpop"', 'obChatRows()', 'h+=obBubbles(n)', 'obCards(x=>x.concept||x.kq)',
                 "if(OB.offline)drain()", "outbox('chat_to',{text:msg,to}"):
        check(part in page, f'the page has {part}')
    send = page.split('async function send(){', 1)[1].split('\n}', 1)[0]
    check("act('chat_to'" not in send, 'a message no longer waits for chat_to before leaving the box', send)
    if not shutil.which('node'):
        print('  (no node here: the outbox script test is skipped)')
        return
    it = lambda cid, name='answer', **k: {'cid': cid, 'name': name, 'args': k.pop('args', {}), 'state': 'sending',  # noqa: E731
                                          'say': cid, **k}
    nc = it('n1', 'new_control', newchat=True)
    msg = it('m1', 'chat_to', args={'to': '@n1', 'text': 'hi'})
    box = [nc, msg, it('a1', need='F1'), it('p1', concept='F9')]
    got = logic_js([
        ['obParse', json.dumps(box + [{'cid': 'z'}, 'junk', {**nc, 'state': 'odd'}])], ['obParse', '{bad'],
        ['obNext', box], ['obNext', [msg]],
        ['obSettle', box, 'n1', {'ok': True, 'name': 'c7'}],
        ['obSettle', box, 'n1', {'ok': False, 'out': 'no run is up\nmore'}],
        ['obSettle', box, 'a1', {'ok': True}],
        ['obRetry', [{**nc, 'state': 'failed', 'err': 'x'}, {**msg, 'state': 'failed'}], 'm1', 'n2'],
        ['obDrop', box, 'n1'],
        ['obName', box, '@n1', 'c8'],
        ['obCounts', [nc, {**msg, 'state': 'failed'}]],
        ['obHidden', box, 'need'], ['obHidden', [{**box[2], 'state': 'failed'}], 'need'], ['obHidden', box, 'concept'],
        ['obPill', {'sending': 2, 'failed': 1}, False], ['obPill', {'sending': 1, 'failed': 0}, True],
        ['obPill', {'sending': 0, 'failed': 0}, False],
    ])
    eq([x['cid'] for x in got[0]], ['n1', 'm1', 'a1', 'p1'], 'a stored outbox keeps only whole items')
    eq(got[1], [], 'a broken store is an empty outbox')
    eq(got[2]['cid'], 'n1', 'items go in order')
    eq(got[3], None, 'a message to a chat still starting waits for it')
    eq([(x['cid'], x['args'].get('to')) for x in got[4]], [('m1', 'c7'), ('a1', None), ('p1', None)],
       'a new chat that answers leaves, and its messages go to its name')
    eq([(x['cid'], x['state'], x.get('err')) for x in got[5][:2]],
       [('n1', 'failed', 'no run is up'), ('m1', 'failed', 'the new chat did not start')],
       'a failed new chat stays with its first line, and so do its messages')
    eq([x['cid'] for x in got[6]], ['n1', 'm1', 'p1'], 'an answered item leaves the outbox')
    eq([(x['cid'], x['state'], x['args'].get('to')) for x in got[7]], [('n2', 'sending', None), ('m1', 'sending', '@n2')],
       "Retry on a message waiting for a chat that did not start retries the chat, under a new cid")
    eq([x['cid'] for x in got[8]], ['a1', 'p1'], 'Discard on a new chat drops its messages too')
    eq(got[9][1]['args']['to'], 'c8', 'a chat the snapshot names gets its messages')
    eq(got[10], {'sending': 1, 'failed': 1}, 'the pill counts')
    eq((got[11], got[12], got[13]), (['F1'], [], ['F9']), 'only items still sending hide their cards')
    eq(got[14], ['2 sending', '1 failed · tap to see'], "the pill's words")
    eq(got[15], ['1 waiting for the connection'], 'offline, it says it waits')
    eq(got[16], [], 'nothing in the outbox: no pill')


SENT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const kept = {}, store = {get: k => kept[k] || '', set(k, v) { kept[k] = v }};
const said = [], toast = t => said.push(t), render = () => {}, tq = p => p, obDraw = () => {}, talkHear = () => {};
const esc = t => String(t), LOGO = () => '', threadTitle = n => n, PN = () => 'p', md = t => t, I = {chev: ''};
const isAgent = () => false, chats = () => [], takeSnap = () => {}, TK = {playing: ''}, sureHTML = () => '';
const opened = [], open = n => { S.thread = n; opened.push(n) };
let feeds = {}, answers = [], posts = [];
const fetch = async (p, o) => {
  if (p === 'act') { posts.push(JSON.parse(o.body)); return {status: 200, json: async () => answers.shift() || {ok: true, at: 100}} }
  return {json: async () => feeds[p.split('/')[1]] || {ok: false, entries: [], out: 'no transcript'}};
};
const S = {snap: {sessions: [{name: 'c3', state: 'live'}], needs: [], concepts: []}, feeds: {}, sent: {}, ob: [], openSteps: {}, thread: null, waitNew: null};
const feedOf = n => (S.feeds[n] || {}).entries || [], sessionOf = n => S.snap.sessions.find(s => s.name === n);
const OB = {busy: false, offline: false, timer: 0, wait: 2000}, OB_KEY = 'ob', SENT_KEY = 'sent';
let cids = 0;
const newCid = () => 'k' + (++cids), realNow = Date.now;
let skew = 0;
Date.now = () => realNow() + skew;
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
eval(logic.replace(/if\(typeof module[^\n]*/, '') + line('function obChange(') + grab('function outbox(') + grab('async function drain(')
  + grab('function obDone(') + grab('function obBubbles(') + grab('function convo(') + grab('async function loadFeed(')
  + grab('function addSent(') + grab('function carrySent(') + line('const keepSent=') + line('const busy=n') + line('const obState=') + line('const obBtns=') + `
const tick = () => new Promise(r => setTimeout(r, 5));
const settle = async () => { for (let i = 0; i < 6; i++) await tick() };
const shows = (n, t) => convo(n).includes(t);
(async () => {
  const out = {};
  // a new chat with an ask: shown as pending in its thread until the feed has it
  const it = outbox('quick_ask', {key: 'since'}, {newchat: true, say: 'Since', ask: 'what happened?'});
  answers.unshift({ok: true, name: 'c3', at: 100, ask: 'what happened?'});
  S.thread = '@' + it.cid; await settle();
  out.opened = opened.slice(); out.askBeforeFeed = shows('c3', 'what happened?');
  await loadFeed('c3'); out.askNoTranscript = shows('c3', 'what happened?');
  feeds.c3 = {ok: true, entries: [{kind: 'you', text: 'another'}]};
  await loadFeed('c3'); out.askOtherEntry = shows('c3', 'what happened?');
  feeds.c3.entries.push({kind: 'you', text: 'what happened?', at: 130});
  out.starting = shows('c3', 'Starting the chat…');
  await loadFeed('c3'); out.askLanded = [(S.sent.c3.pending || []).length, kept.sent, shows('c3', 'Starting the chat…')];
  feeds.c3.entries.push({kind: 'say', text: 'Hello.'});
  await loadFeed('c3'); out.replied = shows('c3', 'Starting the chat…');
  // two messages: each leaves only when its own text is in the feed, and an older same text does not count
  for (const t of ['yes', 'and more']) { answers.push({ok: true, at: 200}); outbox('chat_to', {text: t, to: 'c3'}, {text: t, say: t}); }
  await settle();
  out.kept = JSON.parse(kept.sent).c3.map(p => p.text);
  feeds.c3.entries.push({kind: 'you', text: 'yes', at: 150}, {kind: 'say', text: 'ok'}, {kind: 'you', text: 'and more', at: 210});
  await loadFeed('c3'); out.own = S.sent.c3.pending.map(p => p.text);
  feeds.c3.entries.push({kind: 'say', text: 'Done.'});
  await loadFeed('c3'); skew += 50000; await loadFeed('c3');
  out.failed = S.sent.c3.pending.map(p => [p.text, p.state]);
  out.failedShown = [shows('c3', 'Not delivered'), shows('c3', 'data-sentretry'), shows('c3', 'data-sentdrop')];
  feeds.c3.entries.push({kind: 'you', text: 'yes', at: 260});
  await loadFeed('c3'); out.late = S.sent.c3.pending.length;
  console.log(JSON.stringify(out));
  process.exit(0);
})();`);
"""


def test_sent_b154(tmp: Path) -> None:
    """B154: a sent message stays shown until its own text is in the feed as 'you': a new chat's ask is carried over,
    and one that never lands is shown as not delivered, with Retry."""
    if not shutil.which('node'):
        print('  (no node here: the sent message script test is skipped)')
        return
    p = lambda text, at=100, **k: {'text': text, 'at': at, 'since': 0, 'state': 'sent', **k}  # noqa: E731
    you = lambda text, at=110: {'kind': 'you', 'text': text, 'at': at}  # noqa: E731
    left = lambda ps, es: ['sentLeft', ps, es]  # noqa: E731
    got = logic_js([
        left([p('hi')], [{'kind': 'say', 'text': 'hi'}]),
        left([p('hi')], [you('hi', 90)]), left([p('hi')], [you('hi')]),
        left([p('hi'), p('hi')], [you('hi')]),
        left([p('a  b\n\nc')], [you('\n\n<pasted_content id="36f3">\na b\nc\n</pasted_content>')]),
        left([p('one'), p('two')], [you('one\ntwo')]),
        left([p('yes')], [you('yes please')]),
        left([p('fix B1')], [you('fix B1\n\n<runner-waiting>\nF2: x\n</runner-waiting>')]),
        left([p('look\n\nAttached: /r/a.png')], [you('look\n\n[Image #1]')]),
        left([p('hello', talk=True)], [you('(Talk: answer as speech.) hello')]),
        ['sentStep', [p('x', since=1000)], [{'kind': 'say', 'text': 'ok'}], 60000, True],
        ['sentStep', [p('x', since=1000)], [{'kind': 'tool', 'text': 'Bash(ls)'}], 60000, True],
        ['sentStep', [p('x', since=1000)], [{'kind': 'tool', 'text': 'Bash(ls)'}], 60000, False],
        ['sentStep', [p('x', since=1000, first=True)], [], 60000, True],
        ['sentStep', [p('/clear', since=1000)], [], 60000, True],
        ['sentStep', [p('x', since=1000)], [you('later', 200)], 60000, True, True],
        ['sentStep', [p('x', 300, since=1000)], [you('before', 200), {'kind': 'say', 'text': 'ok'}], 60000, True, True],
        left([p('Attached: /r/a.png')], [you('[Image #1]')]),
    ])
    eq([len(x) for x in got[:3]], [1, 1, 0], "only your own words, and only since they were sent, make it land")
    eq(len(got[3]), 1, 'one entry lands one of two same messages')
    eq([len(x) for x in got[4:10]], [0, 0, 1, 0, 0, 0],
       'a paste wrap, merged messages, a whole line only, the waiting block, an image, a Talk reminder')
    eq([[(x['text'], x['state']) for x in r] for r in got[10:]],
       [[('x', 'failed')], [('x', 'sent')], [('x', 'failed')], [('x', 'sent')], [], [], [('x', 'failed')], []],
       'not delivered once idle a while; not mid-turn; a chat that ended; longer for a first message; a slash command goes; behind the cut; not before it; a picture alone')
    (tmp / 'driver.js').write_text(SENT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the page', r.stderr[-1500:])
    o = json.loads(r.stdout or '{}')
    eq(o.get('opened'), ['c3'], 'the started chat opens')
    eq([o.get(k) for k in ('askBeforeFeed', 'askNoTranscript', 'askOtherEntry')], [True] * 3,
       "a new chat's ask stays shown before its feed, with no transcript, and past another entry")
    eq(o.get('askLanded'), [0, '', True], 'and leaves once the feed has it')
    eq((o.get('starting'), o.get('replied')), (True, False), 'the starting line stands until the reply')
    eq(o.get('kept'), ['yes', 'and more'], 'kept over a reload')
    eq(o.get('own'), ['yes'], 'only the message in the feed leaves')
    eq((o.get('failed'), o.get('failedShown')), ([['yes', 'failed']], [True] * 3), 'never landed: Not delivered, Retry, Discard')
    eq(o.get('late'), 0, 'one that lands after all leaves')


def test_card_chat_b139(tmp: Path) -> None:
    """B139: a run page button that starts a chat (Add a task, a card's Chat, a quick ask, Take) starts a fresh
    control session (`control --new --ask`) instead of sending to c1 with its whole history; typing in the c1
    chat box with no card context still goes to c1."""
    fake_repo(tmp)

    def no_send(t):
        raise AssertionError(f'a chat-starting button reached c1: {t!r}')
    ran = []
    with mock.patch.object(U, 'SEND', [no_send]), \
            mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 9 is starting'))[1]]):
        q, t = U.act('quick_ask', key='since', wait=False), U.act('take', tid='F1', wait=False)
    eq(ran, [['control', '--new', '--no-wait', '--ask', 'what happened since my last look?', '--no-feed'],
             ['control', '--new', '--no-wait', '--ask', 'do F1 here', '--no-feed']], 'quick_ask and take use new_control')
    eq((q['name'], t['name']), ('c9', 'c9'), 'each names its new chat for the page to open')
    page = W.PAGE.read_text(encoding='utf-8')
    send = page.split('async function send(){', 1)[1].split('\n}', 1)[0]
    check('sendReq(ctx,to,msg)' in send and "newChat(rq.name,rq.args," in send,
          'send() starts a new chat when a card set the context', send)
    check("newChat('quick_ask'" in page and "outbox('quick_ask'" not in page, 'a quick ask starts a new chat', '')
    check("if(c.key==='task_take'){newChat(" in page, "Take back opens the new chat it started", '')
    if not shutil.which('node'):
        print('  (no node here: the send script test is skipped)')
        return
    got = logic_js([['sendReq', {'kind': 'need', 'id': 'R6'}, 'c1', 'About R6, which needs me: hi'],
                    ['sendReq', {'kind': 'new'}, 'c1', 'Add a task: dark mode'],
                    ['sendReq', None, 'c1', 'hello'], ['sendReq', None, 'c6', 'hi c6']])
    eq(got[:2], [{'name': 'new_control', 'args': {'ask': 'About R6, which needs me: hi'}},
                 {'name': 'new_control', 'args': {'ask': 'Add a task: dark mode'}}],
       'a send with S.ctx set calls new_control, not chat_to c1')
    eq(got[2:], [{'name': 'chat_to', 'args': {'text': 'hello', 'to': 'c1'}},
                 {'name': 'chat_to', 'args': {'text': 'hi c6', 'to': 'c6'}}],
       'with no card context the box still goes to its chat (c1 by default)')


def test_short_ask_b152(tmp: Path) -> None:
    """B152: a Needs you card shows its short ask clamped to 2 lines with a More that opens the whole ask in
    place (Less folds it), and the title under it on one line with an ellipsis."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('.q.clamp{display:-webkit-box;-webkit-line-clamp:2' in page, 'a clamped ask is cut at 2 lines', '')
    check('<div class="small ell">${esc(n.id)}${n.title' in page, 'the title line has an ellipsis', '')
    check("q('[data-more]')" in page and 'S.askOpen' in page, 'More opens the ask in place', '')
    if not shutil.which('node'):
        print('  (no node here: the short ask script test is skipped)')
        return
    long = {'id': 'R45', 'title': 'Check the sign-in', 'ask_short': 'Sign in to Chariz and check that Glint downloads.',
            'ask': 'Sign in to Chariz (iFizBox > Sources > Chariz > Sign In) and check that Glint downloads. '
                   'Notes are in .runner/journal/R45.md - reply yes/no'}
    shut, opened, small = logic_js([['needAsk', long, 3, False], ['needAsk', long, 3, True],
                                    ['needAsk', {'id': 'D7', 'ask': 'Which port?', 'ask_short': 'Which port?'}, 0, False]])
    check('<div class="q clamp">Sign in to Chariz and check that Glint downloads.</div>' in shut
          and 'data-more="3"' in shut and '>More<' in shut and 'R45.md' not in shut,
          'a long ask renders short and clamped, with a More control', shut)
    check('R45.md' in opened and '(iFizBox &gt; Sources' in opened and 'clamp' not in opened and '>Less<' in opened,
          'More shows the whole ask, paths and asides too, with Less', opened)
    eq(small, '<div class="q clamp">Which port?</div>', 'a short ask has no More (and is clamped all the same)')


DICT_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
let rec = null, sent = [], toasts = [];
class SR { constructor() { rec = this } start() { this.started = true } stop() { this.onend() } }
const navigator = {language: 'en-US'}, window = {isSecureContext: true};
const ta = {value: 'fix the', focus() {}, setSelectionRange() {}};
const document = {querySelector: s => s === '[data-in]' ? ta : null};
const drafts = {}, store = {set: (k, v) => { drafts[k] = v }, get: k => drafts[k] || ''};
const DRAFT_KEY = k => 'draft:' + k, boxKey = () => 'c3', grow = () => {}, render = () => {};
const toast = t => toasts.push(t), send = () => sent.push(ta.value), TK = {state: ''};
eval(logic + 'const DK={rec:null,key:\'\',base:\'\'};const dictWhy=()=>\'\';' + grab('function dictShow(') + grab('function dictate(') + `
  dictate();
  const listening = !!DK.rec;
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'merge'}], {isFinal: false})]});
  const interim = ta.value;
  rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'merge conflict'}], {isFinal: true})]});
  dictate();
  console.log(JSON.stringify({listening, interim, after: ta.value, draft: drafts['draft:c3'], stopped: DK.rec === null, sent, toasts}));`);
"""


def test_chat_box_f115(tmp: Path) -> None:
    """F115: the message box has a dictation mic beside attach whose words go into the box to edit (nothing is
    sent), and says why it cannot listen on plain http or without speech recognition; a chat looks like the
    terminal: monospace (the --mono token), the [ui] theme's terminal colours, a '>' prompt and tool lines."""
    page = W.PAGE.read_text(encoding='utf-8')
    box = page.split('function box(ph,foot){', 1)[1].split('\n}\n', 1)[0]
    check('data-clip' in box and 'dictButton(dictWhy()' in box and box.index('data-clip') < box.index('dictButton('),
          'the box draws the mic button, right after attach', box[-600:])
    check("if(q('[data-dict]'))return dictate();" in page, 'a tap on it dictates')
    check('.main.term .msgs{font:14px/1.55 var(--mono)' in page and '.main.term .box textarea{font:16px/1.45 var(--mono)}' in page,
          'a chat and its box use the monospace font token (16px: a phone does not zoom)')
    check(".main.term .u::before{content:'>'" in page and ".stepbox .tl::before{content:'● '" in page
          and '⎿' in page, "a '>' prompt on your messages, Claude Code-like tool lines")
    check("main.classList.toggle('term',chatOn)" in page and "fetch('term'+location.search)" in page,
          "a chat takes the terminal look and the [ui] theme's colours from the terminal-style page")
    check('@media (pointer:coarse){.tool{height:40px;min-width:40px}.send{width:40px;height:40px}}' in page,
          'the box buttons stay touch-sized on a phone')
    if not shutil.which('node'):
        print('  (no node here: the dictation script test is skipped)')
        return
    got = logic_js([['dictProblem', False, True], ['dictProblem', True, False], ['dictProblem', True, True],
                    ['dictButton', '', False, 'MIC'], ['dictButton', '', True, 'MIC'],
                    ['dictButton', 'This browser cannot turn speech into text (Chrome, Edge and Safari can).', False, 'MIC'],
                    ['dictInsert', 'fix the ', ' merge '], ['dictInsert', '', 'hello'], ['dictInsert', 'keep', ''],
                    ['termTokens', '<style id="theme">:root{--bg:#000000;--fg:#e5e5e5;--dim:#737373;--sel:#7f1d1d;'
                     '--line:url(x);color-scheme:dark}</style>'], ['termTokens', '<p>no theme</p>']])
    check('https or localhost' in got[0] and 'Type your message instead.' in got[0],
          'plain http: the dictation mic says it needs https', got[0])
    check('cannot turn speech into text' in got[1], 'no speech recognition: the dictation mic says so', got[1])
    eq(got[2], '', 'https with recognition: it dictates')
    check('data-dict' in got[3] and 'class="tool dict"' in got[3] and 'go into the box to edit' in got[3] and 'MIC' in got[3],
          'the mic button says its words go into the box', got[3])
    check('tool dict on' in got[4] and 'Stop dictating' in got[4] and 'aria-pressed="true"' in got[4],
          'while it listens it shows so and stops on a tap', got[4])
    check('dict off' in got[5] and 'title="This browser cannot turn speech into text' in got[5] and 'disabled' not in got[5],
          'one that cannot listen says why in its label and stays tappable (a tap says why)', got[5])
    eq(got[6:9], ['fix the merge', 'hello', 'keep'], 'the words heard go after what the box held')
    eq(got[9], {'tokens': {'bg': '#000000', 'fg': '#e5e5e5', 'dim': '#737373'}, 'mode': 'dark'},
       "the theme's terminal colours, hex only, and its mode")
    eq(got[10], {'tokens': {}, 'mode': ''}, 'no theme: the app keeps its own colours')
    (tmp / 'driver.js').write_text(DICT_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs dictate()', r.stderr[-800:])
    d = json.loads(r.stdout or '{}')
    eq((d.get('listening'), d.get('interim'), d.get('after'), d.get('draft'), d.get('stopped')),
       (True, 'fix the merge', 'fix the merge conflict', 'fix the merge conflict', True),
       'dictation fills the box as it hears, keeps it as the draft, and a second tap stops it')
    eq((d.get('sent'), d.get('toasts')), ([], []), 'nothing is sent: the words wait in the box to edit')


def test_home_switcher_f134(tmp: Path) -> None:
    """F134: through Runner Home (/p/KEY/) the sidebar opens with a project switcher: every Home project from
    Home's /projects, running/idle/off and its needs-you count, each a link to /p/KEY/?t=TOKEN on the same Home
    address; Home's own page is the same app in Home mode (HOME_PAGE), with All projects and Devices."""
    page = W.PAGE.read_text(encoding='utf-8')
    check("fetch(tq(HB+'projects'))" in page, "the switcher reads Home's /projects, with the page's token")
    check('${HB?switcher():' in page and 'data-psw' in page, 'the sidebar starts with the switcher when Home is around')
    check("nav.concat([['projects','All projects']])" in page and 'projects:projectsHTML' in page,
          'and the run app has an All projects view')
    run_page = W.page_html('app').decode()
    home_page = W.page_html('app', home=True).decode()
    check('const HOME_PAGE=/*HOME_PAGE*/false;' in run_page and 'const HOME_PAGE=true;' in home_page and
          '<title>Runner Home</title>' in home_page, "Home's page is the run app with HOME_PAGE on", home_page[:600])
    if not shutil.which('node'):
        print('  (no node here: the switcher script test is skipped)')
        return
    ps = [{'key': 'alpha', 'name': 'alpha', 'state': 'running', 'paused': False, 'needs': 2},
          {'key': 'beta two', 'name': 'beta two', 'state': 'idle', 'paused': True, 'needs': 0},
          {'key': 'gamma', 'name': 'gamma', 'state': 'off', 'needs': None}]
    got = logic_js([['switcherRows', ps, 'alpha', '/', 'HT&1'],
                    ['homeBase', '/p/alpha/', False], ['homeBase', '/', True], ['homeBase', '/', False],
                    ['homeKey', '/p/beta%20two/'], ['homeKey', '/'],
                    ['projectButtons', {'state': 'off'}],
                    ['projectButtons', {'state': 'running', 'paused': False, 'page': 'p/alpha/'}],
                    ['projectWords', {'state': 'idle', 'paused': True, 'slots': 1, 'running': [], 'left': 3}]])
    eq([(r['key'], r['said'], r['needs'], r['href'], r['on']) for r in got[0]],
       [('alpha', 'running', 2, '/p/alpha/?t=HT%261', True), ('beta two', 'paused', 0, '/p/beta%20two/?t=HT%261', False),
        ('gamma', 'off', 0, '/p/gamma/?t=HT%261', False)],
       "the switcher lists Home's projects with their state and needs-you count, each linking /p/KEY/?t=TOKEN")
    eq(got[1:6], ['/', '/', '', 'beta two', ''],
       "Home's address from the page's path: /p/KEY/ through Home, / on Home's own page, none on a run's own port")
    eq([b['label'] for b in got[6]], ['Start run', 'Unlist'], 'a project that is off: Start run')
    eq([(b['label'], b.get('a'), b.get('arg')) for b in got[7]],
       [('Open', None, None), ('Pause', 'pause', None), ('−1 slot', 'slots', '-1'), ('+1 slot', 'slots', '+1'),
        ('Stop', 'stop', None), ('Unlist', None, None)], "one that runs: Open, Pause, the slots and Stop, as Home's were")
    eq(got[8], 'paused · 1 slot · 3 queued', 'the words under a project')


def test_project_name_b153(tmp: Path) -> None:
    """B153: the run page shows the project's name, not agent-runner: the window title ('proj · runner'), the
    top-left (a link to Runner Home), the logo's letter and a chat's lead label."""
    fake_repo(tmp)
    run_page = W.page_html('app').decode()
    check('<title>proj · runner</title>' in run_page, 'the served title is the project first', run_page[:400])
    check("document.title=pageTitle(S.snap.project)" in run_page, 'and the snapshot keeps it')
    check('${HB?switcher():brand()}' in run_page and '<b>agent-runner</b>' not in run_page,
          'the top-left is the project name (brand), not agent-runner')
    check('class="logo">ar<' not in run_page and "'agent-runner')}</div>" not in run_page,
          'no ar logo, no agent-runner lead label')
    with mock.patch.object(W, 'home_port', lambda: 0):
        eq(W.home_address(), {}, 'Home not installed: no Home link')
    cfg = tmp / 'cfg'
    cfg.mkdir()
    (cfg / 'home.token').write_text('HT\n')
    from agent_runner import home as HM
    with mock.patch.object(W, 'home_port', lambda: 8770), mock.patch.object(HM, 'config_dir', lambda: cfg):
        eq(W.home_address(), {'port': 8770, 't': 'HT'}, "Home's port and token for the link")
        eq(W.with_extras({})['home'], {'port': 8770, 't': 'HT'}, 'in the run page snapshot')
    if not shutil.which('node'):
        print('  (no node here: the Home link script test is skipped)')
        return
    home = {'port': 8770, 't': 'H&T'}
    got = logic_js([['homeHref', '', 'RT', home, {'protocol': 'http:', 'hostname': 'box'}],
                    ['homeHref', '', 'RT', home, {'protocol': 'https:', 'hostname': 'box.ts.net'}],
                    ['homeHref', '/', 'RT', home, {'protocol': 'http:', 'hostname': 'box'}],
                    ['homeHref', '', 'RT', {}, {'protocol': 'http:', 'hostname': 'box'}],
                    ['pageTitle', 'ifizbox'], ['pageTitle', '']])
    eq(got[:4], ['http://box:8770/?t=H%26T', 'http://box.ts.net:8770/?t=H%26T', '/?t=RT', ''],
       "the top-left name links to Runner Home: its port and token on the page's host (over http, also from https); "
       "through Home, Home's own base; none while Home is not installed")
    eq(got[4:], ['ifizbox · runner', 'agent-runner'], 'the window title: the project first')


def test_release_row_f131(tmp: Path) -> None:
    """F131: the page queue shows the release last, as a queued task or a dimmed placeholder, in the row's words."""
    page = W.PAGE.read_text(encoding='utf-8')
    check('qs=planQueue(S.snap)' in page and 'q.placeholder?nextReleaseCard(q):planCard(q)' in page
          and '.card.relph{opacity' in page, 'the Queue view draws planQueue, the placeholder dimmed')
    if not shutil.which('node'):
        print('  (no node here: the release row script test is skipped)')
        return
    task, parked = {'id': 'F1', 'state': 'ready'}, {'id': 'F9', 'state': 'parked'}
    ph = {'id': '', 'title': 'Next release', 'words': 'auto at 10 landed: 6/10', 'placeholder': True}
    row = {'id': 'V5', 'title': 'Release', 'words': 'building', 'placeholder': False}
    v = {'id': 'V5', 'state': 'running s2 6m', 'release': row}
    got = logic_js([['planQueue', {'queue': [task, parked], 'release_row': ph}],
                    ['planQueue', {'queue': [task, parked, v], 'release_row': row}],
                    ['planQueue', {'queue': [task]}], ['planWords', v, []]])
    eq(got, [[task, ph], [task, v], [task], 'building'], 'the release last (Parked is its own group)')


SCROLL_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const line = s => { const i = page.indexOf(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
// a scrolling box as the page has it: keyed rows of a height each, drawn from its markup ('key:height key:height')
class Box {
  constructor(h) { this.h = h; this._top = 0; this.rows = []; this.on = {}; this.cls = new Set();
    this.classList = {add: c => this.cls.add(c), remove: c => this.cls.delete(c), toggle: (c, v) => v ? this.cls.add(c) : this.cls.delete(c), contains: c => this.cls.has(c)} }
  set innerHTML(v) { this.v = v; let y = 0;
    this.rows = v.replace(/<[^>]*>/g, ' ').split(' ').filter(x => x.includes(':')).map(r => { const [k, n] = r.split(':'); const e = {dataset: {k}, y, n: +n, cls: new Set()};
      e.classList = {add: c => e.cls.add(c)}; e.getBoundingClientRect = () => ({top: e.y - this._top, bottom: e.y + e.n - this._top}); y += +n; return e });
    this.scrollTop = this._top }
  get innerHTML() { return this.v || '' }
  get scrollHeight() { return this.rows.reduce((a, r) => a + r.n, 0) }
  get clientHeight() { return this.h }
  get offsetWidth() { return 1 }
  get scrollTop() { return this._top }
  set scrollTop(v) { this._top = Math.max(0, Math.min(v, Math.max(0, this.scrollHeight - this.h))) }
  getBoundingClientRect() { return {top: 0, bottom: this.h} }
  querySelectorAll(s) { return s === '[data-k]' ? this.rows : [] }
  contains() { return false }
  addEventListener(t, f) { this.on[t] = f }
}
const els = {body: new Box(100), dock: new Box(10), top: new Box(10), jump: new Box(10)};
const $ = k => els[k] = els[k] || new Box(10);
const ta = {value: 'hello', dataset: {}};
const document = {activeElement: null, hidden: false, querySelector: s => s === '[data-in]' ? ta : s === '.main' ? {classList: {toggle() {}}, style: {}} : null};
const window = {};
let HOME_PAGE = false, VIEW = 'a:60 b:60 c:60', CHAT = 'm1:80 m2:80';
const S = {snap: {sessions: []}, view: 'home', thread: null, f: {}, atts: [], ob: [], feeds: {}, live: true, sheet: ''};
const HI = {i: null}, TERM = {mode: ''}, I = {down: ''}, keysLine = () => '', esc = s => s, tq = p => p;
const markSeen = () => {}, obHide = () => {}, obDraw = () => {}, side = () => {}, sheetDraw = () => {}, topHTML = () => 'x:1';
const isAgent = () => false, threadTitle = n => n, convo = () => CHAT, box = () => 'box', store = {get: () => '', set() {}};
const boxKey = () => S.thread || 'home', grow = () => {}, slashShow = () => {}, talkHTML = () => CHAT, histAdd = () => {};
const homeHTML = () => VIEW, statusHTML = () => VIEW, planHTML = () => VIEW, conceptsHTML = () => VIEW, settingsHTML = () => VIEW, projectsHTML = () => VIEW;
const DRAFT_KEY = k => k, toast = () => {}, open = n => { S.thread = n; render(true) }, outboxed = [];
const talkMic = () => 'mic', talkFoot = () => '', talkDraw = () => {};
const outbox = (n, a) => { outboxed.push([n, a.text]); CHAT += ' mine' + outboxed.length + ':40'; render(true) };
eval(logic + line('function setHTML(') + grab('function keepScroll(') + grab('function keysIn(').split('\nfunction enter')[0]
  + grab('function enter(') + grab('function keepFields(') + line('function viewIn(') + line('const PD=') + 'const selecting=()=>false;'
  + line('let lastPlace=') + line('S.at={};') + line('const chatShown=') + line('function toEnd(') + line('function jumpDraw(')
  + grab('function render(') + line("$('body').addEventListener('scroll'") + grab('async function send(') + `
(async () => {
  const b = $('body'), out = {}, scroll = y => { b.scrollTop = y; b.on.scroll() };
  // every view: a refresh keeps the reading position, whatever came in above it
  out.views = {};
  for (const v of ['home', 'status', 'plan', 'concepts', 'settings']) {
    S.view = v; VIEW = 'a:60 b:60 c:60 d:60'; render(true);
    b.scrollTop = 70; VIEW = 'a:60 b:60 c:60 d:60 e:60'; render();
    const same = b.scrollTop;
    VIEW = 'new:35 a:60 b:60 c:60 d:60 e:60'; render();
    out.views[v] = [same, b.scrollTop];
  }
  b.scrollTop = 0; VIEW = 'top:20 ' + VIEW; render(); out.atTop = b.scrollTop;
  out.entered = b.rows.filter(r => r.cls.has('enter')).map(r => r.dataset.k);
  VIEW = VIEW + ' '; b._h = ''; render(); out.still = b.rows.filter(r => r.cls.has('enter')).length;
  b.scrollTop = 50; S.view = 'plan'; render(true); S.view = 'settings'; render(true); out.back = b.scrollTop;
  // a chat: opens at its end, follows what comes in, stays put once scrolled up, shows the jump button, goes to the end on send
  S.thread = 'c2'; render(true);
  const left = () => b.scrollHeight - b.scrollTop - b.clientHeight;
  out.open = left();
  CHAT += ' m3:90'; render(); out.follows = left();
  scroll(5); CHAT += ' m4:90'; render();
  out.up = [b.scrollTop, $('jump').cls.has('on'), $('jump').innerHTML];
  ta.value = 'hello'; await send(); out.sent = [outboxed[0], left(), $('jump').cls.has('on')];
  scroll(0); toEnd(); out.jump = [left(), $('jump').cls.has('on')];
  scroll(10); PD.down = true; CHAT += ' m5:50'; render(); out.held = b.innerHTML.includes('m5'); PD.down = false; render(); out.after = [b.innerHTML.includes('m5'), b.scrollTop];
  console.log(JSON.stringify(out));
})();`);
"""


def test_scroll_f83(tmp: Path) -> None:
    """F83: a refresh keeps the reading position in every view (what came in above moves nothing); a chat opens at its
    newest message, follows it unless the person scrolled up (then a jump button), and goes to its end on a send."""
    if not shutil.which('node'):
        print('  (no node here: the scroll script test is skipped)')
        return
    (tmp / 'driver.js').write_text(SCROLL_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs render()', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    for v, (same, above) in (got.get('views') or {}).items():
        eq((same, above), (70, 105), f'{v}: a refresh keeps scrollTop, and a card above it moves nothing on screen')
    eq(len(got.get('views') or {}), 5, 'every view was looked at')
    eq(got.get('atTop'), 0, 'at the very top, the new thing shows')
    eq((got.get('entered'), got.get('still')), (['top'], 0), 'only what is new comes in moving; a redraw moves nothing')
    eq(got.get('back'), 50, 'coming back to a view returns to where it was')
    eq(got.get('open'), 0, 'a chat opens at its newest message')
    eq(got.get('follows'), 0, 'and follows what comes in')
    eq(got.get('up'), [5, True, 'New message'], 'scrolled up: it stays put, and the jump button says so')
    eq(got.get('sent'), [['chat_to', 'hello'], 0, False], 'a send goes to the end')
    eq(got.get('jump'), [0, False], 'the jump button goes to the latest')
    eq((got.get('held'), got.get('after')), (False, [True, 10]), 'a press holds the refresh back until it ends')


HOLD_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8').replace(/\r\n/g, '\n');
const grab = (start) => { const i = page.indexOf(start); return page.slice(i, page.indexOf('\n}\n', i) + 2); };
const line = s => { const i = page.indexOf(s); if (i < 0) throw new Error(s); return page.slice(i, page.indexOf('\n', i)) + '\n' };
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const spoken = [];
const window = {speechSynthesis: {cancel() {}, getVoices: () => [{name: 'Ava', lang: 'en-GB'}], speak(u) { if (u.text) spoken.push(u) }}};
const speechSynthesis = window.speechSynthesis;
class SpeechSynthesisUtterance { constructor(t) { this.text = t } }
let rec = null, starts = 0, sent = [];
class SR { constructor() { rec = this } start() { starts++ } stop() { this.stopped = true; this.onend() } }
const navigator = {language: 'en-US'}, handlers = {};
const document = {addEventListener(t, f) { (handlers[t] = handlers[t] || []).push(f) }};
const fire = (t, e) => (handlers[t] || []).forEach(f => f(e));
const TK = {rec: null, heard: '', state: '', wait: null, said: '', unlocked: false, note: '', playing: '', hold: false, again: false};
const S = {view: 'talk', thread: null, feeds: {c5: {entries: [{kind: 'you', text: 'hi', id: 'a'}, {kind: 'say', text: 'One **thing**.', id: 'b'}]}}};
const feedOf = n => S.feeds[n].entries, talkName = () => 'c5', micWhy = () => '', toast = () => {}, render = () => {};
const talkSend = t => sent.push(t), talkTyping = () => false, voices = () => speechSynthesis.getVoices();
eval(logic + `
let TS = talkSetParse('');
` + grab('function speak(') + line('function hush(') + grab('function playReply(') + grab('function listen(')
  + page.slice(page.indexOf('/* F124: hold to talk'), page.indexOf('/* F124: a swipe right anywhere')) + `
const out = {defaults: TS, parsed: talkSetParse('{"read":false,"voice":"Ava","mic":"hold","auto":true}'), junk: talkSetParse('nope')};
const mic = {target: {closest: s => s === '[data-mic]' ? {} : null}, button: 0};
fire('pointerdown', mic); out.tapStarts = starts;
TS = {...TS, mic: 'hold'};
fire('pointerdown', mic); out.holdStarts = [starts, TK.state];
rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'what is running'}], {isFinal: true})]});
out.before = sent.slice(); fire('pointerup', mic); out.holdSent = [sent.slice(), rec.stopped];
// a reply read to its end: auto listen listens again, and one silent turn ends it
TS = {...TS, mic: 'tap', auto: true, voice: 'Ava'}; starts = 0;
speak('Two agents are running.'); out.voice = [spoken[0].voice.name, spoken[0].lang];
spoken[spoken.length - 1].onend(); out.auto = [starts, TK.state];
rec.onend(); out.silent = [starts, TK.state, TK.note];
speak('Stopped early.'); const u = spoken[spoken.length - 1]; hush(); u.onend(); out.stopped = [starts, TK.state];
TS = {...TS, auto: false, read: false}; speak('No more.'); spoken[spoken.length - 1].onend(); out.off = starts;
playReply('b'); out.play = [TK.playing, spoken[spoken.length - 1].text, TK.state];
playReply('b'); out.playStop = TK.playing;
TS = {...TS, mic: 'tap'}; listen(); rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'x'}], {isFinal: true})]});
const n0 = sent.length; playReply('b'); out.playOver = [sent.length - n0, TK.rec, TK.playing];
starts = 0; listen(); out.micStops = [starts, TK.playing];
TS = {...TS, mic: 'hold'}; listen(); fire('pointerdown', mic); rec.onresult({resultIndex: 0, results: [Object.assign([{transcript: 'auto'}], {isFinal: true})]}); fire('pointerup', mic); out.autoHeld = sent[sent.length - 1];
console.log(JSON.stringify(out));`);
"""


# B160: the keyboard: a stubbed visualViewport, over the same scrolling box
KB_DRIVER = SCROLL_DRIVER.split("const els = ")[0] + r"""
const on = {}, VVS = {height: 800, offsetTop: 0, scale: 1, addEventListener: (t, f) => on[t] = f};
const window = {visualViewport: VVS, scrollY: 0, scrollTo(x, y) { this.scrollY = y }};
const cls = () => { const c = new Set(); return {toggle: (k, v) => v ? c.add(k) : c.delete(k), contains: k => c.has(k)} };
const els = {app: {style: {}, classList: cls()}, body: new Box(600)};
const $ = k => els[k], box = {matches: () => true, closest: () => null}, docOn = {};
const document = {activeElement: null, documentElement: {clientHeight: 800}, addEventListener: (t, f) => docOn[t] = f};
const S = {view: 'talk', thread: null, pin: true}, jumpDraw = () => {};
eval(line('const atEnd=') + line('const chatShown=') + line('function toEnd(') + page.slice(page.indexOf('const VV='), page.indexOf('function grow(')) + `
const b = $('body'), out = {}, left = () => b.scrollHeight - b.scrollTop - b.clientHeight;
const app = () => [$('app').style.height || '', $('app').style.top || '', $('app').classList.contains('kb')];
// what the layout does: the chat loses what .app loses
const vv = (h, top, t = 'resize') => { VVS.height = h; VVS.offsetTop = top; b.h = h - 200; on[t]() };
b.innerHTML = 'a:900 b:900'; toEnd();
vv(700, 0); out.bar = app();
document.activeElement = box;
window.scrollY = 90; vv(420, 260); out.open = [app(), left(), window.scrollY];
vv(420, 0, 'scroll'); out.panned = [app(), left()];
vv(380, 10); out.taller = [app(), left()];
vv(800, 24); out.closed = [app(), left()];
S.pin = false; b.scrollTop = 300; vv(420, 260); out.up = b.scrollTop; vv(800, 0);
VVS.scale = 2; vv(400, 50); out.zoom = app(); VVS.scale = 1; vv(800, 0);
document.activeElement = null; vv(420, 0); out.noField = app(); vv(800, 0);
S.view = 'home'; b.scrollTop = 0;
const field = {matches: () => true, closest: () => b, getBoundingClientRect: () => ({top: 400 - b.scrollTop, bottom: 440 - b.scrollTop})};
document.activeElement = field; vv(420, 260); out.field = [app(), b.scrollTop];
field.getBoundingClientRect = () => ({top: 500 - b.scrollTop, bottom: 540 - b.scrollTop});
docOn.focusin({target: field}); out.next = b.scrollTop;
console.log(JSON.stringify(out));`);
"""


def test_keyboard_b160(tmp: Path) -> None:
    """B160: while a phone's keyboard is open .app takes the visual viewport's height and place with no bottom inset, a
    pinned chat stays at its end, a field in a scroller is shown, and closing puts all of it back."""
    css = W.PAGE.read_text(encoding='utf-8').split('<style>', 1)[1].split('</style>', 1)[0]
    check(re.search(r'\.app\.kb\{[^}]*position:fixed[^}]*padding-bottom:0\}', css), 'keyboard open: .app is placed, with no bottom inset')
    check(re.search(r'\.app\{[^}]*padding-bottom:env\(safe-area-inset-bottom', css), 'closed: .app keeps its bottom inset')
    check(re.search(r'\.app\.kb \.dock\{padding-bottom:8px\}', css), 'and the dock its 14px only when closed')
    check('html,body{height:100%;overscroll-behavior:none;overflow:hidden}' in css and 'body{position:fixed;inset:0' in css, 'the document is locked')
    if not shutil.which('node'):
        print('  (no node here: the keyboard script test is skipped)')
        return
    (tmp / 'driver.js').write_text(KB_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs kbFit()', r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    off = ['', '', False]
    eq(got.get('bar'), off, "Safari's own bar is no keyboard")
    eq(got.get('open'), [['420px', '260px', True], 0, 0], 'open: .app has the height and place, the chat stays at its end, the document is scrolled back')
    eq(got.get('panned'), [['420px', '0px', True], 0], 'a pan moves .app with it')
    eq(got.get('taller'), [['380px', '10px', True], 0], 'a taller keyboard too')
    eq(got.get('closed'), [off, 0], 'closed: back to normal, still at the end, whatever offsetTop Safari left')
    eq(got.get('up'), 300, 'a chat scrolled up stays where it was')
    eq((got.get('zoom'), got.get('noField')), (off, off), 'neither a pinch zoom nor a short window with no field in focus is a keyboard')
    eq(got.get('field'), [['420px', '260px', True], 228], 'a field in a view is scrolled above the keyboard')
    eq(got.get('next'), 328, 'and so is the next field, with the keyboard still open')


def test_talk_settings_f124(tmp: Path) -> None:
    """F124 (F123): Talk's settings and their defaults; hold to talk starts on pointerdown and sends on pointerup; auto
    listen listens again once a reply was read; a play button reads a reply and stops it; mic and speaker are 64px."""
    page = W.page_html().decode()
    for part in ('.mic,.spk{width:64px;height:64px', 'data-spk', 'data-talkmode="type"', 'data-talkmode="mic"', 'data-speak=',
                 'data-sheet="talk"', "'ar-talkset'", "'ar-talkmode'", 'data-ts="read"', 'data-ts="voice"', 'data-ts="mic"',
                 'data-ts="auto"', 'System voice', '.dock.typing .talkbox{opacity:1'):
        check(part in page, f'the Talk view has {part}')
    check('Spoken Content' not in page, 'no how-to for voices (dropped)')
    if not shutil.which('node'):
        print('  (no node here: the Talk settings script test is skipped)')
        return
    (tmp / 'driver.js').write_text(HOLD_DRIVER, encoding='utf-8')
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(W.PAGE)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, "node runs Talk's settings", r.stderr[-900:])
    got = json.loads(r.stdout or '{}')
    eq(got.get('defaults'), {'read': True, 'voice': '', 'mic': 'tap', 'auto': False},
       'defaults: replies read aloud, the system voice, tap, no auto listen')
    eq(got.get('parsed'), {'read': False, 'voice': 'Ava', 'mic': 'hold', 'auto': True}, 'kept per browser')
    eq(got.get('junk'), got.get('defaults'), 'a broken store is the defaults')
    eq(got.get('tapStarts'), 0, 'tap mode: pointerdown starts nothing')
    eq(got.get('holdStarts'), [1, 'listening'], 'hold mode: pointerdown starts listening')
    eq((got.get('before'), got.get('holdSent')), ([], [['what is running'], True]), 'and pointerup stops and sends')
    eq(got.get('voice'), ['Ava', 'en-GB'], 'the picked voice speaks')
    eq(got.get('auto'), [1, 'listening'], 'auto listen: listen() once the reply was read')
    eq(got.get('silent'), [1, '', 'Tap to talk'], 'one silent turn and it stops')
    eq(got.get('stopped'), [1, ''], 'a reply stopped by hand does not listen again')
    eq(got.get('off'), 1, 'off: no auto listen')
    eq(got.get('play'), ['b', 'One thing.', ''], "a reply's play button reads it, with read aloud off too")
    eq(got.get('playStop'), '', 'a second tap stops it')
    eq(got.get('playOver'), [0, None, 'b'], 'playing a reply stops the mic, and sends nothing')
    eq(got.get('micStops'), [0, ''], 'the mic then stops the reply first')
    eq(got.get('autoHeld'), 'auto', 'holding the mic while it already listens: letting go sends')


def test_status_view_f124(tmp: Path) -> None:
    """F124 (F120-F122): Status in place of Activity and Agents, its sections in the TUI's order, the state pill, the
    Run card and the More… sheet from the one list of controls, and the swipe that follows the finger."""
    page = W.page_html().decode()
    body = page.split('function statusHTML(){', 1)[1].split('\n}\n', 1)[0]
    at = [body.find(x) for x in ('needsSec()', '>Run<', '>Usage<', '>Landed lately<', '>Release<', '>Run log<')]
    check(all(i >= 0 for i in at) and at == sorted(at), 'Needs you, Run, Usage, Landed lately, Release, Run log', at)
    check('data-quick="since"' in body and 'data-quick="yesterday"' in body, 'the Since chips stay')
    for gone in ('agentsHTML', 'activityHTML', "['agents','Agents']", "['activity','Activity']"):
        check(gone not in page, f'no {gone}: one Status view')
    for part in ('data-sheet="run"', 'id="sheet"', 'role="dialog"', 'data-k="pill"', 'cardControls(S.snap)',
                 'controlGroups(S.snap)', "outbox(rq.name,rq.args,{ctl:"):
        check(part in page, f'the page has {part}')
    for ev in ('touchstart', 'touchmove', 'touchend', 'touchcancel'):
        check(f"document.addEventListener('{ev}'" in page, f'{ev} is handled')
    swipe = page.split('/* F124: a swipe right anywhere', 1)[1].split("addEventListener('pagehide'", 1)[0]
    check('preventDefault' not in swipe and swipe.count('{passive:true}') == 4, 'with passive listeners only')
    for part in ('input,textarea,select', 'sideways(el)', 'translateX(', 'swipeOpens('):
        check(part in swipe, f'the swipe has {part}')
    if not shutil.which('node'):
        print('  (no node here: the Status script test is skipped)')
        return
    cs = U.controls()
    up = {'up': True, 'controls': cs, 'run': {}, 'fixups': {'resume': [], 'unclaim': [{'id': 'F1', 'label': 'x'}] * 2, 'wip': []}}
    got = logic_js([['viewOf', 'agents'], ['viewOf', 'activity'], ['viewOf', 'plan'],
                    ['runPill', {'up': True, 'run': {'state': 'Caps forced'}}], ['runPill', {'up': False}],
                    ['cardControls', up], ['cardControls', {**up, 'run': {'paused': True, 'stopping': True}}],
                    ['cardControls', {'up': False}], ['controlGroups', up], ['controlGroups', {**up, 'fixups': {}}],
                    ['controlGroups', {**up, 'run': {'forced': True, 'stopping': True}}],
                    ['swipeTakes', 4, 3, False], ['swipeTakes', 40, 5, False], ['swipeTakes', -40, 5, False],
                    ['swipeTakes', -40, 5, True], ['swipeTakes', 40, 60, False],
                    ['swipeOpens', 100, 0, 280, False], ['swipeOpens', 180, 0, 280, False],
                    ['swipeOpens', 60, 0.8, 280, False], ['swipeOpens', -60, -0.8, 280, True],
                    ['swipeOpens', -60, 0, 280, True], ['atEnd', {'scrollHeight': 500, 'scrollTop': 400, 'clientHeight': 100}],
                    ['atEnd', {'scrollHeight': 500, 'scrollTop': 300, 'clientHeight': 100}]])
    eq(got[:3], ['status', 'status', 'plan'], 'the old views land on Status')
    eq(got[3:5], [{'text': 'Caps forced', 'cls': 'warn'}, {'text': 'Not up', 'cls': ''}], "the pill's words")
    eq(got[5], ['slot_remove', 'slot_add', 'pause', 'stop'], "the card's everyday buttons")
    eq(got[6], ['slot_remove', 'slot_add', 'go_on', 'stop_undo'], 'paused and stopping: what undoes it')
    eq(got[7], ['start'], 'no run: Start the run')
    keys = [(g['group'], [i['c']['key'] for i in g['items']]) for g in got[8]]
    eq(keys, [('Stop', ['stop', 'stop_now', 'suspend', 'shutdown']), ('Run', ['slots_set', 'force', 'upgrade', 'restart']),
              ('Fix up', ['unclaim'])], 'the sheet: Stop, Run and Fix up, what there is to fix only')
    eq(got[8][2]['items'][0]['label'], 'Release stale claims (2)', 'with its count')
    eq([g['group'] for g in got[9]], ['Stop', 'Run'], 'nothing to fix: no Fix up')
    eq([i['c']['key'] for i in got[10][0]['items']], ['stop_now', 'suspend', 'shutdown'], 'stopping already: no Stop')
    check('caps_on' in [i['c']['key'] for i in got[10][1]['items']], 'caps forced: Caps back on')
    eq(got[11:16], ['wait', 'drag', '', 'drag', ''], 'right opens, left closes, a mostly vertical move does neither')
    eq(got[16:21], [False, True, True, False, True], 'it settles by how far and how fast')
    eq(got[21:], [True, False], 'at the end, or not')


def test_chats_f128(tmp: Path) -> None:
    """F128, F129: the menu button's dot, a badge on a chat that needs a reply, quiet chats last and gray, and Rename."""
    fake_repo(tmp)
    page = W.page_html().decode()
    for part in ("count={home:needs,concepts:cn}", 'due=needs||cn;S.menuDot=!!due', "${S.menuDot?'<span class=\"bdot\"></span>':''}",
                 'title="needs your reply"', "quiet?' quiet':''", '<div class="qline">Quiet</div>', 'data-renform',
                 "outbox('rename_chat',{chat:n,title}", "SEEN_KEY='ar-seen'", 'data-rowmenu=', '.crow.quiet .thread{color:'):
        check(part in page, f'the page has {part}')
    ran, token = [], W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'renamed'))[1]]):
            code, out = post(f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}',
                             {'name': 'rename_chat', 'args': {'chat': 'c4', 'title': 'Login woes'}})
    finally:
        srv.stop()
    eq((code, out.get('ok'), ran), (200, True, [['control', '--rename', '4', 'Login woes']]), 'the rename action')
    eq(W.run_snapshot().get('chat_quiet'), 21600, "the snapshot says when a chat is quiet")
    if not shutil.which('node'):
        print('  (no node here: the Chats script test is skipped)')
        return
    now = 1_000_000
    row = lambda n, **k: {'name': n, 'title': n, 'last': 'claude', 'at': now - 50000, 'needs_reply': False, **k}  # noqa: E731
    rows = [row('c1'), row('c2'), row('c3', needs_reply=True), row('c4', renamed=True), row('c5', at=now - 60), row('c6'), row('c7'),
            row('c8', at=0), row('c9')]
    o = {'pins': ['c6'], 'quiet': 21600, 'now': now, 'seen': {f'c{i}': now for i in range(1, 9)}, 'open': None}
    got = logic_js([['chatGroups', rows, o], ['chatGroups', rows, {**o, 'quiet': 0}], ['chatGroups', rows, {**o, 'open': 'c2'}],
                    ['needsReply', row('c2'), now], ['needsReply', row('c2'), now - 60000], ['needsReply', row('c2', last='tool'), 0],
                    ['needsReply', row('c2', needs_reply=True), now],
                    ['chatName', {'name': 'c1', 'title': 'Base', 'renamed': True}], ['chatName', {'name': 'c1', 'title': 'Base'}]])
    names = lambda g: ([x['name'] for x in g['top']], [x['name'] for x in g['quiet']])  # noqa: E731
    eq(names(got[0]), (['c1', 'c3', 'c4', 'c5', 'c6', 'c8', 'c9'], ['c2', 'c7']),
       'quiet last: not c1, one that needs a reply (c3, c9 unread), a renamed, a fresh, a pinned or a new one')
    eq(names(got[1])[1], [], 'chat_quiet off: none')
    check('c2' in names(got[2])[0], 'the open chat stays up')
    eq(got[3:7], [False, True, False, True], 'a badge: unread since it spoke, or an open question; not while it works')
    eq(got[7:], ['Base', 'Project chat'], 'c1 shows the name the person gave it')


def test_needs_drop_chat_f110(tmp: Path) -> None:
    """F110, F143: a Needs you card's Drop asks in the page, then need_drop; its Chat sends need_chat and opens a new chat."""
    fake_repo(tmp)
    page, term = W.page_html().decode(), W.TERM.read_text(encoding='utf-8')
    for part in ("outbox('need_drop',{tid:n.id,confirm:true},{need:n.id", "S.sure='need:'+n.id", 'data-needdrop="${i}">Drop</button>',
                 "newChat('need_chat',{tid:n.id}", 'data-needchat="${i}"'):
        check(part in page, f'the run app has {part}')
    for part in ("data-form=\"needdrop\"", "act('need_drop',{tid:it.id,confirm:true}", "K('D','drop')"):
        check(part in term, f'the terminal-style page has {part}')
    repo = S.ROOT
    (repo / 'plan' / 'TODO.md').write_text(TODO + '- [~] **D3** Write the guide | files: d.md BLOCKED: DECIDE: which layout\n',
                                           encoding='utf-8')
    ran, token = [], W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    url = f'http://127.0.0.1:{srv.server_address[1]}/act?t={token}'
    try:
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'control 7 is starting'))[1]]):
            code, out = post(url, {'name': 'need_chat', 'args': {'tid': 'D3', 'wait': False}})
            check(out.get('ok') and out.get('name') == 'c7' and 'D3' in out.get('ask', ''), 'need_chat opens c7', out)
            check(ran and ran[0][:2] == ['control', '--new'] and 'hich layout' in ran[0][-2], 'its first message holds the ask', ran)
            ran.clear()
            eq(post(url, {'name': 'need_drop', 'args': {'tid': 'D3'}})[1].get('ok'), False, 'need_drop asks first')
            eq(post(url, {'name': 'need_drop', 'args': {'tid': 'D3', 'confirm': True}})[1].get('gone'), 'D3', 'then it is gone')
            eq(ran, [['plan', 'drop', 'D3', 'dropped from Needs you']], 'plan drop ID, from Needs you')
    finally:
        srv.stop()
    if not shutil.which('node'):
        return
    js = term.split('<script id="keys">', 1)[1].split('</script>', 1)[0]
    (tmp / 'keys.js').write_text(js, encoding='utf-8')
    (tmp / 'driver.js').write_text(TERM_DRIVER, encoding='utf-8')
    ev = {'key': 'D', 'ctrl': False, 'meta': False, 'shift': True, 'alt': False}
    ctx = {'panel': 4, 'focusMain': False, 'tab': '', 'tabs': [], 'typing': False, 'it': {}}
    r = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'keys.js')], capture_output=True, text=True, timeout=60,
                       input=json.dumps([['route', ctx, ev], ['footer', ctx, []],
                                         ['route', {**ctx, 'focusMain': True, 'tab': 'answer', 'tabs': ['answer']}, ev]]))
    got = json.loads(r.stdout or '[]')
    eq((got[0], got[2]), ([['act', 'drop']], [['act', 'drop']]), 'D on a Needs you item drops it, in the terminal-style page too')
    check(['D', 'drop'] in got[1]['here'], 'and its hint shows', got[1])
    ask = logic_js([['needChatAsk', {'id': 'R1', 'title': 'Phone', 'label': 'CONFIRM', 'ask': 'Does it work?'}]])[0]
    check('R1' in ask and 'Does it work?' in ask and '- Yes' in ask and '- No' in ask, 'the question and its answers show at once', ask)


def test_task_text_f85(tmp: Path) -> None:
    """F85: a queue row folds open to the task's whole text (plan ID)."""
    fake_repo(tmp)
    page = W.page_html().decode()
    for part in ('data-task="${esc(q.id)}" aria-expanded="${open}"', "fetch(tq('task/'", '<pre class="tasktext"', "planCard(q)"):
        check(part in page, f'the page has {part}')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        code, body = get(f'{base}/task/B2?t={token}')
        got = json.loads(body)
        check(code == 200 and got['ok'] and 'Fix the merge retry' in got['text'] and 'after: F1' in got['text'], 'its whole text', got)
        eq(json.loads(get(f'{base}/task/--x?t={token}')[1])['ok'], False, 'a task id only')
        eq(get(f'{base}/task/B2')[0], 403, 'and only with the token')
    finally:
        srv.stop()


def test_settings_f97(tmp: Path) -> None:
    """F97: the Settings view: every key with its value, source and default; a device value saved and reset in place in
    runner.local.toml, its comments kept; a project value queued as a C task; bad values refused."""
    repo = fake_repo(tmp)
    toml, local = repo / 'runner.toml', repo / 'runner.local.toml'
    toml.write_text('[run]\nslots = 4\nslotz = 1\n\n[rnu]\nslots = 9\n\n[git]\npush = false\n', encoding='utf-8')
    mine = '# my laptop\n[run]\nslots = 2   # it is small\nlinks = [\n  "data",  # one\n]  # big\n\n# the end\n[ui]\ntheme = "light"\n'
    local.write_text(mine, encoding='utf-8')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    ran = []

    def key(table, k):
        d = json.loads(get(f'{base}/settings?t={token}')[1])
        return next(x for t in d['tables'] if t['table'] == table for x in t['keys'] if x['key'] == k), d

    def act_(name, **args):
        return post(f'{base}/act?t={token}', {'name': name, 'args': args})[1]
    try:
        slots, d = key('run', 'slots')
        eq((slots['value'], slots['source'], slots['project'], slots['device'], slots['default'], slots['applies'], slots['type']),
           (2, 'device', 4, 2, 3, 'now', 'number'), 'slots: the device value is in force, over the project and the default')
        push, _ = key('git', 'push')
        eq((push['value'], push['source'], push['off']), (False, 'project', True), 'push = false, from the project')
        quiet, _ = key('ui', 'chat_quiet')
        eq((quiet['value'], quiet['source'], quiet['applies']), ('6h', 'default', 'next run'), 'chat_quiet: the default, 6h')
        check('grayed' in quiet['help'], 'with its help text', quiet)
        eq([(u['table'], u['key'], u['file']) for u in d['unknown']], [('run', 'slotz', 'runner.toml'), ('rnu', '', 'runner.toml')],
           'an unknown key is flagged, and an unknown table')
        check('did you mean' in d['unknown'][0]['why'], 'and says why', d['unknown'])
        every = {(t, k) for t, keys in CF.DEFAULTS.items() for k in keys}
        eq({(t['table'], k['key']) for t in d['tables'] for k in t['keys']}, every, 'every key `settings` lists')
        eq([f'[{t}] {k}' for t, k in sorted(every) if CF.setting_problem(t, k, CF.DEFAULTS[t][k])], [], 'every default is valid')
        with mock.patch.object(U, 'RUN', [lambda argv: (ran.append(argv), (0, 'added C9 it'))[1]]), \
                mock.patch.object(S, 'run_up', lambda: True):
            eq(act_('setting_device', table='run', key='slots', value=5)['ok'], True, 'a device save')
            eq(local.read_text(encoding='utf-8'), mine.replace('slots = 2 ', 'slots = 5 '), 'edits that value only, comments kept')
            eq(ran, [['slots', '5']], 'slots applies now, through the slots action')
            eq(act_('setting_device', table='run', key='links', value=['a b'])['ok'], True, 'a list over several lines')
            check('# one\nlinks = ["a b"]  # big' in local.read_text(encoding='utf-8'), 'becomes one line, its comments kept')
            eq(act_('setting_device', table='git', key='land_edited', value='wip')['ok'], True, 'a table not there yet')
            eq(CF.tomllib.loads(local.read_text(encoding='utf-8'))['git'], {'land_edited': 'wip'}, 'is added')
            eq(key('run', 'slots')[0]['value'], 5, 'the page reads the new value')
            for t, k in (('run', 'slots'), ('run', 'links'), ('git', 'land_edited')):
                eq(act_('setting_reset', table=t, key=k)['ok'], True, f'reset [{t}] {k}')
            left = local.read_text(encoding='utf-8')
            check(all(x not in left for x in ('slots', 'links', 'land_edited')) and '# my laptop' in left and '# the end' in left
                  and 'theme = "light"' in left, 'a reset takes the key out, nothing else', left)
            eq((key('run', 'slots')[0]['source'], ran[-1]), ('project', ['slots', '4']), 'and the project value is in force again')
            ran.clear()
            before = toml.read_text(encoding='utf-8')
            r = act_('setting_project', table='run', key='weekly_max', value=80)
            eq(r['ok'], True, 'a project save')
            check(ran[0][:3] == ['plan', 'add', 'C'] and 'set [run] weekly_max = 80' in ran[0][3]
                  and ran[0][4:] == ['--files', 'runner.toml'], 'queues a C task on runner.toml', ran)
            eq(toml.read_text(encoding='utf-8'), before, 'and never edits the main checkout')
            check('chat' in act_('setting_project', table='run', key='test', value='a | files: b')['out'], "the plan's marks are refused")
            ran.clear()
            now = local.read_text(encoding='utf-8')
            for t, k, v in (('run', 'slots', 'four'), ('run', 'slots', 0), ('run', 'slots', True), ('run', 'web', 'yes'),
                            ('run', 'web_port', 99999), ('ui', 'theme', 'pink'), ('run', 'links', 'x'), ('run', 'remote', 1),
                            ('ui', 'chat_quiet', 'soon'), ('ui', 'chat_quiet', True), ('models', 'code', 'nope:x:y'),
                            ('run', 'nokey', 1), ('nope', 'x', 1), ('run', 'weekly_max', -1)):
                for name in ('setting_device', 'setting_project'):
                    r = act_(name, table=t, key=k, value=v)
                    check(not r['ok'] and r['out'], f'{name} refuses [{t}] {k} = {v!r}', r)
            eq((local.read_text(encoding='utf-8'), ran), (now, []), 'a refused value changes nothing')
            local.write_text('run = { slots = 2 }\n', encoding='utf-8')
            check('by hand' in act_('setting_device', table='run', key='slots', value=3)['out'], 'an inline table: by hand')
            eq(local.read_text(encoding='utf-8'), 'run = { slots = 2 }\n', 'and it is left alone')
    finally:
        srv.stop()
    for text, v in (('[run]\nslots = 1\n[run.join]\na = "b"\n', 9), ('', 3), ('# only comments\n', 3),
                    ('[agent-runner.run]\nslots = 1\n', 2), ('[run]\nprompt_extra = """\n[run]\nslots = 7\n"""\nslots = 1\n', 2)):
        raw = CF.tomllib.loads(CF.toml_edit(text, 'run', 'slots', v))
        eq((raw.get('agent-runner') or raw)['run']['slots'], v, f'set in {text!r}')
    eq(CF.setting_problem('ui', 'chat_quiet', False), '', 'chat_quiet = false is off')
    check(CF.setting_problem('ui', 'chat_quiet', 5), 'a bare number is refused')
    page = W.page_html().decode()
    for part in ('settingsHTML', 'data-setsave="${side}"', 'data-setreset=', 'Project</b>', 'This device</b>', 'Restart the run',
                 'unknown</span>', "'setting_device':'setting_project'"):
        check(part in page, f'the Settings view has {part}')
    if not shutil.which('node'):
        return
    k = lambda **o: {'key': 'k', 'type': 'text', 'default': '', 'also': [], 'off': False, **o}  # noqa: E731
    got = logic_js([['settingValue', k(type='number', default=3), '4'], ['settingValue', k(type='number', default=3), 'x'],
                    ['settingValue', k(type='list', default=[]), 'a\n b \n'], ['settingValue', k(type='switch', default=True), 'false'],
                    ['settingValue', k(off=True, default='6h'), 'false'], ['settingValue', k(default='6h'), 'false'],
                    ['settingValue', k(type='choice', default='auto'), 'true'], ['settingValue', k(type='choice', default='auto'), 'auto'],
                    ['settingValue', k(type='table', default=False, also=['table']), '{ every = 10 }'],
                    ['settingValue', k(type='table', default=False), 'nope'],
                    ['settingValue', k(type='text', default='auto', also=['number']), '8'],
                    ['settingValue', k(default=False, also=['list']), 'bug, ui'], ['settingValue', k(default=False, also=['list']), 'true']])
    eq([g.get('v', 'err') for g in got], [4, 'err', ['a', 'b'], False, False, 'false', True, 'auto', {'every': 10}, 'err', 8,
                                          ['bug', 'ui'], True], "a field's words as a value of its type")


def test_style_f83(tmp: Path) -> None:
    """F83: the run app keeps to docs/STYLE.md where a machine can tell: colours, sizes, corners and durations are
    tokens, motion is transform and opacity only, and one rule turns it off under prefers-reduced-motion."""
    root = Path(__file__).resolve().parent.parent
    doc = (root / 'docs' / 'STYLE.md').read_text(encoding='utf-8')
    page = W.PAGE.read_text(encoding='utf-8')
    css = page.split('<style>', 1)[1].split('</style>', 1)[0]
    check('docs/STYLE.md' in css[:200], 'the top of the stylesheet names docs/STYLE.md')
    check('docs/STYLE.md' in (root / 'runner.toml').read_text(encoding='utf-8'), "and so does every session's prompt")
    bare = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    rules = re.sub(r'(?::root[^{]*)\{[^}]*\}', '', bare)
    for what, pat in (('raw colour', r'#[0-9a-fA-F]{3,8}\b|rgba?\('), ('font-size in px', r'font-size:\s*[\d.]'),
                      ('border-radius in px', r'border-radius:[^;}]*\d+px'),
                      ('raw duration', r'(?:transition|animation)[^;}]*[\s:]\.?\d+(?:\.\d+)?m?s\b')):
        eq(re.findall(pat, rules), [], f'no {what} outside the tokens')
    for kind in re.findall(r'transition:([^;}]+)', rules):
        for part in re.split(r',(?![^(]*\))', kind):
            check(part.split()[0] in ('transform', 'opacity', 'visibility', 'background-color', 'none', 'none!important'),
                  f'a transition on {part.split()[0]}', kind)
    for name, frames in re.findall(r'@keyframes (\w+)\{((?:[^{}]*\{[^}]*\})+)\}', bare):
        props = set(re.findall(r'[{;]\s*([a-z-]+):', frames))
        check(props <= {'opacity', 'transform'}, f'@keyframes {name} moves opacity and transform only', props)
    check(re.search(r'prefers-reduced-motion:reduce\)\{\*,\*::before,\*::after\{animation:none!important;transition:none!important', css)
          and css.count('prefers-reduced-motion') == 1, 'one rule turns every motion off')
    tokens = set(re.findall(r'(--[a-z0-9-]+):', re.search(r':root\{(.*?)\n\}', css, re.S)[1]))
    for t in re.findall(r'`(--[a-z0-9- ]+)`', doc):
        for one in t.split():
            check(one in tokens, f'docs/STYLE.md names {one}, a token', sorted(tokens))
    for name in re.findall(r'`(\w+)\(\)`', doc):
        check(re.search(rf'function {name}\(|const {name}=|\b{name}\(', page), f'docs/STYLE.md names {name}(), a helper in the page')
    for cls in re.findall(r'`\.([a-z]\w*)`', doc):
        check(f'.{cls}' in css, f'docs/STYLE.md names .{cls}, a class in the page')
    for dark in re.findall(r'\[data-theme="dark"\]\{(.*?)\}', css, re.S):
        light = set(re.findall(r'(--(?:bg|side|surface|bubble|fg|muted|faint|line2?|accent2?|onaccent|ok|warn|bad|onbad|scrim|shadow|lift)):', css.split('}', 1)[0]))
        eq(light - set(re.findall(r'(--[a-z0-9]+):', dark)), set(), 'every colour has its dark value')
    check('confirm(' not in page and 'alert(' not in page, 'no browser dialogs')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_release_row_f131),in_tmp(test_project_name_b153),in_tmp(test_chat_order_f133), in_tmp(test_delete_chats_f118), in_tmp(test_server), in_tmp(test_real_action), in_tmp(test_run_controls),
                           in_tmp(test_start), in_tmp(test_upload),
                           in_tmp(test_control_rows), in_tmp(test_feed_pane_concept), in_tmp(test_page),
                           in_tmp(test_logic), in_tmp(test_extras), in_tmp(test_diff), in_tmp(test_views),
                           in_tmp(test_new_chat), in_tmp(test_term_moves), in_tmp(test_page_copy_publish), in_tmp(test_parked),
                           in_tmp(test_esc_ctrl_c), in_tmp(test_concepts_view), in_tmp(test_follow_version_f90),
                           in_tmp(test_talk_f93), in_tmp(test_https_link_b130),
                           in_tmp(test_listen_heard_nothing_b132), in_tmp(test_talk_reply_heard_b133),
                           in_tmp(test_slash_menu_b119), in_tmp(test_composer_keys_b120),
                           in_tmp(test_interrupt_c1_b141), in_tmp(test_answer_button_b138), in_tmp(test_pick_f138),
                           in_tmp(test_outbox_f137), in_tmp(test_sent_b154), in_tmp(test_card_chat_b139), in_tmp(test_short_ask_b152),
                           in_tmp(test_chat_box_f115), in_tmp(test_home_switcher_f134),
                           in_tmp(test_scroll_f83), in_tmp(test_keyboard_b160), in_tmp(test_talk_settings_f124), in_tmp(test_status_view_f124),
                           in_tmp(test_chats_f128), in_tmp(test_needs_drop_chat_f110), in_tmp(test_task_text_f85),
                           in_tmp(test_settings_f97), in_tmp(test_style_f83)]))
