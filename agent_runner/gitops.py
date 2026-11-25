"""Pushing finished work, and the one branch that is not pushed by a wrap-up.

The asymmetry everything here serves: an unpushed `task/<ID>` is work that exists on one disk while
nobody watches, so it is always pushed; the shared branch (`main`) is pushed only by the runner, after a
merge that passed the test gate (`[git] push_merge`), so what reaches the remote has been tested.
"""
from __future__ import annotations

import os
import subprocess
from functools import partial
from pathlib import Path

from agent_runner import freeze
from agent_runner.config import cfg, main_checkout


def git(*a: str, cwd, **kw) -> subprocess.CompletedProcess:
    """git in `cwd`, its output captured as UTF-8 text (git's own encoding; the locale's on Windows would
    garble names and fail on bytes it cannot map); `kw` goes to `subprocess.run` (env, input, timeout, …)."""
    kw.setdefault('encoding', 'utf-8')
    kw.setdefault('errors', 'replace')
    with freeze.git_step(a):
        return subprocess.run(['git', *a], cwd=str(cwd), capture_output=True, text=True, **kw)


def _git(cwd: Path):
    return partial(git, cwd=cwd)


NET_TIMEOUT = 300  # s a push or fetch may take; one that asks for a password fails at once instead


def local_urls(cwd: Path) -> list[str]:
    """`-c url.<absolute>.insteadOf=<relative>` for each remote whose URL is a relative path (`../origin.git`).
    git resolves such a path from wherever it runs, so from a slot's worktree it points nowhere; it was
    written relative to the main checkout, so that is where it is resolved. [] outside a repository."""
    try:
        main = main_checkout(cwd)
    except SystemExit:  # a plan clone's parent folder, say
        return []
    out = []
    for line in _git(cwd)('config', '--get-regexp', r'^remote\..*\.url$').stdout.splitlines():
        url = line.partition(' ')[2]
        if url.startswith(('./', '../')) and (main / url).exists():
            out += ['-c', f'url.{(main / url).resolve()}.insteadOf={url}']
    return out


def _net(cwd: Path):
    """git that talks to the remote: no stdin, no terminal or ssh prompt to wait on, NET_TIMEOUT to answer.
    A push runs under the merge lock, so one that hangs on a passphrase would stop every merge."""
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if not env.get('GIT_SSH_COMMAND') and not env.get('GIT_SSH') and _git(cwd)('config', 'core.sshCommand').returncode:
        env['GIT_SSH_COMMAND'] = 'ssh -oBatchMode=yes'
    urls = local_urls(cwd)

    def g(*a: str):
        try:
            return git(*urls, *a, cwd=cwd, stdin=subprocess.DEVNULL, env=env, timeout=NET_TIMEOUT)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(['git', *a], 124, '', f'timed out after {NET_TIMEOUT}s')
    return g


def missing_remote(cwd: Path) -> str | None:
    """`[git] push` when this repository has no remote of that name (a project downloaded without git, say),
    else None: every push then returns '' quietly, so the run and `done` say it once instead (B70)."""
    remote = cfg(cwd).push_remote
    if remote and _git(cwd)('remote', 'get-url', remote).returncode:
        return remote
    return None


def shared_name(cwd: Path, remote: str, default: str | None = 'main') -> str | None:
    """The shared branch: configured `[git] master_branch`, remote HEAD, main/master/trunk, then `default`."""
    if branch := cfg(cwd).master_branch:
        return branch
    g = _git(cwd)
    r = g('symbolic-ref', '--short', f'refs/remotes/{remote}/HEAD')
    if not r.returncode and (head := r.stdout.strip()):
        return head.split('/', 1)[-1]
    for name in ('main', 'master', 'trunk'):
        if not g('rev-parse', '--verify', '-q', f'refs/heads/{name}').returncode:
            return name
    return default


def shared_branch(cwd: Path, remote: str, branch: str) -> bool:
    """Is `branch` the one everybody reads, rather than one task's own?

    It is if the remote's HEAD names it — or, seen from a worktree, if it is what the main checkout has
    out, because that is where a run merges this work whatever it is called. In the main checkout itself
    the branch you have out is just the branch you are on.
    """
    if branch == shared_name(cwd, remote):
        return True
    main = main_checkout(cwd)
    if Path(cwd).resolve() == main:
        return False
    here = _git(main)('branch', '--show-current').stdout.strip()
    return bool(here) and branch == here


