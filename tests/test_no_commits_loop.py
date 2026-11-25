#!/usr/bin/env python3
"""B774: two runs of a task in a row with no commits, and nothing in the plan changed between them, block it under
Needs you with what its last session said.

    python3 tests/test_no_commits_loop.py        (no network; a few seconds of git)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report

from agent_runner import loop as L, no_commits as N, plan as P, runner as R  # noqa: E402
from agent_runner import sched as S  # noqa: E402
from agent_runner import state  # noqa: E402

TODO = 'plan/TODO.md'


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / TODO).write_text('# TODO\n\n### Next\n\n- [ ] **R1** look | files: a.py\n'
                             '- [ ] **R2** other | files: b.py\n', encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def empty_run(repo: Path, said: str = 'No brief.', tid: str = 'R1', n: int = 1) -> None:
    """One session on `tid` that ends with no commits, then the run's tick."""
    P._clear_ask(tid, R.C.todo)  # as `slots.start` does: it must not touch the count
    git(repo, 'branch', f'task/{tid}', 'main')
    with mock.patch.object(L, 'last_words', lambda sid: said):
        eq(L._finish(tid, n, 'sid', 'main'), True, f'{tid}: the session ends, nothing to merge')
    N.tick('main')


def starts(tid: str = 'R1') -> bool:
    return S.holds(next(t for t in S.tasks('main') if t[0] == tid), set(), S.held({}, 'main')) is None


def blocked(tid: str = 'R1') -> bool:
    return tid in S.blocked_tasks('main')


def fresh(repo: Path) -> None:
    """R1 open and never run."""
    if blocked():
        P.unblock('R1', todo=repo / TODO)
        git(repo, 'commit', '-qm', 'reopen', '--', TODO)
    N.forget('R1')


def test_blocks(repo: Path) -> None:
    print('two in a row: blocked under Needs you with the last words')
    empty_run(repo, 'first')
    check(not blocked() and starts(), 'after one it may start again')
    R.init(repo)  # the next run of the run
    empty_run(repo, 'The brief is missing | files: x (after R2) BLOCKED: so I stopped — [A / B]')
    check(blocked(), 'after two it is blocked')
    a = [x for x in P.asks(repo / TODO) if x[1] == 'R1']
    eq([x[0] for x in a], ['DECIDE'], 'it lists under Needs you')
    has(str(a), 'ended 2 times in a row with no commits', 'why')
    has(str(a), 'The brief is missing / files: x after R2 blocked so I stopped - A / B', 'what its last session said')
    ls = P.lines(repo / TODO)
    line = next(l for l in ls if '**R1**' in l)
    eq(P.fields(line).get('files'), ['a.py'], 'its words are not read as fields')
    eq(git(repo, 'status', '--porcelain', '--', TODO), '', 'committed')
    events = (repo / '.runner/events.jsonl').read_text(encoding='utf-8')
    has(events, f'"kind": "{state.EV_LEFT}", "id": "R1"', 'the feed has it')
    check(starts('R2'), 'the other task is not held')


def test_reopened(repo: Path) -> None:
    print('reopened: it counts afresh')
    check(blocked(), 'still blocked')
    P.unblock('R1', todo=repo / TODO)
    git(repo, 'commit', '-qm', 'reopen', '--', TODO)
    check(starts(), 'it starts again')
    empty_run(repo)
    check(not blocked() and starts(), 'one more is the first of a row')
    fresh(repo)


def test_reopened_between(repo: Path) -> None:
    print('blocked and reopened between the two runs, its line the same: not in a row')
    empty_run(repo)
    P.block('R1', 'a wait', todo=repo / TODO, after=[])
    git(repo, 'commit', '-qm', 'block', '--', TODO)  # no tick while it is blocked: no run may be up
    P.unblock('R1', todo=repo / TODO)
    git(repo, 'commit', '-qm', 'reopen', '--', TODO)
    empty_run(repo)
    check(not blocked(), 'not blocked')
    fresh(repo)


def test_changed(repo: Path) -> None:
    print('edited or told between: starts again')
    empty_run(repo)
    P.note('R1', 'try the other door', todo=repo / TODO)
    git(repo, 'commit', '-qm', 'note', '--', TODO)
    empty_run(repo)
    check(not blocked() and starts(), 'a noted task starts again')
    told = P.told_file(R.C, 'R1')
    told.parent.mkdir(parents=True, exist_ok=True)
    told.write_text('use the spare key\n', encoding='utf-8')
    empty_run(repo)
    check(not blocked() and starts(), 'a told one too')
    long = P.long_form(R.C.plan_dir, 'R1')
    long.parent.mkdir(parents=True, exist_ok=True)
    long.write_text('# R1\n\nMore.\n', encoding='utf-8')
    empty_run(repo)
    check(not blocked() and starts(), 'and one whose long form changed')
    P.move('R1', 'bottom', todo=repo / TODO)
    P.note('R2', 'another task', todo=repo / TODO)
    git(repo, 'commit', '-qam', 'move')
    empty_run(repo)
    check(blocked(), 'moving it, or a note on another task, is no change to it')
    fresh(repo)


def test_edited_before_block(repo: Path) -> None:
    print('TODO.md busy at the block: the task is held, and an edit frees it')
    empty_run(repo)
    (repo / TODO).write_text((repo / TODO).read_text(encoding='utf-8') + '\nsomebody types\n', encoding='utf-8')
    empty_run(repo)
    check(not blocked() and not starts(), 'not blocked yet, and no run starts it')
    has(str(S.explain({}, set(), 'main')['R1']), 'needs a person', 'the dry run says why')
    P.note('R1', 'now with a hint', todo=repo / TODO)
    git(repo, 'commit', '-qam', 'edit')
    N.tick('main')
    check(not blocked() and starts(), 'edited, it starts')
    fresh(repo)


def test_not_in_a_row(repo: Path) -> None:
    print('a run with commits between, or a take, does not count')
    empty_run(repo)
    git(repo, 'checkout', '-q', '-b', 'task/R1')
    git(repo, 'commit', '-q', '--allow-empty', '-m', 'R1 part')
    git(repo, 'checkout', '-q', 'main')
    with mock.patch.object(L, 'merge', lambda tid, branch: None):
        L._finish('R1', 1, 'sid', 'main')
    git(repo, 'branch', '-D', 'task/R1')
    empty_run(repo)
    check(not blocked(), 'commits between: not in a row')
    empty_run(repo, n=0)
    check(not blocked(), 'a take is no run')
    fresh(repo)


def test_plain() -> None:
    eq(N.plain('a  b\nc'), 'a b c', 'one line')
    eq(len(N.plain('x' * 999)), N.SAID_MAX + 1, 'cut')


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = make_repo(Path(td).resolve())
        R.init(repo)
        return report([test_plain, *(lambda t=t: t(repo) for t in (
            test_blocks, test_reopened, test_reopened_between, test_changed, test_edited_before_block,
            test_not_in_a_row))])


if __name__ == '__main__':
    sys.exit(main())
