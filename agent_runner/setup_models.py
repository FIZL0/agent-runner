"""F406d: `agent-runner setup` asks which providers to use, logs in to each, and writes [models] code and fix.

At a terminal it lists the built-in providers with what is found and logged in here. The person picks; each pick is
logged in there (`run login PROVIDER`; `claude auth login` for Claude Code), and [models] code and fix are written to
this machine's runner.local.toml for the first pick. A kind ([models.kinds]) on another provider goes to the pick too:
it would win over `code`. Nothing picked changes nothing; no terminal asks nothing and gives the login commands.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from agent_runner import config as CF
from agent_runner import login, provider_login
from agent_runner.config import RUNNER
from agent_runner.watch import LOGIN_CMD

NAMES = {'claude': 'Claude Code', 'copilot': 'GitHub Copilot', 'codex': 'Codex', 'gemini': 'Gemini', 'ollama': 'Ollama'}
HINTS = {'copilot': 'github.com or a GitHub Enterprise domain', 'codex': 'ChatGPT sign-in', 'gemini': 'API key'}
INSTALL = 'https://claude.com/claude-code'
STATUS_WAIT = 15  # s `claude auth status` may take


def config(root: Path):
    """The repo's settings, None when they cannot be read."""
    try:
        return CF.cfg(root)
    except (Exception, SystemExit):
        return None


def claude_program(root: Path) -> str:
    """The Claude Code program setup starts ([run] agent, else `claude`), as a path; '' when this machine has none."""
    c = config(root)
    agent = c.run['agent'] if c else 'claude'
    if not isinstance(agent, str) or CF.agent_problem(root, agent):
        return ''
    if found := shutil.which(agent):
        return found
    return agent if Path(agent).is_absolute() else str(CF.main_checkout(root) / agent)


