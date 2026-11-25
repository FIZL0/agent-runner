#!/usr/bin/env python3
"""F427b: a block that waits on until checks, in the plan, `done` and on the screens.

    python3 tests/test_until_plan.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import RUN, check, eq, git, has, report

from agent_runner import plan as P, runner as R, sched, status, tui, ui_model as U  # noqa: E402

TODO = """# TODO

### Next

- [ ] **T1** first thing | files: a.py
- [ ] **T2** second thing | files: b.py
- [ ] **T3** third thing | files: c.py
- [ ] **V1** Release | after: all

### Parked

### Stretch
"""
TOML = """[run]
test = "true"
remote = false
[run.checks.vm]
cmd = "exit 0"
label = "the test VM"
[run.tools.phone]
check = "exit 0"
label = "iPhone 15"
"""
V = 'version:999.0.0'


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    (repo / 'plan').mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text(TOML, encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def cmd(repo: Path, *args) -> subprocess.CompletedProcess:
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(repo)}
    return subprocess.run([sys.executable, str(RUN), *args], cwd=repo, env=env, capture_output=True, text=True,
                          encoding='utf-8')


def fresh() -> Path:
    R.C.todo.write_text(TODO, encoding='utf-8')
    return R.C.todo


def line(tid: str) -> str:
    return P.section(R.C.todo, tid)[0]


def refused(fn) -> str:
    try:
        fn()
    except SystemExit as e:
        return str(e)
    return ''


def test_block():
    print('block: written as waiting on the checks; unblock frees it')
    todo = fresh()
    P.block('T1', 'needs the new release', todo=todo, until=[V, ' login:codex ', V])
    has(line('T1'), r'- \[~\] .* BLOCKED: \(until version:999\.0\.0, login:codex\) needs the new release$', 'each check once, no stamp')
    eq(P.asks(todo, all=True), [], 'not under Needs you')
    eq(P.reopen(todo), [], 'a merge does not reopen it')
    git(R.C.root, 'commit', '-qam', 'blocked')
    check('T1' not in [t[0] for t in sched.tasks('main')], 'no slot takes it')
    P.unblock('T1', 'go', todo=todo)
    has(line('T1'), r'- \[ \] \*\*T1\*\* first thing \| files: a\.py — go$', 'unblock frees it, the wait gone')

    P.block('T1', 'BLOCKED: waits for T2 and the login', todo=todo, until=['login:codex'])
    has(line('T1'), r'BLOCKED: \(until login:codex\) waits for T2 and the login$',
        'a BLOCKED: label asks nobody, and a task its words name is not waited on')
    P.note('T1', 'a later note', todo=todo)
    eq(P.until_of(P.lines(todo), P._find(P.lines(todo), 'T1')), ['login:codex'], 'a note leaves the wait')


def test_refused():
    print('a bad check is refused before anything is blocked')
    todo = fresh()
    for bad in (['true'], [V, 'check:nope'], ['tool:tablet'], ['version:1'], [''], []):
        has(refused(lambda: P.block('T1', 'x', todo=todo, until=bad)), 'Nothing blocked', f'{bad}')
    has(refused(lambda: P.block('T1', 'x', todo=todo, until=['check:nope'])), 'there is: vm', 'it says which there are')
    has(refused(lambda: P.block('T1', 'x', todo=todo, until=[V], after=['T2'])), '--after do not go together', 'not with --after')
    eq(todo.read_text(encoding='utf-8'), TODO, 'nothing was written')


def test_last_block():
    print('the last block is the one that counts')
    todo = fresh()
    P.block('T1', 'T2 first', todo=todo, after=['T2'])
    P.block('T1', 'now the VM', todo=todo, until=['check:vm'])
    P.drop('T2', 'gone', todo=todo, done=R.C.done)
    eq(P.reopen(todo), [], 'an earlier (after T2) does not reopen it')
    P.block('T1', 'T3 first', todo=todo, after=['T3'])
    eq(P.until_waits(P.lines(todo)), {}, 'a later (after T3) replaces the checks')
    eq(P.reopen(todo), [], 'and waits for T3')
    merged = '- [~] **T9** x BLOCKED: (after T7) a BLOCKED: (until check:vm) b'
    todo.write_text(f'# T\n\n### Next\n\n{merged}\n', encoding='utf-8')
    eq((P.reopen(todo), P._waiters(P.lines(todo))), ([], {}), 'nor one a merge left on the line')


def test_question():
    print('a CONFIRM or DECIDE comes back under Needs you once the checks pass')
    todo = fresh()
    P.block('T1', 'CONFIRM: run it on Windows', todo=todo)
    P.block('T1', 'the VM is down', todo=todo, until=['check:vm'])
    P.block('T2', 'DECIDE: zip or dmg?', todo=todo, until=['check:vm'])
    P.block('T3', 'BLOCKED: release 999, then this reruns', todo=todo)
    P.block('T3', 'the release', todo=todo, until=[V])
    has(line('T1'), r'BLOCKED: \(until check:vm\) CONFIRM: run it on Windows .*— the VM is down$', 'the question is kept')
    eq(P.asks(todo, all=True), [], 'none is under Needs you meanwhile')
    eq([P.until_passed(t, todo) for t in ('T1', 'T2', 'T3', 'V1')], [True, True, True, False], 'passed')
    eq([(a[0], a[1], a[3]) for a in P.asks(todo)], [('CONFIRM', 'T1', 'run it on Windows'), ('DECIDE', 'T2', 'zip or dmg?')],
       'the questions are back')
    has(line('T1'), 'back for you: the test VM passed', 'and say why')
    has(line('T3'), r'- \[ \] .* — reopened: version 999\.0\.0 passed$', 'a BLOCKED reopens for an agent')
    P.block('T1', 'again', todo=todo, until=['check:vm'])
    P.until_passed('T1', todo)
    eq(line('T1').split(' BLOCKED: ')[-1].count('back for you'), 1, 'one such note, not a pile')


def test_release():
    print('a release that waits for all does not wait for a task that waits for its version')
    todo = fresh()
    P.block('T1', 'the release', todo=todo, until=[V])
    P.edit('T2', keyed=' | after: T1', todo=todo)
    ls = P.lines(todo)
    i = P._find(ls, 'V1')
    eq(P.before_all(ls, i), ['T3'], 'only T3 holds it')
    eq(P.not_waiting(P.not_waiting_on(ls, i)), '; not waiting on: T1 (after version 999.0.0), T2 (after T1)', 'and it says so')
    P.unblock('T1', todo=todo)
    ls = P.lines(todo)
    eq(P.before_all(ls, i), ['T1', 'T2', 'T3'], 'reopened, it holds it again')
    P.block('V1', 'the VM', todo=todo, until=['check:vm'])
    row = U.release_rows(P.lines(todo), {})[0]
    eq((row['state'], row['words']), ('blocked', 'waits for the test VM'), 'a release that waits says for what')


def test_words():
    print('Plan, status and the terminal UI say what it waits for')
    todo = fresh()
    P.block('T1', 'the release', todo=todo, until=['version:0.66.0'])
    P.block('T2', 'both', todo=todo, until=['check:vm', 'tool:phone'])
    P.block('T3', 'CONFIRM: look', todo=todo)
    rows = {r['id']: r for r in U.queue_rows(P.lines(todo), {})}
    eq([(rows[t]['state'], rows[t].get('tool_wait')) for t in ('T1', 'T2', 'T3')],
       [('tool', 'waits for version 0.66.0'), ('tool', 'waits for the test VM, iPhone 15'), ('blocked', '')], 'the queue rows')
    check(rows['T1']['blocked'], 'still a blocked task')
    page = next(c for c in vars(tui).values() if hasattr(c, 'queue_tag'))
    eq(page.queue_tag(None, rows['T1']), ('⧗ waits for version 0.66.0', 'dim'), 'the terminal UI')
    has('\n'.join(status.until_lines()), r'T1 waits for version 0\.66\.0\n  T2 waits for the test VM, iPhone 15', 'status')
    git(R.C.root, 'commit', '-qam', 'waits')
    out = cmd(R.C.root, 'status')
    has(out.stdout, r'T1 waits for version 0\.66\.0', 'the status command, no run up')
    has(cmd(R.C.root, 'plan').stdout, r'\[~\] T1  \[waits for version 0\.66\.0\]', 'plan')
    has(cmd(R.C.root, 'plan', 'T1').stdout, r'(?m)^T1 waits for version 0\.66\.0$', 'plan T1')


def test_merge():
    print('the plan merge keeps it')
    base = '### A\n- [ ] **A1** a | files: x\n- [ ] **A2** b\n'.split('\n')
    branch = [l.replace('[ ] **A1**', '[~] **A1**') + (' BLOCKED: (until version:0.66.0, login:codex) why' if 'A1' in l else '')
              for l in base]
    main = [l + (' — a note' if 'A1' in l else '') for l in base][:-2] + ['- [x] **A2** b', '']
    for o, t in ((main, branch), (branch, main)):
        got = P.merge3(o, base, t, 'A1')
        i = next(i for i, l in enumerate(got) if 'A1' in l)
        eq((P.until_of(got, i), 'a note' in got[i]), (['version:0.66.0', 'login:codex'], True), 'the checks and the note')
    free = [l.split(' BLOCKED')[0].replace('[~]', '[ ]') for l in branch]
    eq(P.merge3([l + (' — n' if 'A2' in l else '') for l in branch], branch, free)[1], base[1], 'and an unblock')


def test_commands(repo: Path):
    print('plan block and done take --until')
    todo = fresh()
    git(repo, 'commit', '-qam', 'fresh', '--allow-empty')
    r = cmd(repo, 'plan', 'block', 'T1', '--until', f'{V},check:vm', 'the', 'release')
    has(line('T1'), r'BLOCKED: \(until version:999\.0\.0, check:vm\) the release$', f'before the why {r.stderr}')
    cmd(repo, 'plan', 'block', 'T2', 'the release', '--until', V)
    has(line('T2'), r'BLOCKED: \(until version:999\.0\.0\) the release$', 'or after it')
    before = todo.read_text(encoding='utf-8')
    for words in (['--until', 'uptime', 'why'], ['--until', V], ['--until', V, '--after', 'T1', 'why'],
                  ['--after', 'T1', '--until', V, 'why'], ['why', '--until']):
        r = cmd(repo, 'plan', 'block', 'T3', *words)
        check(r.returncode and 'Nothing blocked' in r.stderr, f'refused: {words}', r.stdout + r.stderr)
    eq(todo.read_text(encoding='utf-8'), before, 'and nothing changed')
    r = cmd(repo, 'plan', 'unblock', 'T1')
    has(line('T1'), r'- \[ \] \*\*T1\*\*', 'plan unblock frees it')

    git(repo, 'checkout', '-qb', 'task/T3')
    head = git(repo, 'rev-parse', 'HEAD')
    for words in (['--blocked', 'why', '--until', 'uptime'], ['--until', V], ['--blocked', 'why', '--until', V, '--after', 'T1']):
        r = cmd(repo, 'done', 'T3', 'T3: part', *words)
        check(r.returncode == 2 and 'gate passed' not in r.stdout, f'done refuses before the gate: {words}', r.stdout + r.stderr)
    eq((git(repo, 'rev-parse', 'HEAD'), todo.read_text(encoding='utf-8') == before), (head, False), 'nothing committed')
    check('[ ] **T3**' in line('T3'), 'nothing blocked')
    r = cmd(repo, 'done', 'T3', 'T3: part', '--blocked', 'the release', '--until', f'{V}, tool:phone')
    eq(r.returncode, 0, f'done blocks it {r.stderr}')
    has(git(repo, 'show', 'HEAD:plan/TODO.md'), r'- \[~\] \*\*T3\*\* .*BLOCKED: \(until version:999\.0\.0, tool:phone\) the release',
        'and commits it')


def test_external(tmp: Path):
    print('a plan in its own repository keeps it through the sync')
    remote, plan, repo = tmp / 'plan.git', tmp / 'plan', tmp / 'code'
    git(tmp, 'init', '-q', '--bare', '-b', 'main', str(remote))
    for d, files in ((plan, {'TODO.md': TODO, 'DONE.md': '# DONE\n'}),
                     (repo, {'runner.toml': TOML + f'[plan]\nrepo = "{remote.as_posix()}"\ndir = "{plan.as_posix()}"\n', '.gitignore': '.runner/\n'})):
        d.mkdir()
        git(d, 'init', '-q', '-b', 'main')
        for n, text in files.items():
            (d / n).write_text(text, encoding='utf-8')
        git(d, 'add', '-A')
        git(d, 'commit', '-qm', 'start')
    git(plan, 'remote', 'add', 'origin', str(remote))
    git(plan, 'push', '-qu', 'origin', 'main')
    other = tmp / 'other'
    git(tmp, 'clone', '-q', str(remote), str(other))
    f = other / 'TODO.md'
    f.write_text(f.read_text(encoding='utf-8').replace('first thing | files: a.py', 'first thing | files: a.py — theirs'), encoding='utf-8')
    git(other, 'commit', '-qam', 'theirs')
    git(other, 'push', '-q')
    r = cmd(repo, 'plan', 'block', 'T1', '--until', V, 'the release')
    git(other, 'pull', '-q')
    has(f.read_text(encoding='utf-8'), r'\*\*T1\*\* .*— theirs BLOCKED: \(until version:999\.0\.0\) the release', f'both edits {r.stderr}')


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    os.environ['AGENT_RUNNER_DEVICES'] = str(tmp / 'devices')
    repo = make_repo(tmp)
    os.environ['AGENT_RUNNER_REPO'] = str(repo)
    R.init(repo)
    return report([test_block, test_refused, test_last_block, test_question, test_release, test_words, test_merge,
                   lambda: test_commands(repo), lambda: test_external(tmp)])


if __name__ == '__main__':
    sys.exit(main())
