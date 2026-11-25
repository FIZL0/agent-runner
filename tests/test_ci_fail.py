#!/usr/bin/env python3
"""T25: an auto-filed CI task names the failing test, and the same failing test comes back to its task.

    python3 tests/test_ci_fail.py        (no network; a few seconds of git)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, eq, git, has, report

from agent_runner import ci, plan as P, runner as R  # noqa: E402

J = 'test (ubuntu-latest)'


def raw(*lines: str) -> str:
    return ''.join(f'{J}\tTest gate\t2026-11-24T19:05:56.1386379Z {l}\n' for l in lines)


def far(*fails: str) -> str:
    """A log whose FAIL lines are far above its tail, as B765's was."""
    body = ['== tests/test_home_service.py', '  ok   no port of its own anywhere']
    for f in fails:
        body += [f'  FAIL {f}', "         got ['a']", "         want ['b']", '  ok   a stopping run does not move']
    body += [f'  ok   later {i}' for i in range(300)]
    return raw(*body, '##[error]failed: tests/test_home_service.py', '##[error]Process completed with exit code 1.',
               'Post job cleanup.')


def parsed(text: str) -> ci.Log:
    return ci.failed_log(lambda *a: subprocess.CompletedProcess(a, 0, text, ''), 1)[0]


def test_names():
    print('the failing tests a log names')
    for line, want in {
        "  FAIL one line: Home's link": "one line: Home's link",
        '--- FAIL: TestX (0.01s)': 'TestX',
        'test a::b ... FAILED': 'a::b',
        'FAILED tests/t.py::test_a[x] - assert 1': 'tests/t.py::test_a[x]',
        'tests/t.py::test_a FAILED   [ 12%]': 'tests/t.py::test_a',
        '[  FAILED  ] Suite.Case (3 ms)': 'Suite.Case',
        'FAIL: test_x (mod.C.test_x)': 'test_x [mod.C.test_x]',
        'FAIL src/a.test.js (5.2 s)': 'src/a.test.js',
        'not ok 3 - adds': 'adds',
        '  FAIL a | files: x — y `z` BLOCKED: n': "a / files: x - y 'z' BLOCKED n",
        '\x1b[31m  FAIL red\x1b[0m': 'red',
    }.items():
        eq(ci.failing_tests(parsed(raw(line))), [want], line)
    for line in ('FAIL', 'FAILED (failures=1)', 'FAIL\tpkg/a\t0.2s', '1 FAILED:', '  ok   it shows FAIL here',
                 'test result: FAILED. 1 passed', '[  FAILED  ] 1 test, listed below:'):
        eq(ci.failing_tests(parsed(raw(line))), [], f'no test: {line!r}')
    crash = parsed(raw('== tests/test_a.py', 'Traceback (most recent call last):', '  File "a.py", line 1', '    f()',
                       'ValueError: no', *['  ok   x'] * 60))
    eq(ci.failing_tests(crash), ['tests/test_a.py'], 'a traceback and no FAIL line: the test file it is under')
    has('\n'.join(ci.fail_lines(crash)), r'ValueError: no$', 'a traceback is kept to its exception')
    eq(ci.fail_lines(parsed(raw(*['  ok   x'] * 9))), [], 'nothing failed, nothing kept')


class Project:
    def __init__(self, toml: str = ''):
        self.repo = repo = Path(tempfile.mkdtemp())
        git(repo, 'init', '-q', '-b', 'main')
        (repo / 'plan').mkdir()
        (repo / 'plan/TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **F1** a task\n', encoding='utf-8')
        (repo / 'plan/DONE.md').write_text('# DONE\n', encoding='utf-8')
        (repo / 'runner.toml').write_text('[run]\ntest = "true"\nmin_free_gb = 0\nremote = false\n'
                                          f'ci_watch = ["ci.yml"]\n{toml}', encoding='utf-8')
        (repo / '.gitignore').write_text('.runner/\n', encoding='utf-8')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'start')
        R.init(repo)
        self.n, self.log = 0, ''
        ci.gh_in = lambda cwd: self.gh

    def gh(self, *a):
        if a[:2] == ('run', 'list'):
            out = json.dumps([{'databaseId': self.n, 'status': 'completed', 'conclusion': 'failure', 'attempt': 2,
                               'headSha': f'{self.n:08d}ff', 'displayTitle': 'Merge', 'createdAt': '2026-11-24T19:04:00Z',
                               'url': f'https://github.com/o/r/actions/runs/{self.n}'}])
        elif '--log-failed' in a:
            out = self.log
        else:
            out = json.dumps({'jobs': [{'name': J, 'conclusion': 'failure'}]})
        return subprocess.CompletedProcess(a, 0, out, '')

    def red(self, log: str) -> list[str]:
        self.n, self.log = self.n + 1, log
        got = R.watch_ci('main', force=True)
        eq(git(self.repo, 'status', '--porcelain', '--', 'plan'), '', '   all of it is committed')
        return got

    def line(self, tid: str, name: str = 'TODO.md') -> str:
        return next((l for l in P.lines(self.repo / 'plan' / name) if f'**{tid}**' in l), '')

    def long(self, tid: str) -> str:
        return (self.repo / f'plan/tasks/{tid}.md').read_text(encoding='utf-8')

    def close(self, tid: str, drop: bool = False) -> str:
        """The task's fix lands and it is ticked (or a person drops it). The merge's commit."""
        todo, done = self.repo / 'plan/TODO.md', self.repo / 'plan/DONE.md'
        if drop:
            P.drop(tid, 'not worth it', todo=todo, done=done)
        else:
            P.tick(tid, todo, done)
        git(self.repo, 'add', '-A')
        git(self.repo, 'commit', '-qm', f"Merge branch 'task/{tid}'")
        return git(self.repo, 'log', '-1', '--format=%h')


