"""F406a: the provider logins of the run app, server side: the terminal each provider's `run login` gets on the run page
and on Runner Home, what is refused, the list of logins, and how a login's end is told. No network; with ttyd and node
here, one whole login with Pi's login package faked."""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from _check import FAILED, check, eq, git
from _web import asked, fake_repo, get

from agent_runner import config as CF
from agent_runner import home as H
from agent_runner import login as G
from agent_runner import login_hold as L
from agent_runner import plan as P
from agent_runner import provider_login as PL
from agent_runner import session_frame as SF
from agent_runner import state as S
from agent_runner import ui_model as U
from agent_runner import web as W

tmp = Path(tempfile.mkdtemp(prefix='agent-runner-plogin-'))
os.environ['AGENT_RUNNER_HOME_CONFIG'] = str(tmp / 'hc')
os.environ['PI_CODING_AGENT_DIR'] = str(tmp / 'pi')
for k in ('GEMINI_API_KEY', 'ACME_KEY', 'AGENT_RUNNER_REPO', 'AGENT_RUNNER_SLOT', 'AGENT_RUNNER_WORKTREE'):
    os.environ.pop(k, None)
repo = fake_repo(tmp)
(repo / 'runner.toml').write_text(
    '[run]\nremote = false\n[models]\nlocal = true\n[models.providers.acme]\nkind = "openai"\n'
    'url = "https://user:pw-SECRET@api.acme.example/v1"\nkey_env = "ACME_KEY"\n[models.providers.lab]\nkind = "openai"\n'
    'url = "http://localhost:8000/v1"\n[models.providers."--x y"]\nkind = "openai"\nurl = "https://x.example"\nkey_env = "X"\n',
    encoding='utf-8')
git(repo, 'add', '-A')
git(repo, 'commit', '-qm', 'settings')
CF._cfg.cache_clear()
S.init(repo)
os.chdir(repo)
token = W.web_token()
run = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
links: dict = {}
home = H.serve_home('HT', 0, '127.0.0.1', rows=lambda: [], roots=lambda: [repo], vitals=mock.Mock(),
                    link=lambda root: links.get(root))
key = next(iter(H.keys([repo])))
RB, HB = (f'http://127.0.0.1:{s.server_address[1]}' for s in (run, home))
PB = f'{HB}/p/{key}'  # its run not up: Home's own
TERMS = [run.terms, home.terms(), home.login_terms(key)]


def until(what, s: float = 20) -> bool:
    end = time.monotonic() + s
    while not what() and time.monotonic() < end:
        time.sleep(0.02)
    return bool(what())


def row(base: str, t: str, name: str) -> dict:
    return next(p for p in json.loads(get(f'{base}/logins?t={t}')[1])['providers'] if p['name'] == name)


def browser(port: int, path: str):
    c = socket.create_connection(('127.0.0.1', port), timeout=20)
    c.sendall((f'GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n').encode())
    f = c.makefile('rb')
    first = f.readline()
    while f.readline() not in (b'\r\n', b''):
        pass
    return c, f, first


FAKE = """export default function ({ id }) {
  if (id === 'github-copilot') return { oauth: { async login(io) {
    const domain = await io.prompt({ type: 'text', message: 'GitHub Enterprise URL/domain' });
    if (domain === 'bad.ghe.com') throw new Error('no such domain');
    return { type: 'oauth', access: 'tok-SECRET', refresh: 'ref-SECRET', expires: 1, enterpriseUrl: domain || undefined };
  } } };
  return { apiKey: { async login(io) {
    return { type: 'api_key', key: await io.prompt({ type: 'secret', message: 'key' }) };
  } } };
}"""


