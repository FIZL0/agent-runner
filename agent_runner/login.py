"""F106e `run login`: the provider logins the harness loop (agent_runner/harness.mjs) runs on.

`run login` lists each provider `[models]` names (its roles, its kinds, `[models.providers]`) and whether it has
a login, and where that login is kept; never the secret. `run login <provider>` adds one through Pi's login
package (harness.mjs --login): Copilot by device code, after asking for a GitHub Enterprise domain (blank for
github.com); Codex by ChatGPT sign-in; Gemini and a custom provider by an API key. Every login is kept where Pi
keeps its own, in Pi's auth.json (`PI_CODING_AGENT_DIR`, else ~/.pi/agent), which the harness loop reads before
any env var: a custom provider's key is stored there under the provider's name, beside its key_env.

A task whose session would run on a provider with no login does not start: `park_unlogged` blocks it with
`BLOCKED: run login <provider>`, so it lists under Needs you, and a login added here reopens it.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agent_runner.config import harness_model, PROVIDERS, RUNNER

# Pi's provider id for each built-in provider the harness loop runs (harness.mjs PROVIDER_IDS)
PI_IDS = {'copilot': 'github-copilot', 'codex': 'openai-codex', 'gemini': 'google'}
# the env var Pi's login package reads a provider's key from when auth.json holds none
ENV_KEYS = {'gemini': 'GEMINI_API_KEY'}
HOW = {'copilot': 'GitHub device code', 'codex': 'ChatGPT sign-in', 'gemini': 'Gemini API key'}
HARNESS_JS = Path(__file__).with_name('harness.mjs')
# a block's why starts so: `park_unlogged` writes it, a login reopens it
WHY_HEAD = 'BLOCKED: `{cmd} login {provider}`'


def auth_file() -> Path:
    """Pi's auth.json: its logins, one credential per provider id."""
    return Path(os.environ.get('PI_CODING_AGENT_DIR') or Path.home() / '.pi' / 'agent') / 'auth.json'


def stored() -> dict:
    try:
        d = json.loads(auth_file().read_text(encoding='utf-8'))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def provider_of(model: str, providers: dict) -> str:
    """The provider a settled model runs on: '<provider>' for a harness model, else 'claude' (a bare name or
    claude's; a Pi model such as 'github-copilot/x' is Pi's own and not listed)."""
    if harness_model(model, providers):
        return model.partition(':')[0]
    return '' if '/' in model else 'claude'


def named(c) -> list[str]:
    """Each provider `[models]` names, in the order first named: its roles, its kinds, then the providers
    `[models.providers]` defines."""
    out: list[str] = []
    models = [v for k, v in c.models.items() if k != 'kinds' and isinstance(v, str)]
    models += [v for v in (c.models.get('kinds') or {}).values() if isinstance(v, str)]
    for m in models:
        if (p := provider_of(m, c.providers)) and p not in out:
            out.append(p)
    return out + [p for p in c.providers if p not in out]


def login_of(provider: str, providers: dict, creds: dict | None = None,
             env: dict | None = None) -> tuple[bool, str]:
    """(has a login, where it is kept) for `provider`; never the secret itself."""
    creds = stored() if creds is None else creds
    env = os.environ if env is None else env
    if provider == 'claude':
        return True, "Claude Code's own login (claude /login), not checked here"
    custom = providers.get(provider)
    if provider in LOCAL_NONE or (custom and not custom.get('key_env')):
        return True, 'needs none (a local model)'
    pid = provider if custom else PI_IDS.get(provider, provider)
    if isinstance(c := creds.get(pid), dict) and c:
        kind = 'OAuth' if c.get('type') == 'oauth' else 'API key' if c.get('type') == 'api_key' else 'login'
        domain = f', GitHub Enterprise {c["enterpriseUrl"]}' if provider == 'copilot' and c.get('enterpriseUrl') else ''
        return True, f'{kind} in {auth_file()} ({pid}{domain})'
    var = custom.get('key_env') if custom else ENV_KEYS.get(provider)
    if var and env.get(var):
        return True, f'env {var}'
    return False, f'no login: {RUNNER} login {provider}'


LOCAL_NONE = ('ollama',)


