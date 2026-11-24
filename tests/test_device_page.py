#!/usr/bin/env python3
"""F407: a device's web page and its start command: the address, start once, stop, failed, restart, removal.

    python3 tests/test_device_page.py        (a temp repo, real processes; about 20 seconds)
"""
from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _check import ROOT, check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import device_page as DP, devices as D, plat, runner as R, shared_tools as T, web as W  # noqa: E402

PW = 'sentinel-page-pw'
BASE = dict(kind='other', reach='git status')
URL = 'http://127.0.0.1:8123/remote'
PY = plat.quote(sys.executable)


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** x | files: a.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def op(op_: str, **a) -> dict:
    return D.post(json.dumps({'op': op_, **a}).encode(), T.S.C)[1]


def cmd(*a: str) -> tuple[int, str, str]:
    r = subprocess.run([sys.executable, str(ROOT / 'run'), 'device', *a], cwd=str(T.S.C.root), capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout, r.stderr


def wait(f, secs: float = 10):
    end = time.monotonic() + secs
    while not (got := f()) and time.monotonic() < end:
        time.sleep(0.05)
    return got


def state(name: str = 'rig') -> str:
    return D.page_state(D.load()['devices'][name])['state']


def folder(name: str = 'rig') -> Path:
    return D._page_dir(D.load()['devices'][name])


def pid_of(name: str = 'rig') -> int:
    return json.loads((folder(name) / 'run.json').read_text())['pid']


def test_address() -> None:
    print('only http and https addresses, on one line, with no sign-in')
    for bad in ('javascript:alert(1)', 'JavaScript://x/%0aalert(1)', 'data:text/html,x', 'file:///etc/passwd', 'http:', 'http://',
                'http:x', 'ftp://x', '//x', 'x.local', 'http://a b', 'http://a"onclick=x', 'http://x\n.y', 'java\nscript:x',
                'http://u:pw@x/', 'http://x:99999', 'http://x:y', 'http://[x', 'http://' + 'x' * 2001):
        r = op('save', name='rig', **BASE, page=bad)
        check(not r['ok'] and (bad in ('http:', 'http://') or bad not in r['out']), f'refused: {bad[:40]!r}', r)
    check(not op('save', name='rig', **BASE, start='true')['ok'], 'a command with no page')
    for k, bad in (('start', 'a\nb'), ('start', 'x' * 1001), ('folder', 'relative'), ('folder', '/x\0')):
        check(not op('save', name='rig', **BASE, page=URL, **{'start': 'true', k: bad})['ok'], f'refused: {k} {bad[:20]!r}')
    eq(D.load()['devices'], {}, 'nothing was saved')
    for good in ('http://x', 'HTTPS://box.ts.net:8443/a?b=c#d', 'http://[::1]:80/'):
        check(op('save', name='rig', **BASE, page=good)['ok'], f'taken: {good}')
        op('remove', name='rig')


def test_page_only() -> None:
    print('a page with no start command has no start, stop or state; nor has an SSH device')
    op('save', name='rig', **BASE, page=URL, folder='/ignored')
    dev = D.load()['devices']['rig']
    eq((dev['page'], 'folder' in dev, D.page_state(dev)), (URL, False, None), 'the address alone')
    for o in ('start', 'stop'):
        r = op(o, name='rig')
        check(not r['ok'] and 'no start command' in r['out'], o, r)
        check(cmd(o, 'rig')[0] == 1, f'run device {o}')
    check(f'web page {URL}\n' in cmd('list')[1], 'list has the address')
    check(op('save', edit='rig', kind='ssh', host='h')['ok'] and 'page' not in D.load()['devices']['rig'], 'an SSH device has none')
    op('remove', name='rig')


def test_run(tmp: Path) -> None:
    print('start once, from a process that ends; every later process sees it run; stop ends its whole group and no more')
    work = tmp / 'work dir'
    work.mkdir()
    code = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(600)"]); time.sleep(600)'
    start = f'echo started >> log; env > env; {PY} -c {plat.quote(code)} & wait'
    r = op('save', name='rig', **BASE, page=URL, start=start, folder=str(work))
    check(r['ok'], 'saved', r)
    eq(state(), 'stopped', 'at first')
    other = subprocess.Popen(['sleep', '600'], start_new_session=True)
    os.environ['AGENT_RUNNER_SLOT'], os.environ['CLAUDECODE'] = '3', '1'
    try:
        rc, o, e = cmd('start', 'rig')
    finally:
        del os.environ['AGENT_RUNNER_SLOT'], os.environ['CLAUDECODE']
    try:
        check(rc == 0 and URL in o, 'the command starts it', (rc, o, e))
        eq(state(), 'running', 'the process that started it is gone, and it runs')
        pid = pid_of()
        check(os.getsid(pid) == pid, 'detached')
        group = lambda: [l.split()[0] for l in subprocess.run(['ps', '-A', '-o', 'pid=,pgid='], capture_output=True, text=True)  # noqa: E731
                         .stdout.splitlines() if l.split()[1] == str(pid)]
        check(wait(lambda: len(group()) >= 3), 'shell, command and its child', group())
        for r in (op('start', name='rig'), dict(ok=True, out=cmd('start', 'rig')[1])):
            check(r['ok'] and 'running' in r['out'], 'a second start says so', r)
        eq((pid_of(), (work / 'log').read_text()), (pid, 'started\n'), 'and starts nothing, in its own folder')
        env = (work / 'env').read_text()
        check('AGENT_RUNNER_SLOT' not in env and 'CLAUDECODE' not in env, "no session's markers in its environment")
        check(f'web page {URL} (running)' in cmd('list')[1] and f'Web page: {URL} (running)' in cmd('show', 'rig')[1], 'list, show')
        eq(next(t for t in D.page(T.S.C)['tools'] if t['name'] == 'rig')['run'], {'state': 'running', 'lines': []}, 'GET /tools')
        check(op('save', edit='rig', name='rig2', **BASE, page=URL + '2', start=start, folder=str(work))['ok'], 'renamed, another address')
        eq((state('rig2'), pid_of('rig2')), ('running', pid), 'it runs on')
        op('save', edit='rig2', name='rig', **BASE, page=URL, start=start, folder=str(work))
        rc, o, e = cmd('stop', 'rig')
        check(rc == 0 and 'stopped' in o, 'stopped', (rc, o, e))
        eq((state(), group(), other.poll()), ('stopped', [], None), 'its whole group is gone, and nothing else')
        check(op('stop', name='rig')['ok'] and 'not running' in op('stop', name='rig')['out'], 'a second stop')
        check(op('start', name='rig')['ok'] and state() == 'running', 'it starts again')
    finally:
        other.kill()
        other.wait()
        op('remove', name='rig')


def test_once() -> None:
    print('starts at the same time start one; a command that ignores the polite end is killed')
    op('save', name='rig', **BASE, page=URL, start="trap '' TERM; while :; do sleep 0.2; done")
    ps = [subprocess.Popen([sys.executable, str(ROOT / 'run'), 'device', 'start', 'rig'], cwd=str(T.S.C.root),
                           stdout=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [p.communicate(timeout=60)[0] for p in ps]
    eq([p.returncode for p in ps], [0] * 3, 'all say it runs')
    eq(sum('already' in o for o in outs), 2, 'two of them already')
    pid = pid_of()
    check(op('stop', name='rig')['ok'] and not DP._group(pid), 'ended')
    op('remove', name='rig')


def test_ends() -> None:
    print('a command that ends at once: failed, with its last lines and no stored secret in them')
    op('save', name='mini', kind='ssh', host='127.0.0.1', user='me')
    op('secret', name='mini', what='password', password=PW)
    split = PW[:5] + '\\033[1m' + PW[5:]
    op('save', name='rig', **BASE, page=URL, start=f"for i in $(seq 40); do echo line $i; done; echo pw {PW}; printf 'x {split} y\\n'; exit 3")
    r = op('start', name='rig')
    check(not r['ok'] and r['state'] == 'failed' and 'ended at once' in r['out'], 'failed', r)
    check(len(r['lines']) == D.PAGE_LINES and r['lines'][-3:] == ['line 40', f'pw {D.HIDDEN}', f'x {D.HIDDEN} y'], 'its last lines', r['lines'])
    rc, o, e = cmd('start', 'rig')
    check(rc == 1 and f'pw {D.HIDDEN}' in e, 'the command says so too', e)
    rc, o2, _ = cmd('show', 'rig')
    check('(failed)' in o2 and 'line 40' in o2, 'and show', o2)
    run = [t['run'] for t in D.page(T.S.C)['tools'] if t['name'] == 'rig']
    check(PW not in o + e + o2 + json.dumps([r, run]), 'the secret is in none')
    (D.state_dir() / 'secrets/mini.password').rename(D.state_dir() / 'kept')
    D._LINES.clear()
    lines = D.page_state(D.load()['devices']['rig'])['lines']
    check(len(lines) == 1 and 'not shown' in lines[0], 'a secret that cannot be read: no output', lines)
    (D.state_dir() / 'kept').rename(D.state_dir() / 'secrets/mini.password')
    op('remove', name='mini')
    eq((op('stop', name='rig')['ok'], state()), (True, 'failed'), 'a stop of what failed changes nothing')
    op('save', edit='rig', **BASE, page=URL, start='true')
    r = op('start', name='rig')
    check(not r['ok'] and r['state'] == 'stopped', 'one that ends well is stopped, and said', r)
    with tempfile.TemporaryDirectory() as t:
        op('save', edit='rig', **BASE, page=URL, start='sleep 600', folder=t)
    r = op('start', name='rig')
    check(not r['ok'] and r['state'] == 'failed' and r['lines'], 'its folder is gone', r)
    op('remove', name='rig')


def test_edit_remove(tmp: Path) -> None:
    print('Remove, another command, another folder or another kind stop it first; a refused save does not')
    save = dict(**BASE, page=URL, start='sleep 600')

    def up() -> tuple[int, Path]:
        check(op('start', name='rig')['ok'], 'started')
        return pid_of(), folder()
    op('save', name='rig', **save)
    pid, d = up()
    for bad in (dict(page='javascript:x'), dict(start='sleep 601', name='-x'), dict(start='a\nb')):
        check(not op('save', edit='rig', **{**save, **bad})['ok'] and state() == 'running', f'refused: {bad}')
    r = op('save', edit='rig', **{**save, 'start': 'sleep 602'})
    check(r['ok'] and 'stopped' in r['out'] and not DP._group(pid) and not d.exists() and state() == 'stopped', 'another command', r)
    for more in (dict(start='sleep 602', folder=str(tmp)), dict(start=''), None):
        pid, d = up()
        r = op('save', edit='rig', **{**save, **more}) if more else op('remove', name='rig')
        check(r['ok'] and not DP._group(pid) and not d.exists(), f'{more or "removed"}', r)
        if more and not more['start']:
            op('save', edit='rig', **save)
    eq(D.load()['devices'], {}, 'gone')
    op('save', name='rig', **save)
    pid, d = up()
    op('save', edit='rig', kind='ssh', host='h')
    check(not DP._group(pid) and not d.exists(), 'an SSH device now')
    op('remove', name='rig')
    eq(list((D.state_dir() / 'pages').iterdir()), [], 'nothing left')


def test_killed() -> None:
    print('the keeper killed: its command is still known and ended; a reused pid is never touched')
    if plat.started(os.getpid()) is None:
        print('  (this OS does not say when a process started: skipped)')
        return
    op('save', name='rig', **BASE, page=URL, start='sleep 600')
    op('start', name='rig')
    pid = pid_of()
    keeper = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
    check(keeper not in (1, os.getpid()), 'the keeper is its parent')
    os.kill(keeper, signal.SIGKILL)
    check(wait(lambda: not plat.alive(keeper)), 'killed')
    eq(state(), 'running', 'the command is not lost')
    check('already' in op('start', name='rig')['out'] and pid_of() == pid, 'nor started twice')
    rec = json.loads((folder() / 'run.json').read_text())
    for wrong in (dict(start='1'), dict(boot='another')):
        DP._write(folder(), {**rec, **wrong})
        check(state() != 'running' and op('stop', name='rig')['ok'] and plat.alive(pid), f'not the same process: left alone ({wrong})')
    DP._write(folder(), rec)
    check(op('stop', name='rig')['ok'] and wait(lambda: not DP._group(pid)) and state() == 'stopped', 'stopped by its proven pid')
    op('save', edit='rig', **BASE, page=URL, start='sleep 600 & wait')
    op('start', name='rig')
    pid = pid_of()
    keeper = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])
    for p in (keeper, pid):
        os.kill(p, signal.SIGKILL)
        wait(lambda: not plat.alive(p))
    check(state() == 'running' and 'already' in op('start', name='rig')['out'], 'the shell killed too: what it started is known')
    rec = json.loads((folder() / 'run.json').read_text())
    DP._write(folder(), {**rec, 'mark': 'another'})
    check(state() != 'running' and op('stop', name='rig')['ok'] and DP._group(pid), 'another group with that id is left alone')
    DP._write(folder(), rec)
    check(op('stop', name='rig')['ok'] and wait(lambda: not DP._group(pid)), 'and ended')
    op('remove', name='rig')


def test_log(tmp: Path) -> None:
    print('the output kept is bounded')
    f = tmp / 'biglog'
    f.write_bytes(b'a line\n' * (DP.LOG_MAX // 7 + 1) + b'last\n')
    DP._trim(f)
    check(0 < f.stat().st_size <= DP.LOG_KEEP and f.read_bytes().startswith(b'a line\n') and f.read_bytes().endswith(b'line\nlast\n'), 'trimmed, whole lines')


def test_rules() -> None:
    print('start and stop follow the rules of every Tools page change')
    import http.client
    op('save', name='rig', **BASE, page=URL, start='sleep 600')
    srv = W.serve('tok', 0, '127.0.0.1')
    port = srv.server_address[1]
    origin = f'http://127.0.0.1:{port}'

    def post(path: str, **h) -> int:
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        c.request('POST', path, body=json.dumps({'op': 'start', 'name': 'rig', 'start': 'touch /x', 'page': 'http://x'}),
                  headers={'Content-Type': 'application/json', **{k.replace('_', '-'): v for k, v in h.items()}})
        return c.getresponse().status
    try:
        for path, h in (('/tools', dict(Origin=origin)), ('/tools?t=tok', dict(Origin='http://evil.example')), ('/tools?t=tok', {}),
                        ('/tools?t=tok', dict(Origin=origin, X_Forwarded_For='8.8.8.8'))):
            eq((post(path, **h), state()), (403, 'stopped'), f'refused: {path} {h}')
        eq((post('/tools?t=tok', Origin=origin), state()), (200, 'running'), 'the page may')
        eq(json.loads((folder() / 'run.json').read_text())['cmd'], 'sleep 600', 'the saved command, not one in the request')
    finally:
        srv.stop()
        op('remove', name='rig')


def main() -> int:
    if os.name == 'nt':
        print('skipped: process groups are POSIX')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        R.init(make_repo(tmp))
        try:
            return report([test_address, test_page_only, lambda: test_run(tmp), test_once, test_ends,
                           lambda: test_edit_remove(tmp), test_killed, lambda: test_log(tmp), test_rules])
        finally:
            for n in list(D.load()['devices']):  # a failed check leaves no process behind
                with contextlib.suppress(Exception):
                    op('remove', name=n)


if __name__ == '__main__':
    sys.exit(main())
