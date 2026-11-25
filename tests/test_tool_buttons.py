#!/usr/bin/env python3
"""F428c: a tool's own buttons: the settings, a press, its failure and timeout, a busy tool, who may.

    python3 tests/test_tool_buttons.py        (a temp repo, real processes; about 10 seconds)
"""
from __future__ import annotations

import contextlib
import http.client
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from _check import check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import config as CF, devices as D, plat, runner as R, shared_tools as T, tool_buttons as B, web as W  # noqa: E402

BASE = '[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'


def toml(*buttons: dict, check_: str = 'true') -> None:
    text = BASE + f'[run.tools.phone]\ncheck = {json.dumps(check_)}\n'
    for b in buttons:
        text += '[[run.tools.phone.buttons]]\n' + ''.join(f'{k} = {json.dumps(v)}\n' for k, v in b.items())
    (T.S.C.root / 'runner.toml').write_text(text, encoding='utf-8')
    T.S.C.run['tools'] = CF.Config(T.S.C.root).run['tools']


def btn(label: str, cmd: str, **more) -> dict:
    return {'label': label, 'cmd': cmd, **more}


def op(op_: str, name: str = 'phone', **a) -> dict:
    return D.post(json.dumps({'op': op_, 'name': name, **a}).encode(), T.S.C)[1]


def press(button: str, name: str = 'phone', **a) -> dict:
    return op('press', name, button=button, **a)


def shown(name: str = 'phone') -> dict:
    return next(t for t in D.page(T.S.C)['tools'] if t['name'] == name)


def live(*tids: str) -> contextlib.AbstractContextManager:
    """A run is up with these tasks running."""
    @contextlib.contextmanager
    def go():
        was, D._running = D._running, lambda root: {str(i): t for i, t in enumerate(tids, 1)}
        try:
            yield
        finally:
            D._running = was
    return go()


def test_config() -> None:
    print('settings: any number of buttons, each a label and a one-line cmd, a question if any')
    ok = btn('A', 'true')
    for bad in ('x', {'label': 'A', 'cmd': 'true'}, ['x'], [{}], [{'label': 'A'}], [{'cmd': 'true'}], [btn(' ', 'true')],
                [btn('A', ' ')], [btn('A', 'a\nb')], [btn('A\tb', 'x')], [btn('A', 'x' * 1001)], [btn('x' * 61, 'x')],
                [btn('A', 'x', confirm='x' * 301)], [btn('A', 'x', confirm=True)], [btn('A', 5)], [btn('A', 'x', sort='y')],
                [ok, btn('a', 'false')]):
        check('[run.tools.p]' in CF.tools_problem({'p': {'check': 'true', 'buttons': bad}}), f'refused: {str(bad)[:60]}')
    for good in ([], [ok], [btn(f'B{i}', 'true') for i in range(40)], [btn('A', 'x | y', confirm='Sure?')]):
        eq(CF.tools_problem({'p': {'check': 'true', 'buttons': good}}), '', f'taken: {len(good)}')
    eq(CF.tools_problem({'p': {'check': 'true'}}), '', 'none, as before')
    toml()
    check('buttons' not in shown(), 'none: GET /tools is as before')
    toml(btn('Go', 'true'), btn('Wipe', 'true', confirm='Wipe it?'))
    eq(shown()['buttons'], [btn('Go', 'true'), btn('Wipe', 'true', confirm='Wipe it?')], 'GET /tools has them')


