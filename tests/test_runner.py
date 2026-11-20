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


def test_done(repo: Path, tmp: Path):
    print('done: gate, tick, commit, push the task branch — never the shared one')
    d = task_branch(repo, 1, 'T5')
    check((d / 'runner.toml').exists(), 'the worktree has the runner.toml')
    trusted = json.loads((tmp / '.claude.json').read_text())['projects'][str(d.resolve())]
    check(trusted.get('hasTrustDialogAccepted'), "the worktree is a folder Claude Code already trusts", trusted)
    check(any('"skipDangerousModePermissionPrompt": true' in a for a in R.Claude().flags('s', 'opus', 30, False, False)),
          'a session skips the bypass-mode warning, which lean mode would otherwise bring back')
    (d / 'd.py').write_text('def log(x):\n    print(x)\n', encoding='utf-8')
    (d / 'BROKEN').write_text('', encoding='utf-8')
    r = run(d, 'done', 'T5', 'T5: the logger')
    check(r.returncode == 1 and 'gate failed' in r.stderr, 'a failing gate refuses', r.stdout + r.stderr)
    check('- [ ] **T5**' in (d / 'plan/TODO.md').read_text(), 'and ticks nothing')
    eq(git(d, 'rev-list', '--count', 'main..HEAD'), '0', 'and commits nothing')
    (d / 'BROKEN').unlink()
    with open(d / 'CHANGELOG.md', 'a') as f:
        f.write('- T5: the logger\n')
    output_env = {**os.environ, 'PYTHONIOENCODING': 'cp1252'}
    r = run(d, 'done', 'T5', 'T5: the logger', env=output_env)
    check(r.returncode == 0, 'a passing gate goes through', r.stdout + r.stderr)
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
    with mock.patch.object(R, 'init'), mock.patch.object(R.plat, 'WINDOWS', False), \
            mock.patch.object(R, 'cmd_background', bg), mock.patch.object(R, 'cmd_attach', at), \
            mock.patch.object(cli, 'skill'):
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
    eq(R.background_argv()[-2:], ['run', '--hidden'], 'Windows: the run, its slot consoles hidden')
    has('\n'.join(R.background_env()), r'^PATH=', 'the tmux session gets this PATH')

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

    rows = ['other\t%1\ts1\t/elsewhere\t', 'ar-proj\t%2\t\t\t' + str(repo), 'ar-proj\t%3\ts1\t' + str(repo) + '\t',
            'ar-proj\t%4\ts2\t' + str(repo) + '\t']
    eq(R.attach_target(rows, repo, 'runner'), ('ar-proj', '%2'), "attach: the runner's own pane")
    eq(R.attach_target(rows, repo, 's1'), ('ar-proj', '%3'), "attach s1: this repo's s1, not another repo's")
    eq(R.attach_target(rows, repo, 's9'), None, 'no such slot')
    eq(R.attach_argv('ar-proj', '%3', inside=False)[-1], ['tmux', 'attach-session', '-t', 'ar-proj'],
       'outside tmux it attaches this terminal')
    eq(R.attach_argv('ar-proj', '%3', inside=True)[-1], ['tmux', 'switch-client', '-t', 'ar-proj'],
       'inside tmux it switches the client')

    for line, want in (('=== 2026-11-19T10:00:00 run: 3 slots in tmux, merging into main', 3),
                       ('=== 2026-11-19T10:00:00 sequential run on main (one session at a time, …)', 0)):
        log = R.C.notes('run.log')
        since = log.stat().st_size if log.exists() else 0
        with open(log, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
        eq(R.wait_started(since, lambda: False, timeout=2), want, f'the launch sees the run come up ({want} slots)')
    eq(R.wait_started(R.C.notes('run.log').stat().st_size, lambda: True, timeout=2), None, 'or that it ended first')

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
            for name, why in (('copilot', 'agent copilot'), ('pi', 'backend pi')):
                with mock.patch.object(R, name, lambda: True):
                    check(not R.remote_on() and R.remote_off_why().startswith(why), f'auto, {why}: off')
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
    f = Path(env[R.PRESENCE_ENV])
    check(f.exists() and f.name == 'quiet-slots', 'a slot on Remote Control names a presence file that exists')
    s = json.loads(flags[flags.index('--settings') + 1])
    eq((s['agentPushNotifEnabled'], s['inputNeededNotifEnabled']), (False, False), 'and its pushes are off')
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


def test_control(repo: Path):
    print('control sessions: the settings file and its brief, the argv, c1 kept, tmux default-command, status')
    R.init(repo)
    data = R.control_settings_data()
    hook = data['hooks']['SessionStart'][0]['hooks'][0]
    check(hook['type'] == 'command' and hook['command'].endswith('control --brief'),
          'a SessionStart hook prints the control brief', hook)
    check('Stop' not in data['hooks'], 'no Stop hook: a control session is never ended on idle')
    check(f'Bash({R.C.command}:*)' in data['permissions']['allow'] and 'Monitor' in data['permissions']['allow'],
          "the runner's commands and Monitor need no permission prompt")
    f = R.control_settings()
    eq(f, repo / '.runner' / 'control-settings.json', 'the file is <notes>/control-settings.json')
    eq(json.loads(f.read_text(encoding='utf-8')), data, 'and holds that')
    brief = R.control_brief()
    for want in ('control session', f'{R.C.command} status', f'{R.C.command} plan add', f'{R.C.command} take',
                 'Never edit code', f'{R.C.command} since', f'{R.C.command} since --follow', 'Open the session',
                 '/run · /since · /follow · /control · /pause · /stop · /slots', 'Never start it unasked',
                 f'{R.C.command} control --new', '"/new"', "Artifact tool's `open` action", '**Waiting for your\n   OK**',
                 '**Running**', '**Landed**', '**Stuck**', "status's `lately`", 'More: /since · /run -n 20',
                 f'{R.C.command} status -n 20'):
        check(want in brief, f'the brief says {want!r}')
    check(brief.index('**Running**') < brief.index('**Landed**') < brief.index('**Stuck**'),
          'the groups in order: Waiting for your OK, Running, Landed, Stuck')
    check('status · since · follow' not in brief, 'the hints line is slash commands, not bare words')
    check('tail -n 0 -F' not in brief, 'no run-log watch at the start: following is asked for')
    r = run(repo, 'control', '--brief')
    eq((r.returncode, r.stdout), (0, brief), '`control --brief` (the hook) prints it')

    argv = R.control_argv(2, 'sid-2', resume=False)
    eq(argv[0], R.plat.exe(R.C.run['agent']), 'the agent')
    check('summary' in argv[1] and 'status' in argv[1] and 'since' in argv[1] and 'watch' not in argv[1],
          'its first message asks for the opening summary, and starts no watch')
    i = argv.index('--session-id')
    eq(argv[i:i + 4], ['--session-id', 'sid-2', '--model', R.C.run['model']], 'a new session on [run] model')
    eq(argv[argv.index('--tools') + 1], 'Bash,Read,Edit,Write,Artifact,Monitor', 'lean: the slot tools and Monitor')
    eq(argv[argv.index('--settings') + 1], str(f), 'the settings file')
    check('--permission-mode' not in argv and '--remote-control' not in argv, 'no bypass; local without [run] remote')
    with mock.patch.dict(R.C.run, {'remote': True}):
        argv = R.control_argv(3, 'sid-3', resume=True)
    eq(argv[-2:], ['--remote-control', f'{R.ROOT.name} · control 3'], 'with [run] remote it is on Remote Control')
    check('--resume' in argv, 'resume continues the session')
    with mock.patch.dict(R.C.run, {'remote': True}):
        sv = R.control_server_argv()
    eq(sv[1:], ['remote-control', '--spawn', 'same-dir', '--name', f'{R.ROOT.name} · control', '--settings', str(f)],
       'the control server: claude remote-control in the main checkout, with the control settings')

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

    dc = R.control_default_command(repo)
    check(dc.startswith(f'cd {repo} && ') and ' control ' in dc + ' ' and dc.endswith('|| exec "${SHELL:-/bin/sh}"'),
          'tmux default-command: a new pane is a control session in the main checkout', dc)
    a = R.control_pane_argv('%5', False, 'mine', repo, 'ar control 1', ['PATH=/bin'])
    eq(a[:8], ['tmux', 'split-window', '-v', '-d', '-l', '40%', '-t', '%5'], 'a foreground run: split under its pane')
    eq(a[-4:], ['-P', '-F', '#{pane_id}', 'ar control 1'], 'running control 1')
    a = R.control_pane_argv('%5', True, 'ar-proj', repo, 'x', [])
    eq(a[1:7], ['new-window', '-d', '-t', '=ar-proj:', '-n', 'control-proj'], 'the background run: a window of its own')
    calls = []
    with mock.patch.object(R, 'MUX', R.TmuxMux()), mock.patch.dict(os.environ, {'TMUX_PANE': '%1'}), \
            mock.patch.object(R, 'tmux', lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, 'ar-proj\n', '')), \
            mock.patch.object(R.sp, 'run', lambda *a, **k: calls.append(a[0]) or subprocess.CompletedProcess(a, 0, '%9\n', '')):
        R.start_control()
        check(any(c[:4] == ('set-option', '-t', '=ar-proj', 'default-command') for c in calls),
              "the background session's default-command is set", calls)
        check(any(c[:2] == ['tmux', 'new-window'] for c in calls if isinstance(c, list)), 'c1 opened in its window')
        check(('set-option', '-p', '-t', '%9', R.TAG, 'c1') in calls, 'tagged c1 (attach c1)')
        calls.clear()
        with mock.patch.dict(R.C.run, {'control': False}):
            R.start_control()
        eq(calls, [], '[run] control = false: none')

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
    line = '  CONCEPT  Settings page layout [K7]: pick an option on the page  https://claude.ai/code/artifact/aaa'
    text = R.status_text(False, {}, [], {}, 0.0, waiting=w)
    eq(text.splitlines(), ['Waiting for your OK:', line, 'no run is up'],
       'status: waiting for your OK first, label first, with the link')
    eq(R.status_text(False, {}, [], {}, 0.0), 'no run is up', 'and nothing extra when none waits')
    now = R.dt.datetime(2026, 11, 19, 15, 0, 0)
    text, _ = R.since_text([], now - R.dt.timedelta(hours=2), {}, now, waiting=w)
    eq(text.splitlines(), ['Waiting for your OK:', line, 'nothing new since 13:00'],
       'since: the same, however old the concept is')
    with tempfile.TemporaryDirectory() as tmp:
        todo = Path(tmp) / 'TODO.md'
        P.ensure(todo)
        P.add('K', 'settings page layout | files: a.py', todo=todo)
        bid = P.concept_done('K1', 'https://x.invalid/p', todo=todo)
        with mock.patch.object(type(R.C), 'todo', property(lambda self: todo)):
            eq(R.waiting_ok(), [('CONCEPT', bid, 'K1', 'pick an option on the page', 'https://x.invalid/p',
                                 'settings page layout', False)],
               'waiting_ok reads the build tasks waiting on a concept page off TODO.md')
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
        P.block('F4', 'needs F9 first', todo=todo)
        check('(after' not in todo.read_text(encoding='utf-8').split('**F2**')[1].split('\n')[0],
              'a block on a person waits on no task, even one its words name')
        a = sorted(P.asks(todo), key=lambda x: x[1])
        eq([(x[0], x[1]) for x in a], [('CONFIRM', 'F1'), ('DECIDE', 'F2'), ('BLOCKED', 'F3')],
           'asks lists the person-blocked tasks with their labels, not a plain block')
        eq((a[0][3], a[0][4]), ('watch a phone for a push when a task lands, see', 'https://x.invalid/howto'),
           'what to do, and its link apart')
        with mock.patch.object(type(R.C), 'todo', property(lambda self: todo)):
            w = R.waiting_ok()
        text = R.status_text(False, {}, [], {}, 0.0, waiting=w)
        has(text, r'^Waiting for your OK:\n  BLOCKED  deploy key \[F3\]: needs a deploy key on the server\n'
                  r'  DECIDE  pick a database \[F2\]: Postgres or SQLite\? F4 does not care\n'
                  r'  CONFIRM  push notices \[F1\]: watch a phone for a push when a task lands, see  '
                  r'https://x\.invalid/howto\nno run is up$',
            'status: label, title [id]: what to do, link, in queue order')
        now = R.dt.datetime(2026, 11, 19, 15, 0, 0)
        has(R.since_text([], now, {}, now, waiting=w)[0],
            r'^Waiting for your OK:\n  BLOCKED  deploy key \[F3\]: .*\n  DECIDE .*\n  CONFIRM  push notices \[F1\]',
            'since: the same')
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
    R.since_mark_file().unlink(missing_ok=True)
    try:
        today = R.dt.date.today().isoformat()  # the command reads the clock: today's stamps read as times
        notes.write_text('\n'.join(l.replace('2026-11-19', today) for l in log) + '\n', encoding='utf-8')
        r1 = run(repo, 'since', f'{today}T12:00')
        has(r1.stdout, r'landed: .*\[F5\]', 'since WHEN prints what happened')
        eq(R.since_mark_file().read_text(encoding='utf-8').strip(), f'{today}T14:20:00', 'and moves the mark')
        r2 = run(repo, 'since')
        eq((r2.returncode, r2.stdout.strip()), (0, 'nothing new since 14:20 (your last look)'),
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
    finally:
        if keep is None:
            notes.unlink(missing_ok=True)
        else:
            notes.write_text(keep, encoding='utf-8')
        R.since_mark_file().unlink(missing_ok=True)


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
    print('run: the prompt, a custom template, the Stop hook, a usage limit')
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
    with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False) as f:
        f.write("You've hit your limit · resets 3pm (Europe/London)\n")
    got = R.limit_only('no-such-session', Path(f.name), 0)
    check(got is not None and (got.hour, got.minute) == (15, 0),
          'a session that only hit the limit gives the reset time', str(got))
    os.unlink(f.name)
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
            eq(R.remote_flags('slot2', None), ['--remote-control', f'{R.ROOT.name} · s2'],
               'with [run] remote_slots a slot starts on Remote Control, named')
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
        R.end_sessions(procs, running)
        check(p.wait(timeout=10) is not None and not procs and not running, '`s!` ends the session')
        eq(R.queued().get(2), ('T9', 'sid-x', 'stopped with s!'), 'and queues it to resume in its slot')
        (repo / '.runner/T9.resume').unlink()
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
    eq(choice('', True, False, windows=False), 'tmux', 'POSIX with tmux: panes')
    eq(choice('', False, False, windows=False), 'sequential', 'POSIX without tmux: the sequential run')
    eq(choice('', False, True, windows=True), 'wt', 'Windows with Windows Terminal: tabs')
    eq(choice('', True, False, windows=True), 'console', 'Windows without it: a console window per slot')
    eq(choice('none', True, True, windows=False), 'sequential', '--no-tmux is sequential')
    eq(choice('console', False, True, windows=True), 'console', '[run] mux picks console over wt')
    eq(choice('wt', True, True, windows=False), 'sequential', 'a terminal that is not there falls back to sequential')

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

    # the shim a Windows tab runs: the agent's pid in the marker while it runs, AGENT_RUNNER_MARKER set
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
        mux = R.ShimMux('wt')
        pid = R.marker_pid(marker)
        check(pid and plat.alive(pid) and pid != shim.pid, 'the shim publishes the agent\'s own pid')
        eq(mux.panes().get('s7', (None, None))[1], pid, 'the Windows terminals list the slot by its marker')
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
        R.pick = lambda *a, **k: None
        eq(R.sequential('main', 'opus', 90, 0, False), 0, 'an idle sequential run ends after powering off')
        eq(calls, ['off'], 'and powered off once')
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
        os.environ['AGENT_RUNNER_SLOT'] = '9'
        t.write_text('{"type":"user"}\n', encoding='utf-8')
        mark = R.finished_mark()
        mark.touch()
        p = subprocess.Popen(agent_with_child(30))
        time.sleep(0.3)
        t0 = time.time()
        R.stop_waiter(p.pid, str(t), 1, 0)
        took = time.time() - t0
        check(p.wait(5) is not None and took < 3, 'after a successful done a leftover background command does not hold it', took)
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
    os.environ['AGENT_RUNNER_SLOT'] = '9'
    try:
        for done in (False, True):
            if done:
                R.finished_mark().touch()
            sys.stdin = io.StringIO(json.dumps({'transcript_path': str(t), 'background_tasks': [{'id': 'b1'}]}))
            R.stop_hook(90)
        eq(seen, ['1800', '5'], 'idle handed to the waiter: before done, and 5 s once done succeeded')
    finally:
        R.plat.spawn_detached, sys.stdin = spawn, stdin
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
        eq(R.cut_off(said('lim', ask, error("You've hit your limit · resets 3pm", 'rate_limit'))), None,
           'nor is a usage limit (the slot sleeps to the reset instead)')
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


