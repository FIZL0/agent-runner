"""F509: a landed task's finished write-up: kept when it finishes, given by /task/ID, shown first on its row.

    python3 tests/test_web_task_writeup.py
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from _check import check, eq, report

from agent_runner import done as D  # noqa: E402
from agent_runner import state as S  # noqa: E402
from agent_runner import web as W  # noqa: E402
from _web import fake_repo, get, logic_js, in_tmp  # noqa: E402


def test_writeup_kept_and_served(tmp: Path) -> None:
    fake_repo(tmp)
    eq(D.writeup(S.C, 'B2'), '', 'no write-up before it finishes')
    D.keep_writeup(S.C, 'B2', 'Fixed the merge retry and added a test.')
    check(D.writeup_file(S.C, 'B2').exists(), 'kept in the notes, apart from the run log')
    token = W.web_token()
    srv = W.serve(token, 0, '127.0.0.1', snap=lambda: {})
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        got = json.loads(get(f'{base}/task/B2?t={token}')[1])
        check(got['ok'] and 'Fix the merge retry' in got['text'], 'the prompt as before', got)
        eq(got['writeup'], 'Fixed the merge retry and added a test.', 'and the write-up')
    finally:
        srv.stop()


def test_row_shows_writeup_first(tmp: Path) -> None:
    if not shutil.which('node'):
        print('  (no node here: the row script test is skipped)')
        return
    t = {'text': 'Fix <the> retry', 'writeup': 'Did it'}
    landed, open_, none = logic_js([['taskBodyHTML', t, 'landed:B2', True], ['taskBodyHTML', t, 'B2', False],
                                    ['taskBodyHTML', {'text': 'Fix', 'writeup': ''}, 'landed:B2', True]])
    check(landed.index('Did it') < landed.index('<summary>Asked</summary>') < landed.index('Fix &lt;the&gt; retry'),
          'a landed task: the write-up first, the prompt folded under Asked', landed)
    check('Did it' not in open_ and 'Asked' not in open_ and 'Fix &lt;the&gt; retry' in open_, 'an open task: the prompt', open_)
    check('Asked' not in none, 'no write-up: the prompt as before', none)


def test_finish_keeps_writeup(tmp: Path) -> None:
    """`run finish` in a slot whose `done` ran keeps its summary with the task."""
    import os
    from unittest import mock
    from _check import git
    from agent_runner import tools as T
    from agent_runner.config import finished_mark
    repo = fake_repo(tmp)
    git(repo, 'checkout', '-qb', 'task/B2')
    old = os.getcwd()
    os.chdir(repo)
    try:
        with mock.patch.dict(os.environ, {'AGENT_RUNNER_SLOT': '7'}):
            finished_mark().touch()
            eq(T.cmd_finish(['Fixed the retry.']), 0, 'finish ends the session')
    finally:
        os.chdir(old)
    eq(D.writeup(S.C, 'B2'), 'Fixed the retry.', 'and its write-up is kept with B2')


def test_writeup_from_log(tmp: Path) -> None:
    """F513: a task finished before write-ups were kept: its summary from events, else from run.log."""
    fake_repo(tmp)
    S.C.notes('run.log').write_text('=== 2026-01-01T00:00:00 slot 1: B3 finished: Old fix, cut\n'
                                    '=== 2026-01-01T00:00:00 slot 1: B33 finished: other\n', encoding='utf-8')
    eq(D.writeup(S.C, 'B3'), 'Old fix, cut', 'from run.log')
    S.C.notes('events.jsonl').write_text(json.dumps({'time': '2026-01-01T00:00:00', 'kind': 'finished', 'id': 'B3',
                                                     'text': 'x', 'summary': 'Old fix, whole'}) + '\n',
                                         encoding='utf-8')
    eq(D.writeup(S.C, 'B3'), 'Old fix, whole', 'the events summary first')
    D.keep_writeup(S.C, 'B3', 'Kept')
    eq(D.writeup(S.C, 'B3'), 'Kept', 'a kept write-up wins')
    eq(D.writeup(S.C, 'B4'), '', 'none for a task that never finished')


if __name__ == '__main__':
    raise SystemExit(report([in_tmp(test_writeup_kept_and_served), in_tmp(test_writeup_from_log), in_tmp(test_row_shows_writeup_first),
                             in_tmp(test_finish_keeps_writeup)]))
