#!/usr/bin/env python3
"""The runner, end to end in a throwaway repo with a bare repo as its remote — no tmux, no real agent.

    python3 tests/test_runner.py        (no network; a few seconds, mostly git)

What it proves is the part a night depends on and nobody watches: which task a free slot takes, that
`done` gates, ticks, commits and pushes only the task branch, and that a finished branch is merged in the
merge worktree, joined or handed to a fix session when it conflicts, tested, landed, pushed, its remote
copy dropped, and the blocks it freed reopened — or parked as wip/<ID> when it cannot land.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _check import RUN, check, eq, git, has, report, run

from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402

TODO = """# TODO

### Next (in this order)

- [ ] **T1** the parser → a.py
- [ ] **T2** the printer → b.py

### Later

- [ ] **T3** speed up the parser → a.py
- [ ] **T6** builds on T1's parser → c.py
- [ ] **T5** the logger → d.py · CHANGELOG.md
- [ ] **T4** the report (after T1, T5) → e.py
- [ ] **L3a** half of it → f.py
- [ ] **L3b** the other half → g.py

### Stretch

- [ ] **S1** a web page → web/index.html
"""

FAKE_AGENT = r'''#!/usr/bin/env python3
# A stand-in for `claude -p`: FAKE_FIX=theirs resolves a merge with the branch's side, =abort gives up.
import os, subprocess
g = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True)
if os.environ.get('FAKE_FIX') == 'theirs':
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
        'joinable = ["plan/TODO.md", "plan/DONE.md", "CHANGELOG.md"]\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(repo, 'remote', 'add', 'origin', str(tmp / 'origin.git'))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    return repo


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
    check('T4' not in ids, '(after T1, T5) holds the task while either is open — every id, not just the first')
    first = R.pick({}, set(), 'd', 'main')
    eq(first[0], 'T1', 'an empty run starts at the top')
    second = R.pick({1: first}, set(), 'd', 'main')
    eq(second[0], 'T5', 'with T1 running: not T2 (ordered section), T3 (same file), T6 (names T1)')
    third = R.pick({1: first, 2: second}, set(), 'd', 'main')
    eq(third[0], 'L3a', 'CHANGELOG.md is a shared file, so it is not an overlap')
    check((R.pick({1: first, 2: second, 3: third}, set(), 'd', 'main') or ('',))[0] != 'L3b',
          'a sibling of a running task waits')
    eq(R.pick({1: first}, set(), 'p', 'main')[0], 'T2', 'mode p just follows the plan order')
    eq(R.pick({}, set(ids), 'd', 'main'), None, 'nothing left once everything has been tried')
    for f in ('plan/TODO.md', 'plan/DONE.md', 'CHANGELOG.md'):
        check(R.joinable(f), f'{f} is in [run] joinable, so a conflict there is joined')
    for f in ('README.md', 'a.py', 'plan/T1.md'):
        check(not R.joinable(f), f'{f} is not, so it needs reading')
    r = run(repo, 'run', '--dry-run', '3')
    has(r.stdout, r'slot 1: T1.*\nslot 2: T5.*\nslot 3: L3a', '`run run --dry-run 3` prints the three picks')
    has(r.stdout, r'waiting on .*T4', 'and what waits')


def test_split_parents(repo: Path):
    print('run: split parents wait for their subtasks, blocked ones too; the words alone hold nothing')
    R.init(repo)
    d = R.worktree('split', 'main')
    git(d, 'checkout', '-q', '-B', 'splitcheck', 'main')
    (d / 'plan/TODO.md').write_text("""# TODO

### Later

- [ ] **P1** the importer (split into P1a, X2) → a.py
- [~] **P1a** read the header → a.py BLOCKED: needs a sample file
- [ ] **X2** read the body → b.py
- [ ] **B9** the settings page, split into two tabs → c.py
- [ ] **Q1** the exporter (split into Q1a) → d.py
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


def task_branch(repo: Path, n: int, tid: str) -> Path:
    """A slot worktree on task/<tid>, the way `start` leaves it for a session."""
    d = R.worktree(n, 'main')
    git(d, 'checkout', '-q', '-B', f'task/{tid}', 'main')
    return d


