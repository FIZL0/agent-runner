#!/usr/bin/env python3
"""F428a: a runner.toml tool's web page: the settings, start, stop, state, a changed command, who may.

    python3 tests/test_tool_page.py        (a temp repo, real processes; about 15 seconds)
"""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import config as CF, device_page as DP, devices as D, runner as R, shared_tools as T, web as W  # noqa: E402

URL = 'http://127.0.0.1:8123/remote'
BASE = '[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'


def toml(*lines: str, name: str = 'phone') -> None:
    (T.S.C.root / 'runner.toml').write_text(BASE + f'[run.tools.{name}]\ncheck = "true"\n' + ''.join(l + '\n' for l in lines), encoding='utf-8')
    with contextlib.suppress(SystemExit):
        T.S.C.run['tools'] = CF.Config(T.S.C.root).run['tools']


def op(op_: str, name: str = 'phone', **a) -> dict:
    return D.post(json.dumps({'op': op_, 'name': name, **a}).encode(), T.S.C)[1]


def cmd(*a: str, cwd: Path | None = None) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(ROOT / 'run'), 'device', *a], cwd=str(cwd or T.S.C.root), capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout + r.stderr


def state(name: str = 'phone') -> str:
    return (D.page_state(D.tool_page(T.S.C, name)) or {}).get('state', '')


def shown(source: str = 'runner.toml') -> dict:
    return next(t for t in D.page(T.S.C)['tools'] if t['name'] == 'phone' and t['source'] == source)


def rec(name: str = 'phone') -> dict:
    return json.loads((D._page_dir(D.tool_page(T.S.C, name)) / 'run.json').read_text())


def test_config() -> None:
    print('page and start as settings: an http(s) address or :PORT, a start only with a page')
    for bad in ({'page': 'javascript:alert(1)'}, {'page': 'data:text/html,x'}, {'page': 'file:///etc'}, {'page': 'x.local'},
                {'page': 'http://u:pw@x/'}, {'page': 'http://a b'}, {'page': ':'}, {'page': ':0'}, {'page': ':65536'}, {'page': ':80/x'},
                {'page': ':80@evil.example'}, {'page': ':x'}, {'page': 8080}, {'start': 'true'}, {'start': ' true', 'page': ' '},
                {'page': URL, 'start': 'a\nb'}, {'page': ':80', 'start': 'x' * 1001}, {'page': ':80', 'start': ['a']},
                {'page': ':80', 'folder': '/x'}):
        check('[run.tools.p]' in CF.tools_problem({'p': {'check': 'true', **bad}}), f'refused: {str(bad)[:60]}')
    for good in ({}, {'page': URL}, {'page': ':8080'}, {'page': 'HTTPS://b.ts.net:8443/a?b=c', 'start': 'x'},
                 {'page': ':1', 'start': 'x | y'}, {'page': '', 'start': ''}):
        eq(CF.tools_problem({'p': {'check': 'true', **good}}), '', f'taken: {good}')
    eq(CF.setting_problem('run', 'tools', {'p': {'check': 'true', 'page': ':8080'}}), '', 'as a setting')
    toml('page = "javascript:x"')
    try:
        CF.Config(T.S.C.root)
        check(False, 'a bad page is refused when the file is read')
    except SystemExit as e:
        check('http' in str(e), 'a bad page is refused when the file is read', e)


def test_none() -> None:
    print('without page nothing changes; a page alone has no start, stop or state')
    toml()
    eq([k for k in shown() if k in ('page', 'start', 'run')], [], 'GET /tools has none')
    for o in ('start', 'stop'):
        check('no start command' in op(o)['out'] and cmd(o, 'phone')[0] == 1, o)
    toml(f'page = "{URL}"')
    eq((shown()['page'], shown()['run']), (URL, None), 'the address alone')
    for o in ('start', 'stop'):
        check('no start command' in op(o)['out'] and cmd(o, 'phone')[0] == 1, o)
    check(URL in cmd('list')[1], 'list has it')


def test_run(tmp: Path) -> None:
    print('start, state, stop, in the main checkout, from its own runner.toml alone')
    toml('page = ":8123"', 'start = "pwd > where; sleep 600"')
    eq((shown()['page'], shown()['run']['state']), (':8123', 'stopped'), 'at first')
    r = op('start', start='touch evil', page='http://evil', folder=str(tmp), cmd='touch evil')
    check(r['ok'] and r['state'] == 'running', 'started', r)
    eq((rec()['cmd'], rec()['cwd'], (T.S.C.root / 'where').read_text().strip(), (T.S.C.root / 'evil').exists()),
       ('pwd > where; sleep 600', str(T.S.C.root), str(T.S.C.root), False), "no text of the request's")
    pid = rec()['pid']
    check('already' in op('start')['out'] and 'already' in cmd('start', 'phone')[1] and rec()['pid'] == pid, 'started once')
    eq(shown()['run'], {'state': 'running', 'lines': []}, 'GET /tools')
    check(':8123 (running)' in cmd('list')[1] and 'Web page: :8123 (running)' in cmd('show', 'phone')[1], 'list, show')
    rc, out = cmd('stop', 'phone')
    check(rc == 0 and not DP._group(pid) and state() == 'stopped', 'run device stop', out)
    check('not running' in op('stop')['out'], 'a second stop')
    wt = tmp / 'wt'
    git(T.S.C.root, 'worktree', 'add', '-q', str(wt), '-b', 'x')
    (wt / 'runner.toml').write_text(BASE + '[run.tools.phone]\ncheck = "true"\npage = ":1"\nstart = "touch evil"\n', encoding='utf-8')
    rc, out = cmd('start', 'phone', cwd=wt)
    check(rc == 0 and ':8123' in out and rec()['cmd'].startswith('pwd'), "from a worktree, the main checkout's command", out)
    check(op('stop')['ok'] and not list(wt.glob('evil')), 'stopped')
    git(T.S.C.root, 'worktree', 'remove', '--force', str(wt))
    toml('page = ":8123"', 'start = "echo no luck; exit 3"')
    r = op('start')
    check(not r['ok'] and r['state'] == 'failed' and r['lines'] == ['no luck'], 'failed', r)
    check('no luck' in cmd('show', 'phone')[1], 'and show says so')


