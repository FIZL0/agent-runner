#!/usr/bin/env python3
"""F66: the run page on the web serves the page and the snapshot, runs an action's plan command, and refuses a
request without its token.

    python3 tests/test_web.py        (a temp repo, a server on a free local port, no agent; a few seconds)
"""
from __future__ import annotations

import json
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

        with mock.patch.object(W.shutil, 'which', return_value=None):
            code, body = get(f'{base}/terminal/s1?t={token}')
        r = json.loads(body)
        check(not r['ok'] and 'install' in r['out'] and 'ttyd' in r['out'],
              'without ttyd the terminal tab says how to install it', r)
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
                     b"isCtl(it)?['terminal','session']:['terminal','info','session']",
                     b"if(isCtl(it))return `<span class=\"r\">${esc(it.name)}</span>",
                     b"if(a==='open'&&it&&it.name&&!isCtl(it))act(",
                     b"tab==='terminal'&&it.state==='idle'&&!isCtl(it)",
                     b'is idle: nothing running'):
            check(part in page, f'the page treats a cN row as a control session: {part.decode()}')
        check(b"it.name==='c1'?['chat','terminal','session']" in page, 'c1 keeps its chat tab')
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


def in_tmp(f):
    def go():
        with tempfile.TemporaryDirectory() as d:
            f(Path(d))
    go.__name__ = f.__name__
    return go


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_server), in_tmp(test_real_action), in_tmp(test_start), in_tmp(test_theme),
                           in_tmp(test_control_rows)]))
