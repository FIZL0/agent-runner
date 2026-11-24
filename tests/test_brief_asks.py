#!/usr/bin/env python3
"""F156: what an agent asks of a person is one short sentence, and the steps go in <notes>/asks/ID.json.

    python3 tests/test_brief_asks.py        (no network; a few seconds, mostly git)
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import asks as A  # noqa: E402
from agent_runner import plan as P  # noqa: E402
from agent_runner import runner as R  # noqa: E402
from agent_runner.config import cfg  # noqa: E402


def make(t: Path, n: int = 4):
    root = t / 'proj'
    root.mkdir()
    git(root, 'init', '-q')
    (root / 'runner.toml').write_text('[run]\nremote = false\n[git]\npush = false\n', encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    for i in range(1, n + 1):
        kind = 'K' if i == n else 'F'
        check(run(root, 'plan', 'add', kind, f'job {i} of {"abcdefgh"[i]} | files: {i}.py', env=env).returncode == 0, f'added {kind}')
    R.init(root)
    return root, env


def put(root: Path, tid: str) -> Path:
    """Task `tid`'s ask file, with a picture."""
    f = root / '.runner' / 'asks' / f'{tid}.json'
    (f.parent / tid).mkdir(parents=True, exist_ok=True)
    (f.parent / tid / '1.png').write_bytes(b'x')
    f.write_text(json.dumps({'steps': ['Press Save']}), encoding='utf-8')
    return f


def there(f: Path) -> tuple[bool, bool]:
    return f.exists(), f.with_suffix('').exists()


def test_brief(root: Path) -> None:
    print('the brief says it in each place')
    for tid in ('F1', 'K1'):
        p = R.prompt_for(tid, 1, 1, root, 'main')
        has(p, r'then one short sentence, at most about 100 characters, and the link', f'{tid}: the CONFIRM/DECIDE/BLOCKED rule')
        has(p, r'what you recommend, one short sentence>"` \(the rest in the ask file\)', f'{tid}: run ask')
        has(p, r'a judgment call\. What you do hand over, write in short steps', f'{tid}: the verify-before-asking rule')
        has(p, re.escape(f'the ask file {root / ".runner" / "asks" / f"{tid}.json"}, as JSON: {{"summary"'), f'{tid}: where the ask file goes')
        for k in ('"where"', '"steps"', '"expect"', '"shots"', '"caption"', 'One action per step', 'no file names or code',
                  f'put under {root / ".runner" / "asks" / tid}/', 'no secrets or tokens'):
            check(k in p, f'{tid}: {k}', p)
    eq(p.count('{path}') + p.count('{{'), 0, 'nothing left unfilled')


def test_worktree(root: Path, t: Path) -> None:
    print('from a slot\'s worktree the ask file is the main checkout\'s')
    wt = t / 's1'
    git(root, 'worktree', 'add', '-q', '-b', 'task/F1', str(wt))
    p = R.prompt_for('F1', 1, 1, wt, 'main')
    check(str(root / '.runner' / 'asks' / 'F1.json') in p, 'the brief names the main checkout\'s folder')
    f = put(root, 'F1')
    eq(A.ask_file('F1', cfg(wt)), f, 'and done there reads the same one')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(wt)}
    r = run(wt, 'done', 'F1', 'F1: part', '--no-test', '--blocked', 'CONFIRM: ' + 'look at it ' * 30, env=env)
    check(r.returncode == 0 and 'ask file' not in r.stdout, 'a long line with its file: blocked, no note', r.stdout + r.stderr)
    eq(there(f), (True, True), 'done --blocked keeps the file just written')
    r = run(wt, 'plan', 'confirm', 'F1', 'it worked', env=env)
    check(r.returncode == 0, 'answered from the worktree', r.stdout + r.stderr)
    eq(there(f), (False, False), 'the main checkout\'s file and pictures go')
    git(root, 'worktree', 'remove', '--force', str(wt))


def test_long_line(root: Path, env: dict) -> None:
    print('done --blocked says once that a long line has no ask file, and blocks all the same')
    done = lambda tid, why, *more: run(root, 'done', tid, f'{tid}: x', '--no-test', '--blocked', why, *more, env=env)  # noqa: E731
    f = root / '.runner' / 'asks' / 'F1.json'
    r = done('F1', 'DECIDE: ' + 'x' * 193)
    eq((r.returncode, r.stdout.count(str(f))), (0, 1), '201 characters: said once, naming the file')
    has(r.stdout, r'(?m)^blocked F1$', 'and blocked')
    run(root, 'plan', 'confirm', 'F1', 'yes', env=env)
    r = done('F1', 'DECIDE: ' + 'x' * 192)
    check(r.returncode == 0 and 'ask file' not in r.stdout, '200 characters: nothing said', r.stdout)
    r = done('F2', 'waits for F3 ' * 20, '--after', 'F3')
    check(r.returncode == 0 and 'ask file' not in r.stdout, 'a wait on a task, not a person: nothing said', r.stdout)


def test_clear(root: Path) -> None:
    print('the ask file goes when the item is answered, dropped or blocks again')
    todo = R.C.todo
    for what, do in (('confirm', lambda: P.confirm('F3', 'yes', todo=todo)),
                     ('change', lambda: P.change('F3', 'other', todo=todo)),
                     ('unblock', lambda: P.unblock('F3', todo=todo)),
                     ('blocks again', lambda: P.block('F3', 'DECIDE: a new one?', todo=todo)),
                     ('drop', lambda: P.drop('F3', 'no', todo=todo))):
        f = put(root, 'F3')
        other = put(root, 'F33')
        P.block('F3', 'DECIDE: this?', todo=todo, keep_ask=True)
        eq(there(f), (True, True), f'{what}: kept while it waits')
        do()
        eq(there(f), (False, False), f'{what}: gone')
        eq(there(other), (True, True), f'{what}: another task\'s stays')
    f = put(root, 'F2')
    P.unblock('F2', todo=todo)
    f = put(root, 'F2')
    P.block('F2', 'CONFIRM: see it', todo=todo, keep_ask=True)
    P.block('F2', 'fix first', todo=todo, after=['F1'])
    eq(there(f), (True, True), 'waiting on a task first: the same ask comes back, with its file')
    scratch = root.parent / 'scratch.md'
    scratch.write_text(todo.read_text(encoding='utf-8'), encoding='utf-8')
    P.unblock('F2', todo=scratch)
    eq(there(f), (True, True), 'a change to a scratch copy of the plan touches no ask file')
    A.clear_ask('..', todo)
    check((root / '.runner').is_dir() and f.exists(), 'an odd id clears nothing')


def test_ask(root: Path) -> None:
    print('`run ask` blocks keep the file too')
    tid = P.add('F', 'pick a colour', todo=R.C.todo)
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'plan')
    f = put(root, tid)
    mark = R.C.notes(f'{tid}.ask')
    mark.write_text(json.dumps({'sid': 's', 'question': 'Which?', 'blocked': False}), encoding='utf-8')
    A.block_asks('main')
    check(json.loads(mark.read_text(encoding='utf-8'))['blocked'], 'blocked by the run')
    check(any(a[1] == tid for a in P.asks(R.C.todo)), 'under Needs you')
    eq(there(f), (True, True), 'with its ask file')


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        root, env = make(t)
        test_brief(root)
        test_worktree(root, t)
        test_long_line(root, env)
        test_clear(root)
        test_ask(root)
    return report([])


if __name__ == '__main__':
    raise SystemExit(main())
