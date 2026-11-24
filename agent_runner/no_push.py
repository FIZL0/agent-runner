"""F400: the no-push policy, `[git] no_push`, for a project that must not publish.

The runner's own pushes stop in `Config.push_remote` and `plansync.publish`. Every session the runner starts (task,
repair, control, one-shot) gets `env` in its environment: git reads config from GIT_CONFIG_COUNT and its numbered
KEY/VALUE pairs on every OS, in every repository, and dies on a push.recurseSubmodules value it does not know.
Only `git push` reads that key, before it looks at its options, so neither `--no-verify`, `-c`, a push URL nor a
repository's own config gets around it, and fetch, pull, clone and commit are as ever.

It holds an agent that follows its brief, not one set on getting out: see docs/REFERENCE.md for its limits.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV = 'AGENT_RUNNER_NO_PUSH'  # set in a session under the policy: the runner's own commands there push nothing either
KEY = 'push.recurseSubmodules'
REFUSED = 'blocked by the no-push policy ([git] no_push)'  # git's refusal quotes it


def active() -> bool:
    """This process runs in a session under the policy."""
    return bool(os.environ.get(ENV))


def _count(env: dict) -> int:
    try:
        return max(0, int(env.get('GIT_CONFIG_COUNT') or 0))
    except ValueError:  # git refuses every command with such a count; ours replaces it
        return 0


def _entries(env: dict) -> list[tuple[str, str]]:
    return [(env.get(f'GIT_CONFIG_KEY_{i}', ''), env.get(f'GIT_CONFIG_VALUE_{i}', '')) for i in range(_count(env))]


def env(base: dict) -> dict[str, str]:
    """What to add to the environment `base` for the policy; the git config `base` carries already is kept."""
    have = _entries(base)
    if (KEY, REFUSED) in have:
        return {ENV: '1'}
    n = len(have)
    return {ENV: '1', 'GIT_CONFIG_COUNT': str(n + 1), f'GIT_CONFIG_KEY_{n}': KEY, f'GIT_CONFIG_VALUE_{n}': REFUSED}


def without(base: dict) -> dict[str, str]:
    """`base` with the policy taken out, other git config kept."""
    if not base.get(ENV) and (KEY, REFUSED) not in _entries(base):
        return dict(base)
    n, keep = _count(base), [e for e in _entries(base) if e != (KEY, REFUSED)]
    drop = {ENV, 'GIT_CONFIG_COUNT'} | {f'GIT_CONFIG_{w}_{i}' for i in range(n) for w in ('KEY', 'VALUE')}
    out = {k: v for k, v in base.items() if k not in drop}
    if keep:
        out['GIT_CONFIG_COUNT'] = str(len(keep))
        for i, (k, v) in enumerate(keep):
            out[f'GIT_CONFIG_KEY_{i}'], out[f'GIT_CONFIG_VALUE_{i}'] = k, v
    return out


def drop() -> None:
    """Out of this process: a run started from a session under the policy follows its own project's setting."""
    new = without(dict(os.environ))
    for k in [k for k in os.environ if k not in new]:
        del os.environ[k]
    os.environ.update(new)


def problem(cwd: Path) -> str:
    """Why this machine's git would not hold the policy (before 2.31 it does not read GIT_CONFIG_COUNT), else ''."""
    from agent_runner.gitops import git
    base = dict(os.environ)
    r = git('push', '--dry-run', '.', 'HEAD:refs/agent-runner/no-push-check', cwd=cwd, env={**base, **env(base)})
    if r.returncode and REFUSED in r.stderr:
        return ''
    return '[git] no_push is on, but git here does not refuse a push (it needs git 2.31 or newer): nothing was started'


def require(c, root: Path) -> None:
    """Refuse to start anything under a policy git here would not hold."""
    if c.no_push and (why := problem(root)):
        raise SystemExit(why)


def start_run(c, root: Path) -> None:
    """A run's start: an inherited policy goes, and this project's own must hold."""
    drop()
    require(c, root)
