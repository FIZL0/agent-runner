#!/usr/bin/env python3
"""F66: the run page on the web serves the page and the snapshot, runs an action's plan command, and refuses a
request without its token.

    python3 tests/test_web.py        (a temp repo, a server on a free local port, no agent; a few seconds)
"""
from __future__ import annotations

import json
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
        for part in (b'Status', b'Sessions', b'Queue', b'Needs you', b'Concepts', b'EventSource', b'#ef4444',
                     b'JetBrains Mono', b'max-width:760px'):
            check(part in page, f'the page has {part.decode()}')

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
        for part in (b"['J/K','reorder']", b"k==='J'||k==='K'", b"act('move'", b'S.follow=it.id'):
            check(part in page, f'the queue reorders with J/K on the page: {part.decode()}')

        code, out = post(f'{base}/act?t={token}', {'name': 'nope', 'args': {}})
        check(not out['ok'] and 'no such action' in out['out'], 'an unknown action is an error result', out)
        code, out = post(f'{base}/act?t={token}', {'name': 'drop', 'args': ['F1']})
        eq(code, 400, 'args that are not an object are a bad request')

        with mock.patch.object(W.shutil, 'which', side_effect=lambda n: '/usr/bin/tmux' if n == 'tmux' else None), \
                mock.patch('agent_runner.plat.WINDOWS', False):
            code, body = get(f'{base}/terminal/s1?t={token}')
        r = json.loads(body)
        check(not r['ok'] and 'install' in r['out'] and 'ttyd' in r['out'],
              'without ttyd the terminal tab says how to install it', r)
        eq((r['mode'], r['capture'], r['every']), ('builtin', 'pane/s1', 0.5),
           'and gives the built-in view: the pane captured every 0.5 s')
        with mock.patch.object(W.shutil, 'which', return_value=None):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        check(r['mode'] == 'feed' and 'no tmux' in r['out'] and r['feed'] == 'feed/s1',
              'no tmux: the feed only', r)
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch.object(W, 'pane_of', return_value=''):
            r = json.loads(get(f'{base}/terminal/s1?t={token}')[1])
        check(not r['ok'] and 'no tmux pane' in r['out'], 'a slot with no pane says so', r)
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


def test_theme(tmp: Path) -> None:
    """F69: the page is served in [ui] theme's colours, with every theme for its picker (T)."""
    fake_repo(tmp)
    eq(CF.DEFAULTS['ui']['theme'], 'ryha', '[ui] theme is ryha by default')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    style = lambda page: page.split(b'<style id="theme">')[1].split(b'</style>')[0]  # noqa: E731
    try:
        page = get(f'{base}/?t={token}')[1]
        check(b'--bg:#000000' in style(page) and b'--accent:#ef4444' in style(page), 'ryha by default',
              style(page))
        with mock.patch.dict(S.C.raw, {'ui': {'theme': 'light'}}):
            page = get(f'{base}/?t={token}')[1]
        check(b'--bg:#ffffff' in style(page) and b'color-scheme:light' in style(page),
              '[ui] theme = "light" serves the light colours', style(page))
        check(b'"default": "light"' in page, 'and the picker starts from it')
        for name in (b'ryha', b'omarchy', b'terminal', b'light'):
            check(b'"%s": {' % name in page, f'the picker has {name.decode()}')
        check(b"k==='T'" in page and b'localStorage' in page, 'T picks a theme, remembered per browser')
        colors = tmp / 'colors.toml'
        colors.write_text('background = "#1e1e2e"\nforeground = "#cdd6f4"\naccent = "#89b4fa"\n', encoding='utf-8')
        with mock.patch.dict(S.C.raw, {'ui': {'theme': 'omarchy'}}), \
                mock.patch.dict(W.os.environ, {'OMARCHY_COLORS': str(colors)}):
            page = get(f'{base}/?t={token}')[1]
        check(b'--bg:#1e1e2e' in style(page) and b'--accent:#89b4fa' in style(page),
              '[ui] theme = "omarchy" serves the Omarchy colours', style(page))
    finally:
        srv.stop()


