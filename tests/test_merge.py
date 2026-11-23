#!/usr/bin/env python3
"""merge_batch's three steps one at a time (C8): `batch_build`, `batch_test` and `batch_land` in merge.py.

    python3 tests/test_merge.py        (no network; a second or two of git)

test_runner.py drives merge_batch whole; this checks each step's answers (None, BATCH_RETRY or why) and the
turn state it leaves for the next step, in a throwaway repo with the gate, repairs and landing stubbed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import config as CF, runner as R  # noqa: E402
from agent_runner import merge as M  # noqa: E402

CF.FIXED['merge_ahead'] = False  # F166: no merge built beside a gate here


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **B1** one | files: b1.py\n'
                                       '- [ ] **B2** two | files: b2.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'a.py').write_text('# a\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    for tid in ('B1', 'B2'):
        git(repo, 'checkout', '-q', '-b', f'task/{tid}')
        (repo / f'{tid.lower()}.py').write_text(f'# {tid}\n', encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', f'{tid}: {tid.lower()}')
        git(repo, 'checkout', '-q', 'main')
    return repo


def turn(d: Path, tid: str = 'B1', solo: bool = True) -> M.BatchTurn:
    return M.BatchTurn(tid, 'main', d, solo, set(), False, False)


def patched(**vals):
    """Set runner names (in every module that holds them) for a block; give back a function that restores."""
    saved = {k: getattr(R, k) for k in vals}
    for k, v in vals.items():
        setattr(R, k, v)
    return lambda: [setattr(R, k, v) for k, v in saved.items()]


def test_build(repo: Path):
    print('batch_build: the merge of task/<tid>, with riders unless solo, on the branch head')
    R.init(repo)
    d = R.worktree('merge', 'main')
    head = git(repo, 'rev-parse', 'main')
    restore = patched(log=lambda *a, **k: None)
    try:
        t = turn(d)
        eq(M.batch_build(t), None, 'built: nothing to say')
        eq(t.base, head, 't.base is the branch head it was built on')
        eq(t.riders, [], 'solo: no riders')
        eq(git(d, 'rev-parse', 'HEAD'), t.merged, 't.merged is the merge commit in the merge worktree')
        files = git(d, 'ls-tree', '--name-only', t.merged).split()
        check('b1.py' in files and 'b2.py' not in files, 'task/B1 is in it, task/B2 is not', files)
        R.WAITING.add('B2')
        try:
            t = turn(d, solo=False)
            eq(M.batch_build(t), None, 'a batch builds too')
            eq(t.riders, ['B2'], 'the waiting B2 rides along')
            files = git(d, 'ls-tree', '--name-only', t.merged).split()
            check('b1.py' in files and 'b2.py' in files, 'both tasks are in the merge', files)
        finally:
            R.WAITING.discard('B2')
        t = turn(d)
        t.repairs = ['0' * 40]
        eq(M.batch_build(t), None, 'a repair that no longer applies does not stop the build')
        eq(t.repairs, [], 'it is dropped: the merge is tested without it')
    finally:
        restore()
        git(d, 'checkout', '-q', '--detach')


def test_test(repo: Path):
    print('batch_test: the gate, the split of a failing batch and one repair per base')
    R.init(repo)
    d = R.worktree('merge', 'main')
    gates, repairs = [], []
    t = turn(d)
    assert M.batch_build(t) is None
    restore = patched(log=lambda *a, **k: None, note=lambda *a, **k: None, gated=lambda tid: True,
                      tested=lambda tid, d, base, tids: (gates.append(tids), 'the tests fail')[1],
                      repair_retest=lambda *a, **k: (repairs.append(a), None, None, [])[1:])
    try:
        R.untestable = lambda f: True  # what B1's own `done` tested is the merged code: no gate again
        eq(M.batch_test(t), None, 'gated by `done` on the same code: it may land')
        eq(gates, [], 'and the gate did not run')
        R.untestable = UNTESTABLE
        R.gated = lambda tid: False
        merged = t.merged
        eq(M.batch_test(t), None, 'the gate fails, the repair session fixes it: it may land')
        eq((len(gates), len(repairs)), (1, 1), 'one gate run, one repair session')
        check(t.solo and t.repaired_on == t.base, 'it goes on alone, the repair counted on this base')
        eq(t.merged, merged, 'the repair committed nothing (a flake): t.merged stays')
        eq(M.batch_test(t), 'the tests fail', 'failing again on the same base: no second repair, the why')
        eq(len(repairs), 1, 'still one repair session')

        R.FAILED['B1'] = ['test_x']
        R.blame = lambda tids, d, base, names: ['B2']
        t = turn(d, solo=False)
        t.base, t.merged, t.riders = git(d, 'rev-parse', 'HEAD'), git(d, 'rev-parse', 'HEAD'), ['B2']
        try:
            eq(M.batch_test(t) is M.BATCH_RETRY, True, 'a batch that blame splits: build again')
            check('B2' in R.ALONE and not t.solo, 'B2 merges in a turn of its own; B1 may still batch')
        finally:
            R.ALONE.discard('B2')
        blamed = []
        R.blame = lambda tids, d, base, names: (blamed.append(names), [])[1]
        R.FAILED['B1'] = ['test_x']
        repair_merges, R.C.run['repair_merges'] = R.C.run['repair_merges'], False
        t = turn(d, solo=False)
        t.base, t.merged, t.riders = git(d, 'rev-parse', 'HEAD'), git(d, 'rev-parse', 'HEAD'), ['B2']
        eq(M.batch_test(t) is M.BATCH_RETRY, True, 'a failing batch nobody is blamed for: build again')
        eq(blamed, [['test_x']], 'blame ran on the failing tests and named nobody')
        check(t.solo and t.repairs == [], 'B1 again alone, without repairs')
        R.C.run['repair_merges'] = repair_merges
    finally:
        restore()
        R.untestable, R.blame = UNTESTABLE, BLAME
        R.FAILED.pop('B1', None)
        git(d, 'checkout', '-q', '--detach')


def test_land(repo: Path):
    print('batch_land: catch up, land, record every task of the turn in LANDED')
    R.init(repo)
    d = R.worktree('merge', 'main')
    lands = []
    restore = patched(caught_up=lambda tid, branch, d, base, merged, tids: None,
                      land=lambda tid, branch, merged: (lands.append(merged), 'conflict')[1])
    try:
        t = turn(d)
        t.base, t.merged, t.riders = 'b0', 'm0', ['B2']
        eq(M.batch_land(t) is M.BATCH_RETRY, True, 'not caught up with the branch: build again')
        eq(lands, [], 'and nothing landed')
        R.caught_up = lambda tid, branch, d, base, merged, tids: ('b1', 'm1')
        eq(M.batch_land(t) is M.BATCH_RETRY, True, 'lost a race to land: build again')
        eq((t.base, t.merged, lands), ('b1', 'm1', ['m1']), 'it landed the caught-up merge')
        eq(M.batch_land(t, last=True), 'conflict', 'on the last try the race is the why')
        R.land = lambda tid, branch, merged: None
        eq(M.batch_land(t), None, 'landed')
        eq((R.LANDED.get('B1'), R.LANDED.get('B2')), (('b1', 'm1'), ('b1', 'm1')), 'B1 and its rider in LANDED')
    finally:
        restore()
        R.LANDED.pop('B1', None)
        R.LANDED.pop('B2', None)


def test_release_holds(repo: Path):
    print('F99: while a release is busy every other merge waits, and goes through once it has landed')
    import threading
    R.init(repo)
    todo = repo / 'plan/TODO.md'
    text = todo.read_text(encoding='utf-8')
    todo.write_text(text + '- [ ] **V1** Release | after: all\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'plan: V1')
    git(repo, 'branch', 'task/V1')  # V1 started in a slot
    built, said = [], []
    restore = patched(log=lambda msg, *a, **k: said.append(msg), note=lambda *a, **k: None,
                      fix_ahead=lambda tid, branch: None, research_held=lambda tid, branch: None,
                      merge_batch=lambda tid, branch, **k: (built.append(tid), 'stubbed')[1], RELEASE_POLL=0.05)
    try:
        eq(M.releasing('B1', 'main'), 'V1', 'V1 is releasing')
        eq(M.releasing('V1', 'main'), '', "a release's own merge is never held")
        eq(M.merge('V1', 'main'), 'stubbed', 'so V1 merges at once')
        built.clear()
        out = []
        th = threading.Thread(target=lambda: out.append(M.merge('B1', 'main')), daemon=True)
        th.start()
        th.join(0.5)
        check(th.is_alive() and built == [], 'B1 waits: no merge built while V1 is busy', built)
        check(any('B1: waits to merge: V1 is releasing' in m for m in said), 'the log says why', said)
        git(repo, 'branch', '-D', 'task/V1')  # V1 landed: its merge deletes the branch
        th.join(10)
        eq((th.is_alive(), built, out), (False, ['B1'], ['stubbed']), 'once V1 landed, B1 merges')
        eq(M.releases({'B1', 'V1', 'V12'}), {'V1', 'V12'}, 'releases never ride in a batch, nor take riders')
    finally:
        restore()
        if git(repo, 'branch', '--list', 'task/V1'):
            git(repo, 'branch', '-D', 'task/V1')
        todo.write_text(text, encoding='utf-8')
        git(repo, 'commit', '-qam', 'plan: no V1')


UNTESTABLE, BLAME = M.untestable, M.blame


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['CLAUDE_CONFIG_DIR'] = tmp
        repo = make_repo(Path(tmp))
        return report([lambda: test_build(repo), lambda: test_test(repo), lambda: test_land(repo),
                       lambda: test_release_holds(repo)])


if __name__ == '__main__':
    sys.exit(main())
