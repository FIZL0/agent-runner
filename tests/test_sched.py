#!/usr/bin/env python3
"""pick's parts one at a time (C10): `held`, `holds`, `explain`, `choose` and `pick` in sched.py.

    python3 tests/test_sched.py        (no network; a second of git)

test_runner.py and test_plansync.py drive pick whole; this checks that the dry run (`explain`) and the pick
(`choose`) read the same reasons, that neither changes the plan, and that only `pick` blocks a parked task.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, report

from agent_runner import runner as R  # noqa: E402
from agent_runner import sched as S  # noqa: E402


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n'
                                       '- [ ] **T1** one | files: a.py\n'
                                       '- [ ] **T2** two | files: a.py\n'
                                       '- [ ] **T3** three | files: c.py\n'
                                       '- [ ] **L4a** four | files: d.py\n'
                                       '- [ ] **L4b** five | files: e.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      'merge_ahead = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def patched(**vals):
    """Set runner names (in every module that holds them) for a block; give back a function that restores."""
    saved = {k: getattr(R, k) for k in vals}
    for k, v in vals.items():
        setattr(R, k, v)
    return lambda: [setattr(R, k, v) for k, v in saved.items()]


def test_explain(repo: Path):
    print('explain: every open task\'s reason, the same first reason holds() gives choose()')
    R.init(repo)
    plan = (repo / 'plan/TODO.md').read_text(encoding='utf-8')
    running = {1: ('T1', 'Next', {'a.py'}, set())}
    why = S.explain(running, {'T3'}, 'main')
    eq(why.get('T1'), ('running', ''), 'the running task')
    eq(why.get('T2'), ('waiting for files', 'a.py held by T1'), 'its file neighbour waits')
    eq(why.get('T3'), ('tried this run', ''), 'a tried one')
    eq((why.get('L4a'), why.get('L4b')), (('free', ''), ('free', '')), 'the rest are free')
    h = S.held(running, 'main')
    eq([t[0] for t in h.todo], ['T1', 'T2', 'T3', 'L4a', 'L4b'], 'held reads the open tasks in order')
    eq(S.holds(h.todo[1], {'T3'}, h), ('clash', h.busy[0]), 'holds names the busy task it clashes with')
    eq(S.holds(h.todo[3], {'T3'}, h), None, 'and None for a free one')
    eq(S.choose(h, {'T3'}, 'main')[0], 'L4a', 'choose takes the first free one')
    eq(S.choose(S.held({1: h.todo[3]}, 'main'), {'T1', 'T2', 'T3'}, 'main'), None, "L4a's sibling waits for it")
    out: dict = {}
    eq(R.pick(running, {'T3'}, 'main', why=out), None, 'pick with why picks nothing')
    eq(out, why, 'and fills in what explain gives')
    eq((repo / 'plan/TODO.md').read_text(encoding='utf-8'), plan, 'the plan is untouched')


def test_parked(repo: Path):
    print('pick: a parked task is blocked by pick, the caller, never by choose or explain')
    R.init(repo)
    blocked: list = []
    restore = patched(parked_attempts=lambda: {'T1': ['wip/T1', 'wip/T1-2']},
                      block_parked=lambda tid, wips, branch: blocked.append((tid, tuple(wips))) or True)
    try:
        why = S.explain({}, set(), 'main')
        eq(why.get('T1'), ('parked 2 times, needs a person', 'wip/T1, wip/T1-2'), 'the dry run says why')
        h = S.held({}, 'main')
        eq(S.parked_now(set(), h), ['T1'], 'parked_now lists it')
        eq(S.parked_now({'T1'}, h), [], 'but not once tried: the first reason wins')
        eq(S.choose(h, set(), 'main')[0], 'T2', 'choose skips it')
        eq(R.pick({}, set(), 'main')[0], 'T2', 'so does a pick that does not claim')
        eq(blocked, [], 'and none of them blocks it')
        eq(R.pick({}, set(), 'main', claim=True)[0], 'T2', 'a claiming pick takes the next')
        eq(blocked, [('T1', ('wip/T1', 'wip/T1-2'))], 'after blocking the parked one')
    finally:
        restore()


def test_release_taken(tmp: Path):
    print('B107: a release passes over a task taken by hand; one running in a slot still holds it')
    repo = tmp / 'rel'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n'
                                       '- [ ] **T3** three | files: c.py\n'
                                       '- [ ] **V1** (alone) Release | after: all\n'  # F130: it runs alone
                                       '- [ ] **T1** one | files: a.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      'merge_ahead = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    ls = (repo / 'plan/TODO.md').read_text(encoding='utf-8').splitlines()
    eq('V1' in S.explain({}, set(), 'main'), False, 'untaken, T3 holds the after: all release')
    eq(R.release_line(ls), 'release: V1 waits for everything before it (1 open)', 'status says it waits')
    S.SLOTS_DIR.mkdir(parents=True, exist_ok=True)
    git(repo, 'worktree', 'add', '-q', '-b', 'task/T3', str(S.SLOTS_DIR / 'take-T3'))  # `take T3`, no changes
    eq(set(S.taken()), {'T3'}, 'T3 is taken by hand')
    why = S.explain({}, set(), 'main')
    eq(why.get('T3'), ('running', 'taken by hand (`take`)'), 'the taken task')
    eq(why.get('V1'), ('free', 'not waiting on T3 (taken by hand)'), 'the release is free to start, and says why')
    eq(S.choose(S.held({}, 'main'), set(), 'main')[0], 'V1', 'choose starts it')
    eq(R.release_line(ls), 'release: ready, nothing left to wait on (V1); not waiting on: T3 (taken by hand)',
       "status's release line says so")
    running = {1: ('T1', 'Next', {'a.py'}, set())}
    eq(S.explain(running, set(), 'main').get('V1'),
       ('runs alone', 'T1 is running or waiting to merge in this run'), 'a task in a slot still holds it')
    eq(S.choose(S.held(running, 'main'), set(), 'main'), None, 'and nothing starts')
    h = S.held({}, 'main')
    h = h._replace(away=h.away | {'X9'}, busy=h.busy + [('X9', 'Next', {'z.py'}, set(), {'z.py'})])
    eq(S.holds(next(t for t in h.todo if t[0] == 'V1'), set(), h), None, 'a task claimed by another runner does not hold it either')


def test_release_beside(tmp: Path):
    print('F99: a release starts once what it waits for landed, beside running tasks, and tasks start beside it')
    repo = tmp / 'beside'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n'
                                       '- [ ] **V1** Release | after: all\n'
                                       '- [ ] **T1** one | files: a.py\n'
                                       '- [ ] **T2** two | files: b.py\n'
                                       '- [ ] **T3** three | files: c.py\n'
                                       '- [ ] **V2** Release | after: all\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      'merge_ahead = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    running = {1: ('T1', 'Next', {'a.py'}, set()), 2: ('T2', 'Next', {'b.py'}, set())}
    eq(S.explain(running, set(), 'main').get('V1'), ('free', ''), 'the release is free while T1 and T2 run')
    eq('V2' in S.explain(running, set(), 'main'), False, 'one with open tasks ahead of it waits for them to land')
    eq(S.choose(S.held(running, 'main'), set(), 'main')[0], 'V1', 'and a free slot starts it')
    with S.MERGE:  # a merge is landing: the release starts from it, once it has
        eq(S.explain(running, set(), 'main').get('V1'),
           ('waiting for a merge to land', 'a release starts from what has landed'), 'not while a merge lands')
    v = next(t for t in S.held({}, 'main').todo if t[0] == 'V1')
    beside = {**running, 3: v}
    eq(S.explain(beside, set(), 'main').get('T3'), ('free', ''), 'a task is free beside the release')
    eq(S.choose(S.held(beside, 'main'), set(), 'main')[0], 'T3', 'and starts beside it')
    # T1 finished while V1 runs: its merge waits, and the dry run says why
    git(repo, 'branch', 'task/V1')  # as a slot starting V1 makes it
    git(repo, 'checkout', '-q', '-b', 'task/T1')
    (repo / 'a.py').write_text('# a\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'T1: a')
    git(repo, 'checkout', '-q', 'main')
    eq(S.explain({2: running[2], 3: v}, set(), 'main').get('T1'), ('finished, waiting to merge', 'V1 is releasing'),
       'a finished task waits to merge while V1 is releasing')
    git(repo, 'branch', '-D', 'task/V1')  # V1 landed: its merge deletes the branch
    eq(S.explain({2: running[2]}, set(), 'main').get('T1'), ('finished, waiting to merge', ''),
       'and merges once it has landed')
    git(repo, 'branch', '-D', 'task/T1')


def test_alone(tmp: Path):
    print('F130: a task tagged (alone) waits for what runs, nothing starts beside it, and a release can carry it')
    repo = tmp / 'alone'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n'
                                       '- [ ] **C1** (alone) rewrite it all | files: native/**\n'
                                       '- [ ] **T1** one | files: a.py\n'
                                       '- [ ] **T2** two | files: b.py\n'
                                       '- [ ] **V1** (alone) Release\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      'merge_ahead = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    todo = {t[0]: t for t in S.held({}, 'main').todo}
    eq(S.held({}, 'main').alone, frozenset({'C1', 'V1'}), 'the tagged tasks are read')
    eq(S.choose(S.held({}, 'main'), set(), 'main')[0], 'C1', 'nothing runs: the alone task starts')
    running = {1: todo['T1']}
    why = S.explain(running, set(), 'main')
    eq(why.get('C1'), ('runs alone', 'T1 is running or waiting to merge in this run'),
       'it waits for a running task, files apart (a whole-directory glob alone would not)')
    eq(why.get('V1'), ('runs alone', 'T1 is running or waiting to merge in this run'), 'so does an alone release')
    eq(why.get('T2'), ('free', ''), 'untagged tasks still start beside T1')
    eq(S.choose(S.held(running, 'main'), set(), 'main')[0], 'T2', 'and the pick skips the alone ones')
    beside = {1: todo['C1']}
    why = S.explain(beside, set(), 'main')
    eq(why.get('T1'), ('runs alone', 'C1 runs alone'), 'nothing starts beside a running alone task')
    eq(why.get('V1'), ('runs alone', 'C1 is running or waiting to merge in this run'), 'not even another alone one')
    eq(S.choose(S.held(beside, 'main'), set(), 'main'), None, 'and the pick starts nothing')
    eq(S.choose(S.held({1: todo['V1']}, 'main'), set(), 'main'), None, 'nothing starts beside an alone release')
    h = S.held({}, 'main')
    h = h._replace(away=h.away | {'X9'}, busy=h.busy + [('X9', 'Next', {'z.py'}, set(), {'z.py'})])
    eq(S.holds(todo['C1'], set(), h), None, 'a task claimed by another runner does not hold it (B107)')
    h = h._replace(busy=h.busy + [('X8', 'Next', set(), set(), set())], away=h.away | {'X8'})
    h = h._replace(alone=h.alone | {'X8'})
    eq((S.holds(todo['C1'], set(), h) or ('',))[0], 'clash', 'but one tagged (alone) itself still holds it')


def test_critical_first(tmp: Path):
    print('B140: a critical task waiting on a merge holds nothing back, and goes first once free')
    repo = tmp / 'crit'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    todo = ('# TODO\n\n### Next\n\n'
            '- [ ] **N1** normal, listed first | files: n.py\n'
            '- [ ] **B1** fix (follow-up, critical) | files: a.py\n'
            '- [ ] **X1** blocker | files: a.py\n'
            '- [ ] **N2** normal too | files: a.py\n')
    (repo / 'plan/TODO.md').write_text(todo, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                      'merge_ahead = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    R.init(repo)
    x1 = ('X1', 'Next', {'a.py'}, set())
    eq(S.choose(S.held({1: x1}, 'main'), set(), 'main')[0], 'N1', 'X1 still running: N1 takes the free slot')
    git(repo, 'checkout', '-q', '-b', 'task/X1')  # X1 exited; its branch waits to merge
    (repo / 'a.py').write_text('# a\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'X1: a')
    git(repo, 'checkout', '-q', 'main')
    eq(S.choose(S.held({1: x1}, 'main'), set(), 'main')[0], 'N1', 'in its slot with commits, X1 is still running')
    h = S.held({}, 'main')
    eq(S.choose(h, set(), 'main')[0], 'N1', 'B1 waits on X1\'s merge; N1 takes the free slot meanwhile')
    why = S.explain({}, set(), 'main')
    eq(why.get('B1'), ('waiting for files', 'a.py held by X1'), 'the dry run: B1 waits for X1')
    eq(why.get('N1'), ('free', ''), 'and N1 is free: a critical task holds nothing back')
    # X1's merge lands: a.py and the ticked line on main, its branch deleted
    git(repo, 'merge', '-q', '--no-ff', '-m', 'Merge X1', 'task/X1')
    (repo / 'plan/TODO.md').write_text(todo.replace('[ ] **X1**', '[x] **X1**'), encoding='utf-8')
    git(repo, 'commit', '-qam', 'X1 done')
    git(repo, 'branch', '-D', 'task/X1')
    eq(S.choose(S.held({}, 'main'), set(), 'main')[0], 'B1', 'once the merge lands, B1 starts ahead of N1')
    b1 = next(t for t in S.held({}, 'main').todo if t[0] == 'B1')
    eq(S.choose(S.held({1: b1}, 'main'), set(), 'main')[0], 'N1', 'and N1 the one after (N2 waits for B1)')


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ['CLAUDE_CONFIG_DIR'] = tmp
        repo = make_repo(Path(tmp))
        return report([lambda: test_explain(repo), lambda: test_parked(repo),
                       lambda: test_release_taken(Path(tmp)), lambda: test_release_beside(Path(tmp)),
                       lambda: test_alone(Path(tmp)), lambda: test_critical_first(Path(tmp))])


if __name__ == '__main__':
    sys.exit(main())
