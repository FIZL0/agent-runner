#!/usr/bin/env python3
"""B885: one run page snapshot spawns few git processes; toplevel/main_checkout are memoized.

    python3 tests/test_snapshot_speed.py        (a temp repo, no agent, no network)
"""
from __future__ import annotations
import subprocess
import time
from pathlib import Path
from unittest import mock
from _check import check, report
from agent_runner import config
from agent_runner import ui_model as U  # noqa: E402
from _ui_model import in_tmp, fake_run  # noqa: E402


def count_runs(f) -> list:
    real, calls = subprocess.run, []

    def spy(*a, **kw):
        calls.append(a[0] if a else kw.get('args'))
        return real(*a, **kw)
    with mock.patch.object(subprocess, 'run', spy):
        f()
    return calls


def test_snapshot_spawns(tmp: Path) -> None:
    repo = fake_run(tmp)
    config.clear_git_cache()
    U.snapshot(up=False, now=time.time(), links={})  # warm
    calls = count_runs(lambda: U.snapshot(up=False, now=time.time(), links={}))
    revs = [c for c in calls if list(c[:2]) == ['git', 'rev-parse'] and
            ('--show-toplevel' in c or '--git-common-dir' in c)]
    check(not revs, f'a second snapshot asks git for no toplevel or common dir: {revs}')
    check(len(calls) <= 5, f'a snapshot spawns at most 5 processes: {len(calls)} {calls}')
    calls = count_runs(lambda: [config.main_checkout(repo) for _ in range(20)])
    check(not calls, 'main_checkout is memoized')
    config.clear_git_cache()
    calls = count_runs(lambda: config.main_checkout(repo))
    check(len(calls) == 2, 'after clear_git_cache it asks git again')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_snapshot_spawns)]))