def test_done(repo: Path, tmp: Path):
    print('done: gate, tick, commit, push the task branch — never the shared one')
    d = task_branch(repo, 1, 'T5')
    check((d / 'runner.toml').exists(), 'the worktree has the runner.toml')
    (d / 'd.py').write_text('def log(x):\n    print(x)\n', encoding='utf-8')
    (d / 'BROKEN').write_text('', encoding='utf-8')
    r = run(d, 'done', 'T5', 'T5: the logger')
    check(r.returncode == 1 and 'gate failed' in r.stderr, 'a failing gate refuses', r.stdout + r.stderr)
    check('- [ ] **T5**' in (d / 'plan/TODO.md').read_text(), 'and ticks nothing')
    eq(git(d, 'rev-list', '--count', 'main..HEAD'), '0', 'and commits nothing')
    (d / 'BROKEN').unlink()
    with open(d / 'CHANGELOG.md', 'a') as f:
        f.write('- T5: the logger\n')
    r = run(d, 'done', 'T5', 'T5: the logger')
    check(r.returncode == 0, 'a passing gate goes through', r.stdout + r.stderr)
    has(r.stdout, r'pushed task/T5 → origin', 'and pushes the task branch')
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
    P._cache.clear()
    P.block('T4', 'needs T1 and T5 landed', todo=repo / 'plan/TODO.md')
    git(repo, 'commit', '-qam', 'T4: blocked')
    has((repo / 'plan/TODO.md').read_text(), r'\*\*T4\*\*.*BLOCKED: \(after T5\)',
        'block records only the id still open: T1 was ticked first')


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


def test_retry(repo: Path):
    print('run: a tried task a human blocks and then unblocks is back in the pool')
    R.init(repo)
    tried, closed = {'T4'}, set()
    R.retry_reopened(tried, closed, 'main')
    check('T4' in tried, 'a tried task still open stays tried (it failed: a human looks next)')
    for step in (lambda: P.block('T4', 'needs a decision', todo=repo / 'plan/TODO.md'),
                 lambda: P.unblock('T4', 'decided', todo=repo / 'plan/TODO.md')):
        P._cache.clear()
        step()
        git(repo, 'commit', '-qam', 'Plan: T4')
        R.retry_reopened(tried, closed, 'main')
        if 'T4' in closed:
            check('T4' in tried, 'blocked, it is seen closed and stays tried')
    check('T4' not in tried and not closed, 'opened again, it leaves tried')
    has((repo / '.runner/run.log').read_text(), r'T4: open again since it was tried', 'and the log says so')


def test_conflicts(repo: Path, tmp: Path):
    print('run: a conflict a join cannot do goes to a fix session; one it gives up on is parked')
    agent = tmp / 'fake-agent'
    agent.write_text(FAKE_AGENT, encoding='utf-8')
    agent.chmod(0o755)
    R.C.run['agent'] = str(agent)
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
    led = (repo / '.runner/ledger.md').read_text()
    has(led, r'T3: conflicts in a\.py resolved by a fix session', 'T3: the fix session resolved it')
    eq((repo / 'a.py').read_text(), '# T3 version\n', 'and its resolution landed on main')
    has(led, r'T6: LEFT FOR A HUMAN — the fix session aborted', 'T6: the fix session gave up, and the ledger says so')
    eq((repo / 'c.py').read_text(), '# main version of c.py\n', 'main is as it was')
    check(git(repo, 'branch', '--list', 'wip/T6') != '' and git(repo, 'branch', '--list', 'task/T6') == '',
          'T6 is parked as wip/T6, so the task can start again')
    check('wip/T6' in remote_branches(tmp), 'and wip/T6 is on the remote')
    check('T6' in [t[0] for t in R.tasks('main')], 'T6 is still open and offered')
    p = R.prompt_for('T6', 1, 2, repo, 'main')
    has(p, r'An earlier attempt .* on wip/T6', 'its next prompt points at the earlier attempt')
    has(p, r'## Task T6', 'and carries the brief')
    os.environ.pop('FAKE_FIX', None)
    R.C.run['agent'] = 'claude'


def test_prompt_and_hooks(repo: Path):
    print('run: the prompt, a custom template, the Stop hook, a usage limit')
    (repo / 'prompt.txt').write_text('Do {tid} with {runner}; keep {unknown}.\n{brief}', encoding='utf-8')
    R.C.run['prompt'] = 'prompt.txt'
    p = R.prompt_for('T2', 1, 1, repo, 'main')
    has(p, rf'^Do T2 with {RUN}; keep {{unknown}}\.', 'a custom template fills what it knows, leaves the rest')
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
    eq(R.stopped_by(), './run stop', 'and the STOP file says who asked')
    R.KEYS.extend(['s'])
    R.take_keys()
    check(not R.stopping(), '`s` in the runner\'s pane takes a stop back')
    R.KEYS.extend(['', 'x', 's'])
    R.take_keys()
    check(R.stopping() and R.stopped_by() == 's', 'and `s` again asks for one, through the same STOP file')
    check(not R.KEYS, 'every line typed is read')
    (repo / '.runner/STOP').unlink()


