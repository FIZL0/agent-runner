#!/usr/bin/env python3
"""F169: devices on the Tools page: secrets that go in and never come out, and the agents' command.

    python3 tests/test_devices.py        (a temp repo, a fake ssh, real ssh-agent and ssh-keygen; a few seconds)
"""
from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _check import ROOT, check, eq, git, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import devices as D, home as H, plan as P, runner as R, sched, shared_tools as T, ui_model as U  # noqa: E402
from agent_runner import brief, config as CF, web as W  # noqa: E402

CF.FIXED['merge_ahead'] = False
PW, PHRASE = 'sentinel-pw $(x) "q"', 'sentinel-phrase-77'
POSIX = os.name != 'nt'
TODO = ('# TODO\n\n### Next\n\n- [ ] **T1** on the mini | files: a.py | needs: mini\n'
        '- [ ] **T2** also | files: b.py | needs: mini\n- [ ] **T3** none | files: c.py\n')

FAKE = '''#!{py}
import os, subprocess, sys, json, pathlib
a, env = sys.argv[1:], dict(os.environ)
opts = dict(x.split('=', 1) for i, x in enumerate(a) if i and a[i-1] == '-o')
with open({log!r}, 'a') as f: f.write(json.dumps([sys.argv, env]) + '\\n')
key = open({hostkey!r}).read().split()
kh = opts['UserKnownHostsFile']
if opts['StrictHostKeyChecking'] == 'accept-new':
    open(kh, 'w').write(opts['HostKeyAlias'] + ' ' + ' '.join(key[:2]) + '\\n'); sys.exit(255)
if open(kh).read().split()[1:] != key[:2]:
    sys.stderr.write('Host key verification failed.\\n'); sys.exit(255)
ask = lambda p: subprocess.run([env['SSH_ASKPASS'], p], capture_output=True, text=True)
got = []
if opts.get('IdentityAgent', 'none') != 'none':
    r = subprocess.run(['ssh-add', '-L'], capture_output=True, text=True, env=dict(env, SSH_AUTH_SOCK=opts['IdentityAgent']))
    got.append(r.stdout.split()[1])
if 'BatchMode' not in opts:
    got += [ask('Enter passphrase for key').stdout, ask("me@host's password: ").stdout.rstrip('\\n'), ask('password again').stdout]
with open({out!r}, 'w') as f: json.dump(got, f)
if a[-1] == 'echo-it': print('pw is', got[-2], flush=True)
elif a[-1] == 'env': print(json.dumps(env))
else: print('ran', a[-1])
sys.exit(int(env.get('FAKE_RC', '0')))
'''


MADE: list[Path] = []  # every temp folder devices made in this process
REAL_TMP = D._tmp


@contextlib.contextmanager
def recorded_tmp():
    with REAL_TMP() as d:
        MADE.append(d)
        yield d


def make_repo(tmp: Path, name: str) -> Path:
    repo = tmp / name
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n[run.tools.phone]\n'
                                      'check = "true"\ndescription = "the test phone"\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def op(op_: str, **a) -> dict:
    return D.post(json.dumps({'op': op_, **a}).encode(), T.S.C)[1]


def key_of(tmp: Path, phrase: str = '') -> str:
    f = tmp / f'k{time.monotonic_ns()}'
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', phrase, '-C', '', '-f', str(f)], check=True)
    return f.read_text()


def request(port: int, method: str, path: str, body=None, peer: str = '127.0.0.1', **headers) -> tuple[int, str]:
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
    c.request(method, path, body=json.dumps(body) if body is not None else None,
              headers={k.replace('_', '-'): v for k, v in headers.items()})
    r = c.getresponse()
    return r.status, r.read().decode()


def raw(port: int, path: str, body: dict) -> str:
    """Everything a kept connection answers to a POST with no origin."""
    b = json.dumps(body).encode()
    with socket.create_connection(('127.0.0.1', port), timeout=5) as s:
        s.sendall(f'POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(b)}\r\n\r\n'.encode() + b)
        got = b''
        with contextlib.suppress(OSError):
            while d := s.recv(4096):
                got += d
    return got.decode()


