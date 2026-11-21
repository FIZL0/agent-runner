#!/usr/bin/env python3
"""The runner, end to end in a throwaway repo with a bare repo as its remote — no tmux, no real agent.

    python3 tests/test_runner.py        (no network; a few seconds, mostly git)

What it proves is the part a night depends on and nobody watches: which task a free slot takes, that
`done` gates, ticks, commits and pushes only the task branch, and that a finished branch is merged in the
merge worktree, joined or handed to a fix session when it conflicts, tested, landed, pushed, its remote
copy dropped, and the blocks it freed reopened — or parked as wip/<ID> when it cannot land (but kept as
task/<ID> while it only waits on edits in the main checkout).
"""
from __future__ import annotations

import json
import os
import subprocess
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from _check import RUN, check, eq, git, has, report, run

from agent_runner import plan as P  # noqa: E402
from agent_runner import gitops  # noqa: E402
from agent_runner import runner as R  # noqa: E402

TODO = """# TODO

### Next (in this order)

- [ ] **T1** the parser | files: a.py
- [ ] **T2** the printer | files: b.py

### Later

- [ ] **T3** speed up the parser | files: a.py
- [ ] **T6** builds on T1's parser | files: c.py | after: T1
- [ ] **T5** the logger | files: d.py, CHANGELOG.md
- [ ] **T4** the report | files: e.py | after: T1, T5
- [ ] **L3a** half of it | files: f.py
- [ ] **L3b** the other half | files: g.py

### Stretch

- [ ] **S1** a web page | files: web/index.html
"""

FAKE_AGENT = r'''#!/usr/bin/env python3
# A stand-in for `claude -p`: FAKE_FIX=theirs resolves a merge with the branch's side, =abort gives up,
# =repair removes BROKEN in a commit on top. FAKE_PROMPT names a file to write the prompt to.
import os, subprocess, sys
g = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True)
if os.environ.get('FAKE_PROMPT'):
    open(os.environ['FAKE_PROMPT'], 'w').write(sys.argv[sys.argv.index('-p') + 1])
if os.environ.get('FAKE_FIX') == 'repair':
    g('rm', '-q', 'BROKEN'); g('commit', '-qm', 'repair: drop BROKEN')
    if os.environ.get('FAKE_MAIN'):  # main moves while it works: the merge is built again, the repair replayed
        open(os.path.join(os.environ['FAKE_MAIN'], 'moved.txt'), 'w').write('x\n')
        subprocess.run(['git', 'add', 'moved.txt'], cwd=os.environ['FAKE_MAIN'])
        subprocess.run(['git', 'commit', '-qm', 'main: moved'], cwd=os.environ['FAKE_MAIN'])
    print('the two sides clashed in BROKEN')
elif os.environ.get('FAKE_FIX') == 'theirs':
    for f in g('diff', '--name-only', '--diff-filter=U').stdout.split():
        g('checkout', '--theirs', '--', f); g('add', f)
    g('commit', '-q', '--no-edit')
    print('resolved with the branch side')
else:
    g('merge', '--abort')
    print('these contradict each other; a human picks')
'''


def make_repo(tmp: Path) -> Path:
    git(tmp, 'init', '-q', '--bare', '-b', 'main', 'origin.git')
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    for f in 'abcdefg':
        (repo / f'{f}.py').write_text(f'# {f}\n', encoding='utf-8')
    (repo / 'CHANGELOG.md').write_text('# Changelog\n', encoding='utf-8')
    # the gate: fails while a file named BROKEN exists
    (repo / 'check.py').write_text('import os, sys\nsys.exit(1 if os.path.exists("BROKEN") else 0)\n')
    (repo / 'runner.toml').write_text(
        '[run]\ntest = "python3 check.py"\nshared_files = ["CHANGELOG.md"]\n'
    'min_free_gb = 0\n'
        'remote = false\n'  # 'auto' would follow this machine's login; test_remote_auto covers it
        'joinable = ["plan/TODO.md", "plan/DONE.md", "CHANGELOG.md"]\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(tmp / 'origin.git'))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    return repo


def use_fake_fix_agent(agent: Path):
    original = R.fix_cmd
    if R.plat.WINDOWS:
        R.fix_cmd = lambda prompt: [sys.executable, str(agent), '-p', prompt]
    return original


def remote_branches(tmp: Path) -> set[str]:
    return set(git(tmp / 'origin.git', 'branch', '--format=%(refname:short)').split())


def test_picking(repo: Path):
    print('run: which task a free slot may take')
    R.init(repo)
    eq((R.family('L3a'), R.family('L3b'), R.family('M8f4')), ('L3', 'L3', 'M8'),
       'siblings share a family, so they never run side by side')
    ids = [t[0] for t in R.tasks('main')]
    eq(ids[0], 'T1', 'the first startable task is the first line of the backlog')
    check('S1' not in ids, 'Stretch is never offered to a run')
    check('T4' not in ids, '`after: T1, T5` holds the task while either is open — every id, not just the first')
    check('T6' not in ids, 'and `after: T1` holds T6')
    first = R.pick({}, set(), 'main')
    eq(first[0], 'T1', 'an empty run starts at the top')
    second = R.pick({1: first}, set(), 'main')
    eq(second[0], 'T5', 'with T1 running: not T2 (ordered section), T3 (same file), T6 (after: T1)')
    check(not R.ordered('Next (user priorities, in order)') and R.ordered('Next (in this order)')
          and R.ordered('Bugs (one at a time)'), 'a priority order starts side by side; "in this order" runs one at a time')
    third = R.pick({1: first, 2: second}, set(), 'main')
    eq(third[0], 'L3a', 'CHANGELOG.md is a shared file, so it is not an overlap')
    check((R.pick({1: first, 2: second, 3: third}, set(), 'main') or ('',))[0] != 'L3b',
          'a sibling of a running task waits')
    touched, ahead = R.touched, R.ahead
    R.touched = lambda tid, branch, slot: {'d.py'} if tid == 'T1' else set()
    try:
        eq(R.pick({1: first}, set(), 'main')[0], 'L3a', 'a file the running T1 has touched (d.py) holds T5 too')
        R.ahead = lambda branch: ['T1']
        eq(R.pick({}, set(), 'main')[0], 'T3',
           'a finished T1 waiting to merge holds its section and the files it changed (d.py), not its line\'s a.py')
    finally:
        R.touched, R.ahead = touched, ahead
    Claim, me = R.plansync.Claim, R.plansync.owner(R.C)
    claims, R.plansync.claims = R.plansync.claims, lambda c: {'T1': Claim('elsewhere:/x', time.time(), 'ian@desk')}
    try:
        eq(R.pick({}, set(), 'main')[0], 'T5',
           "another runner's live claim on T1 holds its files, section and dependants here too")
        R.plansync.claims = lambda c: {'T1': Claim('elsewhere:/x', time.time() - 4 * 3600, 'ian@desk')}
        eq(R.pick({}, set(), 'main')[0], 'T2', "a stale claim (a crashed run's) holds only its own task")
        R.plansync.claims = lambda c: {'S9': Claim('elsewhere:/x', time.time(), 'ian@desk', '0.14.0', 1.0,
                                                   frozenset({'a.py'}))}
        check(R.pick({}, set(), 'main')[0] not in ('T1', 'T3'),
              "files a claim says its session touched hold too, whatever its line lists")
        # the race: both runners pick from plans read before the other's claim, and both claims push
        st, gave = {}, []

        def raced(c):  # nothing claimed until this run claims; then theirs on T3 (T1's file) and ours both show
            if 'tid' not in st:
                return {}
            return {'T3': Claim('elsewhere:/x', time.time(), 'ian@desk', '0.14.0', st['theirs']),
                    st['tid']: Claim(me, time.time(), 'me@here', '0.14.0', 2.0)}

        def claim_(c, tid, files=()):
            st['tid'] = tid
            return True

        saved = (R.plansync.claim, R.plansync.release, R.C.raw['plan']['repo'], R.log)
        R.plansync.claims, R.plansync.claim, R.plansync.release = raced, claim_, lambda c, t: gave.append(t)
        R.C.raw['plan']['repo'], R.log = 'plan.git', lambda m: None
        try:
            st['theirs'] = 1.0
            got = R.pick({}, set(), 'main', claim=True)[0]
            check(got not in ('T1', 'T3'), 'the later of two clashing claims gives way: T1 shares a file with their T3',
                  got)
            eq(gave[:1], ['T1'], 'releasing the claim it gave way on')
            gave.clear()
            st.clear()
            st['theirs'] = 3.0
            eq(R.pick({}, set(), 'main', claim=True)[0], 'T1', 'the earlier claim keeps its task')
            eq(gave, [], 'and releases nothing')
        finally:
            R.plansync.claim, R.plansync.release, R.C.raw['plan']['repo'], R.log = saved
    finally:
        R.plansync.claims = claims
    files = set(R.P.files_on_line('menu | files: Assets/Settings/**, docs/a.md | test: x'))
    check({'Assets/Settings/**', 'docs/a.md'} <= files, 'a `dir/**` on the line is a file pattern', str(files))
    check(R.P.overlap({'Assets/Settings/**'}, {'Assets/Settings/Page.cs'}), 'a pattern meets a path under it')
    check(R.P.overlap({'Assets/Settings/**'}, {'Assets/Settings/**'}), 'and the same pattern on another line')
    check(not R.P.overlap({'Assets/Settings/**'}, {'Assets/Audio/Mix.cs'}), 'but not a path elsewhere')
    check(R.P.overlap({'src/menu.rs'}, {'app/src/menu.rs'}) and not R.P.overlap({'menu.rs'}, {'app/submenu.rs'}),
          'a short path meets the full one it is the tail of, at a / only')
    # T6: a waiting line's whole-directory guess (`tests/**`) does not wait on files another task touched
    waiting = ('W1', 'Next', {'tests/**', 'w.py'}, set())
    toucher = ('B1', 'Other', {'b.py', 'tests/test_x.py'}, set(), {'b.py'})  # touched tests/test_x.py
    check(not R.clash(waiting, toucher, set()), 'tests/** does not clash with a test file B1 only touched')
    check(not R.clash(waiting, ('B1', 'Other', {'tests/test_x.py'}, set(), {'tests/test_x.py'}), set()),
          'nor with a test file named on B1\'s line (B62: a whole-dir glob meets only another)')
    check(R.clash(waiting, ('B1', 'Other', {'tests/**'}, set(), {'tests/**'}), set()),
          'and with the same glob on B1\'s line')
    check(R.clash(('W2', 'Next', {'tests/test_x.py'}, set()), toucher, set()),
          'a named file still clashes with a file B1 touched')
    check(R.clash(waiting, ('B1', 'Other', {'w.py'}, set(), set()), set()), 'a named file beside the glob still clashes')
    check(R.clash(waiting, ('B1', 'Other', {'tests/**'}, set()), set()),
          'a busy tuple without its line files counts all its files as named')
    # B62: a whole-dir glob is a hard lock only against another whole-dir glob, both ways
    rewrite = ('W3', 'Next', {'native/**'}, set())
    check(not R.clash(rewrite, ('B2', 'Other', {'native/a.py'}, set(), {'native/a.py'}), set()),
          'a waiting native/** starts beside a busy task whose line names native/a.py')
    named = ('W4', 'Next', {'native/a.py'}, set())
    check(not R.clash(named, ('B3', 'Other', {'native/**', 'native/b.py'}, set(), {'native/**'}), set()),
          'a waiting native/a.py starts beside a busy native/** that touched only native/b.py')
    check(R.clash(named, ('B3', 'Other', {'native/**', 'native/a.py'}, set(), {'native/**'}), set()),
          'but waits once it touched native/a.py')
    check(R.clash(rewrite, ('B3', 'Other', {'native/**'}, set(), {'native/**'}), set()),
          'native/** vs native/** still clash')
    check(R.whole_dir('tests/**') and R.whole_dir('src/ui/*') and not R.whole_dir('src/*.rs')
          and not R.whole_dir('a.py'), 'what counts as a whole-directory glob')
    eq(R.pick({}, set(ids), 'main'), None, 'nothing left once everything has been tried')
    check(R.joinable('CHANGELOG.md'), 'CHANGELOG.md is in [run] joinable, so a conflict there is joined')
    for f in ('README.md', 'a.py', 'plan/T1.md', 'plan/TODO.md', 'plan/DONE.md'):
        check(not R.joinable(f), f'{f} is not (the task list: git merged it by task already), so it needs reading')
    r = run(repo, 'run', '--dry-run', '3')
    has(r.stdout, r'slot 1: T1.*\nslot 2: T5.*\nslot 3: L3a', '`run run --dry-run 3` prints the three picks')
    has(r.stdout, r'waiting on .*T4', 'and what waits')
    has(r.stdout, r'waiting for files: [^\n]*T3 \([^)]* held by T1\)', 'a file clash names the file and who holds it')
    has(r.stdout, r'one at a time in "[^"]*": [^\n]*T2 \(T1\)', 'an ordered section names the task ahead')
    has(r.stdout, r'waiting for a sibling: [^\n]*L3b \(L3a\)', 'and a sibling names its running sibling')
    r = run(repo, 'run', '--dry-run', '1')
    has(r.stdout, r'next, once a slot is free: [^\n]*T5', 'a task free to start but out of slots is listed as next')


def test_master_branch_option(tmp: Path):
    print('git: an explicit master_branch overrides origin/HEAD and is the shared branch')
    default_dir = tmp / 'default'
    default_dir.mkdir()
    default_repo = make_repo(default_dir)
    R.init(default_repo)
    eq(R.default_branch(), 'main', 'without an override, remote/default branch discovery is unchanged')

    option_dir = tmp / 'option'
    option_dir.mkdir()
    option_repo = make_repo(option_dir)
    git(option_repo, 'branch', 'Development_Branch')
    git(option_repo, 'symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/main')
    with open(option_repo / 'runner.toml', 'a', encoding='utf-8') as config:
        config.write('\n[git]\nmaster_branch = "Development_Branch"\n')
    R.init(option_repo)
    try:
        R.default_branch()
    except SystemExit as error:
        check('must be checked out' in str(error), 'an override cannot silently start a run on another branch', str(error))
    else:
        check(False, 'an override cannot silently start a run on another branch')
    git(option_repo, 'checkout', '-q', 'Development_Branch')
    eq(R.default_branch(), 'Development_Branch', 'the run targets the configured branch')
    eq(gitops.shared_name(option_repo, 'origin'), 'Development_Branch', 'shared-branch detection uses the override')
    check(gitops.shared_branch(option_repo, 'origin', 'Development_Branch'),
          'the configured branch is treated as shared for push safety')
    check(not gitops.shared_branch(option_repo, 'origin', 'main'), 'the old remote default is not shared')
    R.C.raw['git']['master_branch'] = 'missing'
    try:
        R.default_branch()
    except SystemExit as error:
        check('does not exist as a local branch' in str(error), 'a missing override fails clearly', str(error))
    else:
        check(False, 'a missing override fails clearly')


def test_parked_twice(repo: Path, tmp: Path):
    print('run: a task parked twice is blocked on a person, not started a third time (B32)')
    R.init(repo)
    rel = 'plan/TODO.md'
    before = (repo / rel).read_text(encoding='utf-8')
    # a slot's saved edits (save_leftovers) are no failed merge: they never count
    saved = git(repo, 'commit-tree', 'main^{tree}', '-p', 'main', '-m', 'T5 wip: uncommitted edits').strip()
    git(repo, 'branch', 'wip/T5', saved)
    try:
        with mock.patch.object(R, 'merge', lambda tid, branch: 'tests fail after the merge'):
            for k in (1, 2):
                sha = git(repo, 'commit-tree', 'main^{tree}', '-p', 'main', '-m', f'T2 attempt {k}').strip()
                git(repo, 'branch', 'task/T2', sha)
                R.finish('T2', 1, 'sid', 'main')
                if k == 1:
                    eq(R.pick({}, {'T1'}, 'main')[0], 'T2', 'parked once: the task starts again')
        eq(sorted(R.parked_attempts().get('T2', [])), ['wip/T2', 'wip/T2-2'], 'parked twice, as wip/T2 and wip/T2-2')
        check('T5' not in R.parked_attempts(), 'a wip/<ID> of saved edits is not a parked attempt')
        why = {}
        R.pick({}, {'T1'}, 'main', why=why)
        eq(why.get('T2', ('',))[0], 'parked 2 times, needs a person', 'the dry run says why it waits')
        got = R.pick({}, {'T1'}, 'main', claim=True)
        check(got is None or got[0] != 'T2', 'the third pick skips it', got)
        check('T2' in R.blocked_tasks('main'), 'and blocks it')
        a = [x for x in P.asks(repo / rel) if x[1] == 'T2']
        eq([x[0] for x in a], ['DECIDE'], 'on a person: listed under Needs you')
        has(a[0][3] if a else '', r'wip/T2, wip/T2-2.*tests fail after the merge', 'with the branches and the ledger reasons')
        eq(git(repo, 'status', '--porcelain', '--', rel), '', 'committed')
        logged = (repo / '.runner/run.log').read_text(encoding='utf-8').splitlines()
        parked = [l for l in logged if 'T2: not merged, parked as wip/T2-2' in l]
        left = [l for l in logged if 'T2: LEFT FOR A HUMAN — parked 2 times' in l]
        check(parked and left, 'run.log has the parked and the blocked lines', logged[-4:])
        now = R.dt.datetime.now()
        check(parked and R.needs_you_line(parked[-1], {}, now, []) and left and R.needs_you_line(left[-1], {}, now, []),
              'both reach the needs-you feed')
        P.unblock('T2', 'try once more', todo=repo / rel)
        git(repo, 'commit', '-qm', 'test: unblock T2', '--', rel)
        eq(R.pick({}, {'T1'}, 'main')[0], 'T2', 'unblocked by a person: the attempts it was blocked over no longer count')
    finally:
        R.C.notes('parked-seen.json').unlink(missing_ok=True)
        for b in ('wip/T2', 'wip/T2-2', 'wip/T5', 'task/T2'):
            subprocess.run(['git', 'branch', '-D', b], cwd=repo, capture_output=True)
            subprocess.run(['git', 'push', '-q', 'origin', '--delete', b], cwd=repo, capture_output=True)
        if (repo / rel).read_text(encoding='utf-8') != before:
            (repo / rel).write_text(before, encoding='utf-8')
            git(repo, 'commit', '-qm', 'test: T2 open again', '--', rel)


def test_split_parents(repo: Path):
    print('run: split parents wait for their subtasks, blocked ones too; the words alone hold nothing')
    R.init(repo)
    d = R.worktree('split', 'main')
    git(d, 'checkout', '-q', '-B', 'splitcheck', 'main')
    (d / 'plan/TODO.md').write_text("""# TODO

### Later

- [ ] **P1** the importer (split into P1a, X2) | files: a.py
- [~] **P1a** read the header | files: a.py BLOCKED: needs a sample file
- [ ] **X2** read the body | files: b.py
- [ ] **B9** the settings page, split into two tabs | files: c.py
- [ ] **Q1** the exporter (split into Q1a) | files: d.py
""", encoding='utf-8')
    git(d, 'commit', '-qam', 'split check')
    try:
        ids = [t[0] for t in R.tasks('splitcheck')]
        check('P1' not in ids, 'P1 waits: its subtask P1a is blocked, not done')
        check('B9' in ids, 'B9 runs: "split into two tabs" in a description is not a split')
        check('Q1' in ids, 'Q1 runs: its subtask is gone (done), so the parent is next')
    finally:
        git(repo, 'worktree', 'remove', '--force', str(d))
        git(repo, 'branch', '-D', 'splitcheck')


def test_blockers_first(repo: Path):
    print('run: what a waiting task is blocked on takes its place; a pushed plan is read before the merge')
    R.init(repo)
    d = R.worktree('wait', 'main')
    git(d, 'checkout', '-q', '-B', 'waitcheck', 'main')
    (d / 'plan/TODO.md').write_text("""# TODO

### Next: races (in this order)

- [~] **S12e** the AI riders | files: e.py BLOCKED: (after S282) needs the route follower
- [ ] **S13c** laps | files: c.py

### Follow-ups

- [ ] **M1** a car | files: m.py
- [ ] **S283** the AI character | files: a.py
- [ ] **S282** the route follower | files: a.py | after: S283

### Stretch

- [ ] **Z1** someday | files: z.py | after: M1
""", encoding='utf-8')
    git(d, 'commit', '-qam', 'wait check')
    try:
        ids = [t[0] for t in R.tasks('waitcheck')]
        eq(ids, ['S283', 'S13c', 'M1'], 'S283 (S282 waits on it, S12e on S282) goes first; Stretch pulls nothing')
        git(d, 'checkout', '-q', '--detach')
        git(repo, 'update-ref', 'refs/remotes/origin/waitcheck', 'waitcheck')
        git(d, 'checkout', '-q', 'waitcheck')
        (d / 'plan/TODO.md').write_text((d / 'plan/TODO.md').read_text(encoding='utf-8').replace(
            '- [ ] **S13c**', '- [x] **S13c**'), encoding='utf-8')
        git(d, 'commit', '-qam', 'S13c landed elsewhere')
        git(repo, 'update-ref', 'refs/remotes/origin/waitcheck', 'waitcheck')
        git(repo, 'update-ref', 'refs/heads/waitcheck', 'waitcheck~1')
        cls = type(R.C)
        with mock.patch.object(cls, 'push_remote', new=property(lambda s: 'origin')), \
                mock.patch.object(cls, 'push_merge', new=property(lambda s: True)):
            R.FETCHED[0] = time.time()  # no fetch: the ref above stands in for one
            check('S13c' not in [t[0] for t in R.tasks('waitcheck')], 'the remote, ahead, is the plan read')
            git(repo, 'update-ref', 'refs/heads/waitcheck', 'refs/remotes/origin/waitcheck')
            git(repo, 'update-ref', 'refs/remotes/origin/waitcheck', 'waitcheck~1')
            eq(R.newest('waitcheck'), 'waitcheck', 'a remote behind the branch is not read')
    finally:
        git(repo, 'worktree', 'remove', '--force', str(d))
        git(repo, 'branch', '-D', 'waitcheck')
        git(repo, 'update-ref', '-d', 'refs/remotes/origin/waitcheck')


def task_branch(repo: Path, n: int, tid: str) -> Path:
    """A slot worktree on task/<tid>, the way `start` leaves it for a session."""
    d = R.worktree(n, 'main')
    git(d, 'checkout', '-q', '-B', f'task/{tid}', 'main')
    return d


def test_run_policies(repo: Path, tmp: Path):
    print('run: project-configured commit and merge subjects and comment guidance')
    fixture = tmp / 'policy-fixture'
    fixture.mkdir()
    policy_repo = make_repo(fixture)
    (policy_repo / 'runner.toml').write_text(
        '[run]\n'
        f'home = "{fixture.as_posix()}/runner-home/{{repo}}"\n'
        'include_task_id_in_commit = false\ncomment_policy = "minimal"\n'
        '[git]\npush = false\n', encoding='utf-8')
    git(policy_repo, 'add', 'runner.toml')
    git(policy_repo, 'commit', '-qm', 'configure policy fixture')
    env = {**os.environ, 'AGENT_RUNNER_CONFIG': str(policy_repo / 'runner.toml')}
    old_config = os.environ.get('AGENT_RUNNER_CONFIG')
    os.environ['AGENT_RUNNER_CONFIG'] = env['AGENT_RUNNER_CONFIG']
    R.init(policy_repo)
    try:
        from agent_runner import config
        R.C = config.Config(policy_repo)
        prompt = R.prompt_for('T2', 1, 1, policy_repo, 'main')
        has(prompt, r'Do not include task ID .+ in the commit subject',
            'the task-ID setting reaches the agent prompt')
        has(prompt, r'Only add comments when necessary to explain non-obvious intent',
            'the comment policy reaches the agent prompt')

        git(policy_repo, 'checkout', '-q', '-b', 'task/T2', 'main')
        result = run(policy_repo, 'done', 'T2', 'T2: the printer', env=env)
        check(result.returncode == 0, 'configured task completion succeeds', result.stdout + result.stderr)
        eq(git(policy_repo, 'log', '-1', '--format=%s'), 'the printer',
           'the configured commit subject omits its task ID')
        printer_ref = git(policy_repo, 'rev-parse', 'HEAD')

        git(policy_repo, 'checkout', '-q', '-b', 'task/T3', 'main')
        (policy_repo / 'logger.py').write_text('def log(): pass\n', encoding='utf-8')
        git(policy_repo, 'add', 'logger.py')
        result = run(policy_repo, 'done', 'T3', 'T3: the logger', env=env)
        check(result.returncode == 0, 'configured batch-rider completion succeeds', result.stdout + result.stderr)
        eq(git(policy_repo, 'log', '-1', '--format=%s'), 'the logger',
           'the configured batch-rider commit subject omits its task ID')
        logger_ref = git(policy_repo, 'rev-parse', 'HEAD')

        eq(R.merge_message('T2', printer_ref), 'Merge: the printer',
           'the configured primary merge message omits its task ID')
        eq(R.merge_message('T3', logger_ref), 'Merge: the logger',
           'the configured batch-rider merge message omits its task ID')
    finally:
        if old_config is None:
            os.environ.pop('AGENT_RUNNER_CONFIG', None)
        else:
            os.environ['AGENT_RUNNER_CONFIG'] = old_config
        R.init(repo)


def test_no_remote(repo: Path, tmp: Path):
    print('git: [git] push names a remote this repo does not have: said once, not silently skipped (B70)')
    fixture = tmp / 'no-remote-fixture'
    fixture.mkdir()
    lone = make_repo(fixture)
    git(lone, 'remote', 'remove', 'origin')
    with open(lone / 'runner.toml', 'a', encoding='utf-8') as f:
        f.write(f'home = "{fixture.as_posix()}/runner-home/{{repo}}"\n[git]\npush = "origin"\npush_merge = true\n')
    git(lone, 'add', 'runner.toml')
    git(lone, 'commit', '-qm', 'configure no-remote fixture')
    env = {**os.environ, 'AGENT_RUNNER_CONFIG': str(lone / 'runner.toml')}
    old_config = os.environ.get('AGENT_RUNNER_CONFIG')
    os.environ['AGENT_RUNNER_CONFIG'] = env['AGENT_RUNNER_CONFIG']
    R.init(lone)
    try:
        from agent_runner import config
        R.C = config.Config(lone)
        eq(gitops.missing_remote(lone), 'origin', 'missing_remote names the configured remote that is not there')
        eq(gitops.missing_remote(repo), None, 'and nothing where the remote exists')
        has(R.no_remote_line('origin'), r'^\[git\] push = origin: no such remote here, merges stay local; '
            r'git remote add origin <url> to publish$', 'the run start line says it, and how to fix it')
        p = R.prompt_for('T2', 1, 1, lone, 'main')
        check('one copy of your work' not in p and 'no remote `origin`' in p,
              'the prompt does not claim done pushes the one off-disk copy', p)
        git(lone, 'checkout', '-q', '-b', 'task/T2', 'main')
        result = run(lone, 'done', 'T2', 'T2: the printer', env=env)
        check(result.returncode == 0, 'done goes through without a remote', result.stdout + result.stderr)
        has(result.stdout, r'^task/T2 not pushed: no remote origin', 'and says the branch is not pushed')
    finally:
        if old_config is None:
            os.environ.pop('AGENT_RUNNER_CONFIG', None)
        else:
            os.environ['AGENT_RUNNER_CONFIG'] = old_config
        R.init(repo)


def test_done(repo: Path, tmp: Path):
    print('done: gate, tick, commit, push the task branch — never the shared one')
    d = task_branch(repo, 1, 'T5')
    check((d / 'runner.toml').exists(), 'the worktree has the runner.toml')
    trusted = json.loads((tmp / '.claude.json').read_text())['projects'][d.resolve().as_posix()]
    check(trusted.get('hasTrustDialogAccepted'), "the worktree is a folder Claude Code already trusts", trusted)
    check(any('"skipDangerousModePermissionPrompt": true' in a for a in R.Claude().flags('s', 'opus', 30, False, False)),
          'a session skips the bypass-mode warning, which lean mode would otherwise bring back')
    (d / 'd.py').write_text('def log(x):\n    print(x)\n', encoding='utf-8')
    (d / 'BROKEN').write_text('', encoding='utf-8')
    r = run(d, 'done', 'T5', 'T5: the logger')
    check(r.returncode == 1 and 'gate failed' in r.stderr, 'a failing gate refuses', r.stdout + r.stderr)
    check('- [ ] **T5**' in (d / 'plan/TODO.md').read_text(), 'and ticks nothing')
    eq(git(d, 'rev-list', '--count', 'main..HEAD'), '0', 'and commits nothing')
    has(r.stderr, r'Failed gate 1 of 3', 'and counts the failure')
    for n in (1, 2, 3):  # a session that keeps re-running a failing gate on Z9
        r = run(d, 'done', 'Z9', 'Z9: loops')
    check(r.returncode == 1 and 'refuses a fourth' in r.stderr, 'the third failed gate says a fourth is refused',
          r.stdout + r.stderr)
    (d / 'BROKEN').unlink()
    r = run(d, 'done', 'Z9', 'Z9: loops')
    check(r.returncode == 1 and 'a fourth is not run' in r.stderr and 'gate passed' not in r.stdout,
          'and the fourth refuses without running the gate (which would pass now)', r.stdout + r.stderr)
    eq(git(d, 'rev-list', '--count', 'main..HEAD'), '0', 'committing nothing')
    with open(d / 'CHANGELOG.md', 'a') as f:
        f.write('- T5: the logger\n')
    output_env = {**os.environ, 'PYTHONIOENCODING': 'cp1252'}
    r = run(d, 'done', 'T5', 'T5: the logger', env=output_env)
    check(r.returncode == 0, 'a passing gate goes through', r.stdout + r.stderr)
    from agent_runner import done as D
    eq((D.fails(d, 'T5'), D.fails(d, 'Z9')), (0, 3), "and clears T5's failed-gate count, not Z9's")
    has(r.stdout, r'pushed task/T5 -> origin', 'and pushes the task branch with CP1252 output enabled')
    check('task/T5' in remote_branches(tmp), 'which is on the remote now')
    has((d / 'plan/DONE.md').read_text(), r'- \[x\] \*\*T5\*\*', 'T5 is ticked into DONE.md on the branch')

    # meanwhile on main: somebody ticks T1 and logs it (a DONE.md and CHANGELOG.md conflict to come)
    with open(repo / 'CHANGELOG.md', 'a') as f:
        f.write('- T1: the parser\n')
    r = run(repo, 'done', 'T1', 'T1: the parser', '--no-test')
    check(r.returncode == 0, 'done in the main checkout commits', r.stdout + r.stderr)
    has(r.stdout, r'main is not pushed', 'but says main is the runner\'s to push')
    check(git(tmp / 'origin.git', 'rev-parse', 'main') != git(repo, 'rev-parse', 'main'),
          'and the remote main is where it was')
    P.block('T4', 'needs T1 and T5 landed', todo=repo / 'plan/TODO.md')
    git(repo, 'commit', '-qam', 'T4: blocked')
    has((repo / 'plan/TODO.md').read_text(), r'\*\*T4\*\*.*BLOCKED: \(after T5\)',
        'block records only the id still open: T1 was ticked first')


def test_note_on_a_ticked_task(repo: Path):
    print('run: a note main added while the branch ticked the task is kept, on the task in DONE.md')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text().replace('### Stretch', '- [ ] **U2** noted | files: u2.py\n\n### Stretch'))
    git(repo, 'commit', '-qam', 'plan: U2')
    d = task_branch(repo, 1, 'U2')
    (d / 'u2.py').write_text('# u2\n')
    R.P.tick('U2', d / 'plan/TODO.md', d / 'plan/DONE.md')
    git(d, 'add', '-A'), git(d, 'commit', '-qm', 'U2: u2'), git(d, 'checkout', '-q', '--detach')
    R.P.note('U2', 'a person said this', todo=todo)
    git(repo, 'commit', '-qam', 'plan: note U2')
    eq(R.merge('U2', 'main'), None, 'the merge lands')
    check('**U2**' not in todo.read_text(), 'the tick wins in TODO.md')
    has((repo / 'plan/DONE.md').read_text(encoding='utf-8'), r'\*\*U2\*\* noted.* — a person said this', 'and the note went with it')


def test_adopt_merge(repo: Path):
    print('run: a restarted run adopts the gate run and the fix or repair session an earlier one left going')
    R.init(repo)
    d = R.worktree('merge', 'main')
    git(d, 'checkout', '-q', '--detach', 'main')
    start = git(d, 'rev-parse', 'HEAD')
    test, R.C.run['test'] = R.C.run['test'], 'echo ok >> ../gate-ran.log'
    ran = d.parent / 'gate-ran.log'
    ran.unlink(missing_ok=True)
    try:
        if not R.plat.WINDOWS:
            gates = R.C.notes(R.GATES)
            gates.mkdir(exist_ok=True)
            out = gates / f'{R.gate_key(d)}.out'
            with open(out, 'w') as fh:  # as merge_gate starts it, by a run that is gone now
                p = R.sp.Popen(f'(sleep 1; {R.C.run["test"]}\n); echo $? > {out.with_suffix(".rc")}', shell=True,
                               cwd=str(d), stdout=fh, stderr=R.sp.STDOUT, start_new_session=True)
            rec = out.with_suffix('.json')
            rec.write_text(R.json.dumps({'tid': 'Z1', 'pid': p.pid, 'out': str(out), 'until': R.time.time() + 60,
                                         'cwd': str(d), 'rec': str(rec)}))
            eq(R.left_merging(), {'Z1'}, 'a live gate run names its task, which startup merges first')
            R.adopt_merge(d)
            p.wait()
            check(not rec.exists(), 'the adopted gate is waited for')
            eq(R.merge_gate('Z1', d, R.merge_env()), (0, ''), 'and its pass counts')
            eq(ran.read_text().count('ok'), 1, 'so the gate is not run a second time on that merge')
            eq(R.merge_gate('Z1', d, R.merge_env())[0], 0, 'nor a third')
        (d / 'z1.py').write_text('# repaired\n')
        git(d, 'add', 'z1.py'), git(d, 'commit', '-qm', 'Z1: repair')
        made = git(d, 'rev-parse', 'HEAD')
        # a repair session that ended while no run was up: its pid is gone, its commit is in the worktree
        R.C.notes('master.json').write_text(R.json.dumps({'kind': 'repair', 'tid': 'Z1', 'start': start,
                                                          'cwd': str(d), 'pid': 999999999, 'sid': 'x', 'until': 0}))
        R.adopt_merge(d)
        eq(git(repo, 'rev-parse', R.held('Z1', start)), made, 'what the repair made is kept')
        git(d, 'checkout', '-q', '--detach', start)
        check(R.kept('Z1', start, '', d, 'repair') and git(d, 'rev-parse', 'HEAD') == made,
              'and the rebuilt merge takes it instead of a second session')
        check(not R.kept('Z1', made, '', d, 'repair'), 'a different merge is not one it repaired')
        git(d, 'checkout', '-q', '--detach', start)
        git(d, 'checkout', '-q', '-b', 'z1-side')
        (d / 'z1-side.py').write_text('# side\n')
        git(d, 'add', 'z1-side.py'), git(d, 'commit', '-qm', 'side')
        side = git(d, 'rev-parse', 'HEAD')
        git(d, 'checkout', '-q', '--detach', start)
        git(d, 'merge', '-q', '--no-ff', '--no-edit', side)
        fix = {'kind': 'fix', 'tid': 'Z1', 'start': start, 'ref': side, 'cwd': str(d)}
        check(R.keep_made(fix, d), 'a fix session that committed the merge is kept')
        check(not R.keep_made({**fix, 'ref': made}, d), 'one that merged something else is not')
        git(d, 'checkout', '-q', '--detach', start)
        check(R.kept('Z1', start, side, d, 'fix') and git(d, 'rev-parse', 'HEAD^2') == side, 'and is reused')
    finally:
        R.C.run['test'] = test
        git(d, 'checkout', '-q', '--detach', 'main')
        git(repo, 'branch', '-D', 'z1-side')
        for h in git(repo, 'for-each-ref', '--format=%(refname)', R.HELD).split():
            git(repo, 'update-ref', '-d', h)
        R.C.notes('master.json').unlink(missing_ok=True)


def test_merge(repo: Path, tmp: Path):
    print('run: a finished branch is joined, tested, landed, pushed, and frees what it blocked')
    R.init(repo)
    git(R.SLOTS_DIR / 's1', 'checkout', '-q', '--detach')  # as cmd_run does when a session exits
    R.finish('T5', 1, 'sid', 'main')
    log = (repo / '.runner/ledger.md').read_text()
    has(log, r'T5: merged, ticked', 'the ledger says T5 merged')
    check(git(repo, 'branch', '--list', 'task/T5') == '', 'the local task branch is gone')
    eq(git(repo, 'rev-parse', 'main'), git(tmp / 'origin.git', 'rev-parse', 'main'),
       'main was pushed after the gate ([git] push_merge)')
    check('task/T5' not in remote_branches(tmp), 'and the remote task branch dropped once main has it')
    changelog = (repo / 'CHANGELOG.md').read_text()
    check('T1: the parser' in changelog and 'T5: the logger' in changelog, 'CHANGELOG.md kept both sides')
    done = (repo / 'plan/DONE.md').read_text()
    check('**T1**' in done and '**T5**' in done, 'DONE.md kept both ticks')
    todo = (repo / 'plan/TODO.md').read_text()
    check('**T5**' not in todo and '**T1**' not in todo, 'TODO.md has neither')
    has(todo, r'^- \[ \] \*\*T4\*\*.*reopened: T5 landed', 'T4\'s block reopened when T5 landed')
    has(git(repo, 'log', '-1', '--format=%s'), r'Plan: reopen T4 \(T5 landed', 'in a commit of its own')
    check('T4' in R.REOPENED, 'and the run may try it again')
    eq(git(repo, 'status', '--porcelain'), '', 'the main checkout is clean')


def test_merge_into(tmp: Path):
    print('run: a merge git rerere resolved by itself is committed; one git refuses is not a merge')
    d = tmp / 'rerere'
    d.mkdir()
    git(d, 'init', '-q', '-b', 'main')
    for k, v in (('user.name', 't'), ('user.email', 't@t'), ('rerere.enabled', 'true'), ('rerere.autoupdate', 'true')):
        git(d, 'config', k, v)
    (d / 'f').write_text('base\n')
    git(d, 'add', 'f'), git(d, 'commit', '-qm', 'base')
    git(d, 'checkout', '-qb', 'side'), (d / 'f').write_text('side\n'), git(d, 'commit', '-qam', 'side')
    git(d, 'checkout', '-q', 'main'), (d / 'f').write_text('main\n'), git(d, 'commit', '-qam', 'main')
    eq(R.merge_into(d, 'side', 'm'), ['f'], 'a first conflict lists its file')
    (d / 'f').write_text('both\n'), git(d, 'commit', '-qam', 'm')  # rerere records this resolution
    git(d, 'reset', '-q', '--hard', 'HEAD~1')
    eq(R.merge_into(d, 'side', 'm'), [], 'the same conflict again: rerere resolves it, and it is committed')
    eq((d / 'f').read_text(), 'both\n', 'with the recorded resolution')
    eq(git(d, 'rev-parse', 'HEAD^2'), git(d, 'rev-parse', 'side'), 'as a merge of the branch')
    git(d, 'reset', '-q', '--hard', 'HEAD~1')
    git(d, 'checkout', '-q', 'side'), (d / 'g').write_text('x\n'), git(d, 'add', 'g'), git(d, 'commit', '-qm', 'g')
    git(d, 'checkout', '-q', 'main'), (d / 'g').write_text('untracked\n')
    eq(R.merge_into(d, 'side', 'm'), None, 'git refusing (an untracked file in the way) is not a merge')


def test_retry(repo: Path):
    print('run: a tried task a human blocks and then unblocks is back in the pool')
    R.init(repo)
    tried, closed = {'T4'}, set()
    R.retry_reopened(tried, closed, 'main')
    check('T4' in tried, 'a tried task still open stays tried (it failed: a human looks next)')
    for step in (lambda: P.block('T4', 'needs a decision', todo=repo / 'plan/TODO.md'),
                 lambda: P.unblock('T4', 'decided', todo=repo / 'plan/TODO.md')):
        step()
        git(repo, 'commit', '-qam', 'Plan: T4')
        R.retry_reopened(tried, closed, 'main')
        if 'T4' in closed:
            check('T4' in tried, 'blocked, it is seen closed and stays tried')
    check('T4' not in tried and not closed, 'opened again, it leaves tried')
    has((repo / '.runner/run.log').read_text(), r'T4: open again since it was tried', 'and the log says so')

    print('run: a tried task whose line a human edits (a note) is back in the pool')
    tried = {'T4'}
    R.retry_reopened(tried, closed, 'main')
    R.retry_reopened(tried, closed, 'main')
    check('T4' in tried, 'unchanged, it stays tried')
    P.note('T4', 'use the other API this time', todo=repo / 'plan/TODO.md')
    git(repo, 'commit', '-qam', 'Plan: note T4')
    R.retry_reopened(tried, closed, 'main')
    check('T4' not in tried and 'T4' not in R.TRIED_TEXT, 'edited, it leaves tried')
    has((repo / '.runner/run.log').read_text(), r'T4: its line changed since it was tried', 'and the log says so')


def test_unmerged(repo: Path):
    print('run: a branch finished while no run was up is found, even in a slot still on it')
    R.init(repo)
    d = task_branch(repo, 4, 'T2')
    (d / 'b.py').write_text('# printer\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'T2: the printer')
    eq(R.unmerged('main', []), [], 'a branch a busy slot holds is not merged under its session')
    eq(R.unmerged('main', [4]), ['T2'], 'an idle slot still on its finished branch: found')
    eq(git(d, 'branch', '--show-current'), '', 'and that slot let go of the branch')
    git(repo, 'branch', '-D', 'task/T2')
    d = task_branch(repo, 4, 'T2')
    (d / 'b.py').write_text('# printer, again\n', encoding='utf-8')
    (d / 'new.py').write_text('# new\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'T2: the printer again')
    (d / 'c.py').write_text('# not committed yet\n', encoding='utf-8')
    eq(R.touched('T2', 'main', d) >= {'b.py', 'c.py', 'new.py'}, True,
       "a claim's touched files: the branch's commits, the slot's uncommitted and untracked edits")
    git(d, 'checkout', '-q', '--', '.')
    (d / 'new.py').unlink()
    saved = R.open_tasks, R.blocked_tasks
    R.open_tasks, R.blocked_tasks = (lambda b: saved[0](b) - {'T2'}), (lambda b: {'T2'})
    try:
        eq(R.unmerged('main', [4]), ['T2'], 'a task that ended blocked (a concept round) still has its branch merged')
    finally:
        R.open_tasks, R.blocked_tasks = saved
    git(repo, 'branch', '-D', 'task/T2')


def test_take(repo: Path):
    print('take: one chosen task in a person\'s own session, beside a run or without one')
    R.init(repo)
    add = run(repo, 'plan', 'add', 'T', 'take me: write z.py', '--files', 'z.py')
    tid = re.search(r'\b(T\d+)\b', add.stdout + add.stderr)[1]
    r = run(repo, 'take', tid)
    eq(r.returncode, 0, f'`take {tid}` hands it over: {r.stderr}')
    d = R.SLOTS_DIR / f'take-{tid}'
    has(r.stdout, rf'take {tid} --merge', 'and prints the prompt, ending with how to merge it')
    eq(git(d, 'branch', '--show-current'), f'task/{tid}', 'in a worktree of its own, on task/<ID>')
    check(tid in R.taken(), 'the worktree is the claim')
    why: dict = {}
    R.pick({}, set(), 'main', why=why)
    eq(why.get(tid), ('running', 'taken by hand (`take`)'), 'a run leaves it alone')
    check(run(repo, 'take', tid).returncode == 1, 'and it cannot be taken twice')
    (d / 'z.py').write_text('# z\n', encoding='utf-8')
    check(run(repo, 'take', tid, '--merge').returncode == 1, '--merge refuses while edits are uncommitted')
    eq(run(d, 'done', tid, f'{tid}: z.py').returncode, 0, '`done` in its worktree commits')
    r = run(repo, 'take', tid, '--merge')
    has(r.stdout, rf'{tid}: merged into main', f'with no run up, --merge merges it: {r.stdout}{r.stderr}')
    check(not d.exists() and tid not in R.open_tasks('main'), 'the worktree is gone and the task ticked')
    add = run(repo, 'plan', 'add', 'T', 'take me and give me back', '--files', 'y.py')
    tid = re.search(r'\b(T\d+)\b', add.stdout + add.stderr)[1]
    run(repo, 'take', tid)
    has(run(repo, 'take', tid, '--drop').stdout, 'given back', '--drop gives it back')
    check(tid not in R.taken() and not git(repo, 'branch', '--list', f'task/{tid}'), 'worktree and branch gone')
    d = task_branch(repo, 4, tid)
    (d / 'y.py').write_text('# y\n', encoding='utf-8')
    git(d, 'add', 'y.py'), git(d, 'commit', '-qm', f'{tid}: y.py'), git(d, 'checkout', '-q', '--detach')
    started, real = [], R.finish
    R.finish = lambda *a: started.append(a[0])
    try:
        R.SWEEP_AT[0] = 0.0
        merging: list = []
        R.sweep_unmerged('main', merging)
        [t.join() for t in merging]
        R.SWEEP_AT[0] = 0.0
        R.sweep_unmerged('main', merging)
        [t.join() for t in merging]
    finally:
        R.finish = real
    eq(started, [tid], 'a running run merges a branch finished outside its slots, once')
    git(repo, 'branch', '-D', f'task/{tid}')


def test_attach_flag(repo: Path):
    print('agent-runner --attach: the background run, started or found, then its pane in this terminal')
    import contextlib
    import io
    from agent_runner import cli
    R.init(repo)
    calls: list[str] = []
    bg = lambda argv: calls.append('start') or 0
    at = lambda argv: calls.append('attach') or 0
    which = R.shutil.which
    tmux_here = lambda c, *a, **k: '/usr/bin/tmux' if c == 'tmux' else which(c, *a, **k)
    no_tmux = lambda c, *a, **k: None if c == 'tmux' else which(c, *a, **k)
    with mock.patch.object(R, 'init'), mock.patch.object(R.plat, 'WINDOWS', False), \
            mock.patch.object(R, 'cmd_background', bg), mock.patch.object(R, 'cmd_attach', at), \
            mock.patch.object(cli, 'skill'), mock.patch.object(R.shutil, 'which', tmux_here):
        out = io.StringIO()
        with mock.patch.object(R.shutil, 'which', no_tmux), contextlib.redirect_stdout(out):
            eq(cli.main(['--attach']), 0, 'F40: --attach without tmux')
        eq(calls, ['start'], 'without tmux: it starts the run hidden, as bare does, no attach')
        has(out.getvalue(), r'without tmux', 'and says so')
        calls.clear()
        with mock.patch.object(R, 'run_up', lambda: False):
            eq(cli.main(['--attach']), 0, '--attach with no run up')
        eq(calls, ['start', 'attach'], 'no run up: it starts the run, then attaches')
        calls.clear()
        with mock.patch.object(R, 'run_up', lambda: True):
            eq(cli.main(['--attach']), 0, '--attach with a run up')
        eq(calls, ['attach'], 'a run up: it only attaches')
        calls.clear()
        with mock.patch.object(R, 'run_up', lambda: False), mock.patch.object(R, 'cmd_background', lambda a: 1):
            eq(cli.main(['--attach']), 1, 'a run that does not come up fails --attach')
        eq(calls, [], 'and nothing is attached')
        out = io.StringIO()
        with mock.patch.object(R.plat, 'WINDOWS', True), contextlib.redirect_stdout(out):
            eq(cli.main(['--attach']), 0, 'Windows: --attach')
        eq(calls, ['start'], 'Windows: it starts the run as bare does, no attach')
        has(out.getvalue(), r'on Windows', 'and says so')
        calls.clear()
        with contextlib.redirect_stderr(io.StringIO()):
            eq(cli.main(['--attach', 'x']), 2, '--attach takes no more arguments')
        eq(calls, [], 'a bad --attach starts nothing')
    out = io.StringIO()
    with mock.patch.object(cli, 'skill'), contextlib.redirect_stdout(out):
        cli.main(['--help'])
    has(out.getvalue(), r'agent-runner --attach ', '--help lists --attach')


def test_bare_outside_git(tmp: Path):
    print('bare agent-runner outside git: a runner folder becomes a repo; elsewhere git says why, not the usage')
    import contextlib
    import io
    from agent_runner import cli
    plain, proj = tmp / 'bare-plain', tmp / 'bare-proj'
    plain.mkdir(), (proj / 'plan').mkdir(parents=True)
    (proj / 'runner.toml').write_text('', encoding='utf-8')
    (proj / 'plan' / 'TODO.md').write_text('# hi\n', encoding='utf-8')
    started: list = []
    env = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER_REPO'}
    env |= {'GIT_CEILING_DIRECTORIES': str(tmp), 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t',
            'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'}
    cwd = Path.cwd()
    with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(cli, 'skill'), \
            mock.patch.object(R, 'cmd_background', lambda a: started.append(1) or 0):
        try:
            os.chdir(plain)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                eq(cli.main([]), 2, 'no repo, no runner files: it fails')
            has(err.getvalue(), r'not a git repository', "and passes on git's reason")
            check('What you type' not in err.getvalue(), 'not the whole usage')
            check(not (plain / '.git').exists() and not started, 'a plain folder is left alone')
            os.chdir(proj)
            with contextlib.redirect_stderr(io.StringIO()):
                eq(cli.main([]), 0, 'a runner folder with no git')
            eq(started, [1], 'it starts the run')
            has(git(proj, 'log', '--format=%s'), r'Start', 'after making it a repo with its files committed')
        finally:
            os.chdir(cwd)


def test_short_name_hints():
    print('C15: on Windows the hints a person reads say agent-runner when it is on PATH; prompts keep the full path')
    from agent_runner import config
    exe = 'C:/Users/me/AppData/Roaming/Python/Scripts/agent-runner.EXE'
    with mock.patch.object(R.plat, 'WINDOWS', True), mock.patch.object(config, 'RUNNER', exe), \
            mock.patch.object(R, 'RUNNER', exe), mock.patch.object(R, 'control_ok', lambda: True), \
            mock.patch.object(R, 'remote_on', lambda: False), mock.patch.object(R, 'remote_slots_on', lambda: False), \
            mock.patch.dict(R.C.run, {'control': True}):
        with mock.patch.object(config.shutil, 'which', lambda c, *a, **k: exe if c == 'agent-runner' else None):
            note = R.started_note(2, 'its slots hidden', hidden=True)
            check('    agent-runner status' in note and '    agent-runner control' in note and exe not in note,
                  'on PATH: the start hints say agent-runner', note)
            check(f'{exe} status' in R.control_brief(), "a control session's brief keeps the full path")
        with mock.patch.object(config.shutil, 'which', lambda *a, **k: None):
            check(f'    {exe} status' in R.started_note(2, 'here'), 'not on PATH: the full path, which works')
    with mock.patch.object(R.plat, 'WINDOWS', False), mock.patch.object(config, 'RUNNER', '/x/run'):
        eq(config.shown_cmd(), '/x/run', 'elsewhere: RUNNER as it was')


def test_utf8_streams():
    print('B67: on Windows main writes UTF-8 to stdout and stderr, so a pipe (ssh, a Bash tool) reads it right')
    import contextlib
    import io
    from agent_runner import cli

    class Stream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.calls: list[dict] = []

        def reconfigure(self, **kw):
            self.calls.append(kw)

    for windows, want in ((True, [{'encoding': 'utf-8', 'errors': 'replace'}]), (False, [])):
        out, err = Stream(), Stream()
        with mock.patch.object(R.plat, 'WINDOWS', windows), mock.patch.object(cli, 'skill'), \
                mock.patch.object(cli, 'user_hook'), mock.patch.object(sys, 'stdout', out), \
                mock.patch.object(sys, 'stderr', err):
            cli.main(['--version'])
        eq(out.calls, want, f'WINDOWS={windows}: stdout reconfigured' if windows else 'elsewhere: stdout left as it is')
        eq(err.calls, want, f'WINDOWS={windows}: stderr reconfigured' if windows else 'elsewhere: stderr left as it is')
    with mock.patch.object(R.plat, 'WINDOWS', True), mock.patch.object(cli, 'skill'), \
            mock.patch.object(cli, 'user_hook'), contextlib.redirect_stdout(io.StringIO()) as plain:
        cli.main(['--version'])
    has(plain.getvalue(), r'agent-runner ', 'a stream with no reconfigure (a StringIO) is left alone')


def test_background(repo: Path):
    print('bare agent-runner: the run in a detached tmux session, or hidden consoles on Windows; attach')
    R.init(repo)
    eq(R.background_session(), 'ar-proj', 'the session is named for the repo')
    argv = R.tmux_launch_argv('ar-proj', 'runner-proj', repo, 'py -m agent_runner run', ['PATH=/bin'], exists=False)
    eq(argv[:4], ['tmux', 'new-session', '-d', '-s'], 'a new detached session (it never takes this terminal)')
    eq(argv[4:12], ['ar-proj', '-n', 'runner-proj', '-c', str(repo), '-e', 'PATH=/bin', 'py -m agent_runner run'],
       'named, in the main checkout, with this shell\'s PATH, running `run`')
    eq(argv[12:], [';', 'set-option', '-w', '-t', '=ar-proj:runner-proj', 'remain-on-exit', 'on'],
       'its window outlives a run that fails at once, to show why')
    argv = R.tmux_launch_argv('ar-proj', 'runner-proj', repo, 'x', [], exists=True)
    eq(argv[1:5], ['new-window', '-d', '-t', '=ar-proj:'], 'a session already there gets a new window instead')
    eq(R.background_argv()[-2:], ['run', '--hidden'], 'Windows or no tmux: the run, its slots hidden')
    has('\n'.join(R.background_env()), r'^PATH=', 'the tmux session gets this PATH')
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1', 'CLAUDE_CODE_SESSION_ID': 's1',
                                      'CLAUDE_CODE_MESSAGING_TOKEN': 't', 'CLAUDE_CONFIG_DIR': '/c'}):
        os.environ.pop('TMUX', None)
        R.drop_session_env()
        spawn = '\n'.join(R.background_env())
        check('CLAUDE_CODE_CHILD_SESSION' not in spawn and 'CLAUDE_CODE_SESSION_ID' not in spawn
              and 'CLAUDE_CODE_MESSAGING' not in spawn and 'CLAUDE_CONFIG_DIR=/c' in spawn,
              "the run's tmux session gets no Claude session markers from a parent that had them, keeps config")

    from agent_runner import plat
    si = plat.hidden_startupinfo()
    eq((si.dwFlags & plat.STARTF_USESHOWWINDOW, si.wShowWindow), (1, 0), 'STARTUPINFO: wShowWindow = SW_HIDE')
    with mock.patch.object(plat.sp, 'Popen') as popen:
        plat.spawn_console(['a'], repo, {}, hidden=True)
        kw = popen.call_args.kwargs
        check(kw['creationflags'] & plat.CREATE_NEW_CONSOLE, 'a hidden slot still gets a console of its own (a TTY)')
        eq(kw['startupinfo'].wShowWindow, plat.SW_HIDE, 'its window starts hidden')
        plat.spawn_console(['a'], repo, {})
        check('startupinfo' not in popen.call_args.kwargs, 'a console window otherwise shows, as before')
    with mock.patch.object(plat.sp, 'Popen') as popen, mock.patch.object(plat, 'WINDOWS', True):
        plat.spawn_detached(['a'])
        f = popen.call_args.kwargs['creationflags']
        check(f & plat.CREATE_NO_WINDOW and not f & 0x8, 'Windows: a detached process gets a windowless console, '
              "not DETACHED_PROCESS (uv's python launcher would then open a visible one)")

    rows = ['other\t%1\ts1\t/elsewhere\t', 'ar-proj\t%2\t\t\t' + str(repo), 'ar-proj\t%3\ts1\t' + str(repo) + '\t',
            'ar-proj\t%4\ts2\t' + str(repo) + '\t']
    eq(R.attach_target(rows, repo, 'runner'), ('ar-proj', '%2'), "attach: the runner's own pane")
    eq(R.attach_target(rows, repo, 's1'), ('ar-proj', '%3'), "attach s1: this repo's s1, not another repo's")
    eq(R.attach_target(rows, repo, 's9'), None, 'no such slot')
    eq(R.attach_argv('ar-proj', '%3', inside=False)[-1], ['tmux', 'attach-session', '-t', 'ar-proj'],
       'outside tmux it attaches this terminal')
    eq(R.attach_argv('ar-proj', '%3', inside=True)[-1], ['tmux', 'switch-client', '-t', 'ar-proj'],
       'inside tmux it switches the client')

    for line, want in (('up with three slots, worded any way', 3), ('up one session at a time', 0)):
        log = R.events_file()
        since = log.stat().st_size if log.exists() else 0
        R.log(line, R.EV_RUN_UP, slots=want)
        eq(R.wait_started(since, lambda: False, timeout=2), want, f'the launch sees the run come up ({want} slots)')
    since = R.events_file().stat().st_size
    R.log('run: 3 slots in tmux, merging into main')  # F41: the prose alone, with no event, is not the start
    eq(R.wait_started(since, lambda: True, timeout=2), None, 'or that it ended first')

    R.C.run['remote'] = True
    try:
        f = R.claude_json()
        f.write_text('{"x": 1}', encoding='utf-8')
        eq(R.remote_ready(tty=False), False, 'remote, never answered, no terminal: nothing starts')
        eq(R.remote_ready(tty=True, ask=lambda q: 'n'), False, 'answered no here: nothing starts')
        eq(R.remote_ready(tty=True, ask=lambda q: 'y'), True, 'answered yes here: it starts')
        eq(json.loads(f.read_text(encoding='utf-8')), {'x': 1, 'remoteDialogSeen': True},
           'and Claude Code will not ask in the hidden panes')
        eq(R.remote_ready(tty=False, ask=lambda q: 1 / 0), True, 'asked once only')
    finally:
        R.C.run['remote'] = False


def test_remote_auto(tmp: Path):
    """[run] remote = 'auto' (the default): on for a Claude Code session on a claude.ai login, off with a reason
    otherwise; true/false force it; the config takes nothing else. And the quiet launch's presence files."""
    from agent_runner import config
    d = tmp / 'remote-auto'
    d.mkdir()
    repo = make_repo(d)
    for v, ok in (('"auto"', True), ('true', True), ('false', True), ('"yes"', False), ('1', False), ('"on"', False)):
        (repo / 'runner.toml').write_text(f'[run]\nremote = {v}\n', encoding='utf-8')
        try:
            got = config.Config(repo).run['remote']
        except SystemExit as e:
            check(not ok and 'remote' in str(e), f'[run] remote = {v} is refused', str(e))
        else:
            check(ok, f'[run] remote = {v} is accepted ({got!r})')
    (repo / 'runner.toml').write_text('[run]\n', encoding='utf-8')
    eq(config.Config(repo).run['remote'], 'auto', "remote defaults to 'auto'")

    rc = tmp / 'remote-auto-claude'
    rc.mkdir()
    base = {k: v for k, v in os.environ.items()
            if not k.startswith('ANTHROPIC_') and k not in R.REMOTE_ENV_FLAGS} | {'CLAUDE_CONFIG_DIR': str(rc)}
    seen = rc / '.claude.json'
    seen.write_text('{"remoteDialogSeen": true}', encoding='utf-8')
    off = {'ANTHROPIC_API_KEY': 'sk-x', 'ANTHROPIC_AUTH_TOKEN': 't', 'CLAUDE_CODE_USE_BEDROCK': '1',
           'CLAUDE_CODE_USE_VERTEX': '1', 'CLAUDE_CODE_USE_FOUNDRY': 'true',
           'ANTHROPIC_BASE_URL': 'https://llm.example.com/v1'}
    with mock.patch.dict(R.C.run, {'remote': 'auto', 'remote_slots': False}):
        with mock.patch.dict(os.environ, base, clear=True):
            check(R.remote_on() and R.remote_off_why() == '', 'auto, a claude.ai login: on')
            check('--remote-control' in R.control_argv(2, 'sid-r', resume=False), 'so control sessions are on it')
            has(R.remote_line(), r'^remote control on: the control sessions show', 'and the log says so')
            eq(R.remote_flags('slot2', None), [], 'auto leaves the slots local (remote_slots is false)')
        for k, v in off.items():
            with mock.patch.dict(os.environ, base | {k: v}, clear=True):
                check(not R.remote_on() and k in R.remote_off_why(), f'auto, {k} set: off, and it says why')
                has(R.remote_line(), rf'^remote control off: {k}', f'one log line for {k}')
                check('--remote-control' not in R.control_argv(2, 'sid-r', resume=False), f'{k}: control is local')
        for v in ('https://api.anthropic.com', 'https://api.anthropic.com/'):
            with mock.patch.dict(os.environ, base | {'ANTHROPIC_BASE_URL': v}, clear=True):
                check(R.remote_on(), f'auto, ANTHROPIC_BASE_URL={v}: on')
        with mock.patch.dict(os.environ, base | {'CLAUDE_CODE_USE_BEDROCK': '0'}, clear=True):
            check(R.remote_on(), 'auto, CLAUDE_CODE_USE_BEDROCK=0: on')
        with mock.patch.dict(os.environ, base, clear=True):
            with mock.patch.object(R, 'pi', lambda: True):
                check(not R.remote_on() and R.remote_off_why().startswith('backend pi'), 'auto, backend pi: off')
            seen.write_text('{}', encoding='utf-8')
            check(not R.remote_on() and 'remote-control' in R.remote_off_why(),
                  'auto, Remote Control never allowed in Claude Code: off')
            eq(R.remote_ready(tty=False, ask=lambda q: 1 / 0), True, 'auto, no terminal to ask on: the run starts')
            eq(R.remote_ready(tty=True, ask=lambda q: 'n'), True, 'auto, answered no: the run starts, remote off')
            eq(json.loads(seen.read_text(encoding='utf-8')), {}, 'and nothing is kept')
            eq(R.remote_ready(tty=True, ask=lambda q: 'y'), True, 'auto, answered yes')
            check(R.remote_on(), 'then on')
        with mock.patch.dict(os.environ, base | {'ANTHROPIC_API_KEY': 'sk-x'}, clear=True):
            eq(R.remote_ready(tty=True, ask=lambda q: 1 / 0), True, 'auto, off for another reason: nothing asked')
    with mock.patch.dict(os.environ, base | {'ANTHROPIC_API_KEY': 'sk-x'}, clear=True):
        with mock.patch.dict(R.C.run, {'remote': True}):
            check(R.remote_on(), 'true forces it on')
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.dict(R.C.run, {'remote': False}):
            check(not R.remote_on(), 'false keeps it off')
            eq(R.remote_line(), '', 'and logs nothing')

    # the quiet launch: slots keep their presence file, so they never push; notifications off in their settings
    with mock.patch.dict(R.C.run, {'remote_slots': True}):
        env = R.env_vars(R.slot_env(2))
        flags = R.agent_flags('sid-q', 'opus', 30)
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_TMPDIR': ''}):
        eq(R.env_vars(R.slot_env(2))['CLAUDE_CODE_TMPDIR'], str(R.C.home / 'tmp'),
           "a slot's Claude Code temp folder is on disk under the run home, not /tmp's tmpfs")
    f = Path(env[R.PRESENCE_ENV])
    check(f.exists() and f.name == 'quiet-slots', 'a slot on Remote Control names a presence file that exists')
    s = json.loads(flags[flags.index('--settings') + 1])
    eq(s['agentPushNotifEnabled'], False, 'and its PushNotification tool is off')
    check('inputNeededNotifEnabled' not in s, 'no inputNeededNotifEnabled: from --settings it never reaches the server')
    with mock.patch.dict(R.C.run, {'remote_slots': False}):
        check(R.PRESENCE_ENV not in R.env_vars(R.slot_env(2)), 'a local slot has none')
        check('agentPushNotifEnabled' not in R.agent_flags('sid-q', 'opus', 30)[-1], 'nor the settings')
    with mock.patch.dict(R.C.run, {'remote_slots': True, 'silent': False}):
        check(R.PRESENCE_ENV not in R.env_vars(R.slot_env(2)), 'silent = false: a remote slot has no presence file')
        check('agentPushNotifEnabled' not in R.agent_flags('sid-q', 'opus', 30)[-1], 'nor the push settings')
    # a control session's (and the server's) file goes once its link shows
    log_f = R.C.notes('quiet-test.log')
    log_f.write_text('old https://claude.ai/code line\n', encoding='utf-8')
    q = R.quiet_file('test')
    t = threading.Thread(target=R.unquiet_when_up, args=('test',),
                         kwargs={'log_file': log_f, 'since': log_f.stat().st_size, 'wait': 20})
    t.start()
    time.sleep(1.5)
    check(q.exists(), 'quiet while the session starts (an old link in the log does not count)')
    with open(log_f, 'a', encoding='utf-8') as fh:
        fh.write(f'up: {R.REMOTE_URL}/session_abc\n')
    t.join(10)
    check(not q.exists() and not t.is_alive(), 'and loud again once its link shows')


def test_control_server_old_agent(repo: Path, tmp: Path):
    print('control server: an older Claude Code without remote-control --settings starts without it, and says so')
    R.init(repo)
    old, new = tmp / 'old-claude', tmp / 'new-claude'
    old.write_text("#!/bin/sh\necho 'Usage: claude remote-control [options]'\necho '  --name <name>'\n"
                   "echo '  --spawn <mode>'\n", encoding='utf-8')
    new.write_text("#!/bin/sh\necho 'Usage: claude remote-control [options]'\necho '  --settings <file>'\n",
                   encoding='utf-8')
    for f in (old, new):
        f.chmod(0o755)
    R._SERVER_SETTINGS.clear()
    with mock.patch.dict(R.C.run, {'agent': str(new)}):
        check('--settings' in R.control_server_argv(), 'one whose help lists --settings gets the control settings')
    said, started = [], []

    real_popen = R.sp.Popen

    def popen(argv, *a, **k):
        if 'remote-control' not in argv or '--help' in argv:
            return real_popen(argv, *a, **k)  # git, and the --help probe
        started.append(argv)
        raise OSError('stop here')
    with mock.patch.dict(R.C.run, {'agent': str(old)}), mock.patch.object(R, 'log', said.append), \
            mock.patch.object(R, 'backend') as be, mock.patch.object(R, 'control_server_live', lambda: 0), \
            mock.patch.object(R.sp, 'Popen', popen), mock.patch('atexit.register'):
        be.return_value.trust = lambda root: None
        R.keep_control_server()
        R.control_server_argv()
    check(started and '--settings' not in started[0] and 'remote-control' in started[0],
          'the server starts without --settings', started)
    check(any('no --settings' in s and 'claude.ai/code' in s and 'control brief' in s and 'Update Claude Code' in s
              for s in said), 'one run.log line says sessions from claude.ai/code miss the brief, and to update', said)
    err = tmp / 'server.err'
    err.write_text('old noise\n', encoding='utf-8')
    since = err.stat().st_size
    eq(R.server_last_error(err, since), '', 'nothing new on stderr: no line')
    with open(err, 'a', encoding='utf-8') as fh:
        fh.write("\x1b[31merror: unknown option '--settings'\x1b[0m\n\n")
    eq(R.server_last_error(err, since), "error: unknown option '--settings'", 'its last stderr line since it started')
    R._SERVER_SETTINGS.clear()


def test_hand_hook(tmp: Path):
    print('F53: a session opened by hand in the main checkout gets the control brief; a runner-started one once')
    import contextlib
    import io
    root = tmp / 'hand'
    (root / '.claude').mkdir(parents=True)
    f = root / '.claude' / 'settings.local.json'
    f.write_text(json.dumps({'permissions': {'allow': ['Bash(ls)']}}), encoding='utf-8')
    has(R.hand_hook(root), r'settings\.local\.json', 'the hook goes into settings.local.json')
    eq(R.hand_hook(root), '', 'once')
    data = json.loads(f.read_text(encoding='utf-8'))
    eq(data['permissions'], {'allow': ['Bash(ls)']}, "the person's own settings stay")
    hooks = [h['command'] for e in data['hooks']['SessionStart'] for h in e['hooks']]
    check(len(hooks) == 1 and hooks[0].endswith('control --brief --hand'), 'one SessionStart hook', hooks)
    eq(R.control_env().get(R.RUNNER_STARTED_ENV), '1', 'runner-started control sessions are marked')
    base = {k: v for k, v in os.environ.items() if k != R.RUNNER_STARTED_ENV}
    for env, want in (({**base, R.RUNNER_STARTED_ENV: '1'}, False), (base, True)):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(R, 'init'), \
                mock.patch.object(R, 'control_brief', lambda: 'BRIEF'), contextlib.redirect_stdout(out):
            R.cmd_control(['--brief', '--hand'])
        eq('BRIEF' in out.getvalue(), want, '--hand prints the brief' + (' (by hand)' if want else
                                                                         ' only when the runner did not start it'))
    print('B66: hand_hook ignores settings.local.json where git has no rule for it, in every worktree')
    rel = '.claude/settings.local.json'
    gl = tmp / 'hand-noglobal'
    gl.mkdir()
    (gl / 'gitconfig').write_text('[user]\n\tname = t\n\temail = t@t\n', encoding='utf-8')
    genv = {'GIT_CONFIG_GLOBAL': str(gl / 'gitconfig'), 'XDG_CONFIG_HOME': str(gl), 'HOME': str(gl)}
    with mock.patch.dict(os.environ, genv):
        repo = tmp / 'hand-repo'
        repo.mkdir()
        R.git('init', '-q', cwd=repo)
        R.git('commit', '-q', '--allow-empty', '-m', 'init', cwd=repo)
        eq(R.git('check-ignore', '-q', rel, cwd=repo).returncode, 1, 'no ignore rule to start with')
        has(R.hand_hook(repo), r'settings\.local\.json', 'the hook is written in a repo with no ignore rule')
        eq(R.git('check-ignore', '-q', rel, cwd=repo).returncode, 0, 'and git check-ignore passes after it')
        eq(R.git('status', '--porcelain', cwd=repo).stdout, '', 'git status no longer shows ?? .claude/')
        wt = tmp / 'hand-wt'
        R.git('worktree', 'add', '-q', str(wt), cwd=repo)
        eq(R.git('check-ignore', '-q', rel, cwd=wt).returncode, 0, 'a worktree shares the exclude (common dir)')
        R.hand_hook(repo)
        R.hand_hook_exclude(wt)
        ex = (repo / '.git' / 'info' / 'exclude').read_text(encoding='utf-8')
        check(ex.count(rel) == 1, 'added once', ex)


def test_user_hook(tmp: Path):
    print('B79: a user-level SessionStart hook gives the control brief in a runner repo no run has started in')
    from agent_runner import config as CF
    home = tmp / 'uh-claude'
    home.mkdir()
    f = home / 'settings.json'
    f.write_text(json.dumps({'model': 'x', 'hooks': {'SessionStart': [{'hooks': [{'type': 'command',
                                                                                    'command': 'mine'}]}]}}))
    with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(home)}), \
            mock.patch.object(CF, 'HERE', tmp / 'uh-installed' / 'agent_runner'):
        has(CF.install_user_hook(), r'settings\.json', 'merged into the user settings')
        eq(CF.install_user_hook(), '', 'once')
        data = json.loads(f.read_text())
        cmds = [h['command'] for e in data['hooks']['SessionStart'] for h in e['hooks']]
        check(data['model'] == 'x' and cmds[0] == 'mine' and len(cmds) == 2 and CF.USER_HOOK in cmds[1],
              "the person's own settings and hooks stay, ours is added", cmds)
        gone = f'/nonexistent/python3 /nonexistent/run {CF.USER_HOOK} 2>/dev/null || true'
        data['hooks']['SessionStart'][1]['hooks'][0]['command'] = gone
        f.write_text(json.dumps(data))
        has(CF.install_user_hook(), r'settings\.json', 'a hook naming a clone that is gone is repaired')
        cmds = [h['command'] for e in json.loads(f.read_text())['hooks']['SessionStart'] for h in e['hooks']]
        check(cmds[1] == CF.user_hook_command() and len(cmds) == 2, 'in place, still one', cmds)
        bad = home / 'settings.json'
        bad.write_text('{not json')
        eq(CF.install_user_hook(), '', 'a settings file that is not JSON is left alone')
        eq(bad.read_text(), '{not json', 'untouched')
    with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(home)}), \
            mock.patch.object(CF, 'HERE', tmp / 'uh-wt' / 'agent_runner'):
        (tmp / 'uh-wt').mkdir()
        (tmp / 'uh-wt' / '.git').write_text('gitdir: x\n')
        f.unlink()
        eq(CF.install_user_hook(), '', 'never from a clone that is a worktree (a slot of the runner itself)')
    repo = tmp / 'uh-repo'
    repo.mkdir()
    R.git('init', '-q', cwd=repo)
    (repo / 'runner.toml').write_text('[run]\nslots = 1\n')
    R.git('add', '-A', cwd=repo)
    R.git('commit', '-q', '-m', 'init', cwd=repo)
    wt = tmp / 'uh-slot'
    R.git('worktree', 'add', '-q', str(wt), cwd=repo)
    plain = tmp / 'uh-plain'
    plain.mkdir()
    R.git('init', '-q', cwd=plain)
    env = {k: v for k, v in os.environ.items() if k not in CF.SESSION_ENVS}
    (repo / 'sub').mkdir()
    for where, want in ((repo, True), (repo / 'sub', True), (wt, False), (plain, False), (tmp, False)):
        r = subprocess.run(CF.user_hook_command(), shell=True, cwd=where, env=env, capture_output=True, text=True,
                   timeout=60)
        eq((r.returncode, bool(r.stdout.strip()), r.stderr), (0, want, ''),
           f'{where.name}: ' + ('the brief' if want else 'nothing, exit 0, no stderr'))
        if want:
            has(r.stdout, 'control session', 'it is the control brief')
    r = subprocess.run(CF.user_hook_command(), shell=True, cwd=repo, env={**env, R.RUNNER_STARTED_ENV: '1'},
               capture_output=True, text=True, timeout=60)
    eq(r.stdout, '', 'nothing in a control session the runner started (its brief comes through --settings)')
    eq(CF.user_hook_root(repo, {'AGENT_RUNNER_SLOT': '2'}), None, "nothing in a slot's session")
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'settings.local.json').write_text('{"x": "control --brief --hand"}')
    eq(CF.user_hook_root(repo, {}), None, "nothing where the repo's own hook (F53) prints it: never twice")


def test_pane_id_not_a_path(repo: Path, tmp: Path):
    print('B52: a git that answers with a tmux pane id gives no directory: nothing is made from it')
    from agent_runner import config as CF
    real = subprocess.run
    pane = lambda argv, *a, **k: subprocess.CompletedProcess(argv, 0, '%9\n', '')  # noqa: E731
    with mock.patch.object(subprocess, 'run', pane):
        try:
            CF.toplevel(tmp)
            check(False, 'toplevel took "%9" for a checkout')
        except SystemExit as e:
            has(str(e), 'printed no directory', 'toplevel: "%9" is no checkout')
    eq(CF.git_path(f'{repo}\n'), repo, 'an absolute directory is one')
    eq([CF.git_path(s) for s in ('%9\n', '', 'rel/dir', str(tmp / 'missing'))], [None] * 4,
       'a pane id, nothing, a relative or missing path are not')

    def common_pane(argv, *a, **k):
        if '--git-common-dir' in argv:
            return subprocess.CompletedProcess(argv, 0, '%9\n', '')
        return real(argv, *a, **k)
    with mock.patch.object(subprocess, 'run', common_pane):
        eq(CF.main_checkout(repo), repo.resolve(), 'main_checkout: a bad --git-common-dir answer falls back to the checkout')
    check(not (tmp / '%9').exists() and not Path('%9').exists(), 'and no %9 folder anywhere')


def tmux_run(calls: list, out: str = '%9\n'):
    """A stand-in for subprocess.run that answers the tmux commands with `out` (a pane id) and leaves every
    other command (git, finding the repo for run.log) to the real one. B52: answering git with "%9" too made
    log() write a %9/.runner/run.log folder in the current directory."""
    real = subprocess.run

    def fake(argv, *a, **k):
        if argv[:1] != ['tmux']:
            return real(argv, *a, **k)
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, out, '')
    return fake


def test_control(repo: Path):
    with mock.patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1', 'CLAUDECODE': '1', 'CLAUDE_CONFIG_DIR': '/c',
                                      'TMUX': '/tmp/t,1,0'}):
        with mock.patch.object(R, 'run', return_value=0), mock.patch.object(R, 'tmux') as tm:
            R.cmd_run([])
        check(mock.call('set-environment', '-r', 'CLAUDE_CODE_CHILD_SESSION') in tm.call_args_list,
              'and out of its tmux session, whose new windows (the slots) would inherit them')
        check(['set-environment', '-t', '=ar-x', '-r', 'CLAUDE_CODE_SESSION_ID'] in R.session_env_masks('ar-x'),
              "masked with -r, which hides a value the tmux server's global env still holds; -u would not")
        check('CLAUDE_CODE_CHILD_SESSION' not in os.environ and 'CLAUDECODE' not in os.environ
              and os.environ.get('CLAUDE_CONFIG_DIR') == '/c',
              "a run started from a Claude session drops its markers (no slot transcripts otherwise), keeps config")
    said = []
    with mock.patch.object(R, 'run', side_effect=RuntimeError('boom')), mock.patch.object(R, 'log', said.append):
        try:
            R.cmd_run([])
            check(False, 'a crash is raised again')
        except RuntimeError:
            pass
    check(said and said[0].startswith('run crashed:') and 'RuntimeError: boom' in said[0],
          'a crashed run writes its traceback to run.log (its window closes with it)', said)
    print('control sessions: the settings file and its brief, the argv, c1 kept, tmux default-command, status')
    R.init(repo)
    data = R.control_settings_data()
    hook = data['hooks']['SessionStart'][0]['hooks'][0]
    check(hook['type'] == 'command' and hook['command'].endswith('control --brief'),
          'a SessionStart hook prints the control brief', hook)
    check('Stop' not in data['hooks'], 'no Stop hook: a control session is never ended on idle')
    check(data['skipDangerousModePermissionPrompt'], 'no bypass dialog: nobody may be at the terminal to answer it')
    f = R.control_settings()
    eq(f, repo / '.runner' / 'control-settings.json', 'the file is <notes>/control-settings.json')
    eq(json.loads(f.read_text(encoding='utf-8')), data, 'and holds that')
    brief = R.control_brief()
    for want in ('control session', f'{R.C.command} status', f'{R.C.command} plan add', f'{R.C.command} take',
                 'Never edit code', f'{R.C.command} since', f'{R.C.command} since --follow', 'Open the session',
                 '/run · /since · /follow · /control · /pause · /stop · /slots', 'Start it only when asked',
                 f'{R.C.command} control --new', '"/new"', "Artifact tool's `open` action", '**Needs you**',
                 '**Running**', '**Landed**', '**Stuck**', "status's `lately`", 'More: /since · /run -n 20',
                 f'{R.C.command} status -n 20'):
        check(want in brief, f'the brief says {want!r}')
    check(brief.index('**Needs you**') < brief.index('**Running**') < brief.index('**Landed**')
          < brief.index('**Stuck**'), 'the groups in order: Needs you, Running, Landed, Stuck')
    check('Waiting for your OK' not in brief, 'B27: the old heading is gone from the brief')
    from agent_runner.guide import topic
    needs_page = topic('needs', R.C.command)
    check('never a\n   CONCEPT/CONFIRM/DECIDE/BLOCKED label' in brief and 'never show the person those labels' in needs_page
          and 'reply yes/no' in needs_page, 'B27: each item worded plainly, without the caps labels (C2: details in guide needs)', brief)
    check('plan answer' not in brief and f'{R.C.command} plan confirm|change|shelve ID' in brief
          and 'ask the person, naming the items' in brief,
          'C5: a reply naming no item is mapped to its id by the session, which asks when it cannot tell')
    with mock.patch.object(P, 'needs_cfg', lambda: {'heading': 'For you', 'ages': True, 'order': 'oldest'}):
        b2 = R.control_brief()
    check('**For you**' in b2, 'B27: [needs] heading names the group', b2[:200])
    check('status · since · follow' not in brief, 'the hints line is slash commands, not bare words')
    check('--after T181' in brief and f'{R.C.command} plan block ID --after' in brief,
          '"do X after T181" queues X with --after (block --after for a queued task)')
    for want in ('plan add <KIND> "..." --pri later', '`--pri low`', 'plan move ID top', 'plan drop ID',
                 'stop --suspend', 'stop --shutdown', 'resume ID', 'plan claims', 'plan unclaim ID',
                 'plan add ID', 'subtasks wait for their parent', 'cost`'):
        check(f'{R.C.command} {want}' in brief or want in brief, f'the brief maps a request to {want!r}')
    for want in ('plan move ID top', 'plan drop ID', 'stop --suspend', 'stop --shutdown', 'resume ID',
                 'plan claims', 'plan unclaim ID', 'plan add ID', 'cost'):
        check(f'{R.C.command} {want}' in brief, f'the brief runs `{R.C.command} {want}`')
    check('starts it once those merge, so the only watch you start is to tell the person' in ' '.join(brief.split()),
          'the brief keeps a watcher or Monitor to the person\'s "notify me", never to wait for a task')
    # C2: the concept rules are in `guide concepts`; the brief names its triggers and points there
    concepts = topic('concepts', R.C.command)
    check('"concept X", "sketch some options for X"' in brief and f'`{R.C.command} guide concepts`' in brief
          and 'queue a K task only when they\n  say queue it' in brief, 'C2: the brief points concept asks at guide concepts')
    check('show it in this session, now' in concepts and 'queue no K task' in concepts
          and "call\nits `open` action so it shows inline" in concepts,
          '"concept X" builds the options page in the control session and opens it inline, no K task')
    check(f'{R.C.command} plan add K "..."' in concepts and 'only when they say queue it, later, or add a task' in concepts,
          'a K task is queued only when the person asks to queue it')
    check('"sketch some options for X" queues one' not in brief + concepts, 'the brief no longer queues a K for "sketch options"')
    check('"show me a concept first"' in concepts and 'no `take`' in concepts and 'plan drop ID "shown inline"' in concepts,
          '"show me concept first" is shown inline too, never a K task or a take (B23)')
    check('even when the project has its own concept-task or concept-branch convention' in ' '.join(concepts.split())
          and "don't search the plan, DONE or the guide for precedent" in concepts,
          'B76: a project\'s own concept-task convention does not turn "concept X" into a queued task')
    check('"here and now"' in concepts and 'with no question, even when a slot already took it' in concepts
          and 'the drop stops that slot\'s session' in concepts,
          'B76: "here and now" after a queued concept drops it (stopping its slot) and shows it, no question')
    check('tail -n 0 -F' not in brief, 'no run-log watch at the start: following is asked for')
    r = run(repo, 'control', '--brief')
    eq((r.returncode, r.stdout), (0, brief), '`control --brief` (the hook) prints it')

    c1 = R.control_argv(1, 'sid-1', resume=False)
    eq(c1[0], R.plat.exe(R.C.run['agent']), 'the agent')
    watch = f'{R.C.command} since --follow --needs-you'
    check('summary' in c1[1] and f'{R.C.command} status' in c1[1]
          and f'{R.C.command} since' not in c1[1].replace(watch, ''),
          'control 1 opens with a status-only summary: no since')
    from agent_runner.guide import CONTROL_START_WATCH
    check(watch in c1[1] and 'Monitor' in c1[1] and watch in CONTROL_START_WATCH.format(cmd=R.C.command),
          'CONTROL_START names the needs-you watch, under the Monitor tool', c1[1])
    check(watch in brief and 'PushNotification' in brief and 'first turn' in brief,
          'the brief: every control session starts the needs-you watch on its first turn and pushes each line')
    from agent_runner.guide import RUNNER_START
    rs = RUNNER_START.format(cmd=R.C.command, repo='x')
    check('timeout_ms 1800000' in brief and 're-arm it silently' in brief and 'with no text at all' in brief
          and 'timeout_ms 1800000' in c1[1] and 'timeout_ms 1800000' in rs and 'say nothing at all' in rs,
          'the needs-you watch and the feed start at timeout_ms 1800000 and re-arm silently on an empty expiry')
    eq(c1[2:4], ['--session-id', 'sid-1'], 'control 1: the prompt, then its session')
    # B47: a handed-on ask carries what waits under Needs you, so a reply to it is answered, not just queued
    item = ('DECIDE', 'R43', '', 'Deploy on every push or on v* tags?', '', 'How should the site deploy')
    with mock.patch.object(R.P, 'asks', lambda *a, **k: [item]):
        msg = R.control_ask('deploy with tags instead of every push')
    check(msg.startswith('deploy with tags') and '- R43: Deploy on every push or on v* tags?' in msg
          and 'plan confirm|change|shelve ID' in msg and 'plan answer' not in msg,
          'a handed-on ask lists the waiting items and says to settle one by its id')
    # B84: the list is fenced off as runner-added, after the person's words and any attached file, and the brief
    # names the tag: settle only when the words answer it, else say nothing of the waiting items
    with mock.patch.object(R.P, 'asks', lambda *a, **k: [item]):
        msg = R.control_ask('what is wrong with the push deploy in my screenshot?', ['/tmp/shot.png'])
    head, tag, block = msg.partition('\n\n<runner-waiting>\n')
    check(tag and head.startswith('what is wrong') and 'shot.png' in head and 'R43' not in head
          and block.endswith('</runner-waiting>') and "not the person's ask" in block
          and 'say nothing of these' in block and 'From the runner feed' not in msg,
          'B84: the waiting items sit in a tagged runner block after the person\'s words, never part of them')
    check('<runner-waiting>' in brief and 'not the person\'s ask' in brief
          and 'say nothing about the waiting items' in brief,
          'B84: the brief names the runner block: answer the person, settle an item only if their words answer it')
    with mock.patch.object(R.P, 'asks', lambda *a, **k: []):
        eq(R.control_ask('add dark mode'), 'add dark mode', 'nothing waiting: the ask as it was')
    with mock.patch.object(R.P, 'asks', lambda *a, **k: (_ for _ in ()).throw(OSError())):
        eq(R.control_ask('add dark mode'), 'add dark mode', 'an unreadable plan never stops the session opening')
    argv = R.control_argv(2, 'sid-2', resume=False)
    eq(argv[0], R.plat.exe(R.C.run['agent']), 'the agent')
    eq(argv[1], '--session-id', 'a --new session has no first message: blank until the person types')
    check('blank' in brief and 'not `since`' in brief, 'the brief: later sessions start blank, the opening runs no since')
    check('never touch another\nrepository' in brief and 'explicitly asks' in brief,
          'B50: the brief: no change to another repository unless the person explicitly asks')
    mark = R.since_mark_file()
    before = mark.read_text() if mark.exists() else None
    R.control_argv(1, 'sid-1', resume=False)
    R.control_argv(2, 'sid-2', resume=False)
    eq(mark.read_text() if mark.exists() else None, before, 'opening a control session leaves the since mark')
    i = argv.index('--session-id')
    eq(argv[i:i + 4], ['--session-id', 'sid-2', '--model', R.C.run['model']], 'a new session on [run] model')
    check('--tools' not in argv, 'not lean: a person is there, so every tool (Agent for /statusline)')
    eq(argv[argv.index('--settings') + 1], str(f), 'the settings file')
    eq(argv[argv.index('--permission-mode') + 1], 'bypassPermissions', 'bypass: no permission prompts')
    check('--remote-control' not in argv, 'local without [run] remote')
    with mock.patch.dict(R.C.run, {'remote': True}):
        argv = R.control_argv(3, 'sid-3', resume=True)
    eq(argv[-2:], ['--remote-control', f'{R.ROOT.name} · control 3'], 'with [run] remote it is on Remote Control')
    check('--resume' in argv, 'resume continues the session')
    with mock.patch.dict(R.C.run, {'remote': True}), mock.patch.object(R, 'server_takes_settings', lambda e: True):
        sv = R.control_server_argv()
    eq(sv[1:], ['remote-control', '--spawn', 'same-dir', '--name', f'{R.ROOT.name} · control',
                '--permission-mode', 'bypassPermissions', '--settings', str(f)],
       'the control server: claude remote-control in the main checkout, with the control settings')
    with mock.patch.object(R, 'server_takes_settings', lambda e: True):
        check(not R.server_stale(None) and not R.server_stale([*sv, '']), 'an adopted server with these flags stays')
        check(R.server_stale([sv[0], 'remote-control', '--spawn', 'same-dir', '--settings', str(f)]),
              'one started with other flags is restarted')

    sid, resume = R.control_sid(1)
    eq(((repo / '.runner/control.sid').read_text().strip(), resume), (sid, False), 'c1 keeps a new session id')
    with mock.patch.object(R.Claude, 'find_transcript', lambda self, s: '/x.jsonl'):
        eq(R.control_sid(1), (sid, True), 'and resumes it while its transcript is there')
        check(R.control_sid(2)[0] != sid and not R.control_sid(2)[1], 'any other control session starts fresh')
    eq(R.control_number(), 1, 'no control session running: the first is c1')
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'control'])
    try:
        (repo / '.runner/control1.pid').write_text(f'{p.pid} {sid}')
        eq(R.control_live(1), p.pid, 'c1 runs')
        eq(R.control_number(), 2, 'so the next is c2')
    finally:
        p.kill()
        p.wait()
    eq(R.control_live(1), 0, 'a dead pid is not a session')
    # B59: control 2 did /new, so its pid file holds a sid its argv (the original --session-id) does not
    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '--session-id', 'old-sid',
                          '--settings', str(repo / '.runner/control-settings.json')])
    q = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '--session-id', 'other'])
    try:
        (repo / '.runner/control1.pid').write_text(f'{q.pid} {sid}')
        (repo / '.runner/control2.pid').write_text(f'{p.pid} new-sid')
        eq(R.control_live(2), p.pid, 'a control session that did /new stays live')
        eq(R.control_live(1), 0, 'a pid now held by another process is not a session')
        (repo / '.runner/control1.pid').write_text(f'{os.getpid()} {sid}')
        eq(R.control_number(), 1, 'c1 free: the first is c1')
        p2 = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', 'control'])
        try:
            (repo / '.runner/control1.pid').write_text(f'{p2.pid} {sid}')
            eq(R.control_number(), 3, 'control 2 after /new is skipped: the next is 3')
        finally:
            p2.kill()
            p2.wait()
    finally:
        for x in (p, q):
            x.kill()
            x.wait()
    (repo / '.runner/control1.pid').unlink(missing_ok=True)
    (repo / '.runner/control2.pid').unlink(missing_ok=True)

    dc = R.control_default_command(repo)
    check(dc.startswith(f'cd {repo} && ') and ' control ' in dc + ' ' and dc.endswith('|| exec "${SHELL:-/bin/sh}"'),
          'tmux default-command: a new pane is a control session in the main checkout', dc)
    a = R.control_pane_argv('%5', False, 'mine', repo, 'ar control 1', ['PATH=/bin'])
    eq(a[:8], ['tmux', 'split-window', '-v', '-d', '-l', '40%', '-t', '%5'], 'a foreground run: split under its pane')
    eq(a[-4:], ['-P', '-F', '#{pane_id}', 'ar control 1'], 'running control 1')
    a = R.control_pane_argv('%5', True, 'ar-proj', repo, 'x', [])
    eq(a[1:7], ['new-window', '-d', '-t', '=ar-proj:', '-n', 'control-proj'], 'the background run: a window of its own')
    calls = []
    panes_before = {p for d in (Path.cwd(), repo, Path(__file__).parent) for p in d.glob('%*')}
    with mock.patch.object(R, 'MUX', R.TmuxMux()), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
            mock.patch.object(R, 'tmux', lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, 'ar-proj\n', '')), \
            mock.patch.object(R.sp, 'run', tmux_run(calls)), \
            mock.patch.object(R, 'remote_on', lambda: False):
        R.start_control()
        check(any(c[:4] == ('set-option', '-t', '=ar-proj', 'default-command') for c in calls),
              "the background session's default-command is set", calls)
        check(any(c[:2] == ['tmux', 'new-window'] for c in calls if isinstance(c, list)), 'c1 opened in its window')
        check(('set-option', '-p', '-t', '%9', R.TAG, 'c1') in calls, 'tagged c1 (attach c1)')
        new = {p for d in (Path.cwd(), repo, Path(__file__).parent) for p in d.glob('%*')} - panes_before
        check('c1 is up in window' in R.C.notes('run.log').read_text() and not new,
              "B52: c1's log line lands in the repo's own run.log, and no %N folder appears", new)
        calls.clear()
        with mock.patch.dict(R.C.run, {'control': False}):
            R.start_control()
        eq(calls, [], '[run] control = false: none')
        note = R.started_note(2, 'here')
        check('c1 runs beside the run: attach c1' in note and R.REMOTE_URL not in note,
              'remote off: started_note points at c1', note)
    started = []

    class FakeThread:
        def __init__(self, target=None, name='', daemon=None):
            self.name = name

        def start(self):
            started.append(self.name)
    calls = []
    with mock.patch.object(R, 'MUX', R.TmuxMux()), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
            mock.patch.object(R, 'tmux', lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, 'ar-proj\n', '')), \
            mock.patch.object(R.sp, 'run', tmux_run(calls)), \
            mock.patch.object(R, 'remote_on', lambda: True), mock.patch.object(R.threading, 'Thread', FakeThread):
        R.start_control()
        R.start_control_server()
        opened = [c for c in calls if isinstance(c, list) and c[:2] in (['tmux', 'new-window'], ['tmux', 'split-window'])]
        check(len(opened) == 1 and opened[0][-1].endswith('control 1 --blank --local'),
              'remote on: c1 opens in tmux too, blank (free till you type) and local (not in the apps)', calls)
        check(('set-option', '-p', '-t', '%9', R.TAG, 'c1') in calls, 'and tagged c1', calls)
        eq(started, ['control-server'], 'remote on: the control server thread starts')
        note = R.started_note(2, 'here')
        check('attach c1' in note and 'terminal only' in note and 'control server' in note and R.REMOTE_URL in note,
              'remote on: started_note points at c1 (terminal only) and the control server', note)
    with mock.patch.object(R, 'remote_on', lambda: True):
        argv = R.control_argv(1, 'sid', False, blank=True, local=True)
        check(not any('summary' in a for a in argv) and '--remote-control' not in argv,
              'the c1 the run opens has no first message, and no --remote-control: the server is the one app entry', argv)
        check('--remote-control' in R.control_argv(1, 'sid', False, blank=True), 'c1 by hand without --local is on it')
        check(any('summary' in a for a in R.control_argv(1, 'sid', False)), 'c1 by hand still opens with the summary')

    skills = R.control_skills_dir()
    eq(skills, repo / '.runner' / 'control-skills', 'the control skills sit under <notes>, not in the repo files')
    skill = (skills / '.claude/skills/control/SKILL.md').read_text(encoding='utf-8')
    check('name: control' in skill and f'{R.C.command} control --new' in skill, '/control runs control --new', skill)
    for name, want in (('run', 'status $ARGUMENTS'), ('since', 'since $ARGUMENTS'), ('follow', 'since --follow'),
                       ('pause', 'pause $ARGUMENTS'), ('stop', 'stop $ARGUMENTS'), ('slots', 'slots $ARGUMENTS')):
        skill = (skills / f'.claude/skills/{name}/SKILL.md').read_text(encoding='utf-8')
        check(f'name: {name}\n' in skill and f'`{R.C.command} {want}' in skill, f'/{name} runs {want}', skill)
    check(not (skills / '.claude/skills/status').exists() and not (skills / '.claude/skills/new').exists(),
          "no /status or /new skill: Claude Code's own commands keep those names")
    check(data['permissions']['additionalDirectories'] == [str(skills)], 'the settings add that directory')
    argv = R.control_argv(2, 'sid-2', resume=False)
    eq(argv[argv.index('--add-dir') + 1], str(skills), 'and so does the control session')

    import contextlib
    import io
    link = 'https://claude.ai/code/session_01AbCdEf'
    shown = iter(['starting…\n', f'Remote Control active · {link}\n'])
    calls = []

    def fake_tmux(*a, **k):
        calls.append(a)
        out = {'display-message': 'ar-proj\n', 'new-window': '%12\n'}.get(a[0], '')
        if a[0] == 'capture-pane':
            out = next(shown)
        return subprocess.CompletedProcess(a, 0, out, '')
    out = io.StringIO()
    with mock.patch.object(R, 'tmux', fake_tmux), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
            mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), mock.patch.object(R.time, 'sleep', lambda s: None), \
            mock.patch.dict(R.C.run, {'remote': True}), contextlib.redirect_stdout(out):
        eq(R.control_new(2), 0, 'control --new opens one')
    nw = next(c for c in calls if c[0] == 'new-window')
    eq(nw[1:6], ('-d', '-t', '=ar-proj:', '-n', R.window('control2')),
       'a window of its own in this tmux session, without taking focus')
    check(nw[-1].endswith('control 2'), 'running control 2', nw)
    check(('set-option', '-p', '-t', '%12', R.TAG, 'c2') in calls, 'tagged c2 (attach c2)')
    check(link in out.getvalue(), 'and prints the link its pane shows', out.getvalue())
    calls.clear()
    out = io.StringIO()
    with mock.patch.object(R, 'tmux', fake_tmux), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
            mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), contextlib.redirect_stdout(out):
        eq(R.control_new(2), 0, 'local (no [run] remote)')
    check(not any(c[0] == 'capture-pane' for c in calls) and 'local' in out.getvalue(),
          'no link to wait for without [run] remote', out.getvalue())
    with mock.patch.object(R, 'tmux', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', '')), \
            mock.patch.dict(os.environ, {'TMUX_PANE': ''}), mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
            contextlib.redirect_stderr(io.StringIO()):
        eq(R.control_new(), 1, 'no tmux session to open it in: an error, nothing opened')

    lines = ['=== 2026-11-19T21:02:45 F2: merged, ticked', '=== 2026-11-19T21:03:00 B9: not merged, parked as wip/B9 — x',
             '=== 2026-11-19T21:04:00 slot 1: F3 (Next; a.py)', '=== 2026-11-19T21:05:00 run idle: no task']
    st = {'state': '3 slots', 'running': {'1': 'T3'}, 'since': {'1': 1000.0}, 'merging': ['T1'],
          'usage': {'five_hour': 40.0, 'seven_day': 10.4}}
    text = R.status_text(True, st, lines, {'T3': 'speed up the parser', 'F2': 'background run'}, 1000 + 12 * 60)
    eq(text.splitlines(), ['run up: 3 slots', '  s1  speed up the parser [T3]  12 min',
                           'merging: T1', 'lately:', '  21:02 landed: background run [F2]',
                           '  21:03 stuck, not merged: B9 (x) [B9]',
                           '  21:05 run idle: nothing left it may start', 'usage: session 40%, week 10%'],
       'status reads well on a phone: titles first, ids in brackets at the end')


def test_concepts_waiting(repo: Path):
    print('concepts: status and since list what waits for your OK first; a K task\'s prompt says build nothing')
    R.init(repo)
    w = [('CONCEPT', 'F9', 'K7', 'pick an option on the page', 'https://claude.ai/code/artifact/aaa',
          'Settings page layout', False)]
    line = ['  Pick an option for settings page layout - reply A/B/C [K7]', '    https://claude.ai/code/artifact/aaa']
    text = R.status_text(False, {}, [], {}, 0.0, waiting=w)
    eq(text.splitlines(), ['Needs you:', *line, 'no run is up'],
       'status: Needs you first, in plain words, no label, the link on its own line')
    eq(R.status_text(False, {}, [], {}, 0.0), 'no run is up', 'and nothing extra when none waits')
    now = R.dt.datetime(2026, 11, 19, 15, 0, 0)
    text, _ = R.since_text([], now - R.dt.timedelta(hours=2), {}, now, waiting=w)
    eq(text.splitlines(), ['Needs you:', *line, 'nothing new since 13:00'],
       'since: the same, however old the concept is')
    with tempfile.TemporaryDirectory() as tmp:
        todo = Path(tmp) / 'TODO.md'
        P.ensure(todo)
        P.add('K', 'settings page layout | files: a.py', todo=todo)
        bid = P.concept_done('K1', 'https://x.invalid/p', todo=todo)
        with mock.patch.object(type(R.C), 'todo', property(lambda self: todo)):
            got = R.waiting_ok()
            eq([g[:7] for g in got], [('CONCEPT', bid, 'K1', 'pick an option on the page', 'https://x.invalid/p',
                                       'settings page layout', False)],
               'waiting_ok reads the build tasks waiting on a concept page off TODO.md')
            check(re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d', got[0][7]), 'B27: with the time it was asked', got)
    prompt = R.prompt_for('K7', 1, 1, repo, 'main')
    has(prompt, r'K7 is a concept task: do not build it', 'a K task\'s prompt says to build nothing')
    has(prompt, r'done K7 "<msg>" --artifact <the page\'s URL>', 'and how to finish it')
    check('concept task' not in R.prompt_for('T2', 1, 1, repo, 'main'), 'other tasks\' prompts do not')


def test_person_waiting(repo: Path):
    print('waiting for your OK: tasks blocked on a person list with a caps label; confirm, change and shelve move them')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'runner.toml').write_text('[plan]\njournal = "journal"\n', encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        todo, done = root / 'plan' / 'TODO.md', root / 'plan' / 'DONE.md'
        for text in ('push notices | files: a.py', 'pick a database | files: b.py', 'deploy key | files: c.py',
                     'other work | files: d.py'):
            check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
        r = run(root, 'done', 'F1', 'F1: pushes', '--no-test', '--blocked',
                'CONFIRM: watch a phone for a push when a task lands, see https://x.invalid/howto', env=env)
        check(r.returncode == 0, 'done --blocked with a CONFIRM label goes through', r.stdout + r.stderr)
        P.block('F2', 'DECIDE: Postgres or SQLite? F4 does not care', todo=todo)
        P.block('F3', 'BLOCKED: needs a deploy key on the server', todo=todo)
        P.block('F4', 'needs F2 first', todo=todo)  # B35: a block on no open task would be an ask too
        check('(after' not in todo.read_text(encoding='utf-8').split('**F2**')[1].split('\n')[0],
              'a block on a person waits on no task, even one its words name')
        a = sorted(P.asks(todo), key=lambda x: x[1])
        eq([(x[0], x[1]) for x in a], [('CONFIRM', 'F1'), ('DECIDE', 'F2'), ('BLOCKED', 'F3')],
           'asks lists the person-blocked tasks with their labels, not a plain block')
        eq((a[0][3], a[0][4]), ('watch a phone for a push when a task lands, see', 'https://x.invalid/howto'),
           'what to do, and its link apart')
        with mock.patch.object(type(R.C), 'todo', property(lambda self: todo)):
            w = R.waiting_ok()
        check(all(re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d', x[7]) for x in w),
              'B27: each block on a person is stamped with when it was asked', w)
        check(all('(asked' not in x[3] for x in w), 'and the stamp stays out of what it asks', w)
        has(todo.read_text(encoding='utf-8'), r'\*\*F2\*\* .*BLOCKED: DECIDE: Postgres or SQLite\? F4 does not care '
            r'\(asked \d{4}-\d\d-\d\d \d\d:\d\d\)$', 'the stamp is on the block line in TODO.md')
        # fixed stamps, so the ages and the order do not hang on the clock
        stamps = {'F1': '2026-11-19 10:00', 'F2': '2026-11-19 14:30', 'F3': '2026-11-19 12:00'}
        w = [(*x[:7], stamps[x[1]]) for x in w]
        now = R.dt.datetime(2026, 11, 19, 15, 0, 0)
        text = R.status_text(False, {}, [], {}, now.timestamp(), waiting=w)
        eq(text.splitlines(), ['Needs you:',
                               '   5h  Watch a phone for a push when a task lands - reply yes/no [F1]',
                               '    https://x.invalid/howto',
                               '   3h  Needs a deploy key on the server - reply done once it is [F3]',
                               '  30m  Postgres or SQLite? F4 does not care - reply with your answer [F2]',
                               'no run is up'],
           'B27 status: Needs you, oldest first with its age, what is asked and what to reply, no caps label, '
           'the link on its own line')
        text = R.since_text([], now, {}, now, waiting=w)[0]
        check(text.startswith('Needs you:\n   5h  Watch a phone') and 'CONFIRM' not in text
              and 'DECIDE' not in text and 'BLOCKED' not in text, 'since: the same', text)
        nc = {'heading': 'Needs you', 'ages': True, 'order': 'oldest'}
        for order, ids in (('newest', ['F2', 'F3', 'F1']), ('plan', ['F3', 'F2', 'F1'])):
            with mock.patch.object(P, 'needs_cfg', lambda: {**nc, 'order': order}):
                got = re.findall(r'\[(F\d)\]', '\n'.join(R.waiting_text(w, now=now)))
            eq(got, ids, f'B27: [needs] order = "{order}"')
        with mock.patch.object(P, 'needs_cfg', lambda: {**nc, 'ages': False, 'heading': 'Your turn'}):
            got = R.waiting_text(w, now=now)
        eq(got[:2], ['Your turn:', '  Watch a phone for a push when a task lands - reply yes/no [F1]'],
           'B27: [needs] heading and ages = false')
        out = run(root, 'plan', 'waiting', env=env).stdout
        has(out, r'^CONFIRM  F1  push notices  watch a phone .* https://x\.invalid/howto$', 'plan waiting lists it')
        has(out, r'^DECIDE  F2  pick a database', 'and the decision')

        r = run(root, 'plan', 'shelve', 'F3', env=env)
        check(r.returncode == 0, 'shelve goes through', r.stderr)
        has(todo.read_text(encoding='utf-8'), r'^- \[~\] \*\*F3\*\* .*BLOCKED: shelved: BLOCKED: needs a deploy key',
            'shelved: still blocked')
        check('F3' not in run(root, 'plan', 'waiting', env=env).stdout, 'and off plan waiting')
        has(run(root, 'plan', 'waiting', '--all', env=env).stdout, r'^BLOCKED  F3 .*\(shelved\)$', 'but --all shows it')
        with mock.patch.object(type(R.C), 'todo', property(lambda self: todo)):
            text = R.status_text(False, {}, [], {}, 0.0, waiting=R.waiting_ok())
        check('[F3]' not in text, 'status leaves it out', text)
        has(text, r'\(1 shelved: plan waiting --all\)', 'and counts it')
        run(root, 'plan', 'unshelve', 'F3', env=env)
        has(run(root, 'plan', 'waiting', env=env).stdout, r'^BLOCKED  F3 ', 'unshelve brings it back')

        r = run(root, 'plan', 'confirm', 'F1', 'the push came within a minute', env=env)
        check(r.returncode == 0, 'confirm goes through', r.stderr)
        has(done.read_text(encoding='utf-8'), r'- \[x\] \*\*F1\*\* .*confirmed by you .*: the push came within a minute',
            'a CONFIRM is ticked with what they saw')
        r = run(root, 'plan', 'confirm', 'F2', 'SQLite', env=env)
        has(todo.read_text(encoding='utf-8'), r'^- \[ \] \*\*F2\*\* .*your answer \(DECIDE .*\): SQLite$',
            'a DECIDE reopens with the answer noted')
        r = run(root, 'plan', 'change', 'F3', 'use the CI deploy token instead', env=env)
        check(r.returncode == 0, 'change goes through', r.stderr)
        t = todo.read_text(encoding='utf-8')
        has(t, r'^- \[ \] \*\*F3\*\* .*do this instead: use the CI deploy token instead$', 'change: noted and reopened')
        check(' BLOCKED: ' not in t.split('**F3**')[1].split('\n')[0], 'without its block')
        has(run(root, 'plan', 'waiting', env=env).stdout, r'^nothing waits for your OK', 'nothing waits now')
        eq(run(root, 'plan', 'confirm', 'F4', env=env).returncode != 0, True, 'a plain block takes no confirm')
        eq(git(root, 'status', '--porcelain'), '', 'every answer committed')

        k = P.add('K', 'menu layout | files: m.py', todo=todo)
        bid = P.concept_done(k, 'https://x.invalid/k', todo=todo)
        P.shelve(k, todo=todo)
        eq(P.asks(todo), [], 'a concept page shelves too')
        eq([x[0] for x in P.asks(todo, all=True)], ['CONCEPT'], 'and --all still lists it')
        eq(P.confirm(k, 'option A', todo=todo), f'approved: {bid} is open now, and a run starts it',
           'confirm on a concept approves it, shelved or not')


def test_drop_or_change_running(repo: Path):
    print('B19: plan drop / change on a task a slot runs stops that slot; a dropped branch never reaches main')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text().replace('### Stretch', '- [ ] **H1** the halt | files: dr1.py\n'
                                             '- [ ] **H2** the change | files: dr2.py\n'
                                             '- [ ] **H3** finished first | files: dr3.py\n\n### Stretch'))
    git(repo, 'commit', '-qam', 'plan: H1-H3')
    git(repo, 'push', '-q', 'origin', 'main')
    lock = R.plat.lock(R.C.notes('run.lock'))  # this test stands in for the run that is up
    sessions = []

    def session() -> int:
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
        sessions.append(p)
        return p.pid

    def on_slot(n: int, tid: str, f: str) -> Path:
        d = task_branch(repo, n, tid)
        (d / f).write_text(f'# {tid}\n', encoding='utf-8')
        git(d, 'add', '-A'), git(d, 'commit', '-qm', f'{tid}: work')
        git(d, 'push', '-q', 'origin', f'task/{tid}')
        (d / 'scratch.txt').write_text('uncommitted\n', encoding='utf-8')
        return d

    def plan_cmd(*a: str) -> subprocess.Popen:
        env = {**os.environ}
        return subprocess.Popen([sys.executable, str(RUN), 'plan', *a], cwd=str(repo), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def asked(tid: str) -> bool:
        end = time.time() + 30
        while time.time() < end and not (R.P.halt_dir(R.C) / f'{tid}.json').exists():
            time.sleep(0.1)
        return (R.P.halt_dir(R.C) / f'{tid}.json').exists()

    on_main = lambda: git(repo, 'ls-tree', '--name-only', 'main').split()
    started = []
    real_start = R.start
    try:
        # --- drop mid-run ---
        d1 = on_slot(1, 'H1', 'dr1.py')
        pid = session()
        procs, running = {1: (pid, 'sid-h1', 0)}, {1: ('H1', 'Later', {'dr1.py'}, set())}
        free_at = {1: R.dt.datetime.max}
        tried: set[str] = set()
        R.write_state(running)
        eq(R.P.run_on(R.C, 'H1'), 's1', 'plan sees from the run state that s1 runs H1')
        p = plan_cmd('drop', 'H1', 'not wanted after all')
        check(asked('H1'), 'plan drop leaves a request for the run')
        R.halts(procs, running, free_at, tried, 'main', 'opus', 30, 2)
        out, err = p.communicate(timeout=60)
        check(p.returncode == 0, 'plan drop goes through', err)
        has(out, r'^dropped H1$', 'it says the plan edit')
        has(out, r'^dropped H1; stopped s1, removed its work \(reset s1, deleted task/H1, deleted task/H1 from origin\)$',
            'and what the run did')
        check(sessions[0].wait(10) is not None, 'the session is ended')
        eq((procs, running), ({}, {}), 'the slot is no longer running it')
        check(free_at[1] <= R.dt.datetime.now(), 'and is free for the next task at once')
        check(git(repo, 'branch', '--list', 'task/H1') == '', 'task/H1 is deleted here')
        check('task/H1' not in remote_branches(repo.parent), 'and on the remote')
        eq(git(d1, 'status', '--porcelain'), '', 'the worktree is reset clean')
        eq(git(d1, 'rev-parse', '--abbrev-ref', 'HEAD'), 'HEAD', 'and detached, off the deleted branch')
        has((repo / 'plan/DONE.md').read_text(encoding='utf-8'), r'\*\*H1\*\* .*dropped: not wanted after all', 'the plan archives it')
        eq(R.halt_requests(), {}, 'the request is answered and gone')
        R.finish('H1', 1, 'sid-h1', 'main')  # the session's exit, had the run reaped it, finds nothing to merge
        check('dr1.py' not in on_main(), 'nothing of H1 reached main')

        # --- a finished branch waiting to merge: dropped before its merge, it never lands ---
        on_slot(2, 'H3', 'dr3.py')
        git(R.SLOTS_DIR / 's2', 'checkout', '-q', '--detach')
        (R.P.halt_dir(R.C) / 'H3.json').write_text(json.dumps({'how': 'drop'}), encoding='utf-8')
        R.finish('H3', 2, 'sid-h3', 'main')
        check('dr3.py' not in on_main(), 'a dropped finished branch is not merged')
        check(git(repo, 'branch', '--list', 'task/H3') == '', 'and is deleted')
        R.halts({}, {}, {}, set(), 'main', 'opus', 30, 2)
        has((R.P.halt_dir(R.C) / 'H3.done').read_text(encoding='utf-8'), r'^dropped H3; its finished branch never merged',
            'the run says so')

        # --- change mid-run: stopped the same way, restarted with the new text ---
        on_slot(1, 'H2', 'dr2.py')
        pid = session()
        procs, running = {1: (pid, 'sid-h2', 0)}, {1: ('H2', 'Later', {'dr2.py'}, set())}
        free_at = {1: R.dt.datetime.max}
        R.write_state(running)
        R.start = lambda n, task, *a: (started.append((n, task[0], '\n'.join(R.plan_text('main')))),
                                       (4343, 'sid-h2b', 0))[1]
        p = plan_cmd('change', 'H2', '--restart', 'use a table instead')  # F16: else it is told, not stopped
        check(asked('H2'), 'plan change leaves a request for the run')
        tried = {'H2'}
        R.halts(procs, running, free_at, tried, 'main', 'opus', 30, 2)
        out, err = p.communicate(timeout=60)
        check(p.returncode == 0, 'plan change on a running task goes through', err)
        has(out, r'^H2 has your change noted$', 'the change is noted on the open task')
        has(out, r'^changed H2; stopped s1, removed its work \(.*deleted task/H2.*\); restarted it in s1 with the new text$',
            'the run stops and restarts it')
        eq([s[:2] for s in started], [(1, 'H2')], 'restarted in the same slot')
        has(started[0][2] if started else '', r'do this instead: use a table instead', 'and its brief has the new text')
        eq(running.get(1, ('',))[0], 'H2', 'the slot runs it again')
        eq(procs.get(1), (4343, 'sid-h2b', 0), 'in a new session')
        check(git(repo, 'branch', '--list', 'task/H2') == '' and 'task/H2' not in remote_branches(repo.parent),
              'the old attempt\'s branch is gone')

        # nothing running it: plan says the edit and nothing more
        R.write_state({})
        r = run(repo, 'plan', 'note', 'H2', 'just a note')
        check('stopped' not in r.stdout, 'a plain note never asks the run anything')
        eq(R.P.halt(R.C, 'H2', 'drop', wait=0), '', 'a task no slot runs: no request')
        eq(R.halt_requests(), {}, '(none left)')
    finally:
        R.start = real_start
        for s in sessions:
            s.kill()
            s.wait()
        lock.close()
        R.write_state({})


def test_tell_running(repo: Path):
    print('F16: plan change on a running task types the change into its pane and does not stop it; plan tell')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text().replace('### Stretch', '- [ ] **G1** the told | files: tl1.py\n\n### Stretch'))
    git(repo, 'commit', '-qam', 'plan: G1')
    git(repo, 'push', '-q', 'origin', 'main')
    lock = R.plat.lock(R.C.notes('run.lock'))  # this test stands in for the run that is up
    sess = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
    calls: list[tuple] = []
    real = (R.tmux, R.MUX)

    def fake_tmux(*a, **kw):
        calls.append((a, kw.get('input')))
        return subprocess.CompletedProcess(['tmux', *a], 0, '', '')

    class Mux(R.TmuxMux):
        live = True

        def panes(self):
            return {'s1': ('%9', sess.pid)} if self.live else {}

    def plan_cmd(*a: str) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, str(RUN), 'plan', *a], cwd=str(repo), env={**os.environ},
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def asked(d: Path, tid: str) -> bool:
        end = time.time() + 30
        while time.time() < end and not (d / f'{tid}.json').exists():
            time.sleep(0.1)
        return (d / f'{tid}.json').exists()

    tells, halts = R.P.tell_dir(R.C), R.P.halt_dir(R.C)
    try:
        R.tmux, R.MUX = fake_tmux, Mux()
        procs, running = {1: (sess.pid, 'sid-g1', 0)}, {1: ('G1', 'Later', {'tl1.py'}, set())}
        R.write_state(running)

        # --- change on a running task: told, not halted ---
        p = plan_cmd('change', 'G1', 'publish anyway, B171 is fine')
        check(asked(tells, 'G1'), 'plan change leaves a tell request for the run')
        check(not (halts / 'G1.json').exists(), 'and no halt request')
        R.tells(procs, running)
        out, err = p.communicate(timeout=60)
        check(p.returncode == 0, 'plan change goes through', err)
        has(out, r'^G1 has your change noted$', 'the plan line is edited as before')
        has(out, r'^told s1 \(G1\)$', 'and it says the agent has the message')
        eq([c[0][0] for c in calls], ['load-buffer', 'paste-buffer', 'send-keys'], 'paste, then Enter')
        eq(calls[0][1], 'Your task changed: publish anyway, B171 is fine', 'the agent reads the change')
        check('%9' in calls[1][0] and calls[2][0][-2:] == ('%9', 'Enter'), 'into s1\'s pane', calls)
        eq(running.get(1, ('',))[0], 'G1', 'the slot still runs it')
        check(sess.poll() is None, 'its session is not ended')
        check(not (halts / 'G1.json').exists(), 'nothing asked the run to halt it')
        has(todo.read_text(encoding='utf-8'), r'do this instead: publish anyway', 'the change is noted in the plan')

        # --- tell: no plan edit ---
        calls.clear()
        before = todo.read_text(encoding='utf-8')
        p = plan_cmd('tell', 'G1', 'look at the gate log first')
        check(asked(tells, 'G1'), 'plan tell leaves a request')
        R.tells(procs, running)
        out, err = p.communicate(timeout=60)
        check(p.returncode == 0, 'plan tell goes through', err)
        eq(out.strip(), 'told s1 (G1)', 'it prints told')
        has(calls[0][1] if calls else '', r'look at the gate log first$', 'the agent reads the note')
        eq(todo.read_text(encoding='utf-8'), before, 'the plan is not edited')

        # --- tell on a task no slot runs: an error, no request ---
        r = run(repo, 'plan', 'tell', 'G9', 'hello')
        check(r.returncode != 0, 'tell on a task that is not running fails')
        has(r.stderr, r'G9 is not running', 'and says so')
        eq(R.tell_requests(), {}, 'no request left for the run')

        # --- --restart keeps the B19 halt ---
        p = plan_cmd('change', 'G1', '--restart', 'start over with a table')
        check(asked(halts, 'G1'), '--restart asks the run to halt it')
        check(not (tells / 'G1.json').exists(), 'and tells it nothing')
        R.halt_answer('G1', 'changed G1; stopped s1')
        out, err = p.communicate(timeout=60)
        has(out, r'^changed G1; stopped s1$', 'it prints what the run did')
        check('--restart' not in todo.read_text(encoding='utf-8'), 'the flag is not noted as text')

        # --- no live pane: falls back to the halt, and says so ---
        R.MUX.live = False
        p = plan_cmd('change', 'G1', 'use a list')
        check(asked(tells, 'G1'), 'plan change asks the run to tell it first')
        R.tells(procs, running)
        check(asked(halts, 'G1'), 'no pane: then it asks the run to halt it')
        R.halt_answer('G1', 'changed G1; stopped s1')
        out, err = p.communicate(timeout=60)
        has(out, r'^no live pane for s1 \(G1\): its session has ended; stopping it and starting it again',
            'it says why it falls back')
        has(out, r'^changed G1; stopped s1$', 'and what the run did')
    finally:
        R.tmux, R.MUX = real
        sess.kill()
        sess.wait()
        lock.close()
        R.write_state({})


def test_short_titles_and_since(repo: Path):
    print('short titles for a person, and since: what happened since the last look, with its mark')
    st = R.short_title
    eq(st(" Control session experience (user 2026-11-19: 'commands (and) hints'). (1) A control session opens"),
       'Control session experience', 'no quoted asides, dates or later sentences')
    eq(st(' (follow-up, normal) Fix the menu flicker | files: a.py, b/c.rs | after: B1'), 'Fix the menu flicker',
       'no follow-up tag and no fields')
    eq(st(' **Bake** the `letter` sheet (see src/sheet.rs, plan/TODO.md) — it is slow'), 'Bake the letter sheet',
       'no bold, backticks or file lists')
    eq(st(' Keep the (small) cache warm: the gate runs faster'), 'Keep the (small) cache warm: the gate runs faster',
       'a plain aside and a lower-case clause stay')
    long = st(' ' + 'word ' * 30)
    check(len(long) <= 60 and long.endswith('word…'), 'cut at a word to about 60 characters', long)
    eq(st(' make the test `releases::tests::registers_the_discs_beside_and_their_voices` pass again | files: a'),
       'make the test registers_the_discs_beside_and_their_voices…', 'a test path a::b::c shows as its name')
    eq(st(' make `tests/test_x.py::test_y` pass'), 'make test_y pass', 'a pytest path too')
    one = st(' fix ' + 'x' * 80)
    check(len(one) == 60 and one.startswith('fix xxx') and one.endswith('x…'),
          'one word longer than the width: cut inside it, not down to the first word', one)

    R.init(repo)
    titles = {'F5': 'Control session experience', 'B9': 'Fix the flicker'}
    now = R.dt.datetime(2026, 11, 19, 15, 0, 0)
    log = ['=== 2026-11-18T21:00:00 slot 1: B9 (Next; a.py)',
           '=== 2026-11-19T13:00:00 slot 2: F5 (Next; agent_runner/runner.py)',
           '=== 2026-11-19T13:01:00 F5: dropped task/F5 from origin',
           '=== 2026-11-19T14:00:00 F5: merged, ticked',
           '=== 2026-11-19T14:10:00 B9: not merged, parked as wip/B9 — tests fail after the merge. More words',
           '=== 2026-11-19T14:20:00 run idle: no task it may start']
    eq(R.since_start('2h', None, now), now - R.dt.timedelta(hours=2), '2h')
    eq(R.since_start('yesterday', None, now), R.dt.datetime(2026, 11, 18), 'yesterday: from its midnight')
    eq(R.since_start(None, '2026-11-19T13:30:00', now), R.dt.datetime(2026, 11, 19, 13, 30), 'no WHEN: the mark')
    eq(R.since_start(None, None, now), now - R.dt.timedelta(hours=24), 'no mark yet: a day back')
    text, last = R.since_text(log, R.since_start('yesterday', None, now), titles, now)
    eq(text.splitlines(), ['since yesterday 00:00:', '  yesterday 21:00  started: Fix the flicker [B9]',
                           '  13:00  started: Control session experience [F5]',
                           '  14:00  landed: Control session experience [F5]',
                           '  14:10  stuck, not merged: Fix the flicker (tests fail after the merge) [B9]',
                           '  14:20  run idle: nothing left it may start'], 'oldest first, one short line each')
    eq(last, '2026-11-19T14:20:00', 'the newest stamp read')

    notes = R.C.notes('run.log')
    keep = notes.read_text(encoding='utf-8') if notes.exists() else None
    evf = R.events_file()  # F41: these lines are a run.log from before events.jsonl, read as such
    keep_ev = evf.read_text(encoding='utf-8') if evf.exists() else None
    evf.unlink(missing_ok=True)
    R.since_mark_file().unlink(missing_ok=True)
    try:
        today = R.dt.date.today().isoformat()  # the command reads the clock: today's stamps read as times
        notes.write_text('\n'.join(l.replace('2026-11-19', today) for l in log) + '\n', encoding='utf-8')
        r1 = run(repo, 'since', f'{today}T12:00')
        has(r1.stdout, r'landed: .*\[F5\]', 'since WHEN prints what happened')
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), f'{today}T14:20:00', 'and moves the mark')
        r2 = run(repo, 'since')
        eq((r2.returncode, r2.stdout.strip().splitlines()[-1]), (0, 'nothing new since 14:20 (your last look)'),
           'since twice in a row: nothing new the second time')
        mark = R.since_mark_file().read_text(encoding='utf-8').strip()  # now: nothing newer was in the log
        R.move_since_mark(f'{today}T10:00:00')
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), mark, 'the mark never goes back')
        later = (R.dt.datetime.fromisoformat(mark) + R.dt.timedelta(seconds=1)).isoformat()
        with notes.open('a', encoding='utf-8') as f:
            f.write(f'=== {later} slot 1: B9 (Next; a.py)\n')
        has(run(repo, 'since').stdout, r'^since \S+ \(your last look\):\n  .*started: .*\[B9\]$',
            'then only the new')
        eq(run(repo, 'since').stdout.count('B9'), 0, 'and that once')
        eq(run(repo, 'since', 'soon').returncode, 1, 'a WHEN that is no time is refused')
        lines, last = R.follow_lines('\n'.join(log[3:5]), titles, now)
        eq(len(lines), 2, 'follow: a line per event')
        check(lines[0].startswith('14:00  landed: Control session experience [F5]'), 'follow: landed with its title',
              lines)
        eq(last, '2026-11-19T14:10:00', 'follow moves the mark to what it read')
        import contextlib
        import io
        later2 = (R.dt.datetime.fromisoformat(later) + R.dt.timedelta(seconds=5)).isoformat()
        def add():
            with notes.open('a', encoding='utf-8') as fh:
                fh.write(f'=== {later2} F5: merged, ticked\n')
        threading.Timer(0.5, add).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            R.follow(poll=0.1, until=time.monotonic() + 2)
        got = out.getvalue().splitlines()
        eq(len(got), 2, f'follow: its header, then only the new line, not the backlog: {got}')
        check('landed: F5 [F5]' in got[-1],'follow prints a landed task as it lands', got)
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), later2, 'and moves the since mark')

        # --needs-you: only what a person must clear; landed and started are skipped
        ny = ['=== 2026-11-19T14:30:00 slot 1: B9 (Next; a.py)',
              '=== 2026-11-19T14:31:00 F5: merged, ticked',
              '=== 2026-11-19T14:32:00 STOPPED: F5 cannot land: uncommitted edits in demo: commit or move them',
              '=== 2026-11-19T14:33:00 B9: LEFT FOR A HUMAN — the merge crashed: boom',
              '=== 2026-11-19T14:34:00 slot 2: F5 looks stalled (no output for 20 min); look at s2',
              '=== 2026-11-19T14:35:00 B9: merged, blocked',
              '=== 2026-11-19T14:36:00 run idle: no task it may start']
        ask = [('DECIDE', 'B9', '', 'Postgres or SQLite?', 'https://x.invalid/b9', 'Fix the flicker', False)]
        lines, last = R.follow_lines('\n'.join(ny), titles, now, needs_you=True, waiting=ask)
        eq(lines, ['14:32  run held, needs you: F5 cannot land: uncommitted edits in demo: commit or move them',
                   '14:33  needs you: Fix the flicker (the merge crashed: boom) [B9]',
                   '14:34  looks stuck: Control session experience [F5]',
                   '14:35  needs you: Postgres or SQLite? - reply with your answer [B9]  https://x.invalid/b9'],
           '--needs-you: STOPPED with what holds it, LEFT FOR A HUMAN, stalled, a person ask; no landed/started/idle')
        lines, _ = R.follow_lines('\n'.join(ny), titles, now, needs_you=True, waiting=[])
        check(not any('reply' in l or 'landed' in l or 'started' in l for l in lines),
              'a blocked task asking nobody is not news for the watch', lines)
        later3 = (R.dt.datetime.fromisoformat(later2) + R.dt.timedelta(seconds=5)).isoformat()
        def add2():
            with notes.open('a', encoding='utf-8') as fh:
                fh.write(f'=== {later3} F5: merged, ticked\n'
                         f'=== {later3} STOPPED: F5 cannot land: {R.ROOT.name} is mid-merge: finish it\n'
                         f'=== {later3} B9: LEFT FOR A HUMAN — the merge crashed: boom\n')
        threading.Timer(0.5, add2).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            R.follow(poll=0.1, until=time.monotonic() + 2, needs_you=True)
        got = out.getvalue().splitlines()
        eq(len(got), 3, f'follow --needs-you: its header, the STOPPED and the LEFT FOR A HUMAN lines: {got}')
        check('needs you' in got[0] and 'run held, needs you: F5 cannot land' in got[1]
              and 'needs you: B9' in got[2] and not any('landed' in g for g in got), 'and skips the landed one', got)
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), later2, 'the needs-you watch leaves the mark')
        eq(run(repo, 'since', '--needs-you').returncode, 2, '--needs-you without --follow is refused')

        # the board: a header pointing at control sessions, a feed, and the mark left for the person
        later4 = (R.dt.datetime.fromisoformat(later3) + R.dt.timedelta(seconds=5)).isoformat()
        def add3():
            with notes.open('a', encoding='utf-8') as fh:
                fh.write(f'=== {later4} F5: merged, ticked\n')
        threading.Timer(0.5, add3).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            R.follow(poll=0.1, until=time.monotonic() + 2, mark=False)
        check('landed: F5' in out.getvalue(), 'the board feed prints what lands', out.getvalue())
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), later2, 'and leaves the mark')
        check(f'{R.RUNNER} control' in R.board_header() or 'claude.ai/code' in R.board_header(),
              'its header says where to steer from', R.board_header())
        argv = R.board_argv('ar-demo', repo, 'agent-runner since --board')
        check(argv[:5] == ['tmux', 'new-window', '-d', '-t', '=ar-demo:'] and R.window('board') in argv,
              'the board opens in the background session without taking focus', argv)

        # the runner feed: with [run] remote the board is a lean Haiku session in the apps too
        with mock.patch.object(R, 'remote_on', lambda: True), mock.patch.dict(R.C.run, {'agent': 'claude'}):
            fa = R.feed_argv()
            opt = lambda k: fa[fa.index(k) + 1]
            eq((opt('--model'), opt('--tools'), opt('--permission-mode'), opt('--remote-control')),
               ('haiku', 'Bash,Monitor,PushNotification', 'dontAsk', f'{R.ROOT.name} · runner'),
               'the feed: Haiku, Bash, Monitor and PushNotification only, dontAsk, "<repo> · runner" on Remote Control')
            eq(json.loads(opt('--settings')), {'autoMemoryEnabled': False}, 'the feed loads no auto memory')
            check('PushNotification' in opt('--system-prompt'), 'and pushes what needs the person')
            brief, opening = R.control_brief(), R.control_argv(1, 'sid', False)[1]
            check('start no needs-you watch' in brief and '--needs-you' not in opening,
                  'with the feed, control sessions start no needs-you watch', (brief[:80], opening))
            check(opt('--allowedTools') == f'Bash({R.C.command} *)' and opt('--setting-sources') == ''
                  and '--strict-mcp-config' in fa, 'Bash only for the runner command; no settings or MCP', fa)
            check('control --new --forward' in opt('--system-prompt') and '--ask' not in opt('--system-prompt')
                  and 'since --follow --keep-mark' in fa[1],
                  'it hands other asks to a control session and follows without moving the mark', fa)
            bc = R.board_command()
            check(bc.endswith(f'since --board --feed --run-pid {os.getpid()}'),
                  'the board runs the feed with remote on, ended with this run', bc)
        with mock.patch.object(R, 'remote_on', lambda: False):
            check(R.board_command().endswith(f'since --board --run-pid {os.getpid()}'),
                  'and the free text feed with it off', R.board_command())
            check('since --follow --needs-you`, once' in R.control_brief()
                  and '--needs-you' in R.control_argv(1, 'sid', False)[1],
                  'without the feed, control sessions keep their own needs-you watch')
        ask = [('DECIDE', 'B9', '', 'Postgres or SQLite?', 'https://x.invalid/b9', 'Fix the flicker', False)]
        full, _ = R.follow_lines('=== 2026-11-19T14:35:00 B9: merged, blocked', titles, now, waiting=ask)
        check(any('needs you: Postgres or SQLite? - reply with your answer [B9]' in l for l in full),
              'the full feed carries the asks too, in plain words (B27)', full)
        check(not any('DECIDE' in l for l in full), 'B27: no caps label in the feed', full)
        with mock.patch.object(R, 'remote_on', lambda: True), mock.patch.dict(R.C.run, {'agent': 'claude'}):
            fa = R.feed_argv()
            sp_ = fa[fa.index('--system-prompt') + 1]
            check(f'{R.C.command} plan confirm ID "<their words>"' in sp_ and f'{R.C.command} plan shelve ID' in sp_
                  and '"Needs you"' in sp_ and 'plan answer' not in sp_ and 'ask which one they mean' in sp_,
                  'C5: the feed maps a reply under Needs you to its id, and asks when it cannot tell', sp_)
        # B71: a project's [run] command may wrap only part of the runner (openmx's ./kit: run/stop/plan/done)
        with mock.patch.object(R, 'remote_on', lambda: True), \
                mock.patch.dict(R.C.run, {'agent': 'claude', 'command': './kit'}):
            eq(R.C.command, './kit', 'B71: the test sets a wrapper command')
            fa = R.feed_argv()
            opt = lambda k: fa[fa.index(k) + 1]
            check(f'`{R.RUNNER} since --follow --keep-mark`' in fa[1] and './kit' not in fa[1],
                  'B71: the feed Monitors the runner itself, not [run] command', fa[1])
            check(f'`{R.RUNNER} control --new --forward`' in opt('--system-prompt')
                  and f'{R.RUNNER} plan confirm ID' in opt('--system-prompt') and './kit' not in opt('--system-prompt'),
                  'B71: the feed system prompt names the runner', opt('--system-prompt'))
            eq(opt('--allowedTools'), f'Bash({R.RUNNER} *)', 'B71: the feed may run the runner, not ./kit')
            brief = R.control_brief()
            check(f'`{R.RUNNER} status`' in brief and f'{R.RUNNER} plan confirm' in brief and './kit' not in brief,
                  'B71: the control brief names the runner', brief[:200])
            with mock.patch.object(R, 'feed_on', lambda: False):
                opening = R.control_argv(1, 'sid', False)[1]
                check(f'`{R.RUNNER} status`' in opening and f'{R.RUNNER} since --follow --needs-you' in opening
                      and './kit' not in opening, 'B71: the control opening names the runner', opening)
                check('./kit' not in R.control_brief(), 'B71: and so does its needs-you watch')
            skills = R.control_skills_dir() / '.claude' / 'skills'
            check(f'{R.RUNNER} control --new' in (skills / 'control' / 'SKILL.md').read_text(encoding='utf-8')
                  and './kit' not in (skills / 'since' / 'SKILL.md').read_text(encoding='utf-8'),
                  'B71: the /control and /since skills call the runner')
        started = []
        with mock.patch.object(R, 'MUX', R.TmuxMux()), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
                mock.patch.object(R, 'tmux', lambda *a, **k: subprocess.CompletedProcess(a, 0, 'mine\n', '')), \
                mock.patch.object(R.threading, 'Thread', lambda target=None, args=(), **k: mock.Mock(
                    start=lambda: started.append(args))):
            R.start_board()
        eq(started, [('mine',)], 'the board opens in a run in your own tmux session too')
        ca = R.control_argv(3, 'sid', False, ask='fix the login flicker')
        check(ca[1].startswith('fix the login flicker'), 'control --ask: the handed-on request is its first message')
        ca = R.control_argv(3, 'sid', False, ask='why is this red?', images=['/t/a.png', '/t/b b.png'])
        check(ca[1].startswith('why is this red?') and '"/t/a.png"' in ca[1] and '"/t/b b.png"' in ca[1]
              and ca[1].count('Read or open it') == 2 and 'attached a.png' in ca[1],
              'control --image: each attached image is named in the first message', ca[1])
        up = '/h/.claude/uploads/77e72152/b292b0ab-pass word.txt'
        ca = R.control_argv(3, 'sid', False, ask='use this', images=[up])
        check('The person attached pass word.txt, saved at "' + up + '": Read or open it' in ca[1],
              'B30: an upload is named without its id prefix, with its path', ca[1])
        eq(R.control_title('', [up]), 'pass word.txt', 'B30: a file-only ask is titled by its name')
        rn = R.ROOT.name
        eq(R.control_name(3), f'{rn} · control 3', 'B25: no ask keeps the old control name')
        eq(R.control_name(7, 'fix the login flicker'), f'{rn} · 7 · fix the login flicker',
           'B25: an ask titles the control name, N kept')
        eq(R.control_name(4, 'why does the merge step keep failing on Windows runners today?'),
           f'{rn} · 4 · why does the merge step', 'B25: the title is the first five words')
        t = R.control_title('internationalisation-of-everything ' * 3)
        check(len(t) <= 40, 'B25: the title stays near 40 characters', t)
        eq(R.control_title('supercalifragilistic expialidocious extraordinarily verbose'),
           'supercalifragilistic expialidocious', 'B25: trimmed at a word')
        eq(R.control_name(5, '', ['/t/a.png']), f'{rn} · 5 · screenshot', 'B25: an image-only ask is a screenshot')
        eq(R.control_title('look at this:', ['/t/a.png']), 'look at this', 'B25: trailing punctuation dropped')
        with mock.patch.object(R, 'remote_on', lambda: True):
            ca = R.control_argv(6, 'sid', False, ask='fix the login flicker\n\nplease', images=['/t/a.png'])
            eq(ca[ca.index('--remote-control') + 1], f'{rn} · 6 · fix the login flicker please',
               'B25: control --ask is on Remote Control under the titled name')
            ca = R.control_argv(6, 'sid', False)
            eq(ca[ca.index('--remote-control') + 1], f'{rn} · control 6', 'B25: without an ask, the old name')
        from agent_runner.guide import RUNNER_BRIEF
        check('--image' not in RUNNER_BRIEF and '--file' not in RUNNER_BRIEF, 'the feed brief leaves images to control --new', RUNNER_BRIEF)
        rb = RUNNER_BRIEF.format(cmd='run', repo='r', answer='')
        check('start it again the same way and output nothing at all' in rb and 'expires' in rb
              and 're-armed' in rb and 'nothing to repost' in rb,
              'B48: the standing feed brief says to re-arm the Monitor silently', rb)
        with tempfile.TemporaryDirectory() as tdir:
            tr = Path(tdir, 'feed.jsonl')
            hum = lambda *c: {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'content': list(c)}}
            pics = lambda *p: {'type': 'attachment', 'attachment': {'type': 'inlined_image_paths', 'paths': list(p)}}
            note = {'type': 'user', 'origin': {'kind': 'task-notification'}, 'message': {'content': '<task-notification>x'}}
            res = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}
            write = lambda *es: tr.write_text(''.join(json.dumps(e) + '\n' for e in es))
            sid = '12345678-1234-1234-1234-123456789abc'
            with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, a[-1])), \
                    mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
                    mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': ''}):
                Path(tdir, 'feed.sid').write_text(sid + '\n')
                write(hum({'type': 'text', 'text': 'old'}), pics('/u/old.png'),
                      hum({'type': 'image'}, {'type': 'image'}, {'type': 'text', 'text': 'look'}),
                      pics('/u/a.png', '/u/b.png'), note, res)
                eq(R.feed_files(), ['/u/a.png', '/u/b.png'],
                   'control --new --ask passes on the images of the message being handed on')
                write(hum({'type': 'image'}), pics('/u/a.png'), res, hum({'type': 'text', 'text': 'and this?'}))
                eq(R.feed_files(), [], 'a later text-only message forwards no earlier images')
                src = '/tmp/claude-1000/p/7479c552/images/1.png'
                meta = lambda t: {'type': 'user', 'isMeta': True, 'origin': {'kind': 'human'},
                                  'message': {'content': [{'type': 'text', 'text': t}]}}
                write(hum({'type': 'text', 'text': 'old'}), meta('[Image: source: /u/old.png]'),
                      hum({'type': 'image'}, {'type': 'text', 'text': 'see this'}),
                      meta(f'[Image: source: {src}]'), pics(src), res)
                eq(R.feed_files(), [src], 'B24: an isMeta [Image: source: PATH] companion is passed on, deduped')
                write(hum({'type': 'image'}, {'type': 'text', 'text': 'see'}), meta(f'[Image: source: {src}]'),
                      res, hum({'type': 'text', 'text': 'and this?'}))
                eq(R.feed_files(), [], 'B24: a later text-only message forwards no companion image')
                fil = lambda p: {'type': 'attachment', 'attachment': {'type': 'file', 'filename': p}}
                zp, ip = '/h/.claude/uploads/s/d6c7a610-app.zip', '/h/.claude/uploads/s/9a72958e-shot.png'
                summ = {'type': 'user', 'isCompactSummary': True, 'message': {'content': 'continued'}}
                write(hum({'type': 'text', 'text': 'old'}), fil('/u/old.txt'),
                      hum({'type': 'image'}, {'type': 'text', 'text': f'@"{zp}" sign it'}), fil(zp), pics(ip), res,
                      summ, fil(zp), fil('/repo/memory/x.md'))
                eq(R.feed_files(), [zp, ip], 'B30: a file attachment and an image are both passed on, in order; '
                   'files re-read after a compaction are not')
                write(hum({'type': 'text', 'text': 'sign it'}), fil(zp), res, hum({'type': 'text', 'text': 'and?'}))
                eq(R.feed_files(), [], 'B30: a later text-only message forwards no earlier file')
                write(hum({'type': 'image'}, {'type': 'image'}, {'type': 'text', 'text': 'look'}), res)
                got, lost, _ = R.feed_scan()
                eq((got, lost), ([], 2), 'images shown with no recorded path are counted (Claude Code drift)')
                check('send the picture(s) here again' in R.image_drift_note(2, '2.1.400')
                      and '2.1.400' in R.image_drift_note(2, '2.1.400') and R.image_drift_note(0, 'x') == '',
                      'the new control session is told the pictures were lost and why')
                write(hum({'type': 'image'}, {'type': 'text', 'text': 'x'}), meta('[Image: source: /u/d.png]'),
                      pics('/u/d.png'))
                eq(R.feed_scan()[1], 0, 'an image recorded both ways is not counted as lost')
                import contextlib
                import io
                opened = []

                def new_window(*a, **k):
                    opened.append(a)
                    return subprocess.CompletedProcess(a, 0, '%9\n' if a[0] == 'new-window' else '', '')
                late = lambda: (R.time.sleep(0.6), tr.write_text(tr.read_text() + ''.join(json.dumps(e) + '\n' for e in (
                    hum({'type': 'image'}, {'type': 'text', 'text': 'how many have "merged"?'}),
                    meta(f'[Image: source: {src}]')))))
                quiet = contextlib.redirect_stdout(io.StringIO())
                with mock.patch.object(R, 'tmux', new_window), mock.patch.object(R, 'control_live', lambda n: None), \
                        mock.patch.object(R, 'control_new_session', lambda: 'ar-proj'), \
                        mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
                        mock.patch.object(R, 'remote_on', lambda: False):
                    write(hum({'type': 'text', 'text': 'older, text only'}), res)
                    th = R.threading.Thread(target=late)
                    th.start()
                    with quiet:
                        rc = R.control_new(9, ask='how many have merged?')
                    th.join()
                    cmd = next(c for c in opened if c[0] == 'new-window')[-1]
                    check(rc == 0 and src in cmd and 'could not be passed on' not in cmd,
                          'B46: a photo whose message reaches the feed transcript just after control --new starts '
                          'is still passed on', cmd)
                    opened.clear()
                    t0 = time.monotonic()
                    with contextlib.redirect_stdout(io.StringIO()):
                        rc = R.control_new(9, ask='how many have merged?')
                    took = time.monotonic() - t0
                    cmd = next(c for c in opened if c[0] == 'new-window')[-1]
                    check(rc == 0 and took < 1 and src in cmd, 'B46: no wait once the transcript holds the message',
                          took)
                    # B57: the message (3 images) lands well after FEED_WAIT (8 s in the field, scaled down here)
                    shots = [f'/tmp/claude-1000/p/7479c552/images/{i}.png' for i in (1, 2, 3)]
                    later = lambda: (R.time.sleep(1.2), tr.write_text(tr.read_text() + ''.join(
                        json.dumps(e) + '\n' for e in (hum({'type': 'image'}, {'type': 'image'}, {'type': 'image'},
                                                           {'type': 'text', 'text': 'fix these three'}),
                                                       pics(*shots)))))
                    write(hum({'type': 'text', 'text': 'older'}), pics('/u/old.png'), res)
                    opened.clear()
                    th = R.threading.Thread(target=later)
                    th.start()
                    with quiet, mock.patch.object(R, 'FEED_WAIT', 0.3):
                        rc = R.control_new(9, ask='fix these three')
                    cmd = next(c for c in opened if c[0] == 'new-window')[-1]
                    check(rc == 0 and f'--feed-sid {sid}' in cmd and '/u/old.png' not in cmd
                          and not any(s in cmd for s in shots),
                          'B57: a message not in the transcript after FEED_WAIT: the new session waits for it '
                          "itself (--feed-sid), and the previous message's files are not taken", cmd)
                    ask2, files = R.control_late_files('fix these three', [], sid, wait=10)
                    th.join()
                    eq((ask2, files), ('fix these three', shots),
                       'B57: control N --feed-sid waits for the late message and gets --file for each image')
                    ask2, files = R.control_late_files('something never written', ['/u/x.png'], sid, wait=0.3)
                    check(files == ['/u/x.png'] and 'could not read them' in ask2
                          and ask2.startswith('something never written'),
                          'B57: when the message never shows, the first message says attachments may be missing', ask2)
                    eq(R.control_late_files('hi', [], '', wait=5), ('hi', []),
                       'B57: no feed transcript to read: no wait, no note')
                write(hum({'type': 'image'}), pics('/u/c.png'))
                Path(tdir, 'feed.sid').unlink()
                eq(R.feed_files(), [], 'no feed.sid and no session env: nothing')
                with mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}):
                    eq(R.feed_files(), ['/u/c.png'], 'without feed.sid the calling session is read (B22)')
        test_feed_forward()
        test_feed_handoff_b74()
        test_feed_sid_from_record_b83()
        h = run(repo, 'control', '--help')
        check('--image' in h.stdout and '--file' in h.stdout, 'control --file (alias --image) is an option',
              h.stdout)
        check('--forward' in h.stdout and '--ask' not in h.stdout, 'B72: --forward is shown, --ask is hidden',
              h.stdout)
        eq(run(repo, 'since', '--follow', '--keep-mark', '--help').returncode, 0, 'since --keep-mark is an option')
    finally:
        if keep is None:
            notes.unlink(missing_ok=True)
        else:
            notes.write_text(keep, encoding='utf-8')
        if keep_ev is None:
            evf.unlink(missing_ok=True)
        else:
            evf.write_text(keep_ev, encoding='utf-8')
        R.since_mark_file().unlink(missing_ok=True)


def test_feed_forward():
    print('B72: the feed hands a message on with control --new --forward: the text comes word for word from the '
          'feed transcript, never through a shell')
    import contextlib
    import io
    msg = ('please check `git log | head -c 0` and "this" \'too\'\n\n$(rm -rf ~) ${HOME} \\n back\\slash; '
           'echo $((1+1)) && exit\n  indented line\t tab')
    sid = '12345678-1234-1234-1234-123456789abc'
    with tempfile.TemporaryDirectory() as tdir:
        tr = Path(tdir, 'feed.jsonl')
        hum = lambda text, uid: {'type': 'user', 'uuid': uid, 'origin': {'kind': 'human'},
                                 'message': {'content': [{'type': 'text', 'text': text}]}}
        call = lambda cmd: {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': cmd}}]}}
        res = {'type': 'user', 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}
        pics = lambda *p: {'type': 'attachment', 'attachment': {'type': 'inlined_image_paths', 'paths': list(p)}}
        write = lambda *es: tr.write_text(''.join(json.dumps(e) + '\n' for e in es))
        add = lambda *es: tr.write_text(tr.read_text() + ''.join(json.dumps(e) + '\n' for e in es))
        opened = []

        def tm(*a, **k):
            opened.append(a)
            return subprocess.CompletedProcess(a, 0, '%9\n' if a[0] == 'new-window' else '', '')
        with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
                mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
                mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}), \
                mock.patch.object(R, 'tmux', tm), mock.patch.object(R, 'control_live', lambda n: None), \
                mock.patch.object(R, 'control_new_session', lambda: 'ar-proj'), \
                mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
                mock.patch.object(R, 'remote_on', lambda: False):
            mon = {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'Monitor', 'input': {'command': 'run since --follow --keep-mark'}},
                {'type': 'tool_use', 'name': 'PushNotification', 'input': {'message': 'x'}}]}}
            write(hum('status', 'u1'), call('run status'), res,
                  hum(msg, 'u2'), pics('/u/shot.png'), mon, call('run since --follow --keep-mark'),
                  call('run control --new --forward'))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = R.control_new(9, forward=True)
            cmd = next(c for c in opened if c[0] == 'new-window')[-1]
            argv = R.shlex.split(cmd)
            check(rc == 0 and '--ask-file' in argv and '--ask' not in argv and 'rm -rf' not in cmd
                  and 'head -c' not in cmd and '/u/shot.png' in argv, 'B72: the command holds no word of the '
                  'message, only the file it is in and the attached image', cmd)
            text = R.read_ask_file(argv[argv.index('--ask-file') + 1])
            eq(text, msg, 'B72: quotes, backticks, $() and newlines reach the new control session unchanged')
            check(not Path(tdir, 'control9.ask').exists(), 'B72: the message file is removed once read')
            first = R.control_argv(9, 'sid', False, ask=text, images=['/u/shot.png'])[1]
            check(first.startswith(msg) and '"/u/shot.png"' in first, 'B72: it is the first message, word for word',
                  first)
            eq(R.feed_pending(sid)[2], False, 'B72: a message handed on once is not handed on again')
            # the feed's transcript lags (B46): the feed's latest message there is one it answered itself
            write(hum('status', 'u1'), call('run status'), res)
            opened.clear()
            with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(R, 'FEED_WAIT', 0.3):
                R.control_new(9, forward=True)
            argv = R.shlex.split(next(c for c in opened if c[0] == 'new-window')[-1])
            check('--forward' in argv and argv[argv.index('--feed-sid') + 1] == sid and '--ask-file' not in argv
                  and 'status' not in argv, 'B72: a message not in the transcript yet is not guessed at: control N '
                  'waits for it itself', argv)
            th = threading.Thread(target=lambda: (time.sleep(0.6), add(hum(msg, 'u3'),
                                                                       call('run control --new --forward'))))
            th.start()
            with contextlib.redirect_stdout(io.StringIO()):
                got = R.forward_late(9, sid, wait=10)
            th.join()
            eq(got, msg, 'B72: control N --forward --feed-sid takes the late message, word for word')
            with contextlib.redirect_stdout(io.StringIO()):
                got = R.forward_late(9, sid, wait=0.3)
            eq(got, R.feed_lost_note(), 'B72: a message that never shows opens the session saying so, not with an '
               'older one')


def test_feed_sid_from_record_b83():
    print('B83: a feed started before B15 (no feed.sid, no sid in its record) whose Bash has no '
          'CLAUDE_CODE_SESSION_ID: the hand-off finds its session through the record and Claude Code\'s '
          'sessions/<pid>.json, and logs it')
    sid = '3d37d373-b242-4ef6-8ad3-2e052fcbb51e'
    ask = 'is there a better way to handle this situation?'
    shot = f'/tmp/claude-1000/-home-ryha-repos-agent-runner/{sid}/images/1.png'
    with tempfile.TemporaryDirectory() as tdir:
        remote, sessions = Path(tdir, 'remote'), Path(tdir, 'sessions')
        remote.mkdir()
        sessions.mkdir()
        tr = Path(tdir, 'feed.jsonl')
        meta = {'version': '2.1.329', 'sessionId': sid}
        tr.write_text(''.join(json.dumps(e) + '\n' for e in (
            {'type': 'user', 'uuid': 'u1', 'origin': {'kind': 'human'}, 'imagePasteIds': [1], **meta,
             'message': {'role': 'user', 'content': [
                 {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'iVBOR'}},
                 {'type': 'text', 'text': ask}]}},
            {'type': 'user', 'isMeta': True, 'uuid': 'm1', **meta,
             'message': {'role': 'user', 'content': [{'type': 'text', 'text': f'[Image: source: {shot}]'}]}})))
        pid = os.getpid()
        start = R.plat.started(pid)
        rec = {'kind': 'feed', 'name': 'proj · runner', 'pid': pid, 'run': '1:2', 'sid': ''}
        if start is not None:
            rec['start'] = start
        Path(remote, f'feed-{pid}.json').write_text(json.dumps(rec))
        env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_CODE_SESSION_ID'}
        with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
                mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid else None), \
                mock.patch.object(R, 'claude_sessions_dir', lambda: sessions), \
                mock.patch.dict(os.environ, env, clear=True):
            eq(R.feed_sid(), '', 'B83: no sessions/<pid>.json for the feed yet: still no session')
            Path(sessions, f'{pid}.json').write_text(json.dumps(
                {'pid': pid, 'sessionId': sid, 'procStart': start or '', 'kind': 'interactive'}))
            eq(R.feed_sid(), sid, 'B83: the live feed record\'s pid names its session in sessions/<pid>.json')
            eq(R.feed_wait(ask, 2), (True, [shot], 0, '2.1.329'), 'B83: so the screenshot is handed on')
            last = Path(remote, R.FEED_LOG).read_text().splitlines()[-1]
            check(f'sid {sid} (feed record)' in last and shot in last, 'B83: the log says the id came from the '
                  'feed record', last)
            if start is not None:
                Path(sessions, f'{pid}.json').write_text(json.dumps({'pid': pid, 'sessionId': sid,
                                                                     'procStart': f'{start}9'}))
                eq(R.feed_sid(), '', 'B83: a sessions file of another process with that pid is not the feed\'s')
            Path(remote, f'feed-{pid}.json').write_text(json.dumps({**rec, 'sid': sid}))
            eq(R.feed_sid(), sid, 'B83: a sid in the record itself is used first')
            Path(remote, 'feed.sid').write_text('11111111-2222-3333-4444-555555555555\n')
            eq(R.feed_sid(), '11111111-2222-3333-4444-555555555555', 'B83: feed.sid still comes before the record')


def test_feed_handoff_b74():
    print('B74: a phone screenshot handed on from the feed reaches the new control session (--file), replayed as '
          'Claude Code 2.1.329 writes it: the message, then its isMeta companion a moment later')
    import contextlib
    import io
    sid = '3d37d373-b242-4ef6-8ad3-2e052fcbb51e'
    ask = 'this title session is out of date, should we update when the heading changes?'
    shot = f'/tmp/claude-1000/-home-ryha-repos-agent-runner/{sid}/images/6.png'
    with tempfile.TemporaryDirectory() as tdir:
        tr = Path(tdir, 'feed.jsonl')
        meta = {'version': '2.1.329', 'sessionId': sid, 'userType': 'external', 'entrypoint': 'cli'}
        old = {'type': 'user', 'uuid': 'u0', 'origin': {'kind': 'human'}, **meta, 'message': {'role': 'user', 'content': [
            {'type': 'text', 'text': 'agent runner task failed? do we check and handle those automatically?'}]}}
        call = lambda cmd, uid='a0': {'type': 'assistant', 'uuid': uid, **meta, 'message': {'content': [
            {'type': 'tool_use', 'name': 'Bash', 'input': {'command': cmd}}]}}
        res = {'type': 'user', 'uuid': 'r0', **meta, 'message': {'content': [{'type': 'tool_result', 'content': 'ok'}]}}
        notif = {'type': 'user', 'uuid': 'n0', 'origin': {'kind': 'task-notification'}, **meta,
                 'message': {'role': 'user', 'content': '<task-notification>\nMonitor event</task-notification>'}}

        def msg(text: str, image: bool = True, uid: str = 'f40a'):
            c = ([{'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'iVBOR'}}]
                 if image else []) + [{'text': text, 'type': 'text'}]
            return {'parentUuid': 'p', 'isSidechain': False, 'promptId': 'bc2f', 'type': 'user', 'uuid': uid,
                    'message': {'role': 'user', 'content': c}, 'imagePasteIds': [6], 'origin': {'kind': 'human'},
                    'promptSource': 'queued', **meta}
        companion = [
            {'type': 'attachment', 'uuid': 'dc9e', **meta, 'attachment': {
                'type': 'total_tokens_reminder', 'text': '<total_tokens>15000000 tokens left</total_tokens>'}},
            {'type': 'user', 'isMeta': True, 'turnCompanion': True, 'uuid': '1ea5', **meta,
             'message': {'role': 'user', 'content': [{'type': 'text', 'text': f'[Image: source: {shot}]'}]}},
            {'type': 'api-request-blob', 'sessionId': sid, 'message': {'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'data': 'iVBOR'}}, {'type': 'text', 'text': ask},
                {'type': 'text', 'text': f'[Image: source: {shot}]'}]}},
            {'type': 'last-prompt', 'lastPrompt': ask, 'leafUuid': '1ea5', 'sessionId': sid}]
        lines = lambda *es: ''.join(json.dumps(e) + '\n' for e in es)
        write = lambda *es: tr.write_text(lines(*es))
        add = lambda *es: tr.write_text(tr.read_text() + lines(*es))
        later = lambda s, *es: threading.Thread(target=lambda: (time.sleep(s), add(*es)))
        opened = []

        def tm(*a, **k):
            opened.append(a)
            return subprocess.CompletedProcess(a, 0, '%9\n' if a[0] == 'new-window' else '', '')

        def new(**kw):
            opened.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                rc = R.control_new(9, **kw)
            return rc, R.shlex.split(next(c for c in opened if c[0] == 'new-window')[-1])
        with mock.patch.object(R.C, 'notes', lambda *a: Path(tdir, *a)), \
                mock.patch.object(R, 'transcript', lambda s: str(tr) if s == sid and tr.exists() else None), \
                mock.patch.dict(os.environ, {'CLAUDE_CODE_SESSION_ID': sid}), \
                mock.patch.object(R, 'tmux', tm), mock.patch.object(R, 'control_live', lambda n: None), \
                mock.patch.object(R, 'control_new_session', lambda: 'ar-proj'), \
                mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
                mock.patch.object(R, 'remote_on', lambda: False):
            Path(tdir, 'remote').mkdir()  # C.notes makes it; the stand-in does not
            base = (old, call('run control --new --ask "agent runner task failed?"'), res, notif)
            # the message lands just after control --new starts, its companion a few tenths of a second later
            write(*base)
            th = threading.Thread(target=lambda: (time.sleep(0.4), add(
                {'type': 'queue-operation', 'operation': 'dequeue'}, msg(ask)), time.sleep(0.6), add(*companion)))
            th.start()
            rc, argv = new(ask=ask)
            th.join()
            check(rc == 0 and shot in argv and argv[argv.index(shot) - 1] == '--file' and '--feed-sid' not in argv
                  and 'could not be passed on' not in ' '.join(argv),
                  'B74: message then isMeta companion in steps: the control session still gets --file', argv)
            log = Path(tdir, 'remote', R.FEED_LOG).read_text()
            check(sid in log and '(env)' in log and '-> found, 1 file(s)' in log and shot in log
                  and 'with 1 image(s)' in log, 'B74: the hand-off log says what feed_wait saw', log)
            # the message is in, its companion not yet: one image shown and no path is waited for
            write(*base, msg(ask))
            th = later(0.5, *companion)
            th.start()
            rc, argv = new(ask=ask)
            th.join()
            check(shot in argv, 'B74: a message whose companion is not written yet waits for it', argv)
            # imagePasteIds says an image came even when the entry holds no image block yet (shown was 0)
            write(*base, msg(ask, image=False))
            th = later(0.5, *companion)
            th.start()
            rc, argv = new(ask=ask)
            th.join()
            check(shot in argv, 'B74: imagePasteIds counts as an image shown, so its path is waited for', argv)
            # the feed's transcript cannot be found at first: not "found, no files" at once (said None)
            tr.unlink()
            th = threading.Thread(target=lambda: (time.sleep(0.5), write(*base, msg(ask), *companion)))
            th.start()
            rc, argv = new(ask=ask)
            th.join()
            check(shot in argv, 'B74: a feed transcript not there yet is waited for, never taken as no files', argv)
            tr.unlink()
            with mock.patch.object(R, 'FEED_WAIT', 0.3):
                rc, argv = new(ask=ask)
            check('--feed-sid' in argv, 'B74: a feed transcript still missing after FEED_WAIT: control N waits for it',
                  argv)
            write(*base, msg(ask), *companion)
            eq(R.control_late_files(ask, [], sid, wait=5), (ask, [shot]), 'B74: control N --feed-sid gets it too')
            last = Path(tdir, 'remote', R.FEED_LOG).read_text().splitlines()[-1]
            check('control N --feed-sid:' in last and '(--feed-sid)' in last, 'B74: the log names that step and '
                  'where its feed session id came from', last)
            eq(R.feed_wait(ask, 5, ''), (True, [], 0, ''), 'B74: no feed session at all: nothing to wait for')
            # a stale match: an earlier short message held in the new ask is not the message being handed on
            write(old, res, {**msg('openmx', image=False, uid='o1'), 'imagePasteIds': []}, res)
            with mock.patch.object(R, 'FEED_WAIT', 0.3):
                rc, argv = new(ask='openmx is failing again')
            check('--feed-sid' in argv and argv[argv.index('--feed-sid') + 1] == sid,
                  'B74: an earlier short message inside the new ask is not taken for it', argv)
            check(R.same_words('how many have "merged"?', 'how many have merged') and
                  R.same_words(ask + ' thanks', ask) and not R.same_words('openmx', 'openmx is failing again'),
                  'B74: same_words still allows quoting and a long message trimmed or added to')
            # B72's --forward passes images the same way: text from the transcript, the companion a moment later
            write(*base, msg(ask), call('run control --new --forward', 'a1'))
            th = later(0.5, *companion)
            th.start()
            rc, argv = new(forward=True)
            th.join()
            check(rc == 0 and '--ask-file' in argv and shot in argv and argv[argv.index(shot) - 1] == '--file',
                  'B74: control --new --forward passes the screenshot as --file too', argv)


def test_board_follows_run(repo: Path, tmp: Path):
    print('the board follows the run: it ends when the run does (force stop, crash, plain stop), and the feed '
          'holds while the run is idle, or paused or stopping with nothing running')
    import contextlib
    import io
    R.init(repo)
    state = R.C.notes('STATE')
    keep = state.read_text(encoding='utf-8') if state.exists() else None
    notes = R.C.notes('run.log')
    keep_log = notes.read_text(encoding='utf-8') if notes.exists() else None
    try:
        # STATE carries what the hold reads
        saved = R.IDLE[0], R.PAUSED[0]
        R.IDLE[0], R.PAUSED[0] = True, False
        try:
            R.write_state({})
        finally:
            R.IDLE[0], R.PAUSED[0] = saved
        st = json.loads(state.read_text(encoding='utf-8'))
        eq((st['idle'], st['paused'], st['stopping']), (True, False, False), 'STATE says idle, paused, stopping')

        def held(up=True, **st):
            state.write_text(json.dumps({'running': {}, 'merging': [], **st}), encoding='utf-8')
            with mock.patch.object(R, 'run_up', lambda: up):
                return R.board_held()
        check(held(idle=True), 'idle: the feed holds')
        check(held(paused=True), 'paused with nothing running: it holds')
        check(held(stopping=True), 'stopping with nothing running: it holds')
        check(not held(paused=True, running={'1': 'F5'}), 'paused while a task runs: what lands still shows')
        check(not held(stopping=True, merging=['F5']), 'stopping while a merge runs: still shows')
        check(not held(), 'a working run: no hold')
        check(not held(up=False, idle=True), 'no run up: a stale STATE holds nothing')

        # the feed's stream: nothing while held, then what was logged meanwhile once work resumes
        hold = [True]
        stamp = R.dt.datetime.now().replace(microsecond=0).isoformat()
        def add():  # F41: the event the merge logs
            with R.events_file().open('a', encoding='utf-8') as fh:
                fh.write(json.dumps({'time': stamp, 'kind': R.EV_LANDED, 'id': 'F5', 'text': 'F5: merged, ticked'}) + '\n')
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.touch()
        threading.Timer(0.3, add).start()
        threading.Timer(1.2, lambda: hold.__setitem__(0, False)).start()
        out, seen = io.StringIO(), []
        def watch():
            seen.append(out.getvalue().count('landed: F5'))
        threading.Timer(0.9, watch).start()
        with contextlib.redirect_stdout(out):
            R.follow(poll=0.1, until=time.monotonic() + 2.5, mark=False, hold=lambda: hold[0])
        check(seen == [0], 'held: the landed line is not printed while the run is idle', out.getvalue())
        check('landed: F5' in out.getvalue(), 'work resumes: it prints what was logged meanwhile', out.getvalue())

        # the text board ends once its run has
        dead = subprocess.Popen([sys.executable, '-c', 'pass'])
        dead.wait()
        t0 = time.monotonic()
        with contextlib.redirect_stdout(io.StringIO()):
            R.follow(poll=0.1, until=time.monotonic() + 10, mark=False, end=lambda: not R.plat.alive(dead.pid))
        check(time.monotonic() - t0 < 5, 'the text board ends when its run is gone')

        # the runner feed ends with the run: a force stop or a crash ends the run's process
        pidf = tmp / 'feed.pid'
        fake = [sys.executable, '-c', f'import os,time; open({str(pidf)!r},"w").write(str(os.getpid())); '
                                      'time.sleep(60)']
        runp = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        threading.Timer(1.0, runp.kill).start()
        t0 = time.monotonic()
        with mock.patch.object(R, 'feed_argv', lambda: fake):
            rc = R.board_feed(runp.pid, poll=0.1)
        runp.wait()
        eq(rc, 0, 'the board ends once its run is gone')
        check(time.monotonic() - t0 < 10, 'and promptly')
        pid = int(pidf.read_text())
        check(not R.plat.alive(pid), "the feed's process is gone after the run is (offline in the apps)", pid)

        # the feed ending on its own ends the board too (keep_board opens it again while the run is up)
        with mock.patch.object(R, 'feed_argv', lambda: [sys.executable, '-c', 'raise SystemExit(3)']):
            eq(R.board_feed(os.getpid(), poll=0.1), 3, 'the feed exiting ends the board with its code')
        eq(run(repo, 'since', '--feed').returncode, 2, '--feed without --board is refused')
    finally:
        for f, k in ((state, keep), (notes, keep_log)):
            if k is None:
                f.unlink(missing_ok=True)
            else:
                f.write_text(k, encoding='utf-8')


def test_remote_sweep(repo: Path, tmp: Path):
    print('B12: a stop or a restart ends the Remote Control processes an earlier run recorded (SIGTERM, so Claude '
          'Code archives their entries), never kills one, and leaves the current run\'s, control sessions and '
          'unrecorded sessions alone')
    import contextlib
    import io
    R.init(repo)
    notes = R.C.notes('run.log')
    keep_log = notes.read_text(encoding='utf-8') if notes.exists() else None
    procs = []

    def spawn(ignore_term=False):
        ready = tmp / f'rc-ready-{len(procs)}'
        code = ('import os,signal,time\n' + ('signal.signal(signal.SIGTERM, signal.SIG_IGN)\n' if ignore_term else '')
                + f'open({str(ready)!r},"w").close()\ntime.sleep(60)\n')
        p = subprocess.Popen([sys.executable, '-c', code])
        procs.append(p)
        end = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < end:
            time.sleep(0.05)
        return p

    def reap(p):  # the test's children: a dead one stays a zombie until waited for
        threading.Thread(target=p.wait, daemon=True).start()

    try:
        d = R.C.notes(R.REMOTE_DIR)
        if d.is_dir():
            for f in d.glob('*.json'):
                f.unlink()
        earlier = subprocess.Popen([sys.executable, '-c', 'pass'])  # the earlier run: gone
        earlier.wait()
        me = os.getpid()
        old_feed, old_server, old_c2, cur_feed, stranger, stubborn = (spawn(), spawn(), spawn(), spawn(), spawn(),
                                                                        spawn(ignore_term=True))
        for p in (old_feed, old_server, old_c2, cur_feed, stranger, stubborn):
            reap(p)
        R.rc_record('feed', 'repo · runner', old_feed.pid, earlier.pid)
        R.rc_record('server', 'repo · control', old_server.pid, earlier.pid)
        R.rc_record('control', 'repo · control 2', old_c2.pid, earlier.pid)
        R.rc_record('feed', 'repo · runner', cur_feed.pid, me)
        R.rc_record('feed', 'repo · runner (stuck)', stubborn.pid, earlier.pid)
        dead = subprocess.Popen([sys.executable, '-c', 'pass'])
        dead.wait()
        R.rc_forget(R.rc_record('feed', 'repo · killed feed', dead.pid, earlier.pid), killed=True)

        # a restart that adopts the control server: the earlier feed ends, everything else stays
        with mock.patch.object(R.plat, 'terminate', wraps=R.plat.terminate) as term:
            ended, left = R.rc_sweep(me, keep_server=True, wait=3)
        sent = {c.args[0] for c in term.call_args_list}
        eq(sorted(ended), ['repo · runner'], "the earlier run's feed is ended")
        eq(left, ['repo · runner (stuck)'], 'one that ignores SIGTERM is left running, not killed')
        eq(sent, {old_feed.pid, stubborn.pid}, 'SIGTERM went to the earlier run\'s feeds only')
        time.sleep(0.3)
        check(not R.plat.alive(old_feed.pid), 'the earlier feed is gone (its teardown archives its entry)')
        check(R.plat.alive(stubborn.pid), 'never SIGKILLed: a killed session would stay listed')
        check(R.plat.alive(old_server.pid), 'the control server this run adopts is left up (no new entry)')
        check(R.plat.alive(old_c2.pid), "an earlier run's control session is the person's: left up")
        check(R.plat.alive(cur_feed.pid), "the current run's feed is left alone")
        check(R.plat.alive(stranger.pid), 'a session nobody recorded is never touched')
        kinds = sorted((s['kind'], s['name']) for s in R.rc_records())
        check(('feed', 'repo · killed feed') not in kinds and ('feed', 'repo · runner') in kinds and
              len([k for k in kinds if k[1] == 'repo · runner']) == 1, 'gone records are dropped', kinds)
        has(notes.read_text(encoding='utf-8'), '"repo · killed feed" was killed before it could archive itself',
            'a killed one is named as possibly still listed')

        # a restart without the server (remote now off): the earlier server ends too
        ended, _ = R.rc_sweep(me, keep_server=False, wait=3)
        eq(ended, ['repo · control'], "the earlier run's control server is ended when this run will not adopt it")

        # the stop: the current run's own feed ends as well; control sessions stay
        with mock.patch.object(R, 'RC_ENDING', [False]):
            with mock.patch.object(R, 'rc_sweep', lambda *a, **k: R_sweep(*a, **{**k, 'wait': 3})):
                R.rc_sweep_stop()
            check(R.RC_ENDING[0], 'the stop keeps the board from opening a new feed')
        time.sleep(0.3)
        check(not R.plat.alive(cur_feed.pid), "the stop ends the run's own feed")
        check(R.plat.alive(old_c2.pid) and R.plat.alive(stranger.pid), 'control sessions and strangers stay up')

        # the feed's guard records its claude and drops the record once it ends
        fake = [sys.executable, '-c', 'import time; time.sleep(0.5)']
        seen = []
        orig = R.rc_record
        with mock.patch.object(R, 'feed_argv', lambda: fake), \
                mock.patch.object(R, 'rc_record', lambda *a, **k: seen.append(a) or orig(*a, **k)):
            with contextlib.redirect_stdout(io.StringIO()):
                R.board_feed(me, poll=0.1)
            R.board_feed(0, poll=0.1)
        eq([a[0] for a in seen], ['feed'], 'the run\'s feed is recorded; one started by hand is not')
        check(not any(s['kind'] == 'feed' and s['pid'] == seen[0][2] for s in R.rc_records()),
              'and its record goes when it ends')
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        d = R.C.notes(R.REMOTE_DIR)
        if d.is_dir():
            for f in d.glob('*.json'):
                f.unlink()
        if keep_log is None:
            notes.unlink(missing_ok=True)
        else:
            notes.write_text(keep_log, encoding='utf-8')


R_sweep = R.rc_sweep


def test_feed_resume(repo: Path, tmp: Path):
    print('B15: a restart that is not a stop keeps the runner feed (an upgrade\'s exec keeps the run\'s key, so '
          'its feed is left up) or resumes the same Claude session; a real stop ends it and the next is fresh')
    import contextlib
    import io
    R.init(repo)
    me = os.getpid()
    sidf = R.C.notes(R.REMOTE_DIR, R.FEED_SID)
    argf = tmp / 'feed-argv.json'
    fake = [sys.executable, '-c', f'import json,sys,time; json.dump(sys.argv[1:], open({str(argf)!r},"w")); '
                                  'time.sleep(0.3)']

    def start(argv=fake, run_pid=me):
        argf.unlink(missing_ok=True)
        with mock.patch.object(R, 'feed_argv', lambda: argv), contextlib.redirect_stderr(io.StringIO()):
            rc = R.board_feed(run_pid, poll=0.1)
        return rc, (json.loads(argf.read_text()) if argf.exists() else [])

    keeper = None
    try:
        sidf.unlink(missing_ok=True)
        seen = []
        orig = R.rc_record
        with mock.patch.object(R, 'rc_record', lambda *a, **k: seen.append(a) or orig(*a, **k)):
            _, a1 = start()
        check('--session-id' in a1 and '--resume' not in a1, 'the first feed starts a session of its own', a1)
        sid = a1[a1.index('--session-id') + 1]
        eq(sidf.read_text().strip(), sid, 'its session id is kept in <notes>/remote/')
        eq(seen[0][4] if len(seen[0]) > 4 else '', sid, 'and recorded with the feed')

        # an upgrade restart execs in place: same pid and start, so the same run key and the same board
        keeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        R.rc_record('feed', 'repo · runner', keeper.pid, me, sid)
        eq(R.run_key(me), R.run_key(os.getpid()), 'the run keeps its key across exec')
        with contextlib.redirect_stdout(io.StringIO()):
            ended, _ = R.rc_sweep(me, wait=1)
        eq(ended, [], "the restarted run's sweep leaves its live feed up (no new entry)")
        check(R.plat.alive(keeper.pid), 'the feed process is still the same one')
        check(R.board_command().endswith(f'--run-pid {me}'), 'and its board command is unchanged')

        # a feed the board has to start again (window replaced, feed exited, run started again) resumes
        _, a2 = start()
        check(a2[a2.index('--resume') + 1] == sid and '--session-id' not in a2,
              'a restarted feed resumes the same session (history and app entry carry on)', a2)
        _, a3 = start(run_pid=0)
        check('--resume' not in a3 and '--session-id' not in a3, 'a feed started by hand is its own', a3)
        eq(sidf.read_text().strip(), sid, 'and leaves the run\'s session alone')

        # a resume that fails at once (its transcript gone): the next start is fresh, not a loop of failures
        rc, _ = start(argv=[sys.executable, '-c', 'raise SystemExit(1)'])
        eq(rc, 1, 'the failed resume ends the board with its code')
        check(not sidf.exists(), 'and forgets the session')
        _, a4 = start()
        check('--session-id' in a4, 'so the next feed starts fresh', a4)

        # a real stop ends the feed and its session: the next run's feed is a new one
        sid = a4[a4.index('--session-id') + 1]
        with mock.patch.object(R, 'RC_ENDING', [False]), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(R, 'rc_sweep', lambda *a, **k: R_sweep(*a, **{**k, 'wait': 3})):
            R.rc_sweep_stop()
        keeper.wait(timeout=10)
        check(not sidf.exists(), 'the stop forgets the feed\'s session')
        check(not R.plat.alive(keeper.pid), 'and ends the feed')
        _, a5 = start()
        check('--session-id' in a5 and a5[a5.index('--session-id') + 1] != sid, 'the next start is a new session', a5)
    finally:
        if keeper and keeper.poll() is None:
            keeper.kill()
        sidf.unlink(missing_ok=True)
        d = R.C.notes(R.REMOTE_DIR)
        if d.is_dir():
            for f in d.glob('*.json'):
                f.unlink()


def test_take_text_and_here(repo: Path):
    print('take "TEXT" --kind: queue and take in one step; --here carries the main checkout\'s edits along')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    r = run(repo, 'take', 'write the q module', '--kind', 'T', '--files', 'q.py')
    eq(r.returncode, 0, f'take TEXT --kind queues and takes: {r.stderr}')
    tid = re.search(r'queued (T\d+)', r.stderr)[1]
    d = R.SLOTS_DIR / f'take-{tid}'
    eq(git(d, 'branch', '--show-current'), f'task/{tid}', 'in a worktree of its own')
    has(git(d, 'show', 'HEAD:plan/TODO.md'), rf'\*\*{tid}\*\* write the q module \| files: q\.py',
        'the new task is on the branch it works on')
    has(r.stdout, rf'take {tid} --merge', 'and it prints the brief')
    eq(run(repo, 'take', tid, '--drop').returncode, 0, 'and it gives back like any take')
    check(run(repo, 'take', 'no kind given').returncode == 1, 'TEXT without --kind is no task id')

    (repo / 'prompt.txt').unlink(missing_ok=True)  # an earlier test's
    (repo / 'a.py').write_text('# a, edited in the main checkout\n', encoding='utf-8')
    (repo / 'new.py').write_text('# a new file\n', encoding='utf-8')
    r = run(repo, 'take', '--here', 'finish the a.py edit', '--kind', 'T', '--files', 'a.py,new.py')
    eq(r.returncode, 0, f'take --here: {r.stderr}')
    tid = re.search(r'queued (T\d+)', r.stderr)[1]
    d = R.SLOTS_DIR / f'take-{tid}'
    eq(git(repo, 'status', '--porcelain'), '', 'the main checkout is left clean')
    eq((d / 'a.py').read_text(), '# a, edited in the main checkout\n', 'the edit is in the worktree')
    check((d / 'new.py').is_file(), 'new files too')
    eq(git(repo, 'stash', 'list'), '', 'and no stash is left behind')
    git(d, 'checkout', '--', '.'), (d / 'new.py').unlink()
    r = run(repo, 'take', tid, '--drop')
    eq(r.returncode, 0, f'drop it: {r.stderr}')

    (repo / 'a.py').write_text('# a, edited again\n', encoding='utf-8')
    name = R.move_edits_aside('W9')
    has((repo / '.runner/run.log').read_text(), rf'to {name} .*take --here', 'moving edits aside names take --here')
    check(name in R.wip_main(), 'the wip/main-checkout branch is listed')
    has(run(repo, 'plan', 'claims').stdout, rf'{name}  main-checkout edits moved aside', '`plan claims` shows it')
    git(repo, 'branch', '-D', name), git(repo, 'stash', 'drop', '-q')


def test_conflicts(repo: Path, tmp: Path):
    print('run: a conflict a join cannot do goes to a fix session; one it gives up on is parked')
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    R.C.run['agent'], R.C.run['build'] = str(agent), 'make quick'
    original_fix_cmd = use_fake_fix_agent(agent)
    os.environ['FAKE_PROMPT'] = str(tmp / 'fix-prompt.txt')
    for n, tid, mode in ((2, 'T3', 'theirs'), (3, 'T6', 'abort')):
        f = 'a.py' if tid == 'T3' else 'c.py'
        d = task_branch(repo, n, tid)
        (d / f).write_text(f'# {tid} version\n', encoding='utf-8')
        r = run(d, 'done', tid, f'{tid}: done')
        check(r.returncode == 0, f'{tid}: done', r.stderr)
        git(d, 'checkout', '-q', '--detach')
        (repo / f).write_text(f'# main version of {f}\n', encoding='utf-8')
        git(repo, 'commit', '-qam', f'main edits {f}')
        os.environ['FAKE_FIX'] = mode
        R.finish(tid, n, 'sid', 'main')
    led = (repo / '.runner/ledger.md').read_text(encoding='utf-8')
    has(led, r'T3: conflicts in a\.py resolved by a fix session', 'T3: the fix session resolved it')
    has((tmp / 'fix-prompt.txt').read_text(), r'run `make quick` \(a build, not the tests\)',
        'with [run] build, the fix session builds before it commits')
    eq((repo / 'a.py').read_text(), '# T3 version\n', 'and its resolution landed on main')
    has(led, r'T6: not merged, parked as wip/T6 — the fix session aborted', 'T6: the fix session gave up, and the ledger says so')
    eq((repo / 'c.py').read_text(), '# main version of c.py\n', 'main is as it was')
    check(git(repo, 'branch', '--list', 'wip/T6') != '' and git(repo, 'branch', '--list', 'task/T6') == '',
          'T6 is parked as wip/T6, so the task can start again')
    check('wip/T6' in remote_branches(tmp), 'and wip/T6 is on the remote')
    check('T6' in [t[0] for t in R.tasks('main')], 'T6 is still open and offered')
    p = R.prompt_for('T6', 1, 2, repo, 'main')
    has(p, r'An earlier attempt .* on wip/T6', 'its next prompt points at the earlier attempt')
    has(p, r'## Task T6', 'and carries the brief')
    os.environ.pop('FAKE_FIX', None)
    os.environ.pop('FAKE_PROMPT', None)
    R.C.run['agent'], R.C.run['build'] = 'claude', ''
    R.fix_cmd = original_fix_cmd


def test_fix_ahead(repo: Path, tmp: Path):
    print('run: a conflict is fixed outside the merge lock, again if the branch moves under it')
    R.init(repo)
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    R.C.run['agent'] = str(agent)
    original_fix_cmd = use_fake_fix_agent(agent)
    original_session = R.fix_session
    locked, moves = [], ['# main again\n']

    def session(prompt, cwd, fh, keep=None, fork=""):
        locked.append(R.MERGE.locked())
        code = original_session(prompt, cwd, fh, keep)
        if moves:  # main touches the same lines while the session worked
            (repo / 'e.py').write_text(moves.pop(), encoding='utf-8')
            git(repo, 'commit', '-qam', 'main edits e.py again')
        return code
    R.fix_session = session
    os.environ['FAKE_FIX'] = 'theirs'
    try:
        commit_on(repo, 'F1', {'e.py': '# F1 version\n'}, 'F1: e')
        (repo / 'e.py').write_text('# main version\n', encoding='utf-8')
        git(repo, 'commit', '-qam', 'main edits e.py')
        eq(R.merge('F1', 'main'), None, 'it lands')
        eq(locked, [False, False], 'two sessions, neither under the merge lock')
        log = (repo / '.runner/run.log').read_text(encoding='utf-8')
        has(log, r'F1: resolving its conflicts with main outside the merge lock, in fix1', 'in a fix worktree')
        has(log, r'F1: conflicts again with the shared branch', 'the second because main moved under the first')
        eq((repo / 'e.py').read_text(), '# F1 version\n', 'its resolution landed')
        eq(git(repo, 'for-each-ref', 'refs/agent-runner/fixed/'), '', 'and its fixed merge ref is gone')
        R.FIX_DIRS.update({1, 2})
        R.C.run['fix_ahead_max'] = 2
        took = []
        t = R.threading.Thread(target=lambda: took.append(R.fix_ahead('F2', 'main')), daemon=True)
        commit_on(repo, 'F2', {'e.py': '# F2 version\n'}, 'F2: e')
        (repo / 'e.py').write_text('# main, third\n', encoding='utf-8')
        git(repo, 'commit', '-qam', 'main edits e.py a third time')
        t.start()
        t.join(1)
        check(t.is_alive(), 'with fix_ahead_max fix worktrees busy, the next fix waits its turn')
        with R.FIX_DIRS_LOCK:
            R.FIX_DIRS.discard(2)
            R.FIX_DIRS_LOCK.notify()
        t.join(30)
        eq((took, sorted(p.name for p in R.SLOTS_DIR.glob('fix*'))), ([None], ['fix1', 'fix2']),
           'then fixes in the freed one: never more worktrees than the cap')
        R.FIX_DIRS.clear()
        R.FIXING.clear()  # F2 went through fix_ahead alone: no merge to end and let go of its files
        git(repo, 'branch', '-D', 'task/F2')
        R.FIXING['F3'] = {'e.py'}  # fixed ahead in e.py, its merge not over yet
        took = []
        t = R.threading.Thread(target=lambda: took.append(R.fix_ahead('F4', 'main')), daemon=True)
        commit_on(repo, 'F4', {'e.py': '# F4 version\n'}, 'F4: e')
        (repo / 'e.py').write_text('# main, fourth\n', encoding='utf-8')
        git(repo, 'commit', '-qam', 'main edits e.py a fourth time')
        t.start()
        t.join(1)
        check(t.is_alive(), 'a conflict in a file another pending fix had waits for that merge')
        has((repo / '.runner/run.log').read_text(), r'F4: waits for F3 to merge first: its conflicts are in the same files',
            'and says why')
        with R.FIX_DIRS_LOCK:
            R.FIXING.pop('F3')
            R.FIX_DIRS_LOCK.notify_all()
        t.join(30)
        eq((took, R.FIXING), ([None], {'F4': {'e.py'}}), 'then it is fixed, and holds e.py until its own merge ends')
        R.FIXING.clear()
        git(repo, 'branch', '-D', 'task/F4')
    finally:
        os.environ.pop('FAKE_FIX', None)
        R.fix_session = original_session
        R.fix_cmd = original_fix_cmd
        R.C.run['agent'] = 'claude'


def test_repair(repo: Path, tmp: Path):
    print('run: a merge that fails the gate gets one repair session; one that commits nothing is parked')
    R.init(repo)
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    seen = tmp / 'prompt.txt'
    R.C.run['agent'], R.C.run['build'] = str(agent), 'python3 -c "print(1)"'
    original_fix_cmd = use_fake_fix_agent(agent)
    os.environ['FAKE_PROMPT'] = str(seen)

    def on_main(name: str) -> None:  # main moves on, so the merge differs from what the branch's done gated
        (repo / name).write_text('x\n', encoding='utf-8')
        git(repo, 'add', name), git(repo, 'commit', '-qm', f'main: {name}')
    try:
        commit_on(repo, 'R1', {'BROKEN': ''}, 'R1: breaks the gate only merged')
        on_main('r1.txt')
        os.environ['FAKE_FIX'], os.environ['FAKE_MAIN'] = 'repair', str(repo)
        eq(R.merge('R1', 'main'), None, 'a repair session that fixes the merge lands it')
        os.environ.pop('FAKE_MAIN')
        check(not (repo / 'BROKEN').exists() and (repo / 'moved.txt').exists(),
              'with its fix on main, replayed onto main\'s commit made meanwhile')
        eq((repo / '.runner/run.log').read_text().count('R1: the merge fails the gate'), 1,
           'one session: the rebuilt merge passes with the replayed repair')
        has(git(repo, 'log', '-3', '--format=%s', 'main'), r'repair: drop BROKEN', 'as a commit of its own')
        has(seen.read_text(), r'test gate fails on it', 'the session was told the gate fails')
        has(seen.read_text(), r'python3 -c "print\(1\)"', 'and to check with [run] build')
        has((repo / '.runner/ledger.md').read_text(), r'R1: the merge failed the gate; a repair session fixed it',
            'the ledger says so')

        commit_on(repo, 'R2', {'BROKEN': ''}, 'R2: breaks the gate too')
        on_main('r2.txt')
        os.environ['FAKE_FIX'] = 'abort'
        has(R.merge('R2', 'main') or '', r'tests fail after the merge', 'one the session cannot repair stays unmerged')
        has((repo / '.runner/ledger.md').read_text(), r'R2: no repair: the repair session committed nothing',
            'and the ledger says why')
        check(not (repo / 'BROKEN').exists(), 'main is as it was')
        git(repo, 'branch', '-D', 'task/R2')

        R.C.run['repair_merges'] = False
        commit_on(repo, 'R3', {'BROKEN': ''}, 'R3: breaks the gate')
        on_main('r3.txt')
        seen.unlink()
        has(R.merge('R3', 'main') or '', r'tests fail after the merge', 'repair_merges off: parked at the first failure')
        check(not seen.exists(), 'with no session')
        git(repo, 'branch', '-D', 'task/R3')
    finally:
        for k in ('FAKE_FIX', 'FAKE_PROMPT', 'FAKE_MAIN'):
            os.environ.pop(k, None)
        R.C.run.update(agent='claude', build='', repair_merges=True)
        R.fix_cmd = original_fix_cmd


def test_prompt_and_hooks(repo: Path):
    print('run: the prompt, a custom template, the Stop hook')
    (repo / 'prompt.txt').write_text('Do {tid} with {runner}; keep {unknown}.\n{brief}', encoding='utf-8')
    R.C.run['prompt'] = 'prompt.txt'
    p = R.prompt_for('T2', 1, 1, repo, 'main')
    has(p, rf'^Do T2 with {re.escape(R.C.command)}; keep {{unknown}}\.',
        'a custom template fills what it knows, leaves the rest')
    R.C.run['prompt'], R.C.run['prompt_extra'] = '', 'Slot {n} has its own server on port 80{n}.'
    has(R.prompt_for('T2', 3, 3, repo, 'main'), r'^Slot 3 has its own server on port 803\.$',
        '[run] prompt_extra fills placeholders too')
    R.C.run['prompt_extra'] = ''
    R.C.run['prompt'] = 'prompt.txt'
    R.C.run['prompt'] = ''
    p = R.prompt_for('T2', 1, 1, repo, 'main')
    has(p, r'The test gate is `python3 check\.py`', 'the built-in prompt names the gate')
    check('Other agents' not in p, 'and says nothing about other agents in a one-slot run')
    cmd = R.agent_cmd('hi', 'sid', 'opus', 90, 'slot1')
    has(cmd, r'--stop-hook --idle 90', 'the agent command carries the idle Stop hook')
    big = 'x' * 40000  # past tmux's ~16 KB command limit
    cmd = R.agent_cmd(big, 'sid', 'opus', 90, 'slot1')
    check(len(cmd) < 4000 and R.C.notes('slot1.prompt').read_text() == big,
          'the prompt goes through a file, so a long brief stays under tmux\'s command limit')
    huge = 'x' * 140000  # past Linux's 128 KiB for one argument: the agent would exit at once
    cmd = R.agent_cmd(huge, 'sid', 'opus', 90, 'slot1')
    sid = '00000000-0000-0000-0000-000000000001'
    cmd = R.agent_cmd(huge, sid, 'opus', 90, 'slot1')
    check('slot1.cmd-prompt' in cmd and 'system prompt' in R.C.notes('slot1.cmd-prompt').read_text() and
          huge in R.C.notes(f'{sid}.brief').read_text(),
          'one past the argument limit goes in whole as the system prompt, a short first message pointing at it')
    check(str(R.C.notes(f'{sid}.brief')) in R.agent_flags(sid, 'opus', 90, resume=True),
          'and every resume of that session gets it again')
    R.drop_session_tmp(sid)
    check(not R.C.notes(f'{sid}.brief').exists(), 'a session ended for good drops its brief')
    for payload in ('{}', 'garbage', '{"transcript_path": "/nonexistent"}', '{"transcript_path": null}'):
        r = subprocess.run([sys.executable, str(RUN), 'run', '--stop-hook'], input=payload,
                           capture_output=True, text=True, cwd='/')
        eq(r.returncode, 0, f'--stop-hook exits 0 on {payload[:28]} (outside any repo)')
    for cmd in (['help'], ['plan', 'help'], ['run', '--help'], ['done', '--help']):
        r = run(repo, *cmd)
        check(r.returncode == 0 and len(r.stdout) > 200, f'`run {" ".join(cmd)}` explains itself')
    run(repo, 'stop')
    check(R.stopping(), '`run stop` asks the run to start nothing new')
    eq(R.stopped_by(), f'{R.C.command} stop', 'and the STOP file says who asked')
    R.KEYS.extend(['s'])
    R.take_keys()
    check(not R.stopping(), '`s` in the runner\'s pane takes a stop back')
    R.KEYS.extend(['', 's'])
    R.take_keys()
    check(R.stopping() and R.stopped_by() == 's', 'and `s` again asks for one, through the same STOP file')
    check(not R.KEYS, 'every line typed is read')
    R.clear_stop()

    import contextlib
    import io
    saved = R.POWER, R.SLOTS
    try:
        R.POWER, R.SLOTS = '', 2
        R.KEYS.extend(['s!'])
        R.take_keys()
        check(R.stopping() and R.forced(), '`s!` asks for a stop now')
        R.KEYS.extend(['s'])
        R.take_keys()
        check(not R.stopping() and not R.forced(), 'and `s` takes it back, force and all')
        R.KEYS.extend(['p', '+', '+', '-', 'z'])
        R.take_keys()
        check(R.PAUSED[0] and R.SLOTS == 3 and R.POWER == 'suspend', '`p` pauses, `+`/`-` change slots, `z` suspends')
        R.KEYS.extend(['f'])
        R.take_keys()
        check(R.FORCED[0] and 'usage caps off' in R.state_line(), '`f` forces past the usage caps')
        R.KEYS.extend(['f'])
        R.take_keys()
        check(not R.FORCED[0], 'and `f` again takes it back')
        from unittest import mock
        ran, real = [], subprocess.run
        fail = lambda argv, **k: (real(argv, **k) if argv != R.upgrade_argv() else
                                  ran.append(argv) or subprocess.CompletedProcess(argv, 1, '', 'no network'))
        with mock.patch.object(R.sp, 'run', fail):
            R.KEYS.extend(['u'])
            R.take_keys()
            for _ in range(50):
                if ran:
                    break
                time.sleep(0.1)
            check(not R.upgrade(), 'a failed upgrade says so')
        eq(ran, [R.upgrade_argv()] * 2, '`u` runs the upgrade command (and so does upgrade())')
        R.KEYS.extend(['x', 'p', 'x', '-', '-', '-'])
        R.take_keys()
        check(not R.PAUSED[0] and R.POWER == '' and R.SLOTS == 1,
              '`x` switches to shutdown and back off, `p` again unpauses, slots never go below 1')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            R.KEYS.extend(['?', 'frob'])
            R.take_keys()
        text = out.getvalue()
        check(text.count('-' * 78) == 4 and 's!' in text and 'now: 1 slot' in text,
              '`?` prints the ruled-off key list with the current state')
        check("unknown key 'frob'" in text, 'an unknown line says so, then shows the keys')
        r = run(repo, 'pause')
        check(r.returncode == 1 and 'no run is up' in r.stderr, '`pause` with no run up says so')
        R.send_key('p on', 'p on', 'slots +2', 'slots 1', 'slots 0', 'slots x', 'f on')
        R.take_keys()
        check(R.PAUSED[0] and R.SLOTS == 1 and R.FORCED[0] and not (repo / '.runner/KEYS').exists(),
              'keys left by the CLI are taken: `p on` twice stays paused, slots set and checked')
        R.send_key('p off', 'f off', 'f off', 's on', 's on')
        R.take_keys()
        check(not R.PAUSED[0] and not R.FORCED[0] and R.stopping(), '`off` takes back, `on` twice stops once')
        run(repo, 'stop', '--undo')
        check(not R.stopping(), '`stop --undo` with no run up clears the stop')
        opened = []
        with mock.patch.object(R.webbrowser, 'open', lambda u: opened.append(u) or True):
            R.KEYS.append('')
            R.take_keys()
            check(not opened, 'Enter does nothing without [run] remote')
            with mock.patch.dict(R.C.run, {'remote': True}):
                R.KEYS.append('')
                R.take_keys()
                flags = R.remote_flags('slot2', None)
        eq(opened, [R.REMOTE_URL], 'with [run] remote, Enter opens the sessions page')
        eq(flags, [], '[run] remote alone leaves the slots local (only control sessions go on Remote Control)')
        with mock.patch.dict(R.C.run, {'remote_slots': True}):
            eq(R.remote_flags('slot2', None), ['--remote-control', f'{R.ROOT.name} s2'],
               'with [run] remote_slots a slot starts on Remote Control, named')
            with mock.patch.object(R, 'git', return_value=mock.Mock(stdout='task/F10\n')), \
                    mock.patch.object(R.P, 'titles', return_value={'F10': 'Attach to the background run'}):
                eq(R.remote_flags('slot2', R.ROOT), ['--remote-control',
                                                     f'Attach to the background run · {R.ROOT.name} s2 · F10'],
                   'the task title leads the session name, its id last')
        eq(R.remote_flags('slot2', None), [], 'no Remote Control unless [run] remote_slots')
        R.write_state({1: ('T3', '', set(), set())})
        with mock.patch.object(R, 'run_up', lambda: True), mock.patch.object(R, 'init', lambda: None):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                R.cmd_status(['-n', '0'])
        check('run up: 1 slot' in out.getvalue() and re.search(r'^  s1  (.+ \[T3\]|T3)  0 min$', out.getvalue(), re.M),
              '`status` shows the state and each slot\'s task and minutes', out.getvalue())
        run(repo, 'stop', '--force', '--shutdown')
        R.take_keys()
        check(R.forced() and R.POWER == 'shutdown' and not (repo / '.runner/POWER').exists(),
              '`stop --force --shutdown` reaches the run through the same files')
        R.clear_stop()
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        procs, running = {2: (p.pid, 'sid-x', 0.0)}, {2: ('T9', '', set(), set())}
        with mock.patch.object(R, 'transcript', lambda sid: '/t.jsonl'):
            R.end_sessions(procs, running)
        check(p.wait(timeout=10) is not None and not procs and not running, '`s!` ends the session')
        eq(R.queued().get(2), ('T9', 'sid-x', 'stopped with s!'), 'and queues it to resume in its slot')
        (repo / '.runner/T9.resume').unlink()
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        procs, running = {2: (p.pid, 'sid-never', 0.0)}, {2: ('T9', '', set(), set())}
        with mock.patch.object(R, 'transcript', lambda sid: None):
            R.end_sessions(procs, running)
        check(p.wait(timeout=10) is not None and not procs, '`s!` ends a session that never began')
        eq(R.queued(), {}, 'and queues no resume (--resume would find no session): the task starts afresh')
    finally:
        R.POWER, R.SLOTS = saved
        R.PAUSED[0] = R.FORCED[0] = False


def test_hooks(repo: Path, tmp: Path):
    print('hooks a wrapping project uses: its own config file, joiners, suspect')
    from agent_runner import config
    kit = tmp / 'kit.toml'
    kit.write_text('[git]\nkit_owns_this = true\n\n[agent-runner.run]\ntest = "python3 check.py"\n'
                   'command = "./kit"\n\n[agent-runner.git]\npush = false\n',
                   encoding='utf-8')
    env = {**os.environ, 'AGENT_RUNNER_CONFIG': str(kit)}
    os.environ['AGENT_RUNNER_CONFIG'] = str(kit)
    try:
        c = config.Config(repo)
        eq(c.file, kit.resolve(), 'AGENT_RUNNER_CONFIG wins over runner.toml')
        check(c.run['test'] == 'python3 check.py' and c.push_remote is None,
              'and its [agent-runner] table is the config')
        check('kit_owns_this' not in c.raw['git'], "the project's own [git] does not leak in")
        eq(c.command, './kit', '[run] command is what sessions are told to call')
        R._cfg_was = R.C
        R.C = c
        check(f'AGENT_RUNNER_CONFIG={kit.resolve()}' in R.slot_env(2), 'and a slot pane is handed the config file')
        c.run['slot_env'], c.run['pass_env'] = ['KIT_PCSX2={n}', 'KIT_CHECK_SLOTS={slots}'], ['KIT_FLAG', 'KIT_UNSET']
        os.environ['KIT_FLAG'] = 'x'
        R.SLOTS = 3
        env_ = R.slot_env(2)
        check({'KIT_PCSX2=2', 'KIT_CHECK_SLOTS=3', 'KIT_FLAG=x'} <= set(env_) and not any('UNSET' in e for e in env_),
              'slot_env fills {n} and {slots}; pass_env hands on what is set', env_)
        del os.environ['KIT_FLAG']
        R.SLOTS = 1
    finally:
        del os.environ['AGENT_RUNNER_CONFIG']
        R.C = R._cfg_was

    d = task_branch(repo, 2, 'T2')
    (d / 'b.py').write_text('def show(x):\n    return str(x)\n', encoding='utf-8')
    r = run(d, 'done', 'T2', 'T2: the printer', env=env)
    check(r.returncode == 0, 'done commits under the wrapping config', r.stdout + r.stderr)
    check('pushed' not in r.stdout and 'task/T2' not in remote_branches(tmp), "and [agent-runner.git] push = false holds")
    git(d, 'checkout', '-q', '--detach')

    R.init(repo)
    join_command = ('findstr /v /c:CLASH {union} > {out}' if R.plat.WINDOWS
                    else 'grep -v CLASH {union} > {out}')
    refusal_command = 'echo two addresses & exit /b 3' if R.plat.WINDOWS else 'echo two addresses; exit 3'
    R.C.run['join'] = {'*.addr': join_command, 'refuse.addr': refusal_command}
    try:
        check(R.joinable('x/y.addr') and not R.joinable('x/y.txt'), 'a [run.join] glob makes a file joinable')
        sides = []
        for name, text in (('ours', 'a 1\n'), ('base', ''), ('theirs', 'b 2\n')):
            (tmp / name).write_text(text, encoding='utf-8')
            sides.append(str(tmp / name))
        eq(R.custom_join('lists/one.addr', sides, 'a 1\nCLASH\nb 2\n', 'T9', repo), 'a 1\nb 2\n',
           'the joiner rewrites the union through {union} and {out}')
        R.C.run['join'] = {'refuse.addr': refusal_command}
        check(R.custom_join('refuse.addr', sides, 'x\n', 'T9', repo) is None, 'and a non-zero exit refuses the join')
        has((repo / '.runner/run.log').read_text(), r'refused the join \(exit 3\): two addresses', 'saying why')
    finally:
        R.C.run['join'] = {}

    R.C.run['suspect'] = r'BLOCKED:.*\bemulator\b'
    try:
        before = git(repo, 'rev-parse', 'HEAD')
        P.block('T6', 'needs a human at the emulator', todo=repo / 'plan/TODO.md')
        git(repo, 'commit', '-qam', 'T6: blocked')
        has(R.suspect(before, git(repo, 'rev-parse', 'HEAD')), r'T6.*emulator', '[run] suspect flags a block a merge adds')
        eq(R.suspect(before, before), '', 'and nothing when none was added')
        blocked = git(repo, 'rev-parse', 'HEAD')
        todo = repo / 'plan/TODO.md'
        todo.write_text(re.sub(r'(\*\*T6\*\*.*)', r'\1 | files: z.py', todo.read_text(encoding='utf-8'), count=1),
                        encoding='utf-8')
        git(repo, 'commit', '-qam', 'T6: its files')
        eq(R.suspect(blocked, git(repo, 'rev-parse', 'HEAD')), '', 'nor when a blocked line only gets its files')
    finally:
        R.C.run['suspect'] = ''

    if R.plat.WINDOWS:
        heading = R.plat.command_text([sys.executable, '-c', "print('## From the project')"])
        names = R.plat.command_text([sys.executable, '-c', "print('names for {id}')"])
        brief_extra = f'{heading} & {names}'
    else:
        brief_extra = 'echo "## From the project"; echo "names for {id}"'
    R.C.raw['plan']['brief_extra'] = brief_extra
    try:
        b = '\n'.join(P.brief('T6', root=repo))
        has(b, r'^## From the project\nnames for T6$', '[plan] brief_extra ends the brief')
        has(b, r'## Files on the line, and their last commits\n- `c.py`', 'after the files and their git log')
    finally:
        R.C.raw['plan']['brief_extra'] = ''
    has(R.agent_cmd('p', 'sid', 'opus', 90, 'slot1'), r'run run --stop-hook', 'the Stop hook calls this runner back')

    # a restart adopts running sessions: their id is read off the agent's command line, even under a shell
    if not R.plat.WINDOWS:
        sh = subprocess.Popen(['sh', '-c', 'python3 -c "import time; time.sleep(30)" --session-id abc-123; true'],
                              start_new_session=True)
        try:
            time.sleep(0.5)
            eq(R.session_id(sh.pid), 'abc-123', 'session_id finds the agent under the pane\'s shell')
        finally:
            os.killpg(sh.pid, 9)
    lock = R.single_run()
    try:
        r = subprocess.run([sys.executable, '-c', 'from agent_runner import runner as R; R.init(); R.single_run()'],
                           cwd=str(repo), capture_output=True, text=True,
                           env={**os.environ, 'PYTHONPATH': str(Path(R.__file__).parent.parent)})
        has(r.stderr, r'another run is going', 'a second run in the same repository refuses to start')
    finally:
        lock.close()


def test_platform(repo: Path, tmp: Path):
    """The OS layer, on the parts Linux can run: the terminal choice, quoting (Windows' too, by flipping
    plat.WINDOWS for the pure functions), the run lock, links, process checks, and the Windows slot shim,
    which is plain Python around a marker file."""
    print('platform: the terminal per slot, quoting, locks, links, processes, the Windows slot shim')
    from agent_runner import plat
    windows_was = plat.WINDOWS
    choice = plat.mux_choice
    eq(choice('', True, True, windows=False), 'tmux', 'F40: POSIX inside tmux: panes')
    eq(choice('', True, False, windows=False), 'hidden', 'tmux installed but the run not in it: hidden, no error')
    eq(choice('', False, False, windows=False), 'hidden', 'POSIX without tmux: hidden, not the sequential run')
    eq(choice('tmux', True, False, windows=False), 'tmux', 'tmux asked for: tmux (the run then says to start it in tmux)')
    eq(choice('tmux', False, True, windows=False), 'hidden', 'tmux asked for but not installed: hidden')
    eq(choice('hidden', True, True, windows=False), 'hidden', '--mux hidden inside tmux')
    eq(choice('', True, True, windows=True), 'hidden', 'Windows: hidden only')
    eq(choice('tmux', True, True, windows=True), 'hidden', 'Windows: hidden even when tmux is asked for')
    for gone in ('none', 'wt', 'console'):
        eq(choice(gone, True, True, windows=False), 'hidden', f'the old [run] mux = {gone!r} reads as hidden')

    plat.WINDOWS = False
    try:
        eq(plat.command_text(['/usr/bin/python3', '/x y/run', 'run']), "/usr/bin/python3 '/x y/run' run",
           'POSIX command text is shlex.join, as before')
        eq(plat.quote("a b"), "'a b'", 'POSIX quoting for shell=True is shlex.quote')
    finally:
        plat.WINDOWS = windows_was
    plat.WINDOWS = True
    try:
        eq(plat.command_text([r'C:\Program Files\Python\python.exe', r'C:\src\agent-runner\run', 'run', '--idle', '90']),
           '"C:/Program Files/Python/python.exe" C:/src/agent-runner/run run --idle 90',
           'Windows command text: forward slashes, double quotes (Git Bash and cmd.exe agree)')
        eq(plat.quote('a b'), '"a b"', 'Windows quoting for shell=True is cmd.exe\'s')

        # terminate on Windows: WM_CLOSE to the windows of the tree, wait for them, then taskkill /T /F
        saved = plat._snapshot, plat._windows_of, plat._post_close, plat.alive, plat.sp.run, plat.CLOSE_GRACE
        procs = [(10, 1, 'claude.exe'), (11, 10, 'bash.exe'), (12, 11, 'pcsx2-qt.exe'), (13, 99, 'other.exe')]
        posted, ran, polls = [], [], []
        try:
            plat._snapshot = lambda: procs
            plat._windows_of = lambda p: [500] if p == 12 else []
            plat._post_close = posted.append
            plat.alive = lambda p: polls.append(p) or len(polls) < 3  # the emulator exits on the third look
            plat.sp.run = lambda argv, **kw: ran.append(argv)
            eq(plat.descendants(10), [11, 12], 'descendants: the whole tree below, nothing outside it')
            plat.terminate(10)
            eq(posted, [500], 'the emulator\'s window in the tree gets WM_CLOSE')
            eq(polls, [12, 12, 12], 'the runner waits for that process, and only that one')
            eq(ran, [['taskkill', '/T', '/F', '/PID', '10']], 'then the tree is ended by force')
            posted.clear(); ran.clear(); polls.clear()
            plat.CLOSE_GRACE = 0.3
            plat.alive = lambda p: polls.append(p) or True  # it never closes
            t0 = time.monotonic()
            plat.terminate(10)
            check(time.monotonic() - t0 < 2 and ran == [['taskkill', '/T', '/F', '/PID', '10']],
                  'a window that will not close waits out the grace, then the force kill')
            plat._windows_of = lambda p: []
            polls.clear(); ran.clear()
            plat.terminate(10)
            check(not polls and ran, 'no window in the tree: straight to taskkill, no wait')
        finally:
            plat._snapshot, plat._windows_of, plat._post_close, plat.alive, plat.sp.run, plat.CLOSE_GRACE = saved
    finally:
        plat.WINDOWS = windows_was
    saved = os.sep, os.path.relpath
    try:  # Windows' relpath gives backslashes; git names files with forward slashes
        os.sep, os.path.relpath = '\\', lambda a, b=None: 'plan\\TODO.md'
        eq(R.plan_rel('TODO.md'), 'plan/TODO.md', 'plan paths given to git use forward slashes on Windows too')
    finally:
        os.sep, os.path.relpath = saved

    lk = tmp / 'x.lock'
    first = plat.lock(lk)
    check(first is not None, 'a free lock is taken')
    r = subprocess.run([sys.executable, '-c', 'import sys; from agent_runner import plat; '
                        'sys.exit(plat.lock(sys.argv[1]) is None)', str(lk)],
                       env={**os.environ, 'PYTHONPATH': str(Path(R.__file__).parent.parent)})
    eq(r.returncode, 1, 'and another process cannot take it')
    first.close()
    (tmp / 'ldir').mkdir()
    (tmp / 'lfile').write_text('x')
    check(plat.link(tmp / 'ldir', tmp / 'ldir2') and (tmp / 'ldir2').is_dir(), 'link: a directory')
    check(plat.link(tmp / 'lfile', tmp / 'lfile2') and (tmp / 'lfile2').read_text() == 'x', 'link: a file')

    check(plat.alive(os.getpid()) and not plat.alive(0), 'alive: this process yes, pid 0 no')
    if plat.WINDOWS:
        child_code = 'import time; time.sleep(30)'
        parent_code = f'import subprocess,sys,time; subprocess.Popen([sys.executable, "-c", {child_code!r}]); time.sleep(30)'
        sh = subprocess.Popen([sys.executable, '-c', parent_code])
    else:
        sh = subprocess.Popen(['sh', '-c', 'sleep 30; true'])
    try:
        time.sleep(0.3)
        eq(len(plat.children(sh.pid)), 1, 'children: the shell\'s sleep')
    finally:
        if plat.WINDOWS:
            plat.terminate(sh.pid)
        else:
            sh.kill()
            sh.wait()
    check(not plat.alive(sh.pid), 'alive: a reaped process is gone')

    long = R.agent_argv('x' * (R.ARGV_PROMPT_MAX + 1), 'sid-1', 'opus', 90, 'slotT')
    has(long[1], r'in your system prompt', 'a prompt too long for a Windows command line goes in the system prompt')
    has(R.C.notes('sid-1.brief').read_text(encoding='utf-8'), 'x' * (R.ARGV_PROMPT_MAX + 1), 'whole')
    eq(R.C.notes('slotT.prompt').read_text(encoding='utf-8'), 'x' * (R.ARGV_PROMPT_MAX + 1), 'all of it')
    eq(long[2:4], ['--session-id', 'sid-1'], 'and the flags follow, as in agent_cmd')

    # the shim a hidden slot runs: the agent's pid in the marker while it runs, AGENT_RUNNER_MARKER set
    marker, job, seen = R.C.notes('slot7.live'), R.C.notes('slot7.job'), tmp / 'seen'
    agent = [sys.executable, '-c', 'import os, sys, time; open(sys.argv[1], "w").write(os.environ["AGENT_RUNNER_MARKER"]);'
             ' time.sleep(2)', str(seen), '--session-id', 'sid-7']
    job.write_text(json.dumps({'argv': agent, 'cwd': str(repo), 'env': {'AGENT_SLOT': '7'}, 'marker': str(marker)}))
    shim = subprocess.Popen([sys.executable, str(RUN), 'run', '--slot-shim', str(job)], cwd=str(repo))
    try:
        for _ in range(50):
            if R.marker_pid(marker):
                break
            time.sleep(0.1)
        mux = R.HiddenMux()
        pid = R.marker_pid(marker)
        check(pid and plat.alive(pid) and pid != shim.pid, 'the shim publishes the agent\'s own pid')
        eq(mux.panes().get('s7', (None, None))[1], pid, 'hidden slots are listed by their marker')
        eq(mux.session_id(pid), 'sid-7', 'and a restart reads its session id off the job file')
        shim.wait(timeout=10)
    finally:
        shim.kill()
    check(not marker.exists(), 'the marker goes when the session ends')
    eq(seen.read_text() if seen.exists() else '', str(marker), 'the agent is told its marker (for the Stop hook)')


def commit_on(repo: Path, tid: str, files: dict[str, str], subject: str) -> None:
    d = task_branch(repo, 1, tid)
    for f, text in files.items():
        (d / f).write_text(text, encoding='utf-8')
    git(d, 'add', *files)
    git(d, 'commit', '-qm', subject)
    git(d, 'checkout', '-q', '--detach')


def test_shutdown(repo: Path):
    print('run: --shutdown powers off only after the grace period, and stays up when refused; --suspend once per idle')
    R.init(repo)
    calls: list[str] = []
    saved = R.plat.power_off, R.plat.suspend, R.pick, R.POWER, R.SHUTDOWN_GRACE
    try:
        R.plat.power_off = lambda: calls.append('off') or 0
        R.plat.suspend = lambda: calls.append('sleep') or 0
        R.POWER, R.SHUTDOWN_GRACE = '', 0
        check(not R.shut_down(0) and not calls, 'without --shutdown nothing happens')
        R.POWER, R.SHUTDOWN_GRACE = 'shutdown', 3600
        check(not R.shut_down(time.time()) and not calls, 'not before the grace period')
        R.SHUTDOWN_GRACE = 0
        R.plat.power_off = lambda: calls.append('off') or 1
        check(not R.shut_down(0) and calls == ['off'], 'a refused power-off keeps the run up')
        calls.clear()
        R.plat.power_off = lambda: calls.append('off') or 0
        check(R.shut_down(0) and calls == ['off'], 'an accepted power-off ends the run, powered off once')
        calls.clear()
        R.POWER = 'suspend'
        check(not R.shut_down(5.0) and calls == ['sleep'], '--suspend suspends, and the run stays')
        check(not R.shut_down(5.0) and not R.power_due(5.0) and calls == ['sleep'],
              'woken in the same idle stretch, it does not suspend again')
        check(not R.shut_down(9.0) and calls == ['sleep', 'sleep'], 'after work and a new idle stretch, it does')
    finally:
        R.plat.power_off, R.plat.suspend, R.pick, R.POWER, R.SHUTDOWN_GRACE = saved
        R.SLEPT_AT[0] = -1.0


def test_gate_and_batches(repo: Path, tmp: Path):
    print('run: untested globs, flaky and inherited failures, batched merges, phases that are not attempts')
    R.init(repo)
    r = R.C.run
    r['untested'] = ['*.md', 'tools/*', '!tools/check.sh']
    check(R.untestable('docs/a.md') and R.untestable('tools/x.sh') and not R.untestable('tools/check.sh')
          and not R.untestable('a.py'), '[run] untested: globs, and !glob takes a file back')

    d = R.worktree('merge', 'main')
    base = git(repo, 'rev-parse', 'main')
    git(d, 'checkout', '-q', '--detach', base)
    (d / 'only_on_head').write_text('', encoding='utf-8')
    git(d, 'add', 'only_on_head')
    git(d, 'commit', '-qm', 'head')
    head = git(d, 'rev-parse', 'HEAD')
    gate_was = R.merge_gate
    R.merge_gate = lambda tid, cwd, env, batch=None: (1, 'FAIL t_a\nboom')
    r['failures'] = r'^FAIL (\S+)'
    try:
        r['retest'] = 'exit /b 0' if R.plat.WINDOWS else 'true'
        eq(R.tested('X', d, base), None, 'a failure that passes when rerun alone counts as passing')
        r['retest'] = 'echo FAIL {names} & exit /b 1' if R.plat.WINDOWS else 'echo FAIL {names}; false'
        eq(R.tested('X', d, base), None, 'one the base fails the same way merges anyway')
        eq(R.BROKEN.pop('t_a', None), ('X', base, False), 'and is kept to file: the shared branch fails it')
        last = R.C.notes(R.GATES) / R.FULL_PASS
        last.parent.mkdir(parents=True, exist_ok=True)
        last.unlink(missing_ok=True)
        r['test_since'] = 'echo since {base}'
        eq(R.tested('X', d, base), None, 'with test_since, the whole test finding it')
        check(last.exists(), 'counts as the day\'s whole run')
        eq(R.BROKEN.pop('t_a', None), ('X', base, True), 'filed as the daily run\'s')
        r['test_since'] = ''
        last.unlink(missing_ok=True)
        r['retest'] = ('if exist only_on_head (echo FAIL t_a & exit /b 1)'
                       if R.plat.WINDOWS else 'test ! -e only_on_head || { echo FAIL t_a; exit 1; }')
        has(R.tested('X', d, base) or '', r'tests fail after the merge', 'one only the merge fails stops it')
        eq(git(d, 'rev-parse', 'HEAD'), head, 'and the merge worktree is back on the merge')
        r['retest'] = ('if exist only_on_head (echo x>>only_on_head & echo FAIL t_a & exit /b 1)'
                       if R.plat.WINDOWS else
                       'test -e only_on_head && echo x >> only_on_head && echo FAIL t_a && exit 1; exit 0')
        has(R.tested('X', d, base) or '', r'tests fail after the merge',
            'a retest that dirties a tracked file still reruns on the base, not on the merge')
        eq((git(d, 'rev-parse', 'HEAD'), git(d, 'status', '--porcelain')), (head, ''), 'and leaves the merge clean')
        r['failures'] = ''
        has(R.tested('X', d, base) or '', r'boom', 'without [run] failures a failure is a failure')
    finally:
        R.merge_gate = gate_was
        r['failures'] = r['retest'] = ''

    commit_on(repo, 'B1', {'b1.py': '1\n'}, 'B1: one')
    commit_on(repo, 'B2', {'b2.py': '2\n'}, 'B2: two')
    R.WAITING.add('B2')  # as a second finish thread queued on the lock
    eq(R.merge('B1', 'main'), None, 'a batch lands')
    has((repo / '.runner/run.log').read_text(), r'B1: merging together with B2', 'B2 rode along with B1')
    check((repo / 'b1.py').exists() and (repo / 'b2.py').exists(), 'both are in main')
    if R.C.push_merge:
        check(git(repo, 'rev-parse', 'main') != git(tmp / 'origin.git', 'rev-parse', 'main'),
              'not pushed yet: the push is left to B2, still waiting to record its landing')
    R.WAITING.discard('B2')
    eq(R.merge('B2', 'main'), None, 'the rider\'s own turn only does the bookkeeping')
    check(git(repo, 'branch', '--list', 'task/B2') == '' and not R.LANDED, 'its branch is gone')
    if R.C.push_merge:
        eq(git(repo, 'rev-parse', 'main'), git(tmp / 'origin.git', 'rev-parse', 'main'), 'and B2 pushed the batch, once')
        has((repo / '.runner/run.log').read_text(), r'B2: pushed main -> origin.* \(with B1\)', 'naming B1 with it')
        check(not {'task/B1', 'task/B2'} & set(remote_branches(tmp)), 'both remote branches dropped')

    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    r['agent'] = str(agent)
    original_fix_cmd = use_fake_fix_agent(agent)
    try:
        commit_on(repo, 'B3', {'b3.py': '3\n'}, 'B3: three')
        commit_on(repo, 'B4', {'BROKEN': ''}, 'B4: breaks the gate')
        R.WAITING.add('B4')
        os.environ['FAKE_FIX'] = 'abort'
        eq(R.merge('B3', 'main'), None, 'a batch that fails the gate still lands its own task')
        log = (repo / '.runner/run.log').read_text(encoding='utf-8')
        has(log, r'B3: the batch \(B3, B4\) fails the gate — handing it to a repair session', 'after a batch repair session')
        has(log, r'B3: the batch fails the gate', 'that commits nothing, alone, after saying so')
        check((repo / 'b3.py').exists() and not (repo / 'BROKEN').exists(), 'without the rider')
        R.WAITING.discard('B4')
        git(repo, 'branch', '-D', 'task/B4')

        commit_on(repo, 'B5', {'b5.py': '5\n'}, 'B5: five')
        commit_on(repo, 'B6', {'BROKEN': '', 'b6.py': '6\n'}, 'B6: clashes with the batch')
        R.WAITING.add('B6')
        os.environ['FAKE_FIX'] = 'repair'
        eq(R.merge('B5', 'main'), None, 'a batch the repair session fixes lands')
        check((repo / 'b5.py').exists() and (repo / 'b6.py').exists() and not (repo / 'BROKEN').exists(),
              'both tasks, with the repair')
        eq(R.LANDED.get('B6', ('', ''))[1], git(repo, 'rev-parse', 'main'), 'the rider landed in the same merge')
        has(git(repo, 'log', '-4', '--format=%s', 'main'), r'repair: drop BROKEN', 'the repair is a commit of its own')
        R.WAITING.discard('B6')
        eq(R.merge('B6', 'main'), None, 'and its own turn only does the bookkeeping')

        commit_on(repo, 'B7', {'g.py': '# g, B7\n'}, 'B7: g')
        commit_on(repo, 'B8', {'g.py': '# g, B8\n', 'b8.py': '8\n'}, 'B8: g too')
        R.WAITING.add('B8')
        os.environ['FAKE_FIX'] = 'theirs'
        r['fix_ahead_max'] = 0
        eq(R.merge('B7', 'main'), None, 'a rider whose conflict a join cannot do')
        has((repo / '.runner/run.log').read_text(), r'B8: the fix session resolved g\.py',
            'gets a fix session in the batch, with fix_ahead_max = 0')
        check((repo / 'b8.py').exists() and 'B8' in R.LANDED, 'and lands with it, in one gate run')
        R.WAITING.discard('B8')
        eq(R.merge('B8', 'main'), None, 'its own turn only does the bookkeeping')
        r['fix_ahead_max'] = 2
        commit_on(repo, 'B9', {'g.py': '# g, B9\n'}, 'B9: g')
        commit_on(repo, 'B10', {'g.py': '# g, B10\n', 'b10.py': '10\n'}, 'B10: g too')
        R.WAITING.add('B10')
        eq(R.merge('B9', 'main'), None, 'with fix_ahead on, the batch lands')
        check(not (repo / 'b10.py').exists() and 'B10' not in R.LANDED,
              'without the rider whose conflict needs a session: no session under the lock')
        R.WAITING.discard('B10')
        eq(R.merge('B10', 'main'), None, 'which takes its own turn, fixed ahead of the lock')
        check((repo / 'b10.py').exists(), 'and lands')
    finally:
        os.environ.pop('FAKE_FIX', None)
        r['agent'] = 'claude'
        R.fix_cmd = original_fix_cmd

    r['not_attempt'] = r'^{id} spec:'
    commit_on(repo, 'S1', {'s.md': 'spec\n'}, 'S1 spec: how it works')
    check(R.not_attempt('S1', 'main'), '[run] not_attempt: a spec phase is not the attempt')
    commit_on(repo, 'S2', {'s2.md': 'x\n'}, 'S2: done')
    check(not R.not_attempt('S2', 'main'), 'a finished task is')
    r['not_attempt'] = ''
    git(repo, 'branch', '-D', 'task/S1', 'task/S2')



def test_leftovers(repo: Path):
    print('a session that ends uncommitted: its edits are saved on a branch before the slot is reset')
    R.init(repo)
    d = task_branch(repo, 3, 'L1')
    eq(R.save_leftovers(d, 'L1', 'main'), '', 'a clean slot has nothing to keep')
    sub = repo.parent / 'leftover-sub'
    sub.mkdir(exist_ok=True)
    git(sub, 'init', '-q')
    (sub / 's.txt').write_text('s\n', encoding='utf-8')
    git(sub, 'add', '-A')
    git(sub, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 's')
    git(d, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(sub), 'sub')
    git(d, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'sub')
    (d / 'sub' / 's.txt').write_text('patched by a build\n', encoding='utf-8')
    check(git(d, 'status', '--porcelain') != '', 'a submodule edited inside shows in git status')
    eq(R.save_leftovers(d, 'L1', 'main'), '', 'but a commit could not hold it: nothing to keep, no branch')
    git(d, 'reset', '-q', '--hard', 'HEAD~1')
    shutil.rmtree(d / 'sub', ignore_errors=True)
    (d / 'a.py').write_text('# a, edited\n', encoding='utf-8')
    (d / 'new.py').write_text('# new\n', encoding='utf-8')
    git(d, 'add', 'a.py')  # half staged, as an interrupted `done` might leave it
    eq(R.save_leftovers(d, 'L1', 'main'), 'wip/L1', 'with no commits of its own the work goes to wip/<ID>')
    eq(git(repo, 'show', 'wip/L1:new.py'), '# new', 'untracked files too')
    eq(git(repo, 'show', 'wip/L1:a.py'), '# a, edited', 'and staged ones')
    check(git(d, 'status', '--porcelain') != '' and git(d, 'rev-parse', 'HEAD') == git(repo, 'rev-parse', 'main'),
          'the slot itself is left as it was')
    has((repo / '.runner/run.log').read_text(), r'L1: the session left 2 files uncommitted .*saved on wip/L1', 'and the log says where')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'L1: a commit of its own')
    (d / 'b.py').write_text('# b, scratch\n', encoding='utf-8')
    eq(R.save_leftovers(d, 'L1', 'main'), 'leftover/L1', 'with commits (or a wip/ already) it goes to leftover/<ID>')
    eq(git(repo, 'rev-list', '--count', 'main..task/L1'), '1', 'and the task branch does not take in the untested edits')
    (d / 'c.py').write_text('# c, more scratch\n', encoding='utf-8')
    eq(R.save_leftovers(d, 'L1', 'main'), 'leftover/L1-2', 'a second leftover takes the next free name')
    eq(git(repo, 'show', 'leftover/L1:b.py'), '# b, scratch', 'and the first one is kept as it was')
    git(d, 'reset', '-q', '--hard')
    git(d, 'clean', '-fdq')
    git(d, 'checkout', '-q', '--detach')
    git(repo, 'branch', '-D', 'task/L1', 'wip/L1', 'leftover/L1', 'leftover/L1-2')


def test_renumber(repo: Path):
    print("a follow-up filed under an id main gave away meanwhile is renumbered, not dropped by the join")
    R.init(repo)
    (repo / '.git' / P.RESERVED).unlink(missing_ok=True)  # ids other tests handed out
    d = task_branch(repo, 4, 'N1')
    todo = 'plan/TODO.md'
    P.add('Q', 'the follow-up, after Q1 is read', 'bottom', todo=d / todo, done=d / 'plan/DONE.md')
    P.add('Q', 'and its sequel, after Q1', 'bottom', todo=d / todo, done=d / 'plan/DONE.md')
    (d / 'plan/tasks').mkdir(exist_ok=True)
    (d / 'plan/tasks/Q1.md').write_text('# Q1 the follow-up\n', encoding='utf-8')
    git(d, 'add', 'plan/tasks/Q1.md')
    git(d, 'commit', '-qam', 'N1: follow-ups Q1, Q2')
    # `add` counts the slot's ids now (`_other_checkouts`), so the clash comes from a checkout it can't see
    # (one gone since, another machine): written by hand here
    ls = (repo / todo).read_text().split('\n')
    k = next(i for i, l in enumerate(ls) if l.startswith('- ['))
    (repo / todo).write_text('\n'.join(ls[:k] + ["- [ ] **Q1** the person's own task"] + ls[k:]))
    git(repo, 'commit', '-qam', 'plan: add Q1')
    eq(P.add('Q', 'x', todo=d / todo, done=d / 'plan/DONE.md'), 'Q3',
       "a session's add counts the ids in the repo's other checkouts too")
    git(d, 'checkout', '-q', '--', todo)
    (repo / '.git' / P.RESERVED).unlink()  # that probe's Q3 is held, or the renumber below takes Q4
    eq(R.renumber_doubles('main', 'main', 'N1', repo), 'main', 'nothing doubled: the ref is merged as it is')
    ref = R.renumber_doubles('task/N1', 'main', 'N1', repo)
    check(ref != 'task/N1', 'a doubled id gets a commit of its own on top of the branch')
    t = git(repo, 'show', f'{ref}:{todo}')
    has(t, r'\*\*Q3\*\* the follow-up, after Q3 is read', 'the follow-up takes the next id free on both sides, '
        'and a line the branch wrote that names it follows')
    has(t, r'\*\*Q2\*\* and its sequel, after Q3', 'an id main does not use stays, and its mention follows')
    eq(git(repo, 'rev-parse', f'{ref}^'), git(repo, 'rev-parse', 'task/N1'), 'on top of the branch, not instead of it')
    eq(git(repo, 'ls-tree', '--name-only', ref, 'plan/tasks/'), 'plan/tasks/Q3.md', 'its long form is renamed with it')
    git(repo, 'merge', '-q', '--no-edit', ref)
    t = (repo / todo).read_text()
    check(all(x in t for x in ("**Q1** the person's own task", '**Q3** the follow-up', '**Q2** and its sequel')),
          'after the merge all three are there')
    has((repo / '.runner/run.log').read_text(), r'N1: renumbered Q1 -> Q3', 'and the log says so')
    (repo / todo).write_text(t + '- [ ] **Q1** a stray copy under the same id\n', encoding='utf-8')
    try:
        P.tick('Q1', todo=repo / todo, done=repo / 'plan/DONE.md')
        check(False, 'tick refuses an id listed twice')
    except SystemExit as e:
        has(str(e), 'listed twice', 'tick refuses an id listed twice')
    git(repo, 'checkout', '-q', '--', todo)
    git(d, 'checkout', '-q', '--detach')
    git(repo, 'branch', '-D', 'task/N1')


def test_stop_waiter(tmp: Path):
    print('the idle stop waits out a command the agent still runs, up to a cap')
    t = tmp / 'transcript.jsonl'
    t.write_text('{"type":"user"}\n', encoding='utf-8')
    poll, R.WAITER_POLL = R.WAITER_POLL, 0.2

    def agent_with_child(child_seconds: float) -> list[str]:
        child = f'import time; time.sleep({child_seconds})'
        parent = f'import subprocess,sys,time; subprocess.run([sys.executable, "-c", {child!r}]); time.sleep(30)'
        return [sys.executable, '-c', parent]

    try:
        p = subprocess.Popen(agent_with_child(1.5))
        time.sleep(0.3)
        t0 = time.time()
        R.stop_waiter(p.pid, str(t), 1, 0)
        took = time.time() - t0
        check(p.wait(5) is not None and took >= 1.0, 'it ends the session only once its child has exited', took)
        os.environ['AGENT_RUNNER_IDLE_MAX'] = '1'
        p = subprocess.Popen(agent_with_child(4))
        time.sleep(0.3)
        t0 = time.time()
        R.stop_waiter(p.pid, str(t), 1, 0)
        took = time.time() - t0
        check(p.wait(5) is not None and took < 3, 'and not past AGENT_RUNNER_IDLE_MAX', took)
        p = subprocess.Popen(agent_with_child(30))
        t.write_text('{"type":"user"}\n{"type":"user"}\n', encoding='utf-8')
        R.stop_waiter(p.pid, str(t), 1, 0)
        check(p.poll() is None, 'a session that moved on is left alone')
        p.kill()
        os.environ['AGENT_RUNNER_IDLE_MAX'] = '60'
        os.environ['AGENT_RUNNER_SLOT'] = f'9{os.getpid()}'  # its own mark: parallel gates share the notes dir
        t.write_text('{"type":"user"}\n', encoding='utf-8')
        mark = R.finished_mark()
        mark.touch()
        p = subprocess.Popen(agent_with_child(30))
        time.sleep(0.3)
        t0 = time.time()
        R.stop_waiter(p.pid, str(t), 1, 0)
        took = time.time() - t0
        check(p.wait(5) is not None and took < 3, 'after a successful done a leftover background command does not hold it', took)
        mark.unlink()
        gone = subprocess.Popen([sys.executable, '-c', 'pass'])
        gone.wait()
        t0 = time.time()
        R.stop_waiter(gone.pid, str(t), 1, 3600)
        took = time.time() - t0
        check(took < 2, 'a waiter whose session is already gone returns at once, not after the grace', took)
        p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.5)'])
        t0 = time.time()
        R.stop_waiter(p.pid, str(t), 1, 3600)
        took = time.time() - t0
        p.wait(5)
        check(took < 3, 'and one whose session ends during the grace returns once it has', took)
    finally:
        R.WAITER_POLL = poll
        os.environ.pop('AGENT_RUNNER_IDLE_MAX', None)
        os.environ.pop('AGENT_RUNNER_SLOT', None)
        if (m := R.finished_mark('9')) and m.exists():
            m.unlink()


def test_stop_hook_grace(tmp: Path):
    print('the stop hook gives background tasks a long grace, but not once the task is done')
    import io
    t = tmp / 'transcript.jsonl'
    t.write_text('{"type":"user"}\n', encoding='utf-8')
    seen, spawn, stdin = [], R.plat.spawn_detached, sys.stdin
    was_runner = os.environ.get('AGENT_RUNNER')
    R.plat.spawn_detached = lambda argv: seen.append(argv[-1])
    os.environ['AGENT_RUNNER'] = '1'
    os.environ['AGENT_RUNNER_SLOT'] = f'9{os.getpid()}'  # its own mark: parallel gates share the notes dir
    try:
        for done in (False, True):
            if done:
                R.finished_mark().touch()
            sys.stdin = io.StringIO(json.dumps({'transcript_path': str(t), 'background_tasks': [{'id': 'b1'}]}))
            R.stop_hook(90)
        eq(seen, ['1800', '5'], 'idle handed to the waiter: before done, and 5 s once done succeeded')
    finally:
        R.plat.spawn_detached, sys.stdin = spawn, stdin
        R.finished_mark().unlink(missing_ok=True)
        os.environ.pop('AGENT_RUNNER_SLOT', None)
        if was_runner is None:
            os.environ.pop('AGENT_RUNNER', None)
        else:
            os.environ['AGENT_RUNNER'] = was_runner
        if (m := R.finished_mark('9')) and m.exists():
            m.unlink()


def test_land_waits_aloud(repo: Path):
    print('run: a tested merge that waits on edits in the main checkout says so, then lands')
    import threading
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    d = R.SLOTS_DIR / 's1'
    git(d, 'checkout', '-q', '--detach', 'main')
    (d / 'g.py').write_text('# g, from the branch\n', encoding='utf-8')
    git(d, 'commit', '-qam', 'W1: g')
    merged = git(d, 'rev-parse', 'HEAD')
    git(d, 'checkout', '-q', '--detach')
    (repo / 'g.py').write_text('# g, somebody editing\n', encoding='utf-8')
    sleep, R.time.sleep = R.time.sleep, lambda s: sleep(min(s, 0.05))
    try:
        out: list = []
        t = threading.Thread(target=lambda: out.append(R.land('W1', 'main', merged)))
        t.start()
        for _ in range(100):
            if 'STOPPED: W1 cannot land' in (repo / '.runner/run.log').read_text():
                break
            sleep(0.05)
        has((repo / '.runner/run.log').read_text(),
            r'STOPPED: W1 cannot land: uncommitted edits in \S+: .* to g\.py, which the merge changes',
            'a loud STOPPED names the edited file the merge needs, before an hour of silence')
        has((repo / '.runner/run.log').read_text(), r'STOPPED: W1 .*Next time, `\S+ take --here',
            'and says how to keep such edits out of the main checkout next time')
        check(t.is_alive(), 'and it still waits for them')
        git(repo, 'checkout', '--', 'g.py')
        t.join(10)
    finally:
        R.time.sleep = sleep
    eq(out, [None], 'once the edit is gone it lands')
    eq((repo / '.runner/run.log').read_text().count('STOPPED: W1'), 1, 'said once, not every 10 s')


def test_edited_elsewhere(repo: Path, tmp: Path):
    print("run: a task heading into uncommitted edits outside the runner's slots is named in the log")
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    hand = tmp / 'hand-worktree'
    git(repo, 'worktree', 'add', '-q', '--detach', str(hand), 'main')
    s1 = R.SLOTS_DIR / 's1'
    git(s1, 'checkout', '-q', '--detach', 'main')
    try:
        (hand / 'g.py').write_text('# g, edited by hand\n', encoding='utf-8')
        (s1 / 'f.py').write_text('# f, a slot of its own\n', encoding='utf-8')
        fix = R.worktree('fix9', 'main')
        (fix / 'g.py').write_text('# g, a fix ahead of the lock\n', encoding='utf-8')
        eq(R.edited_elsewhere({'g.py', 'f.py', 'h.py'}), [f'{hand} (g.py)'],
           "a hand worktree's edit is named; a runner slot's or fix worktree's is its own business")
        git(repo, 'worktree', 'remove', '--force', str(fix))
        (repo / 'f.py').write_text('# f, in the main checkout\n', encoding='utf-8')
        has('\n'.join(R.edited_elsewhere({'f.py'})), rf'^{re.escape(str(repo))} \(f\.py\)$', 'the main checkout counts too')
        eq(R.edited_elsewhere({'h.py'}), [], 'files nobody edits: nothing')
        eq(R.edited_elsewhere(set()), [], 'a task with no files: nothing')
        gone = tmp / 'gone-worktree'
        git(repo, 'worktree', 'add', '-q', '--detach', str(gone), 'main')
        shutil.rmtree(gone)
        eq(R.edited_elsewhere({'h.py'}), [], 'a worktree whose folder was deleted is skipped, not a crash')
        git(repo, 'worktree', 'prune')
    finally:
        git(repo, 'checkout', '--', 'f.py')
        git(s1, 'checkout', '--', 'f.py')
        git(repo, 'worktree', 'remove', '--force', str(hand))


def test_resume(repo: Path, tmp: Path):
    print('run: a session cut off by a dropped network or a reboot resumes in its own slot')
    R.init(repo)
    ts = {}
    transcript, R.transcript = R.transcript, lambda sid: ts.get(sid)

    def said(sid: str, *entries: dict) -> str:
        ts[sid] = str(tmp / f'{sid}.jsonl')
        Path(ts[sid]).write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
        return sid

    ask = {'type': 'user', 'message': {'role': 'user', 'content': 'do T2'}}
    tool = {'type': 'assistant', 'message': {'stop_reason': 'tool_use', 'content': [{'type': 'tool_use'}]}}
    result = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result'}]}}
    end = {'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'done'}]}}

    def error(text: str, kind: str = 'server_error') -> dict:
        return {'type': 'assistant', 'isApiErrorMessage': True, 'error': kind,
                'message': {'stop_reason': 'stop_sequence', 'content': [{'type': 'text', 'text': text}]}}

    dns = "API Error: Can't reach the API server — check your internet or DNS (EAI_AGAIN)"
    try:
        has(R.cut_off(said('net', ask, tool, result, error(dns))) or '', 'EAI_AGAIN',
            'an API error that ended the turn is a cut-off, and says what the API said')
        eq(R.cut_off(said('fin', ask, tool, result, end)), None, 'a turn that ended is not')
        has(R.cut_off(said('lim', ask, error("You've hit your limit · resets 3pm", 'rate_limit'))) or '',
            'hit your limit', 'a usage limit is a cut-off too: the session resumes like any other (C7)')
        eq(R.cut_off(said('bad', ask, error('prompt is too long', 'invalid_request'))), None,
           'nor a request the API refused, which would fail again')
        eq(R.cut_off(said('mid', ask, tool, result)), None, 'a transcript that stops mid-turn is no cut-off ...')
        has(R.cut_off('mid', mid_turn=True) or '', 'mid-turn', '... but at startup it is: the machine went down')
        flags = R.agent_flags('net', 'opus', 90, resume=True)
        check(flags[:2] == ['--resume', 'net'] and '--session-id' not in flags,
              'a resume passes --resume <id> and no --session-id, which Claude Code refuses beside it', flags)

        # T2 was cut off in slot 2, and the run then saved its edits on wip/T2 and gave the slot to T5
        d = task_branch(repo, 2, 'T2')
        (C := R.C.notes('slot2.log')).write_text('\n=== 2026-10-23T08:00:00 T2 session net\n', encoding='utf-8')
        eq(R.last_session('T2'), (2, 'net'), 'the slot logs name the session and its slot')
        (d / 'b.py').write_text('# b, half done\n', encoding='utf-8')
        (d / 'new.py').write_text('# new\n', encoding='utf-8')
        eq(R.save_leftovers(d, 'T2', 'main'), 'wip/T2', '(the old runner saved them on wip/T2)')
        git(d, 'reset', '-q', '--hard')
        git(d, 'clean', '-fdq')
        git(d, 'checkout', '-q', '-B', 'task/T5', 'main')
        git(repo, 'branch', '-D', 'task/T2')
        R.queue_resume('T2', 2, 'net', 'resumed by hand')
        eq(R.queued(), {2: ('T2', 'net', 'resumed by hand')}, 'a queued resume is kept in the notes')
        check('T2' not in [t[0] for t in [R.pick({}, set(), 'main')] if t], 'and no slot starts that task afresh')
        opened = []

        class Mux:
            name = 'fake'

            def open(self, *a, **kw):
                opened.append((a, kw))
                return 4242

            def where(self, n):
                return f'slot {n}'

        mux, R.MUX = R.MUX, Mux()
        try:
            got = R.resume(2, 'T2', 'net', 'resumed by hand', 'main', 'opus', 90)
        finally:
            R.MUX = mux
        eq(got[:2], (4242, 'net'), 'resume opens the session in its own slot')
        check(opened and opened[0][1].get('resume') is True and opened[0][0][1] == d,
              'with --resume, in the worktree the transcript names', opened)
        has(opened[0][0][2], r'cut off \(resumed by hand\).*task T2', 'and a first turn that says what happened')
        eq(git(d, 'branch', '--show-current'), 'task/T2', 'the slot is back on task/T2')
        eq((git(d, 'rev-parse', 'HEAD'), (d / 'b.py').read_text(), (d / 'new.py').read_text()),
           (git(repo, 'rev-parse', 'main'), '# b, half done\n', '# new\n'),
           'with the saved edits uncommitted again, as the session left them')
        check(git(repo, 'branch', '--list', 'wip/T2') == '' and git(repo, 'branch', '--list', 'resumed/T2') != '',
              'wip/T2 is kept as resumed/T2, so no later attempt reads it as a failed one')
        has(C.read_text(), r'=== \S+ T2 resume net \(resumed by hand\)', 'the slot log has a resume header')
        eq(R.resumes(2, 'net'), 1, 'which counts the resumes, against RESUMES_MAX')
        eq(R.last_session('T2'), (2, 'net'), 'and the session is still the one a later resume finds')

        # a reboot: the session in slot 2 stopped mid-turn and no run saw it end
        R.C.notes('T2.resume').unlink()
        said('net', ask, tool, result)
        R.queue_cut_off('main', [1, 2, 3])
        eq(R.queued(), {2: ('T2', 'net', 'its transcript stops mid-turn')}, 'at startup a slot cut off mid-turn is queued')
        has((repo / '.runner/run.log').read_text(), r'slot 2: T2 was cut off while no run was up', 'and logged')
        R.C.notes('T2.resume').unlink()
        if R.plat.WINDOWS:
            said('net', ask, tool, result, end)
            R.queue_cut_off('main', [2])
            eq(R.queued(), {}, 'a completed session is not resumed on Windows')
        else:
            alive = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()', '--resume', 'net'],
                                     stdin=subprocess.PIPE)
            try:
                eq(R.queue_cut_off('main', [2]), {2: alive.pid},
                   'but one whose session still runs in an untagged pane is held')
                eq(R.queued(), {}, 'and not resumed: that would be a second agent in its worktree')
                has((repo / '.runner/run.log').read_text(), r'slot 2: T2.s session still runs \(pid \d+\)', 'logged')
            finally:
                alive.communicate(b'')
            said('net', ask, tool, result, end)
            R.queue_cut_off('main', [2])
            eq(R.queued(), {}, 'one that ended its turn is left to the merge')
        eq(run(repo, 'resume', 'T9').returncode, 1, '`resume` refuses a task that is not open')
        has(run(repo, 'resume', 'T2').stderr, 'transcript of its session net is gone',
            '`resume` refuses a session whose transcript is gone (this process alone has the fakes)')
        here = os.getcwd()
        os.chdir(repo)
        try:
            eq(R.cmd_resume(['T2']), 0, '`resume T2` queues it')
        finally:
            os.chdir(here)
        eq(R.queued(), {2: ('T2', 'net', 'resumed by hand')}, 'for slot 2, where it ran')
        R.C.notes('T2.resume').unlink()
    finally:
        R.transcript = transcript
        git(d, 'reset', '-q', '--hard')
        git(d, 'clean', '-fdq')
        git(d, 'checkout', '-q', '--detach')
        git(repo, 'branch', '-D', 'task/T2', 'task/T5', 'resumed/T2')
        R.C.notes('slot2.log').unlink(missing_ok=True)


def test_merge_ahead(repo: Path):
    print('run: a task that finishes during a gate is merged on top of it and tested beside it')
    if R.plat.WINDOWS:
        return  # merge_gate runs `gate` there, with no record another turn can wait on
    R.init(repo)
    ran = R.SLOTS_DIR / 'gate-ran.log'
    test, R.C.run['test'] = R.C.run['test'], f'sleep 2; echo ok >> {ran}'
    poll, R.AHEAD_POLL = R.AHEAD_POLL, 0.2
    try:
        commit_on(repo, 'H1', {'h1.py': '1\n'}, 'H1: one')
        first = R.threading.Thread(target=R.merge, args=('H1', 'main'))
        first.start()
        R.time.sleep(1)  # H1's gate is running
        commit_on(repo, 'H2', {'h2.py': '2\n'}, 'H2: two')
        second = R.threading.Thread(target=R.merge, args=('H2', 'main'))
        second.start()
        first.join(60), second.join(60)
        log = (repo / '.runner/run.log').read_text()
        has(log, r'H2: merged ahead on the merge under test', 'H2 was built on H1 during its gate')
        has(log, r'H2: reusing the merge already built and gated', 'and its turn took that merge')
        check((repo / 'h1.py').exists() and (repo / 'h2.py').exists(), 'both landed')
        eq(ran.read_text().count('ok'), 2, 'two gate runs, side by side, not a third after H1 landed')
    finally:
        R.C.run['test'], R.AHEAD_POLL = test, poll
        ran.unlink(missing_ok=True)


def test_adopted_gate_merge(repo: Path):
    print('run: a merge whose gate passed under an earlier run lands as it was, plan commits since or not')
    if R.plat.WINDOWS:
        return
    R.init(repo)
    ran = R.SLOTS_DIR / 'gate-ran.log'
    test, R.C.run['test'] = R.C.run['test'], f'echo ok >> {ran}'
    untested, R.C.run['untested'] = R.C.run['untested'], ['plan/*', '*.md']
    try:
        commit_on(repo, 'Y1', {'y1.py': '1\n'}, 'Y1: one')
        d = R.worktree('merge', 'main')
        base = git(repo, 'rev-parse', 'main')
        git(d, 'checkout', '-q', '--detach', base)
        git(d, 'merge', '-q', '--no-edit', 'task/Y1')
        eq(R.merge_gate('Y1', d, R.merge_env(), {'base': base, 'tids': ['Y1']})[0], 0, 'the earlier run\'s gate')
        # as if it was still running when that run ended: the record outlives it
        rec = R.C.notes(R.GATES) / f'{R.gate_key(d)}.json'
        rec.write_text(R.json.dumps({'tid': 'Y1', 'pid': 999999999, 'out': str(rec.with_suffix('.out')),
                                     'until': 0, 'cwd': str(d), 'rec': str(rec), 'base': base, 'tids': ['Y1'],
                                     'head': git(d, 'rev-parse', 'HEAD')}))
        git(d, 'checkout', '-q', '--detach', base)
        (repo / 'plan/TODO.md').write_text((repo / 'plan/TODO.md').read_text() + '\n')
        git(repo, 'commit', '-qam', 'plan: a note meanwhile')
        commit_on(repo, 'Y2', {'y2.py': '2\n'}, 'Y2: two')
        R.WAITING.add('Y2')  # finished meanwhile: not in the gated merge
        eq(R.merge('Y1', 'main'), None, 'it lands')
        has((repo / '.runner/run.log').read_text(), r'Y1: reusing the merge already built and gated',
            'the adopted merge is reused')
        eq(ran.read_text().count('ok'), 1, 'the gate is not run again')
        check((repo / 'y1.py').exists() and not (repo / 'y2.py').exists(), 'Y2 waits for its own turn')
        R.WAITING.discard('Y2')
        eq(R.merge('Y2', 'main'), None, 'which lands after')
    finally:
        R.C.run['test'], R.C.run['untested'] = test, untested
        ran.unlink(missing_ok=True)


def test_adopted_gate_results(repo: Path):
    print('run: a gate that failed, or ended, while no run was up counts as it ended')
    if R.plat.WINDOWS:
        return
    R.init(repo)
    ran = R.SLOTS_DIR / 'gate-ran.log'
    test, R.C.run['test'] = R.C.run['test'], f'echo ok >> {ran}; test -e only_gate_fail && exit 3; true'
    try:
        d = R.worktree('merge', 'main')
        git(d, 'checkout', '-q', '--detach', 'main')
        gates = R.C.notes(R.GATES)
        gates.mkdir(exist_ok=True)
        out = gates / f'{R.gate_key(d)}.out'
        rec = out.with_suffix('.json')
        # ended while no run was up: its exit code is on disk, its record still names it
        out.write_text('FAIL t_x\n'), out.with_suffix('.rc').write_text('3\n')
        rec.write_text(R.json.dumps({'tid': 'W1', 'pid': 999999999, 'out': str(out), 'until': 0, 'cwd': str(d),
                                     'rec': str(rec)}))
        eq(R.merge_gate('W1', d, R.merge_env()), (3, 'FAIL t_x'), 'a gate that ended unwatched counts')
        check(not ran.exists(), 'and is not run again')
        check(out.with_suffix('.failed').exists() and not rec.exists(), 'its output is kept, its record gone')
        # adopted while running, it fails: the merge's turn goes from that result
        commit_on(repo, 'W2', {'w2.py': '2\n'}, 'W2: two')
        base = git(repo, 'rev-parse', 'main')
        git(d, 'merge', '-q', '--no-edit', 'task/W2')
        out = gates / f'{R.gate_key(d)}.out'
        rec = out.with_suffix('.json')
        with open(out, 'w') as fh:
            p = R.sp.Popen(f'(sleep 1; echo FAIL t_y; exit 3\n); echo $? > {out.with_suffix(".rc")}', shell=True,
                           cwd=str(d), stdout=fh, stderr=R.sp.STDOUT, start_new_session=True)
        rec.write_text(R.json.dumps({'tid': 'W2', 'pid': p.pid, 'out': str(out), 'until': R.time.time() + 60,
                                     'cwd': str(d), 'rec': str(rec), 'base': base, 'tids': ['W2'],
                                     'head': git(d, 'rev-parse', 'HEAD')}))
        R.adopt_merge(d)
        p.wait()
        has((repo / '.runner/run.log').read_text(), r'W2: the adopted gate on W2 failed \(exit 3\)', 'said so')
        eq(len(R.AHEADS), 1, 'its merge is kept for its turn')
        eq(R.merge_gate('W2', d, R.merge_env()), (3, 'FAIL t_y'), 'which goes from that failure')
        check(not ran.exists(), 'without a gate run of its own')
        R.AHEADS.clear()
        git(repo, 'branch', '-D', 'task/W2')
    finally:
        R.C.run['test'] = test
        ran.unlink(missing_ok=True)


def test_gate_since(repo: Path):
    print('run: with test_since a merge tests what changed since its base, the whole test once a day')
    if R.plat.WINDOWS:
        return
    R.init(repo)
    ran = R.SLOTS_DIR / 'gate-ran.log'
    saved = dict(R.C.run)
    R.C.run.update(test=f'echo full >> {ran}', test_since=f'echo since {{base}} >> {ran}', full_every_hours=24)
    last = R.C.notes(R.GATES) / R.FULL_PASS
    try:
        d = R.worktree('merge', 'main')
        git(d, 'checkout', '-q', '--detach', 'main')
        base = git(repo, 'rev-parse', 'main')
        last.unlink(missing_ok=True)
        eq(R.gate_cmd(base), (R.C.run['test'], True), 'no whole test passed yet: the whole test')
        eq(R.merge_gate('V1', d, R.merge_env(), {'base': base, 'tids': ['V1']})[0], 0, 'which passes')
        check(last.exists(), 'and is remembered')
        eq(R.gate_cmd(''), (R.C.run['test'], True), 'no base: the whole test')
        eq(R.gate_cmd(base), (f'echo since {base} >> {ran}', False), 'a fresh whole pass: only what changed')
        commit_on(repo, 'V2', {'v2.py': '2\n'}, 'V2: two')
        git(d, 'merge', '-q', '--no-edit', 'task/V2')
        eq(R.merge_gate('V2', d, R.merge_env(), {'base': base, 'tids': ['V2']})[0], 0, 'the selective gate')
        eq(ran.read_text().split('\n')[:2], ['full', f'since {base}'], 'ran with its base')
        has((repo / '.runner/run.log').read_text(), r'V2: the gate tests what changed since', 'and said so')
        os.utime(last, (0, 0))
        eq(R.gate_cmd(base)[1], True, 'a day on: the whole test again')
        R.C.run['full_every_hours'] = 0
        eq(R.gate_cmd(base)[1], False, 'unless full_every_hours is 0')
        git(repo, 'branch', '-D', 'task/V2')
    finally:
        R.C.run.clear(), R.C.run.update(saved)
        ran.unlink(missing_ok=True)


def test_gate_catch_up(repo: Path):
    print('run: the shared branch got code during a gate: only what it got is tested, from the tested merge')
    if R.plat.WINDOWS:
        return
    R.init(repo)
    ran, flag = R.SLOTS_DIR / 'gate-ran.log', R.SLOTS_DIR / 'gate-moved'
    saved = dict(R.C.run)
    move = (f'if [ ! -e {flag} ]; then touch {flag}; cd {repo} && echo 1 > m.py && git add m.py && '
            f'git commit -qm "M: meanwhile" >/dev/null; fi')
    R.C.run.update(test=f'echo full >> {ran}', test_since=f'echo since {{base}} >> {ran}; {move}',
                   full_every_hours=24, merge_ahead=False)
    last = R.C.notes(R.GATES) / R.FULL_PASS
    last.parent.mkdir(exist_ok=True)
    last.touch()
    try:
        commit_on(repo, 'U1', {'u1.py': '1\n'}, 'U1: one')
        base = git(repo, 'rev-parse', 'main')
        eq(R.merge('U1', 'main'), None, 'it lands')
        lines = ran.read_text().split()
        eq(len(lines), 4, 'two gates: the merge, then what main got during it')
        eq(lines[1], base, 'the first from main as it was')
        merged = lines[3]
        check(lines[3] != base and git(repo, 'merge-base', '--is-ancestor', merged, 'main') == '',
              'the second from the tested merge, which landed under it')
        check((repo / 'm.py').exists() and (repo / 'u1.py').exists(), 'with both')
        has((repo / '.runner/run.log').read_text(), r'U1: main got code commits during the tests \(m.py\); testing',
            'said so')
    finally:
        R.C.run.clear(), R.C.run.update(saved)
        ran.unlink(missing_ok=True), flag.unlink(missing_ok=True)


def test_owed_merge_goes_first(repo: Path):
    print('run: a turn that finds a merge already gated for other waiting tasks gives the turn up to them')
    R.init(repo)
    base = git(repo, 'rev-parse', 'main')
    a = {'base': base, 'tids': ['OA', 'OB'], 'merged': base}
    R.AHEADS[:] = [a]
    R.WAITING.update({'OA', 'OB'})
    try:
        eq(R.merge_batch('OC', 'main'), R.LATER, 'the turn is given up')
        eq(R.AHEADS, [a], 'and the gated merge is kept')
        eq(R.owed('OA', base), None, 'a task in that merge takes its own turn')
        R.WAITING.discard('OB')
        eq(R.owed('OC', base), None, 'not when one of its tasks is not waiting')
        R.WAITING.add('OB')
        eq(R.merge_rank('OA', False) < R.merge_rank('OC', False), True, 'its tasks rank ahead of the one that gave way')
    finally:
        R.AHEADS.clear()
        R.WAITING.difference_update({'OA', 'OB'})


def test_copies(repo: Path):
    print('run: [run] copies puts its own copy of a git-ignored file in a new worktree')
    R.init(repo)
    (repo / 'local.cfg').write_text('mine\n')
    copies, R.C.run['copies'] = R.C.run['copies'], ['local.cfg']
    try:
        d = R.worktree('copytest', 'main')
        check((d / 'local.cfg').is_file() and not (d / 'local.cfg').is_symlink(), 'a copy, not a link')
        (d / 'local.cfg').write_text('changed\n')
        R.worktree('copytest', 'main')
        eq((d / 'local.cfg').read_text(), 'changed\n', 'and it is not copied over again')
    finally:
        R.C.run['copies'] = copies
        (repo / 'local.cfg').unlink()
        git(repo, 'worktree', 'remove', '--force', str(d))


def test_land_gives_merge_back(repo: Path):
    print('run: a tested merge blocked by edits gives MERGE back after LAND_WAIT, and the branch knows when it is free')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    git(repo, 'branch', '-f', 'task/W2', 'main')
    d = R.SLOTS_DIR / 's1'
    git(d, 'checkout', '-q', 'task/W2')
    (d / 'h.py').write_text('# h, from the branch\n', encoding='utf-8')
    git(d, 'add', 'h.py')
    git(d, 'commit', '-qm', 'W2: h')
    merged = git(d, 'rev-parse', 'HEAD')
    git(d, 'checkout', '-q', '--detach')
    (repo / 'h.py').write_text('# h, somebody writing it too\n', encoding='utf-8')
    wait, R.LAND_WAIT = R.LAND_WAIT, 0
    try:
        why = R.land('W2', 'main', merged)
        check(why is not None and why.startswith(R.EDITED), f'it gives up with the edits why, which finish() keeps the branch for ({why})')
        check(R.blocked_by_edits('W2', 'main'), 'the edited file is one task/W2 changes')
        (repo / 'h.py').unlink()
        check(not R.blocked_by_edits('W2', 'main'), 'once the edit is gone the branch may merge again')
        (repo / 'other.py').write_text('# not the branch\'s\n', encoding='utf-8')
        check(not R.blocked_by_edits('W2', 'main'), 'edits to files the branch does not touch never hold it')
        git(repo, 'add', 'other.py')
        check(R.blocked_by_edits('W2', 'main'), 'staged ones do: git merges onto no index but HEAD\'s')
        has((repo / '.runner/run.log').read_text(), r'STOPPED: W2 is not merging: staged changes in the main checkout: .* block the merge',
            'and the log says so')
        git(repo, 'rm', '-q', '--cached', 'other.py')
        (repo / 'other.py').unlink()
        git(repo, 'checkout', '-q', '-b', 'mine')
        why = R.land('W2', 'main', merged) or ''
        check(why.startswith(R.ELSEWHERE), f'a main checkout with another branch out is not merged into ({why})')
        eq(git(repo, 'branch', '--show-current'), 'mine', 'nor switched to main under whoever works there')
        check(R.blocked_by_edits('W2', 'main'), 'and the branch waits until main is out again')
        git(repo, 'checkout', '-q', 'main')
        git(repo, 'branch', '-D', 'mine')
        check(not R.blocked_by_edits('W2', 'main'), 'then it may merge')
    finally:
        R.LAND_WAIT = wait
        git(repo, 'branch', '-D', 'task/W2')


def test_session_tmp(repo: Path, tmp: Path):
    print("an ended session's temp folder is deleted, and stale ones of this repo are swept")
    R.init(repo)
    root = tmp / 'tmproot'
    os.environ['CLAUDE_CODE_TMPDIR'] = str(root)
    sid = lambda: str(__import__('uuid').uuid4())
    mine, slot, other, sibling = (root / 'claude-1' / R.project_slug(p)
                                  for p in (R.ROOT, R.SLOTS_DIR / 's1', tmp / 'elsewhere', tmp / 'proj-slots-foo'))

    def folder(proj: Path, s: str, age: float = 0) -> Path:
        d = proj / s / 'scratchpad' / 'target'
        d.mkdir(parents=True)
        (d / 'big').write_bytes(b'x' * 1000)
        old = time.time() - age
        for p in [d / 'big', d, d.parent, d.parent.parent]:
            os.utime(p, (old, old))
        return proj / s

    day = R.SESSION_TMP_KEEP + 60
    try:
        ended = folder(slot, sid())
        R.drop_session_tmp(ended.name)
        check(not ended.exists(), "a session that ended for good loses its temp folder")
        if R.plat.WINDOWS:
            stale = folder(slot, sid(), day)
            R.sweep_tmp(force=True)
            check(stale.exists(), 'Windows leaves stale session temp folders for the OS to clean up')
            return
        stale, fresh, foreign = folder(slot, sid(), day), folder(slot, sid(), day), folder(other, sid(), day)
        person, near = folder(mine, sid(), day), folder(sibling, sid(), day)
        (fresh / 'scratchpad' / 'new').write_text('just written')
        live_sid, queued_sid = sid(), sid()
        live, waits = folder(slot, live_sid, day), folder(slot, queued_sid, day)
        agent = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '--session-id', live_sid])
        R.queue_resume('T9', 1, queued_sid, 'cut off')
        time.sleep(0.2)
        R.sweep_tmp(force=True)
        check(not stale.exists(), "a slot's session that nothing wrote to in a day is swept")
        check(person.exists(), "the main checkout's is not: an interactive session there names no session id")
        check(near.exists(), "nor a sibling repo's whose name starts like the slots folder's")
        check(fresh.exists(), 'one with a file written inside the day is kept')
        check(live.exists(), 'one whose agent still runs is kept')
        check(waits.exists(), 'one queued to resume is kept')
        check(foreign.exists(), "another project's sessions are not the runner's to sweep")
        R.sweep_tmp()
        agent.kill()
    finally:
        os.environ.pop('CLAUDE_CODE_TMPDIR', None)
        R.C.notes('T9.resume').unlink(missing_ok=True)


def test_tested_ref(repo: Path, tmp: Path):
    print("run: a merge skips the gate only for the tree done's gate passed on; a failed commit ticks nothing")
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text().replace('### Stretch', '- [ ] **G1** gated | files: g1.py\n\n### Stretch'))
    git(repo, 'commit', '-qam', 'plan: G1')
    d = task_branch(repo, 1, 'G1')
    (d / 'g1.py').write_text('# g1\n', encoding='utf-8')
    hooks = tmp / 'hooks'
    hooks.mkdir()
    (hooks / 'pre-commit').write_text('#!/bin/sh\nexit 1\n')
    (hooks / 'pre-commit').chmod(0o755)
    git(repo, 'config', 'core.hooksPath', str(hooks))
    r = run(d, 'done', 'G1', 'G1: g1')
    git(repo, 'config', '--unset', 'core.hooksPath')
    check(r.returncode == 1 and 'git commit failed' in r.stderr, 'a commit that fails fails done', r.stdout + r.stderr)
    check('- [ ] **G1**' in (d / 'plan/TODO.md').read_text(), 'and leaves the task open, so done can run again')
    r = run(d, 'done', 'G1', 'G1: g1')
    check(r.returncode == 0, 'which it then does', r.stdout + r.stderr)
    eq(git(repo, 'rev-parse', 'refs/agent-runner/tested/G1'), git(repo, 'rev-parse', 'task/G1'),
       'done records what its gate passed on, seen from the main checkout too')
    git(d, 'checkout', '-q', '--detach')
    calls: list = []
    gate_was = R.merge_gate
    R.merge_gate = lambda *a, **k: calls.append(1) or gate_was(*a, **k)
    R.C.run['repair_merges'] = False
    try:
        eq(R.merge('G1', 'main'), None, 'the gated branch lands')
        eq(calls, [], 'without a second gate run: it differs from what done tested only in the archived plan')
        check(git(repo, 'for-each-ref', 'refs/agent-runner/tested/G1') == '', 'and its tested ref goes with the branch')
        commit_on(repo, 'G2', {'BROKEN': ''}, 'G2: never ran done')
        has(R.merge('G2', 'main') or '', r'tests fail after the merge',
            'a branch done never gated is tested, though the merge is a fast-forward')
        check(not (repo / 'BROKEN').exists(), 'and stays off main')
    finally:
        R.merge_gate = gate_was
        R.C.run['repair_merges'] = True
        git(repo, 'branch', '-D', 'task/G2')


def test_docs_only_gate(repo: Path):
    print("run: a merge whose diff is all [run] docs_files skips the gate (F37); a mixed one runs it")
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    calls: list = []
    gate_was = R.merge_gate
    R.merge_gate = lambda *a, **k: calls.append(1) or gate_was(*a, **k)
    R.C.run['repair_merges'] = False
    saved = R.C.run['docs_files'], R.C.run['docs_check']
    try:
        eq(saved[0], ['*.md', 'docs/**'], 'docs_files defaults to markdown and docs/')
        check(R.docs_only(['README.md', 'docs/img/a.png'], saved[0]) and not R.docs_only(['README.md', 'a.py'], saved[0])
              and not R.docs_only([], saved[0]) and not R.docs_only(['docs/x.py'], ['docs/**', '!*.py']),
              'docs_only: every file matches, at least one, and !glob takes one back')
        (R.worktree(1, 'main') / 'docs').mkdir(exist_ok=True)  # commit_on writes into slot 1
        commit_on(repo, 'H1', {'BROKEN.md': 'a doc\n', 'docs/guide.txt': 'more\n'}, 'H1: docs only (a B fix, say)')
        eq(R.merge('H1', 'main'), None, 'a docs-only branch done never gated lands')
        eq(calls, [], 'without the gate')
        has((repo / '.runner/run.log').read_text(), r'H1: docs only, gate skipped', 'and the log says so')
        commit_on(repo, 'H2', {'notes.md': 'doc\n', 'BROKEN': ''}, 'H2: docs and code (a D task that touches code)')
        has(R.merge('H2', 'main') or '', r'tests fail after the merge', 'a mixed diff runs the gate')
        eq(len(calls), 1, 'once')
        check(not (repo / 'BROKEN').exists(), 'and stays off main')
        R.C.run['docs_check'] = 'echo dead link: docs/a.md#gone && exit 3'
        commit_on(repo, 'H3', {'docs/a.md': '[x](#gone)\n'}, 'H3: a broken anchor')
        has(R.merge('H3', 'main') or '', r'docs check fails: .*dead link', 'a docs-only merge runs [run] docs_check')
        eq(len(calls), 1, 'and still not the gate')
    finally:
        R.merge_gate = gate_was
        R.C.run['repair_merges'] = True
        R.C.run['docs_files'], R.C.run['docs_check'] = saved
        for b in ('task/H2', 'task/H3'):
            if git(repo, 'branch', '--list', b):
                git(repo, 'branch', '-D', b)


def test_blame_and_own_repair(repo: Path, tmp: Path):
    print('run: a failed batch finds the task that breaks it alone; that task\'s repair is its own session')
    R.init(repo)
    r = R.C.run
    gate = ('if exist BROKEN (echo FAIL t_b & exit /b 1)' if R.plat.WINDOWS
            else 'test ! -e BROKEN || { echo FAIL t_b; exit 1; }')
    saved = dict(test=r['test'], failures=r['failures'], retest=r['retest'], agent=r['agent'])
    r.update(test=gate, failures=r'^FAIL (\S+)', retest=gate)
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    r['agent'] = str(agent)
    original_fix_cmd = use_fake_fix_agent(agent)
    original_merge_gate = R.merge_gate
    if R.plat.WINDOWS:
        def merge_gate(tid, cwd, env, batch=None):
            result = subprocess.run(gate, shell=True, cwd=str(cwd), env=env,
                                    capture_output=True, text=True)
            return result.returncode, result.stdout + result.stderr
        R.merge_gate = merge_gate
    fork_was = R.Claude.fork_flags
    prompt = tmp / 'own-prompt.txt'
    try:
        commit_on(repo, 'C1', {'c1.py': '1\n'}, 'C1: fine')
        commit_on(repo, 'C2', {'BROKEN': ''}, 'C2: breaks the tests by itself')
        commit_on(repo, 'C3', {'c3.py': '3\n'}, 'C3: fine too')
        R.WAITING.update({'C2', 'C3'})
        os.environ['FAKE_FIX'] = 'abort'
        eq(R.merge('C1', 'main'), None, 'a batch with one broken task lands')
        log = (repo / '.runner/run.log').read_text()
        has(log, r'C1: the batch fails t_b; C2 fails them alone', 'having found the broken one by retesting each alone')
        check('C1: the batch (C1' not in log, 'with no batch repair session')
        check((repo / 'c1.py').exists() and (repo / 'c3.py').exists() and not (repo / 'BROKEN').exists(),
              'the others land together, without it')
        eq(R.ALONE, {'C2'}, 'which merges in a turn of its own')
        R.WAITING.discard('C3')
        eq(R.merge('C3', 'main'), None, 'the rider\'s turn only does the bookkeeping')
        R.WAITING.discard('C2')
        R.TASK_SID['C2'] = 'the-c2-session'
        R.Claude.fork_flags = lambda self, sid: ['--fork-of', sid]
        os.environ['FAKE_PROMPT'] = str(prompt)
        has(R.merge('C2', 'main') or '', r'tests fail after the merge', 'its own turn fails the gate')
        has(prompt.read_text(), r'^This is a copy of your own session from task C2',
            'and the repair goes to a copy of the session that did C2')
        has((repo / '.runner/run.log').read_text(), r'C2: .*the task\'s own session \(a copy of the-c2-session\)',
            'saying so')
        check(not R.ALONE and 'C2' not in R.TASK_SID, 'and what was kept about C2 is dropped')
        git(repo, 'branch', '-D', 'task/C2')

    finally:
        os.environ.pop('FAKE_FIX', None)
        os.environ.pop('FAKE_PROMPT', None)
        R.Claude.fork_flags = fork_was
        R.fix_cmd = original_fix_cmd
        R.merge_gate = original_merge_gate
        r.update(saved)


def test_red_base_and_batch_caps(repo: Path, tmp: Path):
    print('run: a test the base fails already never blames a batch\'s tasks; batch_max caps a batch')
    if R.plat.WINDOWS:
        print('  (POSIX gate only)')
        return
    R.init(repo)
    r = R.C.run
    gate = ('for f in OLDRED BROKEN X_*; do test -e "$f" || continue; case $f in OLDRED) echo FAIL t_old;; '
            'BROKEN) echo FAIL t_b;; *) echo FAIL t_x;; esac; done | sort -u > .out; cat .out; rm -f .out; '
            'test -z "$(ls OLDRED BROKEN X_* 2>/dev/null)"')
    saved = dict(test=r['test'], failures=r['failures'], retest=r['retest'], agent=r['agent'],
                 batch_max=r['batch_max'])
    r.update(test=gate, failures=r'^FAIL (\S+)', retest=gate)
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    r['agent'] = str(agent)
    original_fix_cmd = use_fake_fix_agent(agent)
    os.environ['FAKE_FIX'] = 'abort'
    try:
        (repo / 'OLDRED').write_text('', encoding='utf-8')
        git(repo, 'add', 'OLDRED')
        git(repo, 'commit', '-qm', 'main breaks t_old by itself')
        commit_on(repo, 'D1', {'d1.py': '1\n'}, 'D1: fine')
        commit_on(repo, 'D2', {'BROKEN': ''}, 'D2: breaks t_b')
        commit_on(repo, 'D3', {'d3.py': '3\n'}, 'D3: fine too')
        R.WAITING.update({'D2', 'D3'})
        eq(R.merge('D1', 'main'), None, 'a batch failing a test the base fails too, and one of its own, lands')
        log = (repo / '.runner/run.log').read_text()
        has(log, r'D1: t_old already fail without it; only t_b count against it', 'the old failure is set aside')
        has(log, r'D1: the batch fails t_b; D2 fails them alone', 'and only the task breaking the new one is blamed')
        eq(R.ALONE, {'D2'}, 'D2 alone merges in a turn of its own')
        R.BROKEN.clear()
        R.WAITING.discard('D3')
        eq(R.merge('D3', 'main'), None, 'the rider\'s turn only does the bookkeeping')
        R.ALONE.clear()
        R.WAITING.discard('D2')
        git(repo, 'branch', '-D', 'task/D2')
        git(repo, 'rm', '-q', 'OLDRED')
        git(repo, 'commit', '-qm', 'main green again')

        for i in range(1, 5):
            commit_on(repo, f'E{i}', {f'X_{i}': ''}, f'E{i}: each breaks t_x')
        R.WAITING.update({'E2', 'E3', 'E4'})
        R.merge('E1', 'main')
        log = (repo / '.runner/run.log').read_text()
        has(log, r'E1: the batch fails t_x; E1 fails them alone, so it merges', 'halving finds one culprit, and only it '
            'is set aside')
        R.ALONE.clear()
        R.WAITING.clear()
        for i in range(1, 5):
            git(repo, 'branch', '-D', f'task/E{i}')
        R.FAILED.clear()
        R.BROKEN.clear()

        r['batch_max'] = 2
        for t in ('F1', 'F2', 'F3'):
            commit_on(repo, t, {f'{t.lower()}.py': '1\n'}, f'{t}: fine')
        R.WAITING.update({'F2', 'F3'})
        eq(R.merge('F1', 'main'), None, 'a capped batch lands')
        log = (repo / '.runner/run.log').read_text()
        has(log, r'F1: merging together with F2 \(one gate run\)', 'with batch_max - 1 riders')
        check('F3' not in R.LANDED, 'the rest wait for the next batch')
        R.WAITING.discard('F2')
        eq(R.merge('F2', 'main'), None, 'the rider\'s bookkeeping')
        R.WAITING.discard('F3')
        eq(R.merge('F3', 'main'), None, 'and the next batch lands')
    finally:
        os.environ.pop('FAKE_FIX', None)
        R.fix_cmd = original_fix_cmd
        R.WAITING.clear()
        R.ALONE.clear()
        r.update(saved)


def test_reserved_ids(repo: Path):
    print('plan: an id handed out once is never handed out again, even off every checkout')
    R.init(repo)
    todo, done = repo / 'plan/TODO.md', repo / 'plan/DONE.md'
    was = todo.read_text(encoding='utf-8')
    try:
        a = P.add('Z', 'one', todo=todo, done=done)
        todo.write_text(was, encoding='utf-8')  # its branch is gone from every checkout, not merged yet
        b = P.add('Z', 'two', todo=todo, done=done)
        check(a != b, 'the next add skips the id still on an unmerged branch', f'{a} {b}')
        check({a, b} <= P.reserved(todo), 'both are held')
        eq(R._next_free('Z1', {'Z1'} | P.reserved(repo)), 'Z3', 'and a renumber skips them too')
    finally:
        todo.write_text(was, encoding='utf-8')


def test_merge_order_and_backlog(repo: Path):
    print('run: MERGE goes by rank (critical first, then a merge gated ahead); max_unmerged eases slots off')
    R.init(repo)
    lock, order = R.TurnLock(), []
    lock.acquire()

    def wait(name, rank):
        with lock.turn(lambda: rank):
            order.append(name)
    threads = []
    for name, rank in (('plain', 3), ('critical', 1), ('ahead', 2)):
        threads.append(threading.Thread(target=wait, args=(name, rank)))
        threads[-1].start()
        time.sleep(0.1)
    check(not lock.acquire(blocking=False), 'a non-blocking acquire never jumps the waiters')
    lock.release()
    for t in threads:
        t.join(10)
    eq(order, ['critical', 'ahead', 'plain'], 'waiters take the lock by rank, not by arrival')
    check(not lock.locked(), 'and leave it free')

    plan = ['### Critical: breakages', '', '- [ ] **K1** fix a red test', '', '### Later', '',
            '- [ ] **K2** (follow-up, critical) another', '- [ ] **P1** plain', '- [x] **K3** (follow-up, critical) done']
    with mock.patch.object(R, 'plan_text', lambda branch: plan):
        eq(R.criticals('main'), {'K1', 'K2'}, 'critical by section or by tag, open ones only')
    R.AHEADS.append({'base': 'x', 'tids': ['P2'], 'merged': 'y'})
    try:
        eq([R.merge_rank('P2', False), R.merge_rank('K1', True), R.merge_rank('P1', False)], [2, 1, 3],
           'critical, then built ahead, then the rest')
    finally:
        R.AHEADS.clear()

    r = R.C.run
    saved = r['max_unmerged']
    try:
        r['max_unmerged'], bm = 32, r['batch_max']
        r['batch_max'] = 16
        eq([R.backlog_slots(6, n) for n in (0, 32, 33, 40, 41, 72, 73, 200)], [6, 6, 5, 5, 4, 1, 0, 0],
           'one slot fewer for each half batch waiting past max_unmerged')
        r['batch_max'] = bm
        has(R.backlog_line(6, 3, 15), r'15 finished tasks wait.*3 of 6 slots', 'and it says so')
        r['max_unmerged'] = 0
        eq(R.backlog_slots(6, 400), 6, '0 turns it off')
    finally:
        r['max_unmerged'] = saved


def test_no_pane(repo: Path, tmp: Path):
    print('run: tmux refusing a pane fails that one start or fix session, not the run')
    R.init(repo)
    tmux, R.tmux = R.tmux, lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'no server running')
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    R.C.run['agent'], R.MASTER_PANE = (sys.executable if R.plat.WINDOWS else str(agent)), True
    try:
        eq(R.TmuxMux().open(1, repo, 'hi', 'sid', 'opus', 90, [], R.C.notes('slot1.log')), None,
           'a slot whose pane tmux will not open does not start')
        with open(tmp / 'fixer.log', 'w') as fh:
            eq(R.fix_session('fix it', repo, fh), 1, 'a fix session tmux will not open is a failed one')
        has((tmp / 'fixer.log').read_text(), r'no server running', 'and its log says why')
    finally:
        R.tmux, R.MASTER_PANE, R.C.run['agent'] = tmux, False, 'claude'


def test_other_repos_panes(repo: Path, tmp: Path):
    print('tmux: a second repo\'s runner in the same session finds only its own panes')
    R.init(repo)
    other = tmp / 'other'
    rows = [('%1', '101', 's1', str(other)),    # the other repo's
            ('%2', '102', 's2', ''),            # a slot tag with no repo: no runner's
            ('%3', '103', 's3', str(R.ROOT)),   # ours
            ('%5', '105', '', '')]              # not a runner's pane
    calls = []

    def fake(*a, **k):
        calls.append(a)
        if a[0] == 'list-panes':
            return subprocess.CompletedProcess(a, 0, ''.join('\t'.join(r) + '\n' for r in rows), '')
        if a[0] == 'list-windows':
            return subprocess.CompletedProcess(a, 0, '@1\tagents\n@2\tagents-other\n', '')
        if a[0] in ('new-window', 'split-window'):
            return subprocess.CompletedProcess(a, 0, '%9 109 @7\n', '')
        return subprocess.CompletedProcess(a, 0, '', '')
    tmux, R.tmux = R.tmux, fake
    try:
        eq(R.panes(), {'s3': ('%3', 103)}, 'only the slots tagged with this repo')
        eq(R.window('agents'), f'agents-{repo.name}', 'each repo lays out its own window')
        eq(R.pane('s1', repo, 'true'), 109, 'a pane opens')
        check(any(a[0] == 'new-window' and f'agents-{repo.name}' in a for a in calls),
              'in a new window of its own, not the other repo\'s "agents" or "agents-other"')
        check(('set-option', '-p', '-t', '%9', R.REPO_TAG, str(R.ROOT)) in calls, 'tagged with its repo')
    finally:
        R.tmux = tmux


def test_limit_resumes(repo: Path, tmp: Path):
    print('run: a slot whose session ends on a usage limit goes through the cut-off path and resumes there')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    ts, opened = {}, []
    ask = {'type': 'user', 'message': {'role': 'user', 'content': 'do it'}}
    limit = {'type': 'assistant', 'isApiErrorMessage': True, 'error': 'rate_limit',
             'message': {'stop_reason': 'stop_sequence',
                         'content': [{'type': 'text', 'text': "You've hit your limit · resets 3pm"}]}}
    end = {'type': 'assistant', 'message': {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'ok'}]}}

    class Mux:
        name = 'fake'

        def open(self, n, cwd, prompt, sid, model, idle, env, logfile, resume=False):
            opened.append((sid, resume))
            ts[sid] = str(tmp / f'{sid}.jsonl')
            Path(ts[sid]).write_text(''.join(json.dumps(e) + '\n' for e in (ask, end if resume else limit)),
                                     encoding='utf-8')
            R.ask_stop('test')  # the run ends once the resumed session has ended
            p = subprocess.Popen([sys.executable, '-c', 'pass'])
            p.wait()
            return p.pid

        def panes(self):
            return {}

        def session_id(self, pid):
            return None

        def where(self, n):
            return f'slot {n}'

    saved = R.TmuxMux, R.MUX, R.plat.mux_choice, R.time.sleep, os.environ.get('TMUX'), R.transcript
    sleep = R.time.sleep
    R.TmuxMux, R.plat.mux_choice, R.time.sleep = Mux, lambda *a, **k: 'tmux', lambda s: sleep(min(s, 0.05))
    R.transcript = lambda sid: ts.get(sid)
    os.environ['TMUX'] = 'test'
    R.C.run['agent'] = 'fake'
    here = os.getcwd()
    os.chdir(repo)
    try:
        eq(R.run(['1'], 'run'), 0, 'the run ends on its stop')
    finally:
        os.chdir(here)
        R.TmuxMux, R.MUX, R.plat.mux_choice, R.time.sleep = saved[:4]
        os.environ.pop('TMUX') if saved[4] is None else os.environ.update(TMUX=saved[4])
        R.transcript = saved[5]
        R.C.run['agent'], R.MASTER_PANE = 'claude', False
    text = (repo / '.runner/run.log').read_text()
    m = re.search(r'slot 1: (\S+) was cut off \(You\'ve hit your limit', text)
    check(m, 'the session that hit the usage limit was taken for a cut-off', text[-1500:])
    check('only hit the usage limit' not in text and 'sleeps until' not in text, 'and the slot did not sleep')
    eq([r for _, r in opened[:2]], [False, True], 'it was resumed')
    check(len(opened) >= 2 and opened[0][0] == opened[1][0], 'on the same session id', opened)
    if m:  # the resumed session committed nothing, so its finish normally drops the branch already
        subprocess.run(['git', 'branch', '-D', f'task/{m.group(1)}'], cwd=repo, capture_output=True)


def test_shared_push(repo: Path, tmp: Path):
    print('the shared branch is not merged with a remote that moved: that merge would go out untested')
    from agent_runner.gitops import push
    git(repo, 'checkout', '-q', 'main')
    clone = tmp / 'clone'
    git(tmp, 'clone', '-q', str(tmp / 'origin.git'), str(clone))
    (clone / 'theirs.txt').write_text('x\n')
    git(clone, 'add', 'theirs.txt'), git(clone, 'commit', '-qm', 'theirs'), git(clone, 'push', '-q', 'origin', 'main')
    (repo / 'ours.txt').write_text('x\n')
    git(repo, 'add', 'ours.txt'), git(repo, 'commit', '-qm', 'ours')
    head = git(repo, 'rev-parse', 'HEAD')
    has(push(repo, 'main', shared=True), r'did not push: origin/main has moved', 'the push fails, and says why')
    eq(git(repo, 'rev-parse', 'HEAD'), head, 'and main is as it was')
    print('...the next merge takes the remote\'s commits in, tests them with it, and pushes')
    R.init(repo)
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text().replace('### Stretch', '- [ ] **U1** upstream | files: u1.py\n\n### Stretch'))
    git(repo, 'commit', '-qam', 'plan: U1')
    commit_on(repo, 'U1', {'u1.py': '# u1\n'}, 'U1: u1')
    eq(R.merge('U1', 'main'), None, 'the merge lands')
    check((repo / 'theirs.txt').exists() and (repo / 'ours.txt').exists(), 'with both sides in main')
    eq(git(repo, 'rev-parse', 'main'), git(tmp / 'origin.git', 'rev-parse', 'main'), 'and main is pushed')


def test_followups(repo: Path):
    print('run: follow-up levels and kinds in the prompt, Parked never starts, flaky tests get a task')
    R.init(repo)
    p = R.prompt_for('T2', 1, 1, repo, 'main')
    has(p, r'plan add <KIND> "<text>" --files a,dir/\*\* \[--after ID\] \[--test name\] \[--pri LEVEL\]',
        'the prompt shows --files, --after and --pri')
    has(p, r'B bug: .*; F feature', 'and the id letters, from plan.KINDS with none set')
    has(p, r'passes alone is a bug in the test', 'and says a flaky test is to be made robust')
    plan_text = R.plan_text
    R.plan_text = lambda b: ['### Next', '- [ ] **T1** a', '### Parked', '- [ ] **T9** some day']
    try:
        eq([t[0] for t in R.tasks('main')], ['T1'], 'a Parked task is never offered to a run')
    finally:
        R.plan_text = plan_text
    test, R.C.run['test'] = R.C.run['test'], 'python3 -c "print(\'rerun passed: a::one, b::two\')"'
    R.C.run['flaky'] = r'^rerun passed: (.*)$'
    R.FLAKY.clear()
    try:
        eq(R.tested('T2', repo, 'HEAD'), None, 'a passing gate passes')
    finally:
        R.C.run['test'], R.C.run['flaky'] = test, ''
    eq(R.FLAKY, {'a::one': 'T2', 'b::two': 'T2'}, '[run] flaky reads the names a passing gate reran')
    head = git(repo, 'rev-parse', 'HEAD')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text(encoding='utf-8') + '- [ ] **X1** something about b::two\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'X1')
    try:
        R.reopen_landed('main', 'T2')
        text = todo.read_text(encoding='utf-8')
        has(text, r'### Next \(in this order\)\n\n(- \[ \] \*\*T\d+\*\* \(follow-up, critical\).*\n)*'
            r'- \[ \] \*\*T\d+\*\* \(follow-up, critical\) make the test `a::one` robust',
            'a flaky test gets a critical task at the top, behind earlier critical ones')
        check('`b::two` robust' not in text, 'unless an open task names it already')
        has(git(repo, 'log', '-1', '--format=%s'), r'^Plan: T\d+ to fix flaky, runaway or failing tests \(T2', 'committed on its own')
        eq(R.FLAKY, {}, 'and each is filed once')
    finally:
        git(repo, 'reset', '-q', '--hard', head)


def test_person_check_after(repo: Path):
    print('B60: a person check made to wait --after X comes back under Needs you when X lands, not to the queue')
    R.init(repo)
    head = git(repo, 'rev-parse', 'HEAD')
    todo = repo / 'plan/TODO.md'
    todo.write_text(todo.read_text(encoding='utf-8').replace(
        '### Stretch', '- [ ] **X7** upstream fix | files: x7.py\n- [ ] **R7** check it on Windows | files: r7.py\n'
        '- [ ] **R8** check it on a Mac | files: r8.py\n- [ ] **R9** sign it | files: r9.py\n\n### Stretch'),
        encoding='utf-8')
    try:
        P.block('R7', 'CONFIRM: run it on Windows and say what you saw', todo=todo)
        P.block('R7', 'needs X7 first', todo=todo, after=['X7'])  # the blocked ask itself sent to wait
        P.block('R9', 'BLOCKED: needs the signing key', todo=todo)
        P.block('R9', 'needs X7 first', todo=todo, after=['X7'])
        P.block('R8', 'DECIDE: zip or dmg?', todo=todo)
        P.change('R8', 'wait for X7, then ask me again', todo=todo)  # R6's route: change reopens it ...
        git(repo, 'commit', '-qam', 'R8 changed')
        check('R8' in [t[0] for t in R.tasks('main')], 'a change reopens the check for an agent')
        P.block('R8', 'X7 first', todo=todo, after=['X7'])  # ... then a block --after
        eq({a[1] for a in P.asks(todo)} & {'R7', 'R8', 'R9'}, set(), 'while X7 is open none is under Needs you')
        has(todo.read_text(encoding='utf-8'), r'\*\*R7\*\* .*BLOCKED: \(after X7\) CONFIRM: run it on Windows',
            'the block keeps the kind and its question')
        git(repo, 'commit', '-qam', 'plan: R7, R8, R9 wait on X7')
        P.tick('X7', todo=todo)
        git(repo, 'commit', '-qam', 'X7 landed')
        R.reopen_landed('main', 'X7')
        a = {x[1]: x for x in P.asks(todo)}
        eq([a.get(t, ('',))[0] for t in ('R7', 'R8', 'R9')], ['CONFIRM', 'DECIDE', 'BLOCKED'],
           'when X7 lands all are back under Needs you with their kind')
        eq([a[t][3] for t in ('R7', 'R8', 'R9')],
           ['run it on Windows and say what you saw', 'zip or dmg?', 'needs the signing key'], 'and their question')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(repo)}
        env.pop('AGENT_RUNNER', None)
        r = run(repo, 'plan', 'waiting', env=env)
        check(all(t in r.stdout for t in ('R7', 'R8', 'R9')), 'plan waiting lists them', r.stdout + r.stderr)
        picked = [t[0] for t in R.tasks('main')]
        check(not {'R7', 'R8', 'R9'} & set(picked), 'and no slot picks them', picked)
        has(git(repo, 'log', '-1', '--format=%s'), r'^Plan: reopen R7, R8, R9', 'the plan edit is committed')
        eq(P.confirm('R7', 'works', todo=todo), 'confirmed and ticked R7', 'the person answers it as before')
    finally:
        git(repo, 'reset', '-q', '--hard', head)


def test_ci_watch(repo: Path):
    print('run: a red workflow run on the shared branch files one critical task, once')
    from agent_runner import ci
    R.init(repo)
    runs = [{'databaseId': 7, 'status': 'completed', 'conclusion': 'failure', 'headSha': 'abc12345ff',
             'url': 'https://example/runs/7', 'displayTitle': 'T9: something', 'createdAt': '2026-11-02T13:53:00Z'},
            {'databaseId': 8, 'status': 'completed', 'conclusion': 'cancelled', 'headSha': 'f', 'url': '',
             'displayTitle': '', 'createdAt': ''},
            {'databaseId': 5, 'status': 'in_progress', 'conclusion': '', 'headSha': 'e', 'url': '',
             'displayTitle': '', 'createdAt': ''}]
    log = ('ci / test\tUNKNOWN STEP\t2026-11-02T13:54:29.1Z   The system library `alsa` was not found.\n'
           'ci / test\tUNKNOWN STEP\t2026-11-02T13:54:38.1Z ##[error]Process completed with exit code 101.\n'
           'ci / test\tUNKNOWN STEP\t2026-11-02T13:54:38.2Z Post job cleanup.\n')
    asked = []

    def gh(*a):
        asked.append(a)
        if a[:2] == ('run', 'list'):
            out = json.dumps(runs)
        elif '--log-failed' in a:
            out = log
        else:
            out = json.dumps({'jobs': [{'name': 'ci / test', 'conclusion': 'failure'},
                                       {'name': 'web', 'conclusion': 'success'}]})
        return subprocess.CompletedProcess(a, 0, out, '')
    head, real = git(repo, 'rev-parse', 'HEAD'), ci.gh_in
    ci.gh_in = lambda cwd: gh
    R.C.run['ci_watch'], R.CI_RERUN = ['pages.yml'], False
    seen = ci.seen_file(R.C.notes, 'pages.yml')
    seen.unlink(missing_ok=True)
    try:
        R.CI_AT[0] = time.time()
        eq((R.watch_ci('main'), asked), ([], []), 'not before CI_POLL has passed since the last look')
        got = R.watch_ci('main', force=True)
        eq(len(got), 1, 'the newest finished run is red (a cancelled one says nothing): one task')
        todo = (repo / 'plan/TODO.md').read_text(encoding='utf-8')
        has(todo, rf'- \[ \] \*\*{got[0]}\*\* \(follow-up, critical\) CI: `pages.yml` on main is red '
            r'\(failure, run 7 on abc12345.*failed ci / test\.', 'a critical task naming the failed jobs')
        check(got[0].startswith('B'), '[run] ci_kind, B by default')
        own = (repo / f'plan/tasks/{got[0]}.md').read_text(encoding='utf-8')
        has(own, r'Process completed with exit code 101\.\n```', 'the log tail, in the long form, to the last error')
        check('Post job cleanup' not in own and 'ci / test:   The system library' in own,
              'without the cleanup after it, nor the timestamps')
        has(git(repo, 'log', '-1', '--format=%s'), rf'^Plan: {got[0]}, `pages.yml` on main is red', 'committed')
        eq(git(repo, 'status', '--porcelain', '--', 'plan'), '', 'both files')
        eq(R.watch_ci('main', force=True), [], 'the same run is not filed twice')
        runs.insert(0, {**runs[0], 'databaseId': 10})
        eq(R.watch_ci('main', force=True), [], 'nor a newer red run while its task is open')
        eq(seen.read_text().strip(), '10', 'though it is judged')
        git(repo, 'reset', '-q', '--hard', head)
        runs.insert(0, {**runs[0], 'databaseId': 11, 'conclusion': 'success'})
        eq(R.watch_ci('main', force=True), [], 'a green run files nothing')
        runs.insert(0, {**runs[0], 'databaseId': 12, 'conclusion': 'failure'})
        n = len(asked)
        (repo / 'plan/TODO.md').write_text((repo / 'plan/TODO.md').read_text(encoding='utf-8') + '\n- [ ] **Z1** mid-edit\n',
                                          encoding='utf-8')
        eq((R.watch_ci('main', force=True), len(asked)), ([], n), 'a plan with uncommitted edits is left alone')
        git(repo, 'checkout', '-q', '--', 'plan/TODO.md')
        eq(len(R.watch_ci('main', force=True)), 1, 'a red run after the task closed files again')
        git(repo, 'reset', '-q', '--hard', head)
        runs.insert(0, {**runs[0], 'databaseId': 13, 'conclusion': 'failure'})
        runs.insert(0, {**runs[0], 'databaseId': 14, 'status': 'in_progress', 'conclusion': ''})
        eq((R.watch_ci('main', force=True), seen.read_text().strip()), ([], '12'),
           'a red run with a newer one still going: not judged until that one ends')
        runs.pop(0)
        R.CI_RERUN = True
        n = len(asked)
        eq(R.watch_ci('main', force=True), [], 'a red first attempt files nothing')
        check(('run', 'rerun', '13', '--failed') in asked[n:], 'its failed jobs are run again')
        eq(seen.read_text().strip(), '12', 'and it is judged again when the rerun ends')
        runs[0] = {**runs[0], 'attempt': 2}
        n = len(asked)
        eq(len(R.watch_ci('main', force=True)), 1, 'red on the second attempt: filed')
        check(not any(a[:2] == ('run', 'rerun') for a in asked[n:]), 'with no third try')
        has((repo / 'plan/TODO.md').read_text(encoding='utf-8'), r'is red .*\(filed \d{4}-\d\d-\d\d\)',
            'the line says the day it was filed')

        print('run: the third CI task in a week for one workflow is filed blocked on a person (B34)')
        git(repo, 'reset', '-q', '--hard', head)
        today, old = R.dt.date.today(), (R.dt.date.today() - R.dt.timedelta(days=9)).isoformat()
        done = repo / 'plan/DONE.md'
        before = done.read_text(encoding='utf-8') if done.exists() else '# DONE — the archive\n'
        closed = lambda tid, day: f'- [x] **{tid}** (follow-up, critical) CI: `pages.yml` on main is red (failure). (filed {day}) u\n'
        done.write_text(before + '\n### Next\n\n' + closed('B901', today) + closed('B800', old), encoding='utf-8')
        git(repo, 'commit', '-qam', 'one closed CI task this week, one older')
        runs.insert(0, {**runs[0], 'databaseId': 20, 'attempt': 2})
        got = R.watch_ci('main', force=True)
        has((repo / 'plan/TODO.md').read_text(encoding='utf-8'), rf'- \[ \] \*\*{got[0]}\*\* \(follow-up, critical\) CI',
            'one closed in the week (an older one does not count): filed open, as before')
        git(repo, 'reset', '-q', '--hard', head)
        done.write_text(before + '\n### Next\n\n' + closed('B901', today) + closed('B902', today) + closed('B800', old)
                        + '- [x] **B903** (follow-up, critical) CI: `other.yml` on main is red. (filed ' + str(today) + ')\n',
                        encoding='utf-8')
        git(repo, 'commit', '-qam', 'two closed CI tasks for pages.yml this week')
        runs.insert(0, {**runs[0], 'databaseId': 21, 'attempt': 2})
        got = R.watch_ci('main', force=True)
        eq(len(got), 1, 'still one task')
        has((repo / 'plan/TODO.md').read_text(encoding='utf-8'),
            rf'- \[~\] \*\*{got[0]}\*\* .*`pages.yml` on main is red.* BLOCKED: BLOCKED: `pages.yml` on main has had '
            r'2 auto-filed tasks closed in 7 days while it still fails \(B901, B902\)',
            'the third is filed blocked on a person, the earlier ids listed (not another workflow\'s)')
        eq(git(repo, 'status', '--porcelain', '--', 'plan'), '', 'committed')
        eq(R.watch_ci('main', force=True), [], 'and while it waits, nothing more is filed')
    finally:
        ci.gh_in, R.C.run['ci_watch'], R.CI_RERUN = real, [], True
        git(repo, 'reset', '-q', '--hard', head)
        seen.unlink(missing_ok=True)

    print('run: ci_watch = "auto" watches the workflows that run on a push to the shared branch')
    on = ci.runs_on_push
    check(on('on: push\n', 'main') and on('on: [push, pull_request]\n', 'main'), 'on: push, on: [push, ...]')
    check(on('on:\n  - pull_request\n  - push\n', 'main'), 'a list of events')
    check(on('on:\n  pull_request:\n  push:\n    branches: [main]\njobs:\n', 'main'), 'push with branches [main]')
    check(on('on:\n  push:\n    branches:\n      - "release/*"\n      - main\n', 'main'), 'a block list of branches')
    check(not on('on:\n  push:\n    branches: [dev]\n', 'main'), 'push to other branches only: no')
    check(on('on:\n  push:\n    branches: ["**"]\n', 'main'), 'a glob that matches')
    check(not on('on:\n  push:\n    branches-ignore: [main]\n', 'main'), 'branches-ignore that names it: no')
    check(not on('on:\n  push:\n    tags: ["v*"]\n', 'main'), 'tags only: no')
    check(on('on:\n  push: { branches: [main] }\n  schedule: [{ cron: "1 * * * *" }]\n', 'main') and
          not on('on:\n  push: { branches: [dev] }\n', 'main'), 'push: { branches: [...] } inline')
    check(on('on:\n  push:\n    paths: ["src/**"]\n', 'main'), 'paths only: every branch')
    check(not on('on:\n  schedule:\n    - cron: "0 3 * * *"\n  workflow_dispatch:\n', 'main'),
          'a nightly or manual workflow: no')
    check(not on('on:\n  pull_request:\n    branches: [main]\n', 'main'), 'pull requests only: no')
    wf = repo / '.github' / 'workflows'
    wf.mkdir(parents=True, exist_ok=True)
    (wf / 'ci.yml').write_text('name: ci\non:\n  push:\n    branches: [main]\n  pull_request:\njobs: {}\n')
    (wf / 'nightly.yaml').write_text('on:\n  schedule:\n    - cron: "0 3 * * *"\n')
    try:
        eq(ci.push_workflows(repo, 'main'), ['ci.yml'], 'the push workflows of the repository')
        R.C.run['ci_watch'] = 'auto'
        eq(R.ci_flows('main'), (['ci.yml'], 'push'), '"auto": those, push runs only')
        R.C.run['ci_watch'] = 'pages.yml'
        eq(R.ci_flows('main'), (['pages.yml'], ''), 'a name: just it, any event')
        for off in (False, [], ''):
            R.C.run['ci_watch'] = off
            eq(R.ci_flows('main'), ([], ''), f'{off!r}: off')
        R.C.run['ci_watch'] = 'auto'
        asked, said = [], []

        def blind(*a):
            asked.append(a)
            return subprocess.CompletedProcess(a, 1, '', 'HTTP 404: Not Found')
        ci.gh_in, saved = (lambda cwd: blind), R.log
        R.log = said.append
        try:
            eq(R.watch_ci('main', force=True), [], 'a gh that cannot see the repository files nothing')
            R.watch_ci('main', force=True)
        finally:
            ci.gh_in, R.log = real, saved
        eq(len([m for m in said if 'gh cannot see this repository (HTTP 404: Not Found)' in m]), 1,
           'and says so once, with why')
        check(all(a[:2] == ('repo', 'view') for a in asked), 'without asking for runs it cannot see')
    finally:
        R.C.run['ci_watch'] = []
        shutil.rmtree(repo / '.github')


def test_update_notice():
    import io
    import urllib.request
    said, real_log, real_open = [], R.log, urllib.request.urlopen
    R.log = said.append
    try:
        for remote, want in (("__version__ = '999.0.0'\n", 1), ('__version__ = "999.0.0"\n', 1),
                             ("__version__ = '0.0.1'\n", 0), ('__version__ = "0.0.1"\n', 0), ('garbage', 0)):
            urllib.request.urlopen = lambda *a, **k: io.BytesIO(remote.encode())
            said.clear()
            R.LATEST_SAID[0] = ''
            R.update_notice()
            eq(len(said), want, f'update notice for {remote.strip()!r}')
        urllib.request.urlopen = lambda *a, **k: io.BytesIO(b"__version__ = '999.0.0'\n")
        R.LATEST_SAID[0] = ''
        said.clear()
        R.update_notice()
        R.update_notice()
        eq(len(said), 1, 'a version is announced once, not on every look')
        has(said[0], r'999\.0\.0 is out.*To upgrade', 'saying how to upgrade')
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError('offline'))
        said.clear()
        R.update_notice()
        eq(said, [], 'offline: no notice, no crash')
    finally:
        R.log, urllib.request.urlopen = real_log, real_open
        R.LATEST_SAID[0] = ''


def test_restart_if_upgraded():
    import agent_runner
    eq([R.breaking('0.37.1', v) for v in ('0.37.9', '0.38.0', '1.0.0', '10.0.0')], [False, False, True, True], 'breaking')
    said, execs, real_log = [], [], R.log
    R.log = said.append
    try:
        with mock.patch.object(R.os, 'execv', lambda *a: execs.append(a)), mock.patch.object(R.plat, 'WINDOWS', False):
            for installed, ticks, want in ((agent_runner.__version__, 3, 0),  # nothing new
                                           ('9999.0.0', 3, 0),  # breaking: said, never exec
                                           ('.'.join(agent_runner.__version__.split('.')[:2]) + '.999', 1, 0),  # one tick: wait
                                           ('.'.join(agent_runner.__version__.split('.')[:2]) + '.999', 1, 1)):  # seen twice
                with mock.patch.object(R.Path, 'read_text', lambda *a, **k: f'__version__ = "{installed}"\n'):
                    for _ in range(ticks):
                        R.restart_if_upgraded()
                eq(len(execs), want, f'restart on {installed}')
        eq(sum('breaking' in s for s in said), 1, 'a breaking version is said once')
        eq(R.kept_keys(), {'slots': R.SLOTS, 'paused': False, 'power': R.POWER, 'stop': R.stopping(), 'forced': False},
           'the restart hands the new process what the keys set: slots, pause, power, stop, force')
        eq(R.kept_keys(), {}, 'once')
    finally:
        R.log, R._upgrade_seen = real_log, None


def test_auto_upgrade():
    import agent_runner
    due = R.auto_upgrade_due
    from agent_runner.config import DEFAULTS
    eq(DEFAULTS['run']['auto_upgrade'], True, 'C6: [run] auto_upgrade defaults to true')
    check(due('0.49.0', '0.48.0', '0.48.0', False, ''), 'newer seen + no merge: upgrade')
    check(not due('0.49.0', '0.48.0', '0.48.0', True, ''), 'mid-merge: wait')
    check(not due('0.49.0', '0.48.0', '0.49.0', False, ''), 'already installed: restart_if_upgraded takes it')
    check(not due('0.49.0', '0.48.0', '0.48.0', False, '0.49.0'), 'tried for this version: once')
    check(not due('0.48.0', '0.48.0', '0.48.0', False, ''), 'nothing newer')
    check(not due('', '0.48.0', '0.48.0', False, ''), 'no update check yet')
    check(not due('1.0.0', '0.48.0', '0.48.0', False, ''), 'never across a major version')
    check(not due('0.49.0', '0.48.0', '0.48.0', False, '', windows=True), 'not on Windows')
    newer = '.'.join(agent_runner.__version__.split('.')[:2]) + '.999'
    said, ran, real_log = [], [], R.log
    R.log = said.append
    try:
        with mock.patch.object(R, 'upgrade', lambda: ran.append(1)), mock.patch.object(R.plat, 'WINDOWS', False), \
                mock.patch.object(R.Path, 'read_text', lambda *a, **k: f'__version__ = "{agent_runner.__version__}"\n'):
            R.LATEST_SAID[0], R.AUTO_TRIED[0] = newer, ''
            R.AUTO_UPGRADE[0] = False
            eq(R.auto_upgrade(False), None, 'auto_upgrade = false: nothing')
            R.AUTO_UPGRADE[0] = True
            eq(R.auto_upgrade(True), None, 'mid-merge: it waits')
            t = R.auto_upgrade(False)
            check(t is not None, 'idle: the upgrade starts with no key pressed')
            t.join(5)
            eq(ran, [1], 'upgrade() ran once')
            eq(R.auto_upgrade(False), None, 'and not again for the same version')
            has(said[0], rf'{re.escape(newer)} is out.*upgrading by itself', 'logged')
    finally:
        R.log, R.LATEST_SAID[0], R.AUTO_TRIED[0], R.AUTO_UPGRADE[0] = real_log, '', '', True


def test_repair_per_failure(repo: Path):
    """One repair per failure, not per task: a rebuild that fails on commits main got since gets another."""
    print('merge: a repaired merge that fails again after main moved gets a second repair session')
    R.init(repo)
    git(repo, 'checkout', '-q', '-b', 'task/R1')
    (repo / 'r1.py').write_text('# r1\n')
    git(repo, 'add', 'r1.py')
    git(repo, 'commit', '-qm', 'R1: r1')
    git(repo, 'checkout', '-q', 'main')
    calls, gates, saved = [], [], (R.repair_retest, R.tested, R.caught_up, R.land, R.log)
    said = []

    def repair(tid, branch, d, base, merged, riders=()):
        calls.append(base)
        if len(calls) == 1:  # main moves right after the first repair: the rebuild is on a new base
            git(repo, 'commit', '-q', '--allow-empty', '-m', 'main moved')
        return None, None, []

    R.repair_retest, R.tested = repair, lambda *a, **k: (gates.append(1), 'the tests fail after the merge: x')[1]
    R.caught_up = lambda tid, branch, d, base, merged, tids: None  # the shared branch moved: build again
    R.log = said.append
    try:
        why = R.merge_batch('R1', 'main')
    finally:
        R.repair_retest, R.tested, R.caught_up, R.land, R.log = saved
        git(repo, 'branch', '-D', 'task/R1')
    eq(len(calls), 2, 'a second repair session, on the new base')
    check(len(set(calls)) == 2, 'each on the base it failed on')
    check(any('moved since the repair' in s for s in said), 'and the log says why a second one runs')
    check(why, 'still failing on the same base after that: no third repair, it gives up')


def test_flake_repair(tmp: Path):
    """A repair that answers FLAKE: commits nothing; the gate runs once more before anything is parked."""
    log = tmp / 'fixer-flake.log'
    log.write_text('\n=== old\nFLAKE: OldTest\n\n=== now\nchecked it\n', encoding='utf-8')
    eq(R.flake_said(log), [], "an earlier session's FLAKE line is not this one's")
    log.write_text(log.read_text() + 'it passes alone, nothing here touches it\nFLAKE: `LogPanelTest`, TimerTest\n')
    eq(R.flake_said(log), ['LogPanelTest', 'TimerTest'], 'the tests the last session named')
    saved = R.repair_merge, R.tested, R.log, dict(R.FLAKY)
    R.log = lambda m: None
    try:
        R.repair_merge = lambda *a, **k: R.FLAKE + 'LogPanelTest'
        R.tested = lambda *a, **k: None
        eq(R.repair_retest('Q1', 'main', tmp, 'base', 'merged'), (None, None, []), 'a flake that passes the rerun lands')
        check('LogPanelTest' in R.FLAKY, 'and is filed to be fixed')
        R.tested = lambda *a, **k: 'the tests fail after the merge: boom'
        why = R.repair_retest('Q1', 'main', tmp, 'base', 'merged')[0]
        check(why and 'failed again' in why, 'a flake that fails the rerun too is no repair', why)
        R.repair_merge = lambda *a, **k: 'the repair session committed nothing; its reason is in x'
        eq(R.repair_retest('Q1', 'main', tmp, 'base', 'merged')[0][:31], 'the repair session committed no',
           'any other empty repair parks as before, with no rerun')
    finally:
        R.repair_merge, R.tested, R.log = saved[:3]
        R.FLAKY.clear()
        R.FLAKY.update(saved[3])


def test_end_orphans(repo: Path):
    print("what an ended session left running is ended; a live session's and others' are not")
    if R.plat.WINDOWS:
        return
    R.init(repo)
    gone, live = str(__import__('uuid').uuid4()), str(__import__('uuid').uuid4())
    base = {k: v for k, v in os.environ.items() if k not in ('AGENT_RUNNER', 'CLAUDE_CODE_SESSION_ID')}
    sleep = lambda env, *extra: subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', *extra],
                                                 env={**base, **env}, start_new_session=True)
    agent = sleep({}, '--session-id', live)  # stands in for the agent of a running session
    orphan = sleep({'AGENT_RUNNER': '1', 'CLAUDE_CODE_SESSION_ID': gone})
    kept = sleep({'AGENT_RUNNER': '1', 'CLAUDE_CODE_SESSION_ID': live})
    mine = sleep({'CLAUDE_CODE_SESSION_ID': gone})  # not started by a runner
    try:
        R.end_orphans()
        check(orphan.wait(10) is not None, 'the ended session\'s process is ended')
        check(kept.poll() is None and mine.poll() is None, 'a live session\'s and a non-runner process are left')
    finally:
        for p in (agent, orphan, kept, mine):
            p.kill()
            p.wait()


def test_memory_watch(repo: Path):
    print("memory: a runaway of the run's past proc_max_gb is picked, or its biggest under min_free_mem_gb; "
          "only the run's own processes, never an agent")
    R.init(repo)
    G = R.GB
    saved = R.C.run['proc_max_gb'], R.C.run['min_free_mem_gb']
    try:
        R.C.run['proc_max_gb'], R.C.run['min_free_mem_gb'] = 'auto', 4
        procs = [(1, 40 * G, 'test a'), (2, 2 * G, 'cargo'), (3, 10 * G, 'test b')]
        check([p for p, _ in R.mem_hogs(procs, 60 * G, 128 * G)] == [1], 'auto: past a quarter of 128 GB')
        check(R.mem_hogs(procs[1:], 60 * G, 128 * G) == [], 'nothing past it, and memory to spare: none')
        check([p for p, _ in R.mem_hogs(procs[1:], 3 * G, 128 * G)] == [3], 'under the floor: the biggest')
        check(R.mem_hogs([(2, G // 2, 'small')], 3 * G, 128 * G) == [], 'not a process under a GB')
        R.C.run['proc_max_gb'], R.C.run['min_free_mem_gb'] = 0, 0
        check(R.mem_hogs(procs, 1, 128 * G) == [], '0 and 0: never')
        R.C.run['proc_max_gb'] = 8
        check([p for p, _ in R.mem_hogs(procs, 60 * G, 128 * G)] == [1, 3], 'a number of GB')
    finally:
        R.C.run['proc_max_gb'], R.C.run['min_free_mem_gb'] = saved
    if not Path('/proc/meminfo').exists():
        return
    d = R.SLOTS_DIR / 's7'
    d.mkdir(parents=True, exist_ok=True)
    base = {k: v for k, v in os.environ.items() if k != 'AGENT_RUNNER'}
    sleep = lambda env, cwd, *extra: subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', *extra],
                                                      env={**base, **env}, cwd=str(cwd))
    in_slot, tagged = sleep({}, d), sleep({'AGENT_RUNNER': '1'}, repo)
    agent = sleep({}, d, '--session-id', str(__import__('uuid').uuid4()))
    outside = sleep({}, repo)
    try:
        time.sleep(0.5)
        found = {p for p, _, _ in R.runner_procs()}
        check({in_slot.pid, tagged.pid} <= found, "a process in a slot and one with AGENT_RUNNER=1 are the run's")
        check(not {agent.pid, outside.pid} & found, 'an agent and a process outside the run are not')
    finally:
        for p in (in_slot, tagged, agent, outside):
            p.kill()
            p.wait()

    print('memory: a test the watch ended is named from its thread and the binary\'s --list, and filed once')
    named = subprocess.Popen([sys.executable, '-c', 'import ctypes, threading, time\n'
                              'def t():\n    ctypes.CDLL(None).prctl(15, b"the_parts_box_i")\n    time.sleep(30)\n'
                              'threading.Thread(target=t).start()\ntime.sleep(30)'])
    try:
        time.sleep(0.5)
        check('the_parts_box_i' in R.thread_names(named.pid), "a thread's name, the main one's aside")
    finally:
        named.kill()
        named.wait()
    exe = d / 'fake_test'
    exe.write_text('#!/bin/sh\nprintf "the_parts_box_is_the_originals: test\\nthe_parts_list: test\\nbench_x: bench\\n"\n')
    exe.chmod(0o755)
    eq(R.test_names(str(exe), {'the_parts_box_i'}, str(d)), ['the_parts_box_is_the_originals'], 'the whole name')
    eq(R.test_names(str(exe), {'cargo'}, str(d)), [], 'a thread no test is named after: none')
    eq(R.test_names('/bin/true', {'the_parts_box_i'}, str(d)), [], 'not a test binary: none')
    rel = R.plan_rel('TODO.md')
    head = git(repo, 'rev-parse', 'HEAD')
    try:
        R.HOGS['the_parts_box_is_the_originals'] = ('31', 's3')
        got = R.file_flaky(rel)
        eq(len(got), 1, 'one task')
        has((repo / rel).read_text(), rf'\*\*{got[0]}\*\* \(follow-up, critical\) make the test '
            r'`the_parts_box_is_the_originals` stop growing: it held 31 GB in s3', 'critical, naming the test')
        R.HOGS['the_parts_box_is_the_originals'] = ('31', 's1')
        eq(R.file_flaky(rel), [], 'not again while that task is open')
        R.BROKEN['the_rider_leaf'] = ('X', 'a' * 40, True)
        got = R.file_flaky(rel)
        eq(len(got), 1, 'a test the shared branch fails: one task')
        has((repo / rel).read_text(), rf'\*\*{got[0]}\*\* \(follow-up, critical\) make the test `the_rider_leaf` '
            r'pass again: it fails on the shared branch \(aaaaaaaaaa\).*selection reach', 'critical, saying to widen the selection')
        print('run: the third flaky-test task in a week for one test is filed blocked on a person (B34)')
        git(repo, 'reset', '-q', '--hard', head)
        done = repo / R.plan_rel('DONE.md')
        before = done.read_text(encoding='utf-8') if done.exists() else '# DONE — the archive\n'
        day = R.dt.date.today().isoformat()
        done.write_text(before + '\n### Next\n\n' + ''.join(
            f'- [x] **T9{i}** (follow-up, critical) make the test `a::racy` robust: x (filed {day}) | test: a::racy\n'
            for i in (1, 2)), encoding='utf-8')
        git(repo, 'commit', '-qam', 'two closed flaky tasks for a::racy')
        R.FLAKY['a::racy'] = 'X'
        got = R.file_flaky(rel)
        has((repo / rel).read_text(), rf'- \[~\] \*\*{got[0]}\*\* .*make the test `a::racy` robust.* BLOCKED: BLOCKED: '
            r'the test `a::racy` has had 2 auto-filed tasks closed in 7 days.*\(T91, T92\)', 'blocked on a person')
    finally:
        R.FLAKY.clear()
        R.HOGS.clear()
        git(repo, 'checkout', '-q', '--', rel)
        git(repo, 'reset', '-q', '--hard', head)

    print('drop_ahead: a merge2 gate is stopped and its record removed; another worktree\'s is left')
    gd = R.C.notes(R.GATES)
    gd.mkdir(parents=True, exist_ok=True)
    sleeper = subprocess.Popen(['sleep', '60'], start_new_session=True)
    try:
        (gd / 'a.json').write_text(json.dumps({'pid': sleeper.pid, 'cwd': str(d / 'merge2'), 'until': 0}))
        (gd / 'b.json').write_text(json.dumps({'pid': 999999, 'cwd': str(d / 'merge2'), 'until': 0}))
        (gd / 'c.json').write_text(json.dumps({'pid': 999999, 'cwd': str(d / 'merge'), 'until': 0}))
        R.drop_ahead()
        eq(sorted(f.name for f in gd.glob('*.json')), ['c.json'], "merge2's records gone, merge's kept")
        eq(sleeper.wait(10), -signal.SIGTERM, 'the live merge2 gate stopped')
    finally:
        sleeper.kill()
        for f in gd.glob('*.json'):
            f.unlink()


def test_stalled(tmp: Path):
    print('run: a session quiet through a long tool run is not stalled at a prompt the moment the tool ends')
    t = tmp / 'stall.jsonl'
    t.write_text('{}\n')
    old = time.time() - 30 * 60
    os.utime(t, (old, old))
    saved = R.transcript, R.plat.children
    kids = [[1]]
    try:
        R.transcript = lambda sid: t
        R.plat.children = lambda pid: kids[0]
        eq(R.stalled(1, 'busy', 20 * 60), None, 'a tool running 30 min is not stalled (under the hung-tool limit)')
        kids[0] = []
        eq(R.stalled(1, 'busy', 20 * 60), None, 'just after the tool ends: not at a prompt for 30 min')
        has(R.stalled(1, 'never', 20 * 60) or '', 'at a prompt', 'a session never seen busy, quiet 30 min, is stalled')
        R._busy_at['busy'] = time.time() - 21 * 60
        has(R.stalled(1, 'busy', 20 * 60) or '', 'at a prompt', '21 min at a prompt after the tool ended is stalled')
    finally:
        R.transcript, R.plat.children = saved


def test_relative_remote(tmp: Path):
    print('a remote given as a relative path is the main checkout\'s: a worktree elsewhere still pushes to it')
    from agent_runner import config
    from agent_runner.gitops import push
    base = tmp / 'relremote'
    base.mkdir()
    git(base, 'init', '-q', '--bare', '-b', 'main', 'o.git')
    main = base / 'r'
    main.mkdir()
    git(main, 'init', '-q', '-b', 'main')
    git(main, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'i')
    git(main, 'remote', 'add', 'origin', '../o.git')
    wt = tmp / 'elsewhere' / 's1'
    wt.parent.mkdir()
    git(main, 'worktree', 'add', '-q', str(wt), '-b', 'task/X')
    git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'x')
    config._cfg.cache_clear()
    try:
        eq(push(wt, 'task/X'), 'pushed task/X -> origin', 'task/X pushes from the worktree')
        eq(git(base / 'o.git', 'rev-parse', 'task/X'), git(wt, 'rev-parse', 'HEAD'), 'to the remote next to the main checkout')
        git(main, 'remote', 'set-url', 'origin', '../gone.git')
        git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', 'y')
        out = push(wt, 'task/X')
        check('did not push (it is committed locally)' in out and 'has moved' not in out,
              'an unreachable remote is said as such, not as a remote that moved', out)
    finally:
        config._cfg.cache_clear()


def test_paint():
    print('the runner pane in colour: tone by outcome, the id bold; run.log stays plain')
    has(R.paint('t', 'P1: merged, ticked'), r'\x1b\[32m\x1b\[1mP1\x1b\[22m: merged', 'a merge is green, its id bold')
    has(R.paint('t', 'P1: merged, blocked; SUSPECT, recheck'), r'\x1b\[33m', 'a block is yellow, though it merged')
    has(R.paint('t', 'B9: tests fail after the merge'), r'\x1b\[31m', 'a failure is red')
    has(R.paint('t', 'slot 2: P3 (Next; a.rs)'), r'\x1b\[34mslot 2: \x1b\[1mP3', 'a start is blue')


def test_structured_events(repo: Path):
    print('F41: log() with a kind writes events.jsonl, and since/follow/status read its fields, not the prose')
    R.init(repo)
    titles = {'F5': 'Control session experience', 'B9': 'Fix the flicker'}
    now = R.dt.datetime(2026, 11, 19, 15, 0, 0)

    def evs(words: int) -> list[dict]:
        say = ['A', 'B'][words]  # the same events, worded two ways
        e = lambda t, kind, tid='', **f: {'time': f'2026-11-19T{t}', 'kind': kind, 'id': tid, 'text': f'{say} {kind}', **f}
        return [e('13:00:00', R.EV_STARTED, 'F5'), e('13:30:00', R.EV_STALLED, 'F5'), e('14:00:00', R.EV_LANDED, 'F5'),
                e('14:05:00', R.EV_PART, 'B9'), e('14:10:00', R.EV_PARKED, 'B9', why='tests fail. more'),
                e('14:12:00', R.EV_LEFT, 'B9', why='the merge crashed'),
                e('14:15:00', R.EV_HELD, why='F5 cannot land', detail='commit them'),
                e('14:16:00', R.EV_STOP_ASKED, left=2), e('14:17:00', R.EV_DROPPED, 'B9'),
                e('14:18:00', R.EV_RELEASED, text='demo 1.2.0 released'), e('14:19:00', R.EV_STOP_BACK),
                e('14:20:00', R.EV_IDLE), e('14:30:00', R.EV_STOPPED)]
    start = now - R.dt.timedelta(hours=3)
    a, b = (R.since_text(evs(w), start, titles, now) for w in (0, 1))
    eq(a, b, 'rewording every message changes nothing since prints')
    eq(a[0].splitlines(), ['since 12:00:', '  13:00  started: Control session experience [F5]',
                           '  13:30  looks stuck: Control session experience [F5]',
                           '  14:00  landed: Control session experience [F5]',
                           '  14:05  part landed, rest stuck: Fix the flicker [B9]',
                           '  14:10  stuck, not merged: Fix the flicker (tests fail) [B9]',
                           '  14:12  needs you: Fix the flicker (the merge crashed) [B9]',
                           '  14:15  run held, needs you: F5 cannot land',
                           '  14:16  stop requested: 2 left before the run exits',
                           '  14:18  demo 1.2.0 released',
                           '  14:19  stop taken back: the run is starting tasks again',
                           '  14:20  run idle: nothing left it may start', '  14:30  run stopped'],
       'each kind its phrase, from the id and fields')
    eq(*(R.status_text(False, {}, evs(w), titles, 0.0) for w in (0, 1)), 'nor what status lists lately')
    has(R.status_text(False, {}, evs(0), titles, 0.0), r'lately:\n  14:05 part landed.*\n  14:10 stuck.*\n  14:12 needs '
        r'you.*\n  14:20 run idle.*\n  14:30 run stopped$', 'lately: the last five merges, parks, holds, idles, stops')
    with mock.patch.object(R.status, 'what_changed', lambda tid: ''):
        fa, fb = (R.follow_lines('\n'.join(R.json.dumps(e) for e in evs(w)), titles, now)[0] for w in (0, 1))
        eq(fa, fb, 'nor what follow prints, from events.jsonl lines')
        check(any(l.endswith('· 1 left') for l in fa), 'the stop countdown counts the dropped task by its event', fa)
        ny = [R.follow_lines('\n'.join(R.json.dumps(e) for e in evs(w)), titles, now, needs_you=True)[0] for w in (0, 1)]
    eq(ny[0], ny[1], 'nor what the needs-you watch (the phone push) prints')
    check('14:15  run held, needs you: F5 cannot land: commit them' in ny[0], 'a hold with what holds it', ny[0])

    f = R.events_file()
    keep = f.read_text(encoding='utf-8') if f.exists() else None
    try:
        f.unlink(missing_ok=True)
        R.log('F5: anything at all', R.EV_LANDED, 'F5')
        R.log('no kind: run.log only')
        rec = [R.json.loads(l) for l in f.read_text(encoding='utf-8').splitlines()]
        eq([(r['kind'], r['id'], r['text']) for r in rec], [(R.EV_LANDED, 'F5', 'F5: anything at all')],
           'a kind writes {time, kind, id, text}; a line without one stays in run.log only')
        check(R.read_events()[-1]['text'] == 'F5: anything at all', 'read_events reads it back')
        got = []
        for words in ('B9: merged, blocked', 'B9 is in, the rest waits'):  # through log() itself
            f.unlink(missing_ok=True)
            R.log(words, R.EV_PART, 'B9')
            got.append(R.since_text(R.read_events()[-1:], R.dt.datetime(2000, 1, 1), titles, R.dt.datetime.now())[0]
                       .splitlines()[1].split('  ', 2)[-1])
        eq(got, ['part landed, rest stuck: Fix the flicker [B9]'] * 2, 'a reworded log() line reads the same')
        eq(R.paint('t', 'quiet words', R.EV_LANDED)[:16], R.paint('t', 'P1: merged', None)[:16],
           'the pane colours by kind')
    finally:
        if keep is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(keep, encoding='utf-8')


def _ts(ago: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(time.time() - ago, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def _person(text: str, ago: float) -> dict:
    return {'type': 'user', 'timestamp': _ts(ago), 'message': {'role': 'user', 'content': text}}


def _claude(text: str, ago: float) -> dict:
    return {'type': 'assistant', 'timestamp': _ts(ago),
            'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}}


def _call(name: str, inp: dict, uid: str, ago: float) -> dict:
    return {'type': 'assistant', 'timestamp': _ts(ago),
            'message': {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': uid, 'name': name, 'input': inp}]}}


def _result(uid: str, text: str, ago: float) -> dict:
    return {'type': 'user', 'timestamp': _ts(ago), 'message': {'role': 'user', 'content': [
        {'type': 'tool_result', 'tool_use_id': uid, 'content': text}]}}


def test_closed_online_controls(repo: Path):
    print('B53: a control session closed online (archived or deleted in the apps) ends here, and its number is free')
    R.init(repo)
    H = 3600
    gone = {'type': 'system', 'subtype': 'informational', 'level': 'warning', 'timestamp': _ts(H),
            'content': 'Remote Control disconnected — this session was ended or archived from another device or app '
                       '(code 4090)'}
    deleted = dict(gone, content='Remote Control disconnected — the server no longer reports this session — it may '
                                 'have been deleted from another device or app (code 4090)')
    bridge = {'type': 'bridge-session', 'bridgeSessionId': 'cse_01A'}
    base = [bridge, _person('status?', 2 * H), _claude('All quiet.', 2 * H - 5)]
    archived = base + [gone, bridge]  # Claude Code rewrites the same bridge entry after it
    removed = base + [deleted, _claude('A needs-you event came in.', 30)]  # a watch waking it is not the person
    used_here = base + [gone, _person('still here, carry on', 60)]  # typed in its terminal: in use
    reconnected = base + [gone, {'type': 'bridge-session', 'bridgeSessionId': 'cse_01B'}]
    for name, rows, want in (('open', base, False), ('archived', archived, True), ('deleted', removed, True),
                             ('used in its terminal since', used_here, False), ('reconnected', reconnected, False)):
        eq(R.closed_online(rows), want, f'{name}: closed online {want}')

    rows = {'s1': archived, 's2': archived, 's3': base, 's4': removed, 's5': used_here}
    notes = R.C.notes()
    notes.mkdir(parents=True, exist_ok=True)
    for n in range(1, 6):
        (notes / f'control{n}.pid').write_text(f'{9100 + n} s{n}', encoding='utf-8')
        (notes / f'control{n}.title').write_text(f'agent-runner · {n}\n', encoding='utf-8')
    ended, tm = [], []
    live = lambda n: 9100 + n if (notes / f'control{n}.pid').exists() else 0
    panes = {2: '%52', 4: ''}

    def tmux(*a, **kw):
        tm.append(a)
        return subprocess.CompletedProcess(a, 0, '', '')
    try:
        with mock.patch.object(R, 'control_live', live), mock.patch.object(R, 'transcript', lambda s: f'/t/{s}'), \
                mock.patch.object(R, 'entries', lambda s, skip_bad=False: iter(rows[s])), \
                mock.patch.object(R.plat, 'terminate', ended.append), mock.patch.object(R, 'control_ok', lambda: True), \
                mock.patch.object(R, 'control_window', lambda n, pid: panes.get(n, '')), \
                mock.patch.object(R, 'tmux', tmux), mock.patch.object(R, 'log'):
            eq(R.control_number(), 6, 'before: every number up to 5 is held')
            eq(R.end_closed_controls(force=True), [2, 4], 'the archived and the deleted one are ended')
            eq(sorted(ended), [9102, 9104], 'their processes ended; c1, the open one and the one in use left running')
            check(('kill-pane', '-t', '%52') in tm, 'its tmux pane closed', tm)
            check(all(not (notes / f'control{n}.{x}').exists() for n in (2, 4) for x in ('pid', 'title')),
                  'their controlN.pid and controlN.title removed')
            check(all((notes / f'control{n}.pid').exists() for n in (1, 3, 5)), 'the others keep theirs')
            eq(R.control_number(), 2, 'control_number() hands out 2 again')
            eq(R.end_closed_controls(), [], 'within CONTROL_CLOSE_EVERY: no second look')
            (notes / 'control2.pid').write_text('9102 s2', encoding='utf-8')
            ended.clear()
            eq(R.free_control_number(), 2, 'control --new ends a session closed online first, then takes its number')
            eq(ended, [9102], 'so a new session never comes up past the closed ones')
            rows['s3'] = None  # unreadable: logged and skipped, never raised into the run loop
            (notes / 'control2.pid').write_text('9102 s2', encoding='utf-8')
            eq(R.end_closed_controls(force=True), [2], 'one session that cannot be read does not stop the others')
        listing = (f'run\t%60\tc2\t{R.ROOT}\t\t111\nrun\t%61\tc3\t/elsewhere\t\t222\n'
                   f'run\t%62\t\t\t\t333\n')
        with mock.patch.object(R.shutil, 'which', lambda x: '/usr/bin/tmux'), \
                mock.patch.object(R, 'tmux', lambda *a, **kw: subprocess.CompletedProcess(a, 0, listing, '')):
            eq(R.control_window(2, 999), '%60', 'its pane by its c2 tag for this repository')
            eq(R.control_window(3, 333), '%62', 'another repo\'s c3 is not it: found by its pane pid instead')
            eq(R.control_window(4, 444), '', 'no pane: nothing to close')
    finally:
        for n in range(1, 6):
            (notes / f'control{n}.pid').unlink(missing_ok=True)
            (notes / f'control{n}.title').unlink(missing_ok=True)


def test_renamed_control_kept(repo: Path):
    print('B41: idle-close keeps a control session the person renamed (a custom-title entry), and files no question')
    R.init(repo)
    H, cf, now = 3600, R.control_cfg(), time.time()
    done = [_person('watch the push', 4 * H), _claude('Pushed; waiting on CI.', 4 * H - 5)]
    ask = [_person('can T7 go first?', 3 * H), _claude('T7 is now first.\n\nWant me to pause T8 too?', 3 * H - 5)]
    title = lambda t: {'type': 'custom-title', 'customTitle': t, 'sessionId': 'x'}
    eq(R.control_verdict(R.control_state(done), cf, now, 4)[0], 'close', 'without a rename: idle past control_idle closes')
    renamed = done[:1] + [title('PUSH CRUCIAL')] + done[1:]
    eq(R.control_state(renamed)['title'], 'PUSH CRUCIAL', 'control_state records the custom title')
    eq(R.control_verdict(R.control_state(renamed), cf, now, 4), ('keep', 'renamed by the person'),
       'renamed, Claude last and idle 4h: kept')
    eq(R.control_verdict(R.control_state(ask + [title('mine')]), cf, now, 4)[0], 'keep', 'its open question not filed')
    eq(R.control_state(renamed + [title('later name')])['title'], 'later name', 'the latest rename counts')
    R.control_give(4, R.control_name(4, 'can T7 go first?'))  # F32: the name the runner gave session 4
    for t in (R.control_name(4), R.control_name(4, 'can T7 go first?')):
        eq(R.control_verdict(R.control_state(done + [title(t)]), cf, now, 4)[0], 'close', f'the runner\'s own name {t!r}: not a rename')


def test_control_summary_title(repo: Path):
    print('F29: a control session opened with a long ask names itself with a summary once it has read it, and is '
          'still closed or kept as before')
    R.init(repo)
    rn, H, cf, now = R.ROOT.name, 3600, R.control_cfg(), time.time()
    ask = 'deploy with tags instead of pushing to the site branch, and say what breaks if we do'
    cut = R.control_name(11, ask)
    eq(cut, f'{rn} · 11 · deploy with tags instead of', 'the opening name is the ask cut mid-thought')
    sent, renamed, here = [], [], os.getcwd()
    os.chdir(repo)  # cmd_control's init() reads the repository from here
    try:
        with mock.patch.dict(os.environ, {R.CONTROL_N_ENV: '11', 'TMUX_PANE': '%42'}), \
                mock.patch.object(R, 'send_to_pane', lambda p, t: sent.append((p, t)) or True), \
                mock.patch.object(R, 'tmux', lambda *a, **k: renamed.append(a) or subprocess.CompletedProcess(a, 0, '', '')):
            eq(R.cmd_control(['--title', 'R43 site deploy via tags']), 0, 'control --title from session 11 works')
        with mock.patch.dict(os.environ, {R.CONTROL_N_ENV: '', 'TMUX_PANE': ''}):
            eq(R.cmd_control(['--title', 'x y']), 2, 'outside a control session, with no N: refused')
    finally:
        os.chdir(here)
    want = f'{rn} · R43 · site deploy via tags'  # F32: about one task, the task id in place of N
    eq(sent, [('%42', f'/rename {want}')], 'it types /rename with the summary name into its own pane')
    check(('rename-window', '-t', '%42', want) in renamed, 'its tmux window takes the name too', renamed)
    eq(R.control_summary_name(11, '  "R43 site\ndeploy"  '), f'{rn} · R43 · site deploy', 'one line, no quotes')
    eq(R.control_summary_name(11, ''), '', 'no summary, no name')
    title = lambda t: {'type': 'custom-title', 'customTitle': t, 'sessionId': 'x'}
    done = [_person(ask, 4 * H), title(want), _claude('Tags deploy fine; nothing breaks.', 4 * H - 5)]
    st = R.control_state(done)
    eq(st['title'], want, 'the transcript ends up with the summary title, not the cut-off one')
    check(not R.control_renamed(st, 11), 'the summary name is not a rename by the person')
    eq(R.control_verdict(st, cf, now, 11)[0], 'close', 'idle past control_idle: still closed')
    recent = [_person(ask, 60), title(want), _claude('On it.', 50)]
    eq(R.control_verdict(R.control_state(recent), cf, now, 11)[0], 'keep', 'active lately: still kept')
    mine = done + [title('MY DEPLOY')]
    eq(R.control_verdict(R.control_state(mine), cf, now, 11)[0], 'keep', 'a later rename by the person still keeps it')


def test_control_task_name(repo: Path):
    print('F32: a control session about one task is named "<repo> · ID · summary"; /new or /clear puts it back to '
          '"<repo> · N"; attach cN finds it either way; a name the person typed is never overwritten')
    import io
    from contextlib import redirect_stdout
    R.init(repo)
    rn = R.ROOT.name
    title = lambda t: {'type': 'custom-title', 'customTitle': t, 'sessionId': 'x'}
    eq(R.control_summary_name(11, 'R43 site deploy via tags'), f'{rn} · R43 · site deploy via tags', 'one task: its id')
    eq(R.control_summary_name(11, 'R43: site deploy'), f'{rn} · R43 · site deploy', 'a colon after the id dropped')
    eq(R.control_summary_name(11, 'P17a'), f'{rn} · P17a', 'the id alone')
    eq(R.control_summary_name(11, 'deploy with tags'), f'{rn} · 11 · deploy with tags', 'no single task: N kept')
    pidf, titlef = R.C.notes('control11.pid'), R.C.notes('control11.title')
    pidf.write_text('999 old-sid', encoding='utf-8')
    titlef.unlink(missing_ok=True)
    sent, tm, here = [], [], os.getcwd()
    talk = {'old-sid': [title(R.control_name(11, 'deploy with tags instead of'))], 'new-sid': []}
    task = f'{rn} · R43 · site deploy via tags'
    os.chdir(repo)
    try:
        with mock.patch.dict(os.environ, {R.CONTROL_N_ENV: '11', 'TMUX_PANE': '%42'}), \
                mock.patch.object(R, 'send_to_pane', lambda p, t: sent.append((p, t)) or True), \
                mock.patch.object(R, 'transcript', lambda sid: f'/x/{sid}.jsonl' if sid in talk else None), \
                mock.patch.object(R, 'entries', lambda sid, skip_bad=False: list(talk.get(sid, []))), \
                mock.patch.object(R, 'tmux', lambda *a, **k: tm.append(a) or subprocess.CompletedProcess(a, 0, '', '')):
            R.control_give(11, R.control_name(11, 'deploy with tags instead of'))
            eq(R.cmd_control(['--title', 'R43 site deploy via tags']), 0, '--title about R43 works')
            eq(sent[-1], ('%42', f'/rename {task}'), 'an ask about R43 names it "<repo> · R43 · …"')
            eq(R.control_given(11), task, 'the runner keeps the name it gave session 11')
            talk['old-sid'].append(title(task))
            check(not R.control_renamed(R.control_state(talk['old-sid']), 11), 'its own task name is not a rename')
            check(R.control_renamed(R.control_state([title(f'{rn} · 11 · something else')]), 11),
                  'a "<repo> · 11 ·" name the runner did not give counts as the person\'s')
            eq(R.control_session_start(11, {'source': 'startup', 'session_id': 'old-sid'}), '', 'startup: no reset')
            n = len(sent)
            out = io.StringIO()
            with mock.patch.object(R, 'control_hook_input', lambda: {'source': 'clear', 'session_id': 'new-sid'}), \
                    redirect_stdout(out):
                eq(R.cmd_control(['--brief']), 0, 'the SessionStart hook runs')
            check('control session' in out.getvalue(), 'it still prints the brief')
            eq(sent[n:], [('%42', f'/rename {rn} · 11')], 'after /new or /clear the name goes back to "<repo> · 11"')
            check(('rename-window', '-t', '%42', f'{rn} · 11') in tm, 'its tmux window too')
            eq(R.control_given(11), f'{rn} · 11', 'the base name is the one given now')
            eq(pidf.read_text(encoding='utf-8'), '999 new-sid', 'the pid file follows the new conversation')
            talk['new-sid'].append(title(f'{rn} · 11'))
            check(not R.control_renamed(R.control_state(talk['new-sid']), 11), 'the base name is not a rename')
            n = len(sent)
            eq(R.control_session_start(11, {'source': 'clear', 'session_id': 'new-sid'}), '', 'already the base: kept')
            eq(R.cmd_control(['--title', 'deploy docs']), 0, 'the new conversation names itself')
            eq(sent[n:], [('%42', f'/rename {rn} · 11 · deploy docs')], 'its own ask, no single task: "<repo> · 11 · …"')
            # the person types a name: never overwritten, by --title or by /clear
            talk['new-sid'].append(title('MY DOCS'))
            n = len(sent)
            eq(R.cmd_control(['--title', 'R50 other thing']), 0, '--title over the person\'s name: a no-op')
            eq(R.control_session_start(11, {'source': 'clear', 'session_id': 'third-sid'}), '', '/clear keeps it too')
            eq(sent[n:], [], 'nothing typed over the person\'s name')
    finally:
        os.chdir(here)
        pidf.unlink(missing_ok=True)
        titlef.unlink(missing_ok=True)
    rows = [f'run\t%42\tc11\t{R.ROOT}\t', f'run\t%43\tc12\t{R.ROOT}\t']
    eq(R.attach_target(rows, R.ROOT, 'c11'), ('run', '%42'), 'attach c11 finds it by its pane tag, whatever its name')


def test_close_idle_controls(repo: Path):
    print('B26: idle control sessions are closed (transcript kept); an open question is filed under Needs you first')
    R.init(repo)
    H = 3600
    done = [_person('what is running?', 210 * 60), _claude('Two tasks run: B1 and B2. Nothing needs you.', 210 * 60 - 5),
            {'type': 'bridge-session', 'bridgeSessionId': 'cse_01AbC'}]
    ask = [_person('can T7 go first?', 3 * H), _claude('T7 is now first.\n\nWant me to pause T8 too?', 3 * H - 5)]
    ask_young = [_person('x', 90 * 60), _claude('Done. Should I also drop T9?', 90 * 60 - 5)]
    person = [_claude('Here is the status.', 3 * H), _person('ok and the cost?', 2 * H)]
    recent = [_person('status', 20 * 60), _claude('All quiet.', 20 * 60 - 5)]
    bg = [_person('run the tests', 4 * H), _call('Bash', {'command': 'x', 'run_in_background': True}, 'u1', 4 * H - 3),
          _result('u1', 'Command running in background with ID: bk1. Output is being written to: /x', 4 * H - 2),
          _claude('The tests run in the background; I will report.', 4 * H - 1)]
    bg_done = bg + [{'type': 'queue-operation', 'timestamp': _ts(4 * H - 60), 'content':
                     '<task-notification>\n<task-id>bk1</task-id>\n<status>completed</status>\n</task-notification>'},
                    _claude('They passed.', 4 * H - 50)]
    watch = [_person('hi', 4 * H), _call('Monitor', {'command': f'{R.C.command} since --follow --needs-you',
                                                     'timeout_ms': 1800000}, 'u2', 4 * H - 3),
             _result('u2', 'Monitor started (task mw1, expires in 30m unless the source ends first)', 4 * H - 2),
             _claude('Watching for what needs you.', 4 * H - 1),
             _call('Monitor', {'command': f'{R.C.command} since --follow --needs-you', 'timeout_ms': 1800000},
                   'u3', 10 * 60), _result('u3', 'Monitor started (task mw2, expires in 30m)', 10 * 60)]
    cf, now = R.control_cfg(), time.time()
    eq((cf['close'], cf['idle'], cf['ask_idle'], cf['file_asks']), (True, 10800.0, 7200.0, True),
       'defaults: on, control_idle 3h, control_ask_idle 2h, questions filed')
    for name, rows, want in (('done', done, 'close'), ('question', ask, 'ask'), ('young question', ask_young, 'keep'),
                             ('person last', person, 'keep'), ('recent', recent, 'keep'),
                             ('background task running', bg, 'keep'), ('background task finished', bg_done, 'close'),
                             ('only the needs-you watch, re-armed lately', watch, 'close')):
        v = R.control_verdict(R.control_state(rows), cf, now)
        eq(v[0], want, f'{name}: {want} ({v[1]})')
    eq(R.control_verdict(R.control_state(ask), cf, now)[1], 'Want me to pause T8 too?', 'the question in one line')
    eq(R.control_link(R.control_state(done)['bridge']), 'https://claude.ai/code/session_01AbC',
       'the session link from its Remote Control id')
    eq(R.open_question('Landed: see https://x.invalid/a?b=1', cf['open']), '', 'a ? inside a link is no question')
    eq((R.duration('90m'), R.duration(45), R.duration('2h'), R.duration(False)), (5400.0, 45.0, 7200.0, 0.0),
       'times read as 90m, seconds, 2h; false is off')
    with mock.patch.dict(R.C.run, {'control_idle': '4h', 'control_open': ['should i']}):
        eq(R.control_verdict(R.control_state(done), R.control_cfg(), now)[0], 'keep', '[run] control_idle = 4h keeps it')
        eq(R.control_verdict(R.control_state(ask), R.control_cfg(), now)[0], 'keep',
           '[run] control_open without "?" or "want me to": not an open question, not idle 4h either')

    # close_controls end to end: c1 never looked at, sessions 2-7 by their transcripts
    rows = {'s1': done, 's2': done, 's3': ask, 's4': person, 's5': recent, 's6': bg}
    notes = R.C.notes()
    notes.mkdir(parents=True, exist_ok=True)
    for n, sid in ((1, 's1'), (2, 's2'), (3, 's3'), (4, 's4'), (5, 's5'), (6, 's6')):
        (notes / f'control{n}.pid').write_text(f'{9000 + n} {sid}', encoding='utf-8')
    ended, filed = [], []
    live = lambda n: 9000 + n if (notes / f'control{n}.pid').exists() else 0
    with mock.patch.object(R, 'control_live', live), mock.patch.object(R, 'transcript', lambda s: f'/t/{s}'), \
            mock.patch.object(R, 'entries', lambda s, skip_bad=False: iter(rows[s])), \
            mock.patch.object(R.plat, 'terminate', ended.append), mock.patch.object(R, 'control_ok', lambda: True), \
            mock.patch.object(R, 'file_control_ask', lambda n, sid, q, link, branch='': filed.append((n, sid, q, link)) or 'F99'), \
            mock.patch.object(R, 'log'), mock.patch.object(R, 'note'):
        got = R.close_controls(force=True)
        eq(sorted(got), [(2, 'closed', 'idle 209 min'), (3, 'asked', 'F99')], 'done -> closed, question -> filed + closed',
           )
        eq(sorted(ended), [9002, 9003], 'their processes ended, c1 and the rest left running')
        eq(filed, [(3, 's3', 'Want me to pause T8 too?', '')], 'the question filed, with the session (no link here)')
        check(not (notes / 'control2.pid').exists() and not (notes / 'control3.pid').exists()
              and all((notes / f'control{n}.pid').exists() for n in (1, 4, 5, 6)),
              'their pid files removed; c1, person last, recent and busy ones kept')
        ended.clear()
        with mock.patch.dict(R.C.run, {'control_close': False}):
            eq(R.close_controls(force=True), [], '[run] control_close = false closes nothing')
        with mock.patch.dict(R.C.run, {'control_file_asks': False}):
            (notes / 'control3.pid').write_text('9003 s3', encoding='utf-8')
            filed.clear()
            got = R.close_controls(force=True)
            check((3, 'asked', 'Want me to pause T8 too?') in got and not filed,
                  '[run] control_file_asks = false: closed without filing', (got, filed))
    for n in range(1, 7):
        (notes / f'control{n}.pid').unlink(missing_ok=True)

    # file_control_ask in a repository of its own: a task blocked DECIDE, listed under Needs you, committed
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, 'init', '-q')
        (root / 'runner.toml').write_text('[run]\ncontrol_ask_kind = "R"\n', encoding='utf-8')
        (root / 'plan').mkdir()
        (root / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **R1** other | files: a.py\n',
                                               encoding='utf-8')
        git(root, 'add', '-A'); git(root, 'commit', '-qm', 'start')
        try:
            R.init(root)
            tid = R.file_control_ask(3, 'sid-3', 'Want me to pause T8 too?', 'https://claude.ai/code/session_01AbC')
            eq(tid, 'R2', 'filed with [run] control_ask_kind')
            a = [x for x in P.asks(root / 'plan' / 'TODO.md') if x[1] == tid]
            eq([(x[0], x[3], x[4]) for x in a], [('DECIDE', 'Want me to pause T8 too?',
                                                 'https://claude.ai/code/session_01AbC')],
               'a DECIDE item under Needs you: the question, and the session link apart')
            eq(git(root, 'status', '--porcelain', '--', 'plan/TODO.md'), '', 'and committed')
            check('control 3' in git(root, 'log', '-1', '--format=%s'), 'the commit names the session')
        finally:
            R.init(repo)


def test_close_control_tiers(repo: Path):
    print('F56: a one-ask session that queued a task closes after 5 min, one the person talked in stays 12 h')
    R.init(repo)
    M, H = 60, 3600

    def queued(ago: float, last: str = 'Queued it as F7; it runs after B2.') -> list:
        return [_person('add a dark mode toggle', ago + 30),
                _call('Bash', {'command': f'{R.C.command} plan add F "dark mode toggle" --files ui.py'}, 'p1', ago + 20),
                _result('p1', 'added F7', ago + 19), _claude(last, ago)]

    def talked(ago: float, last: str = 'Done: F7 now runs first.') -> list:
        return queued(ago + 60) + [_person('and put it first', ago + 30), _claude(last, ago)]

    cf, now = R.control_cfg(), time.time() + 2  # the rows are stamped after this, a moment later
    eq((cf['quick'], cf['talked']), (300.0, 43200.0), 'defaults: control_idle_quick 5m, control_idle_talked 12h')
    v = lambda rows, one=True, c=None: R.control_verdict(R.control_state(rows), c or cf, now, 4, one)
    eq(R.control_state(queued(0))['said'], 1, 'one person message')
    check(R.control_state(queued(0))['queued'], 'the plan add counted as queued')
    eq(v(queued(4 * M))[0], 'keep', 'one ask, queued: kept at 4 min')
    eq(v(queued(5 * M)), ('close', 'idle 5 min (one ask, queued)'), 'one ask, queued: closed at 5 min')
    eq(v(queued(5 * M), one=False)[0], 'keep', 'a session not opened for one ask: control_idle')
    eq(v(queued(5 * M, 'Queued F7. Want me to put it first?'))[0], 'keep', 'ending in a question: not closed early')
    refused = queued(5 * M)
    refused[2] = _result('p1', 'agent-runner plan: not added: already open, and may be the same work:', 5 * M + 19)
    eq(v(refused)[0], 'keep', 'a plan add that filed nothing: not queued')
    eq(v(queued(5 * M), c={**cf, 'quick': 0.0})[0], 'keep', 'control_idle_quick = false: control_idle')
    # the runner's /rename and hook or system turns are not the person's messages
    noise = [{'type': 'user', 'timestamp': _ts(5 * M + 2), 'message': {'role': 'user', 'content':
              '<command-name>/rename</command-name>\n<command-message>rename</command-message>'}},
             {'type': 'user', 'timestamp': _ts(5 * M + 1), 'isMeta': True, 'message': {'role': 'user', 'content':
              [{'type': 'text', 'text': 'Caveat: the messages below were generated by the user while running local commands.'}]}},
             {'type': 'user', 'timestamp': _ts(5 * M), 'message': {'role': 'user', 'content':
              '<local-command-stdout>Session renamed</local-command-stdout>'}}]
    rows = queued(5 * M + 10) + noise
    eq(R.control_state(rows)['said'], 1, 'slash command, its output and a meta turn: not counted')
    eq(v(rows)[0], 'close', 'and Claude still counts as last: closed at 5 min')
    # a second person message: 12 h
    eq(R.control_state(talked(0))['said'], 2, 'two person messages')
    eq(v(talked(11 * H))[0], 'keep', 'talked: open at 11 h')
    eq(v(talked(12 * H)), ('close', 'idle 720 min (talked)'), 'talked: closed at 12 h')
    eq(v(talked(2 * H, 'Done. Should I also drop T9?'))[0], 'ask', 'talked, open question: control_ask_idle as before')
    eq(v(talked(4 * H), c={**cf, 'talked': 0.0})[0], 'close', 'control_idle_talked = false: control_idle')
    with mock.patch.dict(R.C.run, {'control_idle_quick': False, 'control_idle_talked': '1d'}):
        eq((R.control_cfg()['quick'], R.control_cfg()['talked']), (0.0, 86400.0), 'read from [run]')

    # close_controls end to end: the one-ask mark, and c1 never closed whatever its transcript says
    notes = R.C.notes()
    notes.mkdir(parents=True, exist_ok=True)
    rows = {'s1': queued(6 * M), 's2': queued(6 * M), 's3': queued(6 * M), 's4': talked(13 * H), 's5': talked(11 * H)}
    for n in range(1, 6):
        (notes / f'control{n}.pid').write_text(f'{9100 + n} s{n}', encoding='utf-8')
    R.control_mark_ask(1, 's1')
    R.control_mark_ask(2, 's2')
    R.control_mark_ask(3, 'another-sid')  # the mark of a conversation /clear left behind
    ended = []
    live = lambda n: 9100 + n if (notes / f'control{n}.pid').exists() else 0
    try:
        with mock.patch.object(R, 'control_live', live), mock.patch.object(R, 'transcript', lambda s: f'/t/{s}'), \
                mock.patch.object(R, 'entries', lambda s, skip_bad=False: iter(rows[s])), \
                mock.patch.object(R.plat, 'terminate', ended.append), mock.patch.object(R, 'control_ok', lambda: True), \
                mock.patch.object(R, 'log'), mock.patch.object(R, 'note'):
            got = R.close_controls(force=True, now=now)
        eq(sorted(got), [(2, 'closed', 'idle 6 min (one ask, queued)'), (4, 'closed', 'idle 780 min (talked)')],
           'the marked one-ask session and the talked one past 12 h closed')
        eq(sorted(ended), [9102, 9104], 'c1 never closed, the stale mark and the 11 h talk kept')
        check(R.control_one_ask(2, 's2') and not R.control_one_ask(3, 's3'), 'the mark names its conversation')
    finally:
        for n in range(1, 6):
            (notes / f'control{n}.pid').unlink(missing_ok=True)
            R.control_mark_ask(n, '')


def test_plan_last(repo: Path):
    print('run: F43 a task with `after: all above` starts only once every task above it in its section is done')
    R.init(repo)
    head = ['# TODO', '', '### Next', '']
    rel = '- [ ] **T5** Release: cut the next version | files: CHANGELOG.md | after: all above'
    fu = ['', '### Follow-ups', '', '- [ ] **B9** a follow-up | files: z.py']
    plan = {'ls': []}
    saved = R.plan_text
    R.plan_text = lambda branch: plan['ls']
    try:
        ids = lambda: [t[0] for t in R.tasks('main')]
        plan['ls'] = head + ['- [ ] **F1** one | files: a.py', '- [~] **F2** two BLOCKED: (after F1) waits', rel] + fu
        eq(ids(), ['F1', 'B9'], 'held while an open or a blocked task above it is not done')
        plan['ls'] = head + ['- [~] **F2** two BLOCKED: DECIDE: which?', rel] + fu
        eq(ids(), ['T5', 'B9'], 'picked once the rest are done: a task blocked on a person does not hold it, '
                                'nor does an open Follow-up')
        eq(R.pick({}, set(), 'main')[0], 'T5', 'and a free slot takes it')
        plan['ls'] = head + ['- [ ] **F7** added later | files: q.py', '- [~] **F2** two BLOCKED: DECIDE: which?', rel] + fu
        eq(ids(), ['F7', 'B9'], 'a task added above it later holds it again')
        eq(R.release_line(plan['ls']), 'release: waits on 1 of 1 task (T5): F7', 'status names what it still waits on')
        plan['ls'] = head + [rel.replace('Release: cut the next version', 'Tidy up last')] + fu
        eq(R.release_line(plan['ls']), 'last: ready, nothing left to wait on (T5)', 'a non-release last task gets a line too')
    finally:
        R.plan_text = saved


def test_after_all(repo: Path):
    print('run: F35 an `after: all` task starts only once no open task above it in TODO.md remains')
    R.init(repo)
    rel = '- [ ] **T5** Release: cut the next version | files: CHANGELOG.md | after: all'
    plan = {'ls': []}
    saved = R.plan_text
    R.plan_text = lambda branch: plan['ls']
    try:
        ids = lambda: [t[0] for t in R.tasks('main')]
        later = ['', '### Parked', '', '- [ ] **F9** big future (follow-up, later) | files: p.py']
        plan['ls'] = (['# TODO', '', '### Next', '', '- [ ] **F1** one | files: a.py', '',
                       '### Follow-ups', '', '- [ ] **B2** a follow-up | files: b.py', rel] + later)
        eq(ids(), ['F1', 'B2'], 'unstarted while an earlier open task exists, in any section')
        eq(R.release_line(plan['ls']), 'release: T5 waits for everything before it (2 open)',
           'status gives a count, not an id list')
        plan['ls'] = (['# TODO', '', '### Next', '', '- [~] **C3** BLOCKED: shelved: DECIDE: some day?', '',
                       '### Follow-ups', '', rel] + later)
        eq(ids(), ['T5'], 'starts once they land: a shelved task and a Parked one do not hold it')
        eq(R.pick({}, set(), 'main')[0], 'T5', 'and a free slot takes it')
        eq(R.release_line(plan['ls']), 'release: ready, nothing left to wait on (T5)', 'status says it is ready')
        plan['ls'] = (['# TODO', '', '### Next', '', '- [ ] **F7** queued later | files: q.py', '',
                       '### Follow-ups', '', rel] + later)
        eq(ids(), ['F7'], 'a task queued above it later is waited on too')
        plan['ls'] = ['# TODO', '', '### Next', '', rel.replace('Release: cut the next version', 'Tidy up'),
                      '- [ ] **F8** below it | files: r.py']
        eq(ids(), ['T5', 'F8'], 'any kind; a task below it does not hold it')
    finally:
        R.plan_text = saved


def test_progress_and_release(repo: Path):
    print('status: merged in the window, tasks left and blocked, and how close a queued release is')
    R.init(repo)
    ls = ['# TODO', '', '### Next', '',
          '- [ ] **F1** a feature | files: a.py',
          '- [~] **B2** a bug BLOCKED: (after F1) waits for F1',
          '- [~] **B3** asks BLOCKED: shelved: DECIDE: which one?',
          '- [x] **F4** done already',
          '- [~] **T5** Release: cut the next version | after: B9 BLOCKED: (after B9) old BLOCKED: (after F1, B2, F4, D7) all of it',
          '  - a note under it',
          '', '### Parked', '', '- [ ] **F6** big future work (follow-up, later)']
    eq(R.tasks_left(ls), (3, 2), 'left: open and blocked, not done, not shelved, not Parked; 2 of them blocked')
    eq(R.release_line(ls), 'release: waits on 2 of 4 tasks (T5)',
       'release: its last block\'s list, done and dropped ones not counted as waiting')
    eq(R.release_line(ls[:4] + ['- [ ] **T5** Release v2 | after: F4']), 'release: ready, nothing left to wait on (T5)',
       'an open release task whose `after:` all landed is ready')
    eq(R.release_line(ls[:5]), '', 'no release task queued: no line')
    now = R.dt.datetime.now()
    since = (now - R.dt.timedelta(hours=2)).astimezone().isoformat(timespec='seconds')
    want = len(git(repo, 'log', '--merges', f'--since={since}', '--format=%H', R.default_branch()).split())
    line = R.progress_line('2h', now)
    check(line.startswith(f'merged {want} in the last 2h · '), 'the count matches git log --merges --since', line)
    left, blocked = R.tasks_left(P.lines(R.C.todo))
    check(f'· {left} task' in line and (f'({blocked} blocked)' in line) == bool(blocked), 'and the TODO\'s counts', line)
    eq(R.progress_line('yesterday', now).split(' · ')[0].split(' ', 2)[2], 'since yesterday', 'yesterday counts from its midnight')
    text = R.status_text(False, {}, [], {}, 0.0, progress=line + '\nrelease: waits on 2 of 4 tasks (T5)')
    eq(text.splitlines(), ['no run is up', line, 'release: waits on 2 of 4 tasks (T5)'], 'status: right under the run line')
    from agent_runner.guide import CONTROL
    check('release:' in CONTROL and 'tasks left' in CONTROL and 'how close is release' in CONTROL,
          'the control brief puts both in the headline and answers "how close is release" from them')


def test_control_status_rules(repo: Path):
    """F39: every status a control session writes names IDs with titles and minutes, leads with needs-you, and
    leaves usage out below 80% (or 10 points short of a cap)."""
    from agent_runner.guide import CONTROL, CONTROL_START, CONTROL_WATCH, RUNNER_BRIEF
    text = CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                          needs='Needs you', answer='')
    check('Never a bare task ID' in text and 'short title' in text and 'its minutes' in text,
          'the control brief: each task ID with its short title and a running one with its minutes', text)
    check('first line' in text and 'Nothing needs you.' in text, 'the first line says what needs the person', text)
    check('80%' in text and 'within 10 points of a configured cap' in text and 'weekly_max' in text,
          'usage only at or past 80% or near a cap', text)
    check('push notification' in text, 'the rules cover push notifications too', text)
    check('Nothing needs you' in CONTROL_START, 'the opening prompt asks for the needs-you first line', CONTROL_START)
    check('never a bare ID' in RUNNER_BRIEF, 'the runner feed pushes name tasks with their titles', RUNNER_BRIEF)


def test_control_do_it_here(repo: Path):
    """F50: after queueing, the control brief offers to run the task in this session, and maps that ask to take ID."""
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    text = CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                          needs='Needs you', answer='')
    check('Say "do F48 here" to start it in this session' in text and 'instead of waiting for a slot' in text,
          'the add-a-task bullet ends with the do-it-here hint', text)
    from agent_runner.guide import topic
    take = ' '.join(topic('take', './run').split())
    check('"do F48 here"' in text and '`./run guide take`' in text, 'C2: the brief points "do F48 here" at guide take', text)
    check('"do it here"' in take and '`./run take F48` on the queued task' in take
          and '`./run take F48 --merge`' in take and 'ask which' in take,
          'the take guide maps "do F48 here" to take ID, then take ID --merge, and asks which with several', take)


def test_control_retitle_on_topic(repo: Path):
    """F55: the control brief retitles the session when the topic changes, not for drift, never over the person's name."""
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    text = ' '.join(CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                                   needs='Needs you', answer='').split())
    check('`./run control --title "' in text, 'the brief names control --title', text)
    check('Run it again whenever the conversation moves on to a different task or topic' in text,
          'it retitles when the conversation moves on to another task', text)
    check('not for drift within one topic' in text, 'not for drift within one topic', text)
    check('A name the person gave the session is never overwritten' in text, 'B41: never over the person\'s name', text)
    check('first message, run `./run control --title' in text and '" once (e.g.' not in text,
          'no longer "once": the name may follow the topic', text)


def test_idle_control_not_waiting():
    """B56: an idle control session is not waiting on the person: its run.log lines put out no needs-you line
    (so the feed pushes nothing), and the feed's hand-off and other replies read as reports, never as an ask
    (the Claude apps show the feed's last reply as its status)."""
    from agent_runner.guide import RUNNER_BRIEF, RUNNER_START
    now = R.dt.datetime.now()
    stamp = now.isoformat(timespec='seconds')
    for msg in ('control 4: closed, quiet 1h', 'control: c1 is up in window c1 (run control opens another)',
                'control 3: ended, its Remote Control session was closed online',
                'control: control server up as "r · control" at https://claude.ai/code (pid 12)'):
        line = f'=== {stamp} {msg}'
        eq(R.needs_you_line(line, {}, now, []), None, f'B56: no needs-you line for {msg!r}')
        got, _ = R.follow_lines(line, {}, now, needs_you=True, waiting=[])
        eq(got, [], f'B56: since --follow --needs-you stays quiet for {msg!r}')
    rb = ' '.join(RUNNER_BRIEF.format(cmd='run', repo='r', answer='').split())
    check('That goes to a control session' not in rb and '"Sent to control N: <the link>"' in rb,
          'B56: the feed hands an ask off with a report, not "That goes to a control session"', rb)
    check('"Opened control N: <the link>"' in rb, 'B56: a new control session is reported, not offered', rb)
    check('never an ask' in rb and 'last reply as its status' in rb,
          'B56: the feed brief says every reply is a report, since the apps read an ask as waiting on you', rb)
    start = RUNNER_START.format(cmd='run', repo='r')
    check('?' not in start, 'B56: the feed\'s opening line asks nothing', start)


def test_needs_cmd_f44():
    """F44: `needs` prints only what waits on the person, 'ID - what to do' each, then a summary line; the feed
    brief ends an idle reply with its first item and the control brief answers 'what is waiting on me' with it."""
    from agent_runner import plan as P
    from agent_runner.guide import CONTROL, CONTROL_WATCH, RUNNER_BRIEF
    eq(P.needs_lines([]), ['Nothing needs you'], 'F44: nothing waiting')
    r7 = ('DECIDE', 'R7', '', 'pick which config changes to build', '', 'Config review', False)
    r6 = ('CONFIRM', 'R6', '', 'Windows desktop check - reply with what you saw', 'https://x.example/r6',
          'R6 long title', False, '2026-11-20 10:00')
    shelved = ('CONFIRM', 'R2', '', 'phone check', '', 'Phone', True)
    eq(P.needs_lines([r7, shelved]), ['R7 - pick which config changes to build',
                                      '1 thing needs you'], 'F44: one item, the shelved one left out')
    eq(P.needs_lines([r7, r6]), ['R7 - pick which config changes to build',
                                 'R6 - Windows desktop check, reply with what you saw', '2 things need you'],
       'F44: two items, the agent\'s own reply hint kept and no link')
    long = ('BLOCKED', 'B9', '', 'log in to the dashboard and turn on builds. Then also do many other things '
            'that make this very long indeed', '', 't', False)
    got = P.needs_lines([long])[0]
    eq(got, 'B9 - log in to the dashboard and turn on builds', 'F44: a long ask keeps its first sentence only')
    concept = ('CONCEPT', 'F9', 'K4', P.CONCEPT_ASK, 'https://x.example/k4', 'Sync options', False)
    eq(P.needs_lines([concept])[0], 'K4 - pick an option for sync options', 'F44: a concept by its K id')
    rb = ' '.join(RUNNER_BRIEF.format(cmd='run', repo='r', answer='').split())
    check('`run needs`' in rb and 'first item line' in rb and 're-arming the Monitor' in rb and 'Nothing needs you' in rb,
          'F44: the feed ends an idle reply with `needs`\' first item', rb)
    text = ' '.join(CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                                   needs='Needs you', answer='').split())
    check('"what is waiting on me?"' in text and '`./run needs`' in text.split('"what is waiting on me?"', 1)[1][:200],
          'F44: the control brief answers "what is waiting on me" with `needs`', text)


def test_control_push_when_asked():
    """B81: the control brief pushes what the person asked to hear (its own subagent/take finishing included),
    and finished/stuck/needs-you events while they are away; it never promises a push it cannot send."""
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    text = ' '.join(CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                                   needs='Needs you', answer='').split())
    part = text.split('Push what the person asked to hear', 1)[-1].split(' - ', 1)[0]
    check('Push what the person asked to hear' in text and 'PushNotification' in part
          and 'ToolSearch `select:PushNotification`' in part, 'the brief says to push, loading the tool via ToolSearch', part)
    check('subagent' in part and '`take`' in part and 'no Monitor sees it' in part,
          'a "notify me" ask on its own background work (subagent, take) is pushed when it reports', part)
    check('finished or got stuck' in part and 'needs the person' in part and 'not written here' in part,
          'finished-take, stuck and needs-you events are pushed unasked while the person is away', part)
    check('Never promise a notification you cannot send' in part and 'say so' in part,
          'it never promises a push it cannot send', part)


def test_take_running_slot(repo: Path):
    """F52: `take ID` on a task a slot runs names the slot, its claude.ai/code link and how to steer it."""
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    R.init(repo)
    add = run(repo, 'plan', 'add', 'T', 'a slot runs me', '--files', 'w52.py')
    tid = re.search(r'\b(T\d+)\b', add.stdout + add.stderr)[1]
    d = task_branch(repo, 5, tid)
    try:
        r = run(repo, 'take', tid)
        eq(r.returncode, 1, 'take refuses a task a slot runs')
        has(r.stderr, rf'{tid}: running in slot s5', f'and names the slot: {r.stderr}')
        has(r.stderr, r'attach s5', 'with the attach line')
        has(r.stderr, rf'plan tell {tid} ', 'and how to steer it')
        check('claude.ai/code' not in r.stderr, 'no link while remote_slots is off', r.stderr)
        check(not (R.SLOTS_DIR / f'take-{tid}').exists(), 'and starts nothing')
        eq(R.running_slot(tid), 5, 'running_slot finds the slot worktree on task/<ID>')
        rows = [{'type': 'user', 'message': {'content': 'hi'}}, {'type': 'bridge-session', 'bridgeSessionId': 'cse_abc'}]
        with mock.patch.object(R, 'remote_slots_on', lambda: True), \
                mock.patch.object(R.MUX, 'panes', lambda: {'s5': ('%1', 4242)}), \
                mock.patch.object(R.MUX, 'session_id', lambda pid: 'sid-52' if pid == 4242 else None), \
                mock.patch.object(R.plat, 'alive', lambda pid: True), \
                mock.patch.object(R, 'entries', lambda sid, skip_bad=False: iter(rows if sid == 'sid-52' else [])):
            msg = R.slot_running(tid)
        has(msg, rf'running in slot s5', msg)
        check(f'{R.REMOTE_URL}/session_abc' in msg, 'pane pid -> session -> bridge-session -> its link', msg)
        with mock.patch.object(R, 'remote_slots_on', lambda: False):
            eq(R.slot_link(5, tid), '', 'remote_slots off: no link')
    finally:
        git(d, 'checkout', '-q', '--detach')
        git(repo, 'branch', '-D', f'task/{tid}')
    from agent_runner.guide import topic
    text = topic('take', './run')
    check('When take says the task is running in a slot, start nothing' in text and '`./run attach sN`' in text
          and '`./run plan tell ID "..."`' in text and 'claude.ai/code link' in text,
          'the take guide: a running slot means give the link or attach line, start nothing', text)
    check('`./run guide take`' in CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(
        repo='r', cmd='./run'), needs='Needs you', answer=''), 'C2: and the control brief points there')


def test_runner_route_b54(repo: Path):
    """B54: the feed sends an ask about agent-runner itself to agent-runner's own control session, labelled with
    the project, and a hand-off whose words share nothing with the waiting items carries none of them."""
    import contextlib
    import io
    from agent_runner.guide import RUNNER_BRIEF
    rb = ' '.join(RUNNER_BRIEF.format(cmd='run', repo='iFizBox', answer='').split())
    check('`run control --new --forward --runner`' in rb and 'agent-runner itself' in rb and 'releases' in rb
          and '"Sent to agent-runner control N: <the link>"' in rb, 'B54: the feed brief routes agent-runner asks', rb)
    check('`run upgrade`' in rb and 'update runner' in rb, 'B54: updating this run is still answered in the feed', rb)
    item = ('DECIDE', 'R43', '', 'Deploy on every push or on v* tags?', '', 'How should the site deploy')
    with mock.patch.object(R.P, 'asks', lambda *a, **k: [item]):
        eq(R.control_ask('update runner, when is release?'), 'update runner, when is release?',
           'B54: an ask that shares nothing with the waiting items carries none, and no order to settle one')
        check('<runner-waiting>' in R.control_ask('R43: tags please'), 'B54: an ask naming the item carries it')
        check('<runner-waiting>' in R.control_ask('yes'), 'B54: a bare reply carries the items it can answer')
        check('<runner-waiting>' in R.control_ask('deploy only on tags'), 'B54: an ask on the same subject carries it')
    eq(R.waiting_for_ask('fix the login page', '- R43: Deploy on every push?\n- B9: login page shows an error'),
       '- B9: login page shows an error', 'B54: only the related item of several')
    # the route: the feed's message read here, opened in agent-runner's checkout with the label, no waiting block
    other = repo.parent / 'agent-runner-co'
    other.mkdir(exist_ok=True)
    runs = []
    done = lambda *a, **k: runs.append((a, k)) or R.sp.CompletedProcess(a, 0, 'control 3 is up: https://claude.ai/code/x\n', '')
    out = io.StringIO()
    with mock.patch.object(R, 'runner_checkout', lambda: other), mock.patch.object(R, 'feed_sid', lambda: 's'), \
            mock.patch.object(R, 'feed_take', lambda sid, w: 'update runner, when is release?'), \
            mock.patch.object(R, 'feed_wait', lambda *a, **k: (True, ['/tmp/p.png'], 0, '')), \
            mock.patch.object(R.sp, 'run', done), contextlib.redirect_stdout(out):
        rc = R.control_new_runner()
    cmd, kw = runs[0][0][0], runs[0][1]
    ask = next(x for x in cmd if x.startswith('--ask='))
    eq(rc, 0, 'B54: control --new --runner exits as the session it opened')
    check(kw['cwd'] == str(other) and cmd[cmd.index('--from-feed') + 1] == R.ROOT.name and '--new' in cmd
          and 'update runner, when is release?' in ask and f'from the {R.ROOT.name} runner feed' in ask
          and '<runner-waiting>' not in ask and cmd[cmd.index('--file') + 1] == '/tmp/p.png'
          and 'AGENT_RUNNER_REPO' not in kw['env'], 'B54: opened in agent-runner\'s checkout, labelled', cmd)
    check(out.getvalue().startswith('agent-runner control 3 is up: https://claude.ai/code/x'),
          'B54: the feed is told it went to agent-runner', out.getvalue())
    runs.clear()
    with mock.patch.object(R, 'runner_checkout', lambda: other), mock.patch.object(R, 'feed_sid', lambda: 's'), \
            mock.patch.object(R, 'feed_take', lambda sid, w: None), mock.patch.object(R.sp, 'run', done), \
            contextlib.redirect_stdout(io.StringIO()):
        R.control_new_runner()
    check(runs and runs[0][1]['cwd'] == str(other) and any(R.feed_lost_note() in x for x in runs[0][0][0]),
          'B54: an unreadable message still goes to agent-runner, which asks for it again', runs)
    opened = []
    with mock.patch.object(R, 'runner_checkout', lambda: R.ROOT), \
            mock.patch.object(R, 'control_new', lambda *a, **k: opened.append(k) or 0):
        R.control_new_runner()
    eq(opened[0].get('forward'), True, 'B54: in agent-runner itself, a plain --forward')
    from agent_runner.config import CLONE_ENTRY
    if CLONE_ENTRY.exists():
        found = R.runner_checkout()
        check(found is not None and (found / R.RUNNER_REPO_MARK).is_file(), 'B54: the clone this runs from is found', found)


def test_upgrade_cmd(repo: Path):
    """B49: `upgrade` runs the existing upgrade() (as `u` does), and the control brief names the command."""
    import contextlib
    import io
    from agent_runner import cli
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    calls = []
    with mock.patch.object(cli, 'skill', lambda: None), \
            mock.patch.object(R, 'upgrade', lambda: calls.append(1) or True), \
            mock.patch.object(R, 'installed_version', lambda: __import__('agent_runner').__version__):
        rc = cli.main(['upgrade'])
    eq((rc, calls), (0, [1]), 'agent-runner upgrade calls upgrade() once and exits 0')
    with mock.patch.object(cli, 'skill', lambda: None), mock.patch.object(R, 'upgrade', lambda: False), \
            contextlib.redirect_stderr(io.StringIO()):
        eq(cli.main(['upgrade']), 1, 'a failed upgrade exits 1')
    text = CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                          needs='Needs you', answer='')
    check('Update agent-runner: `./run upgrade`' in text, 'the rendered control brief names `upgrade`', text)
    check('agent-runner upgrade' in cli.USAGE, 'the command list names `upgrade`', cli.USAGE)


def test_control_no_upgrade_watcher():
    """D2: the control brief says runner updates come from [run] auto_upgrade and the release task, so a
    control session never sets up a background watcher to upgrade agent-runner."""
    from agent_runner.guide import CONTROL, CONTROL_WATCH
    text = ' '.join(CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                                   needs='Needs you', answer='').split())
    check('Runner updates otherwise come from `[run] auto_upgrade` and the release task' in text
          and 'never set up a background watcher, Monitor or loop to upgrade agent-runner' in text,
          'the control brief rules out an upgrade watcher', text)


def test_split_modules_c3():
    """C3: runner.py is split into modules that import each other with no cycle (module-level imports), and
    `runner.X = v` (a test's stand-in, a wrapping project's PROMPT) reaches every module that uses X."""
    import ast
    pkg = Path(R.__file__).parent
    deps = {}
    for f in pkg.glob('*.py'):
        names = set()
        for node in ast.parse(f.read_text(encoding='utf-8')).body:
            if isinstance(node, ast.ImportFrom) and node.module == 'agent_runner':
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and (node.module or '').startswith('agent_runner.'):
                names.add(node.module.split('.')[1])
        deps[f.stem] = {n for n in names if (pkg / f'{n}.py').exists()}
    seen, cycle = {}, []

    def visit(m: str, path: list[str]) -> None:
        seen[m] = 1
        for d in sorted(deps.get(m, ())):
            if seen.get(d) == 1 and not cycle:
                cycle.extend(path[path.index(d):] + [d])
            elif d not in seen:
                visit(d, path + [d])
        seen[m] = 2

    for m in sorted(deps):
        if m not in seen:
            visit(m, [m])
    check(not cycle, 'no agent_runner module imports in a cycle', ' -> '.join(cycle))
    big = {f.stem: n for f in pkg.glob('*.py') if f.stem in R.FAMILY
           and (n := len(f.read_text(encoding='utf-8').splitlines())) > 1500}
    check(not big, 'each module runner.py was split into is under 1500 lines', big)
    from agent_runner import loop, merge, slots
    was = R.AHEAD_POLL, R.SLOTS
    try:
        R.AHEAD_POLL, R.SLOTS = 0.25, 7
        check(merge.AHEAD_POLL == 0.25 and slots.SLOTS == 7 and loop.SLOTS == 7,
              'runner.X = v sets X in the modules that use it')
    finally:
        R.AHEAD_POLL, R.SLOTS = was
    check(merge.AHEAD_POLL == was[0] and slots.SLOTS == was[1], 'and putting it back puts it back everywhere')


def test_release_push(repo: Path):
    """F51: a merge that brings a release logs '<repo> X.Y.Z released: <first changelog line>', which
    `since --follow` prints and the runner feed pushes; and the control brief covers 'notify me when'."""
    import contextlib
    import io
    from agent_runner.guide import CONTROL, CONTROL_WATCH, RUNNER_BRIEF
    R.init(repo)
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'CHANGELOG.md').write_text(
        '# Changelog\n\n## Unreleased\n\n## 1.2.0 (2026-11-20)\n\n- Phones hear releases: the feed pushes\n'
        '  one line. More words here.\n- Another change.\n\n## 1.1.0\n\n- Old.\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'release 1.2.0')
    merged = git(repo, 'rev-parse', 'HEAD')
    try:
        eq(R.release_line_for(base, merged), f'{repo.name} 1.2.0 released: Phones hear releases: the feed pushes one line.',
           'a new top version heading is a release, with its first bullet, unwrapped, to its first sentence')
        eq(R.release_line_for(merged, merged), None, 'no new heading: no release')
        git(repo, 'commit', '-q', '--allow-empty', '-m', 'tagged')
        tagged = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'tag', 'v1.2.1')
        eq(R.release_line_for(merged, tagged), f'{repo.name} 1.2.1 released: tagged',
           'a new version tag is a release too, with its subject when the changelog has no entry')
        logf = R.C.notes('run.log')
        logf.parent.mkdir(parents=True, exist_ok=True)
        R.RELEASES_SAID.discard('1.2.0')
        def land():
            R.announce_release(base, merged)
            R.announce_release(base, merged)  # a batch: the second task of the same merge
        threading.Timer(0.5, land).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(R, 'move_since_mark', lambda s: None):
            R.follow(poll=0.1, until=time.monotonic() + 2)
        got = [l for l in out.getvalue().splitlines() if 'released' in l and not l.startswith('===')]  # log() echoes
        eq(len(got), 1, f'since --follow prints the release once: {out.getvalue()}')
        check(got and got[0].endswith(f'  {repo.name} 1.2.0 released: Phones hear releases: the feed pushes one line.'),
              'the release line reaches since --follow as it is', got)
    finally:
        git(repo, 'tag', '-d', 'v1.2.1')
        git(repo, 'reset', '-q', '--hard', base)
    rb = ' '.join(RUNNER_BRIEF.format(cmd='run', repo='r', answer='').split())
    check('released' in rb and 'PushNotification' in rb.split('Releases:', 1)[-1].split('- Commands', 1)[0],
          'the feed brief says to push each release line', rb)
    text = ' '.join(CONTROL.format(repo='r', cmd='./run', log='l', watch=CONTROL_WATCH.format(repo='r', cmd='./run'),
                                   needs='Needs you', answer='').split())
    part = text.split('"notify me when X"', 1)[-1].split(' - ', 1)[0]
    check('"notify me when X"' in text and 'since --follow' in part and 'PushNotification' in part
          and 'stop that Monitor' in part and 'say back in one line what you will watch for' in part,
          'the control brief covers "notify me when": watch, push once, stop, and say what it watches for', text)


def test_help_order_and_bare_wizard(tmp: Path):
    """F48: --help lists what a person types before the agents' section; bare `wizard` runs the one that
    waits, lists them when several, says when there are none."""
    from agent_runner import cli
    cut = cli.USAGE.index('Mostly for agents')
    for c in ('attach', 'control', 'status', 'wizard', 'guide', 'plan add'):
        check(0 <= cli.USAGE.find(f'agent-runner {c}') < cut, f'`{c}` is in the person section')
    for c in ('take B646', 'done B646', 'resume', 'plan block', 'run once', 'force'):
        check(cli.USAGE.find(f'agent-runner {c}') > cut, f'`{c}` is in the agents section')
    check('agent-runner wizard B646' not in cli.USAGE, 'the wizard line has no id')
    if not shutil.which('bash'):
        print('  skip: no bash here')
        return
    root = tmp / 'f48'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'runner.toml').write_text('[run]\nremote = false\n', encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('signing setup | files: a.py', 'store login | files: b.py', 'push cert | files: c.py'):
        check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
    r = run(root, 'wizard', env=env)
    check(r.returncode == 0 and 'No wizard waits' in r.stdout, 'none waiting: says so', r.stdout + r.stderr)
    wiz = root / '.runner' / 'wizards'
    wiz.mkdir(parents=True)
    for tid in ('F1', 'F2'):
        r = run(root, 'done', tid, f'{tid}: hand step', '--no-test', '--blocked', 'BLOCKED: a login', env=env)
        check(r.returncode == 0, f'{tid} blocked with BLOCKED:', r.stdout + r.stderr)
        (wiz / f'{tid}.sh').write_text(f'#!/usr/bin/env bash\necho ran > {tid}.out\n', encoding='utf-8')
    (wiz / 'F2.sh').rename(wiz / 'F2.later')
    r = run(root, 'wizard', env=env, stdin=subprocess.DEVNULL)
    check(r.returncode == 0 and (root / 'F1.out').is_file(), 'one waiting: runs it', r.stdout + r.stderr)
    has((root / 'plan' / 'TODO.md').read_text(encoding='utf-8'), r'^- \[ \] \*\*F1\*\* .*the wizard ran',
        'and confirms it')
    (wiz / 'F1.sh').write_text('#!/usr/bin/env bash\necho again > F1.again\n', encoding='utf-8')
    (wiz / 'F2.later').rename(wiz / 'F2.sh')
    r = run(root, 'done', 'F3', 'F3: hand step', '--no-test', '--blocked', 'BLOCKED: a cert', env=env)
    check(r.returncode == 0, 'F3 blocked with BLOCKED:', r.stdout + r.stderr)
    (wiz / 'F3.sh').write_text('#!/usr/bin/env bash\necho ran > F3.out\n', encoding='utf-8')
    r = run(root, 'wizard', env=env, stdin=subprocess.DEVNULL)
    check(r.returncode == 0 and '2 wizards' in r.stdout and 'F2' in r.stdout and 'F3' in r.stdout
          and 'F1' not in r.stdout, 'several waiting: lists them (not F1, confirmed)', r.stdout + r.stderr)
    check(not any((root / n).exists() for n in ('F1.again', 'F2.out', 'F3.out')), 'and runs none')


def test_setup(tmp: Path):
    print('agent-runner setup: backs up dirty work to a branch, runner.toml only when missing, a plan prompt')
    import contextlib
    import datetime
    import io
    from agent_runner import cli
    from agent_runner import setup as S
    root = tmp / 'f49'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'app.py').write_text('print(1)\n', encoding='utf-8')
    (root / 'Makefile').write_text('test:\n\tpython3 -c pass\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    (root / 'app.py').write_text('print(2)\n', encoding='utf-8')  # a tracked edit, and an untracked file
    (root / 'new.txt').write_text('draft\n', encoding='utf-8')
    status = git(root, 'status', '--porcelain')
    launched: list = []
    out = io.StringIO()

    def setup(argv: list[str]) -> int:
        with contextlib.redirect_stdout(out):
            return S.main(argv, cwd=root)

    with mock.patch.object(S, 'launch', lambda r, text: launched.append((r, text)) or 0), \
            mock.patch.object(S, 'ask', lambda q: launched.append(('asked', q)) or False):
        eq(setup([]), 0, 'setup on a dirty repo')
        name = f'runner-setup-backup-{datetime.date.today().isoformat()}'
        has(out.getvalue(), re.escape(name), 'says the backup branch name')
        eq(git(root, 'show', f'{name}:app.py'), 'print(2)', 'the backup has the tracked edit')
        eq(git(root, 'show', f'{name}:new.txt'), 'draft', 'and the untracked file')
        eq(git(root, 'rev-parse', f'{name}^'), git(root, 'rev-parse', 'main'), 'on top of main')
        eq(git(root, 'rev-parse', '--abbrev-ref', 'HEAD'), 'main', 'still on main')
        eq((root / 'app.py').read_text(encoding='utf-8'), 'print(2)\n', "main's working tree unchanged")
        eq((root / 'new.txt').read_text(encoding='utf-8'), 'draft\n', 'the untracked file too')
        after = [l for l in git(root, 'status', '--porcelain').splitlines()
                 if 'runner.toml' not in l and 'CLAUDE.md' not in l]  # CLAUDE.md: B80's ## Tools
        eq(after, status.splitlines(), 'the same files still uncommitted, nothing staged')
        toml = (root / 'runner.toml').read_text(encoding='utf-8')
        has(toml, r'^test = "make test"', 'runner.toml written, with the Makefile gate')
        eq(len(launched), 1, 'one session launched (no plan yet: no question)')
        r, text = launched[0]
        eq(r, root.resolve(), 'in the repo')
        for want in (r'plan add', r'plan goal', r'\[run\] test', 'make test', 'CLAUDE.md', 'AGENTS.md'):
            has(text, want, f'the prompt names {want}')
        has(out.getvalue(), r'Start the run: agent-runner', 'ends with how to start')
        (root / 'runner.toml').write_text('[run]\ntest = "mine"\n', encoding='utf-8')
        (root / 'plan').mkdir()
        (root / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **F1** x\n', encoding='utf-8')
        launched.clear()
        eq(setup([]), 0, 'setup again on a set-up repo')
        eq((root / 'runner.toml').read_text(encoding='utf-8'), '[run]\ntest = "mine"\n', 'runner.toml kept')
        check(launched and launched[0][0] == 'asked' and len(launched) == 1, 'asks first; a no starts nothing',
              launched)
        check(f'{name}-2' in git(root, 'branch'), 'a second backup gets its own branch')
        launched.clear()
        eq(setup(['--yes']), 0, 'with --yes')
        check(len(launched) == 1 and 'already has a task list' in launched[0][1], 'it goes on, told to add to it',
              launched)
    cut = cli.USAGE.index('What you type')
    eq(cli.USAGE[cut:].splitlines()[1].split()[:2], ['agent-runner', 'setup'], "setup heads the person section")


def test_stop_countdown(repo: Path):
    """F42: once a stop is asked for, each feed line says how many tasks the stopping run still waits for;
    the stop and its undo are feed and since events themselves; no count before a stop or after its undo."""
    R.init(repo)
    titles = {'C20': 'node.mjs', 'F5': 'Control session experience', 'B9': 'Fix the flicker'}
    now = R.dt.datetime(2026, 11, 19, 15, 0)
    log = ['=== 2026-11-19T13:40:00 slot 1: B9 (Next; a.py)',
           '=== 2026-11-19T13:41:00 F5: merged, ticked',
           '=== 2026-11-19T13:50:00 stopping: no new tasks; the running ones finish and merge, then the run ends',
           '=== 2026-11-19T13:50:01 stop asked for: 4 left before the run exits',
           '=== 2026-11-19T13:54:00 C20: merged, ticked',
           '=== 2026-11-19T13:54:30 C20: merged and pushed',  # the same task again: counted once
           '=== 2026-11-19T13:55:00 B9: not merged, parked as wip/B9 — tests fail. Its 2 commits are kept there.',
           '=== 2026-11-19T13:56:00 slot 2: F5 looks stalled (no output for 20 min); look at s2']
    with mock.patch.object(R, 'what_changed', lambda tid: ''):
        lines, _ = R.follow_lines('\n'.join(log), titles, now)
        eq(lines, ['13:40  started: Fix the flicker [B9]',
                   '13:41  landed: Control session experience [F5]',
                   '13:50  stop requested: 4 left before the run exits',
                   '13:54  landed: node.mjs [C20] · 3 left',
                   '13:55  stuck, not merged: Fix the flicker (tests fail) [B9] · 2 left',
                   '13:56  looks stuck: Control session experience [F5] · 2 left'],
           'no count before the stop; then each line says how many are left')
        lines, _ = R.follow_lines('\n'.join(log), titles, now, needs_you=True)
        eq(lines, ['13:55  stuck, not merged: Fix the flicker (tests fail) [B9] · 2 left',
                   '13:56  looks stuck: Control session experience [F5] · 2 left'], 'the needs-you watch counts too')
        ask = [('DECIDE', 'C20', '', 'Postgres or SQLite?', '', 'node.mjs', False)]
        lines, _ = R.follow_lines('\n'.join(log[:5]), titles, now, waiting=ask)
        check(lines[-1].startswith('13:54  needs you: Postgres or SQLite?') and lines[-1].endswith(' · 3 left'),
              'an ask a landed line brings carries the count too', lines)
        stop: dict = {}  # follow keeps the count from one chunk to the next
        R.follow_lines('\n'.join(log[:4]), titles, now, stop=stop)
        lines, _ = R.follow_lines('\n'.join(log[4:5]), titles, now, stop=stop)
        eq(lines, ['13:54  landed: node.mjs [C20] · 3 left'], 'the count carries across chunks')
        R.follow_lines('=== 2026-11-19T13:57:00 dropped F5; stopped s2', titles, now, stop=stop)
        eq(stop['left'], 2, 'a task dropped while it ran is no longer waited for')
        back = ['=== 2026-11-19T14:00:00 stop taken back: starting tasks again',
                '=== 2026-11-19T14:01:00 F5: merged, ticked']
        lines, _ = R.follow_lines('\n'.join(back), titles, now, stop=stop)
        eq(lines, ['14:00  stop taken back: the run is starting tasks again',
                   '14:01  landed: Control session experience [F5]'], 'taken back: said, and no count after it')
    text, _ = R.since_text(log + back, R.since_start('today', None, now), titles, now)
    check('  13:50  stop requested: 4 left before the run exits' in text.splitlines()
          and '  14:00  stop taken back: the run is starting tasks again' in text.splitlines(),
          'since lists the stop and its undo too', text)
    # the runner's side: one line per change, with what the loop counts
    with mock.patch.object(R, 'STOP_SAID', [False]):
        eq(R.stop_note(False, 3), None, 'no stop: nothing said')
        eq(R.stop_note(True, 3, 'agent-runner stop'),
           'stop asked for: no new tasks; exiting once the running ones are merged; 3 left before the run exits',
           'a stop from the command says what it does and how many are left')
        eq(R.stop_note(True, 2), None, 'said once')
        eq(R.stop_note(False, 2), 'stop taken back: starting tasks again', 'run stop --undo is said too')
        eq(R.stop_note(True, 1, 's'), 'stop asked for: 1 left before the run exits',
           'a key logged its own words: only the count')
        R.stop_note(False, 0)
        said = R.stop_note(True, 5, 'agent-runner stop')
        ev = R.legacy_event(f'=== 2026-11-20T10:00:00 {said}') or {}
        eq((ev.get('kind'), ev.get('left')), (R.EV_STOP_ASKED, 5), 'a run.log line from before F41 reads the count back')


def test_real_claude_json_guard(tmp: Path):
    print('B68: a trust entry a suite leaks into the real ~/.claude.json fails it; other sessions\' entries do not')
    import _check
    fake = tmp / 'b68-real' / '.claude.json'
    fake.parent.mkdir()
    fake.write_text(json.dumps({'projects': {'/old/entry': {}}}), encoding='utf-8')
    ours, other = _check.TMP_ROOT / 'b68-slot', tmp.parent.parent / 'elsewhere-b68'
    with mock.patch.object(_check, 'REAL_CLAUDE_JSON', [fake]), \
            mock.patch.object(_check, '_REAL_BEFORE', {fake: _check._projects(fake)}):
        eq(_check.claude_json_leaks(), [], 'an untouched file: no leak')
        with mock.patch.dict(os.environ, {'CLAUDE_CONFIG_DIR': str(fake.parent)}):
            R.Claude.trust(ours)
            data = json.loads(fake.read_text(encoding='utf-8'))
            data['projects'][other.as_posix()] = {'hasTrustDialogAccepted': True}  # a real session, meanwhile
            data['projects']['C:\\Users\\x\\AppData\\Local\\Temp\\proj-slots\\s1'] = {}
            fake.write_text(json.dumps(data), encoding='utf-8')
        eq(_check.claude_json_leaks(), [ours.resolve().as_posix()], 'the suite\'s own temp folder is a leak; '
                                                                    'the other session\'s entry is not')
    check(Path(tempfile.gettempdir()) == _check.TMP_ROOT and os.environ.get('TMPDIR') == str(_check.TMP_ROOT),
          'the suite and its subprocesses make temp folders under its own root')
    check(all(f != Path(os.environ['CLAUDE_CONFIG_DIR']) / '.claude.json' for f in _check.REAL_CLAUDE_JSON),
          'the suite\'s Claude config is never the real one')
    sys_tmp = _check.SYS_TMP.as_posix()
    data = {'projects': {f'{sys_tmp}/tmpab/proj-slots/s1': {'hasTrustDialogAccepted': True},
                         f'{sys_tmp}/claude-1/x/scratchpad': {'hasTrustDialogAccepted': True, 'lastCost': 1},
                         '/home/me/repo': {'hasTrustDialogAccepted': True}}}
    eq(_check.stale_test_entries(data), [f'{sys_tmp}/tmpab/proj-slots/s1'],
       'cleanup: only a bare trust entry under the temp dir is stale, not a real session\'s or a repo\'s')
    fake.write_text(json.dumps(data), encoding='utf-8')
    with mock.patch.object(_check, 'REAL_CLAUDE_JSON', [fake]), \
            mock.patch('sys.stdout', new_callable=__import__('io').StringIO):
        _check.clean_real_claude_json(['--clean'])
    eq(sorted(json.loads(fake.read_text(encoding='utf-8'))['projects']),
       sorted([f'{sys_tmp}/claude-1/x/scratchpad', '/home/me/repo']), 'and --clean removes just those')


HIDDEN_AGENT = r'''#!/usr/bin/env python3
# F40: a stand-in agent in a hidden slot: says whether it has a terminal, waits for a line typed into it, ends.
import os, sys
print('tty', os.isatty(0), os.get_terminal_size().columns, flush=True)
print('told', repr(sys.stdin.readline().strip()), flush=True)
'''

LANDING_AGENT = r'''#!/usr/bin/env python3
# F40: a stand-in agent that does its task in a hidden slot: one edit, then `done`, as a real session would.
import os, subprocess, sys
tid = subprocess.run(['git', 'branch', '--show-current'], capture_output=True, text=True).stdout.strip()[5:]
open('a.py', 'a').write('# ' + tid + ' was here\n')
r = subprocess.run([sys.executable, os.environ['F40_RUN'], 'done', tid, tid + ' from a hidden slot'],
                   capture_output=True, text=True)
open(os.environ['F40_OUT'], 'a').write(f'{tid} tty={os.isatty(0)} done={r.returncode}\n{r.stdout}{r.stderr}\n')
'''


def wait_dead(pid: int, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not R.plat.alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_hidden_slots(repo: Path, tmp: Path):
    print('F40: a hidden slot (a pty, no window) starts, is adopted by a restarted run, is told a line, and ends')
    if R.plat.WINDOWS:
        return
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')
    agent = tmp / 'hidden-agent'
    agent.write_text(HIDDEN_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    d = R.worktree(5, 'main')
    git(d, 'checkout', '-q', '-B', 'task/Z9', 'main')
    saved = R.MUX, R.C.run['agent']
    R.MUX, R.C.run['agent'] = R.HiddenMux(), str(agent)
    pid = 0
    try:
        logfile, _ = R.slot_header(5, 'Z9 session sid-h')
        pid = R.MUX.open(5, d, 'do Z9', 'sid-h', 'opus', 90, R.slot_env(5), logfile)
        check(pid and R.plat.alive(pid), 'the slot starts, and its agent\'s pid comes back', pid)
        hit = R.MUX.panes().get('s5')
        eq(hit and hit[1], pid, 'it is listed by its marker, which is how a restarted run finds it')
        adopted = R.adopt('main')
        eq(adopted.get(5, ((None, None),))[0][:2], (pid, 'sid-h'), 'a restarted run adopts it: its pid and session id')
        eq(adopted.get(5, (None, ('',)))[1][0], 'Z9', 'and the task its worktree is on')
        check(R.MUX.typed and R.MUX.send(hit, 'hello hidden'), 'a tell is typed into it through its FIFO')
        check(wait_dead(pid), 'the session ends')
        text = logfile.read_text(encoding='utf-8', errors='replace')
        has(text, r'tty True 200', 'it ran in a terminal, 200 columns wide, its output in the slot log')
        has(text, r"told '.*hello hidden", 'and read the line typed into it')
        end = time.monotonic() + 10
        while R.marker_pid(R.C.notes('slot5.live')) and time.monotonic() < end:
            time.sleep(0.1)
        check(not R.C.notes('slot5.live').exists() and not R.C.notes('slot5.in').exists(),
              'its marker and FIFO go when it ends')
        eq(R.C.notes('slot5.exit').read_text(encoding='utf-8'), f'exit code 0 (pid {pid})',
           'how it ended, and its pid, are left for the runner')
        fast = R.C.notes('slot6.exit')
        with mock.patch.object(R.plat, 'spawn_detached', lambda *a, **k: fast.write_text('exit code 0 (pid 4242)')):
            eq(R.MUX.open(6, d, 'do Z9', 'sid-f', 'opus', 90, [], logfile), 4242,
               'a session that ran and ended between two looks at its marker counts as started (and is reaped)')
        fast.unlink()
        check(not R.MUX.send(hit, 'too late'), 'a tell to an ended slot is refused, not left hanging')
        has(R.hidden_line(), r'slots run hidden', 'the run says where to watch hidden slots')
    finally:
        if pid and R.plat.alive(pid):
            R.plat.terminate(pid)
        R.MUX, R.C.run['agent'] = saved
        git(d, 'checkout', '-q', '--detach')
        git(repo, 'branch', '-D', 'task/Z9')
        git(repo, 'worktree', 'remove', '--force', str(d))


def test_hidden_run_lands(tmp: Path):
    print('F40: a run with no tmux on PATH runs its slot hidden and lands the task (worktree, done, gate, merge)')
    if R.plat.WINDOWS:
        return
    (tmp / 'f40').mkdir()
    repo = make_repo(tmp / 'f40')
    agent, out = tmp / 'landing-agent', tmp / 'f40' / 'agent.out'
    agent.write_text(LANDING_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    which = R.shutil.which
    no_tmux = lambda c, *a, **k: None if c == 'tmux' else which(c, *a, **k)
    env = {k: v for k, v in os.environ.items()
           if k not in ('TMUX', 'TMUX_PANE') and not (k.startswith('AGENT_RUNNER') and k != 'AGENT_RUNNER_NO_NOTIFY')}
    # its own home: the suite's other repo is called proj too, and would share its worktrees and task branches
    env |= {'F40_RUN': str(RUN), 'F40_OUT': str(out), 'AGENT_RUNNER_HOME': str(tmp / 'f40' / 'home')}
    saved_sleep, saved_mux = R.time.sleep, R.MUX
    here = os.getcwd()
    os.chdir(repo)
    watchdog = threading.Timer(300, lambda: R.ask_stop('test watchdog', force=True))  # never a hung suite
    try:
        watchdog.start()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(R.shutil, 'which', no_tmux), \
                mock.patch.object(R, 'nap', lambda s: saved_sleep(min(s, 0.5))):
            R.init(repo)
            R.C.run['agent'] = str(agent)
            eq(R.run(['once'], 'run'), 0, 'the run ends after its one task')
            eq(type(R.MUX).__name__, 'HiddenMux', 'no tmux: the slots ran hidden, not an error and not sequential')
    finally:
        watchdog.cancel()
        os.chdir(here)
        R.MUX, R.MASTER_PANE, R.HIDDEN[0] = saved_mux, False, False
        R.C.run['agent'] = 'claude'
    said = out.read_text(encoding='utf-8') if out.exists() else ''
    check('T1 tty=True done=0' in said, 'the agent had a terminal and its done passed', said[-1500:])
    has(git(repo, 'log', '--format=%s', 'main'), r'T1 from a hidden slot', 'and the task landed on main')
    has(git(repo, 'show', 'main:a.py'), r'T1 was here', 'with its edit')
    log = (repo / '.runner/run.log').read_text(encoding='utf-8')
    check('slots run hidden' in log, 'the run said its slots run hidden', log[-1500:])
    check('sequential' not in log, 'and no sequential run')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        os.environ['CLAUDE_CONFIG_DIR'] = str(tmp)  # Claude.trust writes here, never to the real ~/.claude.json
        repo = make_repo(tmp)
        return report([test_paint, lambda: test_master_branch_option(tmp), lambda: test_relative_remote(tmp), lambda: test_picking(repo), lambda: test_parked_twice(repo, tmp), lambda: test_split_parents(repo), lambda: test_blockers_first(repo), lambda: test_done(repo, tmp), lambda: test_merge(repo, tmp),
                       lambda: test_retry(repo), lambda: test_unmerged(repo),
                       lambda: test_conflicts(repo, tmp), lambda: test_fix_ahead(repo, tmp), lambda: test_repair(repo, tmp),
                       lambda: test_prompt_and_hooks(repo),
                       lambda: test_hooks(repo, tmp), lambda: test_run_policies(repo, tmp),
                       lambda: test_no_remote(repo, tmp),
                       lambda: test_gate_and_batches(repo, tmp), lambda: test_blame_and_own_repair(repo, tmp),
                       lambda: test_red_base_and_batch_caps(repo, tmp), lambda: test_merge_order_and_backlog(repo), lambda: test_reserved_ids(repo),
                       lambda: test_platform(repo, tmp), lambda: test_shutdown(repo), lambda: test_merge_into(tmp),
                       lambda: test_leftovers(repo), lambda: test_renumber(repo),
                       lambda: test_stop_waiter(tmp), lambda: test_stop_hook_grace(tmp), lambda: test_land_waits_aloud(repo), lambda: test_merge_ahead(repo), lambda: test_adopted_gate_merge(repo), lambda: test_adopted_gate_results(repo), lambda: test_gate_since(repo), lambda: test_gate_catch_up(repo), lambda: test_owed_merge_goes_first(repo), lambda: test_copies(repo), lambda: test_land_gives_merge_back(repo),
                       lambda: test_edited_elsewhere(repo, tmp),
                       lambda: test_resume(repo, tmp),
                       lambda: test_session_tmp(repo, tmp), lambda: test_end_orphans(repo), lambda: test_memory_watch(repo), lambda: test_tested_ref(repo, tmp), lambda: test_docs_only_gate(repo),
                       lambda: test_no_pane(repo, tmp), lambda: test_other_repos_panes(repo, tmp),
                       lambda: test_limit_resumes(repo, tmp),
                       lambda: test_shared_push(repo, tmp), lambda: test_note_on_a_ticked_task(repo), lambda: test_adopt_merge(repo), lambda: test_followups(repo), lambda: test_person_check_after(repo), lambda: test_ci_watch(repo), test_update_notice, test_restart_if_upgraded, test_auto_upgrade, lambda: test_flake_repair(tmp), lambda: test_repair_per_failure(repo),
                       lambda: test_stalled(tmp), lambda: test_take(repo), lambda: test_take_text_and_here(repo), lambda: test_background(repo), test_short_name_hints, test_utf8_streams, lambda: test_attach_flag(repo), lambda: test_bare_outside_git(tmp), lambda: test_hand_hook(tmp), lambda: test_user_hook(tmp), lambda: test_remote_auto(tmp), lambda: test_control(repo), lambda: test_pane_id_not_a_path(repo, tmp),
                       lambda: test_short_titles_and_since(repo), lambda: test_structured_events(repo),
                       lambda: test_board_follows_run(repo, tmp),
                       lambda: test_remote_sweep(repo, tmp), lambda: test_feed_resume(repo, tmp),
                       lambda: test_concepts_waiting(repo),
                       lambda: test_person_waiting(repo), lambda: test_control_server_old_agent(repo, tmp),
                       lambda: test_drop_or_change_running(repo), lambda: test_tell_running(repo),
                       lambda: test_close_idle_controls(repo), lambda: test_close_control_tiers(repo),
                       lambda: test_closed_online_controls(repo),
                       lambda: test_renamed_control_kept(repo),
                       lambda: test_control_summary_title(repo), lambda: test_control_task_name(repo), lambda: test_progress_and_release(repo),
                       lambda: test_control_status_rules(repo), lambda: test_control_do_it_here(repo), lambda: test_control_retitle_on_topic(repo), test_control_push_when_asked, test_needs_cmd_f44, test_idle_control_not_waiting, lambda: test_take_running_slot(repo), lambda: test_upgrade_cmd(repo), lambda: test_runner_route_b54(repo), test_control_no_upgrade_watcher,
                       test_split_modules_c3, lambda: test_plan_last(repo), lambda: test_after_all(repo), lambda: test_release_push(repo),
                       lambda: test_help_order_and_bare_wizard(tmp), lambda: test_setup(tmp),
                       lambda: test_stop_countdown(repo), lambda: test_real_claude_json_guard(tmp),
                       lambda: test_hidden_slots(repo, tmp), lambda: test_hidden_run_lands(tmp)])


if __name__ == '__main__':
    sys.exit(main())
