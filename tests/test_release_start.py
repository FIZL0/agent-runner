#!/usr/bin/env python3
"""B849b: a release ready to start but for the merge under way starts before the merges waiting behind it; one
held otherwise, or one no pick can start (run paused, usage cap, no free slot), holds no merge.

    python3 tests/test_release_start.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import merge as M, row_hold, runner as R, sched  # noqa: E402
from agent_runner.state import MERGE  # noqa: E402

TODO = """# TODO

### Next

- [ ] **F2** a feature | files: a.py
- [ ] **V1** Release
"""
TOML = '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\n'


def pick() -> str | None:
    t = sched.pick({}, set(), 'main', claim=True)
    return t and t[0]


def test_ready():
    print('a release the merge alone holds: the waiting merges hold for it')
    sched.RELEASE_READY.clear()
    check(MERGE.acquire(blocking=False), 'a merge under way')
    try:
        eq(pick(), 'F2', 'the free slot takes another task')
        eq(sched.ready_release(), 'V1', 'the release is marked ready')
        eq(M.release_first('F3', 'main'), 'V1', 'a waiting merge holds for it')
        eq(M.release_first('V1', 'main'), '', 'its own merge holds for nothing')
    finally:
        MERGE.release()
    pick()
    eq(sched.ready_release(), '', 'the merge is over: the pick starts it, and the mark goes')


def test_held_otherwise():
    print('a release held for more than the merge holds no merge')
    keep = sched.unpushed
    sched.unpushed = lambda: 1
    check(MERGE.acquire(blocking=False), 'a merge under way')
    try:
        pick()
        eq(M.release_first('F3', 'main'), '', 'unpushed changes hold it: merges go on')
    finally:
        MERGE.release()
        sched.unpushed = keep
    keep_h = row_hold.held_ids
    row_hold.held_ids = lambda text: {'V1'}
    check(MERGE.acquire(blocking=False), 'a merge under way')
    try:
        pick()
        eq(M.release_first('F3', 'main'), '', 'held by a person: merges go on')
    finally:
        MERGE.release()
        row_hold.held_ids = keep_h


def test_dropped():
    print('a marked release since blocked or dropped holds no merge, before any pick')
    check(MERGE.acquire(blocking=False), 'a merge under way')
    try:
        pick()
        eq(M.release_first('F3', 'main'), 'V1', 'marked')
        R.C.todo.write_text(TODO.replace('- [ ] **V1** Release', '- [~] **V1** Release BLOCKED: DECIDE: now?'), encoding='utf-8')
        git(R.ROOT, 'commit', '-qam', 'block V1')
        eq(M.release_first('F3', 'main'), '', 'blocked: merges go on')
        R.C.todo.write_text(TODO.replace('- [ ] **V1** Release\n', ''), encoding='utf-8')
        git(R.ROOT, 'commit', '-qam', 'drop V1')
        eq(M.release_first('F3', 'main'), '', 'dropped: merges go on')
    finally:
        MERGE.release()
        R.C.todo.write_text(TODO, encoding='utf-8')
        git(R.ROOT, 'commit', '-qam', 'V1 back')
        sched.RELEASE_READY.clear()


def test_paused():
    print('a paused run (no pick renews the mark) still merges')
    keep = sched.READY_FOR, M.RELEASE_POLL
    sched.READY_FOR, M.RELEASE_POLL = 0.5, 0.05
    check(MERGE.acquire(blocking=False), 'a merge under way')
    try:
        pick()
        eq(sched.ready_release(), 'V1', 'marked')
    finally:
        MERGE.release()
    try:
        t = threading.Thread(target=M.hold_for_release, args=('F3', 'main'), daemon=True)
        began = time.monotonic()
        t.start()
        time.sleep(0.2)
        check(t.is_alive(), 'the merge holds while the mark is fresh')
        t.join(5)
        check(not t.is_alive(), 'and goes on once it lapses', f'{time.monotonic() - began:.1f} s')
    finally:
        sched.READY_FOR, M.RELEASE_POLL = keep
        sched.RELEASE_READY.clear()


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    for n, text in (('plan/TODO.md', TODO), ('plan/DONE.md', '# DONE\n'), ('runner.toml', TOML), ('.gitignore', '.runner/\n')):
        (repo / n).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_ready, test_held_otherwise, test_dropped, test_paused])


if __name__ == '__main__':
    sys.exit(main())