def cmd(*a: str) -> tuple[int, str, str]:
    """The agents' command as a process, as an agent runs it."""
    r = subprocess.run([sys.executable, str(ROOT / 'run'), 'device', *a], cwd=str(T.S.C.root), capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    return r.returncode, r.stdout, r.stderr


def test_hostile() -> None:
    print('hostile names, hosts, users and ports are refused, and none is echoed')
    base = {'kind': 'ssh', 'host': 'h', 'user': 'u', 'port': '22'}
    for bad in ('-oProxyCommand=x', 'a b', 'a\nb', 'a;b', '$(x)', '../x', 'a/b', '', 'x' * 41, 5, None, 'memory', 'phone'):
        r = op('save', **{**base, 'name': bad})
        check(not r['ok'] and '$(x)' not in r['out'], f'name {bad!r}', r)
    for f, bads in (('host', ('-oProxyCommand=x', 'a b', 'a\n', 'a;b', '$(x)', '', 'u@h', 'ssh://h', '`x`')),
                    ('user', ('-l', 'a b', 'a\n', 'a;b', '$(x)', 'a@b')), ('port', ('0', '65536', '-1', '2 2', 'x', '22\n'))):
        for bad in bads:
            check(not op('save', **{**base, 'name': 'ok', f: bad})['ok'], f'{f} {bad!r}')
    check(not op('save', name='ok', kind='ssh', alias='-x')['ok'], 'an alias not in ~/.ssh/config')
    check(not op('save', name='ok', kind='telnet')['ok'], 'another kind')
    check(not op('save', name='ok', kind='other', reach='')['ok'], 'no way to reach it')
    eq(D.load()['devices'], {}, 'nothing was saved')
    eq(D.post(b'{"op":"secret"', T.S.C)[0], 400, 'a broken body')
    eq(D.post(b'[1]', T.S.C)[1]['out'], 'bad request', 'a list')
    eq(D.post(b'{"op":"nope"}', T.S.C)[0], 400, 'an unknown op')


def test_secrets(tmp: Path) -> None:
    print('secrets: kept 0600 in 0700, replaced, removed; a wrong passphrase and a public key are refused')
    eq(op('save', name='mini', kind='ssh', host='127.0.0.1', user='me', port='22', exclusive=True,
          description='A Mac mini.\nBuilds only.')['ok'], True, 'added')
    eq(op('save', name='MINI', kind='ssh', host='h')['ok'], False, 'a second name that differs in case')
    key, locked = key_of(tmp), key_of(tmp, PHRASE)
    check(not op('secret', name='mini', what='key', key='ssh-ed25519 AAAA')['ok'], 'a public key')
    check(not op('secret', name='mini', what='key', key=locked)['ok'], 'a locked key without its passphrase')
    check(not op('secret', name='mini', what='key', key=locked, passphrase='wrong')['ok'], 'a wrong passphrase')
    r = op('secret', name='mini', what='key', key=locked.replace('\n', '\r\n'), passphrase=PHRASE)
    check(r['ok'], 'the right one', r)
    check(op('secret', name='mini', what='password', password=PW)['ok'], 'a password')
    check(not op('secret', name='mini', what='password', password='a\nb')['ok'], 'a password of two lines')
    s = D.load()['devices']['mini']['secrets']
    d = D.state_dir()
    for f in (d, d / 'secrets'):
        eq(stat.S_IMODE(f.stat().st_mode), 0o700, f'{f.name}: 0700')
    for f in [d / 'devices.json', *(d / 'secrets').iterdir()]:
        eq(stat.S_IMODE(f.stat().st_mode), 0o600, f'{f.name}: 0600')
    eq(sorted(f.name for f in (d / 'secrets').iterdir()), ['mini.key', 'mini.passphrase', 'mini.password'], 'one file each')
    check(PW not in (d / 'devices.json').read_text() and 'PRIVATE' not in (d / 'devices.json').read_text(),
          'none in devices.json')
    old = s['key']['fp']
    check(op('secret', name='mini', what='key', key=key)['ok'], 'replaced by a key with no passphrase')
    s = D.load()['devices']['mini']['secrets']
    check(s['key']['fp'] != old and 'passphrase' not in s and not (d / 'secrets/mini.passphrase').exists(),
          'its fingerprint and the old passphrase go')
    check(op('unsecret', name='mini', what='password')['ok'] and not (d / 'secrets/mini.password').exists(), 'removed')
    check(op('keypair', name='mini')['ok'], 'a key pair made here')
    s = D.load()['devices']['mini']['secrets']
    check(s['key']['pub'].startswith('ssh-ed25519 ') and s['key']['fp'].startswith('SHA256:'), 'its public key is shown')
    eq([f.name for f in d.iterdir() if f.name.startswith('.')], [], 'nothing left behind')
    base = dict(kind='ssh', host='127.0.0.1', user='me', port='22', exclusive=True)
    check(not op('save', edit='mini', name='-x', **base)['ok'], 'a bad new name')
    check(op('save', edit='mini', name='mini2', **base)['ok'] and T.S.C and 'mini2' in T.specs(), 'renamed, still used here')
    eq([f.name for f in (d / 'secrets').iterdir()], ['mini2.key'], 'its secrets with it')
    check(op('save', edit='mini2', name='mini', **base)['ok'], 'and back')
    for op_ in ('secret', 'keypair', 'unsecret'):
        check(not op(op_, name='nope', what='password', password='x')['ok'], f'{op_}: no such device')
    check(op('secret', name='mini', what='key', key=locked, passphrase=PHRASE)['ok']
          and op('secret', name='mini', what='password', password=PW)['ok'], 'set for what follows')


def test_folder(tmp: Path) -> None:
    print('never a repo, a worktree or a synced folder')
    (tmp / 'wt').mkdir()
    (tmp / 'wt/.git').write_text('gitdir: x')
    for p in (tmp / 'proj/x', tmp / 'wt/x', tmp / 'Dropbox/x', tmp / 'sync/x', tmp / 'OneDrive - Work/x'):
        check(D.unsafe_dir(p), f'refused: {p.name} in {p.parent.name}')
    keep = os.environ['AGENT_RUNNER_DEVICES']
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'proj/devs')
    try:
        check(not op('save', name='x', kind='ssh', host='h')['ok'] and not (tmp / 'proj/devs').exists(), 'nothing written there')
    finally:
        os.environ['AGENT_RUNNER_DEVICES'] = keep


