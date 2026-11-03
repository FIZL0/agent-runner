#!/usr/bin/env python3
"""`[plan] repo`: two code checkouts ("machines") share one plan repo.

    python3 tests/test_plansync.py      (local git only, a few seconds)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import config, plansync  # noqa: E402
from agent_runner import plan as P  # noqa: E402

TODO = '# TODO\n\n### Next\n\n- [ ] **T1** first → a.py\n- [ ] **T2** second → b.py\n- [ ] **T3** third → c.py\n'


def setup(tmp: Path) -> tuple[Path, Path, Path]:
    seed = tmp / 'seed'
    seed.mkdir()
    git(seed, 'init', '-q')
    (seed / 'TODO.md').write_text(TODO)
    (seed / 'DONE.md').write_text('# DONE\n')
    git(seed, 'add', '-A')
    git(seed, 'commit', '-qm', 'plan')
    git(tmp, 'clone', '-q', '--bare', str(seed), 'plan.git')
    out = []
    for name in 'AB':
        repo = tmp / name
        repo.mkdir()
        git(repo, 'init', '-q')
        (repo / 'a.py').write_text('# a\n')
        (repo / '.gitignore').write_text('.runner/\n')
        (repo / 'runner.toml').write_text(f'[plan]\nrepo = "{tmp / "plan.git"}"\ndir = "{tmp / ("clone-" + name)}"\n')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        out.append(repo)
    return out[0], out[1], tmp / 'plan.git'


def remote_todo(bare: Path) -> str:
    return git(bare, 'show', 'main:TODO.md')


def test_all(tmp: Path):
    a, b, bare = setup(tmp)
    ca, cb = config.Config(a), config.Config(b)
    check(ca.plan_external and ca.plan_repo, 'a [plan] repo makes the plan external')

    print('plan: reads clone, edits push')
    has(run(a, 'plan').stdout, r'T1', '`plan` clones the plan repo and lists it')
    head = git(a, 'rev-parse', 'HEAD')
    r = run(a, 'plan', 'add', 'F', 'from A')
    has(r.stdout, r'added F1', 'add works in the clone')
    has(remote_todo(bare), r'F1\*\* from A', 'and is pushed to the plan repo')
    eq(git(a, 'rev-parse', 'HEAD'), head, 'the code repo gets no commit')
    has(run(b, 'plan', 'F1').stdout, r'from A', "B's read sees A's edit")

    print('plan: diverged clones merge by line')
    plansync.pull(ca, force=True)
    plansync.pull(cb, force=True)
    P.add('F', 'from A again', todo=ca.todo, done=ca.done)
    P.add('G', 'from B', todo=cb.todo, done=cb.done)
    eq(plansync.publish(ca, 'a'), '', 'A pushes')
    eq(plansync.publish(cb, 'b'), '', "B's push is rejected, merges A's, pushes")
    t = remote_todo(bare)
    check('from A again' in t and 'from B' in t, 'both new lines are on the remote', t)

    print('plan: a tick on one side and a note on the other')
    plansync.pull(ca, force=True)
    plansync.pull(cb, force=True)
    P.tick('T1', ca.todo, ca.done)
    P.note('T1', 'a stale note', todo=cb.todo)
    plansync.publish(ca, 'tick')
    plansync.publish(cb, 'note')
    check('T1' not in P.open_ids(P.lines(cb.todo)), 'the merge leaves T1 ticked, not open twice',
          cb.todo.read_text())

    print('claims')
    check(plansync.claim(ca, 'T2'), 'A claims T2')
    check(not plansync.claim(cb, 'T2'), 'B cannot')
    plansync.pull(cb, force=True)
    eq(plansync.taken(cb), {'T2'}, "T2 is taken, seen from B")
    eq(plansync.taken(ca), set(), 'but not from A, whose claim it is')
    plansync.release(cb, 'T2')
    plansync.pull(ca, force=True)
    eq(plansync.taken(cb), {'T2'}, "B cannot release A's claim")
    plansync.release(ca, 'T2')
    check(plansync.claim(cb, 'T2'), 'once A releases it, B can')

    real = plansync.pull
    plansync.pull(cb, force=True)
    check(plansync.claim(ca, 'T3'), 'A claims T3')
    skipped = []

    def stale(c, force=False):  # B's first pull in claim() misses A's claim, as if A pushed just after it
        if c is cb and not skipped:
            skipped.append(1)
            return True
        return real(c, force)
    plansync.pull = stale
    try:
        check(not plansync.claim(cb, 'T3'), "B, not having pulled A's claim, loses the race on push")
    finally:
        plansync.pull = real
    check(not (cb.plan_dir / 'claims' / 'T3').exists() or
          (cb.plan_dir / 'claims' / 'T3').read_text().startswith(plansync.owner(ca)),
          "and its own claim commit is gone")

    print('done')
    (a / 'a.py').write_text('# a2\n')
    r = run(a, 'done', 'T3', 'T3: the work', '--no-test')
    check(r.returncode == 0, 'done outside a runner', r.stderr)
    check('T3' not in P.open_ids(remote_todo(bare).splitlines()), 'ticks at once and pushes the plan')
    eq(git(a, 'show', '--name-only', '--format=', 'HEAD'), 'a.py', 'the code commit holds only code')

    (b / 'a.py').write_text('# b2\n')
    r = run(b, 'done', 'G1', 'G1: work', '--no-test', env={**os.environ, 'AGENT_RUNNER_SLOT': '1'})
    check(r.returncode == 0, 'done in a slot', r.stderr)
    check('G1' in P.open_ids(remote_todo(bare).splitlines()), 'leaves the task open until the merge lands')
    check((plansync.ticks(cb) / 'G1').exists(), 'and marks it for the runner')
    from agent_runner import runner as R
    R.init(b)
    R.land_tick('G1', 'abcdef1234567')
    t = git(bare, 'show', 'main:DONE.md')
    has(t, r'\[x\] \*\*G1\*\*.*landed abcdef1234', 'the runner ticks it once landed, saying where')
    check(not (plansync.ticks(cb) / 'G1').exists(), 'and drops the mark')

    print('run: two runners on one queue')
    R.init(a)
    ta = R.pick({}, set(), 'd', 'main', claim=True)
    R.init(b)
    tb = R.pick({}, set(), 'd', 'main', claim=True)
    check(ta and tb and ta[0] != tb[0], 'each run claims a different task as it picks', f'{ta} {tb}')
    has(git(bare, 'show', f'main:claims/{ta[0]}'), str(a), "A's claim is pushed before its slot starts")
    eq(R.pick({}, set(), 'd', 'main')[0], tb[0], 'a pick that does not start (dry run) claims nothing new')
    (tmp / 'plan.git').rename(tmp / 'away.git')
    try:
        left = R.pick({}, {tb[0], 'T2'}, 'd', 'main', claim=True)  # T2: B's, pushed earlier
        eq(left, None, 'with the plan repo out of reach, a run starts nothing: its claim would be unseen')
    finally:
        (tmp / 'away.git').rename(tmp / 'plan.git')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        return report([lambda: test_all(Path(t))])


if __name__ == '__main__':
    sys.exit(main())
