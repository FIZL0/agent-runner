#!/usr/bin/env python3
"""B805: a task filed on main after a merge under way was built does not start on that merge, whose plan has no line
for it: it waits for the merge and starts on main.

    python3 tests/test_stack_new_task.py          (a temp repo, a second of git)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, report

from agent_runner import merge as M, runner as R, stack

TODO = '# TODO\n\n### Next\n\n- [ ] **S1** first | files: a.py\n- [ ] **S2** second | files: a.py\n'
LATE = '- [ ] **S3** filed late | files: a.py\n'


def make_repo(tmp: Path) -> Path:
    repo = tmp / 'proj'
    repo.mkdir()
    git(repo, 'init', '-q', '-b', 'main')
    (repo / 'plan').mkdir()
    (repo / 'plan/TODO.md').write_text(TODO, encoding='utf-8')
    (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
    (repo / 'a.py').write_text('# a\n', encoding='utf-8')
    (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n', encoding='utf-8')
    (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'start')
    return repo


def test_new_task(tmp: Path):
    repo = make_repo(tmp)
    R.init(repo)
    git(repo, 'checkout', '-q', '-b', 'task/S1')
    (repo / 'a.py').write_text('# S1\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'S1: the first')
    on = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-q', 'main')
    (repo / 'plan/TODO.md').write_text(TODO + LATE, encoding='utf-8')
    git(repo, 'commit', '-qam', 'S3 filed')
    with mock.patch.object(M, 'UNDER', [{'on': on, 'tids': ['S1']}]), mock.patch.object(M, 'AHEADS', []):
        print('a task the merge has the line of starts on it')
        task = R.pick({}, {'S1'}, 'main', claim=True)
        eq((task and task[0], stack.CHOSEN.get('S2', {}).get('on')), ('S2', on), 'S2 is chosen for the merge')
        stack.CHOSEN.clear()

        print('one filed since does not')
        eq(R.pick({}, {'S1', 'S2'}, 'main', claim=True), None, 'S3 waits for the merge')
        check('S3' not in stack.CHOSEN, 'nothing is chosen for it to start on')
        why: dict = {}
        R.pick({}, {'S1', 'S2'}, 'main', why=why)
        eq(why.get('S3'), ('waiting for files', 'a.py held by S1'), 'and the dry run says so')

        print('a plan outside the repo is one copy, which every branch reads')
        with mock.patch.object(type(R.C), 'plan_external', True):
            check(stack.has_line(on, 'S3'), 'so no merge lacks a line')

        print('a merge built since it was filed is one to start on')
        git(repo, 'checkout', '-q', '--detach', 'main')
        git(repo, 'merge', '-q', '--no-ff', '-m', 'S1', 'task/S1')
        newer = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'checkout', '-q', 'main')
        M.AHEADS[:] = [{'base': on, 'tids': [], 'merged': newer}]
        task = R.pick({}, {'S1', 'S2'}, 'main', claim=True)
        eq((task and task[0], stack.CHOSEN.get('S3', {}).get('on')), ('S3', newer), 'S3 starts on that one')
        stack.CHOSEN.clear()

    print('once the merge is on main, S3 starts there')
    git(repo, 'merge', '-q', '--no-ff', '-m', 'S1', 'task/S1')
    git(repo, 'branch', '-D', 'task/S1')
    with mock.patch.object(R.MUX, 'open', lambda *a, **kw: os.getpid()), \
            mock.patch.object(R, 'prompt_for', lambda *a, **kw: 'brief'):
        task = R.pick({}, {'S1', 'S2'}, 'main', claim=True)
        eq(task and task[0], 'S3', 'S3 is picked')
        check(R.start(1, task, 'main', '', 0, 1), 'and starts')
    eq(git(repo, 'rev-parse', 'task/S3'), git(repo, 'rev-parse', 'main'), 'on main')
    check('**S3**' in (R.SLOTS_DIR / 's1/plan/TODO.md').read_text(encoding='utf-8'), 'with its line in its plan')
    eq(stack.stacked('S3', 'main'), {}, 'and is recorded on no merge')


def main() -> int:
    with tempfile.TemporaryDirectory() as t, mock.patch.dict(os.environ, {'AGENT_RUNNER_HOME': str(Path(t) / 'home')}):
        return report([lambda: test_new_task(Path(t))])


if __name__ == '__main__':
    sys.exit(main())