def claude_state(program: str) -> str:
    """'in', 'out' or '' (cannot be told): does Claude Code have a login? Asked of the program itself."""
    try:
        r = subprocess.run([program, *LOGIN_CMD.split()[1:-1], 'status'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL, timeout=STATUS_WAIT)
        return 'in' if json.loads(r.stdout)['loggedIn'] else 'out'
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return ''


def rows(root: Path, providers: dict) -> list[tuple[str, bool, str]]:
    """Each built-in provider: (name, needs no login now, what is said of it)."""
    out, creds = [], login.stored()
    for p in CF.PROVIDERS:
        if p == 'claude':
            program = claude_program(root)
            state = claude_state(program) if program else ''
            said = {'in': 'found, logged in', 'out': 'found, not logged in'}.get(state, 'found') if program else \
                'not found on this machine'
            out.append((p, state == 'in', said))
            continue
        ok, where = login.login_of(p, providers, creds)
        if ok:
            said = where if where.startswith('needs none') else f'logged in: {where}'
        else:
            said = f'not logged in ({HINTS[p]})' if p in HINTS else 'not logged in'
        out.append((p, ok, said))
    return out


def commands() -> str:
    """The line for a setup with no terminal."""
    names = [p for p in CF.PROVIDERS if p != 'claude' and not login.needs_none(p, {})]
    said = [f'`{RUNNER} login {p}`' + (' (a GitHub Enterprise domain: `--enterprise company.ghe.com`)'
                                      if p == 'copilot' else '') for p in names]
    return f'log in to the providers you use: `{LOGIN_CMD}` (Claude Code), {", ".join(said)}'


def picked(text: str) -> list[str] | None:
    """The providers `text` names, by number or name, in its order; None when a word is neither."""
    out: list[str] = []
    for w in re.split(r'[\s,]+', text.strip().lower()):
        if w.isdecimal() and 0 < int(w) <= len(CF.PROVIDERS):
            w = CF.PROVIDERS[int(w) - 1]
        if w and w not in CF.PROVIDERS:
            return None
        if w and w not in out:
            out.append(w)
    return out


def ask_domain() -> str:
    """Copilot's GitHub Enterprise domain as a bare host, '' for github.com."""
    while True:
        got = input('GitHub Enterprise domain (blank for github.com): ').strip()
        got = re.sub(r'^https?://', '', got, flags=re.I).rstrip('/').lower()
        if got in ('', 'github.com'):
            return ''
        if len(got) <= 253 and provider_login.HOST.fullmatch(got):
            return got
        print(f'  {provider_login.NO_HOST}')


def log_in(root: Path, provider: str) -> str:
    """Log in to `provider` in this terminal; the line that says how it went."""
    if provider == 'claude':
        program = claude_program(root)
        if not program:
            return f'Claude Code is not found: install it ({INSTALL}), then run setup again'
        argv, shown = [program, *LOGIN_CMD.split()[1:]], LOGIN_CMD
    else:
        words = provider_login.words(provider, ask_domain() if provider == 'copilot' else '')
        argv, shown = [*CF.runner_cmd(), *words], f'{RUNNER} login {provider}'
    try:
        code = subprocess.run(argv, cwd=str(root)).returncode
        why = f'exit {code}'
    except OSError as e:
        code, why = 127, str(e)
    except KeyboardInterrupt:
        code, why = 130, 'interrupted'
    return f'{NAMES[provider]} is not logged in: `{shown}` failed ({why})' if code else f'{NAMES[provider]}: logged in'


def ask_model(provider: str, models: dict, providers: dict) -> tuple[str, str]:
    """([models] code, fix) for `provider`: what is set on it now, else Claude's default, else asked; '' for none."""
    now = {r: m for r in ('code', 'fix') if isinstance(m := models.get(r), str)
           and login.provider_of(m, providers) == provider}
    if provider == 'claude':
        d = CF.DEFAULTS['models']
        return now.get('code', d['code']), now.get('fix', d['fix'])
    had = now.get('code', '').partition(':')[2]
    got = input(f'Model id for tasks on {NAMES[provider]}' + (f' (Enter: {had})' if had else '') + ': ').strip()
    got = got.removeprefix(f'{provider}:').strip() or had
    if not got:
        return '', ''
    return f'{provider}:{got}', now['fix'] if got == had and 'fix' in now else f'{provider}:{got}'


def write(root: Path, provider: str, code: str, fix: str, models: dict, providers: dict) -> str:
    """Write [models] for the pick to runner.local.toml; the line that says so."""
    base = CF.DEFAULTS['models']['kinds']
    kinds = {**base, **(models.get('kinds') or {})}
    to = {k: v if login.provider_of(v, providers) == provider else
          base.get(k, code) if provider == 'claude' else code for k, v in kinds.items()}
    try:
        if provider in CF.LOCAL_PROVIDERS:
            CF.save_local_setting(root, 'models', 'local', True)
        CF.save_local_setting(root, 'models', 'code', code)
        CF.save_local_setting(root, 'models', 'fix', fix)
        if to != kinds:  # a kind wins over `code`, and the defaults name Claude's
            CF.save_local_setting(root, 'models', 'kinds', to)
    except (OSError, ValueError, SystemExit) as e:
        return f'[models] is not all written to {CF.LOCAL}: {e}'
    return f'{CF.LOCAL}: [models] code = "{code}", fix = "{fix}"' + (', and every kind of task on it' if to != kinds else '')


def offer(root: Path, terminal: bool) -> list[str]:
    """Ask, log in and write; the lines to say about it. Never fails setup: Ctrl-C ends the questions."""
    if not terminal:
        return [commands()]
    c = config(root)
    models, providers = (c.models, c.providers) if c else (CF.DEFAULTS['models'], {})
    said: list[str] = []
    try:
        table = rows(root, providers)
        print('\nWhich providers should tasks run on?')
        for n, (p, _, what) in enumerate(table, 1):
            print(f'  {n}  {NAMES[p].ljust(14)}  {what}')
        while (picks := picked(input('Numbers or names; the first runs the tasks (Enter: change nothing): '))) is None:
            print(f'  Use 1 to {len(table)}, or {", ".join(CF.PROVIDERS)}')
        if not picks:
            return ['no provider picked: logins and [models] are as they were']
        has = {p: ok for p, ok, _ in table}
        for p in picks:
            said.append(f'{NAMES[p]}: {"needs no login" if login.needs_none(p, {}) else "already logged in"}'
                        if has[p] else log_in(root, p))
        if 'claude' in picks and not claude_program(root):  # no session on it can start here
            picks.remove('claude')
        if not picks:
            return said
        code, fix = ask_model(picks[0], models, providers)
        said.append(write(root, picks[0], code, fix, models, providers) if code else
                    f'no model given for {NAMES[picks[0]]}: set [models] code and fix in {CF.LOCAL}')
    except (EOFError, KeyboardInterrupt):
        print()
        said.append('the provider questions were ended: run setup again to go on with them')
    return said
