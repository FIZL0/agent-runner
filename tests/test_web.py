#!/usr/bin/env python3
"""F66: the run page on the web serves the page and the snapshot, runs an action's plan command, and refuses a
request without its token. F79: the page is the run app, and keeps uploaded attachments.

    python3 tests/test_web.py        (a temp repo, a server on a free local port, no agent; a few seconds)
"""
from __future__ import annotations

import json
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
        for part in (b'<title>agent-runner</title>', b'EventSource', b'Needs you', b'Working now', b'Up next'):
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
            'upgrade': ['key', 'u'], 'suspend': ['key', 'z'], 'shutdown': ['key', 'x']}  # C26
    cs = U.controls()
    if shutil.which('node'):
        reqs = logic_js([['controlReq', c, {'n': ' 4', 'tid': 'F1', 'sure': True}] for c in cs] +
                        [['controlReq', U.run_control_of('stop_now') | {'needs': '', 'confirm': U.STOP_NOW_ASK},
                          {'tid': 'F1'}]])
    else:
        print('  (no node here: the page requests are built in Python instead)')
        reqs = [{'name': 'run_control', 'args': {'key': c['key'], **({'n': '4'} if c['needs'] == 'n' else {}),
                                                  **({'tid': 'F1'} if c['needs'] == 'id' else {}),
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
                    eq((out.get('ok'), sent, ran), (True, ['do F1 here'], []), 'Take back asks c1 "do F1 here"')
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
        sent = []
        with mock.patch.object(U, 'SEND', [lambda t: (sent.append(t), {'ok': True, 'out': 'sent to c1'})[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'quick_ask', 'args': {'key': 'needs'}})
        eq(sent, ['what needs me?'], 'a quick ask through /act reaches c1')
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
        for part in (b"const chats=()=>S.snap.sessions.filter(s=>/^c\\d+$/.test(s.name))",
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
    """F79: the run app as its design has it: the sidebar (New chat, Home, Agents, Activity, Plan, Chats, Agents
    working, the machine and usage), Home's parts, threads, the message box, the Plan, light and dark, no
    scrollbars, the container layout, its own 'ar' mark, and no direct edit of tasks."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        page = get(f'http://127.0.0.1:{srv.server_address[1]}/?t={token}')[1].decode()
    finally:
        srv.stop()
    for part in ('New chat', "['home','Home'],['agents','Agents'],['activity','Activity'],['plan','Plan'],['concepts','Concepts']",
                 '<div class="shead row"><span>Chats</span>', '<div class="shead">Agents working</div>', 'class="livedot"',
                 'S.snap.machine', 'usage ${esc(use)}',  # the sidebar
                 'side.open', 'class="scrim"', 'data-menu',  # a drawer on a phone
                 'greeting()', 'How can I help with the run?', 'data-quick="since">', 'Since my last look',
                 'data-quick="needs">', 'What needs me', 'data-about="new">', 'Add a task',  # Home
                 '>Needs you<', 'data-ans=', 'data-later=', 'data-about="need:', '>Working now<', '>Up next<',
                 'data-about="plan:', 'Release when they land', 'Release now',
                 "act('answer'", "act('shelve'", "act('release'", "act('quick_ask'", "act('chat_to'",
                 "act('new_control'", "act('interrupt'",
                 '.a{display:grid;gap:8px;font:400 16.5px/1.6 var(--serif)', '.u{justify-self:end',  # threads
                 'Ran ${m.steps.length} step', 'Working on it…', "tq('feed/'",
                 'Goes straight to this agent', "tq('upload?name='", 'type="file" multiple', 'About: <b>',  # the box
                 "e.key==='Enter'&&!e.shiftKey", 'DRAFT_KEY', 'store.set(DRAFT_KEY(boxKey())',
                 'data-pick=', 'data-about="concept:', 'View ${I.ext}', "tq('concept/'",  # the Concepts view
                 '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])', ':root[data-theme="dark"]',
                 '*{box-sizing:border-box;scrollbar-width:none}', '*::-webkit-scrollbar{display:none}',
                 'container-type:inline-size', '@container (min-width:760px)', '<div class="logo">ar</div>'):
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
    check("act('new_control',{})" in page, 'data-new calls new_control')
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
    with mock.patch.object(PC, 'remote_on', lambda: True), mock.patch.object(PC, 'control_ok', lambda: True), \
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
        with mock.patch.object(PC, 'page_copy_argv', lambda path, url: ['/nonexistent/agent-b122']):
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
                 "act('unpark',{tid:id})", "q.state!=='running'&&q.state!=='parked'"):
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
    """B116: on the run app Esc never interrupts (it leaves the box, then goes back); Ctrl+C interrupts the open
    chat while it works (not over selected text), and a small Stop button sits by the working mark."""
    page = W.page_html().decode()
    start = page.index("document.addEventListener('keydown'")
    handler = page[start:page.index('\n});', start)]
    lines = handler.splitlines()
    esc_lines = [ln for ln in lines if "e.key==='Escape'" in ln]
    check(len(esc_lines) >= 2, 'the keydown handler has its Esc branches', esc_lines)
    for ln in esc_lines:
        check('interrupt' not in ln, 'an Esc branch sends no interrupt', ln)
    check(any("e.key==='Escape'" in ln and 'blur()' in ln for ln in lines), 'Esc in the box leaves it')
    check(any("e.key==='Escape'&&S.thread&&" in ln and 'S.thread=null' in ln for ln in lines), 'Esc out of the box goes back')
    ctrl = [ln for ln in lines if 'e.ctrlKey' in ln]
    check(len(ctrl) == 1 and "act('interrupt',{session:S.thread})" in ctrl[0] and 'busy(S.thread)' in ctrl[0]
          and '!selectedText(' in ctrl[0], 'Ctrl+C interrupts the working chat, not over selected text', ctrl)
    check('Working on it… · Ctrl+C interrupts<button type="button" class="btn mini" data-stop="${esc(n)}">Stop</button>'
          in page, 'the working mark says Ctrl+C interrupts and has a Stop button')
    check("if(x=q('[data-stop]')){const n=x.dataset.stop||S.thread;if(n)act('interrupt',{session:n});return}" in page,
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
            eq(calls, [['control', '--new', '--ask', ask]], 'with the spoken-reply instruction as its first message')
            with mock.patch.object(U, 'chat_to', lambda text, to: (typed.append((to, text)),
                                                                   {'ok': True, 'code': 0, 'out': '', 'argv': []})[1]):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'and the merge?', 'to': 'c7'}})
            eq((out.get('ok'), out.get('session')), (True, 'c7'), 'a later send goes to the live Talk session')
            eq(typed, [('c7', CT.TALK_TAG + 'and the merge?')], 'with the spoken-reply reminder')
            with mock.patch.object(U, 'chat_to', lambda text, to: {'ok': False, 'code': 1, 'out': 'gone', 'argv': []}):
                code, out = post(url, {'name': 'talk', 'args': {'text': 'hello', 'to': 'c7'}})
            eq((out.get('ok'), calls[-1]), (True, ['control', '--new', '--ask', CT.talk_ask('hello')]),
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


LISTEN_DRIVER = r"""
const page = require('fs').readFileSync(process.argv[2], 'utf8');
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
const esc = s => s, I = {stop: '', talk: ''}, box = () => '';
eval(logic + grab('function unlockSpeech(') + grab('function talkDock(') + grab('function listen(') + `
  listen();
  const before = rec.started;
  rec.onerror({error: 'no-speech'}); rec.onend();
  const line = talkDock().match(/class="talkline"[^>]*>([^<]*)</)[1];
  listen();
  const cleared = talkDock().match(/class="talkline"[^>]*>([^<]*)</)[1];
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


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_delete_chats_f118), in_tmp(test_server), in_tmp(test_real_action), in_tmp(test_run_controls),
                           in_tmp(test_start), in_tmp(test_upload),
                           in_tmp(test_control_rows), in_tmp(test_feed_pane_concept), in_tmp(test_page),
                           in_tmp(test_logic), in_tmp(test_extras), in_tmp(test_diff), in_tmp(test_views),
                           in_tmp(test_new_chat), in_tmp(test_term_moves), in_tmp(test_page_copy_publish), in_tmp(test_parked),
                           in_tmp(test_esc_ctrl_c), in_tmp(test_concepts_view), in_tmp(test_follow_version_f90),
                           in_tmp(test_talk_f93), in_tmp(test_https_link_b130),
                           in_tmp(test_listen_heard_nothing_b132)]))