def test_feed_pane_concept(tmp: Path) -> None:
    """F74: /feed/NAME gives the session's feed, /pane/NAME its pane's text, /concept/ID a concept's local page
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
        with mock.patch.object(U, 'session_pane', return_value='%6'), \
                mock.patch.object(U, 'TMUX', [lambda argv: (0, 'screen\n')]):
            r = json.loads(get(f'{base}/pane/c6?t={token}')[1])
        eq((r['ok'], r['text']), (True, 'screen\n'), "/pane/c6 is its pane's text")
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
        with mock.patch.object(U, 'session_pane', return_value='%6'), \
                mock.patch.object(U, 'TMUX', [lambda argv: (typed.append(argv), (0, ''))[1]]):
            code, out = post(f'{base}/act?t={token}', {'name': 'interrupt', 'args': {'session': 'c6'}})
        eq((out['ok'], typed), (True, [['send-keys', '-t', '%6', 'Escape']]), 'interrupt c6 through /act')
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
        for part in (b"const isCtl=it=>!!it&&/^c\\d+$/.test(it.name||'')",
                     b"it.ctl?['chat','pane','session']:it.task?['feed','pane','diff','session']:['feed','pane']",
                     b"if(isCtl(it))return `<span class=\"r\">${esc(it.name)}</span>",
                     b"if(isCtl(it)){toast(`${it.name} has no claude.ai/code link`",
                     b"<span class=\"d\">idle</span>"):
            check(part in page, f'the page treats a cN row as a control session: {part.decode()}')
        with mock.patch.object(W.shutil, 'which', return_value='/usr/bin/ttyd'), \
                mock.patch('agent_runner.control.control_live', return_value=0), \
                mock.patch('agent_runner.control.control_window', return_value='') as cw:
            r = json.loads(get(f'{base}/terminal/c6?t={token}')[1])
        eq(cw.call_args.args, (6, 0), "c6's terminal looks up control session 6's window")
        check(not r['ok'] and 'c6 has no tmux pane' in r['out'], 'and says when it has none', r)
    finally:
        srv.stop()
    copy = PC.page_copy_html(snap)
    check('<span class="r">c6</span><span>R43 site deploy</span><a' in copy and 'https://claude.ai/code/c6x' in copy,
          'the copy lists c6 with its title and session link', copy)
    check('s2 is idle: nothing running' in copy, 'and the idle s2 as idle', copy)
    check('open it from the run page' not in copy, 'with no open-it hint on c6 or s2', copy)


def test_tabs(tmp: Path) -> None:
    """F75: the page as the final design has it: each panel's tabs and their markup, keys on the buttons and
    labels, no [ ] keys."""
    fake_repo(tmp)
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    try:
        page = get(f'http://127.0.0.1:{srv.server_address[1]}/?t={token}')[1].decode()
    finally:
        srv.stop()
    for part in ("it.k==='rel'?['release','chat','log']:['chat','log']",  # Status
                 "it.ctl?['chat','pane','session']:it.task?['feed','pane','diff','session']",  # Sessions
                 "it.newchat?['info']", 'new chat (<b class="pk">N</b>)',
                 "it.newtask?['chat edit','direct edit']:['direct edit','chat edit']",  # Queue: no info tab
                 'new task (<b class="pk">n</b>)', "return['answer','info']", "return['preview']",
                 'data-quick=', "quickKey(q.key)", 'data-answer=', "K('L','later')", 'data-opt=', "K('O','open on claude.ai",
                 "K('t','what, why, how to check')", "K('k','kind')", '<b class="pk">K</b> back', "K('p','priority')",
                 "K('f','files')", "K('a','after')", 'id="f-ahint"', "K('^S','save')", "K('D','drop')",
                 "K('H','do it here')", 'class="chip after">⧗ after', 'chip run', 'chip crit', 'chip next',
                 "'diff/'", "'feed/'", "'concept/'", "act('chat_to'", "act('interrupt'", "act('new_control'",
                 "act('quick_ask'", 'DRAFT_KEY', 'localStorage.setItem(DRAFT_KEY', '<div class="fold">· ${fold} step',
                 '.box.on .row.cur .chip.after{max-width:none;flex-basis:100%',
                 '*{scrollbar-width:none}', '*::-webkit-scrollbar{display:none}',  # no visible scrollbars
                 '.pk{color:var(--yellow)', '.foot .k{color:var(--yellow)', '.foot .glob .k{color:var(--bblue)'):
        check(part in page, f'the page has {part}')
    check("k===']'" not in page and "k==='['" not in page, 'no [ ] keys')
    check('cancel' not in page.split('function editHTML')[1].split('function chatBox')[0], 'the direct edit has no cancel')
    check('id="relbtn"' not in page, 'R release only in Status, not in the top bar')


KEYS_DRIVER = """const m=require(process.argv[2]);
const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(([fn,...a])=>m[fn](...a))));
"""


def keys_js(cases: list) -> list:
    """Run the page's key script (<script id="keys">) in node on `cases` ([function name, *args] each)."""
    page = W.PAGE.read_text(encoding='utf-8')
    js = page.split('<script id="keys">', 1)[1].split('</script>', 1)[0]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / 'keys.js').write_text(js, encoding='utf-8')
        (Path(d) / 'driver.js').write_text(KEYS_DRIVER, encoding='utf-8')
        r = subprocess.run(['node', str(Path(d) / 'driver.js'), str(Path(d) / 'keys.js')], input=json.dumps(cases),
                           capture_output=True, text=True, timeout=60)
    check(r.returncode == 0, 'node runs the key script', r.stderr[-800:])
    return json.loads(r.stdout or '[]') or [None] * len(cases)


