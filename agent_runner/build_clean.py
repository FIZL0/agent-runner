"""F424: Home clears old build output by itself in a project whose run is off.

A run trims its worktrees only before a task or a merge, so a stopped run keeps its builds for ever. On Home's
regular footprint walk, a runner worktree that no process works in and whose build output nothing wrote for
BUILD_QUIET loses that output, and nothing else. Build output here is only what git ignores, holds no tracked
file, and is marked as such (`build_folders`): a folder with a CACHEDIR.TAG, a CMake build folder, and, as a
Cargo target folder can hold hand-made checkouts, only the profile folders in one. Each folder is looked at again
just before it goes (`clean_builds`). When in doubt, it stays.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess as sp
from pathlib import Path

from agent_runner.build_output import (CACHEDIR_SIGNATURE, CMAKE_FILES, NOTES, _cargo_target, _fetched_only, _held,
                                       _out_of_source, _read)

BUILD_QUIET = 3 * 24 * 3600.0  # s with no write to any of a worktree's build output before it is old
RUNNER_TREE = re.compile(r's\d+|merge\d*|fix\d+')
TRIPLE = re.compile(r'(x86_64|i[3-6]86|aarch64|arm|thumb|wasm|riscv|powerpc|s390x|loongarch|mips|sparc)\w*(-[\w.]+){1,4}')  # x86_64-unknown-linux-gnu, wasm32-wasip1


def _git(cwd: Path, *args: str) -> bytes | None:
    try:
        r = sp.run(['git', *args], cwd=cwd, capture_output=True, timeout=60)
    except (OSError, sp.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def worktree_of(root: Path, d: Path) -> bool:
    """Is folder `d` itself a worktree of the repository at `root`?"""
    top = _git(d, 'rev-parse', '--show-toplevel')
    if not top or Path(os.fsdecode(top.rstrip(b'\r\n'))).resolve() != d.resolve():
        return False

    def common(p: Path) -> Path | None:
        out = _git(p, 'rev-parse', '--git-common-dir')
        return (p / os.fsdecode(out.rstrip(b'\r\n'))).resolve() if out else None
    mine = common(d)
    return mine is not None and mine == common(root)


def build_folders(d: Path) -> list[Path] | None:
    """The marked build output folders in what git ignores in worktree `d`, none inside another. None when git
    could not tell. Symlinks, and folders with a repository of their own, are not looked into."""
    raw = _git(d, 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z')
    if raw is None:
        return None
    out: list[Path] = []
    for rel in sorted({os.fsdecode(x).rstrip('/') for x in raw.split(b'\0') if x}):
        p = d / rel
        if not any(q == p or q in p.parents for q in out):
            for q in _marked(p):
                if q not in out:
                    out.append(q)
    return out


def _plain(p: Path) -> bool:
    return p.is_dir() and not p.is_symlink()


def _kids(p: Path) -> list[Path]:
    try:
        return sorted(p.iterdir())
    except OSError:
        return []


def _marked(p: Path) -> list[Path]:
    if not _plain(p):
        return []
    kids = _kids(p)
    names = {k.name for k in kids}
    if not kids or '.git' in names:  # empty, or cannot be read
        return []
    if p.name == 'node_modules' or 'pyvenv.cfg' in names:
        return []  # installed, not built (uv tags its .venv as a cache); a build inside is part of it
    if _cargo_target(p):
        return [q for k in kids for q in _cargo_marked(k)]
    if 'CMakeCache.txt' in names:
        return [p] if _out_of_source(p) else []
    if _read(p / 'CACHEDIR.TAG').startswith(CACHEDIR_SIGNATURE):
        return [p]
    return [q for k in kids for q in _marked(k)]


def _cargo_marked(k: Path) -> list[Path]:
    """What is build output in `k`, straight in a Cargo target folder: a profile folder, the profile folders of a
    target-triple folder, and those of a target folder put inside it. Anything else in there may be someone's."""
    if not _plain(k):
        return []
    if (k / '.git').exists():
        return []
    if _cargo_target(k):
        return _marked(k)
    if _profile(k):
        return [k]
    return [q for q in _kids(k) if _profile(q)] if TRIPLE.fullmatch(k.name) else []