def test_limit_lets_go(repo: Path):
    print('run: a slot asleep until a usage reset lets go of its task, so another slot may take it')
    R.init(repo)
    git(repo, 'checkout', '-q', 'main')

    class Mux:
        name = 'fake'

        def open(self, n, cwd, prompt, sid, model, idle, env, logfile, resume=False):
            with open(logfile, 'a', encoding='utf-8') as f:
                f.write("You've hit your limit · resets 3pm\n")
            R.ask_stop('test')  # the run ends once the slot is asleep
            p = subprocess.Popen([sys.executable, '-c', 'pass'])
            p.wait()
            return p.pid

        def panes(self):
            return {}

        def session_id(self, pid):
            return None

        def where(self, n):
            return f'slot {n}'

    saved = R.TmuxMux, R.MUX, R.plat.mux_choice, R.time.sleep, os.environ.get('TMUX')
    sleep = R.time.sleep
    R.TmuxMux, R.plat.mux_choice, R.time.sleep = Mux, lambda *a, **k: 'tmux', lambda s: sleep(min(s, 0.05))
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
        R.C.run['agent'], R.MASTER_PANE = 'claude', False
    m = re.search(r'slot 1: (\S+) only hit the usage limit', (repo / '.runner/run.log').read_text())
    check(m, 'the session only hit the usage limit')
    eq(git(R.SLOTS_DIR / 's1', 'branch', '--show-current'), '', 'and the sleeping slot let go of its task branch')
    if m:
        git(repo, 'branch', '-D', f'task/{m.group(1)}')


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
            eq(R.auto_upgrade(False), None, 'auto_upgrade off (the default): nothing')
            R.AUTO_UPGRADE[0] = True
            eq(R.auto_upgrade(True), None, 'mid-merge: it waits')
            t = R.auto_upgrade(False)
            check(t is not None, 'idle: the upgrade starts with no key pressed')
            t.join(5)
            eq(ran, [1], 'upgrade() ran once')
            eq(R.auto_upgrade(False), None, 'and not again for the same version')
            has(said[0], rf'{re.escape(newer)} is out.*upgrading by itself', 'logged')
    finally:
        R.log, R.LATEST_SAID[0], R.AUTO_TRIED[0], R.AUTO_UPGRADE[0] = real_log, '', '', False


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
    finally:
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


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        os.environ['CLAUDE_CONFIG_DIR'] = str(tmp)  # Claude.trust writes here, never to the real ~/.claude.json
        repo = make_repo(tmp)
        return report([test_paint, lambda: test_master_branch_option(tmp), lambda: test_relative_remote(tmp), lambda: test_picking(repo), lambda: test_split_parents(repo), lambda: test_blockers_first(repo), lambda: test_done(repo, tmp), lambda: test_merge(repo, tmp),
                       lambda: test_retry(repo), lambda: test_unmerged(repo),
                       lambda: test_conflicts(repo, tmp), lambda: test_fix_ahead(repo, tmp), lambda: test_repair(repo, tmp),
                       lambda: test_prompt_and_hooks(repo),
                       lambda: test_hooks(repo, tmp), lambda: test_run_policies(repo, tmp),
                       lambda: test_gate_and_batches(repo, tmp), lambda: test_blame_and_own_repair(repo, tmp),
                       lambda: test_red_base_and_batch_caps(repo, tmp), lambda: test_merge_order_and_backlog(repo), lambda: test_reserved_ids(repo),
                       lambda: test_platform(repo, tmp), lambda: test_shutdown(repo), lambda: test_merge_into(tmp),
                       lambda: test_leftovers(repo), lambda: test_renumber(repo),
                       lambda: test_stop_waiter(tmp), lambda: test_stop_hook_grace(tmp), lambda: test_land_waits_aloud(repo), lambda: test_merge_ahead(repo), lambda: test_adopted_gate_merge(repo), lambda: test_adopted_gate_results(repo), lambda: test_gate_since(repo), lambda: test_gate_catch_up(repo), lambda: test_owed_merge_goes_first(repo), lambda: test_copies(repo), lambda: test_land_gives_merge_back(repo),
                       lambda: test_edited_elsewhere(repo, tmp),
                       lambda: test_resume(repo, tmp),
                       lambda: test_session_tmp(repo, tmp), lambda: test_end_orphans(repo), lambda: test_memory_watch(repo), lambda: test_tested_ref(repo, tmp),
                       lambda: test_no_pane(repo, tmp), lambda: test_other_repos_panes(repo, tmp),
                       lambda: test_limit_lets_go(repo),
                       lambda: test_shared_push(repo, tmp), lambda: test_note_on_a_ticked_task(repo), lambda: test_adopt_merge(repo), lambda: test_followups(repo), lambda: test_ci_watch(repo), test_update_notice, test_restart_if_upgraded, test_auto_upgrade, lambda: test_flake_repair(tmp), lambda: test_repair_per_failure(repo),
                       lambda: test_stalled(tmp), lambda: test_take(repo), lambda: test_take_text_and_here(repo), lambda: test_background(repo), lambda: test_attach_flag(repo), lambda: test_remote_auto(tmp), lambda: test_control(repo),
                       lambda: test_short_titles_and_since(repo), lambda: test_concepts_waiting(repo),
                       lambda: test_person_waiting(repo)])


if __name__ == '__main__':
    sys.exit(main())