def whole_logins() -> None:
    """Real ttyd, `run login` and harness.mjs; only Pi's login package is a fake."""
    if not (shutil.which('ttyd') and shutil.which('node')) or CF.plat.WINDOWS:
        return print('  skip: no ttyd or no node')
    (tmp / 'fake.mjs').write_text(FAKE, encoding='utf-8')
    os.environ['AGENT_RUNNER_HARNESS_LOGIN'] = str(tmp / 'fake.mjs')
    hello = json.dumps({'AuthToken': '', 'columns': 80, 'rows': 24}).encode()

    def sent(c, data: bytes) -> None:
        c.sendall(bytes([130, 128 | len(data)]) + bytes(4) + data)

    def through(base: str, srv, t: str, name: str, typed: bytes = b'') -> bytes:
        where = json.loads(get(f'{base}/terminal/{name}?t={t}')[1])
        check(where['ok'], f'{name} opens', where)
        prefix = base.partition('/p/')
        c, f, first = browser(srv.server_address[1], (f'/p/{prefix[2]}' if prefix[1] else '') + where['path'] + 'ws')
        check(b' 101 ' in first, f'{name}: a WebSocket', first)
        sent(c, hello)
        seen = b''
        while True:
            op, _, body = L.read_frame(f)
            if op == 8:
                break
            if op == 9:
                c.sendall(b'\x8a\x80' + bytes(4))
            elif op < 3:
                seen += body[1:]
                if typed and b'key: ' in seen:
                    sent(c, b'0' + typed)
                    typed = b''
        c.close()
        return seen

    tid = P.add('F', 'Copilot work', todo=S.C.todo)
    P.block(tid, G.why_for('copilot', tid), todo=S.C.todo, after=[])
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'plan')
    seen = through(RB, run, token, 'login-copilot~bad.ghe.com')
    r = row(RB, token, 'copilot')
    eq((r['ok'], r['login']['state']), (False, 'failed'), 'a failed login is told')
    check('did not finish' in r['login']['said'] and 'SECRET' not in seen.decode(), 'with why', (r, seen))
    seen = through(RB, run, token, 'login-copilot~Corp.ghe.com')
    r = row(RB, token, 'copilot')
    eq((r['ok'], r['login']), (True, {'state': 'done', 'said': 'copilot is logged in', 'reopened': [tid]}),
       'a login that finished is told, and the task parked for it reopened')
    check('corp.ghe.com' in r['where'], 'on its domain', r)
    check(not [a for a in P.asks(S.C.todo, all=True) if a[1] == tid], 'it is off Needs you')
    seen += through(RB, run, token, 'login-acme', b'key-SECRET\r')
    eq(row(RB, token, 'acme')['login']['state'], 'done', 'a key is typed in the terminal')
    check(b'SECRET' not in seen, 'which never shows it', seen)

    print('  on Home, with no run up')
    P.block(tid, G.why_for('gemini', tid), todo=S.C.todo, after=[])
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'plan')
    through(HB, home, 'HT', 'login-gemini', b'g-SECRET\r')
    eq(row(HB, 'HT', 'gemini')['login']['state'], 'done', 'Home logs in with no project')
    check(until(lambda: not [a for a in P.asks(S.C.todo, all=True) if a[1] == tid]), "and a project's parked task reopens")
    through(PB, home, 'HT', 'login-acme', b'key-SECRET\r')
    eq(row(PB, 'HT', 'acme')['login']['state'], 'done', "and with a project's own provider")
    for base, t in ((RB, token), (HB, 'HT'), (PB, 'HT')):
        body = get(f'{base}/logins?t={t}')[1].decode()
        check('SECRET' not in body, 'no answer holds a secret', body)


