"""F427a: until checks, what a blocked task can wait on that this machine can read by itself, with no agent session and
no model call.

A check is one of four kinds, written `kind:value`; nothing else is taken, so never a command of its own:

    version:X.Y.Z    the agent-runner serving this run is at least that
    login:PROVIDER   that login works, as far as this machine's files say
    tool:NAME        a shared tool or device is free
    check:NAME       [run.checks.NAME] in runner.toml: `cmd` exits 0 passed, 75 not yet, anything else cannot run
    date:YYYY-MM-DD  that day has come, on this machine's clock (F491: a task that only waits for a date)

`problem` says why a check is refused, `label` what the screens call it, and `run` answers it once: (PASSED, NOT_YET or
CANNOT, words).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess as sp
import sys
import tempfile
import time
from pathlib import Path

from agent_runner import plan as P, plat
from agent_runner import state as S

PASSED, NOT_YET, CANNOT = 'passed', 'not yet', 'cannot run'
EXITS = {0: PASSED, 75: NOT_YET}  # sysexits' TEMPFAIL, as a shared tool's busy
KINDS = ('version', 'login', 'tool', 'check', 'date')
DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')


def today() -> 'datetime.date':
    """This machine's date; tests replace it."""
    import datetime
    return datetime.date.today()
CLAUDE_KEYS = ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')
CHECK_TIMEOUT = 10.0  # s a named check may take, as shared_tools.CHECK_TIMEOUT
VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')


class Refused(ValueError):
    """A check that is not one, or names what this project does not have; its text says why."""


def checks(c=None) -> dict[str, dict]:
    """{name: {cmd, label}} of [run.checks]."""
    c = c or S.C
    return {n: {'cmd': t['cmd'], 'label': t.get('label') or n} for n, t in ((c.run.get('checks') if c else None) or {}).items()}


def read(text: str, c=None) -> tuple[str, str]:
    """(kind, value) of the check `text`; Refused when it is none, or names what is not here."""
    c = c or S.C
    text = text.strip()
    kind, sep, value = text.partition(':')
    if not sep or kind not in KINDS:
        raise Refused(f'no such check: {text!r}; use version:X.Y.Z, login:PROVIDER, tool:NAME, check:NAME or '
                      'date:YYYY-MM-DD (a command goes in [run.checks.NAME] in runner.toml)')
    if kind == 'date':
        if not DATE.fullmatch(value) or not _day(value):
            raise Refused(f'{text!r}: a date is a real day written date:2026-12-03')
        return kind, value
    if kind == 'version':
        if not VERSION.fullmatch(value):
            raise Refused(f'{text!r}: a version is three numbers, version:0.66.0')
        return kind, value
    known = _known(kind, c)
    if not NAME.fullmatch(value) or value not in known:
        what = {'login': 'provider', 'tool': 'shared tool or device', 'check': 'check'}[kind]
        none = {'tool': 'this project has none ([run.tools] in runner.toml, or a device on the Tools page)',
                'check': 'this project names none ([run.checks] in runner.toml)'}.get(kind, '')
        raise Refused(f'no {what} named {value!r}; ' + (f'there is: {", ".join(known)}' if known else none))
    return kind, value


def _known(kind: str, c) -> list[str]:
    from agent_runner import shared_tools
    from agent_runner.config import PROVIDERS
    if kind == 'login':
        return list(dict.fromkeys([*PROVIDERS, *c.providers]))
    return list(shared_tools.specs(c) if kind == 'tool' else checks(c))


def problem(text: str, c=None) -> str:
    """Why the check `text` is refused, or ''."""
    try:
        read(text, c)
    except Refused as e:
        return str(e)
    return ''


def label(text: str, c=None) -> str:
    """What the screens call the check `text`, as in 'waits for <label>'."""
    from agent_runner import shared_tools
    c = c or S.C
    kind, _, value = text.strip().partition(':')
    if kind == 'tool':
        return shared_tools.label(value, c)
    if kind == 'check':
        return (checks(c).get(value) or {}).get('label', value)
    return {'version': f'version {value}', 'login': f'{value} login', 'date': value}.get(kind, text)


def run(text: str, c=None) -> tuple[str, str]:
    """Run the check `text` once, now: (PASSED, NOT_YET or CANNOT, its words). Never raises for what it names being gone."""
    c = c or S.C
    try:
        kind, value = read(text, c)
    except Refused as e:
        return CANNOT, str(e)
    return {'version': _version, 'login': _login, 'tool': _tool, 'check': _named, 'date': _date}[kind](value, c)


def _day(value: str):
    import datetime
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def _date(value: str, c) -> tuple[str, str]:
    now = today()
    return (PASSED if now >= _day(value) else NOT_YET), f'today is {now.isoformat()}'