def test_channel() -> None:
    print('https or loopback, the page itself, and nothing a remote peer can claim')
    h = {'Host': '127.0.0.1:5', 'Origin': 'http://127.0.0.1:5'}
    far = {'Host': 'box:8770', 'Origin': 'http://box:8770'}
    ts = {'Host': 'box.ts.net', 'Origin': 'https://box.ts.net', 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '1.2.3.4'}
    for want, peer, hd, kw in (('', '127.0.0.1', h, {}), ('', '::1', h, {}), ('http', '192.168.1.5', far, {}),
                               ('http', '192.168.1.5', {**far, **ts}, {}),
                               ('http', '192.168.1.5', {**far, D.CHANNEL: 'ok'}, {'behind': True}),
                               ('', '127.0.0.1', ts, {}), ('http', '127.0.0.1', {**ts, 'X-Forwarded-Proto': 'http'}, {}),
                               ('http', '127.0.0.1', {**h, 'X-Forwarded-For': '9.9.9.9'}, {}),
                               ('http', '127.0.0.1', far, {}),  # a name that points at this machine
                               ('origin', '127.0.0.1', {**h, 'Origin': 'http://evil.example'}, {}),
                               ('origin', '127.0.0.1', {**ts, 'Origin': 'http://box.ts.net'}, {}),
                               ('origin', '127.0.0.1', {'Host': h['Host']}, {}),
                               ('origin', '127.0.0.1', {**h, 'Sec-Fetch-Site': 'cross-site'}, {}),
                               ('', '127.0.0.1', {D.CHANNEL: 'ok'}, {'behind': True}),
                               ('http', '127.0.0.1', {D.CHANNEL: 'http', **h}, {'behind': True}),
                               ('http', '127.0.0.1', {D.CHANNEL: 'wat', **h}, {'behind': True}),
                               ('', '127.0.0.1', {D.CHANNEL: 'http', **h}, {})):  # Home takes no one's word
        eq(D.channel(peer, hd, **kw), want, f'{peer} {hd} {kw}')