def test_run() -> None:
    print("a press: the main checkout's command, there; nothing of the request's")
    toml(btn('Go', 'pwd; echo hi; printenv AGENT_RUNNER_SLOT'), btn('Bad', 'echo no luck; exit 3'),
         btn('Wipe', 'touch wiped', confirm='Wipe it?'), btn('Many', 'seq 1 500'))
    os.environ['AGENT_RUNNER_SLOT'] = '9'
    r = press('Go', cmd='touch evil', page='x')
    del os.environ['AGENT_RUNNER_SLOT']
    eq((r['ok'], r['exit'], r['lines']), (False, 1, [str(T.S.C.root), 'hi']), 'in the main checkout, no slot of a run')
    check(not (T.S.C.root / 'evil').exists(), 'no command of the request')
    r = press('Bad')
    eq((r['ok'], r['exit'], r['lines'], r['out']), (False, 3, ['no luck'], 'Bad: failed (exit 3)'), 'a failure')
    r = press('Many')
    eq((r['ok'], len(r['lines']), r['lines'][-1]), (True, D.PAGE_LINES, '500'), 'the last lines')
    eq((press('Wipe')['ask'], press('Wipe', confirm='Other?')['ask']), ('Wipe it?', 'Wipe it?'), 'the question is asked')
    check(not (T.S.C.root / 'wiped').exists(), 'and nothing ran')
    check(press('Wipe', confirm='Wipe it?')['ok'] and (T.S.C.root / 'wiped').exists(), 'answered, it runs')
    for bad in ('Nope', 'go', '', None, 5, ['Go'], {'label': 'Go'}):
        eq(press(bad)['out'], 'phone has no such button', f'unknown: {bad!r}')
    check('no such' in press('Go', name='nope')['out'] and not press('Go', name=['phone'])['ok'], 'unknown tool')
    check(not press('Go', source='x')['ok'] and not press('Go', source='device')['ok'], 'another source')
    (T.S.C.root / 'runner.toml').write_text(BASE + '[run.tools.phone]\ncheck = "true"\nbuttons = [{label="Go", cmd=5}]\n')
    check('no such button' in press('Go')['out'], 'a bad file runs nothing')


def test_secret() -> None:
    print('stored secrets are hidden in the output')
    was, D._all_secrets = D._all_secrets, lambda: ['hunter2hunter2']
    try:
        toml(btn('Say', 'echo pw hunter2hunter2'))
        eq(press('Say')['lines'], [f'pw {D.HIDDEN}'], 'hidden')

        def cannot():
            raise D.Refused('locked')
        D._all_secrets = cannot
        eq(press('Say')['lines'], [D.NOT_SHOWN], 'one that cannot be read: no output')
    finally:
        D._all_secrets = was


def test_timeout() -> None:
    print('past the time limit it is ended, with what it started')
    was, B.TIMEOUT = B.TIMEOUT, 0.5
    try:
        toml(btn('Slow', 'echo before; sleep 600 & echo $! > pid; wait'))
        t = time.monotonic()
        r = press('Slow')
        eq((r['ok'], r['exit'], r['lines']), (False, None, ['before']), 'said')
        check('ran past' in r['out'] and time.monotonic() - t < 8, 'and soon', r)
        check(not plat.alive(int((T.S.C.root / 'pid').read_text())), 'its child is gone')
    finally:
        B.TIMEOUT = was
    was, B.OUT_MAX = B.OUT_MAX, 1 << 16
    try:
        toml(btn('Yes', 'yes'))
        check('too much' in press('Yes')['out'], 'one that prints without end is ended')
    finally:
        B.OUT_MAX = was


def test_once() -> None:
    print('one at a time per tool')
    toml(btn('Wait', 'touch up; while [ ! -e go ]; do sleep 0.05; done'), btn('Other', 'true'))
    got: list[dict] = []
    th = threading.Thread(target=lambda: got.append(press('Wait')))
    th.start()
    end = time.monotonic() + 20
    while not (T.S.C.root / 'up').exists() and time.monotonic() < end:
        time.sleep(0.02)
    eq(press('Other')['out'], 'a button of phone is still running', 'another of the same tool waits for it')
    (T.S.C.root / 'go').touch()
    th.join(30)
    check(got and got[0]['ok'] and press('Other')['ok'], 'then it may')


def test_busy() -> None:
    print('a busy tool: refused with the holder, until that same holder is confirmed')
    go = btn('Go', 'echo x >> ran')
    ran = lambda: len((T.S.C.root / 'ran').read_text().split()) if (T.S.C.root / 'ran').exists() else 0  # noqa: E731
    toml(go, check_='cat who; exit 75')
    (T.S.C.root / 'who').write_text('F389\n')
    r = press('Go')
    eq((r['ok'], r['busy']['holder'], r['out'], ran()), (False, 'F389', 'phone is held by F389', 0), 'refused, named')
    key = r['busy']['key']
    check(press('Go', holder='x')['busy'] and press('Go', holder=True)['busy'] and ran() == 0, 'a guess is none')
    check(press('Go', holder=key)['ok'] and ran() == 1, 'confirmed')
    (T.S.C.root / 'who').write_text('F400\n')
    r = press('Go', holder=key)
    eq((r['ok'], r['busy']['holder'], ran()), (False, 'F400', 1), 'a new holder asks again')
    toml(go, check_='exit 69')
    check(press('Go')['ok'], 'a missing tool is nobody\'s')
    toml(go)
    with live('T1'):
        r = press('Go')
        eq(r['busy']['holder'], 'T1', 'free by its check, but a running task needs it')
        check(press('Go', holder=r['busy']['key'])['ok'], 'confirmed')
    with live('T2'):
        eq(press('Go', holder=r['busy']['key'])['busy']['holder'], 'T2', 'another task asks again')
    with live('T3'):
        check(press('Go')['ok'], 'a task that does not need it holds nothing')


