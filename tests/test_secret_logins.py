#!/usr/bin/env python3
"""F466a: logins: the password stays out of devices.json, repos, argv, the environment and what `login use` prints.

    python3 tests/test_secret_logins.py
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, eq, report

os.environ['AGENT_RUNNER_KEYRING'] = 'off'
from agent_runner import devices as D, secret_logins as L  # noqa: E402

PW = 'sentinel-login-pw-9f3a'


class Out(io.BytesIO):
    pass


def test_logins():
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        lg = L.put('apple-id-free', PW, purpose='Xcode signing', user='me@example.com', twofa='the iPhone',
                   projects=['proj'])
        eq(lg['password'], {'store': 'file'}, 'kept in a file when the keyring is off')
        f = tmp / 'state' / 'secrets' / 'login-apple-id-free.password'
        eq(f.read_text(), PW, 'the password file')
        eq(f.stat().st_mode & 0o777, 0o600, 'the file is 0600')
        for p in (tmp / 'state').rglob('*'):
            if p.is_file() and p != f:
                check(PW not in p.read_text(errors='replace'), f'no password in {p.name}')
        check(not (tmp / 'state' / 'devices.json').exists() or PW not in (tmp / 'state' / 'devices.json').read_text(),
              'not in devices.json')
        shown = '\n'.join(L.lines('apple-id-free', L.get('apple-id-free')))
        check(PW not in shown and 'password: set' in shown and 'me@example.com' in shown, 'show: set, never the value')

        # the command sees its argv and environment: neither holds the password; its stdin does, and its print is hidden
        out = Out()
        code = L.run_with('apple-id-free', [sys.executable, '-c',
                          'import os,sys; print(sys.argv); print(dict(os.environ)); print("got", sys.stdin.readline())'],
                          project='proj', out=out)
        text = out.getvalue().decode()
        eq(code, 0, 'use ran')
        check(PW not in text, 'use: output redacted')
        check(D.HIDDEN in text, 'use: the password came on stdin and was hidden')
        check("'LOGIN_USER': 'me@example.com'" in text, 'use: $LOGIN_USER')
        dump = tmp / 'dump.txt'  # raw, not through the redactor
        L.run_with('apple-id-free', [sys.executable, '-c',
                   'import os,sys; open(sys.argv[1],"w").write(repr(sys.argv)+repr(dict(os.environ)))', str(dump)],
                   project='proj', out=Out())
        raw = dump.read_text()
        check('LOGIN_USER' in raw and PW not in raw, 'use: no password on argv or in the environment (raw dump)')
        check(not any(PW in p.read_text(errors='replace') for p in tmp.rglob('run.log')), 'no password in a run.log')
        out = Out()
        L.run_with('apple-id-free', ['sh', '-c', '"$LOGIN_ASKPASS" "Password:"'], askpass=True, project='proj', out=out)
        text = out.getvalue().decode()
        check(PW not in text and D.HIDDEN in text, f'askpass: answered and hidden: {text!r}')

        try:
            L.run_with('apple-id-free', ['true'], project='other', out=Out())
            check(False, 'another project is refused')
        except D.Refused:
            pass

        # never kept in a repo
        repo = tmp / 'repo'
        (repo / '.git').mkdir(parents=True)
        os.environ['AGENT_RUNNER_DEVICES'] = str(repo / 'state')
        try:
            L.put('x', PW, projects=['*'])
            check(False, 'a repo path is refused')
        except D.Refused:
            pass
        check(not (repo / 'state' / 'secrets').exists() and not (repo / 'state' / 'logins.json').exists(),
              'nothing written in the repo')

        # the CLI: `run login list` through login.main, the provider list untouched
        os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'state')
        r = subprocess.run([sys.executable, '-m', 'agent_runner', 'login', 'list'], capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parent.parent))
        check('apple-id-free' in r.stdout and PW not in r.stdout + r.stderr, f'login list: {r.stdout}{r.stderr}')


if __name__ == '__main__':
    sys.exit(report([test_logins]))
