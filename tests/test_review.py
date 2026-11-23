#!/usr/bin/env python3
"""F28: the spec review before done.

    python3 tests/test_review.py        (no network; a second or two, mostly git)

With `[run] review` on (the default) the slot prompt asks for a fresh subagent's spec review of the diff against
the brief, states when to skip it, and asks for the `review: …` line every commit message ends with; lean Claude
sessions get the Agent tool for it. `[run] review = false` drops all of that.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import runner as R  # noqa: E402


def make(tmp: Path, toml: str = '') -> tuple[Path, dict]:
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'runner.toml').write_text('[run]\nremote = false\n' + toml, encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    for text in ('add a thing | files: a.py', 'add another | files: b.py'):
        check(run(root, 'plan', 'add', 'F', text, env=env).returncode == 0, f'added {text}')
    return root, env


def test_prompt_on():
    print('review on (the default): the prompt carries the review paragraph and the skip rule')
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t))
        R.init(root)
        check(R.C.run['review'] is True and R.C.run['review_min_lines'] == 50, 'on by default, 50 lines')
        p = R.prompt_for('F1', 1, 1, root, 'main')
        has(p, r'Spec review, before `done`', 'the review paragraph')
        has(p, r'fresh subagent', 'in a fresh subagent')
        has(p, re.escape('`git diff main...HEAD`'), 'given the diff against the base branch')
        has(p, re.escape(f'`{R.C.command} plan brief F1`'), 'and the brief')
        for what in ('missing', 'not asked', 'implemented but wrong', 'quoting the task', 'under 300 words'):
            check(what in p, f'asks for {what!r}', p)
        has(p, r'Fix \(a\) and \(c\)', 'missing and wrong get fixed')
        has(p, r'never file them', 'not filed')
        has(p, r'Revert \(b\)', 'unasked extras reverted')
        has(p, r'--pri normal', 'a follow-up is filed at normal')
        has(p, r'Skip the review when the diff is under 50 changed lines', 'the skip rule, with the threshold')
        has(p, re.escape('no long-form brief (plan/tasks/F1.md)'), 'and the long-form exception')
        has(p, r'this task has none', 'F1 has no long form')
        for line in ('`review: nothing`', '`review: fixed <what>`', '`review: filed <IDs>`',
                     '`review: skipped (small)`'):
            check(line in p, f'the commit line {line}', p)
        check(p.index('Spec review') < p.index('Project policies:'), 'before the policies')
        tools = R.lean()
        eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write,Artifact,Agent', 'lean: the Agent tool too')

        long = root / 'plan' / 'tasks' / 'F2.md'
        long.parent.mkdir(parents=True, exist_ok=True)
        long.write_text('# F2\n\nThe long form.\n', encoding='utf-8')
        has(R.prompt_for('F2', 1, 1, root, 'main'), r'this task has one, so review it whatever its size',
            'a task with a long form is reviewed whatever its size')

        R.C.run['review_min_lines'] = 120
        try:
            has(R.prompt_for('F1', 1, 1, root, 'main'), r'under 120 changed lines', '[run] review_min_lines')
        finally:
            R.C.run['review_min_lines'] = 50


def test_prompt_off():
    print('review = false: no review paragraph, no review line, no Agent tool')
    with tempfile.TemporaryDirectory() as t:
        root, _ = make(Path(t), 'review = false\n')
        R.init(root)
        p = R.prompt_for('F1', 1, 1, root, 'main')
        check('Spec review' not in p and 'review: ' not in p and '"review"' not in p, 'not in the prompt', p)
        check('review' not in R.subagents(), 'no review subagent (F101)')
        tools = R.lean()
        eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write,Artifact,Agent',
           'lean: the Agent tool still, for the docs subagent (F101)')
        with mock.patch.dict(R.C.raw['models'], {'docs': False}):
            tools = R.lean()
            eq(tools[tools.index('--tools') + 1], 'Bash,Read,Edit,Write,Artifact', 'no subagent at all: no Agent tool')


if __name__ == '__main__':
    raise SystemExit(report([test_prompt_on, test_prompt_off]))