def test_server() -> str:
    print('POST /tools: token, origin and channel; GET, snapshot and settings hold no secret')
    token = 'tok-e-n'
    srv = W.serve(token, 0, '127.0.0.1')
    port = srv.server_address[1]
    origin, ct = f'http://127.0.0.1:{port}', 'application/json'
    body = {'op': 'secret', 'name': 'mini', 'what': 'password', 'password': 'other-sentinel'}
    before = (D.state_dir() / 'secrets/mini.password').read_text()
    seen = []
    try:
        for want, path, hd in ((403, '/tools', {}), (403, '/tools?t=bad', {}),
                               (403, f'/tools?t={token}', {'Origin': 'http://evil.example'}), (403, f'/tools?t={token}', {'Origin': ''}),
                               (403, f'/tools?t={token}', {'X_Forwarded_For': '8.8.8.8'}),
                               (403, f'/tools?t={token}', {'Host': 'box:80', 'Origin': 'http://box:80'}),
                               (400, f'/tools?t={token}', {'Content_Type': 'text/plain'})):
            code, out = request(port, 'POST', path, body, **{'Origin': origin, 'Content_Type': ct, **hd})
            eq(code, want, f'{path} {hd}')
            seen.append(out)
        eq((D.state_dir() / 'secrets/mini.password').read_text(), before, 'none of them changed it')
        check(not any('other-sentinel' in x for x in seen), 'no refusal echoes it')
        code, out = request(port, 'POST', f'/tools?t={token}', {**body, 'password': PW}, Origin=origin, Content_Type=ct)
        eq((code, json.loads(out)['ok']), (200, True), 'the page itself may')
        for p in ('/tools', '/snapshot', '/settings', '/', '/commands'):
            code, out = request(port, 'GET', f'{p}?t={token}')
            eq(code, 200, p)
            seen.append(out)
        got = json.loads(seen[-5])
        mini = next(t for t in got['tools'] if t['name'] == 'mini')
        eq(sorted(mini['secrets']), ['key', 'passphrase', 'password'], 'what is set')
        check(set(mini['secrets']['password']) == {'changed'} and set(mini['secrets']['key']) == {'changed', 'fp', 'pub'},
              'only when, the fingerprint and the public key')
        check(got['secure'] and any(t['source'] == 'runner.toml' and t['description'] == 'the test phone' for t in got['tools']),
              "runner.toml's tools are on it, with their source")
        eq(json.loads(request(port, 'GET', f'/tools?t={token}', X_Forwarded_For='8.8.8.8')[1])['secure'], False, 'read only over http')
        for path in ('/tools', f'/tools?t={token}'):  # a refused body is never taken for the next request
            check('other-sentinel' not in (out := raw(port, path, body)) and out.count('HTTP/1.1') == 1, 'one answer', out)
        # through Runner Home
        hs = H.serve_home('home-tok', 0, '127.0.0.1', rows=lambda *a: [])
        hs.link, hs.project = (lambda root: (port, token)), (lambda key: T.S.C.root)
        hp = hs.server_address[1]
        try:
            for want, hd in ((200, {}), (403, {'Origin': 'http://evil.example'}), (403, {'X_Forwarded_For': '8.8.8.8'}),
                             (403, {'X_Forwarded_For': '8.8.8.8', 'X_Runner_Channel': 'ok'})):
                code, out = request(hp, 'POST', '/p/proj/tools?t=home-tok', {'op': 'use', 'name': 'mini', 'on': True},
                                    **{'Origin': f'http://127.0.0.1:{hp}', 'Content_Type': ct, **hd})
                eq(code, want, f'through Home {hd}')
            check('other-sentinel' not in (out := raw(hp, '/p/proj/tools', body)) and out.count('HTTP/1.1') == 1, 'Home: one answer', out)
            eq(request(hp, 'POST', '/p/proj/tools', body, Origin=f'http://127.0.0.1:{hp}', Content_Type=ct)[0], 403, 'no token')
        finally:
            hs.stop()
    finally:
        srv.stop()
    return '\n'.join(seen)


