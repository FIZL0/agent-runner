#!/usr/bin/env python3
"""F23: the runner cleans up its own wip branches.

    python3 tests/test_wip.py        (no network; a few seconds, mostly git)

A task ticked or dropped loses its wip/<ID> and wip/<ID>-N, here and on the remote; an open task's wip stays;
wip/main-checkout-* (a person's edits) is never deleted by the run, shows under Needs you with its age and file
count, and `agent-runner wip show|restore|drop NAME` handles it on the person's word.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

import test_runner as TR  # noqa: E402  (its make_repo: a throwaway repo with a bare origin)
from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402

MAIN_WIP = 'wip/main-checkout-2026-11-01-090000'


def branch_at(repo: Path, name: str, msg: str, files: dict[str, str] | None = None, when: str = '') -> None:
    """Branch `name` off main with one commit (`files` written in it), pushed to origin."""
    tmp_index = repo / '.git' / 'test-wip-index'
    env = {**os.environ, 'GIT_INDEX_FILE': str(tmp_index)}
    if when:
        env.update(GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
    import subprocess
    sh = lambda *a: subprocess.run(['git', *a], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()
    sh('read-tree', 'main')
    for f, text in (files or {}).items():
        blob = subprocess.run(['git', 'hash-object', '-w', '--stdin'], cwd=repo, input=text, capture_output=True,
                              text=True, check=True).stdout.strip()
        sh('update-index', '--add', '--cacheinfo', f'100644,{blob},{f}')
    tree = sh('write-tree')
    tmp_index.unlink(missing_ok=True)
    sha = sh('commit-tree', tree, '-p', 'main', '-m', msg)
    git(repo, 'branch', '-f', name, sha)
    git(repo, 'push', '-q', 'origin', name)


def remote(tmp: Path) -> set[str]:
    return TR.remote_branches(tmp)


def local(repo: Path) -> set[str]:
    return set(git(repo, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/wip/').split())


def test_prune(repo: Path, tmp: Path):
    print('F23: a ticked or dropped task loses its wip branches here and on the remote; an open one keeps its own')
    R.init(repo)
    branch_at(repo, 'wip/T2', 'T2 attempt 1')
    branch_at(repo, 'wip/T2-2', 'T2 attempt 2')
    branch_at(repo, 'wip/T5', 'T5 wip: uncommitted edits')
    branch_at(repo, 'wip/T3', 'T3 attempt 1')
    branch_at(repo, 'wip/T1', 'T1 attempt 1')  # T1 is blocked below: not done, so it stays
    branch_at(repo, MAIN_WIP, 'Uncommitted edits from the main checkout (2 files)',
              {'x.py': '# x\n', 'y.py': '# y\n'}, when='2026-11-01T09:00:00')
    git(repo, 'branch', '-D', 'wip/T2-2')  # only on the remote now: still cleaned up
    todo, done = repo / 'plan/TODO.md', repo / 'plan/DONE.md'
    P.tick('T2', todo, done)
    P.drop('T5', 'a duplicate', todo, done)
    P.block('T1', 'BLOCKED: needs a key', todo)
    git(repo, 'commit', '-qam', 'plan: T2 done, T5 dropped, T1 blocked')
    git(repo, 'push', '-q', 'origin', 'main')
    R.FETCHED[0] = time.time()
    eq(R.done_ids('main') >= {'T2', 'T5'}, True, 'DONE.md holds the ticked and the dropped task')
    R.PRUNED[0] = time.time()
    eq(R.prune_wips('main'), [], 'throttled: nothing until PRUNE_EVERY has passed')
    did = R.prune_wips('main', force=True)
    eq(sorted(d.split(':')[0] for d in did), ['T2', 'T5'], 'it acts for the done and dropped tasks only')
    eq(local(repo), {'wip/T1', 'wip/T3', MAIN_WIP}, 'their local wip branches are gone, the rest stay')
    rem = remote(tmp)
    check(not {'wip/T2', 'wip/T2-2', 'wip/T5'} & rem, 'and gone from the remote, a remote-only wip/T2-2 too', rem)
    check({'wip/T1', 'wip/T3', MAIN_WIP} <= rem, 'an open or blocked task keeps its wip; main-checkout is never touched', rem)
    has((repo / '.runner/run.log').read_text(encoding='utf-8'), r'T2: done, so its parked attempts went: .*wip/T2',
        'the run log says so')
    eq(R.drop_wips('T3'), ['deleted wip/T3', 'deleted wip/T3 from origin'], 'drop_wips: local and remote, as for a drop')
    check('wip/T3' not in remote(tmp), 'wip/T3 off the remote')
    branch_at(repo, 'wip/T3', 'T3 attempt 1')

    print('F23: a merge that ticks its task clears that task\'s wip at once')
    branch_at(repo, 'wip/T6', 'T6 attempt 1')
    P.tick('T6', todo, done)
    git(repo, 'commit', '-qam', 'plan: T6 merged')
    git(repo, 'push', '-q', 'origin', 'main')
    with mock.patch.object(R, '_finish', lambda *a: True):
        R.finish('T6', 1, 'sid', 'main')
    check('wip/T6' not in local(repo) | remote(tmp), 'finish: wip/T6 gone after its tick landed')
    check('wip/T3' in local(repo), 'and the open T3 keeps its own')


def test_main_checkout(repo: Path, tmp: Path):
    print('F23: wip/main-checkout-* under Needs you with age and file count; wip show|restore|drop')
    R.init(repo)
    info = R.wip_main_info()
    eq([(n, k) for n, _, k in info], [(MAIN_WIP, 2)], 'wip_main_info: the branch and its 2 files')
    now = dt.datetime(2026, 11, 4, 9, 0)
    text = R.status_text(False, {}, [], {}, now.timestamp(), wips=info)
    eq(text.splitlines()[:2], [f'{R.ROOT.name} needs you:', f'   3d  Main-checkout edits moved aside (2 files) - '
                                             f'{R.C.command} wip show|restore|drop {MAIN_WIP[4:]} [{MAIN_WIP}]'],
       'status: under Needs you, with its age and file count')
    text = R.since_text([], now, {}, now, wips=info)[0]
    check(text.startswith(f'{R.ROOT.name} needs you:\n   3d  Main-checkout edits moved aside (2 files)'), 'since: the same', text)
    eq(R.status_text(False, {}, [], {}, 0.0), 'no run is up', 'nothing extra without them')

    r = run(repo, 'wip')
    has(r.stdout, rf'Main-checkout edits moved aside \(2 files\).*\[{MAIN_WIP}\]', 'wip lists them')
    r = run(repo, 'wip', 'show', MAIN_WIP[4:])
    check(r.returncode == 0 and 'x.py' in r.stdout and 'y.py' in r.stdout, 'wip show: its files', r.stdout + r.stderr)
    r = run(repo, 'wip', 'restore', MAIN_WIP[4:])
    check(r.returncode == 1 and 'take ID' in r.stderr, 'restore with no take worktree says to take one first', r.stderr)
    r = run(repo, 'take', 'T3')
    check(r.returncode == 0, 'take T3', r.stderr)
    d = R.SLOTS_DIR / 'take-T3'
    try:
        r = run(repo, 'wip', 'restore', MAIN_WIP)
        check(r.returncode == 0, 'restore into the one take worktree', r.stdout + r.stderr)
        eq(sorted(git(d, 'status', '--porcelain').splitlines()), ['?? x.py', '?? y.py'],
           'its edits are there, uncommitted and unstaged')
        eq(git(d, 'rev-parse', 'HEAD'), git(repo, 'rev-parse', 'main'), 'and nothing committed')
        check(MAIN_WIP in local(repo), 'restore keeps the branch')
    finally:
        git(repo, 'worktree', 'remove', '--force', str(d))
        git(repo, 'branch', '-D', 'task/T3')
    r = run(repo, 'wip', 'drop', MAIN_WIP[4:])
    check(r.returncode == 0 and 'deleted wip/' in r.stdout, 'wip drop', r.stdout + r.stderr)
    check(MAIN_WIP not in local(repo) | remote(tmp), 'gone here and on the remote')
    eq(R.wip_main_info(), [], 'and off Needs you')
    check(run(repo, 'wip', 'drop', 'nope').returncode == 1, 'drop of a branch that is not there fails')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo = TR.make_repo(tmp)
        return report([lambda: test_prune(repo, tmp), lambda: test_main_checkout(repo, tmp)])


if __name__ == '__main__':
    import sys
    sys.exit(main())