def _profile(p: Path) -> bool:
    return _plain(p) and not os.path.lexists(p / '.git') and _plain(p / '.fingerprint') and _plain(p / 'deps')


def holds_own(p: Path) -> bool:
    """Does build folder `p` hold something that may be a person's: a repository (but for one CMake fetched, under
    the folder's _deps, with nothing of its own), a notes file straight in it, or a Cargo target folder with more
    than Cargo's own in it?"""
    cmake = (p / 'CMakeCache.txt').is_file()
    if (cmake or _profile(p)) and any(k.suffix.lower() in NOTES and k.name not in CMAKE_FILES and k.is_file()
                                      for k in _kids(p)):
        return True
    unread: list[OSError] = []
    for top, dirs, files in os.walk(p, onerror=unread.append):
        if '.git' in dirs or '.git' in files:
            fetched = cmake and Path(top).relative_to(p).parts[:1] == ('_deps',)
            if not fetched or not _fetched_only(Path(top)):
                return True
        if _cargo_target(Path(top)) and _held(Path(top), '')[0]:
            return True
        dirs[:] = [x for x in dirs if x != '.git']
    return bool(unread)


def git_lets_go(d: Path, p: Path) -> bool:
    """Does git ignore folder `p` of worktree `d` as a whole, with no tracked file in it?"""
    rel = p.relative_to(d).as_posix()
    return (_git(d, 'check-ignore', '-q', '--', rel) is not None
            and _git(d, '--literal-pathspecs', 'ls-files', '--cached', '-z', '--', rel) == b'')


def quiet(folders: list[Path], now: float) -> bool:
    """Has nothing written to `folders` for BUILD_QUIET? A repository's own .git folder is not counted: looking
    at it with git can write there."""
    def old(path) -> bool:
        try:
            return now - os.lstat(path).st_mtime >= BUILD_QUIET
        except OSError:
            return False  # written to or removed this moment
    unread: list[OSError] = []
    for p in folders:
        if not old(p):
            return False
        for top, dirs, files in os.walk(p, onerror=unread.append):
            dirs[:] = [x for x in dirs if x != '.git']
            if not all(old(os.path.join(top, x)) for x in dirs + files):
                return False
    return not unread


def worked_in(d: Path, cwds: list[str]) -> bool:
    """Does a process work in worktree `d`? Yes when nothing tells (no /proc: no working folders at all)."""
    here = str(d.resolve())
    return not cwds or any(c == here or c.startswith(here + os.sep) for c in cwds)


def trees_of(p) -> list[Path]:
    try:
        return sorted(d for d in p.home.iterdir() if RUNNER_TREE.fullmatch(d.name) and _plain(d))
    except OSError:
        return []


def clean_builds(projects: list, off, cwds, now: float, size, rm=shutil.rmtree, said=None) -> list[tuple]:
    """Remove the old build output of each runner worktree of `projects` whose run is off: `off(project)` and
    `cwds()` (every process's working folder) say how things are now. Each folder is looked at again just before
    it goes. [(the worktree, folders removed, bytes freed)], those that lost something; `said` is called with each
    as soon as it is known."""
    out = []
    for p in projects:
        for d in trees_of(p):
            if not off(p):
                break
            if worked_in(d, cwds()) or not worktree_of(p.root, d):
                continue
            count, freed = 0, 0
            try:
                for f in build_folders(d) or []:
                    # the slow looks first: those at the run and the processes come last
                    found = build_folders(d) or []
                    if f not in found or not quiet(found, now):
                        break
                    if f.resolve() != d.resolve() / f.relative_to(d) or not git_lets_go(d, f) or holds_own(f):
                        continue
                    n = size(f)
                    if not quiet([f], now) or worked_in(d, cwds()) or not off(p):
                        break
                    try:
                        rm(f)
                    except OSError:
                        pass  # what is left stays, and is looked at on a later walk
                    gone = not f.exists()
                    count += gone
                    freed += n if gone else max(0, n - size(f))
            except OSError:
                pass  # a folder that cannot be looked at: the other worktrees still are
            if count or freed:
                out.append((d, count, freed))
                if said:
                    said(d, count, freed)
    return out
