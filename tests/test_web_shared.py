"""The run page, shared area (agent_runner/page/*-shared.*): split from test_web.py (C41b), tests unchanged.

    python3 tests/test_web_shared.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report
from _trust import asked, trusted_checks

from agent_runner import config as CF  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import ui_model as U  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import TODO, fake_repo, get, post, LOGIC_DRIVER, logic_js, in_tmp  # noqa: E402
from test_web_live import SCROLL_DRIVER  # noqa: E402


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

        with mock.patch.object(W.shutil, 'which', return_value=None), mock.patch('agent_runner.plat.WINDOWS', False), \
                mock.patch.object(W, 'session_live', return_value=True):
            code, body = get(f'{base}/terminal/s1?t={token}')
        r = json.loads(body)
        check(not r['ok'] and r['out'].startswith('ttyd is not installed, so a chat cannot show') and 'Until then, messages still reach s1.' in r['out'],
              'without ttyd the terminal tab says how to install it, and that the chat works meanwhile', r)
        check(r['mode'] == 'install' and 'capture' not in r and 'every' not in r,
              "C24: and no 'builtin' mode: the built-in view is gone", r)
        eq(get(f'{base}/pane/s1?t={token}')[0], 404, 'C24: the capture route is gone')
        with mock.patch.object(U, 'act', side_effect=AssertionError('keys reached ui_model')):
            code, out = post(f'{base}/act?t={token}', {'name': 'keys', 'args': {'session': 's1', 'text': 'x'}})
        check(code == 404 and not out['ok'], 'C24: the web no longer types keys into a pane', out)
        with mock.patch.object(W.shutil, 'which', return_value='ttyd.exe'), mock.patch('agent_runner.plat.WINDOWS', True), \
                mock.patch.object(W, 'socket_of', return_value='x'), mock.patch('agent_runner.attach.reachable', return_value=True), \
                mock.patch.object(W.Terminals, 'ttyd', return_value={'ok': True, 'port': 1}):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        eq((r['ok'], r['port'], r['path']), (True, srv.server_address[1], f'/t/{token}/s1/'),
           "F114: Windows serves the session too, on the page's own address")
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.plat.WINDOWS', False), mock.patch.object(W, 'socket_of', return_value=''):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        check(not r['ok'] and 'is not up' in r['out'], 'a slot with no terminal says so', r)
        argv = W.Terminals(token, 8770, '0.0.0.0').argv('s2', '/x/slot2.sock', 8771)
        eq(argv[-2:], ['attach', 's2'], "C26: ttyd serves `attach s2`, the session's own socket")
    finally:
        srv.stop()


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
    for part in ('New chat', "['home','Home'],['status','Status'],['plan','Plan'],['concepts','Concepts'],['tools','Tools'],['settings','Settings']",
                 'Style rules: docs/STYLE.md',
                 '<div class="shead row"><span>Chats</span>', '<div class="shead">Agents working</div>', 'class="livedot"',
                 'S.snap.machine', 'usage ${esc(use)}',  # the sidebar
                 'side.open', 'class="scrim"', 'data-menu',  # a drawer on a phone
                 'greeting()', 'How can I help with the run?', 'data-quick="since">', 'Since my last look',
                 'data-quick="needs">', 'What needs me', 'data-about="new">', 'Add a task',  # Home
                 '>Needs you<', 'ansBtns(n)', 'restBtns(n)', '>Working now<', '>Up next<',
                 'data-about="plan:', 'S.snap.release_acts',
                 "outbox('answer'", "newChat('quick_ask'", "outbox('chat_to'",
                 "newChat('new_control'", "act('interrupt'",  # F137: through the outbox
                 '.a{display:grid;gap:8px;font:400 16.5px/1.6 var(--serif)', '.u{justify-self:end',  # Talk's words
                 'id="feed"', 'feedHTML(n)', "tq('feed/'",
                 'Goes straight to this agent', "tq('upload?name='", 'type="file" multiple',  # the box
                 "boxEnter(e,TOUCH())==='send'", 'DRAFT_KEY', 'store.set(DRAFT_KEY(boxKey())',
                 'data-pick=', 'data-about="concept:', 'View ${I.ext}', "tq('concept/'",  # the Concepts view
                 '@media (prefers-color-scheme:dark){:root:not([data-theme="light"])', ':root[data-theme="dark"]',
                 '*{box-sizing:border-box;scrollbar-width:none}', '*::-webkit-scrollbar{display:none}',
                 'container-type:inline-size', '@container (min-width:760px)', '<div class="logo">${esc(PN().charAt(0)'):
        check(part in page, f'the page has {part}')
    for gone in ('Anthropic', 'Claude', 'plan_change', 'direct edit', 'JetBrains Mono', '/*THEMES*/', 'threadMsgs', 'data-steps', 'data-jump', 'stepbox', 'Older messages'):
        check(gone not in page.replace('your own Claude usage', ''), f'the page has no {gone}')  # F194b: whose usage a run spends


def test_logic(tmp: Path) -> None:
    """F79: the page's pure parts, driven in node: a feed as Talk's words, the working mark, the answer buttons, the queue in plain words, and what the box sends."""
    if not shutil.which('node'):
        print('  (no node here: the page script test is skipped)')
        return
    feed = [{'kind': 'you', 'text': 'fix it'}, {'kind': 'tool', 'text': 'Read(a.py)'},
            {'kind': 'out', 'text': '12 lines'}, {'kind': 'tool', 'text': 'Edit(a.py)'},
            {'kind': 'say', 'text': 'Fixed.'}, {'kind': 'you', 'text': 'thanks'}, {'kind': 'tool', 'text': 'Bash(ls)'}]
    sessions = [{'name': 's2', 'task': 'F1', 'minutes': 12}]
    got = logic_js([
        ['talkMsgs', feed],
        ['working', feed], ['working', feed[:5]], ['working', feed + [{'kind': 'out', 'text': 'interrupted'}]],
        ['working', []],
        ['answerOpts', U.needs_rows([('CONFIRM', 'F1', '', 'Works?', '', 'T', False)], dt.datetime.now())[0][0]],
        ['answerOpts', {'label': 'DECIDE', 'answers': U.need_answers({'label': 'DECIDE', 'options': ['ship it', 'wait']})}],
        ['answerOpts', U.needs_rows([('BLOCKED', 'F2', '', 'Log in', '', 'T', False)], dt.datetime.now())[0][0]],
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
    eq([(m['w'], m['text']) for m in msgs], [('u', 'fix it'), ('a', 'Fixed.'), ('u', 'thanks')], "F114: Talk's words: yours and the replies, no tool steps")
    eq(got[1:5], [True, False, False, False], 'working while its last entry is a step, not after a reply or an interrupt')
    eq(got[5], ['Yes', 'No'], 'a CONFIRM answers Yes or No')
    eq(got[6], ['Ship it', 'Wait'], "a DECIDE's options are its buttons")
    eq(got[7], ['Done'], 'C33: a BLOCKED answers Done, as the terminal UI does')
    eq(got[8:12], ['s2 is on it · 12 min', 'Waits for F1 Board page', 'Waits for you',
                   'Ready to start when a slot is free'], 'the queue in plain words')
    eq(got[12], 'hello', 'plain words go as typed')
    eq(got[13], 'Add a task: dark mode toggle', 'Add a task says so')
    eq(got[14], 'About F76 (Terminal app): make it first\n\nAttached: /r/.runner/uploads/a.png',
       'the About line names the task; an attachment goes as its path')
    eq(got[15], 'Attached: /r/.runner/uploads/a.png, /r/.runner/uploads/b.txt', 'attachments alone')
    eq(got[16], 'About R6 (Windows status), which needs me: what do I check?',
       "a Needs you item's Chat talks about it, not as its answer")
    eq(got[17], 'session 40%, week 12%', 'the usage line for the sidebar')
    eq(got[18:21], ['Chat 1', 'Site deploy', 'Chat 7'], 'chats by their titles, c1 as any other')
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


def test_views(tmp: Path) -> None:
    """C29: the terminal-style page is gone: /term is 404, web_term.html is deleted, the run app has no view switch,
    and an old runner.toml with [ui] web set is ignored."""
    repo = fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        eq(get(f'{base}/term?t={token}')[0], 404, '/term is gone')
        app = get(f'{base}/?t={token}')[1].decode()
    finally:
        srv.stop()
    check(not (Path(W.__file__).parent / 'web_term.html').exists(), 'web_term.html is deleted')
    for part in ('viewsw', 'WEB_VIEW', 'VIEW_KEY', "location.replace('term'", 'Terminal view</a>'):
        check(part not in app, f'the run app has no {part}')
    (repo / 'runner.toml').write_text('[ui]\nweb = "terminal"\n', encoding='utf-8')
    CF.Config(repo)  # an old [ui] web is ignored, not an error


def test_page_copy_options(tmp: Path) -> None:
    """B203: the run page copy shows a DECIDE's options after its ask, and no answers for any other item."""
    from agent_runner import page_copy as PC, plan as P
    from agent_runner.status import waiting_ok
    fake_repo(tmp)
    P.block('F1', 'DECIDE: Which look? [Small / A<b (recommended)]', todo=S.C.todo)
    P.block('B2', 'BLOCKED: log in', todo=S.C.todo)
    needs = U.needs_rows(waiting_ok(), dt.datetime.now())[0]
    copy = PC.page_copy_html({'needs': needs})
    check('Which look? - reply with your answer</span><span>A&lt;b (recommended) / Small</span><span class="d">' in copy,
          "a DECIDE's options are drawn, the recommended first, escaped", copy)
    check('Log in - reply' in copy and 'Done' not in copy, "a blocked item's Done is not an option", copy)