def test_hooks(repo: Path, tmp: Path):
    print('hooks a wrapping project uses: its own config file, a pre-commit check, joiners, suspect, brief')
    from agent_runner import config
    kit = tmp / 'kit.toml'
    kit.write_text('[git]\nkit_owns_this = true\n\n[agent-runner.run]\ntest = "python3 check.py"\n'
                   'precommit = "test ! -e SECRET"\ncommand = "./kit"\n\n[agent-runner.git]\npush = false\n',
                   encoding='utf-8')
    env = {**os.environ, 'AGENT_RUNNER_CONFIG': str(kit)}
    os.environ['AGENT_RUNNER_CONFIG'] = str(kit)
    try:
        c = config.Config(repo)
        eq(c.file, kit.resolve(), 'AGENT_RUNNER_CONFIG wins over runner.toml')
        check(c.run['precommit'] == 'test ! -e SECRET' and c.push_remote is None,
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
    (d / 'SECRET').write_text('', encoding='utf-8')
    r = run(d, 'done', 'T2', 'T2: the printer', env=env)
    check(r.returncode == 1 and 'pre-commit check failed' in r.stderr, '[run] precommit refuses', r.stdout + r.stderr)
    eq(git(d, 'rev-list', '--count', 'main..HEAD'), '0', 'and commits nothing')
    r = run(d, 'done', 'T2', 'T2: the printer (SECRET is a fixture)', '--skip-check', env=env)
    check(r.returncode == 0 and 'skipped (--skip-check)' in r.stdout, '--skip-check commits anyway', r.stdout + r.stderr)
    check('pushed' not in r.stdout and 'task/T2' not in remote_branches(tmp), "and [agent-runner.git] push = false holds")
    git(d, 'checkout', '-q', '--detach')

    R.init(repo)
    R.C.run['join'] = {'*.addr': 'grep -v CLASH {union} > {out}', 'refuse.addr': 'echo two addresses; exit 3'}
    try:
        check(R.joinable('x/y.addr') and not R.joinable('x/y.txt'), 'a [run.join] glob makes a file joinable')
        sides = []
        for name, text in (('ours', 'a 1\n'), ('base', ''), ('theirs', 'b 2\n')):
            (tmp / name).write_text(text, encoding='utf-8')
            sides.append(str(tmp / name))
        eq(R.custom_join('lists/one.addr', sides, 'a 1\nCLASH\nb 2\n', 'T9', repo), 'a 1\nb 2\n',
           'the joiner rewrites the union through {union} and {out}')
        R.C.run['join'] = {'refuse.addr': 'echo two addresses; exit 3'}
        check(R.custom_join('refuse.addr', sides, 'x\n', 'T9', repo) is None, 'and a non-zero exit refuses the join')
        has((repo / '.runner/run.log').read_text(), r'refused the join \(exit 3\): two addresses', 'saying why')
    finally:
        R.C.run['join'] = {}

    R.C.run['suspect'] = r'BLOCKED:.*\bemulator\b'
    try:
        before = git(repo, 'rev-parse', 'HEAD')
        P._cache.clear()
        P.block('T6', 'needs a human at the emulator', todo=repo / 'plan/TODO.md')
        git(repo, 'commit', '-qam', 'T6: blocked')
        has(R.suspect(before, git(repo, 'rev-parse', 'HEAD')), r'T6.*emulator', '[run] suspect flags a block a merge adds')
        eq(R.suspect(before, before), '', 'and nothing when none was added')
    finally:
        R.C.run['suspect'] = ''

    R.C.raw['plan']['brief_extra'] = 'echo "## From the project"; echo "names for {id}"'
    try:
        P._cache.clear()
        b = '\n'.join(P.brief('T6', root=repo))
        has(b, r'^## From the project\nnames for T6$', '[plan] brief_extra ends the brief')
        has(b, r'## Files on the line, and their last commits\n- `c.py`', 'after the files and their git log')
    finally:
        R.C.raw['plan']['brief_extra'] = ''
    has(R.agent_cmd('p', 'sid', 'opus', 90, 'slot1'), r'run run --stop-hook', 'the Stop hook calls this runner back')

    # a restart adopts running sessions: their id is read off the agent's command line, even under a shell
    sh = subprocess.Popen(['sh', '-c', 'python3 -c "import time; time.sleep(30)" --session-id abc-123; true'], start_new_session=True)
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


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        repo = make_repo(tmp)
        return report([lambda: test_picking(repo), lambda: test_split_parents(repo), lambda: test_done(repo, tmp), lambda: test_merge(repo, tmp),
                       lambda: test_retry(repo),
                       lambda: test_conflicts(repo, tmp), lambda: test_prompt_and_hooks(repo),
                       lambda: test_hooks(repo, tmp)])


if __name__ == '__main__':
    sys.exit(main())