def push(cwd: Path, branch: str, shared: bool = False) -> str:
    """Push `branch` to `[git] push`, merging the remote in first if it has moved. Never fatal.

    The shared branch is refused unless `shared=True` (the runner, after a tested merge). Returns one line
    to print, or '' when there is nothing to say. It merges rather than rebases when the remote has moved:
    the worktree branches are based on these commits, and rebasing what they came from turns every later
    merge into a fight. Never for the shared branch, though: that merge would be pushed untested, so the
    runner's next merge takes the remote's commits in before its gate (`runner.upstream`).
    """
    remote = cfg(cwd).push_remote
    if not remote:
        return ''
    g, net = _git(cwd), _net(cwd)
    if g('remote', 'get-url', remote).returncode:
        return ''
    if cfg(cwd).approve:  # F98: only an approved pitch is pushed (`push_sha`)
        return ''
    if not shared and shared_branch(cwd, remote, branch):
        return ''
    if shared and cfg(cwd).pr:  # F419: only a person's merge moves it
        return f'! {branch} is not pushed: PR mode is on'
    if not (first := net('push', '-q', remote, branch)).returncode:
        return f'pushed {branch} -> {remote}'
    why = (first.stderr.strip().splitlines() or ['no message'])[-1][:200]
    if shared:
        net('fetch', '-q', remote)
        return (f'! {branch} did not push: {remote}/{branch} has moved (or refused it). Not merged here, since '
                f'that merge would go out untested: the next merge takes it in before its gate, then pushes.')
    if g('branch', '--show-current').stdout.strip() != branch:
        return f'! {branch} did not push (it is committed locally; push it by hand)'
    if net('fetch', '-q', remote).returncode:  # the remote cannot be reached: it has not "moved"
        return f'! {branch} did not push (it is committed locally): {why}'
    if g('rev-parse', '--verify', '-q', f'refs/remotes/{remote}/{branch}').returncode:
        return f'! {branch} did not push (it is committed locally): {why}'  # refused, not moved: nothing to merge
    was = g('rev-parse', 'HEAD').stdout.strip()
    _renumber(cwd, f'refs/remotes/{remote}/{branch}', branch)
    if g('merge', '--no-edit', f'{remote}/{branch}').returncode:
        g('merge', '--abort')
        g('reset', '-q', '--keep', was)  # a renumbering goes with the merge it was for
        return (f'! {branch} did not push: {remote}/{branch} has moved and merging it conflicts. '
                f'Nothing is lost — resolve it by hand, then push.')
    if net('push', '-q', remote, branch).returncode:
        return f'! {branch} did not push (it is committed locally; push it by hand)'
    return f'pushed {branch} -> {remote}, after merging {remote}/{branch} into it'


def _renumber(cwd: Path, up: str, branch: str) -> None:
    """`join.renumber_upstream` for a push from `cwd`; join and state read this module, so they load here."""
    from agent_runner import join, state
    main = main_checkout(cwd)
    if state.C is None:
        state.init(cwd)
    if Path(state.ROOT).resolve() == Path(main).resolve():  # a repository the run does not work on has no plan of its
        join.renumber_upstream(cwd, up, branch.rsplit('/', 1)[-1])


def push_sha(cwd: Path, sha: str, branch: str) -> str:
    """F98: push the shared branch up to commit `sha` to `[git] push`, fast-forward only: an approved pitch. Why it
    could not, or ''."""
    remote = cfg(cwd).push_remote
    net = _net(cwd)
    if not remote:
        return 'no push remote'
    if not (r := net('push', '-q', remote, f'{sha}:refs/heads/{branch}')).returncode:
        return ''
    net('fetch', '-q', remote)
    if not _git(cwd)('merge-base', '--is-ancestor', f'refs/remotes/{remote}/{branch}', sha).returncode:
        return (r.stderr.strip().splitlines() or ['no message'])[-1][:200]
    return (f'{remote}/{branch} has moved: the next merge takes its commits in, and goes out with that merge once '
            f'it is approved')


def drop_if_merged(cwd: Path, branch: str) -> str:
    """Delete `branch` from the remote, but only once the remote's shared branch can be seen to hold it.

    Deleting it as soon as it is merged locally would take the only remote copy of work the remote's
    `main` does not have yet (when `push_merge` is off, or the push failed). What stays on the remote is
    therefore exactly "work the shared branch has not published", never a list with something missing.
    """
    remote = cfg(cwd).push_remote
    if not remote:
        return ''
    g, net = _git(cwd), _net(cwd)
    if g('remote', 'get-url', remote).returncode:
        return ''
    net('fetch', '-q', remote)
    ref = f'refs/remotes/{remote}/{branch}'
    if g('rev-parse', '--verify', '-q', ref).returncode:
        return ''
    shared = shared_name(cwd, remote)
    if g('merge-base', '--is-ancestor', ref, f'refs/remotes/{remote}/{shared}').returncode:
        return f'kept {branch} on {remote}: {remote}/{shared} does not have the merge yet'
    if net('push', '-q', remote, '--delete', branch).returncode:
        return ''
    return f'dropped {branch} from {remote}: {remote}/{shared} has the merge now'


def drop_remote(cwd: Path, branch: str) -> str:
    """Delete `branch` from `[git] push` whatever it holds: work nobody wants any more (a dropped task's
    branch, B19). Returns one line to print, or '' when the remote has no such branch or there is none."""
    remote = cfg(cwd).push_remote
    if not remote:
        return ''
    g, net = _git(cwd), _net(cwd)
    if g('remote', 'get-url', remote).returncode:
        return ''
    if not net('ls-remote', '--exit-code', '--heads', remote, branch).stdout.strip():
        return ''
    if net('push', '-q', remote, '--delete', branch).returncode:
        return f'! {branch} could not be deleted from {remote}: delete it by hand'
    g('update-ref', '-d', f'refs/remotes/{remote}/{branch}')
    return f'deleted {branch} from {remote}'


def shell(cmd: str, cwd, env: dict | None, timeout: float) -> tuple[int | None, str]:
    """Run a project's command in a shell at `cwd` for at most `timeout` seconds: (its exit code, stdout and
    stderr), or (None, '') when it ran past and was stopped. The core of state.hook and done.gate (C16); each
    says in its own way that one ran past."""
    try:
        r = freeze.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, errors='replace',
                       env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, ''
    return r.returncode, (r.stdout or '') + (r.stderr or '')
