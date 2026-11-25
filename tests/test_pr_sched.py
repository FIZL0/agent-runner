#!/usr/bin/env python3
"""PR mode's limit and display (F420): no new task past `[git] pr_max` open pull requests, no start on an unmerged one,
and each open pull request with its link and state in status, the snapshot, the terminal UI and Needs you.

    python3 tests/test_pr_sched.py        (no network; some seconds of git)
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

from _check import check, eq, git, has, report, run

from agent_runner import config as CF, pr, pr_rows as R, sched, state as S, status, tui as T, ui_model as U  # noqa: E402
from _web import logic_js  # noqa: E402
from test_pr import make, using, work  # noqa: E402

TASKS = ('- [ ] **F1** one | files: a.py\n- [ ] **F2** two | files: b.py | after: F1\n'
         '- [ ] **F3** three | files: c.py\n- [ ] **F4** four | files: d.py\n')
NOW = {'state': 'OPEN', 'reviewDecision': 'REVIEW_REQUIRED', 'mergeable': 'MERGEABLE', 'statusCheckRollup': []}
RED = [{'name': 'test', 'conclusion': 'FAILURE'}]


def rec(n: int, *ids: str, **more) -> dict:
    return {'key': ids[0], 'ids': list(ids), 'tips': {}, 'branch': f'task/{ids[0]}', 'head': 'h', 'base': 'b', 'gate': '',
            'number': n, 'url': f'https://github.com/o/r/pull/{n}', 'pushed': 'h', 'state': 'OPEN', 'at': time.time(), **more}


def keep(*recs: dict) -> None:
    with pr.edit() as d:
        d[:] = recs


def free() -> list[str]:
    return [t for t, (kind, _) in sched.explain({}, set(), 'main').items() if kind == 'free']


def queue(up: bool = True) -> dict[str, dict]:
    return {q['id']: q for q in U.snapshot(up=up, links={})['queue']}


def test_states() -> None:
    print('the state in words')
    for got, want in (({}, 'waits for review'), ({'reviewDecision': 'CHANGES_REQUESTED'}, 'changes asked'),
                      ({'statusCheckRollup': RED}, 'CI red'), ({'mergeable': 'CONFLICTING'}, 'conflicts with main'),
                      ({'statusCheckRollup': RED, 'reviewDecision': 'CHANGES_REQUESTED'}, 'CI red, changes asked'),
                      ({'reviewDecision': 'APPROVED'}, 'approved, waits to be merged'),
                      ({'reviewDecision': 'APPROVED', 'statusCheckRollup': RED}, 'CI red')):
        eq(R.state_of(rec(1, 'F1', **R.seen({**NOW, **got}))), want, f'{got}')
    eq(R.state_of(rec(1, 'F1', round={'tid': 'F1', 'items': [{'key': 'c1'}]})), 'changes asked', 'a comment its session is on')
    eq(R.state_of(rec(1, 'F1')), 'waits for review', 'one GitHub was not asked about yet')


def test_limit(tmp: Path) -> None:
    print('no new task past the limit')
    repo, _, _ = make(tmp, 'lim', tasks=TASKS)
    eq(S.C.pr_max, 5, 'five by default')
    eq(free(), ['F1', 'F3', 'F4'], 'none open: what may start')
    keep(*(rec(n, f'X{n}') for n in range(1, 5)), rec(0, 'X9'), rec(7, 'X7', state='CLOSED'), rec(8, 'X8', state='MERGED'))
    eq((R.full(), free()), (0, ['F1', 'F3', 'F4']), 'four open: closed, merged and collecting ones do not count')
    keep(*(rec(n, f'X{n}') for n in range(1, 6)))
    eq((R.full(), free(), sched.pick({}, set(), 'main')), (5, [], None), 'five open: nothing new starts')
    eq(sched.explain({}, set(), 'main')['F3'], ('waiting for a pull request to be merged', '5 are open, [git] pr_max is 5'),
       'the dry run says why')
    q = queue()
    eq((q['F3']['state'], q['F3']['tool_wait'], q['F3']['pr_wait']),
       ('tool', 'waits for an open pull request to be merged', True), 'its row says so')
    eq(queue(up=False)['F3']['tool_wait'], 'waits for the run to start', 'no run up: that first')
    git(repo, 'branch', 'asked/F3')
    eq(free(), ['F3'], 'a session that goes on is not new')
    check('pr_wait' not in queue()['F3'], 'nor does its row say that it waits')
    git(repo, 'branch', '-D', 'asked/F3')
    with mock.patch.dict(S.C.raw['git'], pr_max=0):
        eq(free(), ['F1', 'F3', 'F4'], '0: no limit')
    with mock.patch.dict(S.C.raw['git'], pr_max=6):
        eq(free(), ['F1', 'F3', 'F4'], 'a higher one')
    with mock.patch.dict(S.C.raw['git'], pr=False):
        eq((free(), R.rows(), R.asks(), R.lines()), (['F1', 'F3', 'F4'], [], [], []), 'PR mode off: nothing of it')
    has(R.limit_line(), '^5 pull requests are open: no new task starts until you merge or close one$', 'status says it')
    keep(*(rec(n, f'X{n}') for n in range(1, 5)), rec(5, 'X5', state='MERGED'))
    eq(free(), ['F1', 'F3', 'F4'], 'one merged: they start')


def test_setting(tmp: Path) -> None:
    print('the setting')
    repo, _, _ = make(tmp, 'set', tasks=TASKS)
    eq(CF.setting_check(repo, 'git', 'pr_max', 3), '', 'a number')
    has(CF.setting_check(repo, 'git', 'pr_max', -1), 'below 0', 'not a negative one')
    f = repo / 'runner.toml'
    f.write_text(f.read_text(encoding='utf-8').replace('pr = true', 'pr = true\npr_max = "many"'), encoding='utf-8')
    has(run(repo, 'plan').stderr, r'\[git\] pr_max must be a whole number', 'a config with another does not load')


def test_after(tmp: Path) -> None:
    print('what is after an open pull request waits for its merge')
    repo, _, gh = make(tmp, 'aft', tasks=TASKS)
    with using(gh):
        work(repo, 'F1', 'a.py')
        check('F2' not in free(), 'F2 does not start on the unmerged F1')
        eq(pr.mates('F2', S.plan_text('main')), set(), 'nor on its branch')
        q = queue()
        eq(q['F1']['tool_wait'], 'pull request #1: waits for review', 'the row of the task itself')
        eq((q['F2']['state'], q['F2']['after_title']), ('after', 'F1 one (pull request #1 is not merged)'), 'the waiting row')
        gh.prs[0]['state'] = 'CLOSED'
        pr.look('main', gh)
        check('F2' not in free(), 'closed without a merge: it waits still')
        gh.prs[0]['state'] = 'OPEN'
        gh.merge(1, 'squash', tmp / 'm')
        pr.look('main', gh)
        check('F2' in free(), 'merged: it starts')
        eq(R.rows(), [], 'and nothing is open')


def test_look(tmp: Path) -> None:
    print('a look keeps what GitHub says')
    repo, _, gh = make(tmp, 'look', tasks=TASKS)

    def more(*a):
        r = gh(*a)
        if a[:2] != ('pr', 'view'):
            return r
        check('reviewDecision' in a[-1], 'it asks for the review')
        return type(r)(a, 0, json.dumps({**json.loads(r.stdout), 'reviewDecision': 'CHANGES_REQUESTED', 'statusCheckRollup': RED}), '')
    with using(gh):
        work(repo, 'F1', 'a.py')
        with mock.patch('agent_runner.pr_feedback.look'):
            pr.look('main', more)
    eq([(r['number'], r['ids'], r['title'], r['state']) for r in R.rows()], [(1, ['F1'], 'one', 'CI red, changes asked')], 'its row')


def test_shown(tmp: Path) -> None:
    print('status, the snapshot, the terminal UI and Needs you')
    make(tmp, 'show', tasks=TASKS)
    keep(rec(3, 'F1', ci_red=True), rec(4, 'F3', 'F4'))
    url = 'https://github.com/o/r/pull/'
    text = status.status_text(True, {}, [], {'F1': 'one', 'F3': 'three'}, time.time(), waiting=status.waiting_ok())
    for want in ('pull requests:', '  #3 F1 one · CI red', f'    {url}3', '  #4 F3, F4 three · waits for review', f'    {url}4',
                 'Pull request #3: CI red - this clears once it is merged or closed [pr-3]'):
        check(want in text.splitlines() or want in text, f'status: {want}', text)
    snap = U.snapshot(up=True, links={})
    eq([(r['id'], r['url'], r['state']) for r in snap['prs']], [('pr-3', url + '3', 'CI red'), ('pr-4', url + '4', 'waits for review')],
       'the snapshot')
    eq(snap['pr_limit'], '', 'under the limit')
    check(f'#3 F1: CI red · {url}3' in snap['status'], 'a status line each, which the terminal UI lists', snap['status'])
    need = next(n for n in snap['needs'] if n['id'] == 'pr-3')
    eq((need['label'], need['url'], need['title'], need['acts'], need['answers']), ('PR', url + '3', 'one', [], []),
       'Needs you: its link, and nothing to answer')
    eq((need['detail']['said'], need['detail']['summary'], need['age']), ('Review this', 'Pull request #3: CI red', 'now'), 'its card')
    eq((U.need_label('pr-3'), U.need_label('pr-9')), ('PR', ''), 'its label while it is open')
    has(run(S.ROOT, 'plan', 'waiting').stdout, f'PR  pr-3 .*{url}3', 'plan waiting')
    line = T.RunPage.row_lines(mock.Mock(run_failed='', row=lambda n, it: [('● ', 'dim'), (it, 'fg')]), 1, f'#3 F1: CI red · {url}3', 30, True)
    check(len(line) > 1 and url + '3' in ''.join(t for l in line for t, _ in l), 'a selected line shows its whole link', line)
    if shutil.which('node'):
        eq(logic_js([['idleWhy', {'queue': [{'id': 'F2', 'state': 'tool', 'pr_wait': True}, {'id': 'F3', 'state': 'tool'}]}, []]]),
           ['Of 2 queued tasks, 1 waits for a pull request, 1 waits for a tool or a check.'], 'an idle slot says it')
    S.C.notes('prs.json').write_text('{', encoding='utf-8')
    eq((R.rows(), R.limit_line()), ([], ''), 'a broken file costs the rows, not status')


TESTS = [test_limit, test_setting, test_after, test_look, test_shown]

if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='agent-runner-test-pr-sched-') as t:
        sys.exit(report([test_states, *(lambda f=f, i=i: f((Path(t) / str(i)).mkdir() or Path(t) / str(i)) for i, f in enumerate(TESTS))]))
