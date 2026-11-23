#!/usr/bin/env python3
"""F106e: `run login` (agent_runner/login.py, harness.mjs --login) with Pi's login package faked: the list of
providers [models] names and their logins, a login stored where Pi keeps it (the GitHub Enterprise domain passed
through), and a task whose provider has no login listed under Needs you instead of started. Needs node for the
logins; no network and no real provider."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import login as L, plan as P, runner as R
from agent_runner.config import Config

# Pi's login package, faked: Copilot asks its Enterprise question and signs in by device code; a provider with an
# API key asks for it as a secret. What it was asked lands in $FAKE_LOG.
FAKE = r"""
import fs from 'node:fs';
const log = (o) => fs.appendFileSync(process.env.FAKE_LOG, JSON.stringify(o) + '\n');
export default function ({ id, custom }) {
  if (id === 'github-copilot') return { oauth: { async login(io) {
    const domain = await io.prompt({ type: 'text', message: 'GitHub Enterprise URL/domain (blank for github.com)',
                                     placeholder: 'company.ghe.com' });
    io.notify({ type: 'device_code', verificationUri: `https://${domain || 'github.com'}/login/device`, userCode: 'ABCD-1234' });
    log({ id, domain });
    return { type: 'oauth', access: 'tok-SECRET', refresh: 'ref-SECRET', expires: 1, enterpriseUrl: domain || undefined };
  } } };
  return { apiKey: { async login(io) {
    const key = await io.prompt({ type: 'secret', message: `Enter ${id} key` });
    log({ id, custom, key });
    return { type: 'api_key', key };
  } } };
}
"""

MODELS = ('code = "copilot:gpt-x"\nlocal = true\n\n[models.kinds]\nD = "gemini:pro"\n\n'
          '[models.providers.acme]\nkind = "openai"\nurl = "https://api.acme.example/v1"\nkey_env = "ACME_KEY"\n\n'
          '[models.providers.lab]\nkind = "openai"\nurl = "http://localhost:8000/v1"\n')


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.repo = tmp / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        (self.repo / 'runner.toml').write_text(f'[run]\n\n[models]\n{MODELS}', encoding='utf-8')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'start')
        self.pi = tmp / 'pi'
        self.fake, self.log = tmp / 'fake.mjs', tmp / 'asked.jsonl'
        self.fake.write_text(FAKE, encoding='utf-8')
        os.chdir(self.repo)
        R.init(self.repo)
        self.c = Config(self.repo)

    def auth(self) -> dict:
        try:
            return json.loads((self.pi / 'auth.json').read_text(encoding='utf-8'))
        except OSError:
            return {}

    def asked(self) -> list[dict]:
        return [json.loads(l) for l in self.log.read_text(encoding='utf-8').splitlines()] if self.log.exists() else []


def env_vars(e: Env, **more) -> dict:
    return {'PI_CODING_AGENT_DIR': str(e.pi), 'AGENT_RUNNER_HARNESS_LOGIN': str(e.fake), 'FAKE_LOG': str(e.log), **more}


def run_login(argv: list[str], e: Env, **patches) -> tuple[int, str]:
    out = io.StringIO()
    with mock.patch.dict(os.environ, env_vars(e)), redirect_stdout(out), \
            mock.patch('builtins.input', patches.get('input', lambda q='': '')), \
            mock.patch('getpass.getpass', patches.get('secret', lambda q='': '')), \
            mock.patch.object(L.getpass, 'getpass', patches.get('secret', lambda q='': '')):
        rc = L.main(argv)
    return rc, out.getvalue()


def test_list(e: Env):
    eq(L.named(e.c), ['copilot', 'claude', 'gemini', 'acme', 'lab'],
       'the providers [models] names: its roles, its kinds, then [models.providers]')
    e.pi.mkdir(exist_ok=True)
    (e.pi / 'auth.json').write_text(json.dumps({'github-copilot': {'type': 'oauth', 'access': 'tok-SECRET',
                                                                   'enterpriseUrl': 'corp.ghe.com'}}), encoding='utf-8')
    with mock.patch.dict(os.environ, {'PI_CODING_AGENT_DIR': str(e.pi)}):
        os.environ.pop('ACME_KEY', None)
        os.environ.pop('GEMINI_API_KEY', None)
        rc, out = run_login([], e)
        eq(rc, 0, 'run login with no provider lists them')
        lines = {l.split()[0]: l for l in out.splitlines()}
        has(lines.get('copilot', ''), r'✓ OAuth in .*auth\.json \(github-copilot, GitHub Enterprise corp\.ghe\.com\)',
            'copilot has a login: where it is kept, and its Enterprise domain')
        has(lines.get('gemini', ''), r'✗ no login: .* login gemini', 'gemini has none, and the line says how to add it')
        has(lines.get('acme', ''), r'✗ no login: .* login acme', 'a custom provider with its key_env unset has none')
        has(lines.get('lab', ''), r'✓ needs none', 'a local custom provider without key_env needs none')
        has(lines.get('claude', ''), r"✓ Claude Code's own login", "claude is Claude Code's own login")
        check('SECRET' not in out, 'never the secret itself', out)
        with mock.patch.dict(os.environ, {'ACME_KEY': 'k-SECRET'}):
            rc, out = run_login([], e)
        has(out, r'acme\s+✓ env ACME_KEY', 'a key in its key_env counts as its login, named by the var')
        check('k-SECRET' not in out, 'and the key is not shown', out)
    (e.pi / 'auth.json').unlink()


def test_copilot(e: Env):
    if not shutil.which('node'):
        print('  skip: no node on PATH')
        return
    rc, out = run_login(['copilot', '--enterprise', 'acme.ghe.com'], e)
    eq(rc, 0, 'run login copilot --enterprise signs in')
    eq([a.get('domain') for a in e.asked() if a['id'] == 'github-copilot'], ['acme.ghe.com'],
       "the Enterprise domain given reaches the login package's question")
    eq(e.auth().get('github-copilot', {}).get('enterpriseUrl'), 'acme.ghe.com', "and is kept in Pi's auth.json")
    has(out, r'https://acme\.ghe\.com/login/device and enter the code ABCD-1234', 'the device code is shown')
    asked = []
    rc, out = run_login(['copilot'], e, input=lambda q='': asked.append(q) or 'corp.ghe.com')
    check(rc == 0 and any('Enterprise' in q and 'blank for github.com' in q for q in asked),
          'without --enterprise it asks for the domain, blank for github.com', asked)
    eq(e.auth()['github-copilot'].get('enterpriseUrl'), 'corp.ghe.com', 'and passes the answer through')
    rc, out = run_login(['copilot', '--enterprise', ''], e)
    check(rc == 0 and 'enterpriseUrl' not in e.auth()['github-copilot'], 'a blank domain is github.com', e.auth())
    check('SECRET' not in out, 'the login prints no token', out)


def test_keys(e: Env):
    if not shutil.which('node'):
        print('  skip: no node on PATH')
        return
    rc, _ = run_login(['gemini'], e, secret=lambda q='': 'g-key')
    eq((rc, e.auth().get('google')), (0, {'type': 'api_key', 'key': 'g-key'}),
       "a Gemini key is asked as a secret and kept under Pi's google login")
    rc, out = run_login(['acme'], e, secret=lambda q='': 'a-key')
    eq((rc, e.auth().get('acme')), (0, {'type': 'api_key', 'key': 'a-key'}),
       "a custom provider's key is kept under its name, where the harness loop reads it before ACME_KEY")
    got = [a for a in e.asked() if a['id'] == 'acme']
    check(got and got[-1]['custom'].get('key_env') == 'ACME_KEY', 'the login knows its key_env', got)
    with mock.patch.dict(os.environ, env_vars(e)):
        eq(L.login_of('acme', e.c.providers)[0], True, 'and the list shows it has a login')
    rc, _ = run_login(['lab'], e)
    eq(rc, 0, 'a local provider needs no login')
    rc, _ = run_login(['nope'], e)
    eq(rc, 2, 'an unknown provider is refused')


def test_needs_you(e: Env):
    with mock.patch.dict(os.environ, {'PI_CODING_AGENT_DIR': str(e.tmp / 'empty')}):
        os.environ.pop('GEMINI_API_KEY', None)
        tid = P.add('D', 'Write the docs', todo=R.C.todo)
        git(e.repo, 'add', '-A')
        git(e.repo, 'commit', '-qm', 'plan')
        eq(L.missing('gemini:pro', R.C), 'gemini', 'a model on gemini with no login is missing its login')
        eq(L.missing('opus', R.C), '', 'a claude model never is')
        check(L.unlogged(tid, 'main', R.C.models['code']), f'{tid} (kind D, on gemini) is held back, not started')
        asks = [a for a in P.asks(R.C.todo, all=True) if a[1] == tid]
        check(asks and asks[0][0] == 'BLOCKED' and 'login gemini' in asks[0][3],
              'it lists under Needs you with run login gemini', asks)
        eq(git(e.repo, 'status', '--porcelain', '--', str(R.C.todo.relative_to(e.repo))), '',
           'and the block is committed')
        out = io.StringIO()
        with redirect_stdout(out):
            R.cmd_needs([])
        has(out.getvalue(), rf'login gemini.*{tid}|{tid}.*login gemini', '`needs` names it')
        with mock.patch.dict(os.environ, {'GEMINI_API_KEY': 'k'}):
            eq(L.missing('gemini:pro', R.C), '', 'with a key in GEMINI_API_KEY it has a login')
            eq(L.reopen_for('gemini'), [tid], 'and a login reopens the task it held back')
        check(not [a for a in P.asks(R.C.todo, all=True) if a[1] == tid], 'it is off Needs you again')


def main() -> int:
    here = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        e = Env(Path(tmp))
        try:
            return report([lambda: test_list(e), lambda: test_copilot(e), lambda: test_keys(e),
                           lambda: test_needs_you(e)])
        finally:
            os.chdir(here)


if __name__ == '__main__':
    sys.exit(main())
