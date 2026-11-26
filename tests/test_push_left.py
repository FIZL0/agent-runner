#!/usr/bin/env python3
"""B841: landed work a refused push left on this disk is pushed before a run ends: the remote taken in, tested.

    python3 tests/test_push_left.py        (temp repos with a local remote, a few seconds; every OS)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import config as CF, runner as R  # noqa: E402
from agent_runner.push_left import push_left, unpushed, unpushed_line  # noqa: E402


def make(tmp: Path, test: str = 'true') -> tuple[Path, Path, Path]:
    repo, bare, other = tmp / 'repo', tmp / 'repo.git', tmp / 'other'
    repo.mkdir()
    git(tmp, 'init', '-q', '--bare', '-b', 'main', str(bare))
    git(repo, 'init', '-q', '-b', 'main')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    (repo / 'runner.toml').write_text(f'[run]\ntest = "{test}"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(bare))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    git(tmp, 'clone', '-q', str(bare), str(other))
    CF._cfg.cache_clear()
    R.init(repo)
    return repo, bare, other


def commit(d: Path, name: str) -> None:
    (d / name).write_text(name, encoding='utf-8')
    git(d, 'add', name)
    git(d, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', name)


def test_moved_remote() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo, bare, other = make(Path(t))
        commit(repo, 'mine.txt')  # landed here
        commit(other, 'theirs.txt')  # another device landed and pushed first
        git(other, 'push', '-q', 'origin', 'main')
        git(repo, 'fetch', '-q', 'origin')
        eq(unpushed(repo, 'main'), 1, 'one landed commit counts as unpushed')
        check('git push origin main' in unpushed_line(repo, 'main'), 'status names it, and how to push it')
        out = push_left(repo, 'main')
        check(out.startswith('pushed main'), 'the remote is taken in and main is pushed', out)
        files = git(bare, 'ls-tree', '--name-only', 'main').split()
        check('mine.txt' in files and 'theirs.txt' in files, 'the remote holds both sides', str(files))
        eq(git(repo, 'rev-parse', 'main'), git(bare, 'rev-parse', 'main'), 'main and the remote agree')
        eq(unpushed_line(repo, 'main'), '', 'status says nothing once pushed')
        eq(push_left(repo, 'main'), '', 'nothing left: nothing said')


def test_gate_fails() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo, bare, other = make(Path(t), test='test ! -e theirs.txt')
        commit(repo, 'mine.txt')
        commit(other, 'theirs.txt')
        git(other, 'push', '-q', 'origin', 'main')
        was = git(repo, 'rev-parse', 'main')
        out = push_left(repo, 'main')
        check(out.startswith('! main is not pushed: the gate failed'), 'an untested merge is never pushed', out)
        eq(git(repo, 'rev-parse', 'main'), was, 'main stays where it was')
        check('mine.txt' not in git(bare, 'ls-tree', '--name-only', 'main').split(), 'the remote did not get it')


def test_fast_forward() -> None:
    with tempfile.TemporaryDirectory() as t:
        repo, bare, _ = make(Path(t))
        commit(repo, 'mine.txt')
        out = push_left(repo, 'main')
        check(out.startswith('pushed main'), 'a remote that has not moved: pushed as it is', out)


if __name__ == '__main__':
    sys.exit(report([test_moved_remote, test_gate_fails, test_fast_forward]))
