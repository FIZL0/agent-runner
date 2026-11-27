"""F466c: a Login's 2FA code is used once, expires after 5 minutes and is never in run.log; a missing Login's block
links the Login form with its name and purpose filled in."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from _check import check, eq, report, ROOT  # noqa: F401

from agent_runner import login_code as LC

CODE = '482913'


def _env(d: Path, text: str, age: float = 0) -> Path:
    f = d / 'F1.env'
    f.write_text(text, encoding='utf-8')
    if age:
        t = f.stat().st_mtime - age
        os.utime(f, (t, t))
    return f


def test_once():
    with tempfile.TemporaryDirectory() as d:
        f = _env(Path(d), f"OTHER='x'\n{LC.ENV}='{CODE}'\n")
        eq(LC.take(f), (CODE, ''), 'the code is taken')
        eq(LC.take(f), (None, 'none yet'), 'a code is used once')
        eq(f.read_text(encoding='utf-8'), "OTHER='x'\n", 'the other secrets stay')


def test_expires():
    with tempfile.TemporaryDirectory() as d:
        f = _env(Path(d), f"{LC.ENV}='{CODE}'\n", age=LC.KEEP + 5)
        eq(LC.take(f), (None, 'expired'), 'a code older than 5 minutes is thrown away')
        check(not f.exists(), 'and gone from the file')
        f = _env(Path(d), f"{LC.ENV}='12ab'\n")
        eq(LC.take(f)[0], None, 'not 6 digits: refused')


def test_wait():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / 'F1.env'
        t = [0.0]
        def sleep(s):
            t[0] += s
            if t[0] >= 4:
                f.write_text(f"{LC.ENV}='{CODE}'\n", encoding='utf-8')
        eq(LC.wait(f, 100, clock=lambda: t[0], sleep=sleep)[0], CODE,
           'the waiting command goes on once the code is entered')
        t[0] = 0.0
        eq(LC.wait(Path(d) / 'none.env', 6, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s)),
           (None, 'no code came before the deadline'), 'the wait has a deadline')


def test_ask_and_log():
    a = LC.ask('apple-id', 'sign in to App Store Connect', 'the iPhone 15')
    x = a['inputs'][0]
    eq((x['kind'], x['env'], x['match']), ('secret', LC.ENV, '^[0-9]{6}$'), 'the ask file has a 6-digit code field')
    src = (ROOT / 'agent_runner' / 'login_code.py').read_text(encoding='utf-8')
    check('run.log' not in src.replace('never written to run.log', '') and 'log(' not in src,
          'login_code writes nothing to run.log')


def test_missing():
    why = LC.missing_why('apple-id', 'App Store uploads', base='https://box.ts.net/?t=tok')
    check(why.startswith('BLOCKED: Add the login apple-id'), f'the block line says what to do: {why}')
    u = urlsplit(why.split(': ', 2)[-1])
    eq(u.fragment.partition('?')[0], 'login-add', 'the link opens the Login form, not just the Tools page')
    q = parse_qs(u.fragment.partition('?')[2])
    eq((q['name'], q['for']), (['apple-id'], ['App Store uploads']), 'name and purpose filled in')
    eq(u.query, 't=tok', 'the page token kept')
    js = (ROOT / 'agent_runner' / 'page' / '132-login-link.js').read_text(encoding='utf-8')
    check('#login-add' in js and "formlogin" in js, 'the page opens the Login form for #login-add')


if __name__ == '__main__':
    sys.exit(report([test_once, test_expires, test_wait, test_ask_and_log, test_missing]))