def missing(model: str, c) -> str:
    """The provider a session on `model` (a settled one) runs on, when it has no login; '' when it has one, or
    it is no harness model."""
    if not harness_model(model, c.providers):
        return ''
    provider = model.partition(':')[0]
    return '' if login_of(provider, c.providers)[0] else provider


def why_for(provider: str, tid: str) -> str:
    return (WHY_HEAD.format(cmd=RUNNER, provider=provider) + f': {tid} runs on {provider}, which has no login '
            f'here; run it on this machine and {tid} starts again')


def park_unlogged(tid: str, model: str, branch: str) -> bool:
    """F106e: when `tid`'s session (on `model`) would run on a provider with no login, block it on the person
    with `run login <provider>` instead of starting it, committed as the runner commits a block (sched's
    `block_parked`: MERGE free, TODO.md clean). True when it is held back: the caller starts nothing and marks
    it tried, so the next pick takes another task. Blocked, it comes back once it is unblocked (the run's
    `retry_reopened`); not blocked yet (a merge holds the plan, TODO.md has edits), `retry_held` hands it back
    after HELD_RETRY s."""
    from agent_runner import state
    if not (provider := missing(model, state.C)):
        return False
    HELD[tid] = time.time()
    if park_now(tid, provider, branch):
        HELD.pop(tid, None)
    return True


HELD: dict[str, float] = {}  # task id: when the run held it back without blocking it
HELD_RETRY = 60


def retry_held(now: float | None = None) -> set[str]:
    """The tasks held back without a block HELD_RETRY s ago or more: the run takes them out of its tried set."""
    now = time.time() if now is None else now
    due = {t for t, at in HELD.items() if now - at >= HELD_RETRY}
    for t in due:
        HELD.pop(t)
    return due


def park_now(tid: str, provider: str, branch: str) -> bool:
    """Block `tid` on `run login <provider>` and commit it; False when that cannot be done now."""
    from agent_runner import state
    from contextlib import ExitStack
    from agent_runner import plan as P, plansync
    from agent_runner.state import commit_plan, git, log, MERGE, plan_rel
    if not MERGE.acquire(blocking=False):
        return False
    hold = ExitStack()
    try:
        C, root = state.C, state.ROOT
        if C.plan_external:
            hold.enter_context(plansync.locked(C))
            plansync.pull(C, force=True)
        rel = plan_rel('TODO.md')
        if not C.plan_external and (git('status', '--porcelain', '--', rel).stdout.strip() or branch and
                                    git('branch', '--show-current').stdout.strip() != branch):
            return False
        try:
            P.block(tid, why_for(provider, tid), todo=root / rel, after=[])
        except SystemExit:
            return True  # ticked or dropped meanwhile
        if not commit_plan(f'Plan: block {tid}, {provider} has no login', rel):
            if not C.plan_external:
                git('checkout', '-q', '--', rel)
            return False
        log(f'{tid}: not started: {provider} has no login; `{RUNNER} login {provider}` is under Needs you')
        return True
    finally:
        hold.close()
        MERGE.release()


def unlogged(tid: str, branch: str, model: str) -> bool:
    """The run's check before it starts `tid` (`model` is `[models] code`): `park_unlogged` on the model its
    session would run on (slots.task_model)."""
    from agent_runner.slots import task_model
    return park_unlogged(tid, task_model(tid, model, branch), branch)


def reopen_for(provider: str) -> list[str]:
    """After a login: unblock every task `park_unlogged` blocked for `provider` (the plan's own tool, so the
    unblock is committed as any `plan unblock` is). The ids reopened."""
    from agent_runner import plan as P
    mark = f' login {provider}`: '  # the run that blocked it may name the runner another way (./run, agent-runner)
    try:
        ids = [a[1] for a in P.asks(all=True) if a[0] == 'BLOCKED' and a[3].startswith('`') and mark in a[3]]
    except (OSError, SystemExit):
        return []
    out = []
    for tid in ids:
        try:
            if P.main(['unblock', tid, f'{provider} has a login now']) == 0:
                out.append(tid)
        except SystemExit:
            pass
    return out


