"""B841: landed work left unpushed. A merge pushes the shared branch, and a push that loses the race to
the remote leaves it to "the next merge"; a run that ends (once, stop, idle shutdown) has no next merge,
so before it exits, and when a run starts, `push_stranded` takes the remote in, runs the test gate on
that merge, and pushes, again while the remote keeps moving. `unpushed_line` says it in status."""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_runner.config import cfg
from agent_runner.gitops import _git, _net

TRIES = 5


def ahead(cwd: Path, branch: str = 'main') -> int:
    """Commits on `branch` that the push remote's copy (as last fetched) does not have; 0 with no remote."""
    remote = cfg(cwd).push_remote
    g = _git(cwd)
    if not remote or g('rev-parse', '-q', '--verify', f'refs/remotes/{remote}/{branch}').returncode:
        return 0
    r = g('rev-list', '--count', f'refs/remotes/{remote}/{branch}..refs/heads/{branch}')
    return int(r.stdout.strip() or 0) if not r.returncode else 0


def unpushed_line(cwd: Path, branch: str = 'main') -> str:
    """The status warning for landed work not on the remote, or ''."""
    c = cfg(cwd)
    if not c.push_merge or c.approve or getattr(c, 'pr', False):
        return ''
    if not (n := ahead(cwd, branch)):
        return ''
    return (f'! {n} landed commit{"s" if n > 1 else ""} on {branch} not pushed to {c.push_remote}: '
            f'the next run start or end pushes them, or `git push {c.push_remote} {branch}`')


def push_stranded(cwd: Path, branch: str = 'main', tries: int = TRIES) -> str:
    """Push `branch` when it is ahead of the push remote: merge the remote in first (in a worktree of its
    own, tested by the gate, then fast-forwarded here), again up to `tries` times while the remote moves.
    '' when nothing was ahead; a line starting '!' when it is left unpushed."""
    from agent_runner.done import gate
    remote = cfg(cwd).push_remote
    g, net = _git(cwd), _net(cwd)
    if not remote or not ahead(cwd, branch):  # as last fetched: a push that lost the race leaves it ahead
        return ''
    up = f'refs/remotes/{remote}/{branch}'
    for _ in range(tries):
        if (f := net('fetch', '-q', remote, f'+refs/heads/{branch}:{up}')).returncode:
            return f'! {branch} is not pushed: fetching {remote} failed: {(f.stderr or "").strip()[:200]}'
        if not ahead(cwd, branch):
            return ''
        tip = g('rev-parse', f'refs/heads/{branch}').stdout.strip()
        new = tip
        if g('merge-base', '--is-ancestor', up, tip).returncode:  # the remote moved: merge and test it
            with tempfile.TemporaryDirectory(prefix='stranded-') as tmp:
                wt = Path(tmp) / 'wt'
                if g('worktree', 'add', '-q', '--detach', str(wt), tip).returncode:
                    return f'! {branch} is not pushed: could not make a worktree to merge {remote}/{branch} in'
                try:
                    w = _git(wt)
                    if w('merge', '-q', '--no-edit', '-m', f'Merge {remote}/{branch} into {branch}', up).returncode:
                        w('merge', '--abort')
                        return (f'! {branch} is not pushed: merging {remote}/{branch} conflicts; '
                                f'merge it by hand, then push')
                    rc, out = gate(wt)
                    if rc:
                        return (f'! {branch} is not pushed: the test gate fails on the merge with '
                                f'{remote}/{branch}: {out.splitlines()[-1] if out else rc}')
                    new = w('rev-parse', 'HEAD').stdout.strip()
                finally:
                    g('worktree', 'remove', '--force', str(wt))
            if g('rev-parse', f'refs/heads/{branch}').stdout.strip() != tip:
                continue  # it moved here meanwhile: start again
            if g('branch', '--show-current').stdout.strip() == branch:
                if g('merge', '-q', '--ff-only', new).returncode:
                    return (f'! {branch} is not pushed: the main checkout has edits to files the merge with '
                            f'{remote}/{branch} changes')
            elif g('update-ref', f'refs/heads/{branch}', new, tip).returncode:
                continue
        if not net('push', '-q', remote, f'{new}:refs/heads/{branch}').returncode:
            g('update-ref', up, new)
            return f'pushed {branch} -> {remote}' + (', after merging the remote in and testing it' if new != tip else '')
    return f'! {branch} is not pushed: {remote}/{branch} kept moving ({tries} tries)'
