#!/usr/bin/env python3
"""B822a: a merge that takes the remote in renumbers the ids this side added that the remote uses for another task.

    python3 tests/test_upstream_ids.py        (no network; a bare remote in a temp folder)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import config as CF, gitops, merge as M, plan as P, runner as R  # noqa: E402

CF.FIXED['merge_ahead'] = False  # no merge built beside a gate here

TODO = 'plan/TODO.md'
LINE = {'own': '- [ ] **B1** one | files: b1.py', 'two': '- [ ] **B2** two | files: b2.py'}
PUSHED = '- [ ] **B3** the Tailscale links of the run page | files: web.py'
MINE = '- [ ] **B3** a question card hides under the keys | files: page.js'
AFTER = '- [ ] **B4** the sequel of B3 | files: seq.js | after: B3'


def make(tmp: Path) -> tuple[Path, Path, Path]:
    """The run's repository, its bare remote and another machine's clone of it."""
    repo, bare, other = tmp / f'proj-{tmp.name}', tmp / 'origin.git', tmp / 'other'  # its name is its run folder's
    repo.mkdir(parents=True)
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / TODO).write_text('# TODO\n\n### Next\n\n' + '\n'.join(LINE.values()) + '\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    git(tmp, 'init', '-q', '--bare', '-b', 'main', str(bare))
    git(repo, 'remote', 'add', 'origin', str(bare))
    git(repo, 'push', '-q', '-u', 'origin', 'main')
    git(tmp, 'clone', '-q', str(bare), str(other))
    R.init(repo)
    return repo, bare, other


def add(d: Path, *lines: str, msg: str = 'plan: add'):
    """A plan commit that puts `lines` at the end of the task list in `d`, with no id check (another machine's)."""
    f = d / TODO
    f.write_text(f.read_text(encoding='utf-8') + ''.join(l + '\n' for l in lines), encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', msg)


def task(repo: Path, tid: str = 'B1', *lines: str):
    git(repo, 'checkout', '-q', '-b', f'task/{tid}')
    (repo / f'{tid.lower()}.py').write_text(f'# {tid}\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', f'{tid}: work')
    if lines:
        add(repo, *lines, msg=f'{tid}: follow-ups')
    git(repo, 'checkout', '-q', 'main')


def pushed(other: Path, *lines: str):
    add(other, *lines)
    git(other, 'push', '-q', 'origin', 'main')


def build(repo: Path) -> str:
    """The task list in the merge of task/B1 as batch_build makes it."""
    d = R.worktree('merge', 'main')
    t = M.BatchTurn('B1', 'main', d, True, set(), False, False)
    eq(M.batch_build(t), None, 'the merge builds')
    check(not M.git('merge-base', '--is-ancestor', 'origin/main', t.merged, cwd=d).returncode, 'with the remote in it')
    return git(d, 'show', f'{t.merged}:{TODO}')


def ids(text: str) -> list[str]:
    return sorted(t for _, _, t, _, _ in P.iter_tasks(text.splitlines()))


def run_log(repo: Path) -> str:
    return (repo / '.runner/run.log').read_text(encoding='utf-8')


def test_task_branch(tmp: Path):
    print('a follow-up on the task branch clashes with a pushed task')
    repo, _, other = make(tmp / 'branch')
    task(repo, 'B1', MINE, AFTER)
    pushed(other, PUSHED)
    t = build(repo)
    eq(ids(t), ['B1', 'B2', 'B3', 'B4', 'B5'], 'each task has an id of its own')
    has(t, r'\*\*B3\*\* the Tailscale', 'the pushed one keeps its id')
    has(t, r'\*\*B5\*\* a question card', 'the follow-up gets the next free one')
    has(t, r'\*\*B4\*\* the sequel of B5 \| files: seq.js \| after: B5', 'after: and the words that name it follow')
    has(run_log(repo), r'B1: renumbered B3 -> B5', 'the log says so')


def test_plan_commit(tmp: Path):
    print('an unpushed plan commit on the local main clashes with a pushed task')
    repo, _, other = make(tmp / 'plan')
    task(repo)
    (repo / 'plan/tasks').mkdir()
    (repo / 'plan/tasks/B3.md').write_text('# the card\n', encoding='utf-8')
    add(repo, MINE, AFTER)
    pushed(other, PUSHED)
    t = build(repo)
    eq(ids(t), ['B1', 'B2', 'B3', 'B4', 'B5'], 'each task has an id of its own')
    has(t, r'\*\*B3\*\* the Tailscale', 'the pushed one keeps its id')
    has(t, r'\*\*B5\*\* a question card', 'the local one is renumbered')
    has(t, r'\| after: B5', 'after: follows')
    d = R.SLOTS_DIR / 'merge'
    eq(git(d, 'ls-tree', '--name-only', 'HEAD', 'plan/tasks/'), 'plan/tasks/B5.md', 'and its long form')
    check(not git(d, 'status', '--porcelain'), 'the merge worktree is clean')


def test_same(tmp: Path):
    print('the same task on both sides is one task')
    repo, _, other = make(tmp / 'same')
    task(repo, 'B1', MINE)
    pushed(other, MINE)
    eq(ids(build(repo)), ['B1', 'B2', 'B3'], 'the same line on both sides is not doubled')
    repo, _, other = make(tmp / 'noted')
    task(repo, 'B1', MINE)
    pushed(other, MINE + ' — seen again on a phone')
    t = build(repo)
    eq(ids(t), ['B1', 'B2', 'B3'], 'nor one the remote noted since')
    has(t, r'seen again on a phone', 'and its note is kept')


def test_begun(tmp: Path):
    print('a clashing task with a branch of its own keeps its id')
    repo, _, other = make(tmp / 'begun')
    task(repo)
    add(repo, MINE)
    git(repo, 'branch', 'task/B3')
    pushed(other, PUSHED)
    eq(ids(build(repo)), ['B1', 'B2', 'B3', 'B3'], 'it is not renumbered under its session')
    has(run_log(repo), r'B1: .*origin/main uses B3 for another task, but it has a branch', 'and the log says so')


def test_push(tmp: Path):
    print("gitops.push's fallback renumbers too, and leaves nothing when its merge conflicts")
    repo, bare, other = make(tmp / 'push')
    task(repo)
    git(repo, 'checkout', '-q', 'task/B1')
    git(repo, 'push', '-q', 'origin', 'task/B1')
    git(other, 'fetch', '-q')
    git(other, 'checkout', '-q', 'task/B1')
    add(other, PUSHED)
    git(other, 'push', '-q', 'origin', 'task/B1')
    add(repo, MINE, AFTER)
    has(gitops.push(repo, 'task/B1'), 'after merging origin/task/B1', 'pushed after a merge')
    t = git(bare, 'show', f'task/B1:{TODO}')
    eq(ids(t), ['B1', 'B2', 'B3', 'B4', 'B5'], 'each task has an id of its own')
    has(t, r'\*\*B3\*\* the Tailscale', 'the pushed one keeps its id')
    has(t, r'\*\*B5\*\* a question card', 'the local one is renumbered')
    has(t, r'\| after: B5', 'after: follows')
    eq(git(repo, 'status', '--porcelain'), '', 'the checkout is clean')

    git(other, 'pull', '-q')
    (other / 'b1.py').write_text('# theirs\n', encoding='utf-8')
    add(other, '- [ ] **B6** another pushed one | files: q.py')
    git(other, 'push', '-q', 'origin', 'task/B1')
    (repo / 'b1.py').write_text('# ours\n', encoding='utf-8')
    add(repo, '- [ ] **B6** a local one that clashes | files: r.py')
    head = git(repo, 'rev-parse', 'HEAD')
    has(gitops.push(repo, 'task/B1'), 'conflicts', 'a conflict is said')
    eq(git(repo, 'rev-parse', 'HEAD'), head, 'and the branch is as it was')
    eq(git(repo, 'status', '--porcelain'), '', 'with nothing left half merged')


if __name__ == '__main__':
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-test-upstream-ids-'))
    sys.exit(report([lambda f=f: f(tmp) for f in (test_task_branch, test_plan_commit, test_same, test_begun,
                                                  test_push)]))
