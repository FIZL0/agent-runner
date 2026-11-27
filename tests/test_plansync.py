#!/usr/bin/env python3
"""`[plan] repo`: two code checkouts ("machines") share one plan repo.

    python3 tests/test_plansync.py      (local git only, a few seconds)
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import time
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import config, plansync  # noqa: E402
from agent_runner import plan as P  # noqa: E402

TODO = '# TODO\n\n### Tasks\n\n- [ ] **T1** first | files: a.py\n- [ ] **T2** second | files: b.py\n- [ ] **T3** third | files: c.py\n'


def setup(tmp: Path) -> tuple[Path, Path, Path]:
    seed = tmp / 'seed'
    seed.mkdir()
    git(seed, 'init', '-q')
    (seed / 'TODO.md').write_text(TODO, encoding='utf-8')
    (seed / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
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
        plan_repo = (tmp / 'plan.git').as_posix()
        plan_dir = (tmp / f'clone-{name}').as_posix()
        (repo / 'runner.toml').write_text(
            f'[plan]\nrepo = "{plan_repo}"\ndir = "{plan_dir}"\n', encoding='utf-8')
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
    r = run(a, 'plan')
    has(r.stdout, r'T1', '`plan` clones the plan repo and lists it')
    check(r.returncode == 0 and not r.stderr.count('Traceback'), 'and exits 0', r.stderr)
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

    print('claims: a gone run\'s claim is taken over after TAKEOVER (B857)')

    def age(tid, secs):  # A's claim on tid, as if last refreshed `secs` ago
        plansync.pull(ca, force=True)
        f = ca.plan_dir / 'claims' / tid
        ls = f.read_text().splitlines()
        ls[1] = time.strftime(plansync._STAMP, time.localtime(time.time() - secs))
        f.write_text('\n'.join(ls) + '\n')
        eq(plansync.publish(ca, f'age {tid}'), '', 'the aged claim pushes')
    check(plansync.claim(ca, 'T4'), 'A claims T4')
    age('T4', 3600)
    plansync.pull(cb, force=True)
    eq(plansync.taken(cb) & {'T4'}, {'T4'}, 'a 1h-old claim still holds T4, seen from B')
    check(not plansync.claim(cb, 'T4'), 'and B cannot take it over')
    age('T4', 2 * 3600 + 120)
    plansync.pull(cb, force=True)
    eq(plansync.taken(cb) & {'T4'}, set(), 'a 2h-old claim no longer holds T4')
    check(plansync.claim(cb, 'T4'), 'B takes T4 over')
    has(plansync.TOOK.pop('T4', ''), r'took over T4 from .* \(claim not refreshed since ', 'and says so')
    eq(plansync.claims(cb)['T4'].owner, plansync.owner(cb), 'the claim is now B\'s')
    plansync.pull(ca, force=True)
    eq(set(plansync.lost(ca, {'T4'})), {'T4'}, 'A, back, sees T4 is no longer its own')
    plansync.refresh(ca, {'T4'})
    plansync.pull(cb, force=True)
    eq(plansync.claims(cb)['T4'].owner, plansync.owner(cb), "and A's refresh leaves B's claim alone")

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
    ta = R.pick({}, set(), 'main', claim=True)
    R.init(b)
    tb = R.pick({}, set(), 'main', claim=True)
    check(ta and tb and ta[0] != tb[0], 'each run claims a different task as it picks', f'{ta} {tb}')
    check('G1' not in (ta[0], tb[0]), 'never one ticked since the pick last read the plan (G1, just above)')
    has(git(bare, 'show', f'main:claims/{ta[0]}'), re.escape(str(a)),
        "A's claim is pushed before its slot starts")
    eq(R.pick({}, set(), 'main')[0], tb[0], 'a pick that does not start (dry run) claims nothing new')
    R.init(a)
    nxt = R.C.plan_dir / 'TODO.md'
    keep = nxt.read_text()
    nxt.write_text(keep.replace('### Tasks', '### Next (in this order)'))
    try:
        eq(R.pick({}, set(), 'main'), None, "an ordered section waits while another runner has one of its tasks")
    finally:
        nxt.write_text(keep)
    R.init(b)
    (tmp / 'plan.git').rename(tmp / 'away.git')
    try:
        left = R.pick({}, {tb[0], 'T2'}, 'main', claim=True)  # T2: B's, pushed earlier
        eq(left, None, 'with the plan repo out of reach, a run starts nothing: its claim would be unseen')
    finally:
        (tmp / 'away.git').rename(tmp / 'plan.git')

    print('claims: what a claim file holds')
    from agent_runner import __version__
    cl = plansync.claims(cb)[ta[0]]
    eq(cl.version, __version__, 'a claim records its runner version')
    check(cl.since > 0, 'and when it was claimed, so a later clashing claim can give way')
    check(plansync.claim(ca, 'Z9', {'z.py', 'lib/**'}), 'a claim with files')
    eq(plansync.claims(ca)['Z9'].files, frozenset({'z.py', 'lib/**'}), 'records the files it holds')
    plansync.release(ca, 'Z9')
    R.init(a)
    R.CLAIMS_AT[0] = 0.0
    R.keep_claims({1: ta}, 'main')
    plansync.pull(ca, force=True)
    check(ta[0] in plansync.claims(ca), 'its live claim is kept')
    check('T3' not in plansync.claims(ca), "and its claim on a task it no longer runs or holds is dropped")
    plansync.publish(ca, 'drop OLD1')

    print('claims on the board')
    has(run(b, 'plan').stdout, rf'\] {ta[0]}  \[\S+@\S+ \d\d:\d\d v\d+\.\d+\.\d+\]',
        '`plan` marks a claimed task with who, when and which runner version')
    has(run(b, 'plan', 'claims').stdout, rf'^{ta[0]}  ', '`plan claims` lists them')
    f = ca.plan_dir / 'claims' / ta[0]
    ls = f.read_text().splitlines()
    f.write_text('\n'.join([ls[0], '2026-01-01 09:00', *ls[2:]]) + '\n')
    plansync.publish(ca, 'age a claim')
    plansync.pull(cb, force=True)
    check(plansync.stale(plansync.claims(cb)[ta[0]]), 'a claim not refreshed for hours is stale')
    R.init(b)
    R.CLAIMS_AT[0] = 0.0
    said = []
    saved, R.log = R.log, said.append
    try:
        R.keep_claims({}, 'main')
    finally:
        R.log = saved
    has('\n'.join(said), rf'{ta[0]}: claimed by .*STALE.*plan unclaim {ta[0]}', 'a run says so, with the fix')
    R.init(a)
    R.CLAIMS_AT[0] = 0.0
    R.keep_claims({1: ta}, 'main')
    check(not plansync.stale(plansync.claims(ca)[ta[0]]), "A's live run re-stamps its own claim")
    r = run(b, 'plan', 'unclaim', ta[0])
    check(r.returncode == 0 and ta[0] not in git(bare, 'ls-tree', '--name-only', 'main', 'claims/'),
          "B can unclaim A's task by hand", r.stderr)
    eq(run(b, 'plan', 'unclaim', ta[0]).returncode, 1, 'unclaiming nothing says so')


def test_in_repo(tmp: Path):
    """A plan in the code repo: claims are refs on the code's remote, so two clones on one machine (or two)
    never take one task."""
    seed = tmp / 'seed'
    seed.mkdir(parents=True)
    git(seed, 'init', '-q', '-b', 'main')
    (seed / 'plan').mkdir()
    (seed / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    git(seed, 'add', '-A')
    git(seed, 'commit', '-qm', 'start')
    git(tmp, 'clone', '-q', '--bare', str(seed), 'code.git')
    a, b = tmp / 'A', tmp / 'B'
    for d in (a, b):
        git(tmp, 'clone', '-q', str(tmp / 'code.git'), d.name)
    ca, cb = config.Config(a), config.Config(b)
    check(not ca.plan_external and plansync.enabled(ca), 'an in-repo plan with a remote claims tasks')
    print('in-repo claims: two clones on one machine')
    check(plansync.claim(ca, 'T1', {'a.py'}), 'A claims T1')
    check(not plansync.claim(cb, 'T1'), 'B cannot: the claim is on the remote')
    eq(plansync.taken(cb), {'T1'}, 'T1 is taken, seen from B')
    eq(plansync.claims(cb)['T1'].files, frozenset({'a.py'}), 'with the files it holds')
    eq(plansync.taken(ca), set(), 'not from A, whose claim it is')
    check(git(a, 'branch', '-r').count('claims') == 0, 'no branch for it: clones and CI never see one')
    plansync.release(cb, 'T1')
    eq(plansync.taken(cb), {'T1'}, "B cannot release A's claim")
    plansync.refresh(ca, {'T1'}, {'T1': {'a.py', 'b.py'}})
    plansync.SYNCED.clear()
    eq(plansync.claims(cb)['T1'].files, frozenset({'a.py', 'b.py'}), 'a refresh re-stamps it (a fast-forward)')
    check(plansync.claim(ca, 'T2'), 'A claims T2')
    plansync.refresh(ca, {'T1'})
    plansync.SYNCED.clear()
    eq(set(plansync.claims(cb)), {'T1'}, 'a refresh drops the claims A no longer holds')
    plansync.release(ca, 'T1')
    check(plansync.claim(cb, 'T1'), 'once A releases it, B can')
    check(plansync.claim(ca, 'T3'), 'A claims T3')
    real = plansync._Refs.sync
    plansync._Refs.sync = lambda self: True  # B's read misses A's claim, as if A pushed just after it
    try:
        check(not plansync.claim(cb, 'T3'), "B, not having seen A's claim, loses the race on push")
    finally:
        plansync._Refs.sync = real
    check(plansync.unclaim(cb, 'T3'), 'unclaim drops anyone\'s')
    plansync.SYNCED.clear()
    eq(plansync.taken(ca), {'T1'}, 'and the remote has only B\'s T1 left')
    git(a, 'remote', 'remove', 'origin')
    check(not plansync.enabled(config.Config(a)), 'no remote: no claims (a local-only run is the only one)')


def test_repo_setup(tmp: Path):
    """F460: `plan repo-setup` moves an in-repo plan to its own repo, and a second checkout joins it."""
    seed = tmp / 'seed'
    (seed / 'plan' / 'tasks').mkdir(parents=True)
    git(seed, 'init', '-q', '-b', 'main')
    (seed / 'plan' / 'TODO.md').write_text(TODO, encoding='utf-8')
    (seed / 'plan' / 'tasks' / 'T1.md').write_text('# T1\nlong form\n', encoding='utf-8')
    (seed / 'a.py').write_text('# a\n')
    git(seed, 'add', '-A')
    git(seed, 'commit', '-qm', 'start')
    (seed / 'plan' / 'TODO.md').write_text(TODO + '- [ ] **T4** fourth | files: d.py\n', encoding='utf-8')
    git(seed, 'commit', '-qam', 'plan: add T4')
    git(tmp, 'clone', '-q', '--bare', str(seed), 'code.git')
    a, b = tmp / 'A', tmp / 'B'
    for d in (a, b):
        git(tmp, 'clone', '-q', str(tmp / 'code.git'), d.name)
        (d / '.git' / 'info' / 'exclude').write_text('.runner/\n')
    print('repo-setup: from a plain repo')
    (a / 'plan' / 'TODO.md').write_text(TODO + '- [ ] **T4** fourth | files: d.py\n- [ ] **T5** uncommitted\n',
                                       encoding='utf-8')
    pr = (tmp / 'plan.git').as_posix()
    r = run(a, 'plan', 'repo-setup', pr)
    check(r.returncode == 0, 'repo-setup succeeds', r.stdout + r.stderr)
    has(r.stdout, r'On the other machine.*plan repo-setup ' + re.escape(pr), 'and prints the line for the other machine')
    has(git(tmp / 'plan.git', 'show', 'main:TODO.md'), r'T5\*\* uncommitted', 'the plan, edits too, is in the plan repo')
    has(git(tmp / 'plan.git', 'show', 'main:tasks/T1.md'), 'long form', 'with its long forms')
    has(git(tmp / 'plan.git', 'log', '--format=%s', 'main'), r'plan: add T4', 'and its history')
    has((a / 'runner.toml').read_text(), r'repo = "' + re.escape(pr), 'runner.toml names the plan repo')
    eq(git(a, 'ls-files', 'plan'), '', 'the plan is gone from the code repo')
    eq(git(a, 'status', '--porcelain', '--untracked-files=no'), '', 'all of it in a commit')
    has(run(a, 'plan').stdout, r'T5', '`plan` reads the plan repo')
    print('repo-setup: a second checkout joins')
    git(a, 'push', '-q', 'origin', 'HEAD:main')
    git(b, 'pull', '-q')
    r = run(b, 'plan', 'repo-setup', pr)
    check(r.returncode == 0, 'repo-setup on the second checkout', r.stdout + r.stderr)
    has(r.stdout, r'plan repo mode is on', 'says it is on')
    has(run(b, 'plan').stdout, r'T5', 'and B reads the shared plan')
    print('repo-setup: joining before the code merge')
    c2 = tmp / 'C'
    git(tmp, 'clone', '-q', '-b', 'main', str(seed), c2.name)  # still has its own plan
    (c2 / '.git' / 'info' / 'exclude').write_text('.runner/\n')
    r = run(c2, 'plan', 'repo-setup', pr)
    check(r.returncode == 0, 'joins a plan repo that holds a plan', r.stdout + r.stderr)
    has(r.stdout, r'joined', 'says it joined')
    has(config.Config(c2).todo.read_text(), r'T5', 'and reads the shared plan')

    print('hint: claims from another host')
    from agent_runner import plansync as PS
    ca = config.Config(a)
    eq(PS.share_hint(ca), '', 'no hint in plan repo mode')
    cs = config.Config(seed)
    real_store, real_claims = PS.store, PS.claims
    PS.store = lambda c: object()
    PS.claims = lambda c: {'T1': PS.Claim('x', 0.0, 'pat@other-box')}
    try:
        has(PS.share_hint(cs), r'other-box.*plan repo-setup', 'claims from another host give the hint')
        eq(PS.share_hint(cs), '', 'once')
    finally:
        PS.store, PS.claims = real_store, real_claims


def test_fetch_taken(tmp: Path) -> None:
    print('takeover: the task starts from the task/<ID> branch the gone run pushed (F467)')
    tmp.mkdir()
    git(tmp, 'init', '-q', '--bare', 'origin.git')
    repo = tmp / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'a.py').write_text('# a\n')
    (repo / '.gitignore').write_text('.runner/\n')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(tmp / 'origin.git'))
    git(repo, 'checkout', '-qb', 'task/T9')
    (repo / 'a.py').write_text('# gone run\n')
    git(repo, 'commit', '-qam', 'T9 wip')
    pushed = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'push', '-q', 'origin', 'task/T9')
    git(repo, 'checkout', '-q', '-')
    git(repo, 'branch', '-D', 'task/T9')
    from agent_runner import runner as R, sched
    R.init(repo)
    check(sched.fetch_taken('T9'), 'the pushed branch is fetched')
    eq(git(repo, 'rev-parse', 'took/T9'), pushed, 'into took/T9')
    eq(sched.took_base('T9'), pushed, 'which slots.start checks out')
    eq(sched.took_base('T9'), '', 'once: the took/T9 branch is dropped')
    check(not sched.fetch_taken('T8'), 'a task with no pushed branch starts fresh')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        return report([lambda: test_all(Path(t)), lambda: test_in_repo(Path(t) / 'in-repo'),
                       lambda: test_repo_setup(Path(t) / 'setup'), lambda: test_fetch_taken(Path(t) / 'took')])


if __name__ == '__main__':
    sys.exit(main())