def test_connect(tmp: Path) -> str:
    print('the fake ssh gets the key from an agent and the password from askpass; output is redacted')
    fake, log, hostkey, out = tmp / 'bin', tmp / 'ssh.log', tmp / 'hostkey', tmp / 'got'
    fake.mkdir()
    for n in ('ssh', 'scp'):
        (fake / n).write_text(FAKE.format(py=sys.executable, log=str(log), hostkey=str(hostkey), out=str(out)))
        os.chmod(fake / n, 0o755)
    os.environ['PATH'] = f'{fake}{os.pathsep}{os.environ["PATH"]}'
    blob = key_of(tmp) and D.load()['devices']['mini']['secrets']['key']['pub'].split()
    hostkey.write_text(' '.join(blob))
    said = []
    rc, o, e = cmd('ssh', 'mini', '--', 'x')
    check(rc == 1 and 'not accepted yet' in e, 'no host key accepted: refused', e)
    r = op('test', name='mini')
    check(not r['ok'] and r['hostkey']['fp'] == D.fingerprint(blob[1]) and 'seen' not in r, 'the first fingerprint is shown', r)
    check(not op('accept', name='mini', fp='SHA256:other')['ok'], 'another fingerprint is not accepted')
    r = op('accept', name='mini', fp=r['hostkey']['fp'])
    check(r['ok'] and 'Connected' in r['out'], 'accepted, and it connects', r)
    rc, o, e = cmd('ssh', 'mini', '--', 'echo-it')
    said += [o, e]
    eq((rc, o.strip()), (0, f'pw is {D.HIDDEN}'), 'the password in the output is hidden')
    got = json.loads(out.read_text())
    eq(got[0], blob[1], 'the key is in its agent')
    eq(got[1:], ['', PW, ''], 'the password is given once, to a password prompt only')
    rc, o, e = cmd('ssh', 'mini', '--', 'a b', '$(x)', "it's")
    said += [o, e]
    eq(o.strip(), "ran 'a b' '$(x)' 'it'\"'\"'s'", 'several words go as they are')
    rc, o, e = cmd('ssh', 'mini', '--', '-oProxyCommand=x')
    argv = json.loads(log.read_text().splitlines()[-1])[0]
    eq(argv[-3:], ['--', '127.0.0.1', '-oProxyCommand=x'], 'the host and command are past --')
    rc, o, e = cmd('copy', str(tmp / '-f:x'), 'mini:/tmp/y')
    argv = json.loads(log.read_text().splitlines()[-1])[0]
    eq(argv[-3:], ['--', str(tmp / '-f:x'), '127.0.0.1:/tmp/y'], 'copy')
    eq(cmd('copy', 'a', 'b')[0], 2, 'a copy between two local files is refused')
    eq(cmd('ssh', 'nope', '--', 'x')[0], 2, 'an unknown device')
    rc, o, e = cmd('ssh', 'mini', '--', 'env')
    child = json.loads(o)
    check('SSH_ASKPASS' in child and PW not in o and PHRASE not in o, 'no secret in the child environment')
    said += [o, e]
    eq(cmd('ssh', 'mini', '--', 'x')[0], 0, 'its exit code')
    os.environ['FAKE_RC'] = '7'
    eq(cmd('ssh', 'mini', '--', 'x')[0], 7, 'and another')
    del os.environ['FAKE_RC']
    hostkey.write_text('ssh-ed25519 ' + D.base64.b64encode(b'another').decode())
    rc, o, e = cmd('ssh', 'mini', '--', 'x')
    check(rc == 255 and 'refused' in e and 'host key' in e, 'a changed host key is refused and said', e)
    r = op('test', name='mini')
    check(not r['ok'] and 'changed' in r['out'] and r['hostkey']['was'], 'the page says so, with both', r)
    hostkey.write_text(' '.join(blob))
    check(op('save', edit='mini', kind='ssh', host='127.0.0.1', user='me', port='23', exclusive=True, description='x')['ok']
          and 'hostkey' not in D.load()['devices']['mini'], 'a new place to connect to forgets the accepted key')
    op('save', edit='mini', kind='ssh', host='127.0.0.1', user='me', port='22', exclusive=True, description='A Mac mini.')
    op('accept', name='mini', fp=op('test', name='mini')['hostkey']['fp'])
    op('unsecret', name='mini', what='key')
    cmd('ssh', 'mini', '--', 'x')
    argv = json.loads(log.read_text().splitlines()[-1])[0]
    check('PubkeyAuthentication=no' in argv and 'IdentityFile' not in str(argv), 'a password alone')
    r = op('unsecret', name='mini', what='password')
    cmd('ssh', 'mini', '--', 'x')
    check('BatchMode=yes' in json.loads(log.read_text().splitlines()[-1])[0], 'with no secret nothing is asked')
    op('secret', name='mini', what='password', password=PW)
    cfg = tmp / 'ssh_config'
    cfg.write_text('Host box *.lan\n  User me\nHost=two\n')
    os.environ['AGENT_RUNNER_SSH_CONFIG'] = str(cfg)
    eq(D.aliases(), ['box', 'two'], "~/.ssh/config's hosts")
    check(op('save', name='lan', kind='ssh', alias='box')['ok'], 'picked by alias')
    check(not op('secret', name='lan', what='password', password='x')['ok'], 'it takes no secret')
    op('remove', name='lan')
    # only the folders this test made, as other runs on the machine have theirs in /tmp too: MADE has this process's,
    # and the fake ssh's arguments name its subprocesses'
    argvs = [json.loads(line)[0] for line in log.read_text().splitlines()]
    made = {*MADE, *(Path(a.split('=', 1)[1]).parent for argv in argvs for a in argv if a.startswith('UserKnownHostsFile='))}
    check(MADE and made - set(MADE) and all(p.name.startswith('ar-dev-') for p in made), 'the folders of both are known', made)
    left = [p for p in made if p.exists()]
    check(not left, 'nothing left in /tmp', left)
    return '\n'.join([*said, log.read_text(), json.dumps(op('test', name='mini'))])


