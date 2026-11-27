"""F466c: a Login's 2FA code, asked of the person while the agent's command waits; and the block for a missing Login.

`run login code NAME "why"` (in a task's worktree) writes the task's ask file with one code field (6 digits), blocks the
task so it lists under Needs you (which sends the push), and waits, with a deadline, for the person to enter the code.
What they enter lands in the task's ask env file (asks.keep_secrets, 0600, git-ignored) as LOGIN_CODE; this command
takes it from there once, prints it for the agent and removes it: a code is used once, and one older than five minutes
is thrown away. The code is never written to run.log, the plan or a note: the answer's note names only the file.

A Login the task needs that does not exist: `run login code` (or `missing_why`) gives the block line, with a link
straight to the Tools page's Login form with its name and 'what it is for' filled in.
"""
from __future__ import annotations

import os
import re
import subprocess as sp
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

ENV = 'LOGIN_CODE'
KEEP = 300          # seconds an entered code is good for
WAIT = 600          # seconds the command waits for one by default
CODE = re.compile(r'[0-9]{6}')
FORM_HASH = 'login-add'  # agent_runner/page/132-login-link.js opens the form for #login-add?name=…&for=…


def form_link(name: str, purpose: str = '', base: str | None = None) -> str:
    """The run app's Tools page with the Login form open, name and 'what it is for' filled in ('' with no run app)."""
    if base is None:
        from agent_runner import devices
        base = devices.tools_link()
    if not base:
        return ''
    q = urlencode({'name': name, 'for': purpose}, quote_via=quote)
    return f'{base.partition("#")[0]}#{FORM_HASH}?{q}'


def missing_why(name: str, purpose: str = '', base: str | None = None) -> str:
    """The `done --blocked` line for a Login that does not exist: what the person does, then the form's link."""
    head = f'BLOCKED: Add the login {name} on the Login form, so the agent can sign in'
    link = form_link(name, purpose, base)
    return f'{head}: {link}' if link else f'{head} (Tools page, Add…, Login)'


def ask(name: str, why: str, twofa: str = '') -> dict:
    """The ask file for a code: one secret field of 6 digits."""
    where = f' ({twofa})' if twofa else ''
    return {'summary': f'Enter the 2FA code for the login {name}{where}, so the agent can sign in: {why}'[:300],
            'where': twofa or 'where the login sends its codes',
            'steps': ['Wait for the 6-digit code to arrive', 'Type it in the code field', 'Send it within 5 minutes'],
            'inputs': [{'key': 'code', 'label': f'2FA code for {name}', 'kind': 'secret', 'env': ENV,
                        'match': '^[0-9]{6}$', 'hint': '6 digits'}]}


def block_line(name: str) -> str:
    return f'BLOCKED: Enter the 2FA code for the login {name}; the agent is waiting to sign in'


def take(env_file: Path, now: float | None = None) -> tuple[str | None, str]:
    """(the code, '') once, and it is gone from the file; (None, why) when there is none, it expired or is malformed
    (those are removed too)."""
    try:
        text = env_file.read_text(encoding='utf-8')
        at = env_file.stat().st_mtime
    except OSError:
        return None, 'none yet'
    import shlex
    keep, got = [], None
    for line in text.splitlines():
        k, _, v = line.partition('=')
        if k == ENV:
            try:
                got = (shlex.split(v) or [''])[0]
            except ValueError:
                got = ''
        else:
            keep.append(line)
    if got is None:
        return None, 'none yet'
    _rewrite(env_file, keep)
    if (now if now is not None else time.time()) - at > KEEP:
        return None, 'expired'
    if not CODE.fullmatch(got):
        return None, 'not 6 digits'
    return got, ''


def _rewrite(f: Path, lines: list[str]) -> None:
    if not lines:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_name(f'.{f.stem}.code.tmp')
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as h:
        h.write(''.join(f'{x}\n' for x in lines))
    os.replace(tmp, f)


def wait(env_file: Path, deadline: float, every: float = 2.0, clock=time.time, sleep=time.sleep) -> tuple[str | None, str]:
    """Poll for the code until `deadline`; an expired one is dropped and the wait goes on."""
    why = 'none yet'
    while True:
        code, why = take(env_file, clock())
        if code:
            return code, ''
        if clock() >= deadline:
            return None, 'no code came before the deadline' if why == 'none yet' else f'{why}; the deadline passed'
        sleep(every)


def task_here(cwd: Path | None = None) -> str:
    """The task this worktree is on (branch task/<ID>), '' elsewhere."""
    try:
        b = sp.run(['git', 'branch', '--show-current'], cwd=cwd, capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, sp.SubprocessError):
        return ''
    return b.removeprefix('task/') if b.startswith('task/') else ''


def run(name: str, why: str, tid: str = '', wait_s: float = WAIT) -> int:
    """`run login code NAME "why"`: ask, block, wait, print the code once."""
    import json
    from agent_runner import asks, secret_logins as L, state as S
    lg = L.load().get(name)
    if not lg:
        print(f'{L.RUNNER} login: there is no login {name}. Block the task with this line:\n'
              f'{missing_why(name, why)}', file=sys.stderr)
        return 3
    tid = tid or task_here()
    if not tid:
        print(f'{L.RUNNER} login code: run it in a task\'s worktree (branch task/<ID>), or give --task ID', file=sys.stderr)
        return 2
    c = S.cfg()
    env = asks.env_file(tid, c)
    take(env)  # an old code is never used for a new ask
    f = asks.ask_file(tid, c)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(ask(name, why, lg.get('twofa', '')), indent=1), encoding='utf-8')
    r = sp.run([sys.executable, '-m', 'agent_runner', 'plan', 'block', tid, block_line(name)],
               capture_output=True, text=True)
    if r.returncode:
        print(f'{L.RUNNER} login code: could not list it under Needs you: {(r.stderr or r.stdout).strip()}', file=sys.stderr)
        return 1
    print(f'waiting up to {int(wait_s)}s for the 2FA code for {name} (Needs you)...', file=sys.stderr)
    code, no = wait(env, time.time() + wait_s)
    if not code:
        print(f'{L.RUNNER} login code: {no}; the task stays under Needs you', file=sys.stderr)
        return 1
    print(code)
    return 0
