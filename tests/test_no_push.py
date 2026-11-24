#!/usr/bin/env python3
"""F400: the no-push policy ([git] no_push): the runner pushes nothing, and git refuses every push in a session.

    python3 tests/test_no_push.py        (temp repos with local remotes, a few seconds; every OS)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import cmds, config as CF, control, gitops, loop, no_push as N, plan as P, plansync  # noqa: E402
from agent_runner import runner as R, slots, tools  # noqa: E402


def head(bare: Path, branch: str = 'main') -> str:
    r = subprocess.run(['git', 'rev-parse', '-q', '--verify', f'refs/heads/{branch}'], cwd=bare, capture_output=True, text=True)
    return r.stdout.strip()


def make(tmp: Path, name: str) -> tuple[Path, Path]:
    repo, bare = tmp / name, tmp / f'{name}.git'
    repo.mkdir()
    git(tmp, 'init', '-q', '--bare', '-b', 'main', str(bare))
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **T1** one | files: a.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'remote', 'add', 'origin', str(bare))
    configure(repo, False)
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    return repo, bare


def configure(repo: Path, on: bool, more: str = '') -> None:
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n' + more +
                                      ('[git]\nno_push = true\n' if on else ''), encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'settings', '--allow-empty')
    CF._cfg.cache_clear()
    R.init(repo)


def session(env: dict, cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)


def refused(r, label: str) -> None:
    check(r.returncode != 0 and N.REFUSED in r.stderr, label, r.stdout + r.stderr)


def task_env(n: int | None) -> dict:
    return {**os.environ, **slots.env_vars(slots.slot_env(n))}


def test_off(repo: Path, bare: Path) -> None:
    configure(repo, False)
    eq((CF.DEFAULTS['git']['no_push'], R.C.no_push, R.C.push_remote, R.C.push_merge), (False, False, 'origin', True),
       'off by default: the push remote and push_merge are as ever')
    for label, env in (('task', task_env(1)), ('repair', task_env(None)), ('control', control.control_env())):
        check(N.ENV not in env and not any(k.startswith('GIT_CONFIG_KEY') for k in env), f'nothing in a {label} session')
        eq(session(env, repo, 'git', 'push', '-q', 'origin', 'main').returncode, 0, f'a {label} session may push')
    with mock.patch.object(N, 'problem', lambda _: 'old git'):
        N.require(R.C, repo)  # off: no git is too old
    check(not CF.setting_problem('git', 'no_push', True) and CF.setting_problem('git', 'no_push', 'x'), 'a switch')


def test_sessions(repo: Path, bare: Path, other: Path, other_bare: Path) -> None:
    configure(repo, True)
    was, was_other = head(bare), head(other_bare)
    (other / 'x').write_text('x', encoding='utf-8')
    git(other, 'add', '-A')
    git(other, 'commit', '-qm', 'x')
    for label, env in (('task', task_env(1)), ('repair', task_env(None)), ('control', control.control_env())):
        refused(session(env, repo, 'git', 'push', 'origin', 'main'), f'{label}: git push here')
        refused(session(env, other, 'git', 'push'), f'{label}: git push in another repository')
        refused(session(env, repo, 'git', '-C', str(other), 'push', '--no-verify', str(other_bare), 'HEAD:main'),
                f'{label}: -C, --no-verify and a path for the remote')
        refused(session(env, other, 'git', 'push', '--recurse-submodules=no'), f'{label}: the option of the same key')
        refused(session(env, other, 'git', '-c', f'{N.KEY}=no', 'push'), f'{label}: -c with the key')
        refused(session(env, other, 'git', '-c', 'alias.up=push', 'up'), f'{label}: an alias')
        refused(session(env, other, sys.executable, '-c',  # a script's git, as a Windows shell or build tool runs it
                        'import subprocess, sys; sys.exit(subprocess.call(["git", "push"]))'), f'{label}: a child process')
    git(other, 'config', N.KEY, 'no')
    git(other, 'config', 'remote.origin.pushurl', str(other_bare))
    refused(session(env, other, 'git', 'push'), "a repository's own config and push URL")
    git(other, 'config', '--unset', N.KEY)
    git(other, 'config', '--unset', 'remote.origin.pushurl')
    eq((head(bare), head(other_bare)), (was, was_other), 'nothing reached either remote')
    for args in (('fetch', 'origin'), ('pull', '-q', 'origin', 'main'), ('commit', '-q', '--allow-empty', '-m', 'y'),
                 ('submodule', 'update', '--init'), ('fetch', '--recurse-submodules'), ('status',)):
        r = session(env, other, 'git', *args)
        eq(r.returncode, 0, f'git {args[0]} works as ever: {r.stderr}')
    check(slots.fence_argv()[-1] == '0', 'the git fence refuses a push in every repository too')


def test_config_kept(repo: Path) -> None:
    base = {'A': '1', 'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'user.name', 'GIT_CONFIG_VALUE_0': 'Ann'}
    on = {**base, **N.env(base)}
    eq((on['GIT_CONFIG_COUNT'], on['GIT_CONFIG_VALUE_0'], on['GIT_CONFIG_KEY_1']), ('2', 'Ann', N.KEY),
       "git config the environment carries is kept")
    eq({**on, **N.env(on)}, on, 'a session in a session: once')
    eq(N.env({'GIT_CONFIG_COUNT': 'x'})['GIT_CONFIG_COUNT'], '1', 'a broken count is replaced')
    configure(repo, True, 'slot_env = ["GIT_CONFIG_COUNT=1", "GIT_CONFIG_KEY_0=user.name", "GIT_CONFIG_VALUE_0=Ann"]\n')
    env = task_env(1)
    eq(session(env, repo, 'git', 'config', 'user.name').stdout.strip(), 'Ann', "slot_env's git config still holds")
    refused(session(env, repo, 'git', 'push'), 'and cannot displace the policy')


def test_runner(repo: Path, bare: Path, tmp: Path) -> None:
    configure(repo, True)
    was = head(bare)
    eq((R.C.push_remote, R.C.push_merge, R.C.approve), (None, False, False), 'no push remote, so nothing to push or approve')
    git(repo, 'branch', '-f', 'task/T1')
    eq((gitops.push(repo, 'main', shared=True), gitops.push(repo, 'task/T1')), ('', ''), 'no merge and no task branch')
    eq(P._push(repo), '', 'no plan edit')
    eq((head(bare), head(bare, 'task/T1')), (was, ''), 'the remote is as it was')
    eq((plansync.store(R.C), plansync.claim(R.C, 'T1')), (None, True), 'no claims: a task starts without one')
    check('Pushing is off' in R.prompt_for('T1', 1, 1, repo, 'main'), 'the brief says so')
    from types import SimpleNamespace
    clone, pbare = make(tmp, 'plan')  # a plan repository: committed in the clone, never pushed
    R.init(repo)
    c = SimpleNamespace(plan_repo=str(pbare), plan_dir=clone, no_push=True, todo=clone / 'plan/TODO.md',
                        done=clone / 'plan/DONE.md', root=repo, notes=R.C.notes)
    before = head(pbare)
    (clone / 'plan/TODO.md').write_text('# TODO\n', encoding='utf-8')
    eq((plansync.publish(c, 'edit'), head(pbare)), ('', before), 'a plan repository edit is not pushed')
    eq(git(clone, 'status', '--porcelain').strip(), '', 'but is committed')
    eq(plansync.store(c), None, 'and has no claims')


def test_inherited(repo: Path, other: Path) -> None:
    """A session's `done` or `plan` in a project without the policy."""
    R.init(other)
    with mock.patch.dict(os.environ, N.env(dict(os.environ))):
        eq(CF.cfg(other).push_remote, None, "the runner's commands there push nothing either")
        eq(gitops.push(other, 'main', shared=True), '', 'no push to try')
        refused(session(task_env(1), other, 'git', 'push'), 'its sessions are still refused')
        N.require(R.C, other)
        eq(CF.cfg(other).push_remote, None, 'a run started from that session keeps the policy')
        check('no-push policy' in (tools.fence('Bash', {'command': 'git push'}, other, other, other, other, other, False) or ''),
              'the git fence names the policy')


