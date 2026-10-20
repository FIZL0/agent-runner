"""Pushing finished work, and the one branch that is not pushed by a wrap-up.

The asymmetry everything here serves: an unpushed `task/<ID>` is work that exists on one disk while
nobody watches, so it is always pushed; the shared branch (`main`) is pushed only by the runner, after a
merge that passed the test gate (`[git] push_merge`), so what reaches the remote has been tested.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from agent_runner.config import cfg, main_checkout


def _git(cwd: Path):
    def g(*a: str):
        return subprocess.run(['git', *a], cwd=str(cwd), capture_output=True, text=True)
    return g


def shared_name(cwd: Path, remote: str) -> str:
    """The branch everybody reads: what the remote's HEAD points at, else main/master/trunk."""
    g = _git(cwd)
    r = g('symbolic-ref', '--short', f'refs/remotes/{remote}/HEAD')
    if not r.returncode and (head := r.stdout.strip()):
        return head.split('/', 1)[-1]
    for name in ('main', 'master', 'trunk'):
        if not g('rev-parse', '--verify', '-q', f'refs/heads/{name}').returncode:
            return name
    return 'main'


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
    merge into a fight.
    """
    remote = cfg(cwd).push_remote
    if not remote:
        return ''
    g = _git(cwd)
    if g('remote', 'get-url', remote).returncode:
        return ''
    if not shared and shared_branch(cwd, remote, branch):
        return ''
    if not g('push', '-q', remote, branch).returncode:
        return f'pushed {branch} → {remote}'
    if g('branch', '--show-current').stdout.strip() != branch:
        return f'! {branch} did not push (it is committed locally; push it by hand)'
    g('fetch', '-q', remote)
    if g('merge', '--no-edit', f'{remote}/{branch}').returncode:
        g('merge', '--abort')
        return (f'! {branch} did not push: {remote}/{branch} has moved and merging it conflicts. '
                f'Nothing is lost — resolve it by hand, then push.')
    if g('push', '-q', remote, branch).returncode:
        return f'! {branch} did not push (it is committed locally; push it by hand)'
    return f'pushed {branch} → {remote}, after merging {remote}/{branch} into it'


def drop_if_merged(cwd: Path, branch: str) -> str:
    """Delete `branch` from the remote, but only once the remote's shared branch can be seen to hold it.

    Deleting it as soon as it is merged locally would take the only remote copy of work the remote's
    `main` does not have yet (when `push_merge` is off, or the push failed). What stays on the remote is
    therefore exactly "work the shared branch has not published", never a list with something missing.
    """
    remote = cfg(cwd).push_remote
    if not remote:
        return ''
    g = _git(cwd)
    if g('remote', 'get-url', remote).returncode:
        return ''
    g('fetch', '-q', remote)
    ref = f'refs/remotes/{remote}/{branch}'
    if g('rev-parse', '--verify', '-q', ref).returncode:
        return ''
    shared = shared_name(cwd, remote)
    if g('merge-base', '--is-ancestor', ref, f'refs/remotes/{remote}/{shared}').returncode:
        return f'kept {branch} on {remote}: {remote}/{shared} does not have the merge yet'
    if g('push', '-q', remote, '--delete', branch).returncode:
        return ''
    return f'dropped {branch} from {remote}: {remote}/{shared} has the merge now'
