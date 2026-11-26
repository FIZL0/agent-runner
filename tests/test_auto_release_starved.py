#!/usr/bin/env python3
"""B849a: auto release by count is queued at the landing that reaches the count, even when MERGE is never free at a tick.

    python3 tests/test_auto_release_starved.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import autorelease as A, merge as M, plan as P, runner as R, state as S  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** first thing | files: a.py

### Parked

### Stretch
"""
TOML = '[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\nauto_release = { every = 10, idle = true }\n'


def releases() -> list[str]:
    return [t for t in P.open_ids(P.lines(R.C.todo)) if P.release(t)]


def test_starved():
    print('merges back to back: the tick never gets MERGE, the landing that reaches 10 queues the release once')
    landed = [f'T{i}' for i in range(1, 9)]
    got, free = threading.Event(), threading.Event()

    def other_merge():  # a merge holding MERGE the whole time
        with S.MERGE:
            got.set()
            free.wait(30)
    th = threading.Thread(target=other_merge)
    th.start()
    got.wait(10)
    try:
        with mock.patch.object(A, 'landed_since_release', lambda b: list(landed)):
            for i in (9, 10, 11, 12):
                landed.append(f'T{i}')
                A.AUTO_RELEASE_SEEN[0] = None
                eq(A.auto_release('main'), '', f'the tick at {i} gets no MERGE')
                if i < 10:
                    eq(M.auto_release_landed('main'), '', f'not at {i}')
                    continue
                # the landing runs inside its merge's MERGE turn: here, the held lock stands in for it
                tid = M.auto_release_landed('main')
                if i == 10:
                    check(tid, 'queued at the 10th landing')
                else:
                    eq(tid, '', f'once: none again at {i}')
            eq(len(releases()), 1, 'one release')
    finally:
        free.set()
        th.join(10)


def test_guards():
    print('a stop, or releases off, queues none at a landing')
    with mock.patch.object(A, 'landed_since_release', lambda b: [f'X{i}' for i in range(20)]):
        with mock.patch.object(S, 'stopping', lambda: True):
            eq(A.auto_release('main', merging=True), '', 'stopping')
        with mock.patch.object(A, 'releases_on', lambda: False):
            eq(A.auto_release('main', merging=True), '', 'releases off')
        from agent_runner import release_moves
        with mock.patch.object(release_moves, 'cuts', lambda: mock.Mock(held=True)):
            eq(A.auto_release('main', merging=True), '', 'the next release held')


def test_idle_queues():
    print('idle release unchanged: queued when the run goes idle with landed work')
    with mock.patch.object(A, 'landed_since_release', lambda b: ['T1']):
        check(A.auto_release('main', idle=True), 'queued at idle')
    R.C.todo.write_text(TODO, encoding='utf-8')
    git(R.ROOT, 'commit', '-qam', 'fresh')


def test_idle():
    print('idle release unchanged: none while a release is open')
    with mock.patch.object(A, 'landed_since_release', lambda b: ['T1']):
        eq(A.auto_release('main', idle=True), '', 'an open release hinders it')


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='ar-starved-'))
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
    return report([test_idle_queues, test_starved, test_guards, test_idle])


if __name__ == '__main__':
    sys.exit(main())
