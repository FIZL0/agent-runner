#!/usr/bin/env python3
"""B829: the remote's plan commits taken in by a `[plan] repo` pull or a plan edit's push leave no two tasks under
one id.

    python3 tests/test_plan_clone_ids.py        (no network; a bare remote in a temp folder)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import config, plan as P, plansync  # noqa: E402

START = '# TODO\n\n### Next\n\n- [ ] **B1** one | files: b1.py\n- [ ] **B2** two | files: b2.py\n'
PUSHED = '- [ ] **B3** the Tailscale links of the run page | files: web.py'
MINE = '- [ ] **B3** a question card hides under the keys | files: page.js'
AFTER = '- [ ] **B4** the sequel of B3 | files: seq.js | after: B3'


def seed(tmp: Path, at: str) -> tuple[Path, Path]:
    """A bare remote whose task list is in folder `at`, and another machine's clone of it."""
    first, bare, other = tmp / 'first', tmp / 'origin.git', tmp / 'other'
    (first / at).mkdir(parents=True)
    git(first, 'init', '-q', '-b', 'main')
    (first / at / 'TODO.md').write_text(START, encoding='utf-8')
    (first / at / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
    (first / 'runner.toml').write_text('[run]\ntest = "true"\n', encoding='utf-8')
    (first / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(first, 'add', '-A')
    git(first, 'commit', '-qm', 'start')
    git(tmp, 'clone', '-q', '--bare', str(first), str(bare))
    git(tmp, 'clone', '-q', str(bare), str(other))
    return bare, other


def clone(tmp: Path) -> tuple[config.Config, Path, Path]:
    """A project with a `[plan] repo`, its bare remote and another machine's clone."""
    bare, other = seed(tmp, '.')
    repo = tmp / 'code'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'runner.toml').write_text(
        f'[plan]\nrepo = "{bare.as_posix()}"\ndir = "{(tmp / "clone").as_posix()}"\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    c = config.Config(repo)
    plansync.ensure_clone(c)
    return c, bare, other


def checkout(tmp: Path) -> tuple[Path, Path, Path]:
    """A project with its plan in the code repo, its bare remote and another machine's clone."""
    bare, other = seed(tmp, 'plan')
    root = tmp / 'main'
    git(tmp, 'clone', '-q', str(bare), str(root))
    return root, bare, other


def add(d: Path, f: str, *lines: str):
    """A plan commit that puts `lines` at the end of the task list, with no id check."""
    p = d / f
    p.write_text(p.read_text(encoding='utf-8') + ''.join(l + '\n' for l in lines), encoding='utf-8')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'plan: add')


def pushed(other: Path, f: str, *lines: str):
    add(other, f, *lines)
    git(other, 'push', '-q', 'origin', 'main')


def ids(text: str) -> list[str]:
    return sorted(t for _, _, t, _, _ in P.iter_tasks(text.splitlines()))


def renumbered(t: str):
    eq(ids(t), ['B1', 'B2', 'B3', 'B4', 'B5'], 'each task has an id of its own')
    has(t, r'\*\*B3\*\* the Tailscale', 'the pushed one keeps its id')
    has(t, r'\*\*B5\*\* a question card', 'the unpushed one gets the next free one')
    has(t, r'\*\*B4\*\* the sequel of B5 \| files: seq.js \| after: B5', 'after: and the words that name it follow')


def test_pull(tmp: Path):
    print('plansync.pull in a [plan] repo clone')
    c, bare, other = clone(tmp / 'pull')
    d = c.plan_dir
    (d / 'tasks').mkdir()
    (d / 'tasks/B3.md').write_text('# the card\n', encoding='utf-8')
    add(d, 'TODO.md', MINE, AFTER)
    pushed(other, 'TODO.md', PUSHED)
    check(plansync.pull(c, force=True), 'the pull merges')
    renumbered(c.todo.read_text(encoding='utf-8'))
    eq(git(d, 'ls-files', 'tasks'), 'tasks/B5.md', 'and its long form')
    eq(git(d, 'status', '--porcelain'), '', 'the clone is clean')
    has(c.notes('run.log').read_text(encoding='utf-8'), r'plan: renumbered B3 -> B5', 'the log says so')
    eq(plansync.publish(c, 'x'), '', 'and it is pushed')
    renumbered(git(bare, 'show', 'main:TODO.md'))


def test_publish(tmp: Path):
    print("publish's pull, when its push is refused")
    c, bare, other = clone(tmp / 'publish')
    pushed(other, 'TODO.md', PUSHED)
    c.todo.write_text(c.todo.read_text(encoding='utf-8') + f'{MINE}\n{AFTER}\n', encoding='utf-8')
    eq(plansync.publish(c, 'add'), '', 'it merges and pushes')
    renumbered(git(bare, 'show', 'main:TODO.md'))


def test_pull_undone(tmp: Path):
    print('a pull that conflicts leaves no renumbering; a task with a branch keeps its id')
    c, _, other = clone(tmp / 'undone')
    d = c.plan_dir
    (other / 'claim').write_text('theirs\n', encoding='utf-8')
    pushed(other, 'TODO.md', PUSHED)
    (d / 'claim').write_text('ours\n', encoding='utf-8')
    add(d, 'TODO.md', MINE)
    head = git(d, 'rev-parse', 'HEAD')
    check(not plansync.pull(c, force=True), 'the conflict is said')
    eq(git(d, 'rev-parse', 'HEAD'), head, 'the clone is as it was')
    eq(git(d, 'status', '--porcelain'), '', 'with nothing half merged')
    eq(P.reserved(d), set(), 'and no id used up')

    c, _, other = clone(tmp / 'begun')
    git(c.root, 'branch', 'task/B3')  # in the code repo, where a session's branch is
    add(c.plan_dir, 'TODO.md', MINE)
    pushed(other, 'TODO.md', PUSHED)
    check(plansync.pull(c, force=True), 'the pull merges')
    eq(ids(c.todo.read_text(encoding='utf-8')), ['B1', 'B2', 'B3', 'B3'], 'not renumbered under its session')
    has(c.notes('run.log').read_text(encoding='utf-8'), r'uses B3 for another task, but it is under way', 'the log says so')


def test_push(tmp: Path):
    print("a plan edit's push when the remote has moved")
    root, bare, other = checkout(tmp / 'push')
    add(root, 'plan/TODO.md', MINE, AFTER)
    pushed(other, 'plan/TODO.md', PUSHED)
    r = run(root, 'plan', 'note', 'B3', 'seen on a phone')  # the local B3, before the remote's is known
    eq(r.returncode, 0, 'the edit is made')
    has(r.stderr, r'plan: renumbered B3 -> B5: refs/remotes/origin/main gave the id', 'and says what was renumbered')
    check('not pushed' not in r.stderr, 'and pushed', r.stderr)
    t = git(bare, 'show', 'main:plan/TODO.md')
    renumbered(t)
    has(t, r'\*\*B5\*\*.*seen on a phone', 'the note is on the local one')
    check('seen on a phone' not in next(l for l in t.splitlines() if '**B3**' in l), 'not on the pushed one', t)
    eq(git(root, 'status', '--porcelain'), '', 'the checkout is clean')


def test_push_again(tmp: Path):
    print('a renumbering merge that was not pushed is not flattened when the remote moves again')
    root, bare, other = checkout(tmp / 'again')
    add(root, 'plan/TODO.md', MINE, AFTER)
    pushed(other, 'plan/TODO.md', PUSHED)
    hook = bare / 'hooks/pre-receive'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\nexit 1\n', encoding='utf-8')
    hook.chmod(0o755)
    r = run(root, 'plan', 'note', 'B1', 'a note')
    has(r.stderr, r'renumbered B3 -> B5', 'it is renumbered and merged')
    has(r.stderr, r'not pushed', 'and the push is refused')
    hook.unlink()
    (other / 'x.py').write_text('x\n', encoding='utf-8')
    git(other, 'add', '-A')
    git(other, 'commit', '-qm', 'more')
    git(other, 'push', '-q', 'origin', 'main')
    run(root, 'plan', 'note', 'B2', 'another')
    renumbered(git(bare, 'show', 'main:plan/TODO.md'))


def test_push_undone(tmp: Path):
    print("a plan edit's push that conflicts leaves no renumbering")
    root, _, other = checkout(tmp / 'pushundone')
    (other / 'x.py').write_text('theirs\n', encoding='utf-8')
    pushed(other, 'plan/TODO.md', PUSHED)
    (root / 'x.py').write_text('ours\n', encoding='utf-8')
    add(root, 'plan/TODO.md', MINE)
    r = run(root, 'plan', 'note', 'B1', 'a note')
    has(r.stderr, r'not pushed: .*do not merge cleanly', 'it says so')
    eq(git(root, 'log', '-1', '--format=%s')[:10], 'plan: note', 'the edit is the last commit')
    eq(git(root, 'status', '--porcelain'), '', 'with nothing half merged')
    has((root / 'plan/TODO.md').read_text(encoding='utf-8'), r'\*\*B3\*\* a question card', 'the id is as it was')


def test_noted(tmp: Path):
    print('a task both sides added, noted on one side, is one task')
    noted = MINE + ' — seen again on a phone'
    base = START.splitlines()
    for o, t in ((MINE, noted), (noted, MINE)):
        got = P.merge3([*base, o], base, [*base, t])
        eq(got, [*base, noted], 'merge3 keeps one, with its note')
    for name, o, t in (('ours', noted, MINE), ('theirs', MINE, noted)):
        c, _, other = clone(tmp / f'noted-{name}')
        add(c.plan_dir, 'TODO.md', o)
        pushed(other, 'TODO.md', t)
        check(plansync.pull(c, force=True), 'the pull merges')
        t = c.todo.read_text(encoding='utf-8')
        eq(ids(t), ['B1', 'B2', 'B3'], f'noted on {name}: one task in the clone')
        has(t, r'seen again on a phone', 'with its note')
    root, bare, other = checkout(tmp / 'noted-push')
    add(root, 'plan/TODO.md', noted)
    pushed(other, 'plan/TODO.md', MINE)
    run(root, 'plan', 'note', 'B1', 'a note')
    t = git(bare, 'show', 'main:plan/TODO.md')
    eq(ids(t), ['B1', 'B2', 'B3'], "one task after a plan edit's push")
    has(t, r'seen again on a phone', 'with its note')


if __name__ == '__main__':
    tmp = Path(tempfile.mkdtemp(prefix='agent-runner-test-plan-clone-ids-'))
    sys.exit(report([lambda f=f: f(tmp) for f in (test_pull, test_publish, test_pull_undone, test_push, test_push_again,
                                                  test_push_undone, test_noted)]))