def test_far_above():
    print('a FAIL far above the tail: first in the long form, and on the line')
    p = Project()
    tid, = p.red(far("one line: Home's link"))
    own = p.long(tid)
    fail, tail = own.find("FAIL one line: Home's link"), own.find('Last 40 lines')
    check(0 < fail < tail, 'the FAIL line comes before the tail', own[:900])
    check("got ['a']" in own and 'no port of its own' in own, 'with a few lines around it')
    has(own, r'exit code 1\.\n```', 'the tail still ends at the last error')
    check('later 299' in own and 'later 100' not in own, 'and holds its last lines only')
    has(p.line(tid), r"Failing: `one line: Home's link`\. ", 'the line names it')

    print('a red run while it is open')
    eq(p.red(far("one line: Home's link")), [], 'the same failing test: its open task has it')
    eq(p.red(far("one line: Home's link", 'the other')), [tid], 'a different one: put on the open task')
    has(p.line(tid), r'— run 3 on 00000003 also fails `the other`', 'named there')
    check(p.long(tid).index('FAIL the other') < p.long(tid).index('## Before'), 'its log is first in the long form')
    eq(p.red(far('the other')), [], 'once')
    P.block(tid, 'DECIDE: what now?', todo=p.repo / 'plan/TODO.md', after=[])
    git(p.repo, 'commit', '-qam', 'blocked')
    eq(p.red(far('a third')), [tid], 'a blocked one too')
    has(p.line(tid), r'also fails `a third`.* BLOCKED: DECIDE: what now\?', 'named before what it is blocked with')
    eq(sum('is red' in l for l in P.lines(p.repo / 'plan/TODO.md')), 1, 'one task all the while')


def test_closed():
    print('the same failing test after its task closed: the task is opened again, its fix linked')
    p = Project()
    tid, = p.red(far('flips'))
    sha = p.close(tid)
    R.REOPENED.clear()
    eq(p.red(far('flips', 'new one')), [tid], 'the same task')
    l = p.line(tid)
    has(l, r'^- \[ \] .*— reopened: run 2 on 00000002 fails `flips` again, and `new one`', 'open, and why')
    has(l, rf'Earlier fixes that did not hold: {tid} \({sha}\)', 'its earlier fix')
    eq(l.count('(filed '), 2, 'a stamp for each filing')
    has(p.long(tid), rf'- {tid}: https://github\.com/o/r/commit/{sha}', 'linked in the long form')
    eq((p.line(tid, 'DONE.md'), tid in R.REOPENED), ('', True), 'out of DONE.md, and the run may try it again')
    p.close(tid)
    print('a different failing test is a task of its own, and the third filing in a week waits on a person')
    q, = p.red(far('unrelated'))
    check(q != tid, 'a new task')
    has(p.line(q), rf'^- \[~\] .*2 auto-filed tasks closed in 7 days while it still fails \({tid} 2 times\)',
        'a reopened task counts each time')

    print('a dropped task stays dropped: a new one, the dropped one named')
    p = Project()
    tid, = p.red(far('flips'))
    p.close(tid, drop=True)
    got, = p.red(far('flips'))
    check(got != tid, 'a new task')
    has(p.line(got), rf'Earlier fixes that did not hold: {tid} \(dropped\)', 'the dropped one named')


def test_many():
    print('many failing tests: a few on the line, all in the long form')
    p = Project()
    names = [f'case {i}' for i in range(90)]
    tid, = p.red(far(*names))
    has(p.line(tid), r'`case 4` and 85 more\. ', 'the line names five')
    check('more such lines in the log' in p.long(tid), 'the FAIL lines stop somewhere')
    eq(p.red(far(*names)), [], 'and the rest still count as named')


def test_rollback():
    print('a plan edit git refuses is put back, long form too')
    p = Project()
    tid, = p.red(far('a'))
    was = (p.line(tid), p.long(tid))
    hook = p.repo / '.git/hooks/pre-commit'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('#!/bin/sh\nexit 1\n')
    hook.chmod(0o755)
    eq(p.red(far('b')), [], 'nothing filed')
    eq((p.line(tid), p.long(tid)), was, 'the task and its long form as they were')
    hook.unlink()
    p.n -= 1
    eq(p.red(far('b')), [tid], 'the next look tries that run again')


if __name__ == '__main__':
    real = ci.gh_in
    try:
        code = report([test_names, test_far_above, test_closed, test_many, test_rollback])
    finally:
        ci.gh_in = real
    sys.exit(code)
