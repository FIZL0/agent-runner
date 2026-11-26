"""F456: `agent-runner setup` offers Runner Home when it is not installed, and to list the project in it; every
answer and the install are faked, so no real service is touched."""
from __future__ import annotations

import builtins
import contextlib
import io
import tempfile
from pathlib import Path
from unittest import mock

import _check as C
from _check import report

from agent_runner import setup as S


def check(what, ok):
    C.check(ok, what)


def eq(what, got, want):
    C.eq(got, want, what)


def has(what, text, pat):
    C.check(pat in text, what, f'no {pat!r} in {text!r}')


class FakeHome:
    def __init__(self, on=False, listed=False, code=0, root=None):
        self.on, self.code, self.calls, self.added = on, code, [], []
        self.list = [root] if listed else []

    def home_on(self):
        return self.on

    def projects(self):
        return list(self.list)

    def add_project(self, p):
        self.added.append(p)
        self.list.append(Path(p))
        return True, f'Home lists {Path(p).name}'

    def install(self):
        self.calls.append('install')
        if isinstance(self.code, BaseException):
            raise self.code
        self.on = self.code == 0
        return self.code

    def mark_installed(self, on):
        self.calls.append(f'mark {on}')
        self.on = on


def run(home, answers, tty=True):
    root = Path(tempfile.mkdtemp())
    if home.list:
        home.list = [root]
    asked = []

    def fake_input(q=''):
        asked.append(q)
        a = answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a
    with mock.patch.object(S, 'at_terminal', lambda: tty), mock.patch.object(builtins, 'input', fake_input), \
            contextlib.redirect_stdout(io.StringIO()):
        out = S.offer_home(root, home)
    return out, asked, root


for name, ans in (('yes', 'y'), ('Enter', '')):
    h = FakeHome()
    out, asked, root = run(h, [ans])
    check(f'{name}: asks to install', 'Install Runner Home, one address for every project on this device? [Y/n]' in asked[0])
    eq(f'{name}: installs', h.calls, ['install'])
    eq(f'{name}: adds the project not listed', h.added, [str(root)])
    has(f'{name}: says so', out[0], 'installed')

h = FakeHome()
out, asked, _ = run(h, ['n'])
eq('no: nothing installed', h.calls, [])
has('no: names the command', out[0], 'home install')

h = FakeHome()
out, asked, _ = run(h, [KeyboardInterrupt()])
eq('Ctrl-C: nothing installed', (h.calls, h.added), ([], []))

h = FakeHome(on=True, listed=True)
out, asked, _ = run(h, [])
eq('installed and listed: nothing asked', (asked, out, h.calls), ([], [], []))

h = FakeHome(on=True)
out, asked, root = run(h, [''])
has('installed, not listed: asks to add', asked[0], 'does not list')
eq('installed, not listed: added, not installed', (h.added, h.calls), ([str(root)], []))

h = FakeHome(on=True)
out, asked, _ = run(h, ['n'])
eq('installed, add declined', h.added, [])

h = FakeHome(code=1)
out, asked, _ = run(h, ['y'])
eq('failed install: Home left off', (h.calls, h.on, h.added), (['install', 'mark False'], False, []))
has('failed install: said', out[0], 'not installed')

h = FakeHome(code=RuntimeError('boom'))
out, asked, _ = run(h, ['y'])
has('install that raises: said, no raise', out[0], 'boom')

h = FakeHome()
out, asked, _ = run(h, [], tty=False)
eq('no terminal: nothing asked', (asked, h.calls), ([], []))
has('no terminal: names the command', out[0], 'home install')

raise SystemExit(report([]))