def test_redactor() -> None:
    print('a secret cut across reads is hidden, and only it')
    for cut in range(1, 12):
        r, s = D.Redactor(['hunter2!', 'hunter', 'ter2!xx']), b'a hunter2! b hunterx'
        out = b''.join(r.feed(s[i:i + cut]) for i in range(0, len(s), cut)) + r.end()
        eq(out.decode(), f'a {D.HIDDEN} b {D.HIDDEN}x', f'cut every {cut}')
    eq(D.Redactor([]).all(b'x'), b'x', 'no secret, no change')
    key = '-----BEGIN X-----\n' + 'A' * 40 + '\n' + 'B' * 40 + '\n-----END X-----\n'
    check('B' * 40 not in D.Redactor([key]).all(b'line ' + b'B' * 40 + b'\n').decode(), "one line of a key's body")


def test_needs(repo: Path, other: Path, tmp: Path) -> None:
    print('a device works as a needs: name, one task at a time, across projects')
    for n in T.specs():
        T.READINGS.pop(n, None)
    keep, D.reach = D.reach, lambda dev: ('free', '')
    try:
        eq(sorted(T.specs()), ['mini', 'phone'], 'it is a shared tool here')
        eq(T.unknown_names(['mini']), '', 'needs: mini is taken')
        check(T.unknown_names(['mini'], CF.cfg(other)), 'not in a project that does not use it')
        T.start()
        try:
            T.STOP.set()
            for t in T.THREADS.values():
                t.join(5)
        finally:
            T.STOP.clear()
            T.THREADS.clear()
        T.READINGS.clear()
        eq(sched.pick({}, set(), 'main')[0], 'T1', 'free: T1 starts')
        t1 = next(t for t in sched.tasks('main') if t[0] == 'T1')
        eq(sched.pick({1: t1}, set(), 'main')[0], 'T3', 'beside it T2 waits')
        op('save', edit='mini', kind='ssh', host='127.0.0.1', user='me', port='22', exclusive=False)
        eq(sched.pick({1: t1}, set(), 'main')[0], 'T2', 'a device for several tasks holds none')
        op('save', edit='mini', kind='ssh', host='127.0.0.1', user='me', port='22', exclusive=True, description='A Mac mini.')
        D.reach = lambda dev: ('missing', 'nothing answers on its port')
        eq(T.check('mini'), ('missing', 'nothing answers on its port'), 'not reachable: missing')
        D.reach = lambda dev: ('free', '')
        with D._edit() as d:
            d['uses'][D.project(CF.cfg(other))] = ['mini']
        running, D._running = D._running, lambda root: {'1': 'T1'} if root == D.project(CF.cfg(other)) else {}
        try:
            eq(T.check('mini'), ('busy', 'a task of other'), "another project's task has it, its id not named")
        finally:
            D._running = running
        b = T.brief('run', 'T1')
        check('A Mac mini.' in b and 'device ssh mini' in b and 'the test phone' in b, 'the brief has name and description', b)
        check('needing mini' in b, 'and that this task needs it')
        op('use', name='mini', on=False)
        eq(sorted(T.specs()), ['phone'], 'not used: no shared tool')
        eq(cmd('ssh', 'mini', '--', 'x')[0], 2, 'and no agent reaches it from here')
        op('use', name='mini', on=True)
        eq(U.project_tools(), ['mini', 'phone'], 'the pages offer it')
    finally:
        D.reach = keep