def serving_version(c) -> str:
    """The version of the run that is up (its STATE); with none up this process's own. '' when it cannot be told."""
    from agent_runner import __version__
    if f := plat.lock(c.notes('run.lock')):
        f.close()
        return __version__
    try:
        return str(json.loads(c.notes('STATE').read_text(encoding='utf-8')).get('version') or '')
    except (OSError, ValueError, AttributeError):
        return ''


def _version(want: str, c) -> tuple[str, str]:
    have = serving_version(c)
    if not VERSION.match(have):
        return CANNOT, "the run's version cannot be told"

    def num(v: str) -> tuple:
        return tuple(int(x) for x in VERSION.match(v).group().split('.'))
    return PASSED if num(have) >= num(want) else NOT_YET, f'the run is on {have}'


def _login(provider: str, c) -> tuple[str, str]:
    from agent_runner import login
    if provider == 'claude':
        return _claude(c)
    creds = login.stored()
    ok, words = login.login_of(provider, c.providers, creds)
    if ok and not login.needs_none(provider, c.providers):
        cred = creds.get(provider if provider in c.providers else login.PI_IDS.get(provider, provider))
        ends = cred.get('expires') if isinstance(cred, dict) and cred.get('type') == 'oauth' else None
        # one that can be renewed is renewed by itself
        if isinstance(ends, (int, float)) and not cred.get('refresh') and ends / 1000 <= time.time():
            return NOT_YET, 'the login has expired'
    return PASSED if ok else NOT_YET, words


def _claude(c) -> tuple[str, str]:
    from agent_runner import watch
    agent = c.run['agent']
    if agent != 'claude':
        return CANNOT, f'the login of [run] agent = {agent!r} cannot be read here'
    if not watch.own_claude_login(agent):
        key = next((k for k in CLAUDE_KEYS if os.environ.get(k)), '')
        return (PASSED, f'env {key}') if key else (CANNOT, "sessions do not use Claude Code's own login, and theirs cannot be read here")
    path = Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / '.credentials.json'
    said = watch.claude_login(path=path, agent=agent)
    if said and not said.startswith('Claude login expires in'):  # that one still works
        return NOT_YET, said
    try:
        there = bool(json.loads(path.read_text(encoding='utf-8'))['claudeAiOauth'].get('refreshToken'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        there = False
    if not there:  # claude_login says nothing then on macOS, which keeps the login in the Keychain
        return CANNOT, 'the Claude login cannot be read on this machine' + (
            ' (it is in the Keychain)' if sys.platform == 'darwin' else '')
    return PASSED, said or 'logged in'


def _tool(name: str, c) -> tuple[str, str]:
    from agent_runner import shared_tools as T
    state, who = T.check(name, c)
    if state == T.FREE and (u := T.used(P.lines(c.todo), T._state()).get(name)):
        state, who = T.BUSY, u[0]  # a running task has it, whatever its check says
    if state == T.BUSY:
        return NOT_YET, f'held by {who}' if who else 'in use'
    return {T.FREE: (PASSED, 'free'), T.MISSING: (NOT_YET, who or 'not connected')}.get(state, (CANNOT, who or 'unknown'))


def _named(name: str, c) -> tuple[str, str]:
    """[run.checks.<name>]'s command, in the main checkout, as shared_tools.check runs a tool's."""
    from agent_runner.config import main_checkout
    # files, not pipes: a daemon the check leaves behind would hold a pipe open past the timeout
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            p = sp.Popen(checks(c)[name]['cmd'], shell=True, cwd=str(main_checkout(c.root)), stdin=sp.DEVNULL,
                         stdout=out, stderr=err, start_new_session=not plat.WINDOWS,
                         env={k: v for k, v in os.environ.items()
                              if k not in ('AGENT_RUNNER_SLOT', 'AGENT_RUNNER_WORKTREE')})
        except OSError as e:
            return CANNOT, f'its command does not start ({e})'[:120]
        try:
            rc = p.wait(timeout=CHECK_TIMEOUT)
        except sp.TimeoutExpired:
            if plat.WINDOWS:
                plat.terminate(p.pid)
            else:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except OSError:
                    pass
            try:
                p.wait(timeout=5)
            except sp.TimeoutExpired:
                pass
            return CANNOT, f'its command ran past {CHECK_TIMEOUT:g} s'

        def first(f) -> str:
            f.seek(0)
            return next((x.strip()[:80] for x in f.read(4000).decode('utf-8', 'replace').splitlines() if x.strip()), '')
        state, said = EXITS.get(rc, CANNOT), first(out)
        if state == CANNOT:
            why = first(err) or said
            return CANNOT, f'its command failed (exit {rc}{": " + why if why else ""})'
        return state, said or state
