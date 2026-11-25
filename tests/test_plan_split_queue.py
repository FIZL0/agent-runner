#!/usr/bin/env python3
"""B811a: a split task stands in the queue, not in Parked, while one of its open parts is neither parked nor shelved.

    python3 tests/test_plan_split_queue.py        (a temp repo, a few seconds)
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import RUN, check, eq, git, has, report

from agent_runner import guide, plan as P, runner as R, sched, ui_model as U  # noqa: E402

SPLIT = '(split into F427a, F427b, F427c, F427d)'
PARENT = f'- [ ] **F427** (follow-up, later) Self-unblocking checks {SPLIT} | files: until.py'
SHELVED = f' BLOCKED: {P.SHELVED} DECIDE: which one'


def part(letter: str, pri: str = 'normal', blocked: str = '') -> str:
    return f'- [{"~" if blocked else " "}] **F427{letter}** (follow-up, {pri}) part {letter} | files: {letter}.py{blocked}'


def rows(ls: list[str]) -> dict[str, dict]:
    return {r['id']: r for r in U.queue_rows(ls, {})}


def lines(queued: list[str], parked: list[str]) -> list[str]:
    return ['# TODO', '', '### Follow-ups', '', *queued, '', '### Parked', '', *parked, '']


def state(queued: list[str], parked: list[str]) -> str:
    return rows(lines(queued, parked))['F427']['state']


def test_queued() -> None:
    print('a split task at level later, with an open part that is not parked')
    got = rows(lines([part('c'), part('d')], [PARENT, part('a', 'later')]))
    eq((got['F427']['state'], got['F427']['pri']), ('split', 'normal'), "F427's shape: in the queue")
    check('queue_unpark' not in U.row_acts('queue', got['F427']), 'with a queue row\'s actions, no Unpark')
    eq(got['F427a']['state'], 'parked', 'its parked part stays in Parked')
    eq(state([PARENT, part('c')], []), 'split', 'tagged later outside Parked')
    eq(state([part('c', blocked=' BLOCKED: DECIDE: which one')], [PARENT]), 'split', 'a blocked part is an open one')


def test_parked() -> None:
    print('one whose every open part is parked or shelved stays in Parked')
    eq(state([], [PARENT, part('c', 'later'), part('d', 'later')]), 'parked', 'parked parts')
    eq(state([], [PARENT, part('c')]), 'parked', 'a part in the Parked section, whatever its tag')
    check(P._shelved([part('c', blocked=SHELVED)], 0), 'a shelved part')
    eq(state([part('c', blocked=SHELVED)], [PARENT, part('d', 'later')]), 'parked', 'a shelved part and a parked one')
    eq(state([part('c').replace('[ ]', '[x]')], [PARENT, part('d', 'later')]), 'parked', 'a done part is not open')
    eq(state([], [PARENT]), 'parked', 'no part yet')
    eq(state([part('c')], [PARENT.replace(f' {SPLIT}', '')]), 'parked', 'a task that was not split')


def test_guide() -> None:
    print("guide queue's split text, and the plan its commands make")
    has(guide.control_topic('queue'), r'(?s)parked only until its parts are filed.*--pri later`, then `\S+ plan add ID '
        r'"part".*as the last step `\S+ plan edit ID --pri normal`', 'the last step takes the title out of Parked')
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / 'repo'
        (root / 'plan').mkdir(parents=True)
        git(root, 'init', '-q', '-b', 'main')
        (root / 'runner.toml').write_text('[run]\ntest = "true"\nremote = false\nmin_free_gb = 0\n', encoding='utf-8')
        (root / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n\n', encoding='utf-8')
        (root / 'plan' / 'DONE.md').write_text('# DONE\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        R.init(root)

        def plan(*args: str) -> None:
            r = subprocess.run([sys.executable, str(RUN), 'plan', *args], cwd=root, env=env, capture_output=True,
                               text=True, encoding='utf-8')
            eq(r.returncode, 0, f'plan {args[0]}: {r.stderr.strip()}')

        def of(tid: str) -> str:
            return rows(P.lines(R.C.todo))[tid]['state']

        plan('add', 'F', 'Checks (split into parts)', '--files', 'a.js', '--pri', 'later')
        eq(of('F1'), 'parked', 'parked until a part is filed')
        plan('add', 'F1', 'the first', '--files', 'a.js', '--pri', 'normal')
        eq(of('F1'), 'split', 'a part is queued')
        plan('edit', 'F1', '--pri', 'normal')
        eq({tid: s for s, _, tid, _, _ in P.iter_tasks(P.lines(R.C.todo))}, {'F1a': 'Follow-ups', 'F1': 'Follow-ups'},
           'both stand in Follow-ups')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'plan')
        eq([x[0] for x in sched.tasks('main')], ['F1a'], 'a run starts the part, not the title')


if __name__ == '__main__':
    sys.exit(report([test_queued, test_parked, test_guide]))