def test_page_copy_publish(tmp: Path) -> None:
    """B122: a run change publishes the run page copy through a one-shot `claude -p` with only Artifact and Read,
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
        eq(argv[argv.index('--tools') + 1], 'Artifact,Read', 'with only Artifact, and the Read it needs')
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
        eq((PC.PAGE_COPY_OFF[0], PC.PAGE_COPY_FAILS[0]), ('', 0), 'no agent here (F406e): the local copy is the answer, no failure')
        check('Z1' in PC.page_copy_file().read_text(encoding='utf-8'), 'and it is written')
    eq(keys, [], 'no run change sends keys to any pane or FIFO')
    check(not hasattr(PC, 'c1_send'), 'the copy has no way to type into c1')
    src = Path(PC.__file__).read_text(encoding='utf-8')
    for name in ('send_fifo', 'control_type', 'control_live', 'send_keys', 'MUX'):
        check(name not in src, f'page_copy.py never calls {name}')
    PC.PAGE_COPY_OFF[0] = ''
    # B180: a sign-in warning before the answer, on stdout or stderr, and why a publish failed
    warn = ('Warning: this sign-in ends between 2026-11-27 and 2026-11-30 (in 4 days at the earliest). Renewing it '
            'does not move those dates. Run claude auth login before then, or use claude setup-token for unattended '
            'jobs.\n')
    url, why = 'https://claude.ai/artifact/b180', 'x' * 500 + ' the Read deny rule forbids reading files.\n'

    def publish(out: str, err: str) -> tuple[str, list]:
        said: list = []
        with mock.patch.object(PC, 'C', S.C), mock.patch.object(PC, 'log', said.append), \
                mock.patch.object(PC.sp, 'run', lambda argv, **kw: subprocess.CompletedProcess(argv, 0, out, err)):
            return PC.page_copy_publish(tmp / 'p.html', ''), said

    eq(publish(warn + url + '\n', '')[0], url, 'the warning first on stdout: still published')
    eq(publish(url + '\n', warn)[0], url, 'the warning on stderr: still published')
    for out, err in ((why, warn), (warn + why, '')):
        got, said = publish(out, err)
        eq(got, '', 'no URL in the answer: not published')
        check(len(said) == 1 and said[0].endswith('the Read deny rule forbids reading files.'),
              'the log has the end of the answer, not just the warning', said)


MOTION_DRIVER = r"""
const page = require('fs').readFileSync(0, 'utf8').replace(/\r\n/g, '\n');
const logic = page.split('<script id="logic">')[1].split('</script>')[0];
const S = {live: true, f: {}, drawer: false, sheet: '', thread: null};
let reduced = false, now = 1000, ran = [];
Date.now = () => now;
const document = {hidden: false, activeElement: null, documentElement: {classList: {cls: new Set(), add(...c) { c.forEach(x => this.cls.add(x)) }, remove(...c) { c.forEach(x => this.cls.delete(x)) }}}, querySelector: () => null, addEventListener() {}, createElement: () => new El('')};
const matchMedia = () => ({matches: reduced}), getComputedStyle = () => ({getPropertyValue: k => k.startsWith('--dur') ? '450ms' : 'ease'});
// a laid-out thing: key k, its class, top y; kids nest
class El {
  constructor(k, y = 0, cls = '', o = {}) { this.dataset = {}; if (k) this.dataset.k = k; Object.assign(this.dataset, o); this.y = y; this.kids = []; this.style = {}; this.cls = new Set(cls.split(' ').filter(Boolean));
    this.attributes = [{name: 'data-k'}, {name: 'id'}, {name: 'class'}]; this.gone = []; this.childNodes = []; this.scrollTop = 0; this.isConnected = true; this.attrs = {};
    this.classList = {add: c => this.cls.add(c), remove: (...c) => c.forEach(x => this.cls.delete(x))} }
  add(...es) { for (const e of es) { e.parentElement = this; this.kids.push(e) } return this }
  getBoundingClientRect() { const h = this.h || 40; return {left: 0, top: this.y, right: 300, bottom: this.y + h, width: 300, height: h} }
  all() { return this.kids.flatMap(k => [k, ...k.all()]) }
  querySelectorAll(s) { return s === '*' ? this.all() : this.all().filter(e => e.dataset.k) }
  contains(e) { return this === e || this.all().includes(e) }
  matches(s) { return s.split(',').some(x => x[0] === '.' && this.cls.has(x.slice(1))) }
  closest(s) { for (let e = this; e; e = e.parentElement) if (s.startsWith('[data-k]') ? e.dataset.k : e.matches(s)) return e; return null }
  cloneNode() { const c = new El('', this.y, [...this.cls].join(' ')); c.dead = this.attributes.map(a => a.name); c.of = this.dataset.k; return c }
  removeAttribute(n) { this.dead = this.dead.filter(x => x !== n) } setAttribute(n, v) { this.attrs[n] = v }
  appendChild(e) { e.isConnected = true; this.gone.push(e) } append(...xs) { this.childNodes.push(...xs) } remove() { this.isConnected = false }
  animate(kf, o) { const a = {el: this, kf, o, cancel() { this.cancelled = true }}; ran.push(a); return a }
}
eval(logic.replace(/if\(typeof module[^\n]*/, '') + page.slice(page.indexOf('/* F147: motion (docs/STYLE.md'), page.indexOf('function viewIn(el)')) + `
const box = (...es) => { const b = new El('', 0); b.h = 600; return b.add(...es) };
const cards = (...ks) => ks.map((k, i) => new El(k, i * 50, 'card'));
// a redraw: what was, what is; the moves, and what left
function redraw(was, is) { ran = []; const spot = glideSpot(was), had = keysIn(was); is._gone = was._gone; enter(is, had); glide(is, is, spot); leaving(is);
  return {moved: ran.filter(a => a.el.dataset.k).map(a => [a.el.dataset.k, a.kf[0].transform]), left: is.gone.map(g => [g.of, g.dead, g.attrs['aria-hidden'], g.inert]), came: is.all().filter(e => e.cls.has('enter')).map(e => e.dataset.k)} }
const out = {};
out.reorder = redraw(box(...cards('a', 'b', 'c')), box(...cards('c', 'a', 'b')));
const after = box(...cards('a', 'c'));
out.leave = redraw(box(...cards('a', 'b', 'c')), after);
after.gone.forEach(g => { g.isConnected = false }); const again = box(...cards('a', 'c')); redraw(after, again); out.goesOn = again.gone.map(g => g.of);
ran = []; now += 1000;
const came = box(...cards('n', 'a')); out.enter = redraw(box(...cards('a')), came);
now += 100; const half = box(...cards('n', 'a')); redraw(came, half); out.half = [half.kids[0].cls.has('enter'), half.kids[0].style.animationDelay];
now += 1000; const done = box(...cards('n', 'a')); redraw(half, done); out.done = done.kids[0].cls.has('enter');
const nest = y => box(new El('run', y, 'card').add(new El('slot', y + 10, 'srow')));
out.nested = redraw(nest(0), nest(80)).moved;
const part = (a, b) => box(new El('run', 0, 'card').add(...a, ...b));
const both = redraw(part([new El('s1', 10, 'srow')], []), part([], [])); out.row = both.left.map(x => x[0]);
out.whole = redraw(box(...cards(...'abcdefghij')), box(...cards('z'))).left.length;
out.offscreen = redraw(box(new El('far', 900, 'card')), box(new El('far', 950, 'card'))).moved;
MO.fly.clear(); const el = new El('x'); glideTo(el, 0, 30); const first = ran[ran.length - 1]; glideTo(el, 0, -5); out.again = [first.cancelled, MO.fly.get(el) !== first];
const words = (v, roll) => new El('n', 0, '', roll ? {v, roll: ''} : {v});
ran = []; const r1 = box(words('3', true)); enter(r1, keysIn(box(words('2', true)))); const r2 = box(words('1', true)); enter(r2, keysIn(box(words('2', true))));
out.roll = ran.map(a => a.kf.map(k => k.transform)).filter((x, i) => i % 2 === 0).map(x => x[0]);
S.live = false; out.first = redraw(box(...cards('a')), box(...cards('b', 'a'))); S.live = true;
reduced = true; ran = [];
out.calm = redraw(box(...cards('a', 'b')), box(...cards('b', 'c'))); enter(box(words('3', true)), keysIn(box(words('2', true)))); out.calmRan = ran.length;
let went = 0; document.startViewTransition = () => { throw new Error('started') }; var kbH = 0; viewGo(() => { went++ }, 'c2'); out.calmView = [went, document.documentElement.classList.cls.size];
out.spring = [springFrames(-280, 0, 0), springFrames(0, 600, 2), springFrames(0, 600, 0)].map(f => [f[0], f[f.length - 1], f.length <= 61, f[3]]);
console.log(JSON.stringify(out));`);
"""


def test_motion_f147(tmp: Path) -> None:
    """F147: what comes in rises, what leaves collapses and the rest glides from where it was; a redraw half way goes on;
    nothing moves on the first load or under reduced motion."""
    if not shutil.which('node'):
        print('  (no node here: the motion script test is skipped)')
        return
    p = subprocess.run(['node', '-e', MOTION_DRIVER], input=W.page_html().decode(), capture_output=True, text=True, encoding='utf-8', timeout=30)
    check(p.returncode == 0, 'the motion script runs', p.stderr[-1500:])
    if p.returncode:
        return
    o = json.loads(p.stdout)
    eq(o['reorder'], {'moved': [['c', 'translate(0px,100px)'], ['a', 'translate(0px,-50px)'], ['b', 'translate(0px,-50px)']], 'left': [], 'came': []},
       'a reorder: each glides from where it was, transform only')
    eq(o['leave']['moved'], [['c', 'translate(0px,50px)']], 'a card that leaves: the rest closes up')
    eq(o['leave']['left'], [['b', ['class'], 'true', True]], 'its copy has no data or id, and is out of reach')
    eq(o['goesOn'], ['b'], 'and it goes on over the next redraw')
    eq((o['enter']['came'], o['enter']['moved']), (['n'], [['a', 'translate(0px,-50px)']]), 'a new card rises in, the one it pushed glides')
    eq((o['half'], o['done']), ([True, '-100ms'], False), 'a redraw half way goes on from there; later it is at rest')
    eq(o['nested'], [['run', 'translate(0px,-80px)']], 'a row moves with its card, not twice')
    eq(o['row'], ['s1'], 'a row that leaves its card')
    eq((o['whole'], o['offscreen']), (0, []), 'a whole other list, or one out of sight, does not move')
    eq(o['again'], [True, True], 'a new glide takes over from the one under way')
    eq(o['roll'], ['translateY(100%)', 'translateY(-100%)'], 'a count rolls up when it grew, down when it fell')
    eq(o['first'], {'moved': [], 'left': [], 'came': []}, 'nothing moves on the first load')
    eq((o['calm']['moved'], o['calm']['left'], o['calmRan']), ([], [], 0), 'reduced motion: no glide, no copy, no roll')
    eq(o['calmView'], [1, 0], 'and a chat opens at once, with no View Transition')
    (a, b, c) = o['spring']
    eq((a[:3], b[:3]), ([-280, 0, True], [0, 600, True]), 'a panel springs from where it was let go to its place')
    check(b[3] > c[3], "with the finger's speed", o['spring'])


JUMP_DRIVER = SCROLL_DRIVER.split("eval(logic")[0] + r"""
const slice = (a, z) => page.slice(page.indexOf(a), page.indexOf(z, page.indexOf(a)));
const hears = {}; document.addEventListener = (t, f) => { hears[t] = f };
const TK = {state: '', gen: 0, starting: []}, TM_KEY = 't', talkName = () => '', talkKept = () => '', talkStarts = () => {}, unlockSpeech = () => {}, loadVoices = () => {}, kbFocus = () => {};
const act = () => new Promise(() => {}), SL = {cmds: [{name: 'a'}, {name: 'ab'}, {name: 'abc'}], items: [], i: 0, at: Date.now(), of: ''};
let P = 0, made = [];
Box.prototype.animate = function (kf, o) { const a = {el: this, kf, o, playState: 'running', effect: {getComputedTiming: () => ({progress: P})}, cancel() { this.cancelled = true }}; made.push(a); return a };
Box.prototype.isConnected = true; Box.prototype.contains = function (e) { return e === this };
const frame = p => { P = p; if (p === 1) made.forEach(a => { a.playState = 'finished' }); const l = frames; frames = []; l.forEach(f => f()) };
const js = {reveal: grab('function kbReveal('), slash: grab('function slashShow('), hand: line("for(const t of ['pointerdown','touchstart','wheel'])"), mode: line('function talkMode('), send: grab('async function talkSend(')};
""" + 'eval(logic' + SCROLL_DRIVER.split('eval(logic')[1].split('(async () => {')[0].rstrip().removesuffix('`') + r"""js.reveal + js.slash.replace('function slashShow', 'function slashDraw') + js.hand + js.mode + js.send + `
(async () => {
  const b = $('body'), out = {};
  S.view = 'talk'; render(true); made = [];
  const up = () => { scrollStop(b); CHAT = 'm1:400 m2:400'; b._h = ''; render(true); b.scrollTop = 100; b.on.scroll(); frames = []; made = []; P = 0 };
  const trail = () => { const t = [b.scrollTop]; frame(.5); t.push(b.scrollTop); frame(1); t.push(b.scrollTop); return t };
  const talk = {send: () => { talkSend('Hi') }, mode: () => talkMode('type')};
  for (const k in talk) {
    up(); out.unpinned = S.pin; talk[k](); out[k] = [trail(), S.pin, made.map(a => [a.kf.length, a.o.duration]), MO.scroll.size];
    reduced = true; up(); talk[k](); out[k + 'Calm'] = [b.scrollTop, made.length]; reduced = false;
    document.hidden = true; up(); talk[k](); out[k + 'Hidden'] = [b.scrollTop, made.length]; document.hidden = false;
  }
  // a redraw, new words and a scroll event half way: the glide goes on, to the new end
  up(); talkSend('Hi'); frame(.5); CHAT += ' m3:100'; b._h = ''; render(true); b.on.scroll(); const half = b.scrollTop; frame(.5); const on1 = b.scrollTop; frame(1); out.redrawn = [half, on1, b.scrollTop, S.pin];
  // the person's hand takes it over; another view ends it
  up(); talkSend('Hi'); frame(.5); hears.wheel({target: b}); frame(1); out.hand = [b.scrollTop, S.pin, MO.scroll.size];
  up(); talkSend('Hi'); frame(.5); S.view = 'plan'; VIEW = 'a:300'; render(true); frame(1); out.moved = [b.scrollTop, MO.scroll.size]; S.view = 'talk'; render(true);
  // a field: a press glides to it, typing is at once, unless that glide is under way
  const field = {closest: () => b, getBoundingClientRect: () => ({top: 500 - b.scrollTop, bottom: 540 - b.scrollTop})};
  up(); kbReveal(field, true); out.reveal = trail();
  up(); kbReveal(field); out.typed = [b.scrollTop, made.length];
  up(); reduced = true; kbReveal(field, true); out.revealCalm = [b.scrollTop, made.length]; reduced = false;
  up(); kbReveal(field, true); kbReveal(field); out.both = [...trail(), made.length];
  up(); kbReveal(field, true); frame(.5); b.scrollTop += 35; frame(.5); out.pushed = [b.scrollTop]; frame(1); out.pushed.push(b.scrollTop);
  // the slash menu: an arrow glides, typing is at once
  const menu = new Box(50); menu.innerHTML = 'x:40 y:40 z:40'; let into = 0;
  const row = {scrollIntoView() { into++ }, getBoundingClientRect: () => ({top: 80 - menu.scrollTop, bottom: 120 - menu.scrollTop})};
  Object.defineProperty(menu, 'innerHTML', {set() {}}); menu.querySelector = () => row; document.querySelector = s => s === '[data-slash]' ? menu : null;
  const tb = {value: '/a'}; made = []; frames = []; slashDraw(tb, true); frame(0); slashDraw(tb); const s0 = menu.scrollTop; frame(.5); const s1 = menu.scrollTop; frame(1); out.slash = [s0, s1, menu.scrollTop, into];
  made = []; slashDraw(tb); out.slashTyped = [into, made.length];
  reduced = true; menu.scrollTop = 0; slashDraw(tb, true); out.slashCalm = [menu.scrollTop, made.length]; reduced = false;
  // at once, with motion on: the first load, a view's own place, a refresh, Talk following a reply, its opening
  document.querySelector = s => s === '[data-in]' ? ta : s === '.main' ? main : s === '.notices' ? {offsetHeight: 0} : null;
  scrollStop(b); frames = []; made = []; S.view = 'home'; VIEW = 'a:60 b:60 c:60 d:60'; render(true); b.scrollTop = 70; VIEW = 'n:35 ' + VIEW; render(); out.held = b.scrollTop;
  S.view = 'plan'; render(true); S.view = 'home'; render(true); out.back = b.scrollTop;
  S.view = 'talk'; render(true); const open = endOf(b) - b.scrollTop; CHAT += ' m9:90'; render(); out.follow = [open, endOf(b) - b.scrollTop];
  S.live = false; lastPlace = null; b._top = 0; render(true); out.load = endOf(b) - b.scrollTop; out.ran = [made.length, frames.length];
  console.log(JSON.stringify(out));
})();`);
"""


FOLD_DRIVER = MOTION_DRIVER.split('const out = {};')[0] + r"""const out = {}; El.prototype.textContent = '';
Object.defineProperty(El.prototype, 'previousElementSibling', {get() { const k = this.parentElement.kids; return k[k.indexOf(this) - 1] || null }});
const tall = (k, y, h, cls) => Object.assign(new El(k, y, cls), {h});
const list = open => box(tall('a', 0, open ? 140 : 40, 'card').add(new El('', 10, 'fold'), ...(open ? [tall('fold:a', 40, 100, 'foldin').add(tall('text:a', 40, 100))] : [])), new El('b', open ? 150 : 50, 'card'));
const look = () => ran.map(a => [a.el.dataset.k || 'copy of ' + a.el.of, a.o.easing, a.o.duration, a.kf.map(f => f.clipPath || f.transform)]);
const go = (was, is) => { redraw(was, is); return {anims: look(), came: is.all().filter(e => e.cls.has('enter')).map(e => e.dataset.k), room: is.kids[0].style.marginBottom || ''} };
const press = () => { now += 5000; MO.folded = now };
press(); out.open = go(list(false), list(true));
now += 100; out.half = (() => { const r = go(list(true), list(true)), a = ran.find(a => a.el.dataset.k === 'fold:a'); return [r.came, a && a.currentTime] })();
press(); const shut = list(false); out.close = go(list(true), shut); const edge = ran.find(a => a.el.dataset.k === 'a'); edge.onfinish(); out.after = shut.kids[0].style.marginBottom;
// in a sheet, anchored to its foot: what the fold shows goes with its button
const sheet = open => box(tall('head', open ? 100 : 200, 40), tall('btn', open ? 140 : 240, 40, 'fold'), ...(open ? [tall('fold:x', 180, 100, 'foldin')] : []), tall('foot', 280, 40));
press(); redraw(sheet(false), sheet(true)); out.up = look();
press(); redraw(sheet(true), sheet(false)); out.down = look();
now += 5000; out.refresh = go(list(false), list(true));
press(); document.activeElement = {matches: () => true}; const typed = list(false); typed.all().forEach(() => 0); typed.contains = () => true; out.typing = go(typed, list(true)).anims.length;
now += 5000; out.typingRefresh = go(typed, list(true)).anims.length; document.activeElement = null;
reduced = true; press(); out.calm = [go(list(false), list(true)), go(list(true), list(false))];
reduced = false; document.hidden = true; press(); out.hidden = [go(list(false), list(true)), go(list(true), list(false))];
console.log(JSON.stringify(out));`);
"""


def test_folds_f189b(tmp: Path) -> None:
    """F189b: a fold that a press opens or closes moves: what it shows is revealed and what stands under it glides, on
    one curve; a refresh half way goes on; instant when calm()."""
    if not shutil.which('node'):
        print('  (no node here: the fold script test is skipped)')
        return
    p = subprocess.run(['node', '-e', FOLD_DRIVER], input=W.page_html().decode(), capture_output=True, text=True, encoding='utf-8', timeout=30)
    check(p.returncode == 0, 'the fold script runs', p.stderr[-1500:])
    if p.returncode:
        return
    o = json.loads(p.stdout)
    clip = 'inset(0px 0px {}px 0px round 0px)'.format
    soft = ['ease', 450]
    eq(o['open']['anims'], [['fold:a', *soft, ['inset(0px 0px 100% 0px)', 'inset(0px 0px 0% 0px)']],
                            ['a', *soft, [clip(100), clip(0)]], ['b', *soft, ['translate(0px,-100px)', 'none']]],
       'open: the words are revealed, the card grows, the next card glides down')
    eq(o['open']['came'], [], 'nothing in it rises in as well')
    eq(o['half'], [[], 100], 'a refresh half way: it goes on from there')
    eq(o['close']['anims'], [['a', *soft, [clip(0), clip(100)]], ['b', *soft, ['translate(0px,100px)', 'none']],
                             ['copy of fold:a', *soft, ['inset(0px 0px 0px 0px)', 'inset(0px 0px 100px 0px)']]],
       'close: the card shrinks, the next card glides up, a copy of the words closes')
    eq((o['close']['room'], o['after']), ('-100px', ''), 'the card keeps room for what it lost until then')
    eq(o['up'][0], ['fold:x', *soft, ['inset(0px 0px 100% 0px)', 'inset(0px 0px 0% 0px)']], 'in a sheet it opens upward')
    eq({x[0]: x[3] for x in o['up'][1:]}, {'head': ['translate(0px,100px)', 'none'], 'btn': ['translate(0px,100px)', 'none'], 'fold:x': ['translate(0px,100px)', 'none']},
       'what it shows goes with its button; the foot stays')
    eq([(x[0], x[3]) for x in o['down'] if x[0] != 'copy of fold:x'], [('head', ['translate(0px,-100px)', 'none']), ('btn', ['translate(0px,-100px)', 'none'])], 'and closes downward')
    eq(o['refresh']['came'], ['fold:a', 'text:a'], 'no press: a new thing comes in as any other')
    check(o['typing'] > 0 and o['typingRefresh'] == 0, 'while a field is in use: a press moves it, a refresh does not', (o['typing'], o['typingRefresh']))
    for k in ('calm', 'hidden'):
        eq([x['anims'] for x in o[k]], [[], []], f'{k}: at once')
        eq([x['room'] for x in o[k]], ['', ''], f'{k}: no room kept')
    page = W.PAGE.read_text(encoding='utf-8')
    check("if(q('[aria-expanded],#sheet button'))MO.folded=Date.now()" in page, 'a press on a fold, or on a button of a sheet, moves it')
    for name, k in (('a Needs you fold', "foldIn('ask:'"), ('a task', 'foldIn(q.id'), ('a setting', "foldIn('set:'"), ('the models of a few kinds', "foldIn('kinds:'"),
                    ('Advanced and Project file', "foldIn('#'+id"), ('Not this', "foldIn('pitch:'"), ('Fix up', "foldIn('fix:'")):
        check(k in page, f'{name}: what it shows is one box')


def test_jumps_f189a(tmp: Path) -> None:
    """F189a: a scroll jump that a press causes glides (Talk's end, a field to look at, the slash menu's row); calm() makes
    it instant; a refresh, a reply, a view's own place, the first load and typing never glide."""
    if not shutil.which('node'):
        print('  (no node here: the scroll jump script test is skipped)')
        return
    (tmp / 'page.html').write_text(W.page_html().decode(), encoding='utf-8')
    (tmp / 'driver.js').write_text(JUMP_DRIVER, encoding='utf-8')
    p = subprocess.run(['node', str(tmp / 'driver.js'), str(tmp / 'page.html')], capture_output=True, text=True, encoding='utf-8', timeout=30)
    check(p.returncode == 0, 'the scroll jump script runs', p.stderr[-1500:])
    if p.returncode:
        return
    o = json.loads(p.stdout)
    eq(o['unpinned'], False, 'Talk is scrolled up')
    for k in ('send', 'mode'):
        eq(o[k], [[100, 400, 700], True, [[0, 450]], 0], f'Talk, {k}: the jump to its end glides, on a token, and it is pinned')
        eq((o[k + 'Calm'], o[k + 'Hidden']), ([700, 0], [700, 0]), f'{k}: at once when calm()')
    eq(o['redrawn'], [400, 450, 800, True], 'a redraw and new words half way: it goes on, to the new end')
    eq(o['hand'], [400, False, 0], "the person's hand takes it over")
    eq(o['moved'], [0, 0], 'another view ends it')
    eq(o['reveal'], [100, 274, 448], 'a press that moves to a field glides to it')
    eq((o['typed'], o['revealCalm']), ([448, 0], [448, 0]), 'while typing, and when calm(), at once')
    eq(o['both'], [100, 274, 448, 1], 'its focus does not cut the glide')
    eq(o['pushed'], [309, 483], 'a refresh that moves the place under it: it goes on to the field')
    eq(o['slash'], [0, 35, 70, 0], "an arrow in the slash menu glides to its row")
    eq((o['slashTyped'], o['slashCalm']), ([1, 0], [70, 0]), 'typing and calm(): at once')
    eq((o['held'], o['back'], o['follow'], o['load']), (105, 105, [0, 0], 0), 'a refresh, a view back, Talk following, the first load are in place')
    eq(o['ran'], [0, 0], 'and none of them glides')
    page = W.PAGE.read_text(encoding='utf-8')
    check('kbReveal(el,true);el.focus(' in page and 'kbReveal(t,true);kbFocus(t)' in page and 'e.key);slashShow(e.target,true)' in page,
          'the presses ask for the glide: a refused Done, Rename, an arrow key')


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
                      ('raw duration', r'(?:transition|animation)[^;}]*[\s:](?!0s)\.?\d+(?:\.\d+)?m?s\b')):
        eq(re.findall(pat, rules), [], f'no {what} outside the tokens')
    for kind in re.findall(r'transition:([^;}]+)', rules):
        for part in re.split(r',(?![^(]*\))', kind):
            if part.split()[0] in ('border-color', 'box-shadow') and ' 0s ' in part:  # B218: a step, not a motion
                continue
            check(part.split()[0] in ('transform', 'translate', 'opacity', 'clip-path', 'visibility', 'background-color', 'none', 'none!important'),
                  f'a transition on {part.split()[0]}', kind)
    for name, frames in re.findall(r'@keyframes (\w+)\{((?:[^{}]*\{[^}]*\})+)\}', bare):
        props = set(re.findall(r'[{;]\s*([a-z-]+):', frames))
        check(props <= {'opacity', 'transform'}, f'@keyframes {name} moves opacity and transform only', props)
    check(re.search(r'prefers-reduced-motion:reduce\)\{\*,\*::before,\*::after\{animation:none!important;transition:none!important', css)
          and css.count('prefers-reduced-motion') == 1, 'one rule turns every motion off')
    js = page.split('</style>', 1)[1]  # F147: a script's motion asks calm() itself; kbGlide() asks the browser
    for at in (m.start() for m in re.finditer(r'\.animate\(', js)):
        body = js[js.rindex('\nfunction ', 0, at):at]
        check('calm()' in body or 'prefers-reduced-motion' in body, 'a script that moves things asks for reduced motion first', body[:80])
    for guard in (r'function viewGo\(.*\n.*calm\(\).*\{go\(\);return\}', r'function leave\([^§]*?const a=moAnim'):
        check(re.search(guard, js), f'{guard}: none under reduced motion')
    for one in ('--spring:', '--spring-soft:'):
        check(css.count(one) == 2 and f'{one}cubic-bezier(' in css and f'{one}linear(0,' in css, f'{one} a spring, and its fallback')
    check('@supports (transition-timing-function:linear(0,1)){:root{' in css, 'only where the browser has linear()')
    check('if(MO.vt&&MO.vt.skip)MO.vt.skip()' in js and 'e.target!==document.documentElement' in js, 'a press during a View Transition ends it and lands')
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


def test_page_parts_c41a(tmp: Path) -> None:
    print('C41a: the page is one file per area, joined in the order of their names into one page')
    parts = sorted(W.PAGE_DIR.glob('*'))
    check(len(parts) >= 10, 'the parts are there', len(parts))
    page = W.PAGE.read_text(encoding='utf-8')
    check('/*PAGE_PARTS' not in page, 'every marker has its parts')
    for p in parts:
        check(p.read_text(encoding='utf-8') in page, f'{p.name} is in the page')
    check({p.suffix for p in parts} == {'.css', '.js'}, 'only styles and scripts', {p.suffix for p in parts})
    areas = {p.name.split('-', 1)[1].split('.')[0] for p in parts}
    check({'talk', 'chats', 'settings', 'tools', 'home', 'plan', 'live', 'shared'} <= areas, 'a file for each area', areas)
    eq(W.PAGE_TEXT, page, 'the served page is the joined one')
    toml = (Path(W.__file__).parent.parent / 'pyproject.toml').read_text(encoding='utf-8')
    check('"page/*.css"' in toml and '"page/*.js"' in toml, 'the wheel holds every part')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_server), in_tmp(test_page), in_tmp(test_logic), in_tmp(test_extras), in_tmp(test_views), in_tmp(test_page_copy_options), in_tmp(test_page_copy_publish), in_tmp(test_motion_f147), in_tmp(test_jumps_f189a), in_tmp(test_folds_f189b), in_tmp(test_style_f83), in_tmp(test_page_parts_c41a)]))