def test_changed() -> None:
    print('the command changed or taken out while it runs: Stop still ends the old one')
    for new in (('page = ":8123"', 'start = "sleep 601"'), ('page = ":8123"',), ()):
        toml('page = ":8123"', 'start = "sleep 600"')
        check(op('start')['ok'], 'started')
        pid, old = rec()['pid'], rec()['cmd']
        toml(*new)
        eq((state(), shown()['run']['state']), ('running', 'running'), f'still running: {new}')
        eq((rec()['cmd'], rec()['pid']), (old, pid), 'the old one')
        r = op('stop')
        check(r['ok'] and not DP._group(pid), 'stopped', r)
    toml('page = ":8123"', 'start = "sleep 601"')
    check(op('start')['ok'] and rec()['cmd'] == 'sleep 601', 'the next start has the new one')
    pid = rec()['pid']
    toml(name='other')
    rc, out = cmd('stop', 'phone')
    check(rc == 0 and not DP._group(pid), 'the tool itself gone', out)
    check(cmd('stop', 'phone')[0] == 2, 'then there is none')
    toml('page = ":8123"', 'start = "sleep 600"')
    op('start')
    pid = rec()['pid']
    (T.S.C.root / 'runner.toml').write_text('[run', encoding='utf-8')
    check(op('stop')['ok'] and not DP._group(pid), 'a file that does not read')
    toml('page = "javascript:x"', 'start = "sleep 600"')
    check(not op('start')['ok'], 'a bad page starts nothing')


def test_one_name() -> None:
    print('a device with the same name is another thing: source says which')
    toml()
    save = dict(kind='other', reach='git status', page=URL, start='sleep 700')
    check(op('save', name='mine', **save)['ok'], 'a device')
    d = json.loads((D.state_dir() / 'devices.json').read_text())
    d['devices']['phone'] = {**d['devices'].pop('mine')}
    (D.state_dir() / 'devices.json').write_text(json.dumps(d))
    toml('page = ":8123"', 'start = "sleep 600"')
    for src, other in (('runner.toml', 'device'), ('device', 'runner.toml')):
        check(op('start', source=src)['ok'], src)
        eq((shown(src)['run']['state'], shown(other)['run']['state']), ('running', 'stopped'), f'{src} alone')
        check(op('stop', source=src)['ok'] and shown(src)['run']['state'] == 'stopped', f'{src} stopped')
    check(not op('start', source='x')['ok'], 'no other source')
    check(op('start')['ok'] and shown('device')['run']['state'] == 'running', 'with none named: the device, as before')
    op('stop')
    check(cmd('start', 'phone')[0] == 0 and state() == 'running', 'run device: runner.toml wins')
    op('stop', source='runner.toml')
    op('remove')


def test_rules() -> None:
    print('refused over http, without the token, from another page')
    toml('page = ":8123"', 'start = "sleep 600"')
    srv = W.serve('tok', 0, '127.0.0.1')
    port = srv.server_address[1]
    origin = f'http://127.0.0.1:{port}'

    def post(path: str, **h) -> int:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        c.request('POST', path, body=json.dumps({'op': 'start', 'name': 'phone', 'source': 'runner.toml'}),
                  headers={'Content-Type': 'application/json', **{k.replace('_', '-'): v for k, v in h.items()}})
        return c.getresponse().status
    try:
        for path, h in (('/tools', dict(Origin=origin)), ('/tools?t=tok', dict(Origin='http://evil.example')), ('/tools?t=tok', {}),
                        ('/tools?t=tok', dict(Origin=origin, X_Forwarded_For='8.8.8.8')),
                        ('/tools?t=tok', dict(Host='box:80', Origin='http://box:80'))):
            eq((post(path, **h), state()), (403, 'stopped'), f'refused: {path} {h}')
        eq((post('/tools?t=tok', Origin=origin), state()), (200, 'running'), 'the page may')
    finally:
        srv.stop()
        op('stop', source='runner.toml')


def main() -> int:
    if os.name == 'nt':
        print('skipped: process groups are POSIX')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        repo = tmp / 'proj'
        (repo / 'plan').mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py\n', encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text(BASE, encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        try:
            return report([test_config, test_none, lambda: test_run(tmp), test_changed, test_one_name, test_rules])
        finally:
            for d in (tmp / 'state/pages').glob('*'):  # a failed check leaves no process behind
                with contextlib.suppress(Exception):
                    DP.stop(d)


if __name__ == '__main__':
    sys.exit(main())