def test_keys(tmp: Path) -> None:
    """F75: the key handler and the bottom line, driven in node: h/l, ^h/^l, n, the direct edit's field keys,
    1-5 everywhere, Enter / Esc in a chat, the answer keys, and the footer's rules."""
    if not shutil.which('node'):
        print('  (no node here: the key handler test is skipped)')
        return
    tabs = {1: ['chat', 'log'], 2: ['chat', 'pane', 'session'], 3: ['direct edit', 'chat edit'], 4: ['answer', 'info'],
            5: ['preview']}

    def c(panel=3, main=False, tab=None, typing=False, chat_box=False, busy=False, it=None, answer_keys=()):
        return {'panel': panel, 'panelName': ['', 'Status', 'Sessions', 'Queue', 'Needs you', 'Concepts'][panel],
                'focusMain': main, 'tab': tab or tabs[panel][0], 'tabs': tabs[panel], 'typing': typing,
                'chatBox': chat_box, 'popup': False, 'busy': busy, 'it': it or {}, 'answerKeys': list(answer_keys)}

    def ev(key, **kw):
        return {'key': key, 'ctrl': False, 'meta': False, 'shift': False, 'alt': False, **kw}
    edit = c(3, True, 'direct edit')
    cases = [  # (what, context, event, the commands it should give)
        ('l in a panel goes into the main pane', c(3), ev('l'), [['into']]),
        ('Enter too', c(3), ev('Enter'), [['into']]),
        ('h in a panel does nothing', c(3), ev('h'), []),
        ('h on the first tab goes back to the panels', c(3, True, 'direct edit'), ev('h'), [['back']]),
        ('h on a later tab: the previous tab', c(3, True, 'chat edit'), ev('h'), [['tab', -1]]),
        ('l in the main pane: the next tab', c(2, True, 'chat'), ev('l'), [['tab', 1]]),
        ('Esc goes back to the panels', c(2, True, 'pane'), ev('Escape'), [['back']]),
        ('^h: the left side', c(2, True, 'pane'), ev('h', ctrl=True), [['side', 'left']]),
        ('^l: the right side', c(2), ev('l', ctrl=True), [['side', 'right']]),
        ('^h while typing too', c(2, True, 'chat', typing=True, chat_box=True), ev('h', ctrl=True), [['side', 'left']]),
        ('n in Queue: a new task (chat edit)', c(3), ev('n'), [['newtask']]),
        ('n in Queue\'s main pane too', c(3, True, 'chat edit'), ev('n'), [['newtask']]),
        ('n elsewhere: nothing', c(2), ev('n'), []),
        ('e: the direct edit', c(3), ev('e'), [['tabto', 'direct edit']]),
        ('E: the chat edit', c(3), ev('E'), [['tabto', 'chat edit']]),
        ('J: move down', c(3), ev('J'), [['reorder', 1]]),
        ('K: move up', c(3), ev('K'), [['reorder', -1]]),
        ('p: priority on/off', c(3), ev('p'), [['pri']]),
        ('H: do it here', c(3), ev('H'), [['act', 'take']]),
        ('D: drop', c(3), ev('D'), [['act', 'drop']]),
        ('t: the what field', edit, ev('t'), [['focus', 'f-title']]),
        ('k: the next kind', edit, ev('k'), [['cycle', 'f-kind', 1]]),
        ('K: the kind back', edit, ev('K'), [['cycle', 'f-kind', -1]]),
        ('p: priority toggles', edit, ev('p'), [['cycle', 'f-pri', 1]]),
        ('f: files', edit, ev('f'), [['focus', 'f-files']]),
        ('a: after', edit, ev('a'), [['focus', 'f-after']]),
        ('Tab: the next field', edit, ev('Tab'), [['field', 1]]),
        ('Shift+Tab: the previous field', edit, ev('Tab', shift=True), [['field', -1]]),
        ('Tab while typing in a field', c(3, True, 'direct edit', typing=True), ev('Tab'), [['field', 1]]),
        ('^S saves', c(3, True, 'direct edit', typing=True), ev('s', ctrl=True), [['save']]),
        ('D in the edit drops', edit, ev('D'), [['act', 'drop']]),
        ('H in the edit: do it here', edit, ev('H'), [['act', 'take']]),
        ('a new task has no drop', c(3, True, 'direct edit', it={'newtask': True}), ev('D'), []),
        ('1-5 work in a direct edit', edit, ev('4'), [['panel', 4]]),
        ('and in every other tab', c(5, True, 'preview'), ev('2'), [['panel', 2]]),
        ('but not while typing', c(3, True, 'direct edit', typing=True), ev('2'), []),
        ('no [ key', c(3, True, 'chat edit'), ev('['), []),
        ('no ] key', c(3), ev(']'), []),
        ('Tab: the next panel', c(3), ev('Tab'), [['panel', 4]]),
        ('Shift+Tab: the previous panel', c(1), ev('Tab', shift=True), [['panel', 5]]),
        ('R in Status: release', c(1), ev('R'), [['release']]),
        ('R elsewhere: nothing', c(3), ev('R'), []),
        ('c: chat with c1', c(4), ev('c'), [['chat']]),
        ('Enter in a chat box sends', c(2, True, 'chat', typing=True, chat_box=True), ev('Enter'), [['send']]),
        ('Shift+Enter is a new line', c(2, True, 'chat', typing=True, chat_box=True), ev('Enter', shift=True), []),
        ('Esc while it works interrupts', c(2, True, 'chat', typing=True, chat_box=True, busy=True), ev('Escape'),
         [['interrupt']]),
        ('Esc otherwise leaves the box', c(2, True, 'chat', typing=True, chat_box=True), ev('Escape'), [['blur']]),
        ('s in Status chat: a quick ask', c(1, True, 'chat'), ev('s'), [['quick', 'since']]),
        ('u: usage', c(1, True, 'chat'), ev('u'), [['quick', 'usage']]),
        ('v shows the steps', c(2, True, 'chat'), ev('v'), [['steps']]),
        ('N: a new chat', c(2), ev('N'), [['newchat']]),
        ('o opens the session', c(2, it={'ctl': True}), ev('o'), [['open']]),
        ('j in a concept: the next option', c(5, True), ev('j'), [['opt', 1]]),
        ('k: the previous option', c(5, True), ev('k'), [['opt', -1]]),
        ('Enter goes with it', c(5, True), ev('Enter'), [['go']]),
        ('i: say what to change', c(5, True), ev('i'), [['typebox']]),
        ('O opens it on claude.ai', c(5, True), ev('O'), [['open']]),
        ('n answers no', c(4, True, 'answer', answer_keys=['y', 'n']), ev('n'), [['answer', 1]]),
        ('L: later', c(4, True, 'answer'), ev('L'), [['act', 'later']]),
        ('a in Needs you: answer', c(4), ev('a'), [['tabto', 'answer']]),
    ]
    feet = [  # (what, context, keys the window shows)
        ('queue', c(3), ['n']),
        ('direct edit', edit, ['t', 'k', 'K', 'p', 'f', 'a', '^S', 'D', 'H']),
        ('typing', c(2, True, 'chat', typing=True, chat_box=True), ['⏎']),
        ('concept', c(5, True), ['O']),
        ('sessions', c(2, it={'ctl': True}), ['N']),
    ]
    got = keys_js([['route', ctx, e] for _, ctx, e, _ in cases] + [['footer', ctx, shown] for _, ctx, shown in feet]
                  + [['answerOpts', {'label': 'CONFIRM', 'ask': 'Works?'}],
                     ['answerOpts', {'label': 'DECIDE', 'options': ['ship it', 'wait', 'drop it']}],
                     ['tabsFor', 3, {'newtask': False}], ['tabsFor', 2, {'task': True}]])
    for (what, _, _, want), out in zip(cases, got):
        eq(out, want, what)
    foot = dict(zip([w for w, _, _ in feet], got[len(cases):len(cases) + len(feet)]))
    keys = lambda f: [k for k, _ in f['here']]  # noqa: E731
    glob = [['1-5', 'panel'], ['c', 'chat'], ['?', 'keys']]
    eq(keys(foot['queue']), ['e', 'E', 'J/K', 'p', 'H', 'D'], "Queue's keys, without n (its row shows it)")
    eq((foot['queue']['mode'], foot['queue']['glob']), ('QUEUE', glob), 'the mode badge, then only 1-5, c and ?')
    eq(keys(foot['direct edit']), ['h/l', 'Tab', 'Esc'], 'a direct edit: no key its labels and buttons show')
    eq((foot['typing']['mode'], foot['typing']['glob'], keys(foot['typing'])), ('INSERT', [], ['Esc', '⇧⏎']),
       'typing: Esc and Shift+Enter, no global keys')
    eq(keys(foot['concept']), ['h/l', '⏎', 'i', 'Esc'], 'a concept: no j/k, nor the O its link shows')
    check(all(k not in ('j/k', '^h/^l', 'j', 'k') for f in foot.values() for k in keys(f)), 'never j/k or ^h/^l')
    eq(keys(foot['sessions']), ['⏎', 'v', 'o'], 'Sessions: without N (its row shows it)')
    opts = got[len(cases) + len(feet):]
    eq(opts[0], [{'key': 'y', 'label': 'yes'}, {'key': 'n', 'label': 'no'}], 'a CONFIRM answers y yes, n no')
    eq([o['key'] for o in opts[1]], ['a', 'b', 'c'], "a pick's options answer a, b, c")
    eq(opts[2], ['direct edit', 'chat edit'], 'Queue has no info tab')
    eq(opts[3], ['feed', 'pane', 'diff', 'session'], 'a slot on a task: feed, pane, diff, session')


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


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_server), in_tmp(test_real_action), in_tmp(test_start), in_tmp(test_theme),
                           in_tmp(test_control_rows), in_tmp(test_feed_pane_concept), in_tmp(test_tabs),
                           in_tmp(test_keys), in_tmp(test_diff)]))
