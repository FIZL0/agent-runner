#!/usr/bin/env python3
"""Worktrees keep builds warm, within limits: slot_max_gb, min_free_gb, and slots past the count removed.

    python3 tests/test_disk.py          (temp repos, a few seconds)
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import runner as R  # noqa: E402


def make(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'a.py').write_text('# a\n')
    (repo / 'data').mkdir()
    (repo / 'data/big.bin').write_bytes(b'd' * 3_000_000)  # a `links` target: never the slot's size
    (repo / 'runner.toml').write_text('[run]\nslot_max_gb = 0.002\nmin_free_gb = 20\nlinks = ["data"]\n')
    (repo / '.gitignore').write_text('.runner/\nbuild/\ndata\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def build(d: Path, mb: int) -> None:
    (d / 'build').mkdir(exist_ok=True)
    (d / 'build/out.o').write_bytes(b'x' * mb * 1_000_000)


def test_disk(tmp: Path):
    repo = make(tmp)
    R.init(repo)
    said: list[str] = []
    R.log = said.append

    print('slot_max_gb')
    d = R.worktree(1, 'main')
    check((d / 'data').is_symlink(), 'the slot has its link')
    build(d, 1)
    check(not R.trim(d, 'slot 1'), 'a slot under the cap is left warm (the 3 MB link does not count)')
    build(d, 3)
    check(R.trim(d, 'slot 1'), 'one over it is cleaned')
    check(not (d / 'build').exists() and (d / 'a.py').exists(), 'its build output goes, tracked files stay')
    has('\n'.join(said), r'slot 1: .* GB, over \[run\] slot_max_gb .*git clean', 'and says so')
    R.worktree(1, 'main')
    check((d / 'data').is_symlink() and (repo / 'data/big.bin').exists(), 'the link comes back; its target was never touched')

    print('min_free_gb')
    build(d, 1)
    real = R.free_gb
    R.free_gb = lambda: 5.0
    try:
        check(R.low_disk([1]), 'low disk: no new task starts')
        check(not (d / 'build').exists(), 'and the free slots were cleaned first, small or not')
        has('\n'.join(said), r'disk: 5\.0 GB free, under \[run\] min_free_gb', 'it says why once')
        n = len(said)
        R.low_disk([1])
        eq(len(said), n, 'and only once')
    finally:
        R.free_gb = real
    R.free_gb = lambda: 50.0
    try:
        check(not R.low_disk([1]), 'room again: tasks start')
    finally:
        R.free_gb = real

    print('slots past the count')
    s2, s3 = R.worktree(2, 'main'), R.worktree(3, 'main')
    build(s2, 1)
    (s3 / 'notes.txt').write_text('uncommitted\n')
    R.drop_extra_slots(1, set())
    time.sleep(0.5)
    check(not s2.exists(), 'an unused slot past the count is removed')
    check(str(s2) not in git(repo, 'worktree', 'list'), 'and git forgets the worktree')
    check(s3.exists(), 'one with uncommitted work is kept')
    has('\n'.join(said), r'slot 3: past the 1 slots, but it has uncommitted work', 'and says why')
    check(d.exists(), 'a slot within the count is never touched')
    s4 = R.worktree(4, 'main')
    R.drop_extra_slots(1, {4})
    check(s4.exists(), 'nor one a session still runs in')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        return report([lambda: test_disk(Path(t))])


if __name__ == '__main__':
    sys.exit(main())