def harness_login(provider: str, custom: dict | None, enterprise: str | None,
                  ask=None, secret=None, say=print) -> tuple[bool, str]:
    """Run harness.mjs --login for `provider`, answering its questions here; (saved, where or why not)."""
    argv = [shutil.which('node') or 'node', str(HARNESS_JS), '--login', provider]
    if custom:
        argv += ['--provider', json.dumps(custom)]
    if enterprise is not None:
        argv += ['--enterprise', enterprise]
    try:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    except OSError as e:
        return False, f'node did not start ({e}); the harness loop needs Node on PATH'
    saved = ''
    assert p.stdout and p.stdin
    for line in p.stdout:
        try:
            m = json.loads(line)
        except ValueError:
            say(line.rstrip('\n'))  # npm installing the login package, once
            continue
        if not isinstance(m, dict):
            continue
        if 'say' in m:
            say(m['say'])
        elif 'saved' in m:
            saved = m.get('file', '')
        elif q := m.get('ask'):
            answer = answer_prompt(q, ask or input, secret or getpass.getpass, say)
            p.stdin.write(json.dumps({'answer': answer}) + '\n')
            p.stdin.flush()
    p.stdin.close()
    code = p.wait()
    if code or not saved:
        return False, f'the login did not finish (harness.mjs --login exited {code})'
    return True, saved


def answer_prompt(q: dict, ask, secret, say) -> str | None:
    msg = q.get('message') or 'Answer'
    try:
        if q.get('type') == 'select':
            opts = q.get('options') or []
            say(msg)
            for o in opts:
                say(f'  {o.get("id")}  {o.get("label")}')
            got = ask('Type one of the ids above: ').strip()
            return got if any(o.get('id') == got for o in opts) else None
        if q.get('type') == 'secret':
            return secret(f'{msg}: ')
        hint = f' ({q["placeholder"]})' if q.get('placeholder') else ''
        return ask(f'{msg}{hint}: ')
    except (EOFError, KeyboardInterrupt):
        return None


def list_lines(c) -> list[str]:
    names = named(c)
    if not names:
        return ['[models] names no provider.']
    creds, width = stored(), max(len(n) for n in names)
    out = []
    for n in names:
        ok, where = login_of(n, c.providers, creds)
        out.append(f'{n.ljust(width)}  {"✓" if ok else "✗"} {where}')
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog=f'{RUNNER} login', description=(
        'The provider logins the harness loop runs on. With no provider: each provider [models] names and '
        'whether it has a login (and where it is kept, never the secret). With one: add its login through '
        "Pi's login package."))
    ap.add_argument('provider', nargs='?', help='copilot, codex, gemini, or one of [models.providers]')
    ap.add_argument('--enterprise', metavar='DOMAIN', default=None,
                    help='copilot: your GitHub Enterprise domain (company.ghe.com); "" for github.com. Asked when left out')
    a = ap.parse_args(argv)
    from agent_runner.config import cfg
    c = cfg()
    if not a.provider:
        print('\n'.join(list_lines(c)))
        return 0
    name = a.provider
    if name == 'claude':
        print("claude runs as Claude Code, on Claude Code's own login: `claude /login`.")
        return 0
    custom = c.providers.get(name)
    if name not in PROVIDERS and not custom:
        print(f'{RUNNER} login: no provider {name}: use one of {", ".join([*PROVIDERS, *c.providers])}, '
              f'or define it in [models.providers.{name}]', file=sys.stderr)
        return 2
    if name in LOCAL_NONE or (custom and not custom.get('key_env')):
        print(f'{name} is a local provider: it needs no login.')
        return 0
    enterprise = a.enterprise
    if name == 'copilot' and enterprise is None:
        try:
            enterprise = input('GitHub Enterprise domain (blank for github.com): ').strip()
        except EOFError:
            enterprise = ''
    if name != 'copilot' and enterprise is not None:
        print(f'{RUNNER} login: --enterprise is for copilot only', file=sys.stderr)
        return 2
    print(f'{name}: {HOW.get(name, "API key, kept for " + (custom or {}).get("key_env", name))}')
    ok, where = harness_login(name, custom, enterprise)
    if not ok:
        print(f'{RUNNER} login {name}: {where}', file=sys.stderr)
        return 1
    print(f'{name}: logged in; kept in {where}')
    if back := reopen_for(name):
        print(f'reopened {", ".join(back)}, blocked until {name} had a login')
    return 0
