"""`done`'s docs-only decision: which files a worktree changed, and whether they all need no test gate (F37)."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from agent_runner.config import cfg
from agent_runner.gitops import git, shared_name

DOCS_SKIP = 'docs only, gate skipped'  # what `done` and the merge say when a diff is all `[run] docs_files`


def docs_only(files: list[str], globs: list[str]) -> bool:
    """Every one of `files` (at least one) matches `[run] docs_files` (the last glob that matches decides,
    `!glob` takes a file back; a manifest marked DESCRIBED counts as docs): a diff the test gate need not run on."""
    def doc(f: str) -> bool:
        if f.endswith(DESCRIBED):  # F494: a manifest's description line is wording, not code
            return True
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
    files = mark_descriptions(base, None, files, cwd)
    files += git('ls-files', '--others', '--exclude-standard', cwd=cwd).stdout.splitlines()
    return sorted({f for f in files if f})



MANIFESTS = ('pyproject.toml', 'package.json', 'Cargo.toml')  # F494: a description-only change here is docs


def _description_lines(text: str, name: str) -> set[str]:
    """The lines of a manifest that hold the project's own description: in `[project]` or `[package]` for TOML,
    at the top level of the object for package.json (a nested `description` is not wording)."""
    import re
    out, table, depth = set(), '', 0
    for ln in text.splitlines():
        if name.endswith('.toml'):
            if m := re.match(r'\s*\[([^\]]*)\]', ln):
                table = m.group(1).strip()
            elif table in ('project', 'package') and re.match(r'\s*description\s*=', ln):
                out.add(ln)
        else:
            if depth == 1 and re.match(r'\s*"description"\s*:', ln):
                out.add(ln)
            depth += ln.count('{') + ln.count('[') - ln.count('}') - ln.count(']')
    return out


def description_only(base: str, head: str | None, f: str, cwd: Path) -> bool:
    """`f` is a project manifest whose diff from `base` (to `head`, or the worktree) changes only its own
    `description` line: a wording change the gate need not run on."""
    if Path(f).name not in MANIFESTS:
        return False
    diff = git('diff', '-U0', '--no-renames', base, *([head] if head else []), '--', f, cwd=cwd).stdout
    lines = [ln[1:] for ln in diff.splitlines() if ln[:1] in '+-' and not ln.startswith(('+++', '---'))]
    before = git('show', f'{base}:{f}', cwd=cwd).stdout
    after = git('show', f'{head}:{f}', cwd=cwd).stdout if head else (cwd / f).read_text(encoding='utf-8', errors='replace') \
        if (cwd / f).is_file() else ''
    ok = _description_lines(before, f) | _description_lines(after, f)
    return bool(lines) and all(ln in ok for ln in lines)


DESCRIBED = '#description'  # marks a manifest whose only change is its description: docs_only counts it as docs


def mark_descriptions(base: str, head: str | None, files: list[str], cwd: Path) -> list[str]:
    """`files`, each manifest whose only change is its description marked with DESCRIBED (F494)."""
    return [f + DESCRIBED if description_only(base, head, f, cwd) else f for f in files]


def merge_files(base: str, merged: str, cwd: Path) -> list[str]:
    """The files a merge changes on its base, description-only manifests marked (F494)."""
    files = git('diff', '--name-only', '--no-renames', base, merged, cwd=cwd).stdout.split()
    return mark_descriptions(base, merged, files, cwd)
