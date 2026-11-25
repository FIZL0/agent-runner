#!/usr/bin/env python3
"""F451: a task's brief says to read only the ranges it needs and to hand a broad search to a subagent.

    python3 tests/test_brief_reads.py        (no network; a second or two, mostly git)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, git, report, run

from agent_runner import runner as R  # noqa: E402

READS = ('Read only the ranges you need', '`grep -n`', 'Do not read a big file whole',
         'read again a range you already have', 'Read all the task needs')
SEARCH = ('Hand a broad search over several files', 'read-only search subagent', '`Explore`',
          'file:line and a short conclusion')


def brief(root: Path, model: str, want: bool, what: str) -> None:
    p = R.prompt_for('F1', 1, 1, root, 'main', model)
    for text in READS:
        check(text in p, f'{what}: {text!r}', p)
    for text in SEARCH:
        check((text in p) is want, f'{what}: {"" if want else "no "}{text!r}', p)


def test_brief() -> None:
    with tempfile.TemporaryDirectory() as t:
        root = Path(t) / 'proj'
        root.mkdir()
        git(root, 'init', '-q', '-b', 'main')
        (root / 'runner.toml').write_text('[run]\nremote = false\n[git]\npush = false\n', encoding='utf-8')
        (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'start')
        env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
        env.pop('AGENT_RUNNER', None)
        check(run(root, 'plan', 'add', 'F', 'add a thing | files: a.py', env=env).returncode == 0, 'added F1')
        R.init(root)

        print('a Claude session: the reading lines and the search subagent')
        brief(root, 'opus', True, 'claude')
        print('a harness session: the reading lines, no subagent')
        brief(root, 'codex:gpt-test', False, 'harness')
        print('no Agent tool in a lean session: no subagent line')
        with mock.patch.dict(R.C.run, {'review': False, 'lean': True}), \
                mock.patch.dict(R.C.raw['models'], {'docs': False}):
            check('Agent' not in R.lean()[R.lean().index('--tools') + 1], 'lean gives no Agent tool')
            brief(root, 'opus', False, 'no Agent tool')
            print('not lean: every tool, so the subagent line')
            with mock.patch.dict(R.C.run, {'lean': False}):
                brief(root, 'opus', True, 'not lean')


if __name__ == '__main__':
    raise SystemExit(report([test_brief]))
