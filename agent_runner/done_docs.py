"""`done`'s docs-only decision: which files a worktree changed, and whether they all need no test gate (F37)."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from agent_runner.config import cfg
from agent_runner.gitops import git, shared_name

DOCS_SKIP = 'docs only, gate skipped'  # what `done` and the merge say when a diff is all `[run] docs_files`


def docs_only(files: list[str], globs: list[str]) -> bool:
    """Every one of `files` (at least one) matches `[run] docs_files` (the last glob that matches decides,
    `!glob` takes a file back): a diff the test gate need not run on."""
    def doc(f: str) -> bool:
        hit = False
        for g in globs:
            if fnmatch.fnmatch(f, g.lstrip('!')):
                hit = not g.startswith('!')
        return hit
    return bool(files) and all(map(doc, files))


def changed(cwd: Path) -> list[str]:
    """The files this worktree's work changes: commits since the shared branch, staged, unstaged and untracked
    (renames as both names, so a code file moved into docs/ still counts as code)."""
    shared = shared_name(cwd, cfg(cwd).push_remote or 'origin', default=None)
    base = shared and git('merge-base', 'HEAD', shared, cwd=cwd).stdout.strip() or 'HEAD'
    files = git('diff', '--name-only', '--no-renames', base, cwd=cwd).stdout.splitlines()
    files += git('ls-files', '--others', '--exclude-standard', cwd=cwd).stdout.splitlines()
    return sorted({f for f in files if f})