def test_device(tmp: Path) -> None:
    print('an added device has them too, saved by a person')
    toml()
    save = dict(kind='other', reach='git status')
    check(not op('save', 'rig', **save, buttons=[btn('A', '')])['ok'], 'a bad one is refused')
    check(op('save', 'rig', **save, buttons=[btn('Go', 'pwd', confirm='')])['ok'], 'saved')
    eq(shown('rig')['buttons'], [btn('Go', 'pwd')], 'GET /tools')
    eq(press('Go', 'rig')['lines'], [str(Path.home())], 'run in the home folder')
    check(op('save', 'rig', edit='rig', **save, description='x')['ok'], 'an edit by a page that knows no buttons')
    eq(shown('rig')['buttons'], [btn('Go', 'pwd')], 'keeps them')
    check(op('save', 'rig', edit='rig', **save, exclusive=True, page='http://x/', start='true', folder=str(tmp),
             buttons=[btn('Go', 'pwd'), btn('Two', 'true')])['ok'], 'edited')
    eq(press('Go', 'rig')['lines'], [str(tmp)], 'in its working directory')
    with live('T4'):
        r = press('Two', 'rig')
        eq(r['busy']['holder'], 'T4', 'a task has it')
        check(press('Two', 'rig', holder=r['busy']['key'])['ok'], 'confirmed')
    (D._folder('held') / 'rig').write_text(json.dumps({'root': str(tmp / 'other'), 'tid': 'T9', 'at': 1}))
    with live('T9'):
        r = press('Two', 'rig')
        eq(r['busy']['holder'], 'a task of other', 'one of another project')
    (D._folder('held') / 'rig').write_text(json.dumps({'root': str(tmp / 'other'), 'tid': 'T8', 'at': 1}))
    with live('T8'):
        check(press('Two', 'rig', holder=r['busy']['key']).get('busy'), "that project's next task asks again")
    check(op('save', 'rig', edit='rig', **save, buttons=[])['ok'] and 'buttons' not in shown('rig'), 'taken out')
    op('remove', 'rig')


def test_rules() -> None:
    print('refused over http, without the token, from another page')
    toml(btn('Go', 'touch pressed'))
    srv = W.serve('tok', 0, '127.0.0.1')
    port = srv.server_address[1]
    origin = f'http://127.0.0.1:{port}'
    done = T.S.C.root / 'pressed'

    def post(path: str, **h) -> int:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        c.request('POST', path, body=json.dumps({'op': 'press', 'name': 'phone', 'button': 'Go'}),
                  headers={'Content-Type': 'application/json', **{k.replace('_', '-'): v for k, v in h.items()}})
        return c.getresponse().status
    try:
        for path, h in (('/tools', dict(Origin=origin)), ('/tools?t=tok', dict(Origin='http://evil.example')), ('/tools?t=tok', {}),
                        ('/tools?t=tok', dict(Origin=origin, X_Forwarded_For='8.8.8.8')),
                        ('/tools?t=tok', dict(Host='box:80', Origin='http://box:80'))):
            eq((post(path, **h), done.exists()), (403, False), f'refused: {path} {h}')
        eq((post('/tools?t=tok', Origin=origin), done.exists()), (200, True), 'the page may')
    finally:
        srv.stop()


def main() -> int:
    if os.name == 'nt':
        print('skipped: the commands are POSIX shell')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        repo = tmp / 'proj'
        (repo / 'plan').mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py | needs: phone\n'
                                           '- [ ] **T2** x | files: b.py | needs: phone\n- [ ] **T3** x | files: c.py\n'
                                           '- [ ] **T4** x | files: d.py | needs: rig\n', encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text(BASE, encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        return report([test_config, test_run, test_secret, test_timeout, test_once, test_busy, lambda: test_device(tmp), test_rules])


if __name__ == '__main__':
    sys.exit(main())