def test_lease(repo: Path, tmp: Path) -> None:
    print('an agent that uses a one-task device has it until its task ends or it releases it')
    root = D.project(T.S.C)
    running, D._running = D._running, lambda r: {'1': 'T9', '2': 'T8'} if r == root else {}
    keep, os.environ['AGENT_RUNNER_SLOT'] = os.environ.get('AGENT_RUNNER_SLOT'), '1'
    from agent_runner import tools
    here, tools.task_here = tools.task_here, lambda *a: 'T9'
    dev = D.used(T.S.C)['mini']
    try:
        eq(D.take('mini', dev, T.S.C), '', 'T9 takes it')
        eq(T.check('mini'), ('busy', 'T9'), 'the check says so')
        check(not op('remove', name='mini')['ok'], 'and it is not removed under it')
        tools.task_here = lambda *a: 'T8'
        eq(D.take('mini', dev, T.S.C), 'T9', 'T8 does not get it')
        D._running = lambda r: {}
        eq(D.take('mini', dev, T.S.C), '', 'once T9 ended it does')
    finally:
        D._running, tools.task_here = running, here
        os.environ.pop('AGENT_RUNNER_SLOT', None)
        if keep is not None:
            os.environ['AGENT_RUNNER_SLOT'] = keep


def test_keyring(tmp: Path) -> None:
    print('the keyring when an unattended run can read it, else a file')
    b = tmp / 'ring'
    b.mkdir()
    (b / 'busctl').write_text(f'#!/bin/sh\ncat {tmp}/lockstate\n')
    (b / 'secret-tool').write_text(f'''#!{sys.executable}
import sys, pathlib
f = pathlib.Path({str(tmp)!r}, 'ring-' + sys.argv[-1].replace('/', '_'))
open({str(tmp / 'ring.log')!r}, 'a').write(repr(sys.argv))
w = sys.argv[1]
if w == 'store': f.write_text(sys.stdin.read())
elif w == 'lookup': sys.exit(1) if not f.exists() else print(f.read_text(), end='')
else: f.unlink(missing_ok=True)
''')
    for f in b.iterdir():
        os.chmod(f, 0o755)
    path, user = os.environ['PATH'], os.environ.get('USER')
    os.environ['PATH'] = f'{b}{os.pathsep}{path}'
    os.environ['USER'] = 'no-such-user-f169'
    del os.environ['AGENT_RUNNER_KEYRING']
    try:
        (tmp / 'lockstate').write_text('b true\n')
        eq(D.keyring(), '', 'locked: a file')
        (tmp / 'lockstate').write_text('b false\n')
        eq(D.keyring(), 'secret-tool', 'open and readable: the keyring')
        op('secret', name='mini', what='password', password=PW)
        dev = D.load()['devices']['mini']
        eq(dev['secrets']['password']['store'], 'secret-tool', 'kept there')
        check(not (D.state_dir() / 'secrets/mini.password').exists(), 'and the file is gone')
        eq(D._secret('mini', 'password', dev), PW, 'a connection reads it')
        check(PW not in (tmp / 'ring.log').read_text(), 'never in the argv')
        (tmp / 'lockstate').write_text('b true\n')
        try:
            D._secret('mini', 'password', dev)
            check(False, 'a locked keyring is said')
        except D.Refused as e:
            check('locked' in str(e), 'a locked keyring is said', str(e))
        (tmp / 'lockstate').write_text('b false\n')
    finally:
        os.environ['AGENT_RUNNER_KEYRING'] = 'off'
    op('secret', name='mini', what='password', password=PW)
    check(not (tmp / 'ring-agent-runner_mini_password').exists(), 'back in a file, it is gone from the keyring')
    os.environ['PATH'] = path
    os.environ.pop('USER')
    if user:
        os.environ['USER'] = user


