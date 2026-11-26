"""B841: landed work the shared branch's push left behind, pushed before a run ends (and when one starts).

`gitops.push` leaves a refused push of the shared branch to the next merge, which takes the remote in before
its gate. A run that ends (once, stop, idle shutdown) has no next merge, and another device's runner never
merges this one's task branches, so the work would stay on this disk. Here: take the remote in, run the
gate on the two together, move the shared branch there and push, again while the remote keeps moving.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runner.config import cfg
from agent_runner.gitops import _net, git

TRIES = 5  # pushes lost to a remote that keeps moving before it gives up until the next merge or run


def _remote(root: Path) -> str:
    """The push remote when the run pushes the shared branch itself, else ''."""
    c = cfg(root)
    if not (c.push_merge and c.push_remote) or c.pr or c.approve:
        return ''
    if c.push_merge and not (c.run['test'] or 'push_merge' in c.given.get('git', ())):
        return ''  # no gate and push_merge not set by the config: never pushed untested (`land.pushes_main`)
    if git('remote', 'get-url', c.push_remote, cwd=root).returncode:
        return ''
    return c.push_remote


def unpushed(root: Path, branch: str) -> int:
    """How many commits `branch` has that the push remote's copy (as last fetched) lacks; 0 when it pushes nothing."""
    if not (remote := _remote(root)):
        return 0
    ref = f'refs/remotes/{remote}/{branch}'
    if git('rev-parse', '--verify', '-q', ref, cwd=root).returncode:
        return 0
    out = git('rev-list', '--count', f'{ref}..refs/heads/{branch}', cwd=root).stdout.strip()
    return int(out) if out.isdigit() else 0


def unpushed_line(root: Path, branch: str) -> str:
    """For status: landed work this disk holds and the remote does not, or ''."""
    n = unpushed(root, branch)
    if not n:
        return ''
    remote = cfg(root).push_remote
    return (f'! {branch} has {n} landed commit{"s" if n != 1 else ""} not on {remote}: the next run or merge '
            f'pushes {"them" if n != 1 else "it"}, or push by hand: git push {remote} {branch}')


def _merged(root: Path, branch: str, up: str) -> tuple[str, str]:
    """(the commit of `branch` with `up` merged in and the gate passed on it, '') or ('', why not)."""
    from agent_runner.done import gate
    d = Path(tempfile.mkdtemp(prefix='push-left-'))
    if git('worktree', 'add', '-q', '--detach', str(d), f'refs/heads/{branch}', cwd=root).returncode:
        return '', 'could not make a worktree to test the merge in'
    try:
        if (m := git('merge', '-q', '--no-edit', '-m', f'Merge {up.removeprefix("refs/remotes/")} into {branch}', up,
                     cwd=d)).returncode:
            clash = git('diff', '--name-only', '--diff-filter=U', cwd=d).stdout.strip()
            git('merge', '--abort', cwd=d)
            if not clash:  # no identity to commit as, say: git's own words
                return '', f'git could not merge {up.removeprefix("refs/remotes/")}: ' + \
                    (m.stderr.strip().splitlines() or ['no message'])[-1][:200]
            return '', f'{up.removeprefix("refs/remotes/")} conflicts with it; the next merge takes it in'
        rc, out = gate(d)
        if rc:
            return '', f'the gate failed on it merged with {up.removeprefix("refs/remotes/")}: {out[-300:]}'
        return git('rev-parse', 'HEAD', cwd=d).stdout.strip(), ''
    finally:
        git('worktree', 'remove', '--force', str(d), cwd=root)


def push_left(root: Path, branch: str, tries: int = TRIES) -> str:
    """Push landed work `branch` holds and the remote lacks, merging the remote in (tested) when it has moved.
    One line to log ('pushed …' or '! …'), or '' when there was nothing to push."""
    if not (remote := _remote(root)):
        return ''
    net = _net(root)
    up = f'refs/remotes/{remote}/{branch}'
    for _ in range(tries):
        if net('fetch', '-q', remote).returncode:
            return f'! {branch} is not pushed: {remote} cannot be reached' if unpushed(root, branch) else ''
        if not unpushed(root, branch):
            return ''
        if git('merge-base', '--is-ancestor', up, f'refs/heads/{branch}', cwd=root).returncode:
            sha, why = _merged(root, branch, up)
            if not sha:
                return f'! {branch} is not pushed: {why}'
            if git('branch', '--show-current', cwd=root).stdout.strip() != branch:
                return f'! {branch} is not pushed: the main checkout has another branch out'
            if git('merge', '-q', '--ff-only', sha, cwd=root).returncode:
                return f'! {branch} is not pushed: it could not move to the tested merge (uncommitted edits?)'
        if not (p := net('push', '-q', remote, branch)).returncode:
            return f'pushed {branch} -> {remote}: landed work a refused push had left on this disk'
        net('fetch', '-q', remote)
        if not git('merge-base', '--is-ancestor', up, f'refs/heads/{branch}', cwd=root).returncode:
            return f'! {branch} is not pushed: {remote} refused it: ' + \
                (p.stderr.strip().splitlines() or ['no message'])[-1][:200]  # refused, not moved: no retry helps
    return f'! {branch} is not pushed: {remote}/{branch} kept moving ({tries} tries); the next run or merge pushes it'
