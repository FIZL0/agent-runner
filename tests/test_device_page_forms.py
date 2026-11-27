#!/usr/bin/env python3
"""F466b: the Tools page's three Add forms: SSH machine, Login (write-only, refused over plain http from another
host) and Custom tool (its description queues a task that turns it into a tool entry).

    python3 tests/test_device_page_forms.py
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
from pathlib import Path

from _check import ROOT, check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import config as CF, devices as D, runner as R, secret_logins as L, tool_forms as F  # noqa: E402
from agent_runner import web as W  # noqa: E402

PW = 'sentinel-form-pw-31c7'
C = None


def op(op_: str, **a) -> dict:
    return D.post(json.dumps({'op': op_, **a}).encode(), C)[1]


def request(port: int, body: dict, **headers) -> tuple[int, str]:
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    c.request('POST', f'/tools?t=tok', body=json.dumps(body), headers={k.replace('_', '-'): v for k, v in headers.items()})
    r = c.getresponse()
    return r.status, r.read().decode()


def test_ssh() -> None:
    print('SSH machine: the device form as before')
    got = op('save', name='mini', kind='ssh', host='mini.local', user='me', port='22', description='the mini')
    check(got['ok'], 'saved', got)
    dev = D.load()['devices']['mini']
    eq((dev['kind'], dev['host'], dev['user']), ('ssh', 'mini.local', 'me'), 'an SSH device')


def test_login() -> None:
    print('Login: saved write-only, shown as set and its date, replaced and removed')
    got = op('login_save', name='apple-id', purpose='Xcode signing', user='me@example.com', password=PW,
             twofa='the iPhone', projects='proj, other')
    check(got['ok'], 'saved', got)
    check(PW not in json.dumps(got), 'the answer holds no password')
    page = D.page(C)
    lg = next(x for x in page['logins'] if x['name'] == 'apple-id')
    eq((lg['set'], lg['changed'], lg['projects'], lg['user']), (True, D.today(), ['proj', 'other'], 'me@example.com'),
       'the card: set, its date')
    check(PW not in json.dumps(page), 'the page holds no password')
    check('host' not in lg and 'port' not in lg, 'no ssh fields')
    eq(L.password('apple-id', L.get('apple-id'), 'proj'), PW, 'kept for `login use`')
    check(not op('login_save', name='new-one', password='')['ok'], 'a new login needs a password')
    check(op('login_save', name='apple-id', purpose='other words', password='')['ok'], 'replace keeps the password')
    eq(L.password('apple-id', L.get('apple-id'), 'proj'), PW, 'still the old password')
    check(op('login_remove', name='apple-id')['ok'], 'removed')
    check('apple-id' not in L.load(), 'gone')
    check(not (D.state_dir() / 'secrets' / 'login-apple-id.password').exists(), 'its password too')


def test_custom() -> None:
    print('Custom tool: another way, and Describe it queues a task')
    queued = []
    was, F.QUEUE = F.QUEUE, lambda c, text: queued.append(text) or 'F99'
    try:
        got = op('custom', name='rig', reach='vnc://rig.local:5900', description='the rig', describe='')
        check(got['ok'] and not queued, 'no description: the device alone', got)
        eq(D.load()['devices']['rig']['kind'], 'other', 'reached another way')
        got = op('custom', name='rig2', reach='http://rig2.local', describe='A test rig; agents press Reset first.')
        check(got['ok'] and got['task'] == 'F99', 'a description queues a task', got)
        check(len(queued) == 1 and 'agents press Reset first' in queued[0] and 'approve' in queued[0]
              and '| files: runner.toml' in queued[0] and 'needs: rig2' in queued[0], 'its text', queued)
    finally:
        F.QUEUE = was
    tid = F.add_task(C, F.task_text('rig3', 'a rig'))
    check(tid.startswith('F'), f'queued in the project for real: {tid}')
    check(f'**{tid}**' in (Path(C.root) / 'plan/TODO.md').read_text(), 'in its plan')


def test_http_refused() -> None:
    print('a Login over plain http from another host is refused')
    eq(D.channel('100.64.0.5', {'Host': 'box:8080', 'Origin': 'http://box:8080'}), 'http', 'another host, no https')
    srv = W.serve('tok', 0, '127.0.0.1')
    port = srv.server_address[1]
    try:
        body = {'op': 'login_save', 'name': 'leak', 'password': PW}
        code, out = request(port, body, Origin=f'http://127.0.0.1:{port}', Content_Type='application/json',
                            X_Forwarded_For='100.64.0.5')
        eq(code, 403, 'refused')
        check(PW not in out and 'leak' not in L.load(), 'nothing saved, nothing echoed')
        code, out = request(port, body, Origin=f'http://127.0.0.1:{port}', Content_Type='application/json')
        eq((code, json.loads(out)['ok']), (200, True), 'on the machine itself it is saved')
    finally:
        srv.shutdown()


def test_page_parts() -> None:
    print('the page has the three forms')
    js = (ROOT / 'agent_runner/page/131-tool-forms.js').read_text(encoding='utf-8')
    for w in ('SSH machine', 'Login', 'Custom tool', 'Describe it', "op:'login_save'", "op:'custom'"):
        check(w in js, w)
    check('value=' not in js.split('SHEETS.devlogin')[1].split('function loginCard')[0], 'no saved value in the sheet')


def main() -> int:
    global C
    if os.name == 'nt':
        print('skipped: a stored secret is not used on Windows')
        return 0
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        os.environ['AGENT_RUNNER_SSH_CONFIG'] = str(tmp / 'none')
        repo = tmp / 'proj'
        (repo / 'plan').mkdir(parents=True)
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py\n', encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\n', encoding='utf-8')
        (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        C = CF.cfg(repo)
        return report([test_ssh, test_login, test_custom, test_http_refused, test_page_parts])


if __name__ == '__main__':
    sys.exit(main())