try:
    print("each provider's argv")
    for terms in (run.terms, TERMS[2]):
        for name, want in (('login-copilot', ['login', 'copilot', '--enterprise=']), ('login-codex', ['login', 'codex']),
                           ('login-gemini', ['login', 'gemini']), ('login-acme', ['login', 'acme']),
                           ('login-copilot~Company.ghe.com', ['login', 'copilot', '--enterprise=company.ghe.com'])):
            argv = terms.argv(name, name, 9)
            eq(argv[-len(want) - len(CF.runner_cmd()):], [*CF.runner_cmd(), *want], f'{name}: the runner, as argv')
            check('-a' not in argv and '--url-arg' not in argv, 'no arguments from the URL', argv)
            eq((argv[argv.index('-i') + 1], argv[argv.index('-b') + 1]), ('127.0.0.1', f'/t/{terms.token}/{name}'),
               'on 127.0.0.1, at its token')
    eq((run.terms.cwd('login-acme'), TERMS[2].cwd('login-acme')), (str(S.ROOT), str(repo)), 'in the project')
    eq(TERMS[1].cwd('login-codex'), str(Path.home()), "Home's own in none")

    print('a refused name or domain, with the reason')
    BAD = ['nope', 'claude', 'ollama', 'lab', '--x%20y', '-x', '', 'codex~a.ghe.com', 'acme~a.ghe.com', 'copilot;id',
           *(f'copilot~{d}' for d in ('', 'ghe', 'https:', 'https%3A%2F%2Fa.ghe.com', 'a.ghe.com:8443', 'a.ghe.com/x', 'a.ghe.com/',
                                      '-a.ghe.com', 'a..com', 'a.ghe.com.', '10.0.0.1', '$(id).com', 'a%20b.com', 'u@a.com',
                                      'a.com~b.com', 'a.com%0A', 'a' * 64 + '.com', 'a.' * 130 + 'com', 'é.com'.encode().hex() + '%C3%A9.com'))]
    with mock.patch.object(W.Terminals, 'argv', side_effect=AssertionError('started')):
        for base, t in ((RB, token), (HB, 'HT'), (PB, 'HT')):
            for bad in BAD:
                code, body = get(f'{base}/terminal/login-{bad}?t={t}')
                r = json.loads(body)
                check(code == 200 and r['ok'] is False and r['out'], f'refused: {bad[:40]}', r)
                if '/' not in bad:
                    eq(get(f'{base}/t/{t}/login-{bad}/')[0], 502, 'and its terminal is not served')
        eq(json.loads(get(f'{HB}/terminal/login-acme?t=HT')[1])['ok'], False, "Home's own knows only the built-in ones")
    said = json.loads(get(f'{RB}/terminal/login-copilot~key-SECRET?t={token}')[1])['out']
    eq(said, PL.NO_HOST, 'the reason never says back what was sent')
    check('acme' in PL.parse('login-nope', S.C.providers)[2], 'an unknown provider: the ones there are')
    eq(PL.parse('login---x y', S.C.providers)[0], '', 'a name that would be an option is refused')
    for bad in ('login-copilot~a.com\n', 'login-codex\n'):
        check(PL.parse(bad, {})[2], 'a newline is refused')

    print('only with the key')
    with mock.patch.object(W.Terminals, 'ttyd', lambda self, n, sock='': {'ok': True, 'port': 9}), mock.patch.object(
            SF, 'frame', lambda h, port, path, n, look: h.send(200, json.dumps([path, n]))):
        for base, t in ((RB, token), (HB, 'HT'), (PB, 'HT')):
            eq(json.loads(get(f'{base}/terminal/login-codex?t={t}')[1])['path'], f'/t/{t}/login-codex/', 'where it is')
            eq(json.loads(get(f'{base}/t/{t}/login-codex/?arg=sh')[1]), [f'/t/{t}/login-codex/', 'login-codex'], 'served, its query not')
            for bad in ('/t/wrong/login-codex/', '/t//login-codex/', '/terminal/login-codex?t=wrong', '/logins', '/logins?t=x'):
                eq(get(base + bad)[0], 403, f'refused: {bad}')
        ts = '100.101.1.2'
        S.C.raw['ui']['trusted_networks'] = ['tailnet']
        H.save_registry({**H.load_registry(), 'trusted_networks': ['tailnet']})
        links[repo] = (run.server_address[1], token)
        for base, srv in ((RB, run), (HB, home), (PB, home), (PB + '/', home)):
            eq([asked(base + p, ts, srv) for p in ('/t//login-codex/', '/terminal/login-codex', '/logins')], [403] * 3,
               'nor on a trusted network without it')
        eq(json.loads(get(f'{PB}/t/HT/login-codex/')[1])[0], f'/t/{token}/login-codex/', 'with a run up, the run serves it')
        links.clear()
        S.C.raw['ui']['trusted_networks'] = []
        H.save_registry({**H.load_registry(), 'trusted_networks': []})

    print('without ttyd: how to install it, and the command')
    with mock.patch.object(U, 'terminal_mode', return_value='install'):
        r = json.loads(get(f'{RB}/terminal/login-copilot~a.ghe.com?t={token}')[1])
        eq((r['ok'], r['mode']), (False, 'install'), 'not opened')
        check('login copilot --enterprise=a.ghe.com in a terminal' in r['out'], 'the command', r['out'])

    print('the list of providers')
    with mock.patch.dict(os.environ, {'ACME_KEY': 'env-SECRET'}):
        body = get(f'{RB}/logins?t={token}')[1].decode()
        rows = {p['name']: p for p in json.loads(body)['providers']}
        eq(list(rows), [*CF.PROVIDERS, 'acme', 'lab', '--x y'], 'the built-in ones, then [models.providers]')
        for n, p in rows.items():
            eq((p['ok'], p['where']), G.login_of(n, S.C.providers), f"{n}: login_of's answer")
        eq([p['terminal'] for p in rows.values()],
           ['login', 'login-copilot', 'login-codex', 'login-gemini', '', 'login-acme', '', ''], 'what opens each')
        check('SECRET' not in body, 'never a secret', body)
    check('acme' in {p['name'] for p in json.loads(get(f'{PB}/logins?t=HT')[1])['providers']}, "a project's own, with no run up")
    eq([p['name'] for p in json.loads(get(f'{HB}/logins?t=HT')[1])['providers']], list(CF.PROVIDERS), "Home's: the built-in ones")

    print('one terminal a provider; one cut off is told as failed')
    logins = PL.Logins(dict)
    a, _ = logins.get('login-copilot')
    b, old = logins.get('login-copilot~a.ghe.com')
    eq((old, logins.get('login-copilot~a.ghe.com')), ('login-copilot', (b, '')), 'another domain takes its place')
    b.began()
    eq(b.status()['state'], 'running', 'running')
    b.over()
    eq(b.status()['state'], 'failed', 'ended with nothing said')
    b.began()
    b.result.write_text('[]', encoding='utf-8')
    b.over()
    eq((b.status()['state'], b.result.exists()), ('failed', False), 'a file of another shape too, and it is gone')
    done = []
    c = PL.Login('login-codex', 'codex', done.append)
    c.began()
    G.told(str(c.result), True, 'codex is logged in', ['F1'])
    if os.name == 'posix':
        eq(c.result.stat().st_mode & 0o777, 0o600, 'only this user reads how it ended')
    c.over()
    eq(c.status(), {'state': 'done', 'said': 'codex is logged in', 'reopened': ['F1']}, 'finished')
    check(until(lambda: done == ['codex']), 'and Home is told, to reopen in every project')

    print('run login --reopen: only with a login, and no plan made where there is none')
    with mock.patch.object(G, 'reopen_for', side_effect=lambda p: done.append(p) or ['F1']), redirect_stdout(io.StringIO()):
        done.clear()
        eq((G.main(['codex', '--reopen']), done), (0, []), 'no login: nothing')
        (tmp / 'pi').mkdir(exist_ok=True)
        (tmp / 'pi' / 'auth.json').write_text('{"openai-codex": {"type": "oauth"}}', encoding='utf-8')
        eq((G.main(['codex', '--reopen']), done), (0, ['codex']), 'reopened')
        (tmp / 'pi' / 'auth.json').unlink()
        eq((G.reopen_here('codex', None), G.reopen_here('codex', mock.Mock(todo=str(tmp / 'none')))), ([], []), 'no plan: nothing')

    print('whole logins')
    whole_logins()
finally:
    run.stop()
    home.stop()
raise SystemExit(1 if FAILED else print('\nall checks passed'))