def test_old_git(repo: Path) -> None:
    configure(repo, True)
    eq(N.problem(repo), '', 'this git holds the policy')
    with mock.patch.object(N, 'env', lambda base: {}):  # a git that does not read GIT_CONFIG_COUNT
        check('git 2.31' in N.problem(repo), 'one that does not is told of')
        past = mock.Mock(side_effect=RuntimeError('went on'))  # a check that does not hold starts no real session
        cwd = os.getcwd()
        os.chdir(repo)
        try:
            with mock.patch.object(loop, 'wait_last_run', past), mock.patch.object(cmds, 'free_control_number', past):
                for what, go in (('a run', lambda: loop.run([], 'run')), ('a control session', lambda: cmds.cmd_control([]))):
                    try:
                        go()
                        check(False, f'{what} is refused')
                    except (SystemExit, RuntimeError) as e:
                        check('nothing was started' in str(e), f'{what} is refused', e)
        finally:
            os.chdir(cwd)


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo, bare = make(tmp, 'proj')
        other, other_bare = make(tmp, 'other')
        return report([lambda: test_off(repo, bare), lambda: test_sessions(repo, bare, other, other_bare),
                       lambda: test_config_kept(repo), lambda: test_runner(repo, bare, tmp),
                       lambda: test_inherited(repo, other), lambda: test_old_git(repo)])


if __name__ == '__main__':
    sys.exit(main())
