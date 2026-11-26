#!/usr/bin/env python3
"""B841: landed work a lost push race left behind is pushed at a run's start or end, after the remote is merged in
and the gate passes; status says when it is left unpushed.

    python3 tests/test_stranded.py        (temp repos with a local remote, a few seconds)
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import config as CF, stranded as S  # noqa: E402


def tip(bare: Path) -> str:
    return subprocess.run(['git', 'rev-parse', 'refs/heads/main'], cwd=bare, capture_output=True, text=True).stdout.strip()


def setup(tmp: Path, test: str = 'true') -> tuple[Path, Path, Path]:
    repo, bare, other = tmp / 'repo', tmp / 'repo.git', tmp / 'other'
    git(tmp, 'init', '-q', '--bare', '-b', 'main', str(bare))
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'runner.toml').write_text(f'[run]\ntest = "{test}"\n[git]\npush_merge = true\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(bare))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    git(tmp, 'clone', '-q', str(bare), str(other))
    CF._cfg.cache_clear()
    return repo, bare, other


def commit(d: Path, name: str) -> None:
    (d / name).write_text(name, encoding='utf-8')
    git(d, 'add', name)
    git(d, 'commit', '-qm', name)


def test_moved_remote_merged_and_pushed():
    with tempfile.TemporaryDirectory() as t:
        repo, bare, other = setup(Path(t))
        commit(repo, 'mine.txt')  # landed here, its push lost the race:
        commit(other, 'theirs.txt')
        git(other, 'push', '-q', 'origin', 'main')
        eq(S.ahead(repo), 1, 'one landed commit ahead of origin as last fetched')
        check(S.unpushed_line(repo).startswith('! 1 landed commit'), 'status says it', S.unpushed_line(repo))
        out = S.push_stranded(repo)
        check(out.startswith('pushed main'), 'pushed after merging origin in', out)
        eq(tip(bare), git(repo, 'rev-parse', 'HEAD').strip(), 'origin has main')
        check((repo / 'theirs.txt').exists(), 'the main checkout has the remote work')
        eq(S.unpushed_line(repo), '', 'nothing said once pushed')
        eq(S.push_stranded(repo), '', 'nothing to do the second time')


def test_gate_fails_stays_local():
    with tempfile.TemporaryDirectory() as t:
        repo, bare, other = setup(Path(t), test='test ! -e theirs.txt')
        commit(repo, 'mine.txt')
        commit(other, 'theirs.txt')
        git(other, 'push', '-q', 'origin', 'main')
        before = tip(bare)
        out = S.push_stranded(repo)
        check(out.startswith('! main is not pushed: the test gate fails'), 'a failing gate leaves it unpushed', out)
        eq(tip(bare), before, 'origin unchanged')
        check(not (repo / 'theirs.txt').exists(), 'main untouched')


if __name__ == '__main__':
    raise SystemExit(report([test_moved_remote_merged_and_pushed, test_gate_fails_stays_local]))