def test_nowhere(seen: str, repo: Path) -> None:
    print('the sentinel is nowhere but its own file')
    from agent_runner import page_copy, status
    seen += page_copy.page_copy_html({**U.snapshot(up=False, links={}, terminal_base='.')})
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        for a in (['list'], ['show', 'mini']):
            D.cmd_device(a)
    r = subprocess.run([sys.executable, str(ROOT / 'run'), 'status'], cwd=str(repo), capture_output=True, text=True, timeout=60)
    seen += out.getvalue() + r.stdout + r.stderr + json.dumps(D.page(T.S.C), default=str) + T.brief('run', 'T1')
    key = [l for l in (D.state_dir() / 'secrets/mini.password').read_text().splitlines()]
    for s in (PW, PHRASE, 'other-sentinel', 'PRIVATE KEY', *key):
        check(s not in seen.replace("from BEGIN to END", ''), f'not in any answer, page, argv, environment or error: {s[:14]}…')
    hits = [str(f) for f in repo.rglob('*') if f.is_file() and (PW.encode() in (b := f.read_bytes()) or PHRASE.encode() in b)]
    eq(hits, [], 'nor anywhere in the project, its log, plan and feed')
    eq(op('remove', name='mini')['ok'], True, 'removed')
    eq(list((D.state_dir() / 'secrets').iterdir()), [], 'its secrets with it')
    eq(D.load(), {'devices': {}, 'uses': {}}, 'and its uses')


def test_other_kind() -> None:
    print('a device reached another way')
    eq(op('save', name='rig', kind='other', reach='vnc://127.0.0.1:1')['ok'], True, 'added')
    eq(D.reach({'kind': 'other', 'reach': 'vnc://127.0.0.1:1'})[0], 'missing', 'its port is checked')
    eq(D.reach({'kind': 'other', 'reach': 'git status'})[0], 'free', 'a command on this machine')
    eq(D.reach({'kind': 'other', 'reach': 'no-such-cmd-f169 -x'})[0], 'missing', 'one that is not')
    eq(D.reach({'kind': 'other', 'reach': "it's broken"})[0], 'unknown', 'one that does not read')
    check('vnc://127.0.0.1:1' in T.brief('run'), 'the brief says how')
    check(not op('secret', name='rig', what='password', password='x')['ok'], 'it takes no secret')
    op('remove', name='rig')


def main() -> int:
    if not POSIX:
        print('skipped: a stored secret is not used on Windows')
        return 0
    with tempfile.TemporaryDirectory() as tmp_:
        tmp = Path(tmp_).resolve()
        D._tmp = recorded_tmp
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'homecfg')
        os.environ['AGENT_RUNNER_SSH_CONFIG'] = str(tmp / 'none')
        repo, other = make_repo(tmp, 'proj'), make_repo(tmp, 'other')
        R.init(repo)
        seen = []
        have = shutil.which('ssh-agent') and shutil.which('ssh-keygen')
        tests = [test_hostile, lambda: test_folder(tmp), test_channel, test_redactor, test_other_kind]
        if have:
            tests += [lambda: test_secrets(tmp), lambda: seen.append(test_server()), lambda: seen.append(test_connect(tmp)),
                      lambda: test_needs(repo, other, tmp), lambda: test_lease(repo, tmp), lambda: test_keyring(tmp),
                      lambda: test_nowhere('\n'.join(seen), repo)]
        else:
            print('skipped in part: ssh is not installed')
        return report(tests)


if __name__ == '__main__':
    sys.exit(main())
