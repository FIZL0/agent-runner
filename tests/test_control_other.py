"""B785: the person's answer to a control session's question lets the slot that carries it out `plan add` in the project
the question names, and nothing else there (B103)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from _check import check, eq, report

from agent_runner import control as K, control_other as O, plan as P, runner as R

Q = 'Queue this setup as a high-priority task in iFizBox? [Yes, all (recommended) / Only one / No]'
REPO = Path(__file__).resolve().parent.parent


def git(d: Path, *a: str) -> str:
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *a], cwd=d, capture_output=True, text=True,
                          check=True).stdout


def project(d: Path) -> Path:
    (d / 'plan').mkdir(parents=True)
    (d / 'plan' / 'TODO.md').write_text('# TODO\n\n### Next\n\n- [ ] **A1** a task | files: a.py\n', encoding='utf-8')
    git(d, 'init', '-q', '-b', 'main')
    for k in ('name', 'email'):
        git(d, 'config', f'user.{k}', 't@t')
    git(d, 'add', '-A')
    git(d, 'commit', '-qm', 'start')
    return d


def test_route():
    print('B785: an answered question about another project: its slot may add there, only there, and only add')
    with tempfile.TemporaryDirectory() as tmp:
        mine, other, third = (project(Path(tmp) / n) for n in ('mine', 'iFizBox', 'third'))
        R.init(mine)
        tid = K.file_control_ask(5, 'sid-5', Q, 'https://claude.ai/code/session_01AbC')
        check(tid, 'filed')
        wt = Path(tmp) / 's1'
        git(mine, 'worktree', 'add', '-q', '-b', f'task/{tid}', str(wt), 'main')
        env = {k: v for k, v in os.environ.items() if not k.startswith('AGENT_')}
        env.update({'AGENT_RUNNER': '1', P.WORKTREE_ENV: str(wt), 'PYTHONPATH': str(REPO)})

        def plan(d: Path, *a: str) -> int:
            return subprocess.run([sys.executable, '-m', 'agent_runner', *a], cwd=d, env=env, capture_output=True,
                                  text=True).returncode
        add = ('plan', 'add', 'F', 'set up the phones', '--files', 'b.py')
        eq(plan(other, *add), 3, 'not answered yet: refused')
        P.confirm(tid, 'Yes, all', todo=mine / 'plan' / 'TODO.md')
        for a in (('plan', 'note', 'A1', 'x'), ('plan', 'tick', 'A1'), ('done', 'A1', 'm')):
            eq(plan(other, *a), 3, f'{a[0]} {a[1]} there is refused still')
        eq(plan(third, *add), 3, 'a project the question does not name is refused')
        git(wt, 'checkout', '-q', '-b', 'task/A1')
        eq(plan(other, *add), 3, "another task's slot is refused")
        git(wt, 'checkout', '-q', f'task/{tid}')
        eq(plan(other, *add), 0, 'answered: added')
        check('set up the phones' in git(other, 'show', 'HEAD:plan/TODO.md'), 'and committed there')
        check('set up the phones' not in (mine / 'plan' / 'TODO.md').read_text(encoding='utf-8'), 'not here')


def test_copilot_link_b874():
    print('B874: a chat on an agent that is not Claude gives the run page link to that chat, never a claude.ai/code one')
    from unittest import mock
    from agent_runner import web as web_urls
    with tempfile.TemporaryDirectory() as tmp:
        mine = project(Path(tmp) / 'mine')
        R.init(mine)
        check(K.ROOT == mine.resolve(), 'the control module writes in the temp repo', K.ROOT)
        before = git(REPO, 'log', '-1', '--format=%H', '--', 'plan/TODO.md')
        page = 'https://box.example.ts.net/?t=tok'
        with mock.patch.dict(K.C.run, {'agent': 'copilot'}), \
                mock.patch.object(web_urls, 'page_line', lambda site=None: f'run page: {page} (or http://box:8770/?t=tok)'):
            eq(K.ask_link(4, 'sid-4', 'https://claude.ai/code/session_01AbC'), f'{page}#c4', 'the run page, at chat c4')
            tid = K.file_control_ask(4, 'sid-4', 'Which? [A / B]', 'https://claude.ai/code/session_01AbC')
            line = (mine / 'plan' / 'TODO.md').read_text(encoding='utf-8')
            check(tid and f'{page}#c4' in line and 'claude.ai/code' not in line, 'filed with it', line)
            with mock.patch.object(web_urls, 'page_line', lambda site=None: ''):
                eq(K.ask_link(4, 'sid-4', 'https://claude.ai/code/session_01AbC'), '', 'no page served: no link')
        eq(K.ask_link(4, 'sid-4', 'https://claude.ai/code/session_01AbC'), 'https://claude.ai/code/session_01AbC',
           'on Claude Code: its own link')
        eq(git(REPO, 'log', '-1', '--format=%H', '--', 'plan/TODO.md'), before, "the checkout's plan is untouched")


def test_answers():
    print('B785: which answers allow it')
    head = (f'- [ ] **F9** (follow-up, normal) Control session 5 asked the person: "{Q}" Carry on from their answer (x). '
            f'{O.ROUTE}')
    yes = head + f' — your answer (DECIDE {Q}): '
    for said in ('Yes, all', 'Only one', 'ok, go', 'Yes — your answer (BLOCKED Log in): Done'):
        check(O.allowed(yes + said, 'iFizBox'), f'allowed: {said}')
    for said in ('No', 'no, leave it', "Don't", 'Not now', 'done', 'Wait', 'Let me think', 'Keep it here', f'Yes — your answer (DECIDE {Q}): No',
                 f'Yes — you said, on DECIDE {Q}: do this instead: nothing'):
        check(not O.allowed(yes + said, 'iFizBox'), f'refused: {said}')
    check(not O.allowed(head, 'iFizBox'), 'no answer')
    where = 'Where does it go? [iFizBox (recommended) / Clay / Neither]'
    eq([O.says_yes(s, where, p) for s, p in (('iFizBox', 'iFizBox'), ('Clay', 'iFizBox'), ('Neither', 'Clay'))],
       [True, False, False], 'a project only an option names needs that option picked')
    for q in ('Queue it in iFizBox — now? [Yes / No]', 'Queue it in iFizBox? [Yes / No] https://example.com/a'):
        with tempfile.TemporaryDirectory() as tmp:
            R.init(project(Path(tmp) / 'mine'))
            todo = Path(tmp) / 'mine' / 'plan' / 'TODO.md'
            tid = K.file_control_ask(5, 'sid-5', q, 'https://claude.ai/code/session_01AbC')
            P.confirm(tid, 'Yes', todo=todo)
            check(O.allowed(' '.join(P.section(todo, tid)), 'iFizBox'), f'as the plan notes it: {q}')
    check(not O.allowed(yes + 'Yes', 'Box') and not O.allowed(yes + 'Yes', 'runner'), 'a whole name only')
    check(not O.allowed(f'- [ ] **F9** a task for iFizBox — your answer (DECIDE {Q}): Yes', 'iFizBox'), 'any other task')


if __name__ == '__main__':
    raise SystemExit(report([test_route, test_copilot_link_b874, test_answers]))
