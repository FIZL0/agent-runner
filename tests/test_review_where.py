#!/usr/bin/env python3
"""F444d: the Review page of a change that waits on its task branch, or as a pull request in PR mode.

    python3 tests/test_review_where.py        (no network; a second or two, mostly git)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report, run

from agent_runner import runner as R  # noqa: E402


def make(tmp: Path) -> Path:
    root = tmp / 'proj'
    root.mkdir()
    git(root, 'init', '-q', '-b', 'main')
    (root / 'runner.toml').write_text('[run]\nremote = false\n', encoding='utf-8')
    (root / '.gitignore').write_text('.runner/\n', encoding='utf-8')
    git(root, 'add', '-A')
    git(root, 'commit', '-qm', 'start')
    env = {**os.environ, 'AGENT_RUNNER_REPO': str(root)}
    env.pop('AGENT_RUNNER', None)
    check(run(root, 'plan', 'add', 'F', 'add a thing | files: a.py', env=env).returncode == 0, 'added F1')
    return root


def test_branch():
    print('a change on its task branch: its diff, why, questions and how to answer it')
    from agent_runner import review as RV, state as S
    with tempfile.TemporaryDirectory() as t:
        root = make(Path(t))
        R.init(root)
        x, why = RV.waiting_change('F1', 'main')
        check(x is None and 'no task/F1 branch' in why, 'no branch, no change', why)
        git(root, 'checkout', '-qb', 'task/F1')
        (root / 'a.py').write_text('one <b>\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'F1 a thing')
        git(root, 'checkout', '-q', 'main')
        x, why = RV.waiting_change('F1', 'main')
        check(x is not None, 'the change is found', why)
        eq((x['where'], x['files'], x['title']), ('branch', ['a.py'], 'add a thing'), 'on the branch, its files, its title')
        page = RV.where_page_html(x)
        has(page, 'task/F1', 'says where it waits')
        has(page, '\\+one &lt;b&gt;', 'the diff, escaped')
        has(page, 'review F1 --ask', 'how to ask about it')
        has(page, 'plan note F1', 'how to ask for a better way')
        said, _ = RV.ask_change(x, 'why one?', root, once=lambda text: ('because', ''))
        eq(said, 'because', 'answered')
        has(RV.where_page_html(x), 'why one\\?', 'the question is on its page')


def test_pr():
    print('a change in a pull request: its diff from the pull request, and a link to it')
    from agent_runner import review as RV, state as S
    with tempfile.TemporaryDirectory() as t:
        root = make(Path(t))
        R.init(root)
        base = git(root, 'rev-parse', 'HEAD')
        git(root, 'checkout', '-qb', 'task/F1')
        (root / 'a.py').write_text('two\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'F1 a thing')
        head = git(root, 'rev-parse', 'HEAD')
        git(root, 'checkout', '-q', 'main')
        git(root, 'branch', '-qD', 'task/F1')
        url = 'https://github.com/o/r/pull/7'
        f = S.C.notes('prs.json')
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({'prs': [{'key': 'F1', 'ids': ['F1'], 'tips': {'F1': head}, 'branch': 'task/F1',
                                          'head': head, 'base': base, 'number': 7, 'url': url}]}), encoding='utf-8')
        x, why = RV.waiting_change('F1', 'main')
        check(x is not None and x['where'] == 'pr', 'the pull request carries it', why)
        page = RV.where_page_html(x)
        has(page, 'pull request', 'says it waits as a pull request')
        has(page, url, 'links it')
        has(page, '\\+two', 'its diff')


if __name__ == '__main__':
    raise SystemExit(report([test_branch, test_pr]))
