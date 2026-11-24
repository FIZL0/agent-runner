"""F406a: the provider logins of the run app, server side: `run login <provider>` in a terminal (web.Terminals), on the
run page and on Runner Home, and the list of providers with their logins.

A login's terminal is named `login-PROVIDER`, Copilot's on a GitHub Enterprise domain `login-copilot~company.ghe.com`
(no character that a path has to escape). The name is checked here and becomes an argv, never a shell's words. A key is
typed only in that terminal: no request and no answer holds one. `run login` writes how it ended to the file RESULT_ENV
names (`login.told`), so the page's list can say it.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
from pathlib import Path

from agent_runner import login, login_hold
from agent_runner.config import PROVIDERS, RUNNER, runner_cmd

PREFIX = 'login-'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]*')  # a provider that can be an address's part and is no option
LABEL = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
HOST = re.compile(rf'(?:{LABEL}\.)+[A-Za-z](?:[A-Za-z0-9-]{{0,61}}[A-Za-z0-9])')  # no address, port, path or scheme
NO_HOST = 'The GitHub Enterprise domain must be a bare host name, such as company.ghe.com'


def is_login(name: str) -> bool:
    return name.startswith(PREFIX)


def parse(name: str, providers: dict) -> tuple[str, str, str]:
    """(provider, Enterprise domain, '') of the terminal `name`, else ('', '', why it is refused). The reason never
    repeats what was sent: it may be a key put in the wrong place."""
    provider, sep, domain = name.removeprefix(PREFIX).partition('~')
    if why := refusal(provider, providers):
        return '', '', why
    if sep and provider != 'copilot':
        return '', '', f'{provider} takes no GitHub Enterprise domain: only copilot does'
    if sep and (len(domain) > 253 or not HOST.fullmatch(domain)):
        return '', '', NO_HOST
    return provider, domain.lower(), ''


def refusal(provider: str, providers: dict) -> str:
    """Why `provider` has no login terminal; '' when it has one."""
    if provider == 'claude':
        return 'claude logs in with Log in again, not here'
    if provider not in PROVIDERS and provider not in providers:
        return f'No such provider: use one of {", ".join(p for p in [*PROVIDERS, *providers] if p != "claude")}'
    if login.needs_none(provider, providers):
        return f'{provider} is a local provider: it needs no login'
    return '' if NAME.fullmatch(provider) else \
        f'This provider\'s name cannot be used here: log in with {RUNNER} login in a terminal'


def words(provider: str, domain: str) -> list[str]:
    """What follows the runner's command. Copilot's domain is always said (blank: github.com), so it is not asked."""
    return ['login', provider, *([f'--enterprise={domain}'] if provider == 'copilot' else [])]


def argv(name: str, providers: dict) -> list[str]:
    """What the terminal `name`'s ttyd runs; it ends with it, as the Claude login's does."""
    provider, domain, why = parse(name, providers)
    if why:
        raise ValueError(why)
    return ['-t', 'disableReconnect=true', *runner_cmd(), *words(provider, domain)]


class Login:
    """One provider's login in a terminal: its held socket, and how the last one ended."""

    def __init__(self, name: str, provider: str, done=None):
        self.name, self.provider, self.done = name, provider, done
        self.state, self.said, self.reopened = '', '', []
        self.result = Path(tempfile.gettempdir()) / f'agent-runner-login-{secrets.token_hex(8)}.json'
        self.hold = login_hold.LoginHold(self.began, self.over)

    def began(self) -> None:
        self.result.unlink(missing_ok=True)
        self.state, self.said, self.reopened = 'running', '', []

    def over(self) -> None:
        """The terminal ended (hold.lock is held): what `run login` left in its file, or that it never finished."""
        try:
            got = json.loads(self.result.read_text(encoding='utf-8'))
            ok, said, reopened = got['ok'] is True, str(got['said']), [str(t) for t in got['reopened']]
        except (OSError, ValueError, KeyError, TypeError):
            ok, said, reopened = False, 'The login ended before it finished', []
        self.state, self.said, self.reopened = 'done' if ok else 'failed', said, reopened
        try:
            self.result.unlink(missing_ok=True)
        except OSError:
            pass
        if ok and self.done:
            threading.Thread(target=self.done, args=(self.provider,), name='login-done', daemon=True).start()

    def status(self) -> dict:
        with self.hold.lock:
            return {'state': self.state, 'said': self.said, 'reopened': list(self.reopened)}


class Logins:
    """A page's provider logins, one a provider: opening Copilot's on another domain ends the one before.
    `providers`: gives [models.providers]; `done`: told the provider once one has logged in; `env`: the environment."""

    def __init__(self, providers, done=None, env=None):
        self.providers, self.done, self._env = providers, done, env or (lambda: dict(os.environ))
        self.lock, self.at = threading.Lock(), {}

    def get(self, name: str) -> tuple[Login, str]:
        """The login of terminal `name` (a good one), and the name of the one it took the place of ('': none)."""
        provider, _, why = parse(name, self.providers())
        if why:
            raise ValueError(why)
        with self.lock:
            old = self.at.get(provider)
            if old and old.name == name:
                return old, ''
            got = self.at[provider] = Login(name, provider, self.done)
        if old:
            old.hold.close()
        return got, old.name if old else ''

    def env(self, name: str) -> dict:
        return {**self._env(), login.RESULT_ENV: str(self.get(name)[0].result)}

    def live(self) -> bool:
        return any(g.hold.live() for g in list(self.at.values()))

    def close(self) -> None:
        for g in list(self.at.values()):
            g.hold.close()

    def rows(self) -> list[dict]:
        """Each provider a role can name: {'name', 'ok' and 'where' (login.login_of), 'terminal' (what /terminal/ takes;
        '': it has none), 'why' (then), 'login': its terminal's {'state' ('' / running / done / failed), 'said',
        'reopened'}}. Never a secret."""
        own, creds, out = self.providers(), login.stored(), []
        for name in [*PROVIDERS, *own]:
            ok, where = login.login_of(name, own, creds)
            why = '' if name == 'claude' else refusal(name, own)
            at = self.at.get(name)
            out.append({'name': name, 'ok': ok, 'where': where, 'why': why,
                        'terminal': 'login' if name == 'claude' else '' if why else PREFIX + name,
                        'login': at.status() if at else {'state': '', 'said': '', 'reopened': []}})
        return out
